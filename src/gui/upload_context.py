from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.upload_policy import OperationScope
from src.wizard import CodebeamerUploadWizard

from .service_core import PreviewData


@dataclass
class DefaultValueCandidate:
    schema_field: str
    field_type: str
    value_kind: str
    options: list[str]
    mandatory: bool
    allows_custom_value: bool


@dataclass
class TrackerItemFieldCandidate:
    df_column: str
    schema_field: str
    field_type: str
    source_tracker_ids: list[int]
    supports_query: bool
    query_status: str


@dataclass
class MappingContext:
    wizard: CodebeamerUploadWizard
    upload_mode: str
    schema_df: pd.DataFrame
    upload_columns: list[str]
    selected_mapping: dict[str, str]
    selected_mapping_modes: dict[str, OperationScope]
    default_value_candidates: list[DefaultValueCandidate]
    selected_default_values: dict[str, str]
    selected_default_value_modes: dict[str, OperationScope]
    selected_tracker_item_settings: dict[str, dict[str, Any]]
    tracker_item_field_candidates: list[TrackerItemFieldCandidate]
    tracker_item_lookup_cache: dict[tuple[str, str], tuple[Any, str | None, str | None]]
    user_lookup_cache: dict[tuple[int | None, str], tuple[Any, Any, str, str | None]]
    member_lookup_cache: dict[tuple[int | None, int | None, int | None, str], tuple[Any, Any, str, str | None]]
    group_lookup_cache: dict[str, list[dict[str, Any]]]
    tracker_role_cache: dict[tuple[int, int, int], dict[str, list[dict[str, Any]]]]
    list_cols: list[str]
    file_paths: list[str]
    representative_file_path: str
    sheet_name: str
    header_row: int
    summary_column: str
    preview_data: PreviewData | None
    root_item_config: dict[str, Any]
    existing_item_cache: dict[int, dict[str, Any]]
    batch_duplicate_update_item_ids: set[int]


@dataclass
class ValidationContext:
    comparison_df: pd.DataFrame
    option_check_df: pd.DataFrame
    converted_upload_df: pd.DataFrame
    payload_df: pd.DataFrame
    issue_df: pd.DataFrame
    has_blocking_issues: bool
    summary_stats: dict[str, int]


@dataclass
class BatchUploadJob:
    file_path: str
    file_label: str
    root_item_specs: list[RootItemUploadSpec]
    ready_count: int
    insert_ready_count: int
    update_ready_count: int
    output_dir: str
    wizard: CodebeamerUploadWizard


@dataclass
class RootItemUploadSpec:
    key: str
    name: str
    field_values: dict[str, Any]
    row_ids: list[int]
    parent_key: str | None = None
    kind: str = "group_root"


@dataclass
class FailedUploadRetryJob:
    """현재 GUI 세션에서 다시 실행할 수 있는 실패 행과 준비 상태다."""

    file_path: str
    file_label: str
    root_item_specs: list[RootItemUploadSpec]
    output_dir: str
    wizard: CodebeamerUploadWizard
    upload_mode: str
    retry_row_ids: set[int]
    retry_root_keys: set[str]
    created_row_item_ids: dict[int, Any]
    created_parent_item_ids_by_key: dict[str, Any]
    update_payload_prepared: bool = True

    @property
    def retry_target_count(self) -> int:
        return len(self.retry_row_ids) + len(self.retry_root_keys)


@dataclass
class FailedUploadRetryContext:
    """원본 파일을 다시 고르지 않고 실패 항목만 재시도하는 세션 캐시다."""

    jobs: list[FailedUploadRetryJob]
    success_df: pd.DataFrame
    failed_df: pd.DataFrame
    unresolved_df: pd.DataFrame
    created_map_by_file: dict[str, dict[Any, Any]]
    dry_run: bool
    non_retryable_count: int = 0

    @property
    def retry_target_count(self) -> int:
        return sum(job.retry_target_count for job in self.jobs)


@dataclass
class RootFieldCandidate:
    schema_field: str
    field_type: str
    mandatory: bool
    supported: bool
    fixed_value_kind: str
    fixed_options: list[str]
    allows_file_source: bool
    allows_fixed_value: bool
    allows_custom_value: bool


@dataclass
class RootSourceOption:
    key: str
    label: str


@dataclass
class RootItemPreviewContext:
    enabled: bool
    group_enabled: bool
    root_mode: str
    group_by_column: str
    group_column_options: list[str]
    regex_pattern: str
    regex_target: str
    field_assignments: dict[str, dict[str, Any]]
    field_sources: dict[str, str]
    field_candidates: list[RootFieldCandidate]
    source_options: list[RootSourceOption]
    preview_columns: list[str]
    preview_rows: list[dict[str, str]]
    regex_error: str | None
    status_message: str
    has_blocking_issues: bool
