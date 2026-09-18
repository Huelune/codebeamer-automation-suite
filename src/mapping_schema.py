from __future__ import annotations

from typing import Any

import pandas as pd

from .models import CONNECTED_FIELD_TYPE_VALUE_MODEL_MAP
from .models import FieldValueType
from .models import LookupTargetKind
from .models import MappingStatus
from .models import OptionMapKind
from .models import OptionSourceKind
from .models import PayloadTargetKind
from .models import PreconstructionKind
from .models import ReferenceType
from .models import ResolutionStrategy
from .models import ResolvedFieldKind
from .models import SchemaFieldType
from .models import TrackerItemBase


class MappingSchemaMixin:
    @classmethod
    def _resolve_payload_target_kind(cls, field: dict[str, Any]) -> str:
        """이 필드가 builtin field인지 custom field인지 먼저 판정한다."""
        tracker_item_field = field.get("trackerItemField")
        if TrackerItemBase.has_builtin_field(tracker_item_field):
            return PayloadTargetKind.BUILTIN_FIELD.value
        if field.get("id") is not None and field.get("name"):
            return PayloadTargetKind.CUSTOM_FIELD.value
        return PayloadTargetKind.UNSUPPORTED.value

    @classmethod
    def _reference_detail(cls, resolved_field_kind: str, field: dict[str, Any]) -> str:
        """reference 계열 필드가 실제로 어떤 참조 객체를 요구하는지 설명 문자열로 만든다."""
        if resolved_field_kind == ResolvedFieldKind.STATIC_OPTION.value:
            return field.get("referenceType") or ReferenceType.CHOICE_OPTION.value
        if resolved_field_kind == ResolvedFieldKind.MEMBER_REFERENCE.value:
            return ReferenceType.ABSTRACT.value
        if resolved_field_kind == ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value:
            return ReferenceType.TRACKER_ITEM.value
        if resolved_field_kind == ResolvedFieldKind.USER_REFERENCE.value:
            return ReferenceType.USER.value
        if field.get("referenceType"):
            return str(field["referenceType"])
        return "generic reference candidate"

    @classmethod
    def _field_value_detail(cls, resolved_field_kind: str, field: dict[str, Any]) -> str:
        """custom field가 필요로 하는 FieldValue 종류를 사람이 읽기 쉬운 문자열로 만든다."""
        if resolved_field_kind in {
            ResolvedFieldKind.MEMBER_REFERENCE.value,
            ResolvedFieldKind.STATIC_OPTION.value,
            ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value,
            ResolvedFieldKind.USER_REFERENCE.value,
            ResolvedFieldKind.GENERIC_REFERENCE.value,
        }:
            return f"{FieldValueType.CHOICE.value}<{cls._reference_detail(resolved_field_kind, field)}>"

        field_type = field.get("field_type") or field.get("type")
        if field_type in CONNECTED_FIELD_TYPE_VALUE_MODEL_MAP:
            return CONNECTED_FIELD_TYPE_VALUE_MODEL_MAP[field_type]

        value_model = field.get("valueModel")
        if isinstance(value_model, str) and value_model.endswith("FieldValue"):
            return value_model
        return FieldValueType.TEXT.value

    @classmethod
    def _resolve_field_kind(cls, field: dict[str, Any]) -> dict[str, Any]:
        """raw schema field를 내부 분류 체계로 해석한다."""
        field_type = field.get("type")
        reference_type = field.get("referenceType")
        has_options = bool(field.get("options"))
        value_model = field.get("valueModel")
        tracker_item_field = field.get("trackerItemField", field.get("name"))
        payload_target_kind = cls._resolve_payload_target_kind(field)

        result = {
            "resolved_field_kind": ResolvedFieldKind.UNSUPPORTED.value,
            "resolution_strategy": ResolutionStrategy.UNKNOWN_TYPE.value,
            "is_supported": payload_target_kind != PayloadTargetKind.UNSUPPORTED.value,
            "unsupported_reason": None,
            "payload_target_kind": payload_target_kind,
        }

        if payload_target_kind == PayloadTargetKind.UNSUPPORTED.value:
            result["unsupported_reason"] = (
                "trackerItemField가 builtin field로 해석되지 않았고 custom field로도 판정할 수 없습니다."
            )

        if field_type == SchemaFieldType.TABLE.value:
            result["resolved_field_kind"] = ResolvedFieldKind.TABLE.value
            result["resolution_strategy"] = ResolutionStrategy.TYPE_TABLE.value
            return result

        if field_type == SchemaFieldType.BOOL.value:
            result["resolved_field_kind"] = ResolvedFieldKind.SCALAR_BOOL.value
            result["resolution_strategy"] = ResolutionStrategy.TYPE_BOOL.value
            return result

        if field_type == SchemaFieldType.OPTION_CHOICE.value:
            if has_options:
                result["resolved_field_kind"] = ResolvedFieldKind.STATIC_OPTION.value
                result["resolution_strategy"] = ResolutionStrategy.TYPE_OPTION_WITH_OPTIONS.value
                return result
            if reference_type == ReferenceType.USER.value:
                result["resolved_field_kind"] = ResolvedFieldKind.USER_REFERENCE.value
                result["resolution_strategy"] = ResolutionStrategy.TYPE_OPTION_WITH_USER_REFERENCE.value
                return result
            if reference_type:
                result["resolved_field_kind"] = ResolvedFieldKind.GENERIC_REFERENCE.value
                result["resolution_strategy"] = ResolutionStrategy.TYPE_OPTION_WITH_REFERENCE_TYPE.value
                return result

            result["resolved_field_kind"] = ResolvedFieldKind.UNSUPPORTED.value
            result["resolution_strategy"] = ResolutionStrategy.TYPE_OPTION_AMBIGUOUS.value
            result["is_supported"] = False
            if cls._is_choice_value_model(value_model):
                result["unsupported_reason"] = (
                    "OptionChoiceField인데 options/referenceType이 없고 valueModel만 choice 계열이라 확정할 수 없습니다."
                )
            else:
                result["unsupported_reason"] = (
                    "OptionChoiceField인데 options와 referenceType이 모두 없어 안전하게 해석할 수 없습니다."
                )
            return result

        if field_type == SchemaFieldType.USER_CHOICE.value:
            result["resolved_field_kind"] = ResolvedFieldKind.USER_REFERENCE.value
            result["resolution_strategy"] = ResolutionStrategy.TYPE_REFERENCE_WITH_USER_REFERENCE.value
            return result

        if field_type == SchemaFieldType.TRACKER_ITEM_CHOICE.value:
            result["resolved_field_kind"] = ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value
            result["resolution_strategy"] = ResolutionStrategy.TYPE_TRACKER_ITEM_CHOICE.value
            return result

        if field_type == SchemaFieldType.MEMBER.value:
            result["resolved_field_kind"] = ResolvedFieldKind.MEMBER_REFERENCE.value
            result["resolution_strategy"] = ResolutionStrategy.TYPE_MEMBER.value
            return result

        if field_type == SchemaFieldType.REFERENCE.value:
            if reference_type == ReferenceType.USER.value:
                result["resolved_field_kind"] = ResolvedFieldKind.USER_REFERENCE.value
                result["resolution_strategy"] = ResolutionStrategy.TYPE_REFERENCE_WITH_USER_REFERENCE.value
                return result
            if (
                reference_type == ReferenceType.TRACKER_ITEM.value
                and payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value
                and TrackerItemBase.has_builtin_field(tracker_item_field)
            ):
                result["resolved_field_kind"] = ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value
                result["resolution_strategy"] = ResolutionStrategy.TYPE_REFERENCE_WITH_REFERENCE_TYPE.value
                return result
            if reference_type:
                result["resolved_field_kind"] = ResolvedFieldKind.GENERIC_REFERENCE.value
                result["resolution_strategy"] = ResolutionStrategy.TYPE_REFERENCE_WITH_REFERENCE_TYPE.value
                return result

            result["resolved_field_kind"] = ResolvedFieldKind.GENERIC_REFERENCE.value
            result["resolution_strategy"] = ResolutionStrategy.TYPE_REFERENCE_WITHOUT_REFERENCE_TYPE.value
            result["is_supported"] = False
            result["unsupported_reason"] = (
                "ReferenceField인데 referenceType이 없어 어떤 reference 객체를 구성해야 하는지 확정할 수 없습니다."
            )
            return result

        if cls._is_choice_value_model(value_model):
            result["resolved_field_kind"] = ResolvedFieldKind.UNSUPPORTED.value
            result["resolution_strategy"] = ResolutionStrategy.UNKNOWN_TYPE.value
            result["is_supported"] = False
            result["unsupported_reason"] = (
                "valueModel이 choice 계열이지만 type/options/referenceType 조합이 없어 보조 신호만으로는 해석할 수 없습니다."
            )
            return result

        result["resolved_field_kind"] = ResolvedFieldKind.SCALAR_TEXT.value
        result["resolution_strategy"] = (
            ResolutionStrategy.BUILTIN_SCALAR.value
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value
            else ResolutionStrategy.CUSTOM_SCALAR.value
        )
        return result

    @classmethod
    def _resolve_preconstruction(cls, field_resolution: dict[str, Any]) -> dict[str, Any]:
        """payload를 만들기 전에 무엇을 먼저 준비해야 하는지 규칙을 정한다."""
        resolved_field_kind = field_resolution["resolved_field_kind"]
        payload_target_kind = field_resolution["payload_target_kind"]
        multiple_values = cls._is_truthy_flag(field_resolution.get("multiple_values"))
        is_supported = field_resolution.get("is_supported", True)
        unsupported_reason = field_resolution.get("unsupported_reason")

        result = {
            "requires_lookup": False,
            "lookup_target_kind": LookupTargetKind.NONE.value,
            "preconstruction_kind": PreconstructionKind.NONE.value,
            "preconstruction_detail": None,
            "payload_target_kind": payload_target_kind,
            "is_supported": is_supported,
            "unsupported_reason": unsupported_reason,
        }

        if payload_target_kind == PayloadTargetKind.UNSUPPORTED.value:
            return result

        if resolved_field_kind == ResolvedFieldKind.TABLE.value:
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["is_supported"] = False
                result["unsupported_reason"] = (
                    result["unsupported_reason"] or "TableField는 builtin field에 직접 매핑할 수 없습니다."
                )
                return result
            result["preconstruction_kind"] = PreconstructionKind.TABLE_FIELD_VALUE.value
            result["preconstruction_detail"] = FieldValueType.TABLE.value
            return result

        if resolved_field_kind == ResolvedFieldKind.SCALAR_BOOL.value:
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["preconstruction_kind"] = PreconstructionKind.BUILTIN_DIRECT.value
                result["preconstruction_detail"] = "bool"
            else:
                result["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                result["preconstruction_detail"] = FieldValueType.BOOL.value
            return result

        if resolved_field_kind == ResolvedFieldKind.SCALAR_TEXT.value:
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["preconstruction_kind"] = PreconstructionKind.BUILTIN_DIRECT.value
                result["preconstruction_detail"] = (
                    field_resolution.get("tracker_item_field") or "builtin scalar"
                )
            else:
                result["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                result["preconstruction_detail"] = cls._field_value_detail(
                    resolved_field_kind,
                    field_resolution,
                )
            return result

        if resolved_field_kind == ResolvedFieldKind.STATIC_OPTION.value:
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["preconstruction_kind"] = (
                    PreconstructionKind.REFERENCE_LIST.value
                    if multiple_values
                    else PreconstructionKind.REFERENCE.value
                )
                result["preconstruction_detail"] = cls._reference_detail(resolved_field_kind, field_resolution)
            else:
                result["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                result["preconstruction_detail"] = cls._field_value_detail(
                    resolved_field_kind,
                    field_resolution,
                )
            return result

        if resolved_field_kind == ResolvedFieldKind.USER_REFERENCE.value:
            result["requires_lookup"] = True
            result["lookup_target_kind"] = LookupTargetKind.USER.value
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["preconstruction_kind"] = (
                    PreconstructionKind.REFERENCE_LIST.value
                    if multiple_values
                    else PreconstructionKind.REFERENCE.value
                )
                result["preconstruction_detail"] = ReferenceType.USER.value
            else:
                result["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                result["preconstruction_detail"] = cls._field_value_detail(
                    resolved_field_kind,
                    field_resolution,
                )
            return result

        if resolved_field_kind == ResolvedFieldKind.MEMBER_REFERENCE.value:
            result["requires_lookup"] = True
            result["lookup_target_kind"] = LookupTargetKind.MEMBER.value
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["preconstruction_kind"] = (
                    PreconstructionKind.REFERENCE_LIST.value
                    if multiple_values
                    else PreconstructionKind.REFERENCE.value
                )
                result["preconstruction_detail"] = ReferenceType.ABSTRACT.value
            else:
                result["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                result["preconstruction_detail"] = cls._field_value_detail(
                    resolved_field_kind,
                    field_resolution,
                )
            return result

        if resolved_field_kind == ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value:
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["preconstruction_kind"] = (
                    PreconstructionKind.REFERENCE_LIST.value
                    if multiple_values
                    else PreconstructionKind.REFERENCE.value
                )
                result["preconstruction_detail"] = ReferenceType.TRACKER_ITEM.value
            else:
                result["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                result["preconstruction_detail"] = cls._field_value_detail(
                    resolved_field_kind,
                    field_resolution,
                )
            return result

        if resolved_field_kind == ResolvedFieldKind.GENERIC_REFERENCE.value:
            result["requires_lookup"] = True
            result["lookup_target_kind"] = LookupTargetKind.REFERENCE.value
            if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
                result["preconstruction_kind"] = (
                    PreconstructionKind.REFERENCE_LIST.value
                    if multiple_values
                    else PreconstructionKind.REFERENCE.value
                )
                result["preconstruction_detail"] = cls._reference_detail(resolved_field_kind, field_resolution)
            else:
                result["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                result["preconstruction_detail"] = cls._field_value_detail(
                    resolved_field_kind,
                    field_resolution,
                )
            return result

        return result

    @classmethod
    def _is_option_like_field(cls, field: pd.Series | dict[str, Any]) -> bool:
        """이 필드가 옵션 또는 참조 해석 과정을 거쳐야 하는지 판정한다."""
        getter = field.get
        resolved_field_kind = getter("resolved_field_kind")
        if resolved_field_kind in {
            ResolvedFieldKind.MEMBER_REFERENCE.value,
            ResolvedFieldKind.STATIC_OPTION.value,
            ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value,
            ResolvedFieldKind.USER_REFERENCE.value,
            ResolvedFieldKind.GENERIC_REFERENCE.value,
        }:
            return True

        has_options = bool(getter("has_options", False) or getter("options", []))
        reference_type = getter("reference_type") or getter("referenceType")
        value_model = getter("value_model") or getter("valueModel")
        field_type = getter("field_type") or getter("type")
        return (
            has_options
            or bool(reference_type)
            or cls._is_choice_value_model(value_model)
            or field_type in {SchemaFieldType.REFERENCE.value, SchemaFieldType.OPTION_CHOICE.value}
        )

    @classmethod
    def _detect_option_source_kind(cls, field: pd.Series | dict[str, Any]) -> str | None:
        """옵션 값을 어디서 해결해야 하는지 출처 종류를 정한다."""
        getter = field.get
        resolved_field_kind = getter("resolved_field_kind")
        if resolved_field_kind == ResolvedFieldKind.STATIC_OPTION.value:
            return OptionSourceKind.SCHEMA_OPTIONS.value
        if resolved_field_kind == ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value:
            return OptionSourceKind.DIRECT_PARSE.value
        if resolved_field_kind in {
            ResolvedFieldKind.MEMBER_REFERENCE.value,
            ResolvedFieldKind.USER_REFERENCE.value,
            ResolvedFieldKind.GENERIC_REFERENCE.value,
        }:
            return OptionSourceKind.REFERENCE_LOOKUP.value
        if cls._is_option_like_field(field):
            return OptionSourceKind.UNSUPPORTED.value
        return None

    def flatten_schema_fields(self, schema: dict | list) -> pd.DataFrame:
        """복잡한 schema JSON을 분석하기 쉬운 표 형태로 펼친다."""
        candidates = []

        if isinstance(schema, list):
            candidates = schema
        elif isinstance(schema, dict):
            for key in ["fieldDefinitions", "fields"]:
                if key in schema and isinstance(schema[key], list):
                    candidates = schema[key]
                    break

        all_status_option_ids = self._extract_status_option_ids(candidates)
        rows = []
        for field in candidates:
            options = field.get("options", [])
            has_options = len(options) > 0
            is_table_field = field.get("type") == SchemaFieldType.TABLE.value
            columns = field.get("columns", []) if is_table_field else None
            reference_type = field.get("referenceType")
            value_model = field.get("valueModel")
            multiple_values = self._is_truthy_flag(field.get("multipleValues"))
            mandatory_meta = self._build_mandatory_metadata(field, all_status_option_ids)

            if columns:
                columns = [
                    {
                        **column,
                        **self._build_mandatory_metadata(column, all_status_option_ids),
                    }
                    for column in columns
                ]

            row = {
                "field_id": field.get("id"),
                "field_name": field.get("name"),
                "field_label": field.get("label") or field.get("title"),
                "field_type": field.get("type"),
                "mandatory": mandatory_meta["mandatory"],
                "mandatory_mode": mandatory_meta["mandatory_mode"],
                "mandatory_statuses": mandatory_meta["mandatory_statuses"],
                "mandatory_status_names": mandatory_meta["mandatory_status_names"],
                "tracker_item_field": field.get("trackerItemField", field.get("name", None)),
                "raw_tracker_item_field": field.get("trackerItemField"),
                "value_model": value_model,
                "reference_type": reference_type,
                "member_types": field.get("memberTypes") or [],
                "has_options": has_options,
                "multiple_values": multiple_values,
                "options": options if has_options else None,
                "is_table_field": is_table_field,
                "table_columns": columns,
                "raw": field,
            }
            row.update(self._resolve_field_kind(field))
            row.update(self._resolve_preconstruction(row))
            row["is_option_like"] = self._is_option_like_field(row)
            row["option_source_kind"] = self._detect_option_source_kind(row)
            rows.append(row)

        return pd.DataFrame(rows)

    def compare_upload_df_with_schema(
        self,
        upload_df: pd.DataFrame,
        schema_df: pd.DataFrame,
        selected_mapping: dict[str, str],
    ) -> pd.DataFrame:
        """업로드 컬럼과 schema 필드를 비교해 위험 요소를 한 표로 정리한다."""
        schema_field_names = set(schema_df["field_name"].dropna().astype(str).str.strip())
        upload_columns = set(upload_df.columns)

        rows = []
        for df_col in sorted(upload_columns):
            mapped_schema_field = selected_mapping.get(df_col)
            schema_exists = mapped_schema_field in schema_field_names if mapped_schema_field else False

            row = {
                "df_column": df_col,
                "selected_schema_field": mapped_schema_field,
                "df_exists": True,
                "schema_field_exists": schema_exists,
                "status": (
                    MappingStatus.UNMAPPED.value
                    if not mapped_schema_field
                    else (
                        MappingStatus.OK.value
                        if schema_exists
                        else MappingStatus.SCHEMA_FIELD_MISSING.value
                    )
                ),
            }

            if mapped_schema_field and schema_exists:
                matched = schema_df[schema_df["field_name"] == mapped_schema_field]
                if not matched.empty:
                    match = matched.iloc[0]
                    row["field_id"] = match["field_id"]
                    row["field_label"] = match.get("field_label")
                    row["field_type"] = match["field_type"]
                    row["mandatory"] = match["mandatory"]
                    row["mandatory_mode"] = match.get("mandatory_mode")
                    row["mandatory_status_names"] = match.get("mandatory_status_names")
                    row["value_model"] = match["value_model"]
                    row["reference_type"] = match.get("reference_type")
                    row["hidden"] = match.get("raw", {}).get("hidden", False)
                    row["is_option_field"] = bool(match.get("is_option_like", False))
                    row["option_source_kind"] = match.get("option_source_kind")
                    row["tracker_item_field"] = match.get("tracker_item_field")
                    row["resolved_field_kind"] = match.get("resolved_field_kind")
                    row["resolution_strategy"] = match.get("resolution_strategy")
                    row["is_supported"] = match.get("is_supported")
                    row["unsupported_reason"] = match.get("unsupported_reason")
                    row["requires_lookup"] = match.get("requires_lookup")
                    row["lookup_target_kind"] = match.get("lookup_target_kind")
                    row["preconstruction_kind"] = match.get("preconstruction_kind")
                    row["preconstruction_detail"] = match.get("preconstruction_detail")
                    row["payload_target_kind"] = match.get("payload_target_kind")

            rows.append(row)

        return pd.DataFrame(rows)

    def get_option_field_candidates(self, schema_df: pd.DataFrame) -> pd.DataFrame:
        """옵션 또는 참조 해석이 필요한 schema 필드만 골라낸다."""
        if "is_option_like" in schema_df.columns:
            mask = schema_df["is_option_like"].fillna(False)
            return schema_df[mask].copy()

        mask = schema_df.apply(self._is_option_like_field, axis=1)
        return schema_df[mask].copy()

    def get_list_columns_for_mapping(
        self,
        selected_mapping: dict[str, str],
        schema_df: pd.DataFrame,
    ) -> list[str]:
        """`multipleValues=true` 필드에 연결된 Excel 컬럼만 추려낸다."""
        if schema_df.empty or not selected_mapping:
            return []

        multiple_value_fields = {
            row["field_name"]
            for _, row in schema_df.iterrows()
            if row.get("field_name") and self._is_truthy_flag(row.get("multiple_values"))
        }
        table_fields = {
            row["field_name"]
            for _, row in schema_df.iterrows()
            if row.get("field_name") and self._is_truthy_flag(row.get("is_table_field"))
        }

        return [
            df_col
            for df_col, schema_field in selected_mapping.items()
            if (
                schema_field in multiple_value_fields
                or (
                    schema_field in table_fields
                    and "." in str(df_col)
                )
            )
        ]

    def get_default_value_candidates(self, schema_df: pd.DataFrame) -> list[dict[str, Any]]:
        """공통 기본값으로 선택할 수 있는 단일 static option 필드 목록을 만든다."""
        if schema_df.empty:
            return []

        option_maps = self.build_option_maps_from_schema(schema_df)
        candidates: list[dict[str, Any]] = []

        for _, row in schema_df.iterrows():
            field_name = str(row.get("field_name") or "").strip()
            if not field_name:
                continue
            if self._is_truthy_flag(row.get("multiple_values")):
                continue

            option_info = option_maps.get(field_name)
            if not option_info or option_info.get("kind") != OptionMapKind.STATIC_OPTIONS.value:
                continue

            option_names = [
                str(option.get("name")).strip()
                for option in option_info.get("options") or []
                if option.get("name")
            ]
            if not option_names:
                continue

            candidates.append({
                "field_name": field_name,
                "field_type": row.get("field_type"),
                "tracker_item_field": row.get("tracker_item_field"),
                "mandatory": bool(row.get("mandatory", False)),
                "options": option_names,
            })

        return candidates
