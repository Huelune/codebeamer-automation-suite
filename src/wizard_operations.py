from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import pandas as pd

from .models import PayloadStatus
from .models import UploadStatus


if TYPE_CHECKING:
    from .codebeamer_client import CodebeamerClient
    from .models import WizardState
    from .wizard_payload_cache import WizardPayloadCacheService


if TYPE_CHECKING:

    class _WizardOperationMixinSiblings:
        """조립된 뒤 형제 믹스인이 제공하는 메서드 선언이다.

        런타임에는 존재하지 않는다. 시그니처는 정의 위치에서 그대로 옮겼다.
        """

        def _build_root_item_payload(
            self, root_item_name: str, root_field_values: dict[str, Any] | None = None
        ) -> dict[str, Any]: ...

        @staticmethod
        def _concat_result_frames(frames: list[pd.DataFrame | None]) -> pd.DataFrame:
            ...

        @staticmethod
        def _filter_payload_rows(payload_df: pd.DataFrame, include_row_ids: set[int] | None) -> pd.DataFrame:
            ...

        @staticmethod
        def _http_status_code(exc: Exception) -> int | None:
            ...

        @staticmethod
        def _normalize_root_item_name(root_item_name: str | None) -> str | None:
            ...

        @classmethod
        def _normalize_top_level_parent_specs(
            cls, top_level_parent_specs: list[dict[str, Any]] | None
        ) -> tuple[list[dict[str, Any]], dict[int, str]]: ...

        @staticmethod
        def _response_json(exc: Exception) -> Any:
            ...

        @staticmethod
        def _result_count(frame: pd.DataFrame | None) -> int:
            ...

        @staticmethod
        def _unresolved_parent_error(parent_row_id: Any, *, root_item_name: str | None=None) -> str:
            ...

else:
    _WizardOperationMixinSiblings = object


