from __future__ import annotations

from typing import Any

import pandas as pd

from src.codebeamer_client import CodebeamerClient
from src.excel_reader import ExcelReader
from src.hierarchy_processor import HierarchyProcessor
from src.mapping_service import MappingService
from src.models import OptionMapKind
from src.upload_pipeline import load_tracker_schema_df
from src.upload_pipeline import prepare_upload_dataframe
from src.upload_pipeline import suggest_mapping_from_headers
from src.upload_policy import UPLOAD_MODE_UPSERT as GUI_UPLOAD_MODE_UPSERT
from src.upload_policy import OperationScope
from src.upload_policy import normalize_upload_mode as normalize_gui_upload_mode
from src.upload_policy import upload_mode_allows_root_items as gui_upload_mode_allows_root_items
from src.wizard import CodebeamerUploadWizard

from .batch_upload import BatchUploadService
from .batch_validation import GUI_EXCLUDED_MAPPING_COLUMNS
from .batch_validation import BatchValidationService
from .root_item_service import RootItemService
from .service_core import GuiExcelService
from .service_core import PreviewData
from .service_core import _build_gui_client
from .tracker_config import TrackerConfigurationService
from .upload_context import DefaultValueCandidate
from .upload_context import MappingContext
from .upload_context import RootItemPreviewContext
from .upload_context import RootItemUploadSpec
from .upload_context import TrackerItemFieldCandidate
from .upload_context import ValidationContext
from .validation_presenter import ValidationPresenter


