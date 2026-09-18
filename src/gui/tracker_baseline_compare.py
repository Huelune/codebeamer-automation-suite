from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .tracker_query_models import TrackerItemSummary
from .tracker_query_models import mask_sensitive_payload


class BaselineComparisonKind(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class TrackerBaseline:
    baseline_id: int
    name: str
    created_at: str = ""

    @classmethod
    def from_raw(cls, value: dict[str, Any]) -> TrackerBaseline:
        baseline_id = int(value.get("id") or 0)
        if baseline_id <= 0:
            raise ValueError("Baseline ID가 올바르지 않습니다.")
        return cls(
            baseline_id=baseline_id,
            name=str(value.get("name") or value.get("label") or baseline_id),
            created_at=str(value.get("createdAt") or ""),
        )


@dataclass(frozen=True)
class BaselineComparisonSource:
    baseline_id: int | None = None

    @property
    def is_head(self) -> bool:
        return self.baseline_id is None

    @property
    def label(self) -> str:
        return "현재 상태" if self.is_head else f"Baseline #{self.baseline_id}"


@dataclass(frozen=True)
class TrackerFieldDifference:
    field_key: str
    label: str
    before: Any
    after: Any
    is_changed: bool
    is_table: bool = False
    table_columns: tuple[TrackerTableColumn, ...] = ()

    def before_text(self) -> str:
        if self.is_table:
            return _display_table(self.before, self.table_columns)
        return _display_value(self.before, field_key=self.field_key)

    def after_text(self) -> str:
        if self.is_table:
            return _display_table(self.after, self.table_columns)
        return _display_value(self.after, field_key=self.field_key)

    @property
    def reference(self) -> Any:
        """사용자가 선택한 기준 값. 내부 비교 모델의 after에 대응한다."""
        return self.after

    @property
    def comparison(self) -> Any:
        """사용자가 선택한 비교 값. 내부 비교 모델의 before에 대응한다."""
        return self.before

    def reference_text(self) -> str:
        return self.after_text()

    def comparison_text(self) -> str:
        return self.before_text()


@dataclass(frozen=True)
class TrackerTableColumn:
    column_key: str
    label: str


@dataclass(frozen=True)
class TrackerItemFieldValue:
    """조회 item 한 건에서 Excel에 표시할 수 있도록 정규화한 필드 값이다."""

    field_key: str
    label: str
    value: Any
    is_table: bool = False
    table_columns: tuple[TrackerTableColumn, ...] = ()

    def display_text(self) -> str:
        if self.is_table:
            return _display_table(self.value, self.table_columns)
        return _display_value(self.value, field_key=self.field_key)


@dataclass(frozen=True)
class TrackerItemComparison:
    item_id: int
    kind: BaselineComparisonKind
    before: TrackerItemSummary | None
    after: TrackerItemSummary | None
    fields: tuple[TrackerFieldDifference, ...] = ()

    @property
    def name(self) -> str:
        item = self.after or self.before
        return item.name if item is not None else str(self.item_id)

    @property
    def reference(self) -> TrackerItemSummary | None:
        return self.after

    @property
    def comparison(self) -> TrackerItemSummary | None:
        return self.before


@dataclass(frozen=True)
class BaselineComparisonResult:
    before_source: BaselineComparisonSource
    after_source: BaselineComparisonSource
    items: tuple[TrackerItemComparison, ...]

    def count(self, kind: BaselineComparisonKind) -> int:
        return sum(item.kind == kind for item in self.items)

    @property
    def reference_source(self) -> BaselineComparisonSource:
        return self.after_source

    @property
    def comparison_source(self) -> BaselineComparisonSource:
        return self.before_source


def tracker_item_fields(
    item: TrackerItemSummary,
    *,
    tracker_schema: dict[str, Any] | None = None,
) -> tuple[TrackerItemFieldValue, ...]:
    """단일 조회 item의 builtin/custom/TableField 값을 공통 표시 모델로 바꾼다."""
    schema_fields = _schema_fields(tracker_schema)
    normalized = _comparison_fields(item.raw_reference, schema_fields=schema_fields)
    return tuple(
        TrackerItemFieldValue(
            field_key=field_key,
            label=label,
            value=value,
            is_table=is_table,
            table_columns=table_columns,
        )
        for field_key, (label, _canonical_value, value, is_table, table_columns)
        in normalized.items()
    )


def compare_tracker_items(
    before_items: tuple[TrackerItemSummary, ...],
    after_items: tuple[TrackerItemSummary, ...],
    *,
    before_source: BaselineComparisonSource,
    after_source: BaselineComparisonSource,
    tracker_schema: dict[str, Any] | None = None,
) -> BaselineComparisonResult:
    if before_source == after_source:
        raise ValueError("서로 다른 두 비교 기준을 선택하세요.")
    before_by_id = {item.item_id: item for item in before_items}
    after_by_id = {item.item_id: item for item in after_items}
    comparisons: list[TrackerItemComparison] = []
    for item_id in sorted(before_by_id.keys() | after_by_id.keys()):
        before = before_by_id.get(item_id)
        after = after_by_id.get(item_id)
        if before is None:
            fields = _field_comparisons(
                {},
                after.raw_reference if after is not None else {},
                tracker_schema=tracker_schema,
            )
            comparisons.append(
                TrackerItemComparison(
                    item_id,
                    BaselineComparisonKind.ADDED,
                    None,
                    after,
                    fields,
                )
            )
            continue
        if after is None:
            fields = _field_comparisons(
                before.raw_reference,
                {},
                tracker_schema=tracker_schema,
            )
            comparisons.append(
                TrackerItemComparison(
                    item_id,
                    BaselineComparisonKind.REMOVED,
                    before,
                    None,
                    fields,
                )
            )
            continue
        fields = _field_comparisons(
            before.raw_reference,
            after.raw_reference,
            tracker_schema=tracker_schema,
        )
        kind = (
            BaselineComparisonKind.CHANGED
            if any(field.is_changed for field in fields)
            else BaselineComparisonKind.UNCHANGED
        )
        comparisons.append(TrackerItemComparison(item_id, kind, before, after, fields))
    return BaselineComparisonResult(before_source, after_source, tuple(comparisons))


def _field_comparisons(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    tracker_schema: dict[str, Any] | None = None,
) -> tuple[TrackerFieldDifference, ...]:
    schema_fields = _schema_fields(tracker_schema)
    before_fields = _comparison_fields(before, schema_fields=schema_fields)
    after_fields = _comparison_fields(after, schema_fields=schema_fields)
    comparisons: list[TrackerFieldDifference] = []
    missing = object()
    for key in dict.fromkeys((*after_fields, *before_fields)):
        before_entry = before_fields.get(key)
        after_entry = after_fields.get(key)
        before_label, before_compare, before_value, before_table, before_columns = (
            before_entry
            if before_entry is not None
            else ("", missing, None, False, ())
        )
        after_label, after_compare, after_value, after_table, after_columns = (
            after_entry
            if after_entry is not None
            else ("", missing, None, False, ())
        )
        table_columns = _merge_table_columns(after_columns, before_columns)
        comparisons.append(
            TrackerFieldDifference(
                key,
                _preferred_field_label(key, after_label, before_label),
                before_value,
                after_value,
                before_compare != after_compare,
                before_table or after_table,
                table_columns,
            )
        )
    return tuple(comparisons)


def _preferred_field_label(key: str, *labels: str) -> str:
    fallback_prefix = "사용자 정의 필드 #"
    for label in labels:
        if label and not label.startswith(fallback_prefix):
            return label
    return next((label for label in labels if label), key)


_FIELD_LABELS = {
    "id": "ID",
    "name": "요약",
    "summary": "요약 (summary)",
    "description": "설명",
    "descriptionFormat": "설명 형식",
    "type": "유형",
    "tracker": "트래커",
    "project": "프로젝트",
    "status": "상태",
    "assignedTo": "담당자",
    "assignees": "담당자 (assignees)",
    "parent": "상위 아이템",
    "children": "하위 아이템",
    "childCount": "하위 아이템 수",
    "hasChildren": "하위 아이템 여부",
    "createdAt": "생성 시각",
    "createdBy": "생성자",
    "modifiedAt": "수정 시각",
    "modifiedBy": "수정자",
    "version": "버전",
}

_FIELD_ORDER = tuple(_FIELD_LABELS)


def _comparison_fields(
    raw: dict[str, Any],
    *,
    schema_fields: dict[str, dict[str, Any]] | None = None,
) -> dict[str, tuple[str, Any, Any, bool, tuple[TrackerTableColumn, ...]]]:
    if not isinstance(raw, dict):
        return {}

    def normalize_field(
        label: str,
        value: Any,
        *,
        raw_field: dict[str, Any] | None = None,
        schema_field: dict[str, Any] | None = None,
    ) -> tuple[str, Any, Any, bool, tuple[TrackerTableColumn, ...]]:
        field_payload = raw_field or {}
        schema_payload = schema_field or {}
        type_name = " ".join(
            str(schema_payload.get(key) or field_payload.get(key) or "")
            for key in ("type", "valueModel")
        ).casefold()
        is_table = "tablefield" in type_name
        columns = (
            _merge_table_columns(
                _table_columns(schema_payload, value),
                _table_columns(field_payload, value),
            )
            if is_table
            else ()
        )
        return label, _canonical(value), value, is_table, columns

    safe_raw = mask_sensitive_payload(raw)
    fields: dict[
        str,
        tuple[str, Any, Any, bool, tuple[TrackerTableColumn, ...]],
    ] = {}
    ordered_keys = (
        *(key for key in _FIELD_ORDER if key in safe_raw),
        *(key for key in safe_raw if key not in _FIELD_LABELS and key != "customFields"),
    )
    for key in ordered_keys:
        schema_field = (schema_fields or {}).get(key)
        schema_label = str((schema_field or {}).get("name") or "").strip()
        fields[key] = normalize_field(
            schema_label or _FIELD_LABELS.get(key, key),
            safe_raw[key],
            schema_field=schema_field,
        )

    custom_fields = safe_raw.get("customFields")
    if isinstance(custom_fields, list):
        for field in custom_fields:
            if not isinstance(field, dict):
                continue
            field_id = field.get("fieldId") if field.get("fieldId") is not None else field.get("id")
            name = str(field.get("name") or "").strip()
            key = f"custom:{field_id if field_id is not None else name}"
            schema_field = (schema_fields or {}).get(key)
            schema_name = str((schema_field or {}).get("name") or "").strip()
            fallback_label = (
                f"사용자 정의 필드 #{field_id}"
                if field_id is not None
                else "사용자 정의 필드"
            )
            value = field.get("values") if "values" in field else field.get("value")
            fields[key] = normalize_field(
                schema_name or name or fallback_label,
                value,
                raw_field=field,
                schema_field=schema_field,
            )
    elif "customFields" in safe_raw:
        fields["customFields"] = normalize_field("사용자 정의 필드", custom_fields)
    return fields


def _schema_fields(
    tracker_schema: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(tracker_schema, dict):
        return {}
    raw_fields = tracker_schema.get("fields")
    if not isinstance(raw_fields, list):
        return {}
    fields: dict[str, dict[str, Any]] = {}
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            continue
        field = dict(raw_field)
        builtin_key = str(field.get("trackerItemField") or "").strip()
        if builtin_key:
            fields[builtin_key] = field
        field_id = _optional_column_id(field)
        if field_id is not None:
            fields[f"custom:{field_id}"] = field
    return fields


def _optional_column_id(value: dict[str, Any]) -> int | None:
    raw_id = value.get("fieldId")
    if raw_id is None:
        raw_id = value.get("id")
    if raw_id is None or isinstance(raw_id, bool):
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _table_column(value: Any, index: int) -> TrackerTableColumn:
    if isinstance(value, dict):
        field_id = _optional_column_id(value)
        if field_id is not None:
            key = f"id:{field_id}"
        else:
            name = str(value.get("name") or value.get("label") or "").strip()
            key = f"name:{name.casefold()}" if name else f"index:{index}"
        label = str(
            value.get("name")
            or value.get("label")
            or (f"열 {index + 1}")
        )
        return TrackerTableColumn(key, label)
    return TrackerTableColumn(f"index:{index}", f"열 {index + 1}")


def _table_row_values(value: Any) -> list[Any] | dict[str, Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        nested = value.get("values")
        if isinstance(nested, list):
            return nested
        return value
    return []


def _raw_table_rows(value: Any) -> list[Any]:
    if isinstance(value, dict) and isinstance(value.get("values"), list):
        value = value.get("values")
    if not isinstance(value, (list, tuple)):
        return []
    return list(value)


def _table_columns(
    raw_field: dict[str, Any],
    value: Any,
) -> tuple[TrackerTableColumn, ...]:
    columns: list[TrackerTableColumn] = []
    seen: set[str] = set()

    def add(candidate: Any, index: int) -> None:
        column = _table_column(candidate, index)
        if column.column_key in seen:
            return
        seen.add(column.column_key)
        columns.append(column)

    schema_columns = raw_field.get("columns")
    if isinstance(schema_columns, list):
        for index, candidate in enumerate(schema_columns):
            add(candidate, index)
    for raw_row in _raw_table_rows(value):
        row = _table_row_values(raw_row)
        if isinstance(row, dict):
            for index, (name, cell_value) in enumerate(row.items()):
                candidate = cell_value if isinstance(cell_value, dict) else {"name": name}
                add(candidate, index)
            continue
        for index, candidate in enumerate(row):
            add(candidate, index)
    return tuple(columns)


def _merge_table_columns(
    *groups: tuple[TrackerTableColumn, ...],
) -> tuple[TrackerTableColumn, ...]:
    columns: list[TrackerTableColumn] = []
    seen: set[str] = set()
    for group in groups:
        for column in group:
            if column.column_key in seen:
                continue
            seen.add(column.column_key)
            columns.append(column)
    return tuple(columns)


def _table_cell_value(cell: Any) -> Any:
    if not isinstance(cell, dict):
        return cell
    if "value" in cell:
        return cell.get("value")
    if "values" in cell:
        return cell.get("values")
    return cell


def table_field_rows(value: Any) -> tuple[dict[str, Any], ...]:
    """TableField 값을 열 식별자 기반 행 목록으로 정규화한다."""
    rows: list[dict[str, Any]] = []
    for raw_row in _raw_table_rows(value):
        row_payload = _table_row_values(raw_row)
        normalized: dict[str, Any] = {}
        if isinstance(row_payload, dict):
            for index, (name, cell) in enumerate(row_payload.items()):
                candidate = cell if isinstance(cell, dict) else {"name": name}
                column = _table_column(candidate, index)
                normalized[column.column_key] = _table_cell_value(cell)
        else:
            for index, cell in enumerate(row_payload):
                column = _table_column(cell, index)
                normalized[column.column_key] = _table_cell_value(cell)
        rows.append(normalized)
    return tuple(rows)


def comparison_value_key(value: Any) -> Any:
    """표시명 변경을 제외한 비교용 canonical 값을 반환한다."""
    return _canonical(value)


def display_tracker_value(value: Any, *, field_key: str = "") -> str:
    """조회·비교 Excel에서 공유하는 사용자 친화적 필드 표시 문자열을 반환한다."""
    return _display_value(value, field_key=field_key)


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        reference_keys = {"id", "name", "summary", "type"}
        if value.get("id") is not None and (
            value.get("type") or set(value).issubset(reference_keys)
        ):
            identity = {"id": value.get("id")}
            if value.get("type"):
                identity["type"] = value.get("type")
            return identity
        return {
            str(key): _canonical(nested)
            for key, nested in sorted(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


_NESTED_LABELS = {
    "id": "ID",
    "name": "이름",
    "summary": "요약",
    "label": "이름",
    "type": "유형",
    "project": "프로젝트",
    "tracker": "트래커",
    "status": "상태",
    "value": "값",
    "values": "값",
}

_DESCRIPTION_FORMAT_LABELS = {
    "plaintext": "일반 텍스트",
    "wiki": "Wiki 텍스트",
    "wikitext": "Wiki 텍스트",
    "html": "HTML",
}

_ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def _display_value(value: Any, *, field_key: str = "") -> str:
    if value is None or value == "" or value == [] or value == {}:
        return "-"
    if field_key == "descriptionFormat" and isinstance(value, str):
        return _DESCRIPTION_FORMAT_LABELS.get(value.casefold(), value)
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, dict):
        return _display_mapping(value)
    if isinstance(value, (list, tuple)):
        return _display_list(value)
    if isinstance(value, str) and _ISO_TIMESTAMP.fullmatch(value):
        readable = value.replace("T", " ", 1)
        return f"{readable[:-1]} UTC" if readable.endswith("Z") else readable
    return str(value)


def _display_mapping(value: dict[str, Any]) -> str:
    display_name = value.get("name") or value.get("summary") or value.get("label")
    reference_id = value.get("id")
    reference_keys = {"id", "name", "summary", "label", "type"}
    lines: list[str] = []
    if display_name not in (None, "") or reference_id not in (None, ""):
        if display_name not in (None, "") and reference_id not in (None, ""):
            lines.append(
                str(display_name)
                if str(display_name) == str(reference_id)
                else f"{display_name} (ID {reference_id})"
            )
        elif display_name not in (None, ""):
            lines.append(str(display_name))
        else:
            lines.append(f"ID {reference_id}")
    for key, nested in value.items():
        if key in reference_keys and lines:
            continue
        label = _NESTED_LABELS.get(str(key), str(key))
        nested_text = _display_value(nested)
        lines.extend(_labeled_lines(label, nested_text))
    return "\n".join(lines) if lines else "-"


def _display_list(value: list[Any] | tuple[Any, ...]) -> str:
    if not value:
        return "-"
    if all(isinstance(row, (list, tuple)) for row in value):
        rows: list[str] = []
        for index, row in enumerate(value, start=1):
            cells = [_display_value(cell).replace("\n", " / ") for cell in row]
            rows.append(f"행 {index}: {' | '.join(cells)}")
        return "\n".join(rows)
    lines: list[str] = []
    for item in value:
        item_text = _display_value(item)
        item_lines = item_text.splitlines() or ["-"]
        lines.append(f"• {item_lines[0]}")
        lines.extend(f"  {line}" for line in item_lines[1:])
    return "\n".join(lines)


def _display_table(
    value: Any,
    columns: tuple[TrackerTableColumn, ...],
) -> str:
    rows = table_field_rows(value)
    if not rows:
        return "-"
    effective_columns = columns
    if not effective_columns:
        discovered: list[TrackerTableColumn] = []
        seen: set[str] = set()
        for row in rows:
            for index, key in enumerate(row):
                if key in seen:
                    continue
                seen.add(key)
                discovered.append(TrackerTableColumn(key, f"열 {index + 1}"))
        effective_columns = tuple(discovered)
    rendered: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column in effective_columns:
            cell_text = _display_value(row.get(column.column_key)).replace("\n", " / ")
            cells.append(f"{column.label}={cell_text}")
        rendered.append(f"행 {row_index}: {' | '.join(cells)}")
    return "\n".join(rendered)


def _labeled_lines(label: str, value: str) -> list[str]:
    lines = value.splitlines() or ["-"]
    if len(lines) == 1:
        return [f"{label}: {lines[0]}"]
    return [f"{label}:", *(f"  {line}" for line in lines)]


__all__ = [
    "BaselineComparisonKind",
    "BaselineComparisonResult",
    "BaselineComparisonSource",
    "TrackerBaseline",
    "TrackerFieldDifference",
    "TrackerItemComparison",
    "TrackerTableColumn",
    "compare_tracker_items",
    "comparison_value_key",
    "table_field_rows",
]
