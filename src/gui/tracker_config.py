from __future__ import annotations

from typing import Any

import pandas as pd

from src.models import TrackerItemResolutionMode
from src.upload_policy import DEFAULT_TRACKER_ITEM_ID_REGEX

from .upload_context import TrackerItemFieldCandidate


TRACKER_ITEM_QUERY_STATUS_SUPPORTED = "supported"
TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED = "unsupported"
TRACKER_ITEM_QUERY_STATUS_UNAVAILABLE = "unavailable"


class TrackerConfigurationService:
    @staticmethod
    def _normalize_lookup_text(value: Any) -> str:
        text = str(value or "").strip()
        return "" if text.lower() == "nan" else text

    @staticmethod
    def _normalize_reference_id(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_field_records(cls, payload: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_nodes: set[int] = set()

        def _looks_like_field_record(node: Any) -> bool:
            if not isinstance(node, dict):
                return False
            if "referenceId" in node:
                return True
            if not any(
                key in node
                for key in (
                    "choiceOptionSetting",
                    "choiceConfigOptionsSetting",
                    "choiceConfigOptionsSetApi",
                    "referenceFilters",
                )
            ):
                return False
            return any(key in node for key in ("label", "name", "title"))

        def _append_record(node: dict[str, Any]) -> None:
            node_id = id(node)
            if node_id in seen_nodes:
                return
            seen_nodes.add(node_id)
            records.append(node)

        def _walk(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    _walk(item)
                return
            if not isinstance(node, dict):
                return
            if _looks_like_field_record(node):
                _append_record(node)
            for value in node.values():
                _walk(value)

        if isinstance(payload, dict):
            fields_container = payload.get("fields")
            if isinstance(fields_container, list):
                _walk(fields_container)
                if records:
                    return records
            elif isinstance(fields_container, dict) and isinstance(fields_container.get("value"), list):
                _walk(fields_container["value"])
                if records:
                    return records

        _walk(payload)
        return records

    @staticmethod
    def _query_support(field_config: dict[str, Any]) -> tuple[list[int], str]:
        if not isinstance(field_config, dict):
            return [], TRACKER_ITEM_QUERY_STATUS_UNAVAILABLE

        source_configs: list[dict[str, Any]] = []
        if isinstance(field_config.get("choiceOptionSetting"), dict):
            source_configs.append(field_config["choiceOptionSetting"])
        if isinstance(field_config.get("choiceConfigOptionsSetting"), dict):
            source_configs.append(field_config["choiceConfigOptionsSetting"])
        if isinstance(field_config.get("choiceConfigOptionsSetApi"), dict):
            source_configs.append(field_config["choiceConfigOptionsSetApi"])
        source_configs.append(field_config)

        tracker_ids: list[int] = []
        seen_ids: set[int] = set()
        saw_reference_filters = False
        for source in source_configs:
            filters = source.get("referenceFilters")
            if not isinstance(filters, list):
                continue
            saw_reference_filters = True
            if not filters:
                return [], TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED
            for filter_entry in filters:
                if not isinstance(filter_entry, dict):
                    return [], TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED
                if str(filter_entry.get("domainType") or "").strip().upper() != "TRACKER":
                    return [], TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED
                domain_id = filter_entry.get("domainId")
                if domain_id is None:
                    return [], TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED
                try:
                    normalized_id = int(domain_id)
                except (TypeError, ValueError):
                    return [], TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED
                if normalized_id in seen_ids:
                    continue
                seen_ids.add(normalized_id)
                tracker_ids.append(normalized_id)

        if not saw_reference_filters:
            return [], TRACKER_ITEM_QUERY_STATUS_UNAVAILABLE
        if tracker_ids:
            return tracker_ids, TRACKER_ITEM_QUERY_STATUS_SUPPORTED
        return [], TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED

    @classmethod
    def enrich_schema(
        cls,
        schema_df: pd.DataFrame,
        tracker_configuration: Any,
    ) -> pd.DataFrame:
        if schema_df is None or schema_df.empty:
            return schema_df

        config_fields = cls._extract_field_records(tracker_configuration)
        if not config_fields:
            work = schema_df.copy()
            work["tracker_item_source_tracker_ids"] = [[] for _ in range(len(work.index))]
            work["tracker_item_query_status"] = [
                TRACKER_ITEM_QUERY_STATUS_UNAVAILABLE
                for _ in range(len(work.index))
            ]
            return work

        def _normalized_candidates(payload: dict[str, Any]) -> set[str]:
            values = {
                cls._normalize_lookup_text(payload.get("label")).casefold(),
                cls._normalize_lookup_text(payload.get("name")).casefold(),
                cls._normalize_lookup_text(payload.get("title")).casefold(),
            }
            return {value for value in values if value}

        config_by_name: dict[str, dict[str, Any]] = {}
        config_by_reference_id: dict[int, dict[str, Any]] = {}
        for field_config in config_fields:
            reference_id = cls._normalize_reference_id(field_config.get("referenceId"))
            if reference_id is not None:
                config_by_reference_id.setdefault(reference_id, field_config)
            for candidate in _normalized_candidates(field_config):
                config_by_name.setdefault(candidate, field_config)

        work = schema_df.copy()
        source_tracker_ids_column: list[list[int]] = []
        query_status_column: list[str] = []

        for _, row in work.iterrows():
            row_field_id = cls._normalize_reference_id(row.get("field_id"))
            matched_config = (
                config_by_reference_id.get(row_field_id)
                if row_field_id is not None
                else None
            )
            normalized_names = {
                cls._normalize_lookup_text(row.get("field_name")).casefold(),
                cls._normalize_lookup_text(row.get("field_label")).casefold(),
            }
            normalized_names.discard("")
            if matched_config is None:
                for candidate in normalized_names:
                    matched_config = config_by_name.get(candidate)
                    if matched_config is not None:
                        break
            tracker_ids, query_status = cls._query_support(matched_config or {})
            source_tracker_ids_column.append(tracker_ids)
            query_status_column.append(query_status)

        work["tracker_item_source_tracker_ids"] = source_tracker_ids_column
        work["tracker_item_query_status"] = query_status_column
        return work

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
            source_tracker_ids = [
                int(item)
                for item in (schema_row.get("tracker_item_source_tracker_ids") or [])
                if str(item).strip()
            ]
            candidates.append(
                TrackerItemFieldCandidate(
                    df_column=str(df_column).strip(),
                    schema_field=str(schema_field).strip(),
                    field_type=str(schema_row.get("field_type") or ""),
                    source_tracker_ids=source_tracker_ids,
                    supports_query=bool(source_tracker_ids),
                    query_status=str(
                        schema_row.get("tracker_item_query_status")
                        or TRACKER_ITEM_QUERY_STATUS_UNAVAILABLE
                    ),
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
