from __future__ import annotations

from typing import Any

import pandas as pd

from .models import OptionCheckStatus
from .models import OptionMapKind
from .models import OptionSourceStatus
from .models import PreconstructionKind
from .models import ReferenceType
from .models import ResolvedFieldKind
from .models import UserLookupStatus


class MappingOptionMixin:
    @staticmethod
    def build_option_name_map(options: list[dict]) -> dict:
        """option 이름으로 빠르게 찾을 수 있는 사전을 만든다."""
        result = {}
        duplicates = set()

        for opt in options:
            name = opt.get("name")
            if not name:
                continue
            key = str(name).strip()
            if key in result:
                duplicates.add(key)
            else:
                result[key] = opt

        if duplicates:
            raise ValueError(f"Duplicate option names found: {sorted(duplicates)}")

        return result

    @staticmethod
    def _option_map_metadata(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
        """option map에도 공통 분류 정보를 함께 담기 위한 묶음을 만든다."""
        getter = row.get
        unsupported_reason = getter("unsupported_reason")
        if unsupported_reason is None:
            unsupported_reason = None
        else:
            try:
                if bool(pd.isna(unsupported_reason)):
                    unsupported_reason = None
            except Exception:
                pass
        if unsupported_reason is not None and str(unsupported_reason).strip() == "":
            unsupported_reason = None

        return {
            "resolved_field_kind": getter("resolved_field_kind"),
            "resolution_strategy": getter("resolution_strategy"),
            "is_supported": getter("is_supported"),
            "unsupported_reason": unsupported_reason,
            "requires_lookup": getter("requires_lookup"),
            "lookup_target_kind": getter("lookup_target_kind"),
            "preconstruction_kind": getter("preconstruction_kind"),
            "preconstruction_detail": getter("preconstruction_detail"),
            "payload_target_kind": getter("payload_target_kind"),
            "tracker_item_source_tracker_ids": getter("tracker_item_source_tracker_ids") or [],
        }

    def build_option_maps_from_schema(self, schema_df: pd.DataFrame) -> dict[str, dict]:
        """schema를 바탕으로 옵션 해결 전략 표를 만든다."""
        option_maps = {}
        option_fields = self.get_option_field_candidates(schema_df)

        for _, row in option_fields.iterrows():
            field_name = row["field_name"]
            if not field_name:
                continue

            metadata = self._option_map_metadata(row)
            resolved_field_kind = row.get("resolved_field_kind")
            reference_type = row.get("reference_type")
            multiple_values = row.get("multiple_values", False)

            if resolved_field_kind == ResolvedFieldKind.STATIC_OPTION.value:
                options = row.get("options") or []
                try:
                    name_map = self.build_option_name_map(options)
                except ValueError:
                    if self.logger:
                        self.logger.warning(f"Duplicate options found in field: {field_name}")
                    option_maps[field_name] = {
                        "kind": OptionMapKind.UNSUPPORTED.value,
                        "name_map": {},
                        "reference_type": reference_type,
                        "multiple_values": multiple_values,
                        "options": options,
                        "source_status": OptionSourceStatus.UNSUPPORTED.value,
                        "resolver_available": False,
                        **metadata,
                        "unsupported_reason": (
                            "schema options에 중복 name이 있어 "
                            "안전하게 option map을 만들 수 없습니다."
                        ),
                    }
                    continue

                option_maps[field_name] = {
                    "kind": OptionMapKind.STATIC_OPTIONS.value,
                    "name_map": name_map,
                    "reference_type": reference_type,
                    "multiple_values": multiple_values,
                    "options": options,
                    "source_status": OptionSourceStatus.READY.value,
                    "resolver_available": True,
                    **metadata,
                }
                continue

            if resolved_field_kind == ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value:
                option_maps[field_name] = {
                    "kind": OptionMapKind.TRACKER_ITEM_DIRECT.value,
                    "name_map": {},
                    "reference_type": reference_type or ReferenceType.TRACKER_ITEM.value,
                    "multiple_values": multiple_values,
                    "options": None,
                    "source_status": OptionSourceStatus.READY.value,
                    "resolver_available": True,
                    **metadata,
                }
                continue

            if resolved_field_kind == ResolvedFieldKind.MEMBER_REFERENCE.value:
                option_maps[field_name] = {
                    "kind": OptionMapKind.MEMBER_LOOKUP.value,
                    "name_map": {},
                    "reference_type": reference_type,
                    "multiple_values": multiple_values,
                    "options": None,
                    "source_status": (
                        OptionSourceStatus.LOOKUP_REQUIRED.value
                        if metadata["is_supported"]
                        else OptionSourceStatus.UNSUPPORTED.value
                    ),
                    "resolver_available": True,
                    "member_types": row.get("member_types") or [],
                    "field_id": row.get("field_id"),
                    **metadata,
                }
                continue

            if resolved_field_kind == ResolvedFieldKind.USER_REFERENCE.value:
                option_maps[field_name] = {
                    "kind": OptionMapKind.USER_LOOKUP.value,
                    "name_map": {},
                    "reference_type": reference_type,
                    "multiple_values": multiple_values,
                    "options": None,
                    "source_status": (
                        OptionSourceStatus.LOOKUP_REQUIRED.value
                        if metadata["is_supported"]
                        else OptionSourceStatus.UNSUPPORTED.value
                    ),
                    "resolver_available": True,
                    **metadata,
                }
                continue

            if resolved_field_kind == ResolvedFieldKind.GENERIC_REFERENCE.value:
                unsupported_reason = metadata["unsupported_reason"]
                if metadata["is_supported"] and not unsupported_reason:
                    unsupported_reason = "generic_reference용 resolver가 아직 구현되지 않았습니다."

                option_maps[field_name] = {
                    "kind": OptionMapKind.REFERENCE_LOOKUP.value,
                    "name_map": {},
                    "reference_type": reference_type,
                    "multiple_values": multiple_values,
                    "options": None,
                    "source_status": OptionSourceStatus.LOOKUP_REQUIRED.value,
                    "resolver_available": False,
                    **metadata,
                    "unsupported_reason": unsupported_reason,
                }
                continue

            option_maps[field_name] = {
                "kind": OptionMapKind.UNSUPPORTED.value,
                "name_map": {},
                "reference_type": reference_type,
                "multiple_values": multiple_values,
                "options": row.get("options"),
                "source_status": OptionSourceStatus.UNSUPPORTED.value,
                "resolver_available": False,
                **metadata,
            }

        return option_maps

    @staticmethod
    def _validation_context(
        df_col: str,
        schema_field: str,
        option_info: dict[str, Any],
        *,
        row_id: Any = None,
        raw_value: Any = None,
        error: str | None = None,
        value_source: str = "mapping",
    ) -> dict[str, Any]:
        """검증 결과 한 행에 공통으로 넣을 설명 정보를 만든다."""
        return {
            "df_column": df_col,
            "schema_field": schema_field,
            "_row_id": row_id,
            "raw_value": raw_value,
            "reference_type": option_info.get("reference_type"),
            "resolved_field_kind": option_info.get("resolved_field_kind"),
            "resolution_strategy": option_info.get("resolution_strategy"),
            "is_supported": option_info.get("is_supported"),
            "unsupported_reason": option_info.get("unsupported_reason"),
            "requires_lookup": option_info.get("requires_lookup"),
            "lookup_target_kind": option_info.get("lookup_target_kind"),
            "preconstruction_kind": option_info.get("preconstruction_kind"),
            "preconstruction_detail": option_info.get("preconstruction_detail"),
            "payload_target_kind": option_info.get("payload_target_kind"),
            "error": error,
            "value_source": value_source,
        }

    @staticmethod
    def resolve_static_option_value(raw_value: Any, option_info: dict[str, Any]) -> Any:
        """schema option 이름을 실제 reference payload 값으로 바꾼다."""
        if raw_value is None or str(raw_value).strip() == "":
            return None

        name_map = option_info["name_map"]
        reference_type = option_info.get("reference_type")
        multiple_values = option_info.get("multiple_values", False)

        if multiple_values and isinstance(raw_value, list):
            resolved_list = []
            for item in raw_value:
                if item is None or str(item).strip() == "":
                    continue
                key = str(item).strip()
                option = name_map.get(key)
                if option:
                    resolved_list.append({
                        "id": option.get("id"),
                        "name": option.get("name"),
                        "type": reference_type or ReferenceType.CHOICE_OPTION.value,
                    })
            return resolved_list or None

        key = str(raw_value).strip()
        option = name_map.get(key)
        if not option:
            return None
        return {
            "id": option.get("id"),
            "name": option.get("name"),
            "type": reference_type or ReferenceType.CHOICE_OPTION.value,
        }

    def check_option_alignment(
        self,
        upload_df: pd.DataFrame,
        option_mapping: dict[str, str],
        option_maps: dict[str, dict],
    ) -> pd.DataFrame:
        """업로드 데이터가 schema 규칙에 맞는지 조기에 검사한다."""
        errors = []

        for df_col, schema_field in option_mapping.items():
            if df_col not in upload_df.columns:
                errors.append({
                    "df_column": df_col,
                    "schema_field": schema_field,
                    "_row_id": None,
                    "raw_value": None,
                    "status": OptionCheckStatus.DF_COLUMN_MISSING.value,
                })
                continue

            if schema_field not in option_maps:
                errors.append({
                    "df_column": df_col,
                    "schema_field": schema_field,
                    "_row_id": None,
                    "raw_value": None,
                    "status": OptionCheckStatus.OPTION_MAP_MISSING.value,
                })
                continue

            option_info = option_maps[schema_field]

            if not option_info.get("is_supported", True) or option_info.get("kind") == OptionMapKind.UNSUPPORTED.value:
                errors.append({
                    **self._validation_context(df_col, schema_field, option_info),
                    "status": OptionCheckStatus.FIELD_UNSUPPORTED.value,
                })
                continue

            if option_info.get("preconstruction_kind") in {
                PreconstructionKind.FIELD_VALUE.value,
                PreconstructionKind.REFERENCE.value,
                PreconstructionKind.REFERENCE_LIST.value,
                PreconstructionKind.TABLE_FIELD_VALUE.value,
            }:
                errors.append({
                    **self._validation_context(df_col, schema_field, option_info),
                    "status": OptionCheckStatus.PRECONSTRUCTION_REQUIRED.value,
                })

            if option_info.get("kind") in {
                OptionMapKind.USER_LOOKUP.value,
                OptionMapKind.MEMBER_LOOKUP.value,
            }:
                resolved_col = f"{df_col}__resolved"
                status_col = f"{df_col}__lookup_status"
                error_col = f"{df_col}__lookup_error"

                for _, row in upload_df.iterrows():
                    raw_value = row[df_col]
                    if raw_value is None or str(raw_value).strip() == "":
                        continue

                    resolved_value = row.get(resolved_col) if resolved_col in row.index else None
                    if resolved_value is not None:
                        continue

                    errors.append({
                        **self._validation_context(
                            df_col,
                            schema_field,
                            option_info,
                            row_id=row.get("_row_id"),
                            raw_value=raw_value,
                            error=(row.get(error_col) if error_col in row.index else None),
                        ),
                        "status": (
                            row.get(status_col)
                            if status_col in row.index
                            else UserLookupStatus.USER_LOOKUP_NOT_RUN.value
                        ),
                    })
                continue

            if option_info.get("kind") == OptionMapKind.TRACKER_ITEM_DIRECT.value:
                resolved_col = f"{df_col}__resolved"
                status_col = f"{df_col}__lookup_status"
                error_col = f"{df_col}__lookup_error"
                tracker_item_mode = str(option_info.get("tracker_item_mode") or "")
                multiple_values = option_info.get("multiple_values", False)
                for _, row in upload_df.iterrows():
                    raw_value = row[df_col]
                    if raw_value is None or str(raw_value).strip() == "":
                        continue

                    resolved_value = row.get(resolved_col) if resolved_col in row.index else None
                    if resolved_value is not None:
                        continue

                    if tracker_item_mode == "query":
                        errors.append({
                            **self._validation_context(
                                df_col,
                                schema_field,
                                option_info,
                                row_id=row.get("_row_id"),
                                raw_value=raw_value,
                                error=(row.get(error_col) if error_col in row.index else None),
                            ),
                            "status": (
                                row.get(status_col)
                                if status_col in row.index and row.get(status_col)
                                else OptionCheckStatus.LOOKUP_REQUIRED.value
                            ),
                        })
                        continue

                    regex_pattern = str(option_info.get("tracker_item_regex_pattern") or "").strip()
                    try:
                        if regex_pattern:
                            self.resolve_tracker_item_reference_value_with_regex(
                                raw_value,
                                multiple_values=multiple_values,
                                pattern=regex_pattern,
                            )
                        else:
                            self.resolve_tracker_item_reference_value(
                                raw_value,
                                multiple_values=multiple_values,
                            )
                    except Exception as exc:
                        errors.append({
                            **self._validation_context(
                                df_col,
                                schema_field,
                                option_info,
                                row_id=row.get("_row_id"),
                                raw_value=raw_value,
                                error=str(exc),
                            ),
                            "status": (
                                OptionCheckStatus.DIRECT_PARSE_FAILED.value
                                if regex_pattern or "tracker_item_mode" not in option_info
                                else OptionCheckStatus.TRACKER_ITEM_REGEX_MISSING.value
                            ),
                        })
                continue

            if option_info.get("kind") == OptionMapKind.REFERENCE_LOOKUP.value:
                errors.append({
                    **self._validation_context(
                        df_col,
                        schema_field,
                        option_info,
                        error=option_info.get("unsupported_reason")
                        or "generic_reference lookup resolver가 아직 구현되지 않았습니다.",
                    ),
                    "status": OptionCheckStatus.LOOKUP_REQUIRED.value,
                })
                continue

            if option_info.get("kind") != OptionMapKind.STATIC_OPTIONS.value:
                errors.append({
                    **self._validation_context(df_col, schema_field, option_info),
                    "status": OptionCheckStatus.OPTION_SOURCE_UNAVAILABLE.value,
                })
                continue

            name_map = option_info["name_map"]
            multiple_values = option_info.get("multiple_values", False)

            for _, row in upload_df.iterrows():
                raw_value = row[df_col]
                if raw_value is None or str(raw_value).strip() == "":
                    continue

                if multiple_values and isinstance(raw_value, list):
                    for val in raw_value:
                        if not val:
                            continue
                        key = str(val).strip()
                        if key not in name_map:
                            errors.append({
                                **self._validation_context(
                                    df_col,
                                    schema_field,
                                    option_info,
                                    row_id=row.get("_row_id"),
                                    raw_value=val,
                                ),
                                "status": OptionCheckStatus.OPTION_NOT_FOUND.value,
                            })
                else:
                    key = str(raw_value).strip()
                    if key not in name_map:
                        errors.append({
                            **self._validation_context(
                                df_col,
                                schema_field,
                                option_info,
                                row_id=row.get("_row_id"),
                                raw_value=raw_value,
                            ),
                            "status": OptionCheckStatus.OPTION_NOT_FOUND.value,
                        })

        return pd.DataFrame(errors)

    def apply_option_resolution(
        self,
        upload_df: pd.DataFrame,
        option_mapping: dict[str, str],
        option_maps: dict[str, dict],
    ) -> pd.DataFrame:
        """정적으로 해결 가능한 옵션 값을 실제 reference payload 값으로 바꾼다."""
        work = upload_df.copy()

        for df_col, schema_field in option_mapping.items():
            if df_col not in work.columns or schema_field not in option_maps:
                continue

            option_info = option_maps[schema_field]
            if option_info.get("kind") == OptionMapKind.TRACKER_ITEM_DIRECT.value:
                resolved_col = f"{df_col}__resolved"
                if resolved_col in work.columns:
                    continue
                resolved_values = []
                multiple_values = option_info.get("multiple_values", False)
                regex_pattern = str(option_info.get("tracker_item_regex_pattern") or "").strip()

                for _, row in work.iterrows():
                    raw_value = row[df_col]
                    if raw_value is None or str(raw_value).strip() == "":
                        resolved_values.append(None)
                        continue

                    try:
                        resolved_values.append(
                            self.resolve_tracker_item_reference_value_with_regex(
                                raw_value,
                                multiple_values=multiple_values,
                                pattern=regex_pattern,
                            ) if regex_pattern else self.resolve_tracker_item_reference_value(
                                raw_value,
                                multiple_values=multiple_values,
                            )
                        )
                    except Exception:
                        resolved_values.append(None)

                work[f"{df_col}__resolved"] = resolved_values
                continue

            if option_info.get("kind") in {
                OptionMapKind.USER_LOOKUP.value,
                OptionMapKind.MEMBER_LOOKUP.value,
            }:
                resolved_col = f"{df_col}__resolved"
                if resolved_col not in work.columns:
                    work[resolved_col] = [None] * len(work)
                continue

            if option_info.get("kind") != OptionMapKind.STATIC_OPTIONS.value:
                work[f"{df_col}__resolved"] = [None] * len(work)
                continue

            resolved_values = []
            for _, row in work.iterrows():
                raw_value = row[df_col]
                if raw_value is None or str(raw_value).strip() == "":
                    resolved_values.append(None)
                    continue

                resolved_values.append(self.resolve_static_option_value(raw_value, option_info))

            work[f"{df_col}__resolved"] = resolved_values

        return work
