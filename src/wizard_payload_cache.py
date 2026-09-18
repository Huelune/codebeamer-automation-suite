from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from .models import PayloadStatus
from .upload_policy import normalize_upload_mode
from .upload_policy import upload_mode_supports_update


class WizardPayloadCacheService:
    """행별 payload 생성 결과를 계산하고 WizardState에 cache한다."""

    def __init__(
        self,
        *,
        state: Any,
        payload_source_df: Callable[[], pd.DataFrame],
        update_item_id_column_name: Callable[[pd.DataFrame], str | None],
        parse_update_item_id: Callable[[Any], int],
        raise_payload_error: Callable[..., None],
        build_update_row_payload: Callable[..., Any],
        build_row_payload: Callable[..., dict[str, Any]],
        resolve_update_target_item_id: Callable[..., int | None],
        apply_upsert_hierarchy_validation: Callable[[pd.DataFrame, pd.DataFrame], None],
    ) -> None:
        self.state = state
        self._payload_source_df = payload_source_df
        self._update_item_id_column_name = update_item_id_column_name
        self._parse_update_item_id = parse_update_item_id
        self._raise_payload_error = raise_payload_error
        self._build_update_row_payload = build_update_row_payload
        self._build_row_payload = build_row_payload
        self._resolve_update_target_item_id = resolve_update_target_item_id
        self._apply_upsert_hierarchy_validation = apply_upsert_hierarchy_validation

    def build_payloads(
        self,
        force: bool = False,
        *,
        fetch_existing_items: bool = True,
    ) -> pd.DataFrame:
        """현재 업로드 대상 전체 행의 payload를 한 번에 계산해 cache한다."""
        if self.state.schema_df is None:
            raise ValueError("schema_df is required before payload generation.")

        if self.state.payload_df is not None and not force:
            return self.state.payload_df

        source_df = self._payload_source_df()
        payload_rows: list[dict[str, Any]] = []
        upload_mode = normalize_upload_mode(self.state.upload_mode)
        id_column_name = None
        duplicate_item_ids: set[int] = set()

        if upload_mode_supports_update(upload_mode):
            id_column_name = self._update_item_id_column_name(source_df)
            if id_column_name is not None:
                item_id_counts: dict[int, int] = {}
                for _, row in source_df.iterrows():
                    try:
                        target_item_id = self._parse_update_item_id(row.get(id_column_name))
                    except ValueError:
                        continue
                    item_id_counts[target_item_id] = item_id_counts.get(target_item_id, 0) + 1
                duplicate_item_ids = {
                    item_id
                    for item_id, item_count in item_id_counts.items()
                    if item_count > 1
                }

        for _, row in source_df.iterrows():
            row_id = int(row["_row_id"])
            operation = "create"
            target_item_id = None
            try:
                payload_json = None
                if upload_mode == "update":
                    operation = "update"
                    if id_column_name is None:
                        self._raise_payload_error(
                            "UPDATE_ITEM_ID_COLUMN_MISSING",
                            schema_field="id",
                            df_col="id",
                            row_id=row_id,
                            detail="update mode requires an Excel 'id' column",
                        )
                    target_item_id, payload_json = self._build_update_row_payload(
                        row,
                        row_id,
                        id_column_name=id_column_name,
                        duplicate_item_ids=duplicate_item_ids,
                        fetch_existing_item=fetch_existing_items,
                    )
                elif upload_mode == "upsert":
                    if id_column_name is None:
                        payload_json = self._build_row_payload(row, row_id)
                    else:
                        target_item_id = self._resolve_update_target_item_id(
                            row,
                            row_id,
                            id_column_name=id_column_name,
                            duplicate_item_ids=duplicate_item_ids,
                            allow_missing=True,
                        )
                        if target_item_id is None:
                            payload_json = self._build_row_payload(row, row_id)
                        else:
                            operation = "update"
                            target_item_id, payload_json = self._build_update_row_payload(
                                row,
                                row_id,
                                id_column_name=id_column_name,
                                duplicate_item_ids=duplicate_item_ids,
                                fetch_existing_item=fetch_existing_items,
                                target_item_id=target_item_id,
                            )
                else:
                    payload_json = self._build_row_payload(row, row_id)
                payload_rows.append({
                    "_row_id": row_id,
                    "parent_row_id": row.get("parent_row_id"),
                    "upload_name": row.get("upload_name"),
                    "_target_item_id": target_item_id,
                    "_operation": operation,
                    "payload_json": payload_json,
                    "payload_status": PayloadStatus.READY.value,
                    "payload_error": None,
                })
            except Exception as exc:
                payload_rows.append({
                    "_row_id": row_id,
                    "parent_row_id": row.get("parent_row_id"),
                    "upload_name": row.get("upload_name"),
                    "_target_item_id": target_item_id,
                    "_operation": operation,
                    "payload_json": None,
                    "payload_status": PayloadStatus.FAILED.value,
                    "payload_error": str(exc),
                })

        self.state.payload_df = pd.DataFrame(payload_rows)
        if upload_mode == "upsert" and not self.state.payload_df.empty:
            self._apply_upsert_hierarchy_validation(self.state.payload_df, source_df)
        return self.state.payload_df

    def preview_payload(self, row_id: int) -> dict:
        """cache된 payload를 돌려주고, 필요하면 먼저 build_payloads를 수행한다."""
        payload_df = self.build_payloads()
        row_df = payload_df[payload_df["_row_id"] == row_id]
        if row_df.empty:
            raise ValueError(f"_row_id={row_id} was not found.")

        payload_row = row_df.iloc[0]
        if payload_row["payload_status"] != PayloadStatus.READY.value:
            raise ValueError(payload_row["payload_error"])

        return payload_row["payload_json"]