class WizardOperationMixin(_WizardOperationMixinSiblings):
    # 조립된 뒤 사용할 속성의 타입 선언이다. 실제 값은
    # `CodebeamerUploadWizard.__init__` 이 채우므로 여기서는 선언만 둔다.
    client: CodebeamerClient
    logger: Any
    payload_cache: WizardPayloadCacheService
    state: WizardState

    def build_payloads(
        self,
        force: bool = False,
        *,
        fetch_existing_items: bool = True,
    ) -> pd.DataFrame:
        return self.payload_cache.build_payloads(
            force,
            fetch_existing_items=fetch_existing_items,
        )

    def preview_payload(self, row_id: int) -> dict:
        return self.payload_cache.preview_payload(row_id)

    def upload(
        self,
        dry_run: bool = False,
        continue_on_error: bool = True,
        *,
        phase_name: str = "insert",
        root_item_name: str | None = None,
        root_field_values: dict[str, Any] | None = None,
        top_level_parent_specs: list[dict[str, Any]] | None = None,
        include_row_ids: set[int] | None = None,
        existing_row_item_ids: dict[int, Any] | None = None,
        existing_parent_item_ids_by_key: dict[str, Any] | None = None,
        event_callback=None,
        cancel_requested=None,
        pause_requested=None,
    ) -> dict:
        """부모-자식 순서를 지키며 업로드를 실행하고 결과를 모아 돌려준다."""
        if self.state.tracker_id is None:
            raise ValueError("tracker_id is not set.")

        root_item_name = self._normalize_root_item_name(root_item_name)
        normalized_parent_specs, top_level_parent_name_by_row_id = self._normalize_top_level_parent_specs(
            top_level_parent_specs
        )
        payload_df = self.build_payloads()
        filtered_payload_df = self._filter_payload_rows(payload_df, include_row_ids)
        ready_df = filtered_payload_df[filtered_payload_df["payload_status"] == PayloadStatus.READY.value].copy()
        payload_failed_df = filtered_payload_df[
            filtered_payload_df["payload_status"] == PayloadStatus.FAILED.value
        ].copy()
        # 이름을 그대로 들고 있어야 아래에서 None 여부를 좁힐 수 있다.
        create_root_item_name: str | None = (
            root_item_name
            if root_item_name is not None and not ready_df.empty and not normalized_parent_specs
            else None
        )
        should_create_root_item = create_root_item_name is not None

        pending = set(ready_df["_row_id"].tolist())
        created_map = {
            int(row_id): item_id
            for row_id, item_id in dict(existing_row_item_ids or {}).items()
        }
        root_item_id = None
        top_level_parent_item_ids: dict[int, Any] = {}
        created_parent_item_ids_by_key = {
            str(key): item_id
            for key, item_id in dict(existing_parent_item_ids_by_key or {}).items()
            if str(key).strip() and item_id not in (None, "")
        }
        # dry run 에서는 실제 id 대신 placeholder 문자열이 들어온다.
        parent_item_id: Any
        for parent_spec in normalized_parent_specs:
            parent_item_id = created_parent_item_ids_by_key.get(parent_spec["key"])
            if parent_item_id is None:
                continue
            for row_id in parent_spec["row_ids"]:
                top_level_parent_item_ids[int(row_id)] = parent_item_id
        success_logs: list[Any] = []
        failed_logs = [
            {
                "_row_id": int(row["_row_id"]),
                "parent_row_id": row.get("parent_row_id"),
                "upload_name": row.get("upload_name"),
                "phase": phase_name,
                "error": row.get("payload_error"),
                "status": PayloadStatus.FAILED.value,
            }
            for _, row in payload_failed_df.iterrows()
        ]

        def _finalize(unresolved_df: pd.DataFrame) -> dict[str, Any]:
            self.state.upload_result = {
                "root_item_id": root_item_id,
                "created_map": created_map,
                "parent_item_ids_by_key": dict(created_parent_item_ids_by_key),
                "success_df": pd.DataFrame(success_logs),
                "failed_df": pd.DataFrame(failed_logs),
                "unresolved_df": unresolved_df,
            }
            return self.state.upload_result

        def _build_unresolved_df(row_df: pd.DataFrame) -> pd.DataFrame:
            unresolved_df = row_df.copy()
            if unresolved_df.empty:
                return unresolved_df
            unresolved_df["status"] = UploadStatus.UNRESOLVED_PARENT.value
            unresolved_df["phase"] = phase_name
            unresolved_df["error"] = unresolved_df.apply(
                lambda row: self._unresolved_parent_error(
                    row.get("parent_row_id"),
                    root_item_name=(
                        top_level_parent_name_by_row_id.get(int(row["_row_id"]))
                        if int(row["_row_id"]) in top_level_parent_name_by_row_id
                        else (root_item_name if should_create_root_item else None)
                    ),
                ),
                axis=1,
            )
            return unresolved_df

        if create_root_item_name is not None:
            while pause_requested is not None and pause_requested():
                time.sleep(0.1)
            if cancel_requested is not None and cancel_requested():
                return _finalize(_build_unresolved_df(ready_df))

            if event_callback is not None:
                event_callback({
                    "type": "row_started",
                    "phase": phase_name,
                    "row_id": None,
                    "upload_name": root_item_name,
                })

            try:
                root_payload = self._build_root_item_payload(
                    create_root_item_name, root_field_values=root_field_values
                )
                if dry_run:
                    result = {"id": "DRYRUN-ROOT"}
                else:
                    result = self.client.create_item(
                        tracker_id=self.state.tracker_id,
                        payload=root_payload,
                        parent_item_id=None,
                    )

                root_item_id = result["id"]
                success_logs.append({
                    "_row_id": None,
                    "parent_row_id": None,
                    "upload_name": root_item_name,
                    "phase": phase_name,
                    "created_item_id": root_item_id,
                    "status": UploadStatus.SUCCESS.value,
                })
                message = f"Row {root_item_name} uploaded successfully: item_id={root_item_id}"
                if self.logger:
                    self.logger.info(message)
                if event_callback is not None:
                    event_callback({
                        "type": "row_success",
                        "phase": phase_name,
                        "row_id": None,
                        "upload_name": root_item_name,
                        "item_id": root_item_id,
                        "message": message,
                    })
            except Exception as exc:
                error_status_code = self._http_status_code(exc)
                error_response_json = self._response_json(exc)
                error_message = str(error_response_json) if error_response_json is not None else str(exc)

                failed_logs.append({
                    "_row_id": None,
                    "parent_row_id": None,
                    "upload_name": root_item_name,
                    "phase": phase_name,
                    "error_status_code": error_status_code,
                    "error_response_json": error_response_json,
                    "error": error_message,
                    "status": UploadStatus.FAILED.value,
                })
                if event_callback is not None:
                    event_callback({
                        "type": "row_failed",
                        "phase": phase_name,
                        "row_id": None,
                        "upload_name": root_item_name,
                        "message": error_message,
                        "status_code": error_status_code,
                        "response_json": error_response_json,
                    })

                return _finalize(_build_unresolved_df(ready_df))

        if normalized_parent_specs:
            pending_parent_specs = [
                parent_spec
                for parent_spec in normalized_parent_specs
                if parent_spec["key"] not in created_parent_item_ids_by_key
            ]
            parent_attempt_index = 0

            while pending_parent_specs:
                progress = False
                deferred_parent_specs: list[dict[str, Any]] = []

                for parent_spec in pending_parent_specs:
                    parent_key = str(parent_spec.get("parent_key") or "").strip() or None
                    if parent_key is not None and parent_key not in created_parent_item_ids_by_key:
                        deferred_parent_specs.append(parent_spec)
                        continue

                    parent_attempt_index += 1
                    parent_item_parent_id = (
                        created_parent_item_ids_by_key.get(parent_key)
                        if parent_key is not None
                        else None
                    )

                    while pause_requested is not None and pause_requested():
                        time.sleep(0.1)
                    if cancel_requested is not None and cancel_requested():
                        return _finalize(
                            _build_unresolved_df(ready_df[ready_df["_row_id"].isin(sorted(pending))].copy())
                        )

                    parent_name = parent_spec["name"]
                    if event_callback is not None:
                        event_callback({
                            "type": "row_started",
                            "phase": phase_name,
                            "row_id": None,
                            "upload_name": parent_name,
                        })

                    try:
                        root_payload = self._build_root_item_payload(
                            parent_name,
                            root_field_values=parent_spec["field_values"],
                        )
                        if dry_run:
                            result = {"id": f"DRYRUN-ROOT-{parent_attempt_index}"}
                        else:
                            result = self.client.create_item(
                                tracker_id=self.state.tracker_id,
                                payload=root_payload,
                                parent_item_id=parent_item_parent_id,
                            )

                        parent_item_id = result["id"]
                        created_parent_item_ids_by_key[parent_spec["key"]] = parent_item_id
                        for row_id in parent_spec["row_ids"]:
                            top_level_parent_item_ids[int(row_id)] = parent_item_id
                        success_logs.append({
                            "_row_id": None,
                            "parent_row_id": None,
                            "upload_name": parent_name,
                            "phase": phase_name,
                            "created_item_id": parent_item_id,
                            "status": UploadStatus.SUCCESS.value,
                        })
                        message = f"Row {parent_name} uploaded successfully: item_id={parent_item_id}"
                        if self.logger:
                            self.logger.info(message)
                        if event_callback is not None:
                            event_callback({
                                "type": "row_success",
                                "phase": phase_name,
                                "row_id": None,
                                "upload_name": parent_name,
                                "item_id": parent_item_id,
                                "message": message,
                            })
                        progress = True
                    except Exception as exc:
                        error_status_code = self._http_status_code(exc)
                        error_response_json = self._response_json(exc)
                        error_message = str(error_response_json) if error_response_json is not None else str(exc)

                        failed_logs.append(
                            {
                                "_row_id": None,
                                "parent_row_id": None,
                                "upload_name": parent_name,
                                "phase": phase_name,
                                "error_status_code": error_status_code,
                                "error_response_json": error_response_json,
                                "error": error_message,
                                "status": UploadStatus.FAILED.value,
                            }
                        )
                        if event_callback is not None:
                            event_callback(
                                {
                                    "type": "row_failed",
                                    "phase": phase_name,
                                    "row_id": None,
                                    "upload_name": parent_name,
                                    "message": error_message,
                                    "status_code": error_status_code,
                                    "response_json": error_response_json,
                                }
                            )

                        if not continue_on_error:
                            return _finalize(
                                _build_unresolved_df(ready_df[ready_df["_row_id"].isin(sorted(pending))].copy())
                            )

                if progress:
                    pending_parent_specs = deferred_parent_specs
                    continue

                for parent_spec in deferred_parent_specs:
                    missing_parent_key = str(parent_spec.get("parent_key") or "").strip()
                    error_message = (
                        f"Top-level parent {parent_spec['name']!r} requires unavailable parent {missing_parent_key!r}."
                    )
                    failed_logs.append({
                        "_row_id": None,
                        "parent_row_id": None,
                        "upload_name": parent_spec["name"],
                        "phase": phase_name,
                        "error": error_message,
                        "status": UploadStatus.UNRESOLVED_PARENT.value,
                    })
                    if event_callback is not None:
                        event_callback({
                            "type": "row_failed",
                            "phase": phase_name,
                            "row_id": None,
                            "upload_name": parent_spec["name"],
                            "message": error_message,
                        })
                break

        while pending:
            progress = False

            for _, row in ready_df.iterrows():
                row_id = int(row["_row_id"])
                if row_id not in pending:
                    continue

                while pause_requested is not None and pause_requested():
                    time.sleep(0.1)
                if cancel_requested is not None and cancel_requested():
                    break

                parent_row_id = row["parent_row_id"]
                if parent_row_id is None or pd.isna(parent_row_id):
                    if normalized_parent_specs:
                        if row_id in top_level_parent_item_ids:
                            parent_item_id = top_level_parent_item_ids[row_id]
                        elif row_id in top_level_parent_name_by_row_id:
                            continue
                        else:
                            parent_item_id = None
                    else:
                        parent_item_id = root_item_id if should_create_root_item else None
                else:
                    parent_row_id = int(parent_row_id)
                    if parent_row_id not in created_map:
                        continue
                    parent_item_id = created_map[parent_row_id]

                try:
                    payload = row["payload_json"]
                    if event_callback is not None:
                        event_callback({
                            "type": "row_started",
                            "phase": phase_name,
                            "row_id": row_id,
                            "upload_name": row["upload_name"],
                        })

                    if dry_run:
                        result = {"id": f"DRYRUN-{row_id}"}
                    else:
                        result = self.client.create_item(
                            tracker_id=self.state.tracker_id,
                            payload=payload,
                            parent_item_id=parent_item_id,
                        )

                    created_map[row_id] = result["id"]
                    pending.remove(row_id)
                    progress = True

                    success_logs.append({
                        "_row_id": row_id,
                        "parent_row_id": row["parent_row_id"],
                        "upload_name": row["upload_name"],
                        "phase": phase_name,
                        "created_item_id": result["id"],
                        "status": UploadStatus.SUCCESS.value,
                    })
                    message = f"Row {row['upload_name']} uploaded successfully: item_id={result['id']}"
                    if self.logger:
                        self.logger.info(message)
                    if event_callback is not None:
                        event_callback({
                            "type": "row_success",
                            "phase": phase_name,
                            "row_id": row_id,
                            "upload_name": row["upload_name"],
                            "item_id": result["id"],
                            "message": message,
                        })

                except Exception as exc:
                    error_status_code = self._http_status_code(exc)
                    error_response_json = self._response_json(exc)
                    error_message = ""
                    error_message = str(error_response_json) if error_response_json is not None else str(exc)

                    failed_logs.append({
                        "_row_id": row_id,
                        "parent_row_id": row["parent_row_id"],
                        "upload_name": row["upload_name"],
                        "phase": phase_name,
                        "error_status_code": error_status_code,
                        "error_response_json": error_response_json,
                        "error": error_message,
                        "status": UploadStatus.FAILED.value,
                    })
                    if event_callback is not None:
                        event_callback({
                            "type": "row_failed",
                            "phase": phase_name,
                            "row_id": row_id,
                            "upload_name": row["upload_name"],
                            "message": error_message,
                            "status_code": error_status_code,
                            "response_json": error_response_json,
                        })

                    if not continue_on_error:
                        return _finalize(ready_df[ready_df["_row_id"].isin(sorted(pending))].copy())

                    pending.remove(row_id)
                    progress = True

            if not progress:
                break
            if cancel_requested is not None and cancel_requested():
                break

        return _finalize(_build_unresolved_df(ready_df[ready_df["_row_id"].isin(sorted(pending))].copy()))

    def update_items(
        self,
        dry_run: bool = False,
        continue_on_error: bool = True,
        *,
        phase_name: str = "update",
        include_row_ids: set[int] | None = None,
        fetch_existing_items: bool = True,
        event_callback=None,
        cancel_requested=None,
        pause_requested=None,
    ) -> dict[str, Any]:
        """대상 item id를 기준으로 PUT 업데이트를 실행하고 결과를 모아 돌려준다."""
        if self.state.tracker_id is None:
            raise ValueError("tracker_id is not set.")

        payload_df = self.build_payloads(
            force=bool(fetch_existing_items),
            fetch_existing_items=fetch_existing_items,
        )
        filtered_payload_df = self._filter_payload_rows(payload_df, include_row_ids)
        ready_df = filtered_payload_df[filtered_payload_df["payload_status"] == PayloadStatus.READY.value].copy()
        payload_failed_df = filtered_payload_df[
            filtered_payload_df["payload_status"] == PayloadStatus.FAILED.value
        ].copy()

        success_logs: list[dict[str, Any]] = []
        failed_logs = [
            {
                "_row_id": int(row["_row_id"]),
                "parent_row_id": row.get("parent_row_id"),
                "upload_name": row.get("upload_name"),
                "phase": phase_name,
                "target_item_id": row.get("_target_item_id"),
                "error": row.get("payload_error"),
                "status": PayloadStatus.FAILED.value,
            }
            for _, row in payload_failed_df.iterrows()
        ]

        def _finalize(unresolved_df: pd.DataFrame) -> dict[str, Any]:
            self.state.upload_result = {
                "root_item_id": None,
                "created_map": {},
                "success_df": pd.DataFrame(success_logs),
                "failed_df": pd.DataFrame(failed_logs),
                "unresolved_df": unresolved_df,
            }
            return self.state.upload_result

        pending_row_ids = ready_df["_row_id"].tolist()

        for current_index, (_, row) in enumerate(ready_df.iterrows()):
            while pause_requested is not None and pause_requested():
                time.sleep(0.1)
            if cancel_requested is not None and cancel_requested():
                break

            row_id = int(row["_row_id"])
            pending_row_ids = [value for value in pending_row_ids if value != row_id]
            target_item_id = int(row["_target_item_id"])

            try:
                if event_callback is not None:
                    event_callback({
                        "type": "row_started",
                        "phase": phase_name,
                        "row_id": row_id,
                        "upload_name": row["upload_name"],
                        "item_id": target_item_id,
                    })

                if dry_run:
                    result = {"id": target_item_id}
                else:
                    result = self.client.update_item(
                        target_item_id,
                        row["payload_json"],
                    )

                success_logs.append({
                    "_row_id": row_id,
                    "parent_row_id": row.get("parent_row_id"),
                    "upload_name": row.get("upload_name"),
                    "phase": phase_name,
                    "target_item_id": target_item_id,
                    "updated_item_id": result.get("id", target_item_id),
                    "status": UploadStatus.SUCCESS.value,
                })
                message = f"Row {row['upload_name']} updated successfully: item_id={target_item_id}"
                if event_callback is not None:
                    event_callback({
                        "type": "row_success",
                        "phase": phase_name,
                        "row_id": row_id,
                        "upload_name": row["upload_name"],
                        "item_id": target_item_id,
                        "message": message,
                    })
            except Exception as exc:
                error_status_code = self._http_status_code(exc)
                error_response_json = self._response_json(exc)
                error_message = str(error_response_json) if error_response_json is not None else str(exc)

                failed_logs.append({
                    "_row_id": row_id,
                    "parent_row_id": row.get("parent_row_id"),
                    "upload_name": row.get("upload_name"),
                    "phase": phase_name,
                    "target_item_id": target_item_id,
                    "error_status_code": error_status_code,
                    "error_response_json": error_response_json,
                    "error": error_message,
                    "status": UploadStatus.FAILED.value,
                })
                if event_callback is not None:
                    event_callback({
                        "type": "row_failed",
                        "phase": phase_name,
                        "row_id": row_id,
                        "upload_name": row["upload_name"],
                        "item_id": target_item_id,
                        "message": error_message,
                        "status_code": error_status_code,
                        "response_json": error_response_json,
                    })

                if not continue_on_error:
                    unresolved_df = ready_df.iloc[current_index + 1 :].copy()
                    if not unresolved_df.empty:
                        unresolved_df["phase"] = phase_name
                        unresolved_df["status"] = UploadStatus.UNRESOLVED_PARENT.value
                        unresolved_df["error"] = "이전 업데이트 실패로 실행이 중단되었습니다."
                    return _finalize(unresolved_df)

        unresolved_df = ready_df[ready_df["_row_id"].isin(pending_row_ids)].copy()
        if not unresolved_df.empty:
            unresolved_df["phase"] = phase_name
            unresolved_df["status"] = UploadStatus.UNRESOLVED_PARENT.value
            unresolved_df["error"] = "업데이트가 완료되지 않았습니다."

        return _finalize(unresolved_df)

    def upsert_items(
        self,
        dry_run: bool = False,
        continue_on_error: bool = True,
        *,
        top_level_parent_specs: list[dict[str, Any]] | None = None,
        event_callback=None,
        cancel_requested=None,
        pause_requested=None,
    ) -> dict[str, Any]:
        """id가 있는 행은 update, 없는 행은 create로 나누어 한 번에 실행한다."""
        if self.state.tracker_id is None:
            raise ValueError("tracker_id is not set.")

        payload_df = self.build_payloads(force=True, fetch_existing_items=False)
        if payload_df.empty:
            self.state.upload_result = {
                "root_item_id": None,
                "created_map": {},
                "parent_item_ids_by_key": {},
                "success_df": pd.DataFrame(),
                "failed_df": pd.DataFrame(),
                "unresolved_df": pd.DataFrame(),
                "phase_results": {},
            }
            return self.state.upload_result

        operation_series = payload_df.get("_operation", pd.Series(dtype=object)).fillna("").astype(str)
        create_row_ids = {
            int(row_id)
            for row_id in payload_df[operation_series.eq("create")]["_row_id"].tolist()
        }
        update_row_ids = {
            int(row_id)
            for row_id in payload_df[operation_series.eq("update")]["_row_id"].tolist()
        }
        seeded_existing_row_item_ids = {
            int(row["_row_id"]): int(row["_target_item_id"])
            for _, row in payload_df[
                payload_df["payload_status"].eq(PayloadStatus.READY.value)
                & operation_series.eq("update")
                & payload_df["_target_item_id"].notna()
            ].iterrows()
        }

        root_item_id = None
        created_map = dict(seeded_existing_row_item_ids)
        parent_item_ids_by_key: dict[str, Any] = {}
        update_payload_prepared = False
        success_frames: list[pd.DataFrame | None] = []
        failed_frames: list[pd.DataFrame | None] = []
        unresolved_frames: list[pd.DataFrame | None] = []
        phase_results: dict[str, dict[str, int]] = {}

        def _emit_phase_started(phase: str, total: int) -> None:
            if event_callback is None:
                return
            event_callback({
                "type": "phase_started",
                "phase": phase,
                "total": int(max(total, 0)),
            })

        def _emit_phase_finished(phase: str, result: dict[str, Any]) -> None:
            success_count = self._result_count(result.get("success_df"))
            failed_count = self._result_count(result.get("failed_df"))
            unresolved_count = self._result_count(result.get("unresolved_df"))
            phase_results[phase] = {
                "total": success_count + failed_count + unresolved_count,
                "success": success_count,
                "failed": failed_count,
                "unresolved": unresolved_count,
            }
            if event_callback is None:
                return
            event_callback({
                "type": "phase_finished",
                "phase": phase,
                "total": phase_results[phase]["total"],
                "success": success_count,
                "failed": failed_count,
                "unresolved": unresolved_count,
            })

        create_result: dict[str, Any] | None = None
        if create_row_ids:
            _emit_phase_started("insert", len(create_row_ids))
            create_result = self.upload(
                dry_run=dry_run,
                continue_on_error=continue_on_error,
                phase_name="insert",
                top_level_parent_specs=top_level_parent_specs,
                include_row_ids=create_row_ids,
                existing_row_item_ids=seeded_existing_row_item_ids,
                event_callback=event_callback,
                cancel_requested=cancel_requested,
                pause_requested=pause_requested,
            )
            _emit_phase_finished("insert", create_result)
            root_item_id = create_result.get("root_item_id")
            created_map.update(create_result.get("created_map", {}))
            parent_item_ids_by_key.update(
                create_result.get("parent_item_ids_by_key", {})
            )
            success_frames.append(create_result.get("success_df"))
            failed_frames.append(create_result.get("failed_df"))
            unresolved_frames.append(create_result.get("unresolved_df"))

            create_failed_df = create_result.get("failed_df")
            create_unresolved_df = create_result.get("unresolved_df")
            cancelled_after_create = bool(
                cancel_requested is not None and cancel_requested()
            )
            should_stop_before_update = (
                not continue_on_error
                and isinstance(create_failed_df, pd.DataFrame)
                and not create_failed_df.empty
            ) or (
                not continue_on_error
                and isinstance(create_unresolved_df, pd.DataFrame)
                and not create_unresolved_df.empty
            ) or cancelled_after_create
            if should_stop_before_update:
                skipped_update_df = payload_df[
                    payload_df["_row_id"].isin(sorted(update_row_ids))
                ].copy()
                if not skipped_update_df.empty:
                    skipped_update_df["phase"] = "update"
                    skipped_update_df["status"] = UploadStatus.UNRESOLVED_PARENT.value
                    skipped_update_df["error"] = (
                        "사용자 중단 요청으로 아직 수정 요청을 실행하지 않았습니다."
                        if cancelled_after_create
                        else "생성 단계 실패로 아직 수정 요청을 실행하지 않았습니다."
                    )
                    unresolved_frames.append(skipped_update_df)
                    phase_results["update"] = {
                        "total": len(skipped_update_df),
                        "success": 0,
                        "failed": 0,
                        "unresolved": len(skipped_update_df),
                    }
                self.state.upload_result = {
                    "root_item_id": root_item_id,
                    "created_map": created_map,
                    "parent_item_ids_by_key": parent_item_ids_by_key,
                    "update_payload_prepared": update_payload_prepared,
                    "success_df": self._concat_result_frames(success_frames),
                    "failed_df": self._concat_result_frames(failed_frames),
                    "unresolved_df": self._concat_result_frames(unresolved_frames),
                    "phase_results": phase_results,
                }
                return self.state.upload_result

        if update_row_ids:
            _emit_phase_started("update", len(update_row_ids))
            update_result = self.update_items(
                dry_run=dry_run,
                continue_on_error=continue_on_error,
                phase_name="update",
                include_row_ids=update_row_ids,
                fetch_existing_items=True,
                event_callback=event_callback,
                cancel_requested=cancel_requested,
                pause_requested=pause_requested,
            )
            update_payload_prepared = True
            _emit_phase_finished("update", update_result)
            success_frames.append(update_result.get("success_df"))
            failed_frames.append(update_result.get("failed_df"))
            unresolved_frames.append(update_result.get("unresolved_df"))

        self.state.upload_result = {
            "root_item_id": root_item_id,
            "created_map": created_map,
            "parent_item_ids_by_key": parent_item_ids_by_key,
            "update_payload_prepared": update_payload_prepared,
            "success_df": self._concat_result_frames(success_frames),
            "failed_df": self._concat_result_frames(failed_frames),
            "unresolved_df": self._concat_result_frames(unresolved_frames),
            "phase_results": phase_results,
        }
        return self.state.upload_result

    def save_state(self, output_dir: str) -> None:
        """현재 세션의 DataFrame, schema, 결과를 파일로 저장한다."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        frames = {
            "raw_df.csv": self.state.raw_df,
            "merged_df.csv": self.state.merged_df,
            "hierarchy_df.csv": self.state.hierarchy_df,
            "upload_df.csv": self.state.upload_df,
            "converted_upload_df.csv": self.state.converted_upload_df,
            "payload_df.csv": self.state.payload_df,
            "schema_df.csv": self.state.schema_df,
            "comparison_df.csv": self.state.comparison_df,
            "option_check_df.csv": self.state.option_check_df,
        }

        for name, df in frames.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                csv_df = df.copy()
                if "payload_json" in csv_df.columns:
                    csv_df["payload_json"] = csv_df["payload_json"].apply(
                        lambda payload: (
                            json.dumps(payload, ensure_ascii=False)
                            if payload is not None
                            else None
                        )
                    )
                csv_df.to_csv(out / name, index=False)

        if self.state.schema is not None:
            with open(out / "schema.json", "w", encoding="utf-8") as file:
                json.dump(self.state.schema, file, ensure_ascii=False, indent=2)

        if self.state.option_maps is not None:
            with open(out / "option_maps.json", "w", encoding="utf-8") as file:
                json.dump(self.state.option_maps, file, ensure_ascii=False, indent=2)

        if self.state.selected_mapping:
            with open(out / "selected_mapping.json", "w", encoding="utf-8") as file:
                json.dump(self.state.selected_mapping, file, ensure_ascii=False, indent=2)

        if self.state.selected_mapping_modes:
            with open(out / "selected_mapping_modes.json", "w", encoding="utf-8") as file:
                json.dump(self.state.selected_mapping_modes, file, ensure_ascii=False, indent=2)

        if self.state.selected_default_values:
            with open(out / "selected_default_values.json", "w", encoding="utf-8") as file:
                json.dump(self.state.selected_default_values, file, ensure_ascii=False, indent=2)

        if self.state.selected_default_value_modes:
            with open(out / "selected_default_value_modes.json", "w", encoding="utf-8") as file:
                json.dump(self.state.selected_default_value_modes, file, ensure_ascii=False, indent=2)

        if self.state.resolved_default_values:
            with open(out / "resolved_default_values.json", "w", encoding="utf-8") as file:
                json.dump(self.state.resolved_default_values, file, ensure_ascii=False, indent=2)

        if isinstance(self.state.payload_df, pd.DataFrame) and not self.state.payload_df.empty:
            with open(out / "payload_preview.jsonl", "w", encoding="utf-8") as file:
                for _, row in self.state.payload_df.iterrows():
                    file.write(json.dumps({
                        "_row_id": row.get("_row_id"),
                        "parent_row_id": row.get("parent_row_id"),
                        "upload_name": row.get("upload_name"),
                        "payload_status": row.get("payload_status"),
                        "payload_error": row.get("payload_error"),
                        "payload_json": row.get("payload_json"),
                    }, ensure_ascii=False))
                    file.write("\n")

        if self.state.upload_result is not None:
            for key in ["success_df", "failed_df", "unresolved_df"]:
                df = self.state.upload_result.get(key)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    csv_df = df.copy()
                    if "error_response_json" in csv_df.columns:
                        csv_df["error_response_json"] = csv_df["error_response_json"].apply(
                            lambda payload: (
                                json.dumps(payload, ensure_ascii=False)
                                if payload is not None
                                else None
                            )
                        )
                    csv_df.to_csv(out / f"{key}.csv", index=False)

            failed_df = self.state.upload_result.get("failed_df")
            if isinstance(failed_df, pd.DataFrame) and not failed_df.empty:
                with open(out / "failed_responses.jsonl", "w", encoding="utf-8") as file:
                    for _, row in failed_df.iterrows():
                        file.write(json.dumps({
                            "_row_id": row.get("_row_id"),
                            "parent_row_id": row.get("parent_row_id"),
                            "upload_name": row.get("upload_name"),
                            "error_status_code": row.get("error_status_code"),
                            "error_response_json": row.get("error_response_json"),
                            "error": row.get("error"),
                            "status": row.get("status"),
                        }, ensure_ascii=False))
                        file.write("\n")

            with open(out / "created_map.json", "w", encoding="utf-8") as file:
                json.dump(self.state.upload_result.get("created_map", {}), file, ensure_ascii=False, indent=2)
