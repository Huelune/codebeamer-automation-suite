from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.hierarchy_processor import HierarchyProcessor
from src.models import PayloadStatus
from src.upload_pipeline import run_validation_pipeline
from src.upload_policy import BLOCKING_OPTION_STATUSES
from src.upload_policy import USER_LOOKUP_FAILURE_SUFFIXES
from src.upload_policy import OperationScope
from src.upload_policy import as_operation_scope
from src.upload_policy import default_operation_scope
from src.upload_policy import normalize_operation_scope
from src.upload_policy import normalize_upload_mode as normalize_gui_upload_mode
from src.upload_policy import scope_applies_to_upload_mode
from src.upload_policy import upload_mode_supports_update as gui_upload_mode_supports_update
from src.wizard import CodebeamerUploadWizard

from .service_core import PreviewData
from .service_core import gui_display_text
from .tracker_config import TrackerConfigurationService
from .upload_context import MappingContext
from .upload_context import TrackerItemFieldCandidate
from .upload_context import ValidationContext
from .validation_presenter import ValidationPresenter


GUI_EXCLUDED_MAPPING_COLUMNS = {
    "id",
    "parent",
    "parent_row_id",
    "upload_name",
    "depth",
    "_row_id",
    "_summary_indent",
    "_start_excel_row",
    "_end_excel_row",
    "_excel_row",
}


