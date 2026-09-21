from __future__ import annotations

from typing import Any
from typing import NoReturn

import pandas as pd

from .models import TableFieldValue
from .models import TrackerItemBase
from .upload_policy import OperationScope
from .wizard_item_builder import WizardItemBuilderService
from .wizard_option_resolution import WizardOptionResolutionService
from .wizard_update_payload import WizardUpdatePayloadService


class WizardPayloadMixin:
    # 조립된 뒤 사용할 속성의 타입 선언이다. 실제 값은
    # `CodebeamerUploadWizard.__init__` 이 채우므로 여기서는 선언만 둔다.
    item_builder: WizardItemBuilderService
    option_resolution: WizardOptionResolutionService
    update_payloads: WizardUpdatePayloadService

    def _option_processing_operation(
        self,
        row: pd.Series,
        *,
        upload_mode: str,
        id_column_name: str | None,
    ) -> str:
        return self.option_resolution._option_processing_operation(
            row,
            upload_mode=upload_mode,
            id_column_name=id_column_name,
        )

    def _mask_inapplicable_option_rows(
        self,
        upload_df: pd.DataFrame,
        option_mapping: dict[str, str],
    ) -> pd.DataFrame:
        return self.option_resolution._mask_inapplicable_option_rows(
            upload_df,
            option_mapping,
        )

    @staticmethod
    def _restore_option_source_columns(
        processed_df: pd.DataFrame,
        source_df: pd.DataFrame,
        option_mapping: dict[str, str],
    ) -> pd.DataFrame:
        return WizardOptionResolutionService._restore_option_source_columns(
            processed_df,
            source_df,
            option_mapping,
        )

    def process_option_mapping(
        self,
        selected_mapping: dict[str, str],
        selected_option_mapping: dict[str, str] | None = None,
        selected_mapping_modes: dict[str, OperationScope] | None = None,
        selected_default_values: dict[str, Any] | None = None,
        selected_default_value_modes: dict[str, OperationScope] | None = None,
        selected_tracker_item_settings: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, str], pd.DataFrame]:
        return self.option_resolution.process_option_mapping(
            selected_mapping,
            selected_option_mapping,
            selected_mapping_modes,
            selected_default_values,
            selected_default_value_modes,
            selected_tracker_item_settings,
        )

    def _serialize_payload_value(self, value: Any) -> Any:
        return self.item_builder._serialize_payload_value(value)

    @staticmethod
    def _has_row_value(row: pd.Series, column_name: str) -> bool:
        return WizardItemBuilderService._has_row_value(row, column_name)

    @staticmethod
    def _has_configured_value(value: Any) -> bool:
        return WizardItemBuilderService._has_configured_value(value)

    @staticmethod
    def _schema_field_info(
        field_row: pd.Series,
        schema_field: str,
    ) -> dict[str, Any]:
        return WizardItemBuilderService._schema_field_info(
            field_row,
            schema_field,
        )

    @staticmethod
    def _raise_payload_error(
        code: str,
        *,
        schema_field: str,
        row_id: int,
        df_col: str,
        detail: str,
    ) -> NoReturn:
        WizardItemBuilderService._raise_payload_error(
            code,
            schema_field=schema_field,
            row_id=row_id,
            df_col=df_col,
            detail=detail,
        )

    def _ensure_field_ready_for_payload(
        self,
        *,
        field_row: pd.Series,
        schema_field: str,
        df_col: str,
        row_id: int,
    ) -> None:
        self.item_builder._ensure_field_ready_for_payload(
            field_row=field_row,
            schema_field=schema_field,
            df_col=df_col,
            row_id=row_id,
        )

    def _resolve_option_field_value(
        self,
        row: pd.Series,
        row_id: int,
        df_col: str,
        schema_field: str,
    ) -> Any:
        return self.item_builder._resolve_option_field_value(
            row,
            row_id,
            df_col,
            schema_field,
        )

    def _resolve_default_field_values(
        self,
        selected_default_values: dict[str, Any],
        option_maps: dict[str, dict[str, Any]],
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        return self.item_builder._resolve_default_field_values(
            selected_default_values,
            option_maps,
        )

    def _resolve_default_field_value(
        self,
        schema_field: str,
        raw_value: Any,
        row_id: int,
    ) -> Any:
        return self.item_builder._resolve_default_field_value(
            schema_field,
            raw_value,
            row_id,
        )

    def _resolve_manual_field_value(
        self,
        schema_field: str,
        raw_value: Any,
        *,
        row_id: int,
        df_col: str,
    ) -> Any:
        return self.item_builder._resolve_manual_field_value(
            schema_field,
            raw_value,
            row_id=row_id,
            df_col=df_col,
        )

    def _apply_manual_field_values(
        self,
        item: TrackerItemBase,
        explicit_field_values: dict[str, Any] | None,
        *,
        row_id: int,
        applied_schema_fields: set[str],
        df_col_prefix: str,
    ) -> None:
        self.item_builder._apply_manual_field_values(
            item,
            explicit_field_values,
            row_id=row_id,
            applied_schema_fields=applied_schema_fields,
            df_col_prefix=df_col_prefix,
        )

    def _apply_default_field_values(
        self,
        item: TrackerItemBase,
        *,
        row_id: int,
        operation: str,
        applied_schema_fields: set[str],
    ) -> None:
        self.item_builder._apply_default_field_values(
            item,
            row_id=row_id,
            operation=operation,
            applied_schema_fields=applied_schema_fields,
        )

    def _build_table_custom_fields(
        self,
        row: pd.Series,
    ) -> list[TableFieldValue]:
        return self.item_builder._build_table_custom_fields(row)

    def _build_row_item(
        self,
        row: pd.Series,
        row_id: int,
        *,
        default_name: str | None,
        operation: str,
    ) -> TrackerItemBase:
        return self.item_builder._build_row_item(
            row,
            row_id,
            default_name=default_name,
            operation=operation,
        )

    def _build_row_payload(
        self,
        row: pd.Series,
        row_id: int,
        *,
        operation: str = "create",
    ) -> dict[str, Any]:
        return self.item_builder._build_row_payload(
            row,
            row_id,
            operation=operation,
        )

    @staticmethod
    def _update_item_id_column_name(source_df: pd.DataFrame) -> str | None:
        return WizardUpdatePayloadService._update_item_id_column_name(source_df)

    @staticmethod
    def _parse_update_item_id(raw_value: Any) -> int:
        return WizardUpdatePayloadService._parse_update_item_id(raw_value)

    def _resolve_update_target_item_id(
        self,
        row: pd.Series,
        row_id: int,
        *,
        id_column_name: str,
        duplicate_item_ids: set[int],
        allow_missing: bool,
    ) -> int | None:
        if allow_missing:
            return self.update_payloads._resolve_update_target_item_id(
                row,
                row_id,
                id_column_name=id_column_name,
                duplicate_item_ids=duplicate_item_ids,
                allow_missing=True,
            )
        return self.update_payloads._resolve_update_target_item_id(
            row,
            row_id,
            id_column_name=id_column_name,
            duplicate_item_ids=duplicate_item_ids,
            allow_missing=False,
        )

    @staticmethod
    def _filter_payload_rows(
        payload_df: pd.DataFrame,
        include_row_ids: set[int] | None,
    ) -> pd.DataFrame:
        return WizardUpdatePayloadService._filter_payload_rows(
            payload_df,
            include_row_ids,
        )

    @staticmethod
    def _concat_result_frames(frames: list[pd.DataFrame | None]) -> pd.DataFrame:
        return WizardUpdatePayloadService._concat_result_frames(frames)

    @staticmethod
    def _result_count(frame: pd.DataFrame | None) -> int:
        return WizardUpdatePayloadService._result_count(frame)

    def _apply_upsert_hierarchy_validation(
        self,
        payload_df: pd.DataFrame,
        source_df: pd.DataFrame,
    ) -> None:
        self.update_payloads._apply_upsert_hierarchy_validation(
            payload_df,
            source_df,
        )

    def _existing_item(
        self,
        item_id: int,
        *,
        row_id: int,
        df_col: str,
    ) -> dict[str, Any]:
        return self.update_payloads._existing_item(
            item_id,
            row_id=row_id,
            df_col=df_col,
        )

    @staticmethod
    def _custom_field_key(field_payload: Any) -> tuple[str, Any] | None:
        return WizardUpdatePayloadService._custom_field_key(field_payload)

    @classmethod
    def _merge_custom_fields(
        cls,
        existing_fields: Any,
        updated_fields: Any,
    ) -> list[dict[str, Any]]:
        return WizardUpdatePayloadService._merge_custom_fields(
            existing_fields,
            updated_fields,
        )

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
        return self.update_payloads._build_update_row_payload(
            row,
            row_id,
            id_column_name=id_column_name,
            duplicate_item_ids=duplicate_item_ids,
            fetch_existing_item=fetch_existing_item,
            target_item_id=target_item_id,
        )

    @staticmethod
    def _normalize_root_item_name(root_item_name: str | None) -> str | None:
        if root_item_name is None:
            return None
        normalized = str(root_item_name).strip()
        return normalized or None

    def _build_root_item_payload(
        self,
        root_item_name: str,
        root_field_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """업로드 시작 전에 생성할 최상위 부모 item payload를 만든다."""
        item = TrackerItemBase()
        item.name = root_item_name
        applied_schema_fields: set[str] = set()
        self._apply_manual_field_values(
            item,
            root_field_values,
            row_id=-1,
            applied_schema_fields=applied_schema_fields,
            df_col_prefix="ROOT",
        )
        self._apply_default_field_values(
            item,
            row_id=-1,
            operation="create",
            applied_schema_fields=applied_schema_fields,
        )
        return self._serialize_payload_value(item.create_new_item_payload())

    @staticmethod
    def _unresolved_parent_error(parent_row_id: Any, *, root_item_name: str | None = None) -> str:
        if parent_row_id is None or pd.isna(parent_row_id):
            if root_item_name:
                return f"Top-level parent {root_item_name!r} is unavailable."
            return "Top-level row was not uploaded."
        return f"Parent row {int(parent_row_id)} was not uploaded successfully."

    @classmethod
    def _normalize_top_level_parent_specs(
        cls,
        top_level_parent_specs: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], dict[int, str]]:
        normalized_specs: list[dict[str, Any]] = []
        parent_name_by_row_id: dict[int, str] = {}
        for raw_spec in top_level_parent_specs or []:
            if not isinstance(raw_spec, dict):
                continue
            parent_name = cls._normalize_root_item_name(raw_spec.get("name"))
            if parent_name is None:
                continue

            normalized_row_ids: list[int] = []
            for raw_row_id in raw_spec.get("row_ids") or []:
                try:
                    normalized_row_ids.append(int(raw_row_id))
                except (TypeError, ValueError):
                    continue

            normalized_spec = {
                "key": str(raw_spec.get("key") or parent_name).strip() or parent_name,
                "name": parent_name,
                "field_values": dict(raw_spec.get("field_values") or {}),
                "row_ids": normalized_row_ids,
                "parent_key": str(raw_spec.get("parent_key") or "").strip() or None,
                "kind": str(raw_spec.get("kind") or "group_root").strip() or "group_root",
            }
            normalized_specs.append(normalized_spec)
            for row_id in normalized_row_ids:
                parent_name_by_row_id[row_id] = parent_name

        return normalized_specs, parent_name_by_row_id