GUI_EXCLUDED_TARGET_FIELDS = {"id", "parent"}
GUI_VALUE_KIND_STATIC_OPTIONS = "static_options"
GUI_VALUE_KIND_BOOL = "bool"
GUI_VALUE_KIND_SCALAR = "scalar"
class GuiUploadPipelineService:
    """GUI 단계가 재사용할 업로드 파이프라인 래퍼다."""

    def __init__(
        self,
        logger=None,
        *,
        client_factory=CodebeamerClient,
        excel_service: GuiExcelService | None = None,
        reader_cls=ExcelReader,
    ) -> None:
        """필요한 의존성과 상태를 초기화한다."""
        self.logger = logger
        self.mapper = MappingService(logger=logger)
        self.client_factory = client_factory
        self.reader_cls = reader_cls
        self.excel_service = excel_service or GuiExcelService(logger=logger, reader_cls=reader_cls)
        self.tracker_configuration = TrackerConfigurationService()
        self.validation_presenter = ValidationPresenter()
        self.batch_validation = BatchValidationService(
            mapper=self.mapper,
            reader_cls=reader_cls,
            logger=logger,
            tracker_configuration=self.tracker_configuration,
            validation_presenter=self.validation_presenter,
        )
        self.root_items = RootItemService(
            mapper=self.mapper,
            reader_cls=reader_cls,
            logger=logger,
            is_schema_field_excluded=self._is_gui_excluded_schema_field,
        )
        self.batch_upload = BatchUploadService(
            mapper=self.mapper,
            create_wizard=self.create_wizard,
            root_items=self.root_items,
            batch_validation=self.batch_validation,
        )

    @classmethod
    def _normalize_mapping_modes(
        cls,
        selected_mapping: dict[str, str],
        selected_mapping_modes: dict[str, Any] | None,
        *,
        upload_mode: str | None,
    ) -> dict[str, OperationScope]:
        return BatchValidationService._normalize_mapping_modes(
            selected_mapping,
            selected_mapping_modes,
            upload_mode=upload_mode,
        )

    @classmethod
    def _normalize_default_value_modes(
        cls,
        selected_default_values: dict[str, str],
        selected_default_value_modes: dict[str, Any] | None,
        *,
        upload_mode: str | None,
    ) -> dict[str, OperationScope]:
        return BatchValidationService._normalize_default_value_modes(
            selected_default_values,
            selected_default_value_modes,
            upload_mode=upload_mode,
        )

    def create_wizard(self, settings) -> CodebeamerUploadWizard:
        client = _build_gui_client(settings, self.client_factory, self.logger)
        reader = self.reader_cls(
            header_row=settings.excel_header_row,
            summary_col=settings.summary_column,
            logger=self.logger,
        )
        processor = HierarchyProcessor(
            header_row=settings.excel_header_row,
            summary_col=settings.summary_column,
            logger=self.logger,
        )
        wizard = CodebeamerUploadWizard(
            client=client,
            processor=processor,
            mapper=self.mapper,
            reader=reader,
            logger=self.logger,
        )
        wizard.state.upload_mode = normalize_gui_upload_mode(getattr(settings, "upload_mode", None))
        return wizard

    @staticmethod
    def _is_gui_excluded_schema_field(row: pd.Series | dict[str, Any]) -> bool:
        # dict 와 pandas.Series 모두 get 을 제공하므로 분기 없이 같은 방식으로 읽는다.
        field_name = str(row.get("field_name") or "").strip().lower()
        tracker_item_field = str(row.get("tracker_item_field") or "").strip().lower()
        return field_name in GUI_EXCLUDED_TARGET_FIELDS or tracker_item_field in GUI_EXCLUDED_TARGET_FIELDS

    @staticmethod
    def _gui_upload_columns(upload_df: pd.DataFrame) -> list[str]:
        columns: list[str] = []
        for column in upload_df.columns:
            if column in GUI_EXCLUDED_MAPPING_COLUMNS:
                continue
            if str(column).startswith("_"):
                continue
            columns.append(str(column))
        return columns

    @staticmethod
    def _gui_visible_comparison_df(comparison_df: pd.DataFrame) -> pd.DataFrame:
        return BatchValidationService._gui_visible_comparison_df(comparison_df)

    def _build_default_value_candidates(
        self,
        schema_df: pd.DataFrame,
    ) -> list[DefaultValueCandidate]:
        if schema_df.empty:
            return []

        option_maps = self.mapper.build_option_maps_from_schema(schema_df)
        candidates: list[DefaultValueCandidate] = []
        for _, row in schema_df.iterrows():
            schema_field = str(row.get("field_name") or "").strip()
            if not schema_field:
                continue
            if bool(row.get("is_table_field", False)):
                continue
            if not bool(row.get("is_supported", True)):
                continue

            value_kind = ""
            options: list[str] = []
            allows_custom_value = False

            if bool(row.get("is_option_like", False)):
                option_info = option_maps.get(schema_field, {})
                if option_info.get("kind") == OptionMapKind.STATIC_OPTIONS.value:
                    value_kind = GUI_VALUE_KIND_STATIC_OPTIONS
                    options = [
                        str(option.get("name")).strip()
                        for option in option_info.get("options") or []
                        if str(option.get("name") or "").strip()
                    ]
                    if not options:
                        continue
                elif option_info.get("kind") in {
                    OptionMapKind.MEMBER_LOOKUP.value,
                    OptionMapKind.TRACKER_ITEM_DIRECT.value,
                    OptionMapKind.USER_LOOKUP.value,
                }:
                    value_kind = GUI_VALUE_KIND_SCALAR
                    allows_custom_value = True
                else:
                    continue
            else:
                field_type = str(row.get("field_type") or "").strip()
                if field_type == "BoolField":
                    value_kind = GUI_VALUE_KIND_BOOL
                    options = ["true", "false"]
                else:
                    value_kind = GUI_VALUE_KIND_SCALAR
                    allows_custom_value = True

            candidates.append(DefaultValueCandidate(
                schema_field=schema_field,
                field_type=str(row.get("field_type") or ""),
                value_kind=value_kind,
                options=options,
                mandatory=bool(row.get("mandatory", False)),
                allows_custom_value=allows_custom_value,
            ))
        return candidates

    def _enrich_schema_df_with_tracker_configuration(
        self,
        schema_df: pd.DataFrame,
        tracker_configuration: Any,
    ) -> pd.DataFrame:
        """TRACKER configuration 정보를 schema field에 연결한다."""
        return self.tracker_configuration.enrich_schema(schema_df, tracker_configuration)

    def _normalize_tracker_item_settings(
        self,
        schema_df: pd.DataFrame,
        selected_mapping: dict[str, str],
        tracker_item_settings: dict[str, dict[str, Any]] | None,
    ) -> tuple[list[TrackerItemFieldCandidate], dict[str, dict[str, Any]]]:
        """필드별 tracker item lookup 설정을 configuration 계약에 맞춰 정규화한다."""
        return self.tracker_configuration.normalize_settings(
            schema_df,
            selected_mapping,
            tracker_item_settings,
        )

    def build_root_item_preview_context(
        self,
        mapping_context: MappingContext,
        root_item_config: dict[str, Any] | None = None,
    ) -> RootItemPreviewContext:
        """루트 항목 설정을 정규화하고 미리보기 결과를 구성한다."""
        return self.root_items.build_root_item_preview_context(
            mapping_context,
            root_item_config,
        )

    def _default_root_item_config(self, schema_df: pd.DataFrame) -> dict[str, Any]:
        """매핑 단계에서 사용할 기본 루트 항목 설정을 구성한다."""
        return self.root_items._default_root_item_config(schema_df)

    @staticmethod
    def _normalize_file_paths(file_state: dict[str, Any]) -> list[str]:
        return BatchValidationService._normalize_file_paths(file_state)

    @classmethod
    def _representative_file_path(cls, file_state: dict[str, Any]) -> str:
        return BatchValidationService._representative_file_path(file_state)

    @staticmethod
    def _cached_preview_data(
        file_state: dict[str, Any],
        *,
        file_path: str,
        sheet_name: str,
        header_row: int,
        summary_column: str,
    ) -> PreviewData | None:
        return BatchValidationService._cached_preview_data(
            file_state,
            file_path=file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_column=summary_column,
        )

    @staticmethod
    def _preview_raw_df_map(preview_data: PreviewData | None) -> dict[str, pd.DataFrame]:
        return BatchValidationService._preview_raw_df_map(preview_data)

    @classmethod
    def _cached_raw_df_for_file(
        cls,
        preview_data: PreviewData | None,
        file_path: str,
    ) -> pd.DataFrame | None:
        return BatchValidationService._cached_raw_df_for_file(preview_data, file_path)

    @staticmethod
    def _visible_headers_from_raw_df(raw_df: pd.DataFrame) -> list[str]:
        return BatchValidationService._visible_headers_from_raw_df(raw_df)

    def _visible_headers_for_file(
        self,
        file_path: str,
        *,
        sheet_name: str,
        header_row: int,
        summary_col: str,
    ) -> list[str]:
        return self.batch_validation._visible_headers_for_file(
            file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_col=summary_col,
        )

    def _validate_batch_headers(
        self,
        file_paths: list[str],
        *,
        representative_file_path: str,
        expected_headers: list[str],
        sheet_name: str,
        header_row: int,
        summary_col: str,
        preview_data: PreviewData | None = None,
    ) -> None:
        self.batch_validation._validate_batch_headers(
            file_paths,
            representative_file_path=representative_file_path,
            expected_headers=expected_headers,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_col=summary_col,
            preview_data=preview_data,
        )

    def _count_upload_rows_for_file(
        self,
        file_path: str,
        *,
        sheet_name: str,
        header_row: int,
        summary_col: str,
        list_cols: list[str],
        preview_data: PreviewData | None = None,
    ) -> int:
        return self.batch_validation._count_upload_rows_for_file(
            file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_col=summary_col,
            list_cols=list_cols,
            preview_data=preview_data,
        )

    def _count_batch_upload_rows(
        self,
        mapping_context: MappingContext,
        *,
        list_cols: list[str],
    ) -> int:
        return self.batch_validation._count_batch_upload_rows(
            mapping_context,
            list_cols=list_cols,
        )

    def _create_validation_wizard(self, mapping_context: MappingContext) -> CodebeamerUploadWizard:
        return self.batch_validation._create_validation_wizard(mapping_context)

    @staticmethod
    def _annotate_source_frame(
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
    def _sync_validation_wizard_caches(
        target_wizard: CodebeamerUploadWizard,
        source_wizard: CodebeamerUploadWizard,
    ) -> None:
        BatchValidationService._sync_validation_wizard_caches(
            target_wizard,
            source_wizard,
        )

    def _raw_df_for_file(
        self,
        mapping_context: MappingContext,
        file_path: str,
    ) -> pd.DataFrame:
        return self.batch_validation._raw_df_for_file(mapping_context, file_path)

    def _upload_df_for_file(
        self,
        mapping_context: MappingContext,
        *,
        file_path: str,
        list_cols: list[str],
    ) -> pd.DataFrame:
        return self.batch_validation._upload_df_for_file(
            mapping_context,
            file_path=file_path,
            list_cols=list_cols,
        )

    @classmethod
    def _build_batch_update_duplicate_issue_df(
        cls,
        mapping_context: MappingContext,
        *,
        file_upload_dfs: dict[str, pd.DataFrame],
    ) -> tuple[set[int], pd.DataFrame]:
        return BatchValidationService._build_batch_update_duplicate_issue_df(
            mapping_context,
            file_upload_dfs=file_upload_dfs,
        )

    def _build_upsert_root_item_issue_df(
        self,
        mapping_context: MappingContext,
        *,
        payload_df: pd.DataFrame,
    ) -> pd.DataFrame:
        return self.batch_validation._build_upsert_root_item_issue_df(
            mapping_context,
            payload_df=payload_df,
        )

    def prepare_mapping_context(self, settings, file_state: dict[str, Any]) -> MappingContext:
        file_paths = self._normalize_file_paths(file_state)
        representative_file_path = self._representative_file_path(file_state)
        if not file_paths or not representative_file_path:
            raise ValueError("Excel 파일을 먼저 선택해야 합니다.")

        wizard = self.create_wizard(settings)
        wizard.select_project(int(settings.default_project_id))
        wizard.select_tracker(int(settings.default_tracker_id))
        wizard.state.upload_mode = normalize_gui_upload_mode(getattr(settings, "upload_mode", None))

        schema, schema_df = load_tracker_schema_df(wizard)
        tracker_configuration = None
        if hasattr(wizard.client, "get_tracker_configuration"):
            try:
                tracker_configuration = wizard.client.get_tracker_configuration(int(settings.default_tracker_id))
            except Exception:
                tracker_configuration = None
        schema_df = self._enrich_schema_df_with_tracker_configuration(schema_df, tracker_configuration)
        mappable_schema_df = schema_df[
            ~schema_df.apply(self._is_gui_excluded_schema_field, axis=1)
        ].reset_index(drop=True)

        target_sheet_name = str(file_state["sheet_name"])
        target_header_row = int(file_state["header_row"])
        target_summary_column = str(file_state["summary_column"])
        preview = self._cached_preview_data(
            file_state,
            file_path=representative_file_path,
            sheet_name=target_sheet_name,
            header_row=target_header_row,
            summary_column=target_summary_column,
        )
        if preview is None:
            preview = self.excel_service.load_preview(
                representative_file_path,
                file_paths=file_paths,
                sheet_name=target_sheet_name,
                header_row=target_header_row,
                summary_column=target_summary_column,
            )
        headers = preview.headers
        self._validate_batch_headers(
            file_paths,
            representative_file_path=representative_file_path,
            expected_headers=headers,
            sheet_name=target_sheet_name,
            header_row=target_header_row,
            summary_col=target_summary_column,
            preview_data=preview,
        )
        raw_mapping = suggest_mapping_from_headers(headers, mappable_schema_df)

        _, list_cols = prepare_upload_dataframe(
            wizard,
            file_path=representative_file_path,
            sheet_name=target_sheet_name,
            header_row=target_header_row,
            summary_col=target_summary_column,
            selected_mapping=raw_mapping,
            schema=schema,
            schema_df=mappable_schema_df,
            raw_df=preview.raw_df,
        )

        upload_columns = self._gui_upload_columns(wizard.state.upload_df)
        selected_mapping = {
            column: schema_field
            for column, schema_field in raw_mapping.items()
            if column in upload_columns
        }
        selected_mapping_modes = self._normalize_mapping_modes(
            selected_mapping,
            None,
            upload_mode=wizard.state.upload_mode,
        )
        default_value_candidates = self._build_default_value_candidates(mappable_schema_df)
        selected_default_value_modes = self._normalize_default_value_modes(
            {},
            None,
            upload_mode=wizard.state.upload_mode,
        )
        tracker_item_field_candidates, selected_tracker_item_settings = self._normalize_tracker_item_settings(
            mappable_schema_df,
            selected_mapping,
            None,
        )

        default_root_item_config = self._default_root_item_config(mappable_schema_df)
        upload_mode = normalize_gui_upload_mode(getattr(settings, "upload_mode", None))
        if not gui_upload_mode_allows_root_items(upload_mode) or upload_mode == GUI_UPLOAD_MODE_UPSERT:
            default_root_item_config["enabled"] = False
            default_root_item_config["group_enabled"] = False

        return MappingContext(
            wizard=wizard,
            upload_mode=upload_mode,
            schema_df=mappable_schema_df,
            upload_columns=upload_columns,
            selected_mapping=selected_mapping,
            selected_mapping_modes=selected_mapping_modes,
            default_value_candidates=default_value_candidates,
            selected_default_values={},
            selected_default_value_modes=selected_default_value_modes,
            selected_tracker_item_settings=selected_tracker_item_settings,
            tracker_item_field_candidates=tracker_item_field_candidates,
            tracker_item_lookup_cache={},
            user_lookup_cache={},
            member_lookup_cache={},
            group_lookup_cache={},
            tracker_role_cache={},
            list_cols=list_cols,
            file_paths=file_paths,
            representative_file_path=representative_file_path,
            sheet_name=target_sheet_name,
            header_row=target_header_row,
            summary_column=target_summary_column,
            preview_data=preview,
            root_item_config=default_root_item_config,
            existing_item_cache={},
            batch_duplicate_update_item_ids=set(),
        )

    @staticmethod
    def _normalize_selected_mapping(
        selected_mapping: dict[str, str] | None,
        *,
        upload_columns: list[str],
        schema_df: pd.DataFrame,
    ) -> dict[str, str]:
        """현재 upload 컬럼과 schema에 실제로 존재하는 매핑만 남긴다."""
        if not selected_mapping:
            return {}

        valid_upload_columns = {
            str(column).strip()
            for column in upload_columns
            if str(column).strip()
        }
        valid_schema_fields = {
            str(field_name).strip()
            for field_name in schema_df["field_name"].dropna().tolist()
            if str(field_name).strip()
        }

        normalized_mapping: dict[str, str] = {}
        for df_column, schema_field in selected_mapping.items():
            normalized_column = str(df_column).strip()
            normalized_field = str(schema_field).strip()
            if not normalized_column or not normalized_field:
                continue
            if normalized_column not in valid_upload_columns:
                continue
            if normalized_field not in valid_schema_fields:
                continue
            normalized_mapping[normalized_column] = normalized_field
        return normalized_mapping

    def apply_saved_workflow_values(
        self,
        mapping_context: MappingContext,
        *,
        root_item_config: dict[str, Any] | None = None,
        selected_mapping: dict[str, str] | None = None,
        selected_mapping_modes: dict[str, OperationScope] | None = None,
        selected_default_values: dict[str, str] | None = None,
        selected_default_value_modes: dict[str, OperationScope] | None = None,
        selected_tracker_item_settings: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """현재 파일 기준 자동 추천은 유지하고, 저장된 preset은 유효한 항목만 덮어쓴다."""
        if root_item_config:
            mapping_context.root_item_config = dict(root_item_config)

        merged_mapping = self._normalize_selected_mapping(
            mapping_context.selected_mapping,
            upload_columns=mapping_context.upload_columns,
            schema_df=mapping_context.schema_df,
        )
        merged_mapping.update(
            self._normalize_selected_mapping(
                selected_mapping,
                upload_columns=mapping_context.upload_columns,
                schema_df=mapping_context.schema_df,
            )
        )
        mapping_context.selected_mapping = merged_mapping
        mapping_context.selected_mapping_modes = self._normalize_mapping_modes(
            mapping_context.selected_mapping,
            selected_mapping_modes
            if selected_mapping_modes is not None
            else mapping_context.selected_mapping_modes,
            upload_mode=mapping_context.upload_mode,
        )

        valid_schema_fields = {
            str(field_name).strip()
            for field_name in mapping_context.schema_df["field_name"].dropna().tolist()
            if str(field_name).strip()
        }

        default_values_source = (
            selected_default_values
            if selected_default_values is not None
            else mapping_context.selected_default_values
        )
        mapping_context.selected_default_values = {
            str(field_name).strip(): str(raw_value).strip()
            for field_name, raw_value in (default_values_source or {}).items()
            if str(field_name).strip() in valid_schema_fields and str(raw_value).strip()
        }
        mapping_context.selected_default_value_modes = self._normalize_default_value_modes(
            mapping_context.selected_default_values,
            selected_default_value_modes
            if selected_default_value_modes is not None
            else mapping_context.selected_default_value_modes,
            upload_mode=mapping_context.upload_mode,
        )

        tracker_item_settings_source = (
            selected_tracker_item_settings
            if selected_tracker_item_settings is not None
            else mapping_context.selected_tracker_item_settings
        )
        (
            mapping_context.tracker_item_field_candidates,
            mapping_context.selected_tracker_item_settings,
        ) = self._normalize_tracker_item_settings(
            mapping_context.schema_df,
            mapping_context.selected_mapping,
            tracker_item_settings_source,
        )

    def validate_mapping(
        self,
        mapping_context: MappingContext,
        selected_mapping: dict[str, str],
        selected_default_values: dict[str, str] | None = None,
        selected_tracker_item_settings: dict[str, dict[str, Any]] | None = None,
        *,
        selected_mapping_modes: dict[str, OperationScope] | None = None,
        selected_default_value_modes: dict[str, OperationScope] | None = None,
    ) -> ValidationContext:
        """다중 파일 매핑과 payload를 검증한다."""
        return self.batch_validation.validate_mapping(
            mapping_context,
            selected_mapping,
            selected_default_values,
            selected_tracker_item_settings,
            selected_mapping_modes=selected_mapping_modes,
            selected_default_value_modes=selected_default_value_modes,
        )

    @classmethod
    def _build_row_label(cls, row: pd.Series) -> str:
        """중복 update 이슈에서 사용할 Excel 행 표시를 만든다."""
        return ValidationPresenter.build_row_label(row)

    def build_root_item_payload_specs(
        self,
        mapping_context: MappingContext,
        wizard: CodebeamerUploadWizard,
        file_path: str,
    ) -> list[RootItemUploadSpec]:
        """업로드할 파일·그룹 루트 항목 명세를 구성한다."""
        return self.root_items.build_root_item_payload_specs(
            mapping_context,
            wizard,
            file_path,
        )

    def build_root_item_payload_spec(
        self,
        mapping_context: MappingContext,
        file_path: str,
    ) -> tuple[str | None, dict[str, Any]]:
        """단일 루트 항목 호환 명세를 구성한다."""
        return self.root_items.build_root_item_payload_spec(
            mapping_context,
            file_path,
        )

    @staticmethod
    def _batch_output_dir(output_dir: str, file_path: str, index: int) -> str:
        return BatchUploadService._batch_output_dir(output_dir, file_path, index)

    @staticmethod
    def _ready_upload_count(
        wizard: CodebeamerUploadWizard,
        root_item_specs: list[RootItemUploadSpec] | None = None,
    ) -> int:
        return BatchUploadService._ready_upload_count(
            wizard,
            root_item_specs=root_item_specs,
        )

    @staticmethod
    def _phase_ready_counts(
        wizard: CodebeamerUploadWizard,
        root_item_specs: list[RootItemUploadSpec] | None = None,
    ) -> tuple[int, int]:
        return BatchUploadService._phase_ready_counts(
            wizard,
            root_item_specs=root_item_specs,
        )

    @staticmethod
    def _annotate_batch_result_frame(
        df: pd.DataFrame | None,
        *,
        file_label: str,
        file_path: str,
    ) -> pd.DataFrame:
        return BatchUploadService._annotate_batch_result_frame(
            df,
            file_label=file_label,
            file_path=file_path,
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
        return self.batch_upload._prepare_wizard_for_file(
            settings,
            mapping_context,
            file_path=file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_col=summary_col,
        )

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
        """검증된 다중 파일을 create/update/upsert 모드로 실행한다."""
        return self.batch_upload.run_batch_upload(
            settings,
            file_state,
            mapping_context,
            dry_run=dry_run,
            continue_on_error=continue_on_error,
            output_dir=output_dir,
            event_callback=event_callback,
            cancel_requested=cancel_requested,
            pause_requested=pause_requested,
        )

    def run_failed_upload_retry(
        self,
        retry_context,
        *,
        continue_on_error: bool,
        event_callback=None,
        cancel_requested=None,
        pause_requested=None,
    ) -> dict[str, Any]:
        """현재 세션에 캐시된 실패/미해결 항목만 다시 실행한다."""
        return self.batch_upload.run_failed_upload_retry(
            retry_context,
            continue_on_error=continue_on_error,
            event_callback=event_callback,
            cancel_requested=cancel_requested,
            pause_requested=pause_requested,
        )

    def _build_summary_stats(
        self,
        issue_df: pd.DataFrame,
        row_context_df: pd.DataFrame | None,
    ) -> dict[str, int]:
        return self.validation_presenter.build_summary_stats(issue_df, row_context_df)

    def _build_user_issue_df(
        self,
        comparison_df: pd.DataFrame,
        option_check_df: pd.DataFrame,
        payload_df: pd.DataFrame,
        *,
        row_context_df: pd.DataFrame | None = None,
        selected_default_values: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        return self.validation_presenter.build_user_issue_df(
            comparison_df,
            option_check_df,
            payload_df,
            row_context_df=row_context_df,
            selected_default_values=selected_default_values,
        )

    def _finalize_issue_df(self, issue_df: pd.DataFrame) -> pd.DataFrame:
        return self.validation_presenter.finalize_issue_df(issue_df)

    @staticmethod
    def _parse_payload_error(payload_error: str) -> dict[str, str]:
        return ValidationPresenter.parse_payload_error(payload_error)