class BatchValidationService:
    """다중 파일의 캐시, 헤더, payload와 사용자 검증 결과를 집계한다."""

    def __init__(
        self,
        *,
        mapper: Any,
        reader_cls: type,
        logger: Any = None,
        tracker_configuration: TrackerConfigurationService | None = None,
        validation_presenter: ValidationPresenter | None = None,
    ) -> None:
        self.mapper = mapper
        self.reader_cls = reader_cls
        self.logger = logger
        self.tracker_configuration = tracker_configuration or TrackerConfigurationService()
        self.validation_presenter = validation_presenter or ValidationPresenter()

    @classmethod
    def _normalize_mapping_modes(
        cls,
        selected_mapping: dict[str, str],
        selected_mapping_modes: dict[str, Any] | None,
        *,
        upload_mode: str | None,
    ) -> dict[str, OperationScope]:
        return {
            str(df_column).strip(): normalize_operation_scope(
                (selected_mapping_modes or {}).get(str(df_column).strip()),
                upload_mode=upload_mode,
            )
            for df_column in selected_mapping
            if str(df_column).strip()
        }

    @classmethod
    def _normalize_default_value_modes(
        cls,
        selected_default_values: dict[str, str],
        selected_default_value_modes: dict[str, Any] | None,
        *,
        upload_mode: str | None,
    ) -> dict[str, OperationScope]:
        default_scope = default_operation_scope(upload_mode)
        normalized: dict[str, OperationScope] = {}
        for schema_field in selected_default_values:
            field_name = str(schema_field).strip()
            if not field_name:
                continue
            raw_scope = (selected_default_value_modes or {}).get(field_name)
            normalized[field_name] = (
                as_operation_scope(default_scope)
                if scope_applies_to_upload_mode(raw_scope, upload_mode=upload_mode)
                else OperationScope(create=False, update=False)
            )
        return normalized

    @staticmethod
    def _gui_visible_comparison_df(comparison_df: pd.DataFrame) -> pd.DataFrame:
        if comparison_df is None or comparison_df.empty or "df_column" not in comparison_df.columns:
            return comparison_df
        work = comparison_df.copy()
        mask = ~work["df_column"].astype(str).isin(GUI_EXCLUDED_MAPPING_COLUMNS)
        mask &= ~work["df_column"].astype(str).str.startswith("_")
        return work[mask].reset_index(drop=True)

    def _normalize_tracker_item_settings(
        self,
        schema_df: pd.DataFrame,
        selected_mapping: dict[str, str],
        tracker_item_settings: dict[str, dict[str, Any]] | None,
    ) -> tuple[list[TrackerItemFieldCandidate], dict[str, dict[str, Any]]]:
        return self.tracker_configuration.normalize_settings(
            schema_df,
            selected_mapping,
            tracker_item_settings,
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
    def _normalize_file_paths(file_state: dict[str, Any]) -> list[str]:
        raw_paths = file_state.get("file_paths")
        normalized: list[str] = []

        if isinstance(raw_paths, (list, tuple)):
            for raw_path in raw_paths:
                text = str(raw_path or "").strip()
                if text:
                    normalized.append(text)

        if normalized:
            return normalized

        single_path = str(file_state.get("file_path") or "").strip()
        return [single_path] if single_path else []

    @classmethod
    def _representative_file_path(cls, file_state: dict[str, Any]) -> str:
        file_paths = cls._normalize_file_paths(file_state)
        if not file_paths:
            return ""

        preview_file_path = str(file_state.get("preview_file_path") or file_state.get("file_path") or "").strip()
        if preview_file_path and preview_file_path in file_paths:
            return preview_file_path
        return file_paths[0]

    @staticmethod
    def _cached_preview_data(
        file_state: dict[str, Any],
        *,
        file_path: str,
        sheet_name: str,
        header_row: int,
        summary_column: str,
    ) -> PreviewData | None:
        preview_data = file_state.get("preview_data")
        if not isinstance(preview_data, PreviewData):
            return None
        if str(preview_data.file_path).strip() != str(file_path).strip():
            return None
        if str(preview_data.sheet_name).strip() != str(sheet_name).strip():
            return None
        if int(preview_data.header_row) != int(header_row):
            return None
        if str(preview_data.summary_column).strip() != str(summary_column).strip():
            return None
        if getattr(preview_data, "file_signatures", None) and not preview_data.files_are_current():
            raise ValueError(
                "선택한 Excel 파일이 전체 데이터 로드 후 변경되었습니다. "
                "파일 단계에서 전체 데이터를 다시 불러오세요."
            )
        return preview_data

    @staticmethod
    def _preview_raw_df_map(preview_data: PreviewData | None) -> dict[str, pd.DataFrame]:
        """`preview_raw_df_map` 미리보기를 계산한다."""
        if preview_data is None:
            return {}

        raw_df_by_file = getattr(preview_data, "raw_df_by_file", None)
        if isinstance(raw_df_by_file, dict) and raw_df_by_file:
            return {
                str(path).strip(): df
                for path, df in raw_df_by_file.items()
                if str(path).strip() and isinstance(df, pd.DataFrame)
            }

        raw_df = getattr(preview_data, "raw_df", None)
        file_path = str(getattr(preview_data, "file_path", "") or "").strip()
        if file_path and isinstance(raw_df, pd.DataFrame):
            return {file_path: raw_df}
        return {}

    @classmethod
    def _cached_raw_df_for_file(
        cls,
        preview_data: PreviewData | None,
        file_path: str,
    ) -> pd.DataFrame | None:
        return cls._preview_raw_df_map(preview_data).get(str(file_path).strip())

    @staticmethod
    def _visible_headers_from_raw_df(raw_df: pd.DataFrame) -> list[str]:
        return [
            str(column)
            for column in raw_df.columns
            if not str(column).startswith("_")
        ]

    def _visible_headers_for_file(
        self,
        file_path: str,
        *,
        sheet_name: str,
        header_row: int,
        summary_col: str,
    ) -> list[str]:
        reader = self.reader_cls(
            header_row=header_row,
            summary_col=summary_col,
            logger=self.logger,
        )
        headers = reader.read_headers(file_path, sheet_name)
        return [header for header in headers if not str(header).startswith("_")]

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
        """`validate_batch_headers` 입력을 검증한다."""
        for file_path in file_paths:
            if file_path == representative_file_path:
                continue

            cached_raw_df = self._cached_raw_df_for_file(preview_data, file_path)
            if cached_raw_df is not None:
                current_headers = self._visible_headers_from_raw_df(cached_raw_df)
            else:
                current_headers = self._visible_headers_for_file(
                    file_path,
                    sheet_name=sheet_name,
                    header_row=header_row,
                    summary_col=summary_col,
                )
            if current_headers != expected_headers:
                raise ValueError(
                    f"'{Path(file_path).name}' 파일의 헤더가 기준 파일과 다릅니다."
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
        cached_raw_df = self._cached_raw_df_for_file(preview_data, file_path)
        if cached_raw_df is not None:
            processor = HierarchyProcessor(
                header_row=header_row,
                summary_col=summary_col,
                logger=self.logger,
            )
            merged_df = processor.merge_multiline_records(cached_raw_df.copy(), list_cols=list_cols)
            return len(merged_df.index)

        reader = self.reader_cls(
            header_row=header_row,
            summary_col=summary_col,
            logger=self.logger,
        )
        if hasattr(reader, "count_upload_rows"):
            try:
                return int(reader.count_upload_rows(file_path=file_path, sheet_name=sheet_name))
            except Exception:
                pass

        raw_df = reader.read_excel(file_path=file_path, sheet_name=sheet_name)
        processor = HierarchyProcessor(
            header_row=header_row,
            summary_col=summary_col,
            logger=self.logger,
        )
        merged_df = processor.merge_multiline_records(raw_df, list_cols=list_cols)
        return len(merged_df.index)

    def _count_batch_upload_rows(
        self,
        mapping_context: MappingContext,
        *,
        list_cols: list[str],
    ) -> int:
        total_rows = 0
        for file_path in mapping_context.file_paths:
            cached_raw_df = self._cached_raw_df_for_file(mapping_context.preview_data, file_path)
            if cached_raw_df is not None:
                processor = HierarchyProcessor(
                    header_row=mapping_context.header_row,
                    summary_col=mapping_context.summary_column,
                    logger=self.logger,
                )
                merged_df = processor.merge_multiline_records(
                    cached_raw_df.copy(),
                    list_cols=list_cols,
                )
                total_rows += len(merged_df.index)
                continue

            total_rows += self._count_upload_rows_for_file(
                file_path,
                sheet_name=mapping_context.sheet_name,
                header_row=mapping_context.header_row,
                summary_col=mapping_context.summary_column,
                list_cols=list_cols,
                preview_data=mapping_context.preview_data,
            )
        return total_rows

    def _create_validation_wizard(self, mapping_context: MappingContext) -> CodebeamerUploadWizard:
        base_wizard = mapping_context.wizard
        reader = self.reader_cls(
            header_row=mapping_context.header_row,
            summary_col=mapping_context.summary_column,
            logger=self.logger,
        )
        processor = HierarchyProcessor(
            header_row=mapping_context.header_row,
            summary_col=mapping_context.summary_column,
            logger=self.logger,
        )
        wizard = CodebeamerUploadWizard(
            client=base_wizard.client,
            processor=processor,
            mapper=self.mapper,
            reader=reader,
            logger=self.logger,
        )
        wizard.state.project_id = base_wizard.state.project_id
        wizard.state.tracker_id = base_wizard.state.tracker_id
        wizard.state.upload_mode = normalize_gui_upload_mode(mapping_context.upload_mode)
        wizard.state.schema = base_wizard.state.schema
        wizard.state.schema_df = mapping_context.schema_df
        wizard.state.user_lookup_cache = dict(base_wizard.state.user_lookup_cache)
        wizard.state.member_lookup_cache = dict(base_wizard.state.member_lookup_cache)
        wizard.state.group_lookup_cache = dict(base_wizard.state.group_lookup_cache)
        wizard.state.tracker_role_cache = dict(base_wizard.state.tracker_role_cache)
        wizard.state.tracker_item_lookup_cache = dict(mapping_context.tracker_item_lookup_cache)
        return wizard

    @staticmethod
    def _annotate_source_frame(
        df: pd.DataFrame | None,
        *,
        file_label: str,
        file_path: str,
    ) -> pd.DataFrame:
        if df is None or getattr(df, "empty", True):
            return pd.DataFrame()

        work = df.copy()
        if "source_file" in work.columns:
            work["source_file"] = file_label
        else:
            work.insert(0, "source_file", file_label)
        if "source_file_path" in work.columns:
            work["source_file_path"] = file_path
        else:
            insert_at = 1 if "source_file" in work.columns else 0
            work.insert(insert_at, "source_file_path", file_path)
        return work

    @staticmethod
    def _sync_validation_wizard_caches(
        target_wizard: CodebeamerUploadWizard,
        source_wizard: CodebeamerUploadWizard,
    ) -> None:
        """`sync_validation_wizard_caches` 상태를 동기화한다."""
        target_wizard.state.user_lookup_cache = dict(source_wizard.state.user_lookup_cache)
        target_wizard.state.member_lookup_cache = dict(source_wizard.state.member_lookup_cache)
        target_wizard.state.group_lookup_cache = dict(source_wizard.state.group_lookup_cache)
        target_wizard.state.tracker_role_cache = dict(source_wizard.state.tracker_role_cache)
        target_wizard.state.tracker_item_lookup_cache = dict(source_wizard.state.tracker_item_lookup_cache)

    def _raw_df_for_file(
        self,
        mapping_context: MappingContext,
        file_path: str,
    ) -> pd.DataFrame:
        cached_raw_df = self._cached_raw_df_for_file(mapping_context.preview_data, file_path)
        if cached_raw_df is not None:
            return cached_raw_df.copy()

        reader = self.reader_cls(
            header_row=mapping_context.header_row,
            summary_col=mapping_context.summary_column,
            logger=self.logger,
        )
        return reader.read_excel(
            file_path=file_path,
            sheet_name=mapping_context.sheet_name,
        )

    def _upload_df_for_file(
        self,
        mapping_context: MappingContext,
        *,
        file_path: str,
        list_cols: list[str],
    ) -> pd.DataFrame:
        raw_df = self._raw_df_for_file(mapping_context, file_path)
        processor = HierarchyProcessor(
            header_row=mapping_context.header_row,
            summary_col=mapping_context.summary_column,
            logger=self.logger,
        )
        merged_df = processor.merge_multiline_records(raw_df, list_cols=list_cols)
        hierarchy_df = processor.add_hierarchy_by_indent(merged_df)
        return processor.build_upload_df(hierarchy_df, list_cols=list_cols)

    @classmethod
    def _build_batch_update_duplicate_issue_df(
        cls,
        mapping_context: MappingContext,
        *,
        file_upload_dfs: dict[str, pd.DataFrame],
    ) -> tuple[set[int], pd.DataFrame]:
        issue_columns = [
            "severity",
            "category",
            "row_id",
            "row_label",
            "item_name",
            "source_file",
            "source_file_path",
            "column",
            "field",
            "raw_value",
            "message",
            "action",
        ]
        if not gui_upload_mode_supports_update(mapping_context.upload_mode):
            return set(), pd.DataFrame(columns=issue_columns)

        occurrences_by_item_id: dict[int, list[dict[str, str]]] = {}
        for file_path, upload_df in file_upload_dfs.items():
            if upload_df is None or upload_df.empty:
                continue

            id_column_name = CodebeamerUploadWizard._update_item_id_column_name(upload_df)
            if not id_column_name:
                continue

            for _, row in upload_df.iterrows():
                try:
                    item_id = CodebeamerUploadWizard._parse_update_item_id(row.get(id_column_name))
                except ValueError:
                    continue

                item_name = gui_display_text(row.get("upload_name"))
                if not item_name:
                    for fallback_column in ("Summary", "summary", "요약", "name"):
                        if fallback_column in row.index:
                            item_name = gui_display_text(row.get(fallback_column))
                        if item_name:
                            break

                occurrences_by_item_id.setdefault(item_id, []).append({
                    "file_name": Path(file_path).name,
                    "row_label": cls._build_row_label(row),
                    "item_name": item_name,
                })

        duplicate_item_ids = {
            item_id
            for item_id, occurrences in occurrences_by_item_id.items()
            if len(occurrences) > 1
        }
        if not duplicate_item_ids:
            return set(), pd.DataFrame(columns=issue_columns)

        issues: list[dict[str, str]] = []
        for item_id in sorted(duplicate_item_ids):
            occurrences = occurrences_by_item_id[item_id]
            location_texts = []
            for occurrence in occurrences[:5]:
                location = occurrence["file_name"]
                if occurrence["row_label"]:
                    location = f"{location} {occurrence['row_label']}"
                location_texts.append(location)
            remaining_count = len(occurrences) - len(location_texts)
            location_summary = ", ".join(location_texts)
            if remaining_count > 0:
                location_summary = f"{location_summary} 외 {remaining_count}건"

            issues.append({
                "severity": "오류",
                "category": "업데이트",
                "row_id": "",
                "row_label": "",
                "item_name": "",
                "column": "id",
                "field": "id",
                "raw_value": str(item_id),
                "message": f"여러 파일에서 같은 item id가 중복됩니다. 대상 id={item_id} ({location_summary})",
                "action": "한 item id는 배치 전체에서 한 번만 수정되도록 파일을 정리한 뒤 다시 검증하세요.",
            })

        return duplicate_item_ids, pd.DataFrame(issues, columns=issue_columns)

    def _build_upsert_root_item_issue_df(
        self,
        mapping_context: MappingContext,
        *,
        payload_df: pd.DataFrame,
    ) -> pd.DataFrame:
        del mapping_context, payload_df
        return pd.DataFrame(columns=[
            "severity",
            "category",
            "row_id",
            "row_label",
            "item_name",
            "source_file",
            "source_file_path",
            "column",
            "field",
            "raw_value",
            "message",
            "action",
        ])

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
        """`validate_mapping` 입력을 검증한다."""
        wizard = mapping_context.wizard
        list_cols = self.mapper.get_list_columns_for_mapping(selected_mapping, mapping_context.schema_df)
        representative_file_path = mapping_context.representative_file_path
        representative_raw_df = self._raw_df_for_file(mapping_context, representative_file_path)
        wizard.load_raw_dataframe(representative_raw_df.copy(), list_cols=list_cols)
        wizard.state.upload_mode = normalize_gui_upload_mode(mapping_context.upload_mode)
        normalized_default_values = {
            str(field_name).strip(): str(raw_value).strip()
            for field_name, raw_value in (selected_default_values or {}).items()
            if str(field_name).strip() and str(raw_value).strip()
        }
        normalized_mapping_modes = self._normalize_mapping_modes(
            selected_mapping,
            selected_mapping_modes,
            upload_mode=mapping_context.upload_mode,
        )
        normalized_default_value_modes = self._normalize_default_value_modes(
            normalized_default_values,
            selected_default_value_modes,
            upload_mode=mapping_context.upload_mode,
        )
        tracker_item_field_candidates, normalized_tracker_item_settings = self._normalize_tracker_item_settings(
            mapping_context.schema_df,
            selected_mapping,
            selected_tracker_item_settings,
        )
        mapping_context.selected_mapping = selected_mapping
        mapping_context.selected_mapping_modes = normalized_mapping_modes
        mapping_context.selected_default_values = normalized_default_values
        mapping_context.selected_default_value_modes = normalized_default_value_modes
        mapping_context.selected_tracker_item_settings = normalized_tracker_item_settings
        mapping_context.tracker_item_field_candidates = tracker_item_field_candidates
        wizard.state.selected_mapping_modes = dict(normalized_mapping_modes)
        wizard.state.selected_default_value_modes = dict(normalized_default_value_modes)
        wizard.state.selected_tracker_item_settings = dict(normalized_tracker_item_settings)
        wizard.state.user_lookup_cache = dict(mapping_context.user_lookup_cache)
        wizard.state.member_lookup_cache = dict(mapping_context.member_lookup_cache)
        wizard.state.group_lookup_cache = dict(mapping_context.group_lookup_cache)
        wizard.state.tracker_role_cache = dict(mapping_context.tracker_role_cache)
        wizard.state.tracker_item_lookup_cache = dict(mapping_context.tracker_item_lookup_cache)
        wizard.state.existing_item_cache = {}
        validation_result = run_validation_pipeline(
            wizard,
            selected_mapping,
            selected_mapping_modes=normalized_mapping_modes,
            selected_default_values=normalized_default_values,
            selected_default_value_modes=normalized_default_value_modes,
            selected_tracker_item_settings=normalized_tracker_item_settings,
            fetch_existing_items=not gui_upload_mode_supports_update(mapping_context.upload_mode),
        )
        comparison_df = self._gui_visible_comparison_df(validation_result.comparison_df)
        option_check_frames = [
            self._annotate_source_frame(
                validation_result.option_check_df if validation_result.option_check_df is not None else pd.DataFrame(),
                file_label=Path(representative_file_path).name,
                file_path=representative_file_path,
            )
        ]
        payload_frames = [
            self._annotate_source_frame(
                validation_result.payload_df,
                file_label=Path(representative_file_path).name,
                file_path=representative_file_path,
            )
        ]
        row_context_frames = [
            self._annotate_source_frame(
                wizard.state.converted_upload_df
                if wizard.state.converted_upload_df is not None
                else wizard.state.upload_df,
                file_label=Path(representative_file_path).name,
                file_path=representative_file_path,
            )
        ]

        batch_wizard = None
        additional_file_paths = [
            file_path
            for file_path in mapping_context.file_paths
            if str(file_path).strip() and str(file_path).strip() != representative_file_path
        ]
        for file_path in additional_file_paths:
            if batch_wizard is None:
                batch_wizard = self._create_validation_wizard(mapping_context)
            else:
                self._sync_validation_wizard_caches(batch_wizard, wizard)
            batch_wizard.load_raw_dataframe(
                self._raw_df_for_file(mapping_context, file_path).copy(),
                list_cols=list_cols,
            )
            batch_wizard.state.selected_tracker_item_settings = dict(normalized_tracker_item_settings)
            batch_wizard.state.tracker_item_lookup_cache = dict(wizard.state.tracker_item_lookup_cache)
            batch_wizard.state.existing_item_cache = {}
            batch_validation_result = run_validation_pipeline(
                batch_wizard,
                selected_mapping,
                selected_mapping_modes=normalized_mapping_modes,
                selected_default_values=normalized_default_values,
                selected_default_value_modes=normalized_default_value_modes,
                selected_tracker_item_settings=normalized_tracker_item_settings,
                fetch_existing_items=not gui_upload_mode_supports_update(mapping_context.upload_mode),
            )
            self._sync_validation_wizard_caches(wizard, batch_wizard)
            option_check_frames.append(
                self._annotate_source_frame(
                    batch_validation_result.option_check_df
                    if batch_validation_result.option_check_df is not None
                    else pd.DataFrame(),
                    file_label=Path(file_path).name,
                    file_path=file_path,
                )
            )
            payload_frames.append(
                self._annotate_source_frame(
                    batch_validation_result.payload_df,
                    file_label=Path(file_path).name,
                    file_path=file_path,
                )
            )
            row_context_frames.append(
                self._annotate_source_frame(
                    batch_wizard.state.converted_upload_df
                    if batch_wizard.state.converted_upload_df is not None
                    else batch_wizard.state.upload_df,
                    file_label=Path(file_path).name,
                    file_path=file_path,
                )
            )

        mapping_context.user_lookup_cache = dict(wizard.state.user_lookup_cache)
        mapping_context.member_lookup_cache = dict(wizard.state.member_lookup_cache)
        mapping_context.group_lookup_cache = dict(wizard.state.group_lookup_cache)
        mapping_context.tracker_role_cache = dict(wizard.state.tracker_role_cache)
        mapping_context.tracker_item_lookup_cache = dict(wizard.state.tracker_item_lookup_cache)
        mapping_context.existing_item_cache = {}
        option_check_df = (
            pd.concat(option_check_frames, ignore_index=True)
            if any(not frame.empty for frame in option_check_frames)
            else pd.DataFrame()
        )
        payload_df = (
            pd.concat(payload_frames, ignore_index=True)
            if any(not frame.empty for frame in payload_frames)
            else pd.DataFrame()
        )
        row_context_df = (
            pd.concat(row_context_frames, ignore_index=True)
            if any(not frame.empty for frame in row_context_frames)
            else pd.DataFrame()
        )

        has_blocking = False
        if not option_check_df.empty:
            status_series = option_check_df["status"].fillna("").astype(str)
            has_blocking = bool(
                status_series.isin(BLOCKING_OPTION_STATUSES).any()
                or status_series.str.endswith(USER_LOOKUP_FAILURE_SUFFIXES).any()
            )

        if not payload_df.empty and (payload_df["payload_status"] != PayloadStatus.READY.value).any():
            has_blocking = True

        issue_df = self._build_user_issue_df(
            comparison_df,
            option_check_df,
            payload_df,
            row_context_df=row_context_df,
            selected_default_values=normalized_default_values,
        )
        mapping_context.batch_duplicate_update_item_ids = set()
        if gui_upload_mode_supports_update(mapping_context.upload_mode):
            file_upload_dfs = {
                file_path: self._upload_df_for_file(
                    mapping_context,
                    file_path=file_path,
                    list_cols=list_cols,
                )
                for file_path in mapping_context.file_paths
            }
            duplicate_item_ids, duplicate_issue_df = self._build_batch_update_duplicate_issue_df(
                mapping_context,
                file_upload_dfs=file_upload_dfs,
            )
            mapping_context.batch_duplicate_update_item_ids = set(duplicate_item_ids)
            if not duplicate_issue_df.empty:
                issue_df = pd.concat([issue_df, duplicate_issue_df], ignore_index=True)
                issue_df = self._finalize_issue_df(issue_df)
        upsert_root_issue_df = self._build_upsert_root_item_issue_df(
            mapping_context,
            payload_df=payload_df,
        )
        if not upsert_root_issue_df.empty:
            issue_df = pd.concat([issue_df, upsert_root_issue_df], ignore_index=True)
            issue_df = self._finalize_issue_df(issue_df)
        summary_stats = self._build_summary_stats(issue_df, row_context_df)
        summary_stats["file_count"] = len(mapping_context.file_paths)
        summary_stats["batch_total_rows"] = self._count_batch_upload_rows(
            mapping_context,
            list_cols=list_cols,
        )
        if not issue_df.empty and issue_df["severity"].eq("오류").any():
            has_blocking = True

        return ValidationContext(
            comparison_df=comparison_df,
            option_check_df=option_check_df,
            converted_upload_df=row_context_df,
            payload_df=payload_df,
            issue_df=issue_df,
            has_blocking_issues=has_blocking,
            summary_stats=summary_stats,
        )

    @classmethod
    def _build_row_label(cls, row: pd.Series) -> str:
        """중복 update 이슈에서 사용할 Excel 행 표시를 만든다."""
        return ValidationPresenter.build_row_label(row)
