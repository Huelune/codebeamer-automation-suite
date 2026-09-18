from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

import pandas as pd


if TYPE_CHECKING:
    # upload_policy 가 models 를 import 하므로 런타임 import 는 순환이 된다.
    from src.upload_policy import OperationScope


@dataclass
class WizardState:
    project_id: int | None = None
    tracker_id: int | None = None
    upload_mode: str = "create"

    raw_df: pd.DataFrame | None = None
    merged_df: pd.DataFrame | None = None
    hierarchy_df: pd.DataFrame | None = None
    upload_df: pd.DataFrame | None = None
    converted_upload_df: pd.DataFrame | None = None
    payload_df: pd.DataFrame | None = None

    # Codebeamer 는 tracker schema 를 dict 또는 field dict 목록으로 돌려준다.
    schema: dict[str, Any] | list[dict[str, Any]] | None = None
    schema_df: pd.DataFrame | None = None
    comparison_df: pd.DataFrame | None = None
    option_candidates_df: pd.DataFrame | None = None
    option_maps: dict[str, Any] | None = None
    option_check_df: pd.DataFrame | None = None

    selected_mapping: dict[str, str] = field(default_factory=dict)
    selected_mapping_modes: dict[str, OperationScope] = field(default_factory=dict)
    selected_option_mapping: dict[str, str] = field(default_factory=dict)
    selected_default_values: dict[str, Any] = field(default_factory=dict)
    selected_default_value_modes: dict[str, OperationScope] = field(default_factory=dict)
    selected_tracker_item_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    resolved_default_values: dict[str, Any] = field(default_factory=dict)
    table_field_mapping: dict[str, dict[str, Any]] = field(default_factory=dict)
    list_cols: list[str] = field(default_factory=list)
    user_lookup_cache: dict[tuple[int | None, str], tuple[Any, Any, str, str | None]] = field(default_factory=dict)
    member_lookup_cache: dict[tuple[int | None, int | None, int | None, str], tuple[Any, Any, str, str | None]] = field(
        default_factory=dict
    )
    group_lookup_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    tracker_role_cache: dict[tuple[int, int, int], dict[str, list[dict[str, Any]]]] = field(default_factory=dict)
    tracker_item_lookup_cache: dict[tuple[str, str], tuple[Any, str | None, str | None]] = field(default_factory=dict)
    existing_item_cache: dict[int, dict[str, Any]] = field(default_factory=dict)

    upload_result: dict[str, Any] | None = None
