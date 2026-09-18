from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.diagnostics import sanitize_diagnostic_text

from .tracker_query_models import TrackerQuery
from .tracker_query_models import mask_sensitive_payload


_CACHE_ATTRIBUTES = {
    "tracker_item_lookup": "tracker_item_lookup_cache",
    "user_lookup": "user_lookup_cache",
    "member_lookup": "member_lookup_cache",
    "group_lookup": "group_lookup_cache",
    "tracker_role": "tracker_role_cache",
    "existing_item": "existing_item_cache",
}
_SCHEMA_COMPARE_COLUMNS = (
    "field_name",
    "field_label",
    "field_type",
    "tracker_item_field",
    "raw_tracker_item_field",
    "mandatory",
    "mandatory_mode",
    "mandatory_statuses",
    "mandatory_status_names",
    "multiple_values",
    "value_model",
    "member_types",
    "has_options",
    "is_table_field",
    "is_option_like",
    "option_source_kind",
    "is_supported",
    "unsupported_reason",
    "resolved_field_kind",
    "reference_type",
    "payload_target_kind",
    "resolution_strategy",
    "requires_lookup",
    "lookup_target_kind",
    "preconstruction_kind",
    "preconstruction_detail",
    "options",
    "table_columns",
)


@dataclass(frozen=True)
class PayloadInspectionResult:
    row_id: str
    status: str
    operation: str
    target_item_id: str
    payload: Any
    pretty_json: str
    error: str


@dataclass(frozen=True)
class CacheEntryStats:
    key: str
    label: str
    entry_count: int


@dataclass(frozen=True)
class SchemaDifference:
    change: str
    identity: str
    field_name: str
    changed_properties: tuple[str, ...]
    before: dict[str, Any] | None
    after: dict[str, Any] | None


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    if isinstance(value, set):
        return sorted((_plain(child) for child in value), key=lambda child: str(child))
    if isinstance(value, pd.Series):
        return _plain(value.to_dict())
    if hasattr(value, "to_dict") and not isinstance(value, type):
        try:
            return _plain(value.to_dict())
        except Exception:
            pass
    try:
        missing = pd.isna(value)
    except Exception:
        missing = False
    try:
        if not hasattr(missing, "__len__") and bool(missing):
            return None
    except Exception:
        pass
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _plain(value.item())
        except Exception:
            pass
    return value


def _row_text(row: pd.Series, *columns: str) -> str:
    for column in columns:
        value = _plain(row.get(column))
        if value not in (None, ""):
            return str(value)
    return ""


def _payload_value(row: pd.Series) -> Any:
    for column in ("payload", "payload_json"):
        value = row.get(column)
        if value is None:
            continue
        try:
            if bool(pd.isna(value)):
                continue
        except Exception:
            pass
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
        return value
    return None


def _schema_identity(row: pd.Series, fallback_index: int) -> str:
    field_id = _plain(row.get("field_id"))
    if field_id not in (None, ""):
        return f"id:{field_id}"
    field_name = str(_plain(row.get("field_name")) or "").strip()
    if field_name:
        return f"name:{field_name.casefold()}"
    return f"row:{fallback_index}"


def _schema_record(row: pd.Series) -> dict[str, Any]:
    return {column: _plain(row.get(column)) for column in _SCHEMA_COMPARE_COLUMNS}


def inspect_payload_row(
    payload_df: pd.DataFrame,
    row_id: Any,
    *,
    source_file_path: str | None = None,
    source_file: str | None = None,
) -> PayloadInspectionResult:
    if not isinstance(payload_df, pd.DataFrame) or payload_df.empty:
        raise ValueError("검증된 payload 데이터가 없습니다. 먼저 검증을 실행하세요.")
    if "_row_id" not in payload_df.columns:
        raise ValueError("payload 데이터에 행 식별자가 없습니다.")

    normalized = str(row_id).strip()
    matches = payload_df[payload_df["_row_id"].map(lambda value: str(_plain(value))).eq(normalized)]
    normalized_path = str(source_file_path or "").strip()
    normalized_file = str(source_file or "").strip()
    if normalized_path and "source_file_path" in matches.columns:
        matches = matches[
            matches["source_file_path"].fillna("").astype(str).eq(normalized_path)
        ]
    elif normalized_file and "source_file" in matches.columns:
        matches = matches[
            matches["source_file"].fillna("").astype(str).eq(normalized_file)
        ]
    if matches.empty:
        raise ValueError(f"payload 행을 찾을 수 없습니다: {normalized}")
    if len(matches.index) > 1:
        raise ValueError(
            "여러 파일에 같은 행 번호가 있습니다. 파일과 행을 함께 선택하세요."
        )
    row = matches.iloc[0]
    masked_payload = mask_sensitive_payload(_plain(_payload_value(row)))
    pretty_json = json.dumps(masked_payload, ensure_ascii=False, indent=2, default=str)
    return PayloadInspectionResult(
        row_id=normalized,
        status=_row_text(row, "payload_status", "status"),
        operation=_row_text(row, "_operation", "operation"),
        target_item_id=_row_text(row, "_target_item_id", "target_item_id"),
        payload=deepcopy(masked_payload),
        pretty_json=pretty_json,
        error=sanitize_diagnostic_text(
            _row_text(row, "payload_error", "error"),
            limit=500,
        ),
    )


