from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from src.hierarchy_processor import HierarchyProcessor
from src.models import OptionMapKind
from src.models import PayloadStatus
from src.wizard import CodebeamerUploadWizard

from .service_core import PreviewData
from .service_core import gui_display_text
from .upload_context import MappingContext
from .upload_context import RootFieldCandidate
from .upload_context import RootItemPreviewContext
from .upload_context import RootItemUploadSpec
from .upload_context import RootSourceOption


ROOT_SOURCE_FILE_NAME = "__file_name__"
ROOT_SOURCE_FILE_STEM = "__file_stem__"
ROOT_SOURCE_REGEX_FULL = "__regex_full__"
ROOT_SOURCE_GROUP_VALUE = "__group_value__"
ROOT_REGEX_TARGET_FILE_NAME = "file_name"
ROOT_REGEX_TARGET_FILE_STEM = "file_stem"
ROOT_ITEM_MODE_FILE = "file"
ROOT_ITEM_MODE_GROUP_BY_COLUMN = "group_by_column"
ROOT_ASSIGNMENT_MODE_FILE_SOURCE = "file_source"
ROOT_ASSIGNMENT_MODE_FIXED_VALUE = "fixed_value"

GUI_VALUE_KIND_STATIC_OPTIONS = "static_options"
GUI_VALUE_KIND_BOOL = "bool"
GUI_VALUE_KIND_SCALAR = "scalar"


