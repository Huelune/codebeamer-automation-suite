from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from src.models import PayloadStatus
from src.models import UploadStatus
from src.upload_pipeline import load_tracker_schema_df
from src.upload_pipeline import prepare_upload_dataframe
from src.upload_policy import UPLOAD_MODE_CREATE as GUI_UPLOAD_MODE_CREATE
from src.upload_policy import UPLOAD_MODE_UPDATE as GUI_UPLOAD_MODE_UPDATE
from src.upload_policy import UPLOAD_MODE_UPSERT as GUI_UPLOAD_MODE_UPSERT
from src.upload_policy import normalize_upload_mode as normalize_gui_upload_mode
from src.upload_policy import upload_mode_action_label as gui_upload_mode_action_label
from src.upload_policy import upload_mode_allows_root_items as gui_upload_mode_allows_root_items
from src.upload_policy import upload_mode_supports_update as gui_upload_mode_supports_update
from src.wizard import CodebeamerUploadWizard

from .batch_validation import BatchValidationService
from .root_item_service import RootItemService
from .upload_context import BatchUploadJob
from .upload_context import FailedUploadRetryContext
from .upload_context import FailedUploadRetryJob
from .upload_context import MappingContext
from .upload_context import RootItemUploadSpec


def _build_file_scoped_event_forwarder(
    *,
    file_label: str,
    file_path: str,
    emit: Callable[[dict[str, Any]], None],
) -> Callable[[dict[str, Any]], None]:
    """업로드 이벤트에 파일 정보를 붙여 전달하는 콜백을 만든다.

    반복문 안에서 콜백을 직접 정의하면 루프 변수를 늦게 바인딩하므로
    파일별 값을 인자로 고정한 별도 함수로 만든다.
    """

    def forward(event: dict[str, Any]) -> None:
        forwarded = dict(event)
        forwarded["source_file"] = file_label
        forwarded["source_file_path"] = file_path

        upload_name = str(forwarded.get("upload_name") or "").strip()
        forwarded["upload_name"] = (
            f"[{file_label}] {upload_name}" if upload_name else f"[{file_label}]"
        )

        message = str(forwarded.get("message") or "").strip()
        if message:
            forwarded["message"] = f"[{file_label}] {message}"

        emit(forwarded)

    return forward


