from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any
from typing import Literal
from typing import overload

import pandas as pd

from .models import PayloadStatus


class WizardUpdatePayloadService:
    """update/upsert 대상 판정, 기존 item 병합과 계층 검증을 담당한다."""

    def __init__(
        self,
        *,
        state: Any,
        client: Any,
        build_row_item: Callable[..., Any],
        serialize_payload_value: Callable[[Any], Any],
        raise_payload_error: Callable[..., None],
    ) -> None:
        self.state = state
        self.client = client
        self._build_row_item = build_row_item
        self._serialize_payload_value = serialize_payload_value
        self._raise_payload_error = raise_payload_error

    @staticmethod
    def _fixed_name_column(source_df: pd.DataFrame, fixed_name: str) -> str | None:
        """이름이 정해진 Excel 열을 찾는다. 같은 이름이 우선이고, 없으면 대소문자만 다른 첫 열이다."""
        case_insensitive_match = None
        for column_name in source_df.columns:
            normalized = str(column_name or "").strip()
            if not normalized or normalized.startswith("_"):
                continue
            if normalized == fixed_name:
                return normalized
            if normalized.casefold() == fixed_name and case_insensitive_match is None:
                case_insensitive_match = normalized
        return case_insensitive_match

    @classmethod
    def _update_item_id_column_name(cls, source_df: pd.DataFrame) -> str | None:
        """업데이트 모드에서 사용할 Excel ID 열 이름을 찾는다."""
        return cls._fixed_name_column(source_df, "id")

    @classmethod
    def _create_parent_column_name(cls, source_df: pd.DataFrame) -> str | None:
        """새로 만드는 최상위 행의 목적지(기존 item id)를 적는 Excel `parent` 열 이름을 찾는다."""
        return cls._fixed_name_column(source_df, "parent")

    def _create_parent_item_problem(self, parent_item_id: int) -> tuple[str, str] | None:
        """목적지 item 을 조회해 쓸 수 없는 이유(오류 코드, 상세)를 돌려준다. 쓸 수 있으면 None.

        수정 대상 캐시(`existing_item_cache`)에는 넣지 않는다. 같은 item 이 수정 행이기도 하면
        생성 단계 전에 읽은 내용으로 수정 payload 를 만들게 된다.
        """
        try:
            parent_item = self.client.get_item(int(parent_item_id))
        except Exception as exc:
            return "PARENT_ITEM_FETCH_FAILED", f"item_id={int(parent_item_id)} error={exc}"
        parent_tracker_id = self._item_tracker_id(parent_item) if isinstance(parent_item, dict) else None
        selected_tracker_id = self.state.tracker_id
        if (
            parent_tracker_id is None
            or selected_tracker_id is None
            or parent_tracker_id != int(selected_tracker_id)
        ):
            return (
                "PARENT_ITEM_TRACKER_MISMATCH",
                f"item_id={int(parent_item_id)} tracker_id={parent_tracker_id} "
                f"selected_tracker_id={selected_tracker_id}",
            )
        return None

    def _resolve_create_parent_item_id(
        self,
        row: pd.Series,
        row_id: int,
        *,
        parent_column_name: str,
        checked_parent_items: dict[int, tuple[str, str] | None],
    ) -> int | None:
        """행의 `parent` 칸을 새 item 을 만들 목적지 item id 로 해석한다. 비어 있으면 None.

        `checked_parent_items` 는 한 번의 payload 계산 동안 같은 목적지를 다시 조회하지 않게 한다.
        """
        raw_parent = row.get(parent_column_name)
        try:
            parent_item_id = self._parse_update_item_id(raw_parent)
        except ValueError as exc:
            if str(exc) == "missing":
                return None
            self._raise_payload_error(
                "PARENT_ITEM_ID_INVALID",
                schema_field="parent",
                df_col=parent_column_name,
                row_id=row_id,
                detail=f"value={raw_parent!r}",
            )

        if parent_item_id not in checked_parent_items:
            checked_parent_items[parent_item_id] = self._create_parent_item_problem(parent_item_id)
        problem = checked_parent_items[parent_item_id]
        if problem is not None:
            self._raise_payload_error(
                problem[0],
                schema_field="parent",
                df_col=parent_column_name,
                row_id=row_id,
                detail=problem[1],
            )
        return parent_item_id

    @staticmethod
    def _parse_update_item_id(raw_value: Any) -> int:
        """업데이트 대상 item id를 정수로 정규화한다."""
        if raw_value is None:
            raise ValueError("missing")
        if isinstance(raw_value, bool):
            raise ValueError(f"invalid: {raw_value!r}")
        if isinstance(raw_value, int):
            if raw_value > 0:
                return raw_value
            raise ValueError(f"invalid: {raw_value!r}")
        if isinstance(raw_value, float):
            if pd.isna(raw_value):
                raise ValueError("missing")
            if raw_value.is_integer() and raw_value > 0:
                return int(raw_value)
            raise ValueError(f"invalid: {raw_value!r}")

        text = str(raw_value).strip()
        if not text:
            raise ValueError("missing")
        if text.lower() == "nan":
            raise ValueError("missing")
        if text.isdigit():
            normalized = int(text)
            if normalized > 0:
                return normalized
        if text.endswith(".0") and text[:-2].isdigit():
            normalized = int(text[:-2])
            if normalized > 0:
                return normalized
        raise ValueError(f"invalid: {raw_value!r}")

    @overload
    def _resolve_update_target_item_id(
        self,
        row: pd.Series,
        row_id: int,
        *,
        id_column_name: str,
        duplicate_item_ids: set[int],
        allow_missing: Literal[False],
    ) -> int: ...

    @overload
    def _resolve_update_target_item_id(
        self,
        row: pd.Series,
        row_id: int,
        *,
        id_column_name: str,
        duplicate_item_ids: set[int],
        allow_missing: Literal[True],
    ) -> int | None: ...

    def _resolve_update_target_item_id(
        self,
        row: pd.Series,
        row_id: int,
        *,
        id_column_name: str,
        duplicate_item_ids: set[int],
        allow_missing: bool,
    ) -> int | None:
        """행의 id 셀을 update 대상 item id로 해석한다.

        `allow_missing=False` 면 값을 찾지 못했을 때 예외를 던지므로 항상 int 를 돌려준다.
        호출부에서 None 검사를 반복하지 않도록 overload 로 그 계약을 드러낸다.
        """
        if id_column_name not in row.index:
            if allow_missing:
                return None
            self._raise_payload_error(
                "UPDATE_ITEM_ID_COLUMN_MISSING",
                schema_field="id",
                df_col="id",
                row_id=row_id,
                detail="update mode requires an Excel 'id' column",
            )

        raw_item_id = row.get(id_column_name)
        try:
            target_item_id = self._parse_update_item_id(raw_item_id)
        except ValueError as exc:
            if str(exc) == "missing":
                if allow_missing:
                    return None
                self._raise_payload_error(
                    "UPDATE_ITEM_ID_MISSING",
                    schema_field="id",
                    df_col=id_column_name,
                    row_id=row_id,
                    detail="update target item id is empty",
                )
            self._raise_payload_error(
                "UPDATE_ITEM_ID_INVALID",
                schema_field="id",
                df_col=id_column_name,
                row_id=row_id,
                detail=f"value={raw_item_id!r}",
            )

        if target_item_id in duplicate_item_ids:
            self._raise_payload_error(
                "UPDATE_ITEM_ID_DUPLICATE",
                schema_field="id",
                df_col=id_column_name,
                row_id=row_id,
                detail=f"item_id={target_item_id}",
            )

        return int(target_item_id)

    @staticmethod
    def _filter_payload_rows(
        payload_df: pd.DataFrame,
        include_row_ids: set[int] | None,
    ) -> pd.DataFrame:
        """지정된 row_id 집합에 해당하는 payload 행만 남긴다."""
        if include_row_ids is None:
            return payload_df.copy()
        normalized_row_ids = {int(row_id) for row_id in include_row_ids}
        if not normalized_row_ids:
            return payload_df.iloc[0:0].copy()
        return payload_df[payload_df["_row_id"].isin(sorted(normalized_row_ids))].copy()

    @staticmethod
    def _concat_result_frames(frames: list[pd.DataFrame | None]) -> pd.DataFrame:
        """업로드 결과 프레임을 비어 있지 않은 것만 합친다."""
        valid_frames = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
        if not valid_frames:
            return pd.DataFrame()
        return pd.concat(valid_frames, ignore_index=True)

    @staticmethod
    def _result_count(frame: pd.DataFrame | None) -> int:
        """결과 DataFrame 행 수를 안전하게 계산한다."""
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return 0
        return len(frame)

    def _apply_upsert_hierarchy_validation(
        self,
        payload_df: pd.DataFrame,
        source_df: pd.DataFrame,
    ) -> None:
        """계층형 upsert에서 신규 조상 아래의 update 행을 차단한다."""
        if payload_df.empty or source_df.empty:
            return

        parent_by_row_id: dict[int, int | None] = {}
        for _, source_row in source_df.iterrows():
            row_id = int(source_row["_row_id"])
            parent_row_id = source_row.get("parent_row_id")
            normalized_parent_id: int | None = None
            if parent_row_id is not None and not pd.isna(parent_row_id):
                try:
                    normalized_parent_id = int(parent_row_id)
                except (TypeError, ValueError):
                    normalized_parent_id = None
            parent_by_row_id[row_id] = normalized_parent_id

        row_index_by_row_id = {
            int(row_id): index
            for index, row_id in enumerate(payload_df["_row_id"].tolist())
        }

        def _has_new_ancestor(row_id: int) -> bool:
            current_parent_id = parent_by_row_id.get(int(row_id))
            while current_parent_id is not None:
                parent_index = row_index_by_row_id.get(int(current_parent_id))
                if parent_index is None:
                    current_parent_id = parent_by_row_id.get(int(current_parent_id))
                    continue
                parent_row = payload_df.iloc[parent_index]
                if str(parent_row.get("_operation") or "").strip().lower() == "create":
                    return True
                current_parent_id = parent_by_row_id.get(int(current_parent_id))
            return False

        for index, row in payload_df.iterrows():
            if row.get("payload_status") != PayloadStatus.READY.value:
                continue
            if str(row.get("_operation") or "").strip().lower() != "update":
                continue

            row_id = int(row["_row_id"])
            if not _has_new_ancestor(row_id):
                continue

            payload_df.at[index, "payload_json"] = None
            payload_df.at[index, "payload_status"] = PayloadStatus.FAILED.value
            payload_df.at[index, "payload_error"] = (
                f"[UPSERT_UPDATE_WITH_NEW_ANCESTOR] field='id' df_column='id' _row_id={row_id} "
                "upsert update rows cannot have newly inserted ancestor rows in the same hierarchy"
            )

    def _existing_item(self, item_id: int, *, row_id: int, df_col: str) -> dict[str, Any]:
        """기존 item payload를 조회하고 캐시에 보관한다."""
        cached = self.state.existing_item_cache.get(int(item_id))
        if isinstance(cached, dict):
            return deepcopy(cached)

        try:
            existing_item = self.client.get_item(int(item_id))
        except Exception as exc:
            self._raise_payload_error(
                "UPDATE_ITEM_FETCH_FAILED",
                schema_field="id",
                df_col=df_col,
                row_id=row_id,
                detail=f"item_id={int(item_id)} error={exc}",
            )

        if not isinstance(existing_item, dict):
            self._raise_payload_error(
                "UPDATE_ITEM_FETCH_FAILED",
                schema_field="id",
                df_col=df_col,
                row_id=row_id,
                detail=f"item_id={int(item_id)} returned invalid payload",
            )

        self.state.existing_item_cache[int(item_id)] = dict(existing_item)
        return deepcopy(existing_item)

    @staticmethod
    def _item_tracker_id(item: dict[str, Any]) -> int | None:
        """조회한 item 이 속한 트래커 id. 응답에 없으면 None."""
        tracker = item.get("tracker")
        raw_id = tracker.get("id") if isinstance(tracker, dict) else None
        try:
            return int(raw_id) if raw_id is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _custom_field_key(field_payload: Any) -> tuple[str, Any] | None:
        """custom field 병합용 식별 키를 만든다."""
        if not isinstance(field_payload, dict):
            return None
        field_id = field_payload.get("fieldId")
        if field_id is not None:
            try:
                return ("fieldId", int(field_id))
            except (TypeError, ValueError):
                pass
        field_name = str(field_payload.get("name") or "").strip()
        if field_name:
            return ("name", field_name.casefold())
        return None

    @classmethod
    def _merge_custom_fields(
        cls,
        existing_fields: Any,
        updated_fields: Any,
    ) -> list[dict[str, Any]]:
        """기존 custom field 목록에 수정 대상 field만 덮어쓴다."""
        merged_fields: list[dict[str, Any]] = []
        field_indexes: dict[tuple[str, Any], int] = {}

        for existing_field in existing_fields if isinstance(existing_fields, list) else []:
            if not isinstance(existing_field, dict):
                continue
            merged_fields.append(deepcopy(existing_field))
            field_key = cls._custom_field_key(existing_field)
            if field_key is not None:
                field_indexes[field_key] = len(merged_fields) - 1

        for updated_field in updated_fields if isinstance(updated_fields, list) else []:
            if not isinstance(updated_field, dict):
                continue
            copied_field = deepcopy(updated_field)
            field_key = cls._custom_field_key(updated_field)
            if field_key is None or field_key not in field_indexes:
                merged_fields.append(copied_field)
                if field_key is not None:
                    field_indexes[field_key] = len(merged_fields) - 1
                continue
            merged_fields[field_indexes[field_key]] = copied_field

        return merged_fields

    def _build_update_row_payload(
        self,
        row: pd.Series,
        row_id: int,
        *,
        id_column_name: str,
        duplicate_item_ids: set[int],
        fetch_existing_item: bool,
        target_item_id: int | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """단일 업데이트 행의 대상 id와 PUT payload를 계산한다."""
        if target_item_id is None:
            target_item_id = self._resolve_update_target_item_id(
                row,
                row_id,
                id_column_name=id_column_name,
                duplicate_item_ids=duplicate_item_ids,
                allow_missing=False,
            )

        partial_item = self._build_row_item(
            row,
            row_id,
            default_name=None,
            operation="update",
        )
        partial_payload = self._serialize_payload_value(partial_item.to_dict())

        if not fetch_existing_item:
            partial_payload["id"] = int(target_item_id)
            return int(target_item_id), partial_payload

        existing_item = self._existing_item(
            target_item_id,
            row_id=row_id,
            df_col=id_column_name,
        )
        # 다른 트래커에서 내보낸 id 열이면 그 트래커 아이템을 지금 트래커 매핑으로 덮어쓰게 된다.
        existing_tracker_id = self._item_tracker_id(existing_item)
        selected_tracker_id = self.state.tracker_id
        if (
            existing_tracker_id is None
            or selected_tracker_id is None
            or existing_tracker_id != int(selected_tracker_id)
        ):
            self._raise_payload_error(
                "UPDATE_ITEM_TRACKER_MISMATCH",
                schema_field="id",
                df_col=id_column_name,
                row_id=row_id,
                detail=(
                    f"item_id={int(target_item_id)} tracker_id={existing_tracker_id} "
                    f"selected_tracker_id={selected_tracker_id}"
                ),
            )
        merged_payload = deepcopy(existing_item)

        for payload_key, payload_value in partial_payload.items():
            if payload_key == "customFields":
                merged_payload["customFields"] = self._merge_custom_fields(
                    merged_payload.get("customFields"),
                    payload_value,
                )
                continue
            merged_payload[payload_key] = payload_value

        merged_payload["id"] = int(target_item_id)
        return int(target_item_id), merged_payload


