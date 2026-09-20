from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from .upload_policy import OperationScope
from .upload_policy import normalize_operation_scope
from .upload_policy import normalize_upload_mode
from .upload_policy import scope_applies_to_operation
from .upload_policy import scope_applies_to_upload_mode


class WizardOptionResolutionService:
    """option/reference mapping의 범위 판정, lookup과 변환 상태를 관리한다."""

    def __init__(
        self,
        *,
        state: Any,
        mapper: Any,
        update_item_id_column_name: Callable[[pd.DataFrame], str | None],
        parse_update_item_id: Callable[[Any], int],
        has_configured_value: Callable[[Any], bool],
        invalidate_payload_cache: Callable[[], None],
        decorate_tracker_item_option_maps: Callable[..., Any],
        resolve_user_reference_fields: Callable[..., pd.DataFrame],
        resolve_tracker_item_reference_fields: Callable[..., pd.DataFrame],
        resolve_member_reference_fields: Callable[..., pd.DataFrame],
        resolve_default_field_values: Callable[..., Any],
    ) -> None:
        self.state = state
        self.mapper = mapper
        self._update_item_id_column_name = update_item_id_column_name
        self._parse_update_item_id = parse_update_item_id
        self._has_configured_value = has_configured_value
        self._invalidate_payload_cache = invalidate_payload_cache
        self._decorate_tracker_item_option_maps = decorate_tracker_item_option_maps
        self._resolve_user_reference_fields = resolve_user_reference_fields
        self._resolve_tracker_item_reference_fields = resolve_tracker_item_reference_fields
        self._resolve_member_reference_fields = resolve_member_reference_fields
        self._resolve_default_field_values = resolve_default_field_values

    def _option_processing_operation(
        self,
        row: pd.Series,
        *,
        upload_mode: str,
        id_column_name: str | None,
    ) -> str:
        """옵션 검증 시 현재 행이 생성/수정 중 어느 흐름인지 판단한다."""
        normalized_mode = normalize_upload_mode(upload_mode)
        if normalized_mode == "update":
            return "update"
        if normalized_mode != "upsert":
            return "create"
        if not id_column_name or id_column_name not in row.index:
            return "create"

        try:
            self._parse_update_item_id(row.get(id_column_name))
        except ValueError as exc:
            if str(exc) == "missing":
                return "create"
            return "update"
        return "update"

    def _mask_inapplicable_option_rows(
        self,
        upload_df: pd.DataFrame,
        option_mapping: dict[str, str],
    ) -> pd.DataFrame:
        """행별 create/update 범위에 맞지 않는 옵션 값은 검증/lookup에서 제외한다."""
        if upload_df.empty or not option_mapping:
            return upload_df.copy()

        work = upload_df.copy()
        upload_mode = normalize_upload_mode(self.state.upload_mode)
        id_column_name = self._update_item_id_column_name(work) if upload_mode == "upsert" else None
        row_operations = [
            self._option_processing_operation(
                row,
                upload_mode=upload_mode,
                id_column_name=id_column_name,
            )
            for _, row in work.iterrows()
        ]

        for df_col in option_mapping:
            if df_col not in work.columns:
                continue
            scope = self.state.selected_mapping_modes.get(str(df_col).strip())
            inactive_mask = pd.Series(
                [
                    not scope_applies_to_operation(
                        scope,
                        operation,
                        upload_mode=upload_mode,
                    )
                    for operation in row_operations
                ],
                index=work.index,
            )
            if inactive_mask.any():
                work.loc[inactive_mask, df_col] = ""

        return work

    @staticmethod
    def _restore_option_source_columns(
        processed_df: pd.DataFrame,
        source_df: pd.DataFrame,
        option_mapping: dict[str, str],
    ) -> pd.DataFrame:
        """검증용으로 마스킹한 원본 옵션 컬럼은 표시와 후속 처리용으로 복원한다."""
        restored = processed_df.copy()
        for df_col in option_mapping:
            if df_col not in restored.columns or df_col not in source_df.columns:
                continue
            restored[df_col] = source_df[df_col].tolist()
        return restored

    def process_option_mapping(
        self,
        selected_mapping: dict[str, str],
        selected_option_mapping: dict[str, str] | None = None,
        selected_mapping_modes: dict[str, OperationScope] | None = None,
        selected_default_values: dict[str, Any] | None = None,
        selected_default_value_modes: dict[str, OperationScope] | None = None,
        selected_tracker_item_settings: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, str], pd.DataFrame]:
        """옵션/참조형 필드를 찾아 lookup과 검증을 한 번에 수행한다."""
        if self.state.schema_df is None:
            raise ValueError("Schema must be loaded before option processing.")
        if self.state.upload_df is None:
            raise ValueError("upload_df is required before option processing.")

        option_fields = self.mapper.get_option_field_candidates(self.state.schema_df)
        self.state.option_candidates_df = option_fields
        upload_mode = normalize_upload_mode(self.state.upload_mode)
        normalized_mapping_modes = {
            str(df_column).strip(): normalize_operation_scope(
                (selected_mapping_modes or {}).get(str(df_column).strip()),
                upload_mode=upload_mode,
            )
            for df_column in selected_mapping
            if str(df_column).strip()
        }
        self.state.selected_mapping_modes = normalized_mapping_modes

        effective_selected_mapping = {
            excel_col: schema_field
            for excel_col, schema_field in selected_mapping.items()
            if scope_applies_to_upload_mode(
                normalized_mapping_modes.get(str(excel_col).strip()),
                upload_mode,
            )
        }

        if selected_option_mapping is None:
            selected_option_mapping = {}
            option_field_names = set(option_fields["field_name"].dropna().astype(str))
            for excel_col, schema_field in effective_selected_mapping.items():
                if schema_field in option_field_names:
                    selected_option_mapping[excel_col] = schema_field
        else:
            selected_option_mapping = {
                excel_col: schema_field
                for excel_col, schema_field in selected_option_mapping.items()
                if excel_col in effective_selected_mapping
            }

        normalized_default_values: dict[str, Any] = {}
        for schema_field, raw_value in (selected_default_values or {}).items():
            if not self._has_configured_value(raw_value):
                continue
            normalized_default_values[str(schema_field).strip()] = raw_value

        self.state.selected_default_values = normalized_default_values
        normalized_default_value_modes = {
            schema_field: normalize_operation_scope(
                (selected_default_value_modes or {}).get(schema_field),
                upload_mode=upload_mode,
            )
            for schema_field in normalized_default_values
        }
        self.state.selected_default_value_modes = normalized_default_value_modes
        effective_default_values = {
            schema_field: raw_value
            for schema_field, raw_value in normalized_default_values.items()
            if scope_applies_to_upload_mode(
                normalized_default_value_modes.get(schema_field),
                upload_mode,
            )
        }
        if selected_tracker_item_settings is not None:
            self.state.selected_tracker_item_settings = {
                str(schema_field).strip(): dict(setting)
                for schema_field, setting in selected_tracker_item_settings.items()
                if str(schema_field).strip() and isinstance(setting, dict)
            }
        self.state.resolved_default_values = {}

        if not selected_option_mapping and not effective_default_values:
            self.state.selected_option_mapping = {}
            self.state.option_maps = {}
            self.state.option_check_df = pd.DataFrame()
            self.state.converted_upload_df = self.state.upload_df.copy()
            self._invalidate_payload_cache()
            return {}, pd.DataFrame()

        self.state.selected_option_mapping = selected_option_mapping
        option_maps = self.mapper.build_option_maps_from_schema(self.state.schema_df)
        option_maps = self._decorate_tracker_item_option_maps(option_maps)
        self.state.option_maps = option_maps

        lookup_ready_df = self._mask_inapplicable_option_rows(
            self.state.upload_df,
            selected_option_mapping,
        )
        if selected_option_mapping:
            lookup_ready_df = self._resolve_user_reference_fields(
                upload_df=lookup_ready_df,
                option_mapping=selected_option_mapping,
                option_maps=option_maps,
            )
            lookup_ready_df = self._resolve_tracker_item_reference_fields(
                upload_df=lookup_ready_df,
                option_mapping=selected_option_mapping,
                option_maps=option_maps,
            )
            lookup_ready_df = self._resolve_member_reference_fields(
                upload_df=lookup_ready_df,
                option_mapping=selected_option_mapping,
                option_maps=option_maps,
            )

        option_check_df = pd.DataFrame()
        if selected_option_mapping:
            option_check_df = self.mapper.check_option_alignment(
                upload_df=lookup_ready_df,
                option_mapping=selected_option_mapping,
                option_maps=option_maps,
            )

        default_value_check_df, resolved_default_values = self._resolve_default_field_values(
            effective_default_values,
            option_maps,
        )
        self.state.resolved_default_values = resolved_default_values

        check_frames = [
            df
            for df in (option_check_df, default_value_check_df)
            if isinstance(df, pd.DataFrame) and not df.empty
        ]
        self.state.option_check_df = (
            pd.concat(check_frames, ignore_index=True)
            if check_frames
            else pd.DataFrame()
        )

        if selected_option_mapping:
            converted_upload_df = self.mapper.apply_option_resolution(
                upload_df=lookup_ready_df,
                option_mapping=selected_option_mapping,
                option_maps=option_maps,
            )
            self.state.converted_upload_df = self._restore_option_source_columns(
                converted_upload_df,
                self.state.upload_df,
                selected_option_mapping,
            )
        else:
            self.state.converted_upload_df = lookup_ready_df.copy()
        self._invalidate_payload_cache()

        return selected_option_mapping, self.state.option_check_df

