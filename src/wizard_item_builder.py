from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from .models import DomainModel
from .models import FieldValueType
from .models import OptionCheckStatus
from .models import OptionMapKind
from .models import ReferenceType
from .models import ResolvedFieldKind
from .models import TableFieldValue
from .models import TrackerItemBase
from .models import UserLookupStatus
from .models.field_values import _build_field_value
from .upload_policy import scope_applies_to_operation


DEFAULT_VALUE_COLUMN_LABEL = "(기본값)"


class WizardItemBuilderService:
    """schema와 해석된 값을 create/root item payload 모델로 조립한다."""

    def __init__(
        self,
        *,
        state: Any,
        mapper: Any,
        resolve_tracker_item_reference_value: Callable[..., Any],
        resolve_user_reference_value: Callable[..., Any],
        resolve_member_reference_value: Callable[..., Any],
    ) -> None:
        self.state = state
        self.mapper = mapper
        self._resolve_tracker_item_reference_value = resolve_tracker_item_reference_value
        self._resolve_user_reference_value = resolve_user_reference_value
        self._resolve_member_reference_value = resolve_member_reference_value

    def _serialize_payload_value(self, value: Any) -> Any:
        """payload 안의 모델 객체를 재귀적으로 일반 자료형으로 바꾼다."""
        if isinstance(value, DomainModel):
            return value.to_dict()
        if isinstance(value, list):
            return [self._serialize_payload_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._serialize_payload_value(item) for key, item in value.items()}
        return value

    @staticmethod
    def _has_row_value(row: pd.Series, column_name: str) -> bool:
        """행 안에 실제로 업로드할 값이 들어 있는지 확인한다."""
        if column_name not in row.index:
            return False

        value = row[column_name]
        if value is None:
            return False
        if isinstance(value, float) and pd.isna(value):
            return False
        return not (isinstance(value, str) and value.strip() == "")

    @staticmethod
    def _has_configured_value(value: Any) -> bool:
        """기본값 설정에 실제 값이 들어 있는지 확인한다."""
        if value is None:
            return False
        if isinstance(value, float) and pd.isna(value):
            return False
        return not (isinstance(value, str) and value.strip() == "")

    @staticmethod
    def _schema_field_info(field_row: pd.Series, schema_field: str) -> dict[str, Any]:
        """schema 비교 행에서 payload 생성에 필요한 정보만 골라낸다."""
        reference_type = field_row.get("reference_type")
        resolved_field_kind = field_row.get("resolved_field_kind")

        if not reference_type and resolved_field_kind == ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value:
            reference_type = ReferenceType.TRACKER_ITEM.value
        if not reference_type and resolved_field_kind == ResolvedFieldKind.USER_REFERENCE.value:
            reference_type = ReferenceType.USER.value
        if not reference_type and resolved_field_kind == ResolvedFieldKind.MEMBER_REFERENCE.value:
            reference_type = ReferenceType.ABSTRACT.value

        return {
            "field_id": field_row.get("field_id"),
            "field_type": field_row.get("field_type"),
            "field_name": schema_field,
            "multiple_values": field_row.get("multiple_values", False),
            "reference_type": reference_type,
            "value_model": field_row.get("value_model"),
            "resolved_field_kind": resolved_field_kind,
            "resolution_strategy": field_row.get("resolution_strategy"),
            "is_supported": field_row.get("is_supported", True),
            "unsupported_reason": field_row.get("unsupported_reason"),
            "requires_lookup": field_row.get("requires_lookup", False),
            "lookup_target_kind": field_row.get("lookup_target_kind"),
            "preconstruction_kind": field_row.get("preconstruction_kind"),
            "preconstruction_detail": field_row.get("preconstruction_detail"),
            "payload_target_kind": field_row.get("payload_target_kind"),
            "tracker_item_field": field_row.get("tracker_item_field"),
        }

    @staticmethod
    def _raise_payload_error(
        code: str,
        *,
        schema_field: str,
        row_id: int,
        df_col: str,
        detail: str,
    ) -> None:
        """payload 생성 중 발생한 구조화된 오류를 같은 형식으로 만든다."""
        raise ValueError(
            f"[{code}] field='{schema_field}' df_column='{df_col}' _row_id={row_id} {detail}"
        )

    def _ensure_field_ready_for_payload(
        self,
        *,
        field_row: pd.Series,
        schema_field: str,
        df_col: str,
        row_id: int,
    ) -> None:
        """현재 field가 업로드 가능한 상태인지 payload 생성 전에 점검한다."""
        if not field_row.get("is_supported", True):
            self._raise_payload_error(
                "FIELD_UNSUPPORTED",
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=(
                    f"reason={field_row.get('unsupported_reason')!r} "
                    f"strategy={field_row.get('resolution_strategy')!r} "
                    f"payload_target={field_row.get('payload_target_kind')!r} "
                    f"preconstruction={field_row.get('preconstruction_kind')!r}"
                ),
            )

        if field_row.get("requires_lookup") and df_col not in self.state.selected_option_mapping:
            self._raise_payload_error(
                "LOOKUP_REQUIRED",
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=(
                    f"lookup_target={field_row.get('lookup_target_kind')!r} "
                    f"preconstruction={field_row.get('preconstruction_kind')!r} "
                    f"detail={field_row.get('preconstruction_detail')!r}"
                ),
            )

    def _resolve_option_field_value(self, row: pd.Series, row_id: int, df_col: str, schema_field: str) -> Any:
        """옵션 또는 참조형 필드의 실제 업로드 값을 `__resolved` 기준으로 꺼낸다."""
        option_info = (self.state.option_maps or {}).get(schema_field, {})
        resolved_col = f"{df_col}__resolved"
        status_col = f"{df_col}__lookup_status"
        error_col = f"{df_col}__lookup_error"

        if not option_info.get("is_supported", True) or option_info.get("kind") == OptionMapKind.UNSUPPORTED.value:
            self._raise_payload_error(
                "FIELD_UNSUPPORTED",
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=(
                    f"reason={option_info.get('unsupported_reason')!r} "
                    f"strategy={option_info.get('resolution_strategy')!r} "
                    f"preconstruction={option_info.get('preconstruction_kind')!r}"
                ),
            )

        if resolved_col in row.index and row[resolved_col] is not None:
            return row[resolved_col]

        if not self._has_row_value(row, df_col):
            return None

        if option_info.get("kind") in {
            OptionMapKind.USER_LOOKUP.value,
            OptionMapKind.MEMBER_LOOKUP.value,
        }:
            lookup_status = (
                row[status_col]
                if status_col in row.index
                else UserLookupStatus.USER_LOOKUP_NOT_RUN.value
            )
            lookup_error = row[error_col] if error_col in row.index else None
            detail = (
                f"value={row[df_col]!r} lookup_status={lookup_status!r} "
                f"preconstruction={option_info.get('preconstruction_kind')!r}"
            )
            if lookup_error:
                detail = f"{detail} error={lookup_error!r}"
            self._raise_payload_error(
                "LOOKUP_REQUIRED",
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=detail,
            )

        if option_info.get("kind") == OptionMapKind.TRACKER_ITEM_DIRECT.value:
            resolved, lookup_status, lookup_error = self._resolve_tracker_item_reference_value(
                schema_field,
                row[df_col],
                option_info,
            )
            if resolved is not None:
                return resolved
            error_code = (
                "DIRECT_PARSE_FAILED"
                if lookup_status in {
                    OptionCheckStatus.DIRECT_PARSE_FAILED.value,
                    OptionCheckStatus.TRACKER_ITEM_REGEX_MISSING.value,
                }
                else "LOOKUP_REQUIRED"
            )
            detail = f"value={row[df_col]!r} lookup_status={lookup_status!r}"
            if lookup_error:
                detail = f"{detail} error={lookup_error!r}"
            self._raise_payload_error(
                error_code,
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=detail,
            )

        if option_info.get("kind") == OptionMapKind.REFERENCE_LOOKUP.value:
            self._raise_payload_error(
                "LOOKUP_REQUIRED",
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=(
                    f"reference_type={option_info.get('reference_type')!r} "
                    f"lookup_target={option_info.get('lookup_target_kind')!r} "
                    f"preconstruction={option_info.get('preconstruction_kind')!r} "
                    f"detail={option_info.get('preconstruction_detail')!r} "
                    f"reason={option_info.get('unsupported_reason')!r}"
                ),
            )

        self._raise_payload_error(
            "OPTION_RESOLUTION_FAILED",
            schema_field=schema_field,
            df_col=df_col,
            row_id=row_id,
            detail=f"value={row[df_col]!r}",
        )
        return None

    def _resolve_default_field_values(
        self,
        selected_default_values: dict[str, Any],
        option_maps: dict[str, dict[str, Any]],
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """필드 기본값을 검증하고 payload에 바로 쓸 값으로 정리한다."""
        if self.state.schema_df is None or not selected_default_values:
            return pd.DataFrame(), {}

        errors: list[dict[str, Any]] = []
        resolved_defaults: dict[str, Any] = {}

        for schema_field, raw_value in selected_default_values.items():
            matched = self.state.schema_df[self.state.schema_df["field_name"] == schema_field]
            if matched.empty:
                errors.append({
                    "df_column": DEFAULT_VALUE_COLUMN_LABEL,
                    "schema_field": schema_field,
                    "_row_id": None,
                    "raw_value": raw_value,
                    "status": "SCHEMA_FIELD_MISSING",
                    "value_source": "default",
                    "error": "선택한 기본값 필드를 현재 트래커 스키마에서 찾을 수 없습니다.",
                })
                continue

            field_row = matched.iloc[0]
            if not bool(field_row.get("is_option_like", False)):
                resolved_defaults[schema_field] = raw_value
                continue

            option_info = option_maps.get(schema_field)
            if option_info is None:
                errors.append({
                    "df_column": DEFAULT_VALUE_COLUMN_LABEL,
                    "schema_field": schema_field,
                    "_row_id": None,
                    "raw_value": raw_value,
                    "status": "OPTION_MAP_MISSING",
                    "value_source": "default",
                    "error": "기본값에 필요한 option map을 만들 수 없습니다.",
                })
                continue

            if not option_info.get("is_supported", True) or option_info.get("kind") == OptionMapKind.UNSUPPORTED.value:
                errors.append({
                    **self.mapper._validation_context(
                        DEFAULT_VALUE_COLUMN_LABEL,
                        schema_field,
                        option_info,
                        raw_value=raw_value,
                        error=option_info.get("unsupported_reason"),
                        value_source="default",
                    ),
                    "status": "FIELD_UNSUPPORTED",
                })
                continue

            if option_info.get("kind") == OptionMapKind.STATIC_OPTIONS.value:
                resolved_value = self.mapper.resolve_static_option_value(raw_value, option_info)
                if resolved_value is None:
                    errors.append({
                        **self.mapper._validation_context(
                            DEFAULT_VALUE_COLUMN_LABEL,
                            schema_field,
                            option_info,
                            raw_value=raw_value,
                            value_source="default",
                        ),
                        "status": "OPTION_NOT_FOUND",
                    })
                    continue
                resolved_defaults[schema_field] = resolved_value
                continue

            if option_info.get("kind") == OptionMapKind.TRACKER_ITEM_DIRECT.value:
                resolved_value, lookup_status, lookup_error = self._resolve_tracker_item_reference_value(
                    schema_field,
                    raw_value,
                    option_info,
                )
                if resolved_value is not None:
                    resolved_defaults[schema_field] = resolved_value
                else:
                    errors.append({
                        **self.mapper._validation_context(
                            DEFAULT_VALUE_COLUMN_LABEL,
                            schema_field,
                            option_info,
                            raw_value=raw_value,
                            error=lookup_error,
                            value_source="default",
                        ),
                        "status": lookup_status or "DIRECT_PARSE_FAILED",
                    })
                continue

            if option_info.get("kind") == OptionMapKind.USER_LOOKUP.value:
                resolved_value, _, lookup_status, lookup_error = self._resolve_user_reference_value(
                    raw_value,
                    multiple_values=option_info.get("multiple_values", False),
                )
                if resolved_value is not None:
                    resolved_defaults[schema_field] = resolved_value
                else:
                    errors.append({
                        **self.mapper._validation_context(
                            DEFAULT_VALUE_COLUMN_LABEL,
                            schema_field,
                            option_info,
                            raw_value=raw_value,
                            error=lookup_error,
                            value_source="default",
                        ),
                        "status": lookup_status or "LOOKUP_REQUIRED",
                    })
                continue

            if option_info.get("kind") == OptionMapKind.MEMBER_LOOKUP.value:
                resolved_value, _, lookup_status, lookup_error = self._resolve_member_reference_value(
                    raw_value,
                    multiple_values=option_info.get("multiple_values", False),
                    field_id=option_info.get("field_id"),
                    member_types=option_info.get("member_types") or [],
                )
                if resolved_value is not None:
                    resolved_defaults[schema_field] = resolved_value
                else:
                    errors.append({
                        **self.mapper._validation_context(
                            DEFAULT_VALUE_COLUMN_LABEL,
                            schema_field,
                            option_info,
                            raw_value=raw_value,
                            error=lookup_error,
                            value_source="default",
                        ),
                        "status": lookup_status or "LOOKUP_REQUIRED",
                    })
                continue

            errors.append({
                **self.mapper._validation_context(
                    DEFAULT_VALUE_COLUMN_LABEL,
                    schema_field,
                    option_info,
                    raw_value=raw_value,
                    error=option_info.get("unsupported_reason"),
                    value_source="default",
                ),
                "status": "LOOKUP_REQUIRED",
            })

        return pd.DataFrame(errors), resolved_defaults

    def _resolve_default_field_value(self, schema_field: str, raw_value: Any, row_id: int) -> Any:
        """payload 생성 중 기본값을 실제 업로드 형식으로 변환한다."""
        matched = self.state.schema_df[self.state.schema_df["field_name"] == schema_field]
        if matched.empty:
            self._raise_payload_error(
                "FIELD_UNSUPPORTED",
                schema_field=schema_field,
                df_col=DEFAULT_VALUE_COLUMN_LABEL,
                row_id=row_id,
                detail="default field is missing in current schema",
            )

        field_row = matched.iloc[0]
        if not bool(field_row.get("is_option_like", False)):
            return raw_value

        option_info = (self.state.option_maps or {}).get(schema_field, {})
        kind = option_info.get("kind")

        if not option_info.get("is_supported", True) or kind == OptionMapKind.UNSUPPORTED.value:
            self._raise_payload_error(
                "FIELD_UNSUPPORTED",
                schema_field=schema_field,
                df_col=DEFAULT_VALUE_COLUMN_LABEL,
                row_id=row_id,
                detail=(
                    f"reason={option_info.get('unsupported_reason')!r} "
                    f"strategy={option_info.get('resolution_strategy')!r}"
                ),
            )

        if kind == OptionMapKind.STATIC_OPTIONS.value:
            resolved_value = self.mapper.resolve_static_option_value(raw_value, option_info)
            if resolved_value is None:
                self._raise_payload_error(
                    "OPTION_RESOLUTION_FAILED",
                    schema_field=schema_field,
                    df_col=DEFAULT_VALUE_COLUMN_LABEL,
                    row_id=row_id,
                    detail=f"value={raw_value!r}",
                )
            return resolved_value

        if kind == OptionMapKind.TRACKER_ITEM_DIRECT.value:
            resolved, lookup_status, lookup_error = self._resolve_tracker_item_reference_value(
                schema_field,
                raw_value,
                option_info,
            )
            if resolved is not None:
                return resolved
            error_code = (
                "DIRECT_PARSE_FAILED"
                if lookup_status in {
                    OptionCheckStatus.DIRECT_PARSE_FAILED.value,
                    OptionCheckStatus.TRACKER_ITEM_REGEX_MISSING.value,
                }
                else "LOOKUP_REQUIRED"
            )
            detail = f"value={raw_value!r} lookup_status={lookup_status!r}"
            if lookup_error:
                detail = f"{detail} error={lookup_error!r}"
            self._raise_payload_error(
                error_code,
                schema_field=schema_field,
                df_col=DEFAULT_VALUE_COLUMN_LABEL,
                row_id=row_id,
                detail=detail,
            )

        if kind == OptionMapKind.USER_LOOKUP.value:
            resolved, _, lookup_status, lookup_error = self._resolve_user_reference_value(
                raw_value,
                multiple_values=option_info.get("multiple_values", False),
            )
            if resolved is not None:
                return resolved
            self._raise_payload_error(
                "LOOKUP_REQUIRED",
                schema_field=schema_field,
                df_col=DEFAULT_VALUE_COLUMN_LABEL,
                row_id=row_id,
                detail=(
                    f"value={raw_value!r} lookup_status={lookup_status!r} "
                    f"error={lookup_error!r}"
                ),
            )

        if kind == OptionMapKind.MEMBER_LOOKUP.value:
            resolved, _, lookup_status, lookup_error = self._resolve_member_reference_value(
                raw_value,
                multiple_values=option_info.get("multiple_values", False),
                field_id=option_info.get("field_id"),
                member_types=option_info.get("member_types") or [],
            )
            if resolved is not None:
                return resolved
            self._raise_payload_error(
                "LOOKUP_REQUIRED",
                schema_field=schema_field,
                df_col=DEFAULT_VALUE_COLUMN_LABEL,
                row_id=row_id,
                detail=(
                    f"value={raw_value!r} lookup_status={lookup_status!r} "
                    f"error={lookup_error!r}"
                ),
            )

        self._raise_payload_error(
            "LOOKUP_REQUIRED",
            schema_field=schema_field,
            df_col=DEFAULT_VALUE_COLUMN_LABEL,
            row_id=row_id,
            detail=(
                f"value={raw_value!r} "
                f"lookup_target={option_info.get('lookup_target_kind')!r} "
                f"reason={option_info.get('unsupported_reason')!r}"
            ),
        )
        return None

    def _resolve_manual_field_value(
        self,
        schema_field: str,
        raw_value: Any,
        *,
        row_id: int,
        df_col: str,
    ) -> Any:
        """행 외부 입력값을 스키마 기준 업로드 값으로 변환한다."""
        matched = self.state.schema_df[self.state.schema_df["field_name"] == schema_field]
        if matched.empty:
            self._raise_payload_error(
                "FIELD_UNSUPPORTED",
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail="schema field is missing in current schema",
            )

        field_row = matched.iloc[0]
        if not bool(field_row.get("is_option_like", False)):
            return raw_value

        option_maps = self.state.option_maps or self.mapper.build_option_maps_from_schema(self.state.schema_df)
        if not self.state.option_maps:
            self.state.option_maps = option_maps
        option_info = option_maps.get(schema_field, {})
        kind = option_info.get("kind")
        if not option_info.get("is_supported", True) or kind == OptionMapKind.UNSUPPORTED.value:
            self._raise_payload_error(
                "FIELD_UNSUPPORTED",
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=(
                    f"reason={option_info.get('unsupported_reason')!r} "
                    f"strategy={option_info.get('resolution_strategy')!r}"
                ),
            )

        if kind == OptionMapKind.STATIC_OPTIONS.value:
            resolved_value = self.mapper.resolve_static_option_value(raw_value, option_info)
            if resolved_value is None:
                self._raise_payload_error(
                    "OPTION_RESOLUTION_FAILED",
                    schema_field=schema_field,
                    df_col=df_col,
                    row_id=row_id,
                    detail=f"value={raw_value!r}",
                )
            return resolved_value

        if kind == OptionMapKind.TRACKER_ITEM_DIRECT.value:
            resolved, lookup_status, lookup_error = self._resolve_tracker_item_reference_value(
                schema_field,
                raw_value,
                option_info,
            )
            if resolved is not None:
                return resolved
            error_code = (
                "DIRECT_PARSE_FAILED"
                if lookup_status in {
                    OptionCheckStatus.DIRECT_PARSE_FAILED.value,
                    OptionCheckStatus.TRACKER_ITEM_REGEX_MISSING.value,
                }
                else "LOOKUP_REQUIRED"
            )
            detail = f"value={raw_value!r} lookup_status={lookup_status!r}"
            if lookup_error:
                detail = f"{detail} error={lookup_error!r}"
            self._raise_payload_error(
                error_code,
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
                detail=detail,
            )

        if kind == OptionMapKind.USER_LOOKUP.value:
            resolved, _, lookup_status, lookup_error = self._resolve_user_reference_value(
                raw_value,
                multiple_values=option_info.get("multiple_values", False),
            )
            if resolved is None:
                self._raise_payload_error(
                    "LOOKUP_REQUIRED",
                    schema_field=schema_field,
                    df_col=df_col,
                    row_id=row_id,
                    detail=(
                        f"value={raw_value!r} lookup_status={lookup_status!r} "
                        f"error={lookup_error!r}"
                    ),
                )
            return resolved

        if kind == OptionMapKind.MEMBER_LOOKUP.value:
            resolved, _, lookup_status, lookup_error = self._resolve_member_reference_value(
                raw_value,
                multiple_values=option_info.get("multiple_values", False),
                field_id=option_info.get("field_id"),
                member_types=option_info.get("member_types") or [],
            )
            if resolved is None:
                self._raise_payload_error(
                    "LOOKUP_REQUIRED",
                    schema_field=schema_field,
                    df_col=df_col,
                    row_id=row_id,
                    detail=(
                        f"value={raw_value!r} lookup_status={lookup_status!r} "
                        f"error={lookup_error!r}"
                    ),
                )
            return resolved

        self._raise_payload_error(
            "LOOKUP_REQUIRED",
            schema_field=schema_field,
            df_col=df_col,
            row_id=row_id,
            detail=(
                f"value={raw_value!r} "
                f"lookup_target={option_info.get('lookup_target_kind')!r} "
                f"reason={option_info.get('unsupported_reason')!r}"
            ),
        )
        return None

    def _apply_manual_field_values(
        self,
        item: TrackerItemBase,
        explicit_field_values: dict[str, Any] | None,
        *,
        row_id: int,
        applied_schema_fields: set[str],
        df_col_prefix: str,
    ) -> None:
        """행 외부에서 받은 값을 루트/보조 payload에 적용한다."""
        if self.state.schema_df is None or not explicit_field_values:
            return

        for schema_field, raw_value in explicit_field_values.items():
            if schema_field in applied_schema_fields:
                continue
            if not self._has_configured_value(raw_value):
                continue

            matched = self.state.schema_df[self.state.schema_df["field_name"] == schema_field]
            if matched.empty:
                continue

            field_row = matched.iloc[0]
            if bool(field_row.get("is_table_field")):
                continue
            tracker_field = str(field_row.get("tracker_item_field") or schema_field).strip()
            if not tracker_field:
                continue

            df_col = f"{df_col_prefix}:{schema_field}"
            self._ensure_field_ready_for_payload(
                field_row=field_row,
                schema_field=schema_field,
                df_col=df_col,
                row_id=row_id,
            )
            field_value = self._resolve_manual_field_value(
                schema_field,
                raw_value,
                row_id=row_id,
                df_col=df_col,
            )
            if field_value is None:
                continue

            field_info = self._schema_field_info(field_row, schema_field)
            item.set_field_value(tracker_field, field_value, field_info)
            applied_schema_fields.add(schema_field)

    def _apply_default_field_values(
        self,
        item: TrackerItemBase,
        *,
        row_id: int,
        operation: str,
        applied_schema_fields: set[str],
    ) -> None:
        """행 값이 없는 필드에 공통 기본값을 보충한다."""
        if self.state.schema_df is None or not self.state.selected_default_values:
            return

        for schema_field, raw_value in self.state.selected_default_values.items():
            if schema_field in applied_schema_fields:
                continue
            if not self._has_configured_value(raw_value):
                continue
            if not scope_applies_to_operation(
                self.state.selected_default_value_modes.get(schema_field),
                operation,
                upload_mode=self.state.upload_mode,
            ):
                continue

            matched = self.state.schema_df[self.state.schema_df["field_name"] == schema_field]
            if matched.empty:
                continue

            field_row = matched.iloc[0]
            tracker_field = str(field_row.get("tracker_item_field") or schema_field).strip()
            if not tracker_field:
                continue

            field_value = self.state.resolved_default_values.get(schema_field)
            if field_value is None:
                field_value = self._resolve_default_field_value(schema_field, raw_value, row_id)
            if field_value is None:
                continue

            field_info = self._schema_field_info(field_row, schema_field)
            item.set_field_value(tracker_field, field_value, field_info)
            applied_schema_fields.add(schema_field)

    def _build_table_custom_fields(self, row: pd.Series) -> list[TableFieldValue]:
        """현재 행에서 TableField 값들을 모아 custom field payload로 만든다."""
        custom_fields: list[TableFieldValue] = []
        if not self.state.table_field_mapping or self.state.schema_df is None:
            return custom_fields

        table_fields_by_name = {}
        table_schema_rows = self.state.schema_df[self.state.schema_df.get("is_table_field", False).fillna(False)]

        for _, tf_row in table_schema_rows.iterrows():
            tf_name = tf_row["field_name"]
            table_fields_by_name[tf_name] = {
                "field_id": tf_row["field_id"],
                "columns": tf_row.get("table_columns", []),
            }

        tables_data: dict[str, dict[str, Any]] = {}

        for df_col, tf_info in self.state.table_field_mapping.items():
            tf_name = tf_info["table_field_name"]
            col_name = tf_info["column_name"]
            if tf_name not in tables_data:
                tables_data[tf_name] = {}
            tables_data[tf_name][col_name] = row[df_col] if df_col in row.index else None

        for tf_name, table_values_by_column in tables_data.items():
            if tf_name not in table_fields_by_name:
                continue

            column_defs = table_fields_by_name[tf_name]["columns"]
            row_count = 0
            for raw_value in table_values_by_column.values():
                if isinstance(raw_value, list):
                    row_count = max(row_count, len(raw_value))
                elif self._has_configured_value(raw_value):
                    row_count = max(row_count, 1)

            values = []
            for row_index in range(row_count):
                row_fields = []
                for column_def in column_defs:
                    column_name = column_def.get("name")
                    if not column_name:
                        continue

                    raw_value = table_values_by_column.get(column_name)
                    if isinstance(raw_value, list):
                        cell_value = raw_value[row_index] if row_index < len(raw_value) else None
                    else:
                        cell_value = raw_value if row_index == 0 else None

                    if not self._has_configured_value(cell_value):
                        continue

                    field_info = {
                        "field_id": column_def.get("id"),
                        "field_name": column_name,
                        "field_type": column_def.get("type"),
                        "value_model": column_def.get("valueModel", FieldValueType.TEXT.value),
                        "reference_type": column_def.get("referenceType"),
                        "multiple_values": column_def.get("multipleValues", False),
                    }
                    row_fields.append(_build_field_value(field_info, cell_value))

                if row_fields:
                    values.append(row_fields)

            if values:
                custom_fields.append(
                    TableFieldValue(
                        field_id=table_fields_by_name[tf_name]["field_id"],
                        field_name=tf_name,
                        values=values,
                    )
                )

        return custom_fields

    def _build_row_item(
        self,
        row: pd.Series,
        row_id: int,
        *,
        default_name: str | None,
        operation: str,
    ) -> TrackerItemBase:
        """행 값과 기본값을 반영한 TrackerItem 조립 결과를 만든다."""
        item = TrackerItemBase()
        if default_name is not None:
            item.name = str(default_name)
        applied_schema_fields: set[str] = set()

        for df_col, schema_field in self.state.selected_mapping.items():
            if not scope_applies_to_operation(
                self.state.selected_mapping_modes.get(df_col),
                operation,
                upload_mode=self.state.upload_mode,
            ):
                continue
            matched = self.state.schema_df[self.state.schema_df["field_name"] == schema_field]
            if matched.empty:
                continue

            field_row = matched.iloc[0]
            if bool(field_row.get("is_table_field")):
                continue
            tracker_field = str(field_row.get("tracker_item_field") or schema_field).strip()
            if not tracker_field:
                continue

            field_value = None
            if df_col in self.state.selected_option_mapping:
                if not self._has_row_value(row, df_col):
                    continue
                self._ensure_field_ready_for_payload(
                    field_row=field_row,
                    schema_field=schema_field,
                    df_col=df_col,
                    row_id=row_id,
                )
                field_value = self._resolve_option_field_value(row, row_id, df_col, schema_field)
            elif self._has_row_value(row, df_col):
                self._ensure_field_ready_for_payload(
                    field_row=field_row,
                    schema_field=schema_field,
                    df_col=df_col,
                    row_id=row_id,
                )
                field_value = row[df_col]

            if field_value is None:
                continue

            field_info = self._schema_field_info(field_row, schema_field)
            item.set_field_value(tracker_field, field_value, field_info)
            applied_schema_fields.add(schema_field)

        self._apply_default_field_values(
            item,
            row_id=row_id,
            operation=operation,
            applied_schema_fields=applied_schema_fields,
        )
        table_custom_fields = self._build_table_custom_fields(row)
        if table_custom_fields:
            for field in table_custom_fields:
                item.add_field_value(field)

        return item

    def _build_row_payload(self, row: pd.Series, row_id: int, *, operation: str = "create") -> dict[str, Any]:
        """단일 생성 행에서 순수 item payload만 계산한다."""
        item = self._build_row_item(
            row,
            row_id,
            default_name=str(row.get("upload_name", "")),
            operation=operation,
        )
        payload = item.create_new_item_payload()
        return self._serialize_payload_value(payload)