class RootItemService:
    """파일·그룹 루트 항목의 설정, 미리보기와 업로드 명세를 구성한다."""

    def __init__(
        self,
        *,
        mapper: Any,
        reader_cls: type,
        logger: Any = None,
        is_schema_field_excluded: Callable[[pd.Series | dict[str, Any]], bool],
    ) -> None:
        self.mapper = mapper
        self.reader_cls = reader_cls
        self.logger = logger
        self._is_gui_excluded_schema_field = is_schema_field_excluded

    @staticmethod
    def _preview_raw_df_map(preview_data: PreviewData | None) -> dict[str, pd.DataFrame]:
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
    def _root_regex_target_options() -> list[tuple[str, str]]:
        return [
            (ROOT_REGEX_TARGET_FILE_STEM, "파일명(확장자 제외)"),
            (ROOT_REGEX_TARGET_FILE_NAME, "전체 파일명"),
        ]

    @staticmethod
    def _normalize_root_mode(value: Any) -> str:
        normalized = str(value or ROOT_ITEM_MODE_FILE).strip()
        if normalized in {ROOT_ITEM_MODE_FILE, ROOT_ITEM_MODE_GROUP_BY_COLUMN}:
            return normalized
        return ROOT_ITEM_MODE_FILE

    @staticmethod
    def _root_group_column_options(mapping_context: MappingContext) -> list[str]:
        return [
            str(column).strip()
            for column in mapping_context.upload_columns
            if str(column).strip()
        ]

    @classmethod
    def _root_group_source_label(cls, group_by_column: str) -> str:
        normalized = str(group_by_column or "").strip()
        if not normalized:
            return cls._root_source_label(ROOT_SOURCE_GROUP_VALUE)
        return f"그룹값 ({normalized})"

    @staticmethod
    def _root_source_label(source_key: str) -> str:
        if source_key == ROOT_SOURCE_FILE_STEM:
            return "파일명(확장자 제외)"
        if source_key == ROOT_SOURCE_FILE_NAME:
            return "전체 파일명"
        if source_key == ROOT_SOURCE_GROUP_VALUE:
            return "그룹값"
        if source_key == ROOT_SOURCE_REGEX_FULL:
            return "정규식 전체 일치"
        if source_key.startswith("group"):
            return f"정규식 {source_key}"
        return source_key

    @classmethod
    def _root_parse_target_text(cls, file_path: str, regex_target: str) -> str:
        if regex_target == ROOT_REGEX_TARGET_FILE_NAME:
            return Path(file_path).name
        return Path(file_path).stem

    def _root_upload_df_for_file(
        self,
        mapping_context: MappingContext,
        file_path: str,
    ) -> pd.DataFrame:
        representative = str(mapping_context.representative_file_path or "").strip()
        if (
            representative
            and representative == str(file_path).strip()
            and mapping_context.wizard.state.upload_df is not None
        ):
            return mapping_context.wizard.state.upload_df.copy()

        raw_df = self._cached_raw_df_for_file(mapping_context.preview_data, file_path)
        if raw_df is None:
            reader = self.reader_cls(
                header_row=mapping_context.header_row,
                summary_col=mapping_context.summary_column,
                logger=self.logger,
            )
            raw_df = reader.read_excel(
                file_path=file_path,
                sheet_name=mapping_context.sheet_name,
            )

        processor = HierarchyProcessor(
            header_row=mapping_context.header_row,
            summary_col=mapping_context.summary_column,
            logger=self.logger,
        )
        merged_df = processor.merge_multiline_records(raw_df.copy(), list_cols=list(mapping_context.list_cols))
        hierarchy_df = processor.add_hierarchy_by_indent(merged_df)
        return processor.build_upload_df(hierarchy_df, list_cols=list(mapping_context.list_cols))

    @staticmethod
    def _top_level_upload_df(
        upload_df: pd.DataFrame,
        *,
        allowed_row_ids: set[int] | None = None,
    ) -> pd.DataFrame:
        if upload_df is None or upload_df.empty:
            return pd.DataFrame()

        top_level_mask = upload_df["parent_row_id"].apply(lambda value: value is None or pd.isna(value))
        top_level_df = upload_df[top_level_mask].copy()
        if allowed_row_ids is not None:
            top_level_df = top_level_df[top_level_df["_row_id"].isin(sorted(allowed_row_ids))].copy()
        return top_level_df.reset_index(drop=True)

    def _build_root_source_rows(
        self,
        mapping_context: MappingContext,
        *,
        file_path: str,
        file_root_enabled: bool,
        group_enabled: bool,
        group_by_column: str,
        regex_pattern: str,
        regex_target: str,
        allowed_row_ids: set[int] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        file_sources, matched, regex_error = self._root_sources_for_file(
            file_path,
            regex_pattern=regex_pattern,
            regex_target=regex_target,
        )
        upload_df = self._root_upload_df_for_file(mapping_context, file_path)
        top_level_df = self._top_level_upload_df(upload_df, allowed_row_ids=allowed_row_ids)
        if top_level_df.empty and allowed_row_ids is not None:
            return [], [], regex_error

        rows: list[dict[str, Any]] = []
        file_key = str(file_path).strip()
        top_level_row_ids = [int(row_id) for row_id in top_level_df["_row_id"].tolist()]

        if file_root_enabled:
            rows.append({
                "key": file_key,
                "sources": dict(file_sources),
                "row_ids": [] if group_enabled and str(group_by_column or "").strip() else top_level_row_ids,
                "matched": matched,
                "kind": "file_root",
                "parent_key": None,
            })

        if not group_enabled or not str(group_by_column or "").strip():
            if rows:
                return rows, [], regex_error
            return [], [], regex_error

        missing_group_values: list[str] = []
        grouped_rows: dict[str, dict[str, Any]] = {}
        for _, row in top_level_df.iterrows():
            row_id = int(row["_row_id"])
            group_value = gui_display_text(row.get(group_by_column))
            if not group_value:
                row_label = gui_display_text(row.get("upload_name")) or f"row {row_id}"
                missing_group_values.append(f"{Path(file_path).name}:{row_label}")
                continue

            group_entry = grouped_rows.setdefault(
                group_value,
                {
                    "key": f"{str(file_path).strip()}::{group_value}",
                    "sources": {
                        **file_sources,
                        ROOT_SOURCE_GROUP_VALUE: group_value,
                    },
                    "row_ids": [],
                    "matched": matched,
                    "kind": "group_root",
                    "parent_key": file_key if file_root_enabled else None,
                },
            )
            group_entry["row_ids"].append(row_id)

        rows.extend(list(grouped_rows.values()))
        return rows, missing_group_values, regex_error

    @staticmethod
    def _root_assignment(
        *,
        enabled: bool,
        mode: str,
        value: str,
    ) -> dict[str, Any]:
        normalized_mode = str(mode or ROOT_ASSIGNMENT_MODE_FILE_SOURCE).strip()
        if normalized_mode not in {
            ROOT_ASSIGNMENT_MODE_FILE_SOURCE,
            ROOT_ASSIGNMENT_MODE_FIXED_VALUE,
        }:
            normalized_mode = ROOT_ASSIGNMENT_MODE_FILE_SOURCE
        return {
            "enabled": bool(enabled),
            "mode": normalized_mode,
            "value": str(value or "").strip(),
        }

    @classmethod
    def _root_file_source_assignments(
        cls,
        field_assignments: dict[str, dict[str, Any]],
    ) -> dict[str, str]:
        field_sources: dict[str, str] = {}
        for schema_field, assignment in field_assignments.items():
            if not isinstance(assignment, dict):
                continue
            if not bool(assignment.get("enabled")):
                continue
            if str(assignment.get("mode") or "").strip() != ROOT_ASSIGNMENT_MODE_FILE_SOURCE:
                continue
            source_key = str(assignment.get("value") or "").strip()
            if source_key:
                field_sources[str(schema_field).strip()] = source_key
        return field_sources

    @staticmethod
    def _name_schema_field(schema_df: pd.DataFrame) -> str | None:
        if schema_df is None or schema_df.empty:
            return None
        matched = schema_df[schema_df["tracker_item_field"].astype(str) == "name"]
        if matched.empty:
            return None
        return str(matched.iloc[0]["field_name"])

    def _default_root_item_config(self, schema_df: pd.DataFrame) -> dict[str, Any]:
        """`default_root_item_config` 기본값을 계산한다."""
        field_assignments: dict[str, dict[str, Any]] = {}
        name_schema_field = self._name_schema_field(schema_df)
        if name_schema_field:
            field_assignments[name_schema_field] = self._root_assignment(
                enabled=True,
                mode=ROOT_ASSIGNMENT_MODE_FILE_SOURCE,
                value=ROOT_SOURCE_FILE_STEM,
            )
        return {
            "enabled": True,
            "group_enabled": False,
            "root_mode": ROOT_ITEM_MODE_FILE,
            "group_by_column": "",
            "regex_pattern": "",
            "regex_target": ROOT_REGEX_TARGET_FILE_STEM,
            "field_assignments": field_assignments,
            "field_sources": self._root_file_source_assignments(field_assignments),
        }

    @classmethod
    def _normalize_root_item_config(
        cls,
        schema_df: pd.DataFrame,
        root_item_config: dict[str, Any] | None,
        *,
        default_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = dict(default_config or {})
        if root_item_config:
            config.update(root_item_config)
        explicit_root_config = dict(root_item_config or {})
        has_explicit_field_assignments = "field_assignments" in explicit_root_config
        explicit_field_sources = explicit_root_config.get("field_sources")
        group_by_column = str(config.get("group_by_column") or "").strip()
        legacy_root_mode = cls._normalize_root_mode(config.get("root_mode"))
        enabled = bool(config.get("enabled", True))
        if "group_enabled" in explicit_root_config:
            group_enabled = bool(explicit_root_config.get("group_enabled"))
        else:
            group_enabled = legacy_root_mode == ROOT_ITEM_MODE_GROUP_BY_COLUMN and bool(group_by_column)
            if group_enabled:
                enabled = False
        root_mode = ROOT_ITEM_MODE_GROUP_BY_COLUMN if group_enabled else ROOT_ITEM_MODE_FILE

        regex_pattern = str(config.get("regex_pattern") or "").strip()
        regex_target = str(config.get("regex_target") or ROOT_REGEX_TARGET_FILE_STEM).strip()
        if regex_target not in {ROOT_REGEX_TARGET_FILE_STEM, ROOT_REGEX_TARGET_FILE_NAME}:
            regex_target = ROOT_REGEX_TARGET_FILE_STEM

        field_assignments: dict[str, dict[str, Any]] = {}
        raw_field_assignments = config.get("field_assignments")
        if isinstance(raw_field_assignments, dict):
            for schema_field, raw_assignment in raw_field_assignments.items():
                field_name = str(schema_field or "").strip()
                if not field_name:
                    continue
                if isinstance(raw_assignment, dict):
                    field_assignments[field_name] = cls._root_assignment(
                        enabled=bool(raw_assignment.get("enabled")),
                        mode=str(raw_assignment.get("mode") or ROOT_ASSIGNMENT_MODE_FILE_SOURCE),
                        value=str(raw_assignment.get("value") or ""),
                    )
                    continue

                field_assignments[field_name] = cls._root_assignment(
                    enabled=True,
                    mode=ROOT_ASSIGNMENT_MODE_FILE_SOURCE,
                    value=str(raw_assignment or ""),
                )

        raw_field_sources = config.get("field_sources")
        if isinstance(raw_field_sources, dict):
            for schema_field, source_key in raw_field_sources.items():
                field_name = str(schema_field or "").strip()
                source_name = str(source_key or "").strip()
                if not field_name:
                    continue
                if field_name in field_assignments and has_explicit_field_assignments:
                    continue
                field_assignments[field_name] = cls._root_assignment(
                    enabled=True,
                    mode=ROOT_ASSIGNMENT_MODE_FILE_SOURCE,
                    value=source_name,
                )

        name_schema_field = cls._name_schema_field(schema_df)
        explicit_name_assignment = False
        if name_schema_field:
            raw_explicit_assignments = explicit_root_config.get("field_assignments")
            if (isinstance(raw_explicit_assignments, dict) and name_schema_field in raw_explicit_assignments) or (
                isinstance(explicit_field_sources, dict) and name_schema_field in explicit_field_sources
            ):
                explicit_name_assignment = True

        if (
            root_mode == ROOT_ITEM_MODE_GROUP_BY_COLUMN
            and group_by_column
            and name_schema_field
            and not explicit_name_assignment
        ):
            field_assignments[name_schema_field] = cls._root_assignment(
                enabled=True,
                mode=ROOT_ASSIGNMENT_MODE_FILE_SOURCE,
                value=ROOT_SOURCE_GROUP_VALUE,
            )

        return {
            "enabled": enabled,
            "group_enabled": group_enabled,
            "root_mode": root_mode,
            "group_by_column": group_by_column,
            "regex_pattern": regex_pattern,
            "regex_target": regex_target,
            "field_assignments": field_assignments,
            "field_sources": cls._root_file_source_assignments(field_assignments),
        }

    def _root_field_candidates(self, schema_df: pd.DataFrame) -> list[RootFieldCandidate]:
        option_maps = self.mapper.build_option_maps_from_schema(schema_df)
        candidates: list[RootFieldCandidate] = []

        for _, row in schema_df.iterrows():
            if self._is_gui_excluded_schema_field(row):
                continue
            if bool(row.get("is_table_field", False)):
                continue

            schema_field = str(row.get("field_name") or "").strip()
            if not schema_field:
                continue

            supported = bool(row.get("is_supported", True))
            fixed_value_kind = ""
            fixed_options: list[str] = []
            allows_fixed_value = False
            allows_custom_value = False
            if bool(row.get("is_option_like", False)):
                option_info = option_maps.get(schema_field, {})
                kind = option_info.get("kind")
                supported = supported and kind not in {
                    None,
                    OptionMapKind.UNSUPPORTED.value,
                    OptionMapKind.REFERENCE_LOOKUP.value,
                }
                if supported and kind == OptionMapKind.STATIC_OPTIONS.value:
                    fixed_value_kind = GUI_VALUE_KIND_STATIC_OPTIONS
                    fixed_options = [
                        str(option.get("name")).strip()
                        for option in option_info.get("options") or []
                        if str(option.get("name") or "").strip()
                    ]
                    allows_fixed_value = bool(fixed_options)
                elif (
                    supported
                    and kind in {
                        OptionMapKind.MEMBER_LOOKUP.value,
                        OptionMapKind.TRACKER_ITEM_DIRECT.value,
                        OptionMapKind.USER_LOOKUP.value,
                    }
                ):
                    fixed_value_kind = GUI_VALUE_KIND_SCALAR
                    allows_fixed_value = True
                    allows_custom_value = True
            elif supported and not bool(row.get("multiple_values", False)):
                field_type = str(row.get("field_type") or "").strip()
                if field_type == "BoolField":
                    fixed_value_kind = GUI_VALUE_KIND_BOOL
                    fixed_options = ["true", "false"]
                    allows_fixed_value = True
                else:
                    fixed_value_kind = GUI_VALUE_KIND_SCALAR
                    allows_fixed_value = True
                    allows_custom_value = True

            candidates.append(RootFieldCandidate(
                schema_field=schema_field,
                field_type=str(row.get("field_type") or ""),
                mandatory=bool(row.get("mandatory", False)),
                supported=supported,
                fixed_value_kind=fixed_value_kind,
                fixed_options=fixed_options,
                allows_file_source=supported,
                allows_fixed_value=allows_fixed_value,
                allows_custom_value=allows_custom_value,
            ))

        return candidates

    @staticmethod
    def _compiled_root_regex(regex_pattern: str) -> tuple[re.Pattern[str] | None, str | None]:
        pattern = str(regex_pattern or "").strip()
        if not pattern:
            return None, None
        try:
            return re.compile(pattern), None
        except re.error as exc:
            return None, str(exc)

    @classmethod
    def _root_regex_group_keys(cls, compiled_pattern: re.Pattern[str] | None) -> list[str]:
        if compiled_pattern is None:
            return []
        if compiled_pattern.groupindex:
            return [name for name, _ in sorted(compiled_pattern.groupindex.items(), key=lambda item: item[1])]
        return [f"group{index}" for index in range(1, compiled_pattern.groups + 1)]

    @classmethod
    def _root_sources_for_file(
        cls,
        file_path: str,
        *,
        regex_pattern: str,
        regex_target: str,
    ) -> tuple[dict[str, str], bool, str | None]:
        sources = {
            ROOT_SOURCE_FILE_NAME: Path(file_path).name,
            ROOT_SOURCE_FILE_STEM: Path(file_path).stem,
        }
        compiled_pattern, regex_error = cls._compiled_root_regex(regex_pattern)
        if regex_error is not None:
            return sources, False, regex_error
        if compiled_pattern is None:
            return sources, True, None

        target_text = cls._root_parse_target_text(file_path, regex_target)
        match = compiled_pattern.search(target_text)
        if match is None:
            return sources, False, None

        sources[ROOT_SOURCE_REGEX_FULL] = match.group(0)
        group_keys = cls._root_regex_group_keys(compiled_pattern)
        if compiled_pattern.groupindex:
            for group_key in group_keys:
                value = match.group(group_key)
                sources[group_key] = "" if value is None else str(value)
        else:
            for group_index, group_key in enumerate(group_keys, start=1):
                value = match.group(group_index)
                sources[group_key] = "" if value is None else str(value)
        return sources, True, None

    def build_root_item_preview_context(
        self,
        mapping_context: MappingContext,
        root_item_config: dict[str, Any] | None = None,
    ) -> RootItemPreviewContext:
        default_config = self._default_root_item_config(mapping_context.schema_df)
        normalized = self._normalize_root_item_config(
            mapping_context.schema_df,
            root_item_config or mapping_context.root_item_config,
            default_config=default_config,
        )
        file_root_enabled = bool(normalized.get("enabled", True))
        group_enabled = bool(normalized.get("group_enabled", False))
        root_mode = self._normalize_root_mode(normalized.get("root_mode"))
        group_column_options = self._root_group_column_options(mapping_context)
        group_by_column = str(normalized.get("group_by_column") or "").strip()
        if group_by_column and group_by_column not in group_column_options:
            group_by_column = ""
        regex_pattern = normalized["regex_pattern"]
        regex_target = normalized["regex_target"]
        field_assignments = {
            str(schema_field): dict(assignment)
            for schema_field, assignment in dict(normalized.get("field_assignments") or {}).items()
            if str(schema_field).strip() and isinstance(assignment, dict)
        }
        field_candidates = self._root_field_candidates(mapping_context.schema_df)
        candidate_by_field = {
            candidate.schema_field: candidate
            for candidate in field_candidates
        }

        compiled_pattern, regex_error = self._compiled_root_regex(regex_pattern)
        source_options = [
            RootSourceOption(ROOT_SOURCE_FILE_STEM, self._root_source_label(ROOT_SOURCE_FILE_STEM)),
            RootSourceOption(ROOT_SOURCE_FILE_NAME, self._root_source_label(ROOT_SOURCE_FILE_NAME)),
        ]
        if group_enabled and group_by_column:
            source_options.append(
                RootSourceOption(ROOT_SOURCE_GROUP_VALUE, self._root_group_source_label(group_by_column))
            )
        if compiled_pattern is not None:
            source_options.append(
                RootSourceOption(ROOT_SOURCE_REGEX_FULL, self._root_source_label(ROOT_SOURCE_REGEX_FULL))
            )
            for group_key in self._root_regex_group_keys(compiled_pattern):
                source_options.append(RootSourceOption(group_key, self._root_source_label(group_key)))

        if not file_root_enabled and not group_enabled:
            preview_columns = ["file_name"]
            preview_rows = [
                {"file_name": Path(file_path).name}
                for file_path in mapping_context.file_paths
            ]
            return RootItemPreviewContext(
                enabled=False,
                group_enabled=False,
                root_mode=root_mode,
                group_by_column=group_by_column,
                group_column_options=group_column_options,
                regex_pattern=regex_pattern,
                regex_target=regex_target,
                field_assignments=field_assignments,
                field_sources=self._root_file_source_assignments(field_assignments),
                field_candidates=field_candidates,
                source_options=source_options,
                preview_columns=preview_columns,
                preview_rows=preview_rows,
                regex_error=None,
                status_message="상단 데이터 생성을 사용하지 않습니다. 이 단계 설정은 업로드에서 무시됩니다.",
                has_blocking_issues=False,
            )

        preview_columns = ["level", "file_name", "parse_target", "matched"]
        if group_enabled:
            preview_columns.insert(1, ROOT_SOURCE_GROUP_VALUE)
        if compiled_pattern is not None:
            preview_columns.append(ROOT_SOURCE_REGEX_FULL)
            preview_columns.extend(self._root_regex_group_keys(compiled_pattern))

        valid_source_keys = {
            str(option.key)
            for option in source_options
        }
        invalid_assignments: list[str] = []
        normalized_assignments: dict[str, dict[str, Any]] = {}
        for schema_field, candidate in candidate_by_field.items():
            raw_assignment = field_assignments.get(schema_field)
            if raw_assignment is None:
                continue

            assignment = self._root_assignment(
                enabled=bool(raw_assignment.get("enabled")),
                mode=str(raw_assignment.get("mode") or ROOT_ASSIGNMENT_MODE_FILE_SOURCE),
                value=str(raw_assignment.get("value") or ""),
            )
            normalized_assignments[schema_field] = assignment
            if not assignment["enabled"]:
                continue

            if assignment["mode"] == ROOT_ASSIGNMENT_MODE_FILE_SOURCE:
                if not candidate.allows_file_source:
                    invalid_assignments.append(schema_field)
                    continue
                if not assignment["value"] or assignment["value"] not in valid_source_keys:
                    invalid_assignments.append(schema_field)
                    continue
                continue

            if assignment["mode"] == ROOT_ASSIGNMENT_MODE_FIXED_VALUE:
                if not candidate.allows_fixed_value:
                    invalid_assignments.append(schema_field)
                    continue
                if not assignment["value"]:
                    invalid_assignments.append(schema_field)
                    continue
                if candidate.fixed_options and assignment["value"] not in candidate.fixed_options:
                    invalid_assignments.append(schema_field)
                    continue
                continue

            invalid_assignments.append(schema_field)

        preview_rows = []
        missing_sources: list[str] = []
        missing_group_values: list[str] = []
        target_kind = "group_root" if group_enabled and group_by_column else "file_root"
        for file_path in mapping_context.file_paths:
            source_rows, current_missing_group_values, source_error = self._build_root_source_rows(
                mapping_context,
                file_path=file_path,
                file_root_enabled=file_root_enabled,
                group_enabled=group_enabled,
                group_by_column=group_by_column,
                regex_pattern=regex_pattern,
                regex_target=regex_target,
            )
            if source_error is not None and regex_error is None:
                regex_error = source_error
            missing_group_values.extend(current_missing_group_values)
            for source_row in source_rows:
                sources = dict(source_row.get("sources") or {})
                preview_row = {
                    "level": "파일 루트" if str(source_row.get("kind") or "") == "file_root" else "그룹 폴더",
                    "file_name": Path(file_path).name,
                    "parse_target": self._root_parse_target_text(file_path, regex_target),
                    "matched": "yes" if bool(source_row.get("matched")) else ("regex error" if regex_error else "no"),
                }
                for column_name in preview_columns:
                    if column_name in {"level", "file_name", "parse_target", "matched"}:
                        continue
                    preview_row[column_name] = str(sources.get(column_name) or "")
                preview_rows.append(preview_row)

                if str(source_row.get("kind") or "") != target_kind:
                    continue
                for schema_field, assignment in normalized_assignments.items():
                    if not bool(assignment.get("enabled")):
                        continue
                    if str(assignment.get("mode") or "") != ROOT_ASSIGNMENT_MODE_FILE_SOURCE:
                        continue
                    source_key = str(assignment.get("value") or "").strip()
                    if not source_key:
                        continue
                    if not str(sources.get(source_key) or "").strip():
                        missing_sources.append(f"{Path(file_path).name}:{schema_field}")

        effective_group_mode = group_enabled and bool(group_by_column)
        has_blocking_issues = regex_error is not None
        status_message = (
            "파일 루트와 그룹 폴더 구성을 확인하세요."
            if file_root_enabled and effective_group_mode
            else (
                "파일별 그룹값과 루트 필드 값을 확인하세요."
                if effective_group_mode
                else "파일명 파싱 결과와 루트 필드 값을 확인하세요."
            )
        )
        if regex_error is not None:
            status_message = f"정규식 오류: {regex_error}"
        elif group_enabled and not group_by_column and not file_root_enabled:
            has_blocking_issues = True
            status_message = "그룹 폴더를 생성하려면 그룹 컬럼을 선택하세요."
        elif effective_group_mode and missing_group_values:
            has_blocking_issues = True
            status_message = "일부 최상위 데이터에 그룹 컬럼 값이 비어 있습니다."
        elif invalid_assignments:
            has_blocking_issues = True
            status_message = "선택한 루트 필드의 값 방식 또는 값이 현재 스키마와 맞지 않습니다."
        elif missing_sources:
            has_blocking_issues = True
            status_message = "일부 파일에서 선택한 루트 필드 소스를 만들 수 없습니다."
        elif group_enabled and not group_by_column and file_root_enabled:
            status_message = "그룹 컬럼을 선택하지 않아 파일 루트만 생성합니다."

        return RootItemPreviewContext(
            enabled=file_root_enabled,
            group_enabled=group_enabled,
            root_mode=root_mode,
            group_by_column=group_by_column,
            group_column_options=group_column_options,
            regex_pattern=regex_pattern,
            regex_target=regex_target,
            field_assignments=normalized_assignments,
            field_sources=self._root_file_source_assignments(normalized_assignments),
            field_candidates=field_candidates,
            source_options=source_options,
            preview_columns=preview_columns,
            preview_rows=preview_rows,
            regex_error=regex_error,
            status_message=status_message,
            has_blocking_issues=has_blocking_issues,
        )

    @staticmethod
    def _root_assignment_target_kind(preview_context: RootItemPreviewContext) -> str:
        return "group_root" if bool(preview_context.group_enabled and preview_context.group_by_column) else "file_root"

    @classmethod
    def _root_field_values_for_source_row(
        cls,
        preview_context: RootItemPreviewContext,
        source_row: dict[str, Any],
        *,
        name_schema_field: str | None = None,
    ) -> dict[str, Any]:
        row_kind = str(source_row.get("kind") or "")
        sources = dict(source_row.get("sources") or {})
        root_field_values: dict[str, Any] = {}
        for schema_field, assignment in preview_context.field_assignments.items():
            if not bool(assignment.get("enabled")):
                continue

            assignment_mode = str(assignment.get("mode") or "").strip()
            assignment_value = str(assignment.get("value") or "").strip()
            if bool(preview_context.group_enabled and preview_context.group_by_column):
                if row_kind == "file_root" and assignment_value == ROOT_SOURCE_GROUP_VALUE:
                    continue
                if (
                    row_kind == "group_root"
                    and bool(preview_context.enabled)
                    and schema_field == name_schema_field
                ):
                    continue
            elif row_kind != "file_root":
                continue

            if assignment_mode == ROOT_ASSIGNMENT_MODE_FILE_SOURCE:
                raw_value = str(sources.get(assignment_value) or "").strip()
            elif assignment_mode == ROOT_ASSIGNMENT_MODE_FIXED_VALUE:
                raw_value = assignment_value
            else:
                raw_value = ""

            if raw_value:
                root_field_values[schema_field] = raw_value

        return root_field_values

    def build_root_item_payload_specs(
        self,
        mapping_context: MappingContext,
        wizard: CodebeamerUploadWizard,
        file_path: str,
    ) -> list[RootItemUploadSpec]:
        preview_context = self.build_root_item_preview_context(mapping_context, mapping_context.root_item_config)
        if not bool(preview_context.enabled) and not bool(preview_context.group_enabled):
            return []
        if bool(preview_context.has_blocking_issues):
            raise ValueError(str(preview_context.status_message or "루트 데이터 설정이 올바르지 않습니다."))

        payload_df = wizard.state.payload_df if wizard.state.payload_df is not None else wizard.build_payloads()
        if payload_df is None or payload_df.empty:
            return []

        ready_top_level_row_ids = {
            int(row_id)
            for row_id in payload_df[
                payload_df["payload_status"].eq(PayloadStatus.READY.value)
                & payload_df["parent_row_id"].apply(lambda value: value is None or pd.isna(value))
            ]["_row_id"].tolist()
        }
        if not ready_top_level_row_ids:
            return []

        source_rows, _, regex_error = self._build_root_source_rows(
            mapping_context,
            file_path=file_path,
            file_root_enabled=bool(preview_context.enabled),
            group_enabled=bool(preview_context.group_enabled),
            group_by_column=preview_context.group_by_column,
            regex_pattern=preview_context.regex_pattern,
            regex_target=preview_context.regex_target,
            allowed_row_ids=ready_top_level_row_ids,
        )
        if regex_error is not None:
            raise ValueError(f"루트 데이터 정규식 오류: {regex_error}")

        name_schema_field = self._name_schema_field(mapping_context.schema_df)
        root_item_specs: list[RootItemUploadSpec] = []
        for source_row in source_rows:
            sources = dict(source_row.get("sources") or {})
            root_field_values = self._root_field_values_for_source_row(
                preview_context,
                source_row,
                name_schema_field=name_schema_field,
            )
            row_kind = str(source_row.get("kind") or "")
            root_item_name = (
                str(sources.get(ROOT_SOURCE_GROUP_VALUE) or "").strip()
                if row_kind == "group_root"
                else (Path(file_path).stem.strip() or "")
            )
            if name_schema_field and str(root_field_values.get(name_schema_field) or "").strip():
                root_item_name = str(root_field_values[name_schema_field]).strip()
            if not root_item_name:
                continue

            root_item_specs.append(RootItemUploadSpec(
                key=str(source_row.get("key") or root_item_name),
                name=root_item_name,
                field_values=root_field_values,
                row_ids=[
                    int(row_id)
                    for row_id in (source_row.get("row_ids") or [])
                    if str(row_id).strip()
                ],
                parent_key=(
                    str(source_row.get("parent_key") or "").strip()
                    or None
                ),
                kind=row_kind or "group_root",
            ))

        return root_item_specs

    def build_root_item_payload_spec(
        self,
        mapping_context: MappingContext,
        file_path: str,
    ) -> tuple[str | None, dict[str, Any]]:
        preview_context = self.build_root_item_preview_context(mapping_context, mapping_context.root_item_config)
        if not bool(preview_context.enabled) and not bool(preview_context.group_enabled):
            return None, {}
        if bool(preview_context.has_blocking_issues):
            raise ValueError(str(preview_context.status_message or "루트 데이터 설정이 올바르지 않습니다."))

        source_rows, _, regex_error = self._build_root_source_rows(
            mapping_context,
            file_path=file_path,
            file_root_enabled=bool(preview_context.enabled),
            group_enabled=bool(preview_context.group_enabled),
            group_by_column=preview_context.group_by_column,
            regex_pattern=preview_context.regex_pattern,
            regex_target=preview_context.regex_target,
            allowed_row_ids=None,
        )
        if regex_error is not None:
            raise ValueError(f"루트 데이터 정규식 오류: {regex_error}")
        if not source_rows:
            return None, {}

        first_row = source_rows[0]
        sources = dict(first_row.get("sources") or {})
        name_schema_field = self._name_schema_field(mapping_context.schema_df)
        root_field_values = self._root_field_values_for_source_row(
            preview_context,
            first_row,
            name_schema_field=name_schema_field,
        )
        row_kind = str(first_row.get("kind") or "")
        root_item_name = (
            str(sources.get(ROOT_SOURCE_GROUP_VALUE) or "").strip()
            if row_kind == "group_root"
            else (Path(file_path).stem.strip() or None)
        )
        if name_schema_field and str(root_field_values.get(name_schema_field) or "").strip():
            root_item_name = str(root_field_values[name_schema_field]).strip()
        return root_item_name, root_field_values