def diff_schema_frames(
    before_df: pd.DataFrame | None,
    after_df: pd.DataFrame | None,
) -> tuple[SchemaDifference, ...]:
    before = before_df if isinstance(before_df, pd.DataFrame) else pd.DataFrame()
    after = after_df if isinstance(after_df, pd.DataFrame) else pd.DataFrame()

    def records(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for index, (_, row) in enumerate(frame.iterrows()):
            identity = _schema_identity(row, index)
            if identity in result:
                identity = f"{identity}#{index}"
            result[identity] = _schema_record(row)
        return result

    before_records = records(before)
    after_records = records(after)
    differences: list[SchemaDifference] = []
    for identity in sorted(set(before_records) | set(after_records)):
        old = before_records.get(identity)
        new = after_records.get(identity)
        if old is None:
            differences.append(
                SchemaDifference(
                    change="추가",
                    identity=identity,
                    field_name=str((new or {}).get("field_name") or ""),
                    changed_properties=(),
                    before=None,
                    after=deepcopy(new),
                )
            )
            continue
        if new is None:
            differences.append(
                SchemaDifference(
                    change="삭제",
                    identity=identity,
                    field_name=str(old.get("field_name") or ""),
                    changed_properties=(),
                    before=deepcopy(old),
                    after=None,
                )
            )
            continue
        changed = tuple(
            column
            for column in _SCHEMA_COMPARE_COLUMNS
            if old.get(column) != new.get(column)
        )
        if changed:
            differences.append(
                SchemaDifference(
                    change="변경",
                    identity=identity,
                    field_name=str(new.get("field_name") or old.get("field_name") or ""),
                    changed_properties=changed,
                    before=deepcopy(old),
                    after=deepcopy(new),
                )
            )
    return tuple(differences)


def cache_entry_stats(context: Any) -> tuple[CacheEntryStats, ...]:
    labels = {
        "tracker_item_lookup": "Tracker Item 조회",
        "user_lookup": "사용자 조회",
        "member_lookup": "멤버 조회",
        "group_lookup": "그룹 조회",
        "tracker_role": "트래커 역할 조회",
        "existing_item": "기존 아이템",
    }
    result: list[CacheEntryStats] = []
    for key, attribute in _CACHE_ATTRIBUTES.items():
        cache = getattr(context, attribute, None)
        count = len(cache) if isinstance(cache, (dict, list, tuple, set)) else 0
        result.append(CacheEntryStats(key=key, label=labels[key], entry_count=count))
    return tuple(result)


def clear_context_caches(context: Any, cache_keys: list[str] | tuple[str, ...]) -> int:
    invalid = sorted(set(cache_keys) - set(_CACHE_ATTRIBUTES))
    if invalid:
        raise ValueError(f"지원하지 않는 캐시입니다: {', '.join(invalid)}")
    removed = 0
    for key in dict.fromkeys(cache_keys):
        cache = getattr(context, _CACHE_ATTRIBUTES[key], None)
        if not hasattr(cache, "clear"):
            continue
        removed += len(cache)
        cache.clear()
    return removed


def build_read_only_query_preview(query: TrackerQuery) -> dict[str, Any]:
    """실행 전에 읽기 전용 TrackerQuery가 만들 요청을 안전하게 보여준다."""
    if not isinstance(query, TrackerQuery):
        raise TypeError("TrackerQuery만 미리 볼 수 있습니다.")
    query_params: dict[str, Any] = {
        "queryString": query.build_cbql(),
        "page": query.page,
        "pageSize": query.page_size,
    }
    if query.baseline_id is not None:
        query_params["baselineId"] = query.baseline_id
    return {
        "method": "GET",
        "path": "/v3/items/query",
        "read_only": True,
        "tracker_id": query.tracker_id,
        "baseline_id": query.baseline_id,
        "page": query.page,
        "page_size": query.page_size,
        "cbql": query.build_cbql(),
        "query_params": query_params,
    }


__all__ = [
    "CacheEntryStats",
    "PayloadInspectionResult",
    "SchemaDifference",
    "build_read_only_query_preview",
    "cache_entry_stats",
    "clear_context_caches",
    "diff_schema_frames",
    "inspect_payload_row",
]