class BatchUploadService:
    """파일별 wizard 준비, 진행 제어와 batch upload 결과 집계를 담당한다."""

    def __init__(
        self,
        *,
        mapper: Any,
        create_wizard: Callable[[Any], CodebeamerUploadWizard],
        root_items: RootItemService,
        batch_validation: BatchValidationService,
    ) -> None:
        self.mapper = mapper
        self.create_wizard = create_wizard
        self.root_items = root_items
        self.batch_validation = batch_validation

    @staticmethod
    def _normalize_file_paths(file_state: dict[str, Any]) -> list[str]:
        return BatchValidationService._normalize_file_paths(file_state)

    def _cached_raw_df_for_file(
        self,
        preview_data: Any,
        file_path: str,
    ) -> pd.DataFrame | None:
        return self.batch_validation._cached_raw_df_for_file(preview_data, file_path)

    def build_root_item_payload_specs(
        self,
        mapping_context: MappingContext,
        wizard: CodebeamerUploadWizard,
        file_path: str,
    ) -> list[RootItemUploadSpec]:
        return self.root_items.build_root_item_payload_specs(
            mapping_context,
            wizard,
            file_path,
        )

    @staticmethod
    def _batch_output_dir(output_dir: str, file_path: str, index: int) -> str:
        safe_name = Path(file_path).stem.strip() or f"file_{index:03d}"
        return str(Path(output_dir) / f"{index:03d}_{safe_name}")

    @staticmethod
    def _ready_upload_count(
        wizard: CodebeamerUploadWizard,
        root_item_specs: list[RootItemUploadSpec] | None = None,
    ) -> int:
        insert_count, update_count = BatchUploadService._phase_ready_counts(
            wizard,
            root_item_specs=root_item_specs,
        )
        return insert_count + update_count

    @staticmethod
    def _phase_ready_counts(
        wizard: CodebeamerUploadWizard,
        root_item_specs: list[RootItemUploadSpec] | None = None,
    ) -> tuple[int, int]:
        payload_df = wizard.state.payload_df if wizard.state.payload_df is not None else wizard.build_payloads()
        if payload_df is None or payload_df.empty:
            return (0, 0)

        ready_df = payload_df[payload_df["payload_status"] == PayloadStatus.READY.value].copy()
        upload_mode = normalize_gui_upload_mode(getattr(wizard.state, "upload_mode", GUI_UPLOAD_MODE_CREATE))
        if ready_df.empty:
            return (0, 0)

        if upload_mode == GUI_UPLOAD_MODE_UPDATE:
            return (0, len(ready_df))

        if upload_mode == GUI_UPLOAD_MODE_UPSERT and "_operation" in ready_df.columns:
            operation_series = ready_df["_operation"].fillna("").astype(str).str.lower()
            insert_count = int(operation_series.eq("create").sum())
            update_count = int(operation_series.eq("update").sum())
            if insert_count > 0 and root_item_specs:
                insert_count += len(root_item_specs)
            return (insert_count, update_count)

        insert_count = len(ready_df)
        if (
            insert_count > 0
            and root_item_specs
            and gui_upload_mode_allows_root_items(upload_mode)
        ):
            insert_count += len(root_item_specs)
        return (insert_count, 0)

    @staticmethod
    def _annotate_batch_result_frame(
        df: pd.DataFrame | None,
        *,
        file_label: str,
        file_path: str,
    ) -> pd.DataFrame:
        return BatchValidationService._annotate_source_frame(
            df,
            file_label=file_label,
            file_path=file_path,
        )

    @staticmethod
    def _root_item_spec_dicts(
        root_item_specs: list[RootItemUploadSpec],
    ) -> list[dict[str, Any]]:
        return [
            {
                "key": spec.key,
                "name": spec.name,
                "field_values": dict(spec.field_values),
                "row_ids": list(spec.row_ids),
                "parent_key": spec.parent_key,
                "kind": spec.kind,
            }
            for spec in root_item_specs
        ]

    @staticmethod
    def _frame_row_ids(df: pd.DataFrame | None) -> set[int]:
        if not isinstance(df, pd.DataFrame) or df.empty or "_row_id" not in df.columns:
            return set()
        row_ids: set[int] = set()
        for value in df["_row_id"].tolist():
            try:
                if value is None or pd.isna(value):
                    continue
                row_ids.add(int(value))
            except (TypeError, ValueError):
                continue
        return row_ids

    @staticmethod
    def _ready_payload_row_ids(wizard: CodebeamerUploadWizard) -> set[int]:
        payload_df = wizard.state.payload_df
        if not isinstance(payload_df, pd.DataFrame) or payload_df.empty:
            return set()
        ready_df = payload_df[
            payload_df["payload_status"].eq(PayloadStatus.READY.value)
        ]
        return {int(row_id) for row_id in ready_df["_row_id"].tolist()}

    @classmethod
    def _build_retry_job(
        cls,
        job: BatchUploadJob | FailedUploadRetryJob,
        *,
        upload_mode: str,
        failed_df: pd.DataFrame,
        unresolved_df: pd.DataFrame,
        created_row_item_ids: dict[Any, Any],
        created_parent_item_ids_by_key: dict[str, Any],
        update_payload_prepared: bool | None = None,
    ) -> FailedUploadRetryJob | None:
        candidate_row_ids = cls._frame_row_ids(failed_df) | cls._frame_row_ids(
            unresolved_df
        )
        retry_row_ids = candidate_row_ids & cls._ready_payload_row_ids(job.wizard)
        known_parent_keys = {
            str(key)
            for key, item_id in dict(created_parent_item_ids_by_key or {}).items()
            if str(key).strip() and item_id not in (None, "")
        }
        retry_root_keys: set[str] = set()
        if retry_row_ids or not failed_df.empty or not unresolved_df.empty:
            retry_root_keys = {
                str(spec.key)
                for spec in job.root_item_specs
                if str(spec.key) not in known_parent_keys
            }
        if not retry_row_ids and not retry_root_keys:
            return None
        return FailedUploadRetryJob(
            file_path=job.file_path,
            file_label=job.file_label,
            root_item_specs=list(job.root_item_specs),
            output_dir=job.output_dir,
            wizard=job.wizard,
            upload_mode=upload_mode,
            retry_row_ids=set(retry_row_ids),
            retry_root_keys=set(retry_root_keys),
            created_row_item_ids={
                int(row_id): item_id
                for row_id, item_id in dict(created_row_item_ids or {}).items()
            },
            created_parent_item_ids_by_key={
                str(key): item_id
                for key, item_id in dict(created_parent_item_ids_by_key or {}).items()
            },
            update_payload_prepared=(
                bool(update_payload_prepared)
                if update_payload_prepared is not None
                else bool(getattr(job, "update_payload_prepared", True))
            ),
        )

    @staticmethod
    def _retry_target_mask(
        df: pd.DataFrame | None,
        job: FailedUploadRetryJob,
    ) -> pd.Series:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.Series(dtype=bool)
        source_mask = pd.Series(True, index=df.index, dtype=bool)
        if "source_file_path" in df.columns:
            source_mask = df["source_file_path"].fillna("").astype(str).eq(
                job.file_path
            )
        row_mask = pd.Series(False, index=df.index, dtype=bool)
        if "_row_id" in df.columns and job.retry_row_ids:
            normalized_row_ids = pd.to_numeric(df["_row_id"], errors="coerce")
            row_mask = normalized_row_ids.isin(sorted(job.retry_row_ids))
        root_names = {
            spec.name
            for spec in job.root_item_specs
            if spec.key in job.retry_root_keys
        }
        root_mask = pd.Series(False, index=df.index, dtype=bool)
        if root_names and "_row_id" in df.columns and "upload_name" in df.columns:
            root_mask = df["_row_id"].isna() & df["upload_name"].fillna("").astype(
                str
            ).isin(root_names)
        return source_mask & (row_mask | root_mask)

    @classmethod
    def _drop_retry_targets(
        cls,
        df: pd.DataFrame,
        job: FailedUploadRetryJob,
    ) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame() if df is None else df.copy()
        return df.loc[~cls._retry_target_mask(df, job)].copy()

    @staticmethod
    def _retry_job_subset(
        job: FailedUploadRetryJob,
        *,
        retry_row_ids: set[int],
        retry_root_keys: set[str],
    ) -> FailedUploadRetryJob:
        return FailedUploadRetryJob(
            file_path=job.file_path,
            file_label=job.file_label,
            root_item_specs=list(job.root_item_specs),
            output_dir=job.output_dir,
            wizard=job.wizard,
            upload_mode=job.upload_mode,
            retry_row_ids=set(retry_row_ids),
            retry_root_keys=set(retry_root_keys),
            created_row_item_ids=dict(job.created_row_item_ids),
            created_parent_item_ids_by_key=dict(
                job.created_parent_item_ids_by_key
            ),
            update_payload_prepared=bool(job.update_payload_prepared),
        )

    @staticmethod
    def _source_result_frame(
        df: pd.DataFrame,
        *,
        file_path: str,
    ) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame()
        if "source_file_path" not in df.columns:
            return df.copy()
        return df.loc[
            df["source_file_path"].fillna("").astype(str).eq(file_path)
        ].copy()

    @staticmethod
    def _concat_frames(frames: list[pd.DataFrame | None]) -> pd.DataFrame:
        valid = [
            frame
            for frame in frames
            if isinstance(frame, pd.DataFrame) and not frame.empty
        ]
        if not valid:
            return pd.DataFrame()
        return pd.concat(valid, ignore_index=True)

    @classmethod
    def _non_retryable_result_count(
        cls,
        failed_df: pd.DataFrame,
        unresolved_df: pd.DataFrame,
        retry_jobs: list[FailedUploadRetryJob],
    ) -> int:
        remaining = cls._concat_frames([failed_df, unresolved_df])
        for retry_job in retry_jobs:
            remaining = cls._drop_retry_targets(remaining, retry_job)
        return len(remaining.index)

    @classmethod
    def _phase_results_from_frames(
        cls,
        success_df: pd.DataFrame,
        failed_df: pd.DataFrame,
        unresolved_df: pd.DataFrame,
    ) -> dict[str, dict[str, int]]:
        phase_results: dict[str, dict[str, int]] = {}
        for phase_name in ("insert", "update"):
            counts: dict[str, int] = {}
            for key, frame in (
                ("success", success_df),
                ("failed", failed_df),
                ("unresolved", unresolved_df),
            ):
                if not isinstance(frame, pd.DataFrame) or frame.empty or "phase" not in frame.columns:
                    counts[key] = 0
                    continue
                counts[key] = int(
                    frame["phase"]
                    .fillna("")
                    .astype(str)
                    .str.lower()
                    .eq(phase_name)
                    .sum()
                )
            counts["total"] = counts["success"] + counts["failed"] + counts["unresolved"]
            phase_results[phase_name] = counts
        return phase_results

    @classmethod
    def _unattempted_job_frame(
        cls,
        job: BatchUploadJob,
        *,
        upload_mode: str,
        reason: str,
    ) -> pd.DataFrame:
        """실행하지 않은 READY 행을 결과와 세션 재시도 대상으로 남긴다."""
        payload_df = getattr(job.wizard.state, "payload_df", None)
        if not isinstance(payload_df, pd.DataFrame) or payload_df.empty:
            return pd.DataFrame()
        if "payload_status" not in payload_df.columns:
            return pd.DataFrame()
        pending = payload_df.loc[
            payload_df["payload_status"].eq(PayloadStatus.READY.value)
        ].copy()
        if pending.empty:
            return pd.DataFrame()
        if upload_mode == GUI_UPLOAD_MODE_UPDATE:
            pending["phase"] = "update"
        elif upload_mode == GUI_UPLOAD_MODE_UPSERT and "_operation" in pending.columns:
            pending["phase"] = (
                pending["_operation"]
                .fillna("")
                .astype(str)
                .str.lower()
                .map({"create": "insert", "update": "update"})
                .fillna("insert")
            )
        else:
            pending["phase"] = "insert"
        pending["status"] = UploadStatus.UNRESOLVED_PARENT.value
        pending["error"] = str(reason)
        return cls._annotate_batch_result_frame(
            pending,
            file_label=job.file_label,
            file_path=job.file_path,
        )

    def _prepare_wizard_for_file(
        self,
        settings,
        mapping_context: MappingContext,
        *,
        file_path: str,
        sheet_name: str,
        header_row: int,
        summary_col: str,
    ) -> CodebeamerUploadWizard:
        wizard = self.create_wizard(settings)
        wizard.select_project(int(settings.default_project_id))
        wizard.select_tracker(int(settings.default_tracker_id))
        wizard.state.upload_mode = normalize_gui_upload_mode(mapping_context.upload_mode)

        schema = mapping_context.wizard.state.schema
        if schema is None:
            schema, _ = load_tracker_schema_df(wizard)
        schema_df = mapping_context.schema_df

        prepare_upload_dataframe(
            wizard,
            file_path=file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_col=summary_col,
            selected_mapping=mapping_context.selected_mapping,
            schema=schema,
            schema_df=schema_df,
            raw_df=self._cached_raw_df_for_file(mapping_context.preview_data, file_path),
        )

        wizard.state.selected_mapping = dict(mapping_context.selected_mapping)
        wizard.state.selected_mapping_modes = {
            str(key): dict(value)
            for key, value in dict(mapping_context.selected_mapping_modes or {}).items()
            if str(key).strip() and isinstance(value, dict)
        }
        wizard.state.schema = schema
        wizard.state.schema_df = schema_df
        wizard.state.selected_default_value_modes = {
            str(key): dict(value)
            for key, value in dict(mapping_context.selected_default_value_modes or {}).items()
            if str(key).strip() and isinstance(value, dict)
        }
        wizard.state.selected_tracker_item_settings = dict(mapping_context.selected_tracker_item_settings)
        wizard.state.user_lookup_cache = dict(mapping_context.user_lookup_cache)
        wizard.state.member_lookup_cache = dict(mapping_context.member_lookup_cache)
        wizard.state.group_lookup_cache = dict(mapping_context.group_lookup_cache)
        wizard.state.tracker_role_cache = dict(mapping_context.tracker_role_cache)
        wizard.state.tracker_item_lookup_cache = dict(mapping_context.tracker_item_lookup_cache)
        wizard.state.existing_item_cache = {}
        wizard.state.comparison_df = wizard.mapper.compare_upload_df_with_schema(
            upload_df=wizard.state.upload_df,
            schema_df=schema_df,
            selected_mapping=wizard.state.selected_mapping,
        )
        wizard._detect_table_field_columns()
        wizard.process_option_mapping(
            wizard.state.selected_mapping,
            selected_mapping_modes=wizard.state.selected_mapping_modes,
            selected_default_values=mapping_context.selected_default_values,
            selected_default_value_modes=wizard.state.selected_default_value_modes,
            selected_tracker_item_settings=mapping_context.selected_tracker_item_settings,
        )
        wizard.build_payloads(
            force=True,
            fetch_existing_items=not gui_upload_mode_supports_update(mapping_context.upload_mode),
        )
        mapping_context.user_lookup_cache = dict(wizard.state.user_lookup_cache)
        mapping_context.member_lookup_cache = dict(wizard.state.member_lookup_cache)
        mapping_context.group_lookup_cache = dict(wizard.state.group_lookup_cache)
        mapping_context.tracker_role_cache = dict(wizard.state.tracker_role_cache)
        return wizard

    def run_batch_upload(
        self,
        settings,
        file_state: dict[str, Any],
        mapping_context: MappingContext,
        *,
        dry_run: bool,
        continue_on_error: bool,
        output_dir: str,
        event_callback=None,
        cancel_requested=None,
        pause_requested=None,
    ) -> dict[str, Any]:
        file_paths = mapping_context.file_paths or self._normalize_file_paths(file_state)
        if not file_paths:
            raise ValueError("업로드할 Excel 파일이 없습니다.")
        if not mapping_context.selected_mapping:
            raise ValueError("검증된 매핑이 없습니다.")
        upload_mode = normalize_gui_upload_mode(mapping_context.upload_mode)
        if gui_upload_mode_supports_update(upload_mode) and bool(getattr(settings, "offline_mode", False)):
            raise ValueError("테스트 모드에서는 기존 수정 또는 혼합 처리 작업을 실행할 수 없습니다.")
        if gui_upload_mode_supports_update(upload_mode) and mapping_context.batch_duplicate_update_item_ids:
            duplicate_ids = ", ".join(str(item_id) for item_id in sorted(mapping_context.batch_duplicate_update_item_ids))
            raise ValueError(f"배치 전체에서 중복된 업데이트 대상 id가 있습니다: {duplicate_ids}")
        action_label = gui_upload_mode_action_label(upload_mode)

        sheet_name = str(file_state["sheet_name"])
        header_row = int(file_state["header_row"])
        summary_col = str(file_state["summary_column"])

        prepared_jobs: list[BatchUploadJob] = []
        skipped_jobs: dict[str, tuple[BatchUploadJob, str]] = {}
        success_frames: list[pd.DataFrame] = []
        failed_frames: list[pd.DataFrame] = []
        unresolved_frames: list[pd.DataFrame] = []
        retry_jobs: list[FailedUploadRetryJob] = []
        created_map_by_file: dict[str, dict[Any, Any]] = {}
        state_save_warnings: list[str] = []
        preparation_stopped = False
        cancelled = False
        total_count = 0
        phase_total_counts = {"insert": 0, "update": 0}
        phase_results = {
            "insert": {"total": 0, "success": 0, "failed": 0, "unresolved": 0},
            "update": {"total": 0, "success": 0, "failed": 0, "unresolved": 0},
        }

        def _emit(event: dict[str, Any]) -> None:
            if event_callback is not None:
                event_callback(event)

        def _sync_control() -> bool:
            """`sync_control` 상태를 동기화한다."""
            while pause_requested is not None and pause_requested():
                time.sleep(0.1)
            return bool(cancel_requested is not None and cancel_requested())

        for index, file_path in enumerate(file_paths, start=1):
            if _sync_control():
                cancelled = True
                for pending_path in file_paths[index - 1 :]:
                    pending_label = Path(pending_path).name
                    unresolved_frames.append(pd.DataFrame([{
                        "source_file": pending_label,
                        "source_file_path": pending_path,
                        "_row_id": None,
                        "parent_row_id": None,
                        "upload_name": Path(pending_path).stem.strip() or pending_label,
                        "phase": (
                            "update"
                            if upload_mode == GUI_UPLOAD_MODE_UPDATE
                            else "insert"
                        ),
                        "error": "사용자 중단 요청으로 파일 준비를 실행하지 않았습니다.",
                        "status": UploadStatus.UNRESOLVED_PARENT.value,
                    }]))
                break
            file_label = Path(file_path).name
            _emit({
                "type": "log",
                "message": f"[{file_label}] {action_label} 데이터를 준비하는 중입니다.",
            })
            try:
                wizard = self._prepare_wizard_for_file(
                    settings,
                    mapping_context,
                    file_path=file_path,
                    sheet_name=sheet_name,
                    header_row=header_row,
                    summary_col=summary_col,
                )
                if gui_upload_mode_allows_root_items(upload_mode):
                    root_item_specs = self.build_root_item_payload_specs(mapping_context, wizard, file_path)
                else:
                    root_item_specs = []
                insert_ready_count, update_ready_count = self._phase_ready_counts(wizard, root_item_specs)
                ready_count = insert_ready_count + update_ready_count
                total_count += ready_count
                phase_total_counts["insert"] += insert_ready_count
                phase_total_counts["update"] += update_ready_count
                prepared_job = BatchUploadJob(
                    file_path=file_path,
                    file_label=file_label,
                    root_item_specs=root_item_specs,
                    ready_count=ready_count,
                    insert_ready_count=insert_ready_count,
                    update_ready_count=update_ready_count,
                    output_dir=self._batch_output_dir(output_dir, file_path, index),
                    wizard=wizard,
                )
                if preparation_stopped:
                    skipped_jobs[file_path] = (
                        prepared_job,
                        "이전 파일 준비 실패로 업로드를 실행하지 않았습니다.",
                    )
                else:
                    prepared_jobs.append(prepared_job)
            except Exception as exc:
                fallback_root_item_name = Path(file_path).stem.strip() or file_label
                failed_frames.append(pd.DataFrame([{
                    "source_file": file_label,
                    "source_file_path": file_path,
                    "_row_id": None,
                    "parent_row_id": None,
                    "upload_name": fallback_root_item_name,
                    "error": str(exc),
                    "status": PayloadStatus.FAILED.value,
                }]))
                _emit({
                    "type": "log",
                    "message": f"[{file_label}] 업로드 준비 실패: {exc}",
                })
                if not continue_on_error:
                    preparation_stopped = True

        _emit({
            "type": "batch_total",
            "total": total_count,
            "phase_totals": dict(phase_total_counts),
        })

        for job_index, job in enumerate(prepared_jobs, start=1):
            if _sync_control():
                cancelled = True
                for pending_job in prepared_jobs[job_index - 1 :]:
                    skipped_jobs[pending_job.file_path] = (
                        pending_job,
                        "사용자 중단 요청으로 업로드를 실행하지 않았습니다.",
                    )
                break
            _emit({
                "type": "log",
                "message": f"[{job_index}/{len(prepared_jobs)}] {job.file_label} {action_label}를 시작합니다.",
            })

            _forward_event = _build_file_scoped_event_forwarder(
                file_label=job.file_label,
                file_path=job.file_path,
                emit=_emit,
            )

            if upload_mode == GUI_UPLOAD_MODE_UPDATE:
                result = job.wizard.update_items(
                    dry_run=dry_run,
                    continue_on_error=continue_on_error,
                    event_callback=_forward_event,
                    cancel_requested=cancel_requested,
                    pause_requested=pause_requested,
                )
            elif upload_mode == GUI_UPLOAD_MODE_UPSERT:
                result = job.wizard.upsert_items(
                    dry_run=dry_run,
                    continue_on_error=continue_on_error,
                    top_level_parent_specs=self._root_item_spec_dicts(
                        job.root_item_specs
                    ),
                    event_callback=_forward_event,
                    cancel_requested=cancel_requested,
                    pause_requested=pause_requested,
                )
            else:
                result = job.wizard.upload(
                    dry_run=dry_run,
                    continue_on_error=continue_on_error,
                    top_level_parent_specs=self._root_item_spec_dicts(
                        job.root_item_specs
                    ),
                    event_callback=_forward_event,
                    cancel_requested=cancel_requested,
                    pause_requested=pause_requested,
                )
            created_map_by_file[job.file_path] = result.get("created_map", {})

            success_df = self._annotate_batch_result_frame(
                result.get("success_df"),
                file_label=job.file_label,
                file_path=job.file_path,
            )
            failed_df = self._annotate_batch_result_frame(
                result.get("failed_df"),
                file_label=job.file_label,
                file_path=job.file_path,
            )
            unresolved_df = self._annotate_batch_result_frame(
                result.get("unresolved_df"),
                file_label=job.file_label,
                file_path=job.file_path,
            )

            if not success_df.empty:
                success_frames.append(success_df)
            if not failed_df.empty:
                failed_frames.append(failed_df)
            if not unresolved_df.empty:
                unresolved_frames.append(unresolved_df)

            retry_job = self._build_retry_job(
                job,
                upload_mode=upload_mode,
                failed_df=failed_df,
                unresolved_df=unresolved_df,
                created_row_item_ids=result.get("created_map", {}),
                created_parent_item_ids_by_key=result.get(
                    "parent_item_ids_by_key", {}
                ),
                update_payload_prepared=bool(
                    result.get(
                        "update_payload_prepared",
                        upload_mode != GUI_UPLOAD_MODE_UPSERT,
                    )
                ),
            )
            if retry_job is not None:
                retry_jobs.append(retry_job)

            for phase_name in ("insert", "update"):
                if not success_df.empty and "phase" in success_df.columns:
                    phase_results[phase_name]["success"] += int(
                        success_df["phase"].fillna("").astype(str).str.lower().eq(phase_name).sum()
                    )
                if not failed_df.empty and "phase" in failed_df.columns:
                    phase_results[phase_name]["failed"] += int(
                        failed_df["phase"].fillna("").astype(str).str.lower().eq(phase_name).sum()
                    )
                if not unresolved_df.empty and "phase" in unresolved_df.columns:
                    phase_results[phase_name]["unresolved"] += int(
                        unresolved_df["phase"].fillna("").astype(str).str.lower().eq(phase_name).sum()
                    )

            try:
                job.wizard.save_state(job.output_dir)
            except Exception:
                warning = (
                    f"[{job.file_label}] 로컬 상태 파일을 저장하지 못했습니다. "
                    "서버 처리 결과와 세션 재시도 정보는 유지됩니다."
                )
                state_save_warnings.append(warning)
                _emit({"type": "log", "message": warning})

            if not continue_on_error and (not failed_df.empty or not unresolved_df.empty):
                for pending_job in prepared_jobs[job_index:]:
                    skipped_jobs[pending_job.file_path] = (
                        pending_job,
                        "이전 파일 업로드 실패로 실행하지 않았습니다.",
                    )
                break
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                for pending_job in prepared_jobs[job_index:]:
                    skipped_jobs[pending_job.file_path] = (
                        pending_job,
                        "사용자 중단 요청으로 업로드를 실행하지 않았습니다.",
                    )
                break

        for skipped_job, reason in skipped_jobs.values():
            unresolved_df = self._unattempted_job_frame(
                skipped_job,
                upload_mode=upload_mode,
                reason=reason,
            )
            if not unresolved_df.empty:
                unresolved_frames.append(unresolved_df)
            retry_job = self._build_retry_job(
                skipped_job,
                upload_mode=upload_mode,
                failed_df=pd.DataFrame(),
                unresolved_df=unresolved_df,
                created_row_item_ids={},
                created_parent_item_ids_by_key={},
                update_payload_prepared=not gui_upload_mode_supports_update(
                    upload_mode
                ),
            )
            if retry_job is not None:
                retry_jobs.append(retry_job)

        for phase_name in ("insert", "update"):
            phase_results[phase_name]["total"] = (
                int(phase_results[phase_name]["success"])
                + int(phase_results[phase_name]["failed"])
                + int(phase_results[phase_name]["unresolved"])
            )

        success_result_df = (
            pd.concat(success_frames, ignore_index=True)
            if success_frames
            else pd.DataFrame()
        )
        failed_result_df = (
            pd.concat(failed_frames, ignore_index=True)
            if failed_frames
            else pd.DataFrame()
        )
        unresolved_result_df = (
            pd.concat(unresolved_frames, ignore_index=True)
            if unresolved_frames
            else pd.DataFrame()
        )
        phase_results = self._phase_results_from_frames(
            success_result_df,
            failed_result_df,
            unresolved_result_df,
        )
        non_retryable_count = self._non_retryable_result_count(
            failed_result_df,
            unresolved_result_df,
            retry_jobs,
        )
        retry_context = (
            FailedUploadRetryContext(
                jobs=retry_jobs,
                success_df=success_result_df.copy(),
                failed_df=failed_result_df.copy(),
                unresolved_df=unresolved_result_df.copy(),
                created_map_by_file={
                    path: dict(created_map)
                    for path, created_map in created_map_by_file.items()
                },
                dry_run=bool(dry_run),
                non_retryable_count=non_retryable_count,
            )
            if retry_jobs
            else None
        )
        retry_unavailable_reason = ""
        if retry_context is None and (
            not failed_result_df.empty or not unresolved_result_df.empty
        ):
            retry_unavailable_reason = (
                "파일 준비, 매핑 또는 payload 생성 단계의 오류는 자동 재시도할 수 없습니다. "
                "검증 단계로 돌아가 데이터를 수정한 뒤 다시 실행하세요."
            )

        return {
            "created_map_by_file": created_map_by_file,
            "success_df": success_result_df,
            "failed_df": failed_result_df,
            "unresolved_df": unresolved_result_df,
            "phase_results": phase_results,
            "retry_context": retry_context,
            "retry_unavailable_reason": retry_unavailable_reason,
            "state_save_warnings": state_save_warnings,
            "cancelled": cancelled,
        }

    def run_failed_upload_retry(
        self,
        retry_context: FailedUploadRetryContext,
        *,
        continue_on_error: bool,
        event_callback=None,
        cancel_requested=None,
        pause_requested=None,
    ) -> dict[str, Any]:
        """현재 세션에서 실패하거나 부모가 미해결인 행만 다시 실행한다."""
        if not isinstance(retry_context, FailedUploadRetryContext):
            raise ValueError("재시도할 업로드 세션 정보가 없습니다.")
        if not retry_context.jobs:
            raise ValueError("자동 재시도가 가능한 실패 항목이 없습니다.")

        def _emit(event: dict[str, Any]) -> None:
            if event_callback is not None:
                event_callback(event)

        cumulative_success = retry_context.success_df.copy()
        cumulative_failed = retry_context.failed_df.copy()
        cumulative_unresolved = retry_context.unresolved_df.copy()
        created_map_by_file = {
            path: dict(created_map)
            for path, created_map in retry_context.created_map_by_file.items()
        }
        next_retry_jobs: list[FailedUploadRetryJob] = []
        retry_success_frames: list[pd.DataFrame] = []
        retry_failed_frames: list[pd.DataFrame] = []
        retry_unresolved_frames: list[pd.DataFrame] = []
        attempted_count = 0
        cancelled = False

        phase_totals = {"insert": 0, "update": 0}
        for retry_job in retry_context.jobs:
            payload_df = retry_job.wizard.state.payload_df
            operation_by_row_id: dict[int, str] = {}
            if isinstance(payload_df, pd.DataFrame) and not payload_df.empty:
                for _, row in payload_df.iterrows():
                    operation_by_row_id[int(row["_row_id"])] = str(
                        row.get("_operation") or ""
                    ).strip().lower()
            if retry_job.upload_mode == GUI_UPLOAD_MODE_UPDATE:
                phase_totals["update"] += len(retry_job.retry_row_ids)
            elif retry_job.upload_mode == GUI_UPLOAD_MODE_UPSERT:
                phase_totals["insert"] += sum(
                    operation_by_row_id.get(row_id) == "create"
                    for row_id in retry_job.retry_row_ids
                ) + len(retry_job.retry_root_keys)
                phase_totals["update"] += sum(
                    operation_by_row_id.get(row_id) == "update"
                    for row_id in retry_job.retry_row_ids
                )
            else:
                phase_totals["insert"] += (
                    len(retry_job.retry_row_ids)
                    + len(retry_job.retry_root_keys)
                )
        _emit({
            "type": "batch_total",
            "total": sum(phase_totals.values()),
            "phase_totals": phase_totals,
        })

        for job_index, retry_job in enumerate(retry_context.jobs):
            while pause_requested is not None and pause_requested():
                time.sleep(0.1)
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                next_retry_jobs.extend(retry_context.jobs[job_index:])
                break

            _emit({
                "type": "log",
                "message": (
                    f"[{retry_job.file_label}] 실패/미해결 "
                    f"{retry_job.retry_target_count}건만 재시도합니다."
                ),
            })

            _forward_event = _build_file_scoped_event_forwarder(
                file_label=retry_job.file_label,
                file_path=retry_job.file_path,
                emit=_emit,
            )

            payload_df = retry_job.wizard.state.payload_df
            operation_by_row_id: dict[int, str] = {}
            if isinstance(payload_df, pd.DataFrame) and not payload_df.empty:
                for _, row in payload_df.iterrows():
                    operation_by_row_id[int(row["_row_id"])] = str(
                        row.get("_operation") or ""
                    ).strip().lower()

            if retry_job.upload_mode == GUI_UPLOAD_MODE_UPDATE:
                insert_row_ids: set[int] = set()
                update_row_ids = set(retry_job.retry_row_ids)
            elif retry_job.upload_mode == GUI_UPLOAD_MODE_UPSERT:
                insert_row_ids = {
                    row_id
                    for row_id in retry_job.retry_row_ids
                    if operation_by_row_id.get(row_id) == "create"
                }
                update_row_ids = {
                    row_id
                    for row_id in retry_job.retry_row_ids
                    if operation_by_row_id.get(row_id) == "update"
                }
            else:
                insert_row_ids = set(retry_job.retry_row_ids)
                update_row_ids = set()

            job_success_frames: list[pd.DataFrame] = []
            job_failed_frames: list[pd.DataFrame] = []
            job_unresolved_frames: list[pd.DataFrame] = []
            created_row_item_ids = dict(retry_job.created_row_item_ids)
            created_parent_item_ids_by_key = dict(
                retry_job.created_parent_item_ids_by_key
            )
            update_payload_prepared = bool(retry_job.update_payload_prepared)

            should_run_insert = bool(insert_row_ids or retry_job.retry_root_keys)
            if should_run_insert:
                insert_total = len(insert_row_ids) + len(retry_job.retry_root_keys)
                insert_target_job = self._retry_job_subset(
                    retry_job,
                    retry_row_ids=insert_row_ids,
                    retry_root_keys=retry_job.retry_root_keys,
                )
                cumulative_failed = self._drop_retry_targets(
                    cumulative_failed,
                    insert_target_job,
                )
                cumulative_unresolved = self._drop_retry_targets(
                    cumulative_unresolved,
                    insert_target_job,
                )
                attempted_count += insert_total
                _emit({"type": "phase_started", "phase": "insert", "total": insert_total})
                insert_result = retry_job.wizard.upload(
                    dry_run=retry_context.dry_run,
                    continue_on_error=continue_on_error,
                    phase_name="insert",
                    top_level_parent_specs=self._root_item_spec_dicts(
                        retry_job.root_item_specs
                    ),
                    include_row_ids=insert_row_ids,
                    existing_row_item_ids=created_row_item_ids,
                    existing_parent_item_ids_by_key=created_parent_item_ids_by_key,
                    event_callback=_forward_event,
                    cancel_requested=cancel_requested,
                    pause_requested=pause_requested,
                )
                created_row_item_ids.update(insert_result.get("created_map", {}))
                created_parent_item_ids_by_key.update(
                    insert_result.get("parent_item_ids_by_key", {})
                )
                for key, collection in (
                    ("success_df", job_success_frames),
                    ("failed_df", job_failed_frames),
                    ("unresolved_df", job_unresolved_frames),
                ):
                    frame = self._annotate_batch_result_frame(
                        insert_result.get(key),
                        file_label=retry_job.file_label,
                        file_path=retry_job.file_path,
                    )
                    if not frame.empty:
                        collection.append(frame)
                _emit({
                    "type": "phase_finished",
                    "phase": "insert",
                    "total": insert_total,
                    "success": sum(len(frame) for frame in job_success_frames),
                    "failed": sum(len(frame) for frame in job_failed_frames),
                    "unresolved": sum(len(frame) for frame in job_unresolved_frames),
                })

            insert_failed = bool(job_failed_frames or job_unresolved_frames)
            if update_row_ids and (continue_on_error or not insert_failed):
                update_target_job = self._retry_job_subset(
                    retry_job,
                    retry_row_ids=update_row_ids,
                    retry_root_keys=set(),
                )
                cumulative_failed = self._drop_retry_targets(
                    cumulative_failed,
                    update_target_job,
                )
                cumulative_unresolved = self._drop_retry_targets(
                    cumulative_unresolved,
                    update_target_job,
                )
                attempted_count += len(update_row_ids)
                _emit({"type": "phase_started", "phase": "update", "total": len(update_row_ids)})
                update_result = retry_job.wizard.update_items(
                    dry_run=retry_context.dry_run,
                    continue_on_error=continue_on_error,
                    phase_name="update",
                    include_row_ids=update_row_ids,
                    fetch_existing_items=not update_payload_prepared,
                    event_callback=_forward_event,
                    cancel_requested=cancel_requested,
                    pause_requested=pause_requested,
                )
                update_payload_prepared = True
                update_success_count = 0
                update_failed_count = 0
                update_unresolved_count = 0
                for key, collection in (
                    ("success_df", job_success_frames),
                    ("failed_df", job_failed_frames),
                    ("unresolved_df", job_unresolved_frames),
                ):
                    frame = self._annotate_batch_result_frame(
                        update_result.get(key),
                        file_label=retry_job.file_label,
                        file_path=retry_job.file_path,
                    )
                    if frame.empty:
                        continue
                    collection.append(frame)
                    if key == "success_df":
                        update_success_count += len(frame)
                    elif key == "failed_df":
                        update_failed_count += len(frame)
                    else:
                        update_unresolved_count += len(frame)
                _emit({
                    "type": "phase_finished",
                    "phase": "update",
                    "total": len(update_row_ids),
                    "success": update_success_count,
                    "failed": update_failed_count,
                    "unresolved": update_unresolved_count,
                })

            job_success_df = self._concat_frames(job_success_frames)
            job_failed_df = self._concat_frames(job_failed_frames)
            job_unresolved_df = self._concat_frames(job_unresolved_frames)
            retry_success_frames.append(job_success_df)
            retry_failed_frames.append(job_failed_df)
            retry_unresolved_frames.append(job_unresolved_df)
            cumulative_success = self._concat_frames(
                [cumulative_success, job_success_df]
            )
            cumulative_failed = self._concat_frames(
                [cumulative_failed, job_failed_df]
            )
            cumulative_unresolved = self._concat_frames(
                [cumulative_unresolved, job_unresolved_df]
            )
            created_map_by_file[retry_job.file_path] = dict(created_row_item_ids)

            next_retry_job = self._build_retry_job(
                retry_job,
                upload_mode=retry_job.upload_mode,
                failed_df=self._source_result_frame(
                    cumulative_failed,
                    file_path=retry_job.file_path,
                ),
                unresolved_df=self._source_result_frame(
                    cumulative_unresolved,
                    file_path=retry_job.file_path,
                ),
                created_row_item_ids=created_row_item_ids,
                created_parent_item_ids_by_key=created_parent_item_ids_by_key,
                update_payload_prepared=update_payload_prepared,
            )
            if next_retry_job is not None:
                next_retry_jobs.append(next_retry_job)

            if not continue_on_error and (
                not job_failed_df.empty or not job_unresolved_df.empty
            ):
                next_retry_jobs.extend(retry_context.jobs[job_index + 1 :])
                break
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                next_retry_jobs.extend(retry_context.jobs[job_index + 1 :])
                break

        non_retryable_count = self._non_retryable_result_count(
            cumulative_failed,
            cumulative_unresolved,
            next_retry_jobs,
        )
        next_retry_context = (
            FailedUploadRetryContext(
                jobs=next_retry_jobs,
                success_df=cumulative_success.copy(),
                failed_df=cumulative_failed.copy(),
                unresolved_df=cumulative_unresolved.copy(),
                created_map_by_file={
                    path: dict(created_map)
                    for path, created_map in created_map_by_file.items()
                },
                dry_run=retry_context.dry_run,
                non_retryable_count=non_retryable_count,
            )
            if next_retry_jobs
            else None
        )
        retry_unavailable_reason = ""
        if next_retry_context is None and (
            not cumulative_failed.empty or not cumulative_unresolved.empty
        ):
            retry_unavailable_reason = (
                "남은 항목은 파일 준비, 매핑 또는 payload 생성 오류이므로 자동 재시도할 수 없습니다. "
                "검증 단계로 돌아가 데이터를 수정하세요."
            )

        return {
            "created_map_by_file": created_map_by_file,
            "success_df": cumulative_success,
            "failed_df": cumulative_failed,
            "unresolved_df": cumulative_unresolved,
            "phase_results": self._phase_results_from_frames(
                cumulative_success,
                cumulative_failed,
                cumulative_unresolved,
            ),
            "retry_context": next_retry_context,
            "retry_unavailable_reason": retry_unavailable_reason,
            "retry_attempted_count": attempted_count,
            "retry_success_df": self._concat_frames(retry_success_frames),
            "retry_failed_df": self._concat_frames(retry_failed_frames),
            "retry_unresolved_df": self._concat_frames(retry_unresolved_frames),
            "cancelled": cancelled,
        }
