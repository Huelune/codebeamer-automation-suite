from __future__ import annotations

from typing import Any

import pandas as pd

from src.models import TrackerItemResolutionMode
from src.upload_policy import DEFAULT_TRACKER_ITEM_ID_REGEX

from .upload_context import TrackerItemFieldCandidate


class TrackerConfigurationService:

    @staticmethod
    def build_field_candidates(
        schema_df: pd.DataFrame,
        selected_mapping: dict[str, str],
    ) -> list[TrackerItemFieldCandidate]:
        candidates: list[TrackerItemFieldCandidate] = []
        if schema_df is None or schema_df.empty:
            return candidates

        schema_rows_by_name = {
            str(row.get("field_name") or "").strip(): row
            for _, row in schema_df.iterrows()
            if str(row.get("field_name") or "").strip()
        }
        for df_column, schema_field in selected_mapping.items():
            schema_row = schema_rows_by_name.get(str(schema_field).strip())
            if schema_row is None:
                continue
            if str(schema_row.get("field_type") or "").strip() != "TrackerItemChoiceField":
                continue
            candidates.append(
                TrackerItemFieldCandidate(
                    df_column=str(df_column).strip(),
                    schema_field=str(schema_field).strip(),
                    field_type=str(schema_row.get("field_type") or ""),
                )
            )
        return candidates

    @classmethod
    def default_settings(
        cls,
        tracker_item_candidates: list[TrackerItemFieldCandidate],
    ) -> dict[str, dict[str, Any]]:
        settings: dict[str, dict[str, Any]] = {}
        for candidate in tracker_item_candidates:
            settings[candidate.schema_field] = {
                "mode": TrackerItemResolutionMode.REGEX.value,
                "regex_pattern": DEFAULT_TRACKER_ITEM_ID_REGEX,
            }
        return settings

    @classmethod
    def normalize_settings(
        cls,
        schema_df: pd.DataFrame,
        selected_mapping: dict[str, str],
        tracker_item_settings: dict[str, dict[str, Any]] | None,
    ) -> tuple[list[TrackerItemFieldCandidate], dict[str, dict[str, Any]]]:
        candidates = cls.build_field_candidates(schema_df, selected_mapping)
        normalized_settings = cls.default_settings(candidates)

        for candidate in candidates:
            raw_setting = (tracker_item_settings or {}).get(candidate.schema_field)
            if not isinstance(raw_setting, dict):
                continue
            default_setting = normalized_settings[candidate.schema_field]
            normalized_settings[candidate.schema_field] = {
                # 이전에 저장된 query 설정도 API 조회를 다시 활성화하지 않도록 무시한다.
                "mode": TrackerItemResolutionMode.REGEX.value,
                "regex_pattern": str(
                    raw_setting.get("regex_pattern")
                    or default_setting["regex_pattern"]
                ).strip()
                or DEFAULT_TRACKER_ITEM_ID_REGEX,
            }

        return candidates, normalized_settings
