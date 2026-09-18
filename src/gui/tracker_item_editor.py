from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from enum import Enum
from typing import Any

from src.codebeamer_client import CodebeamerClient
from src.models.common import CONNECTED_FIELD_TYPE_VALUE_MODEL_MAP

from .service_core import _build_gui_client
from .tracker_query_models import TrackerItemDetail
from .tracker_query_service import TrackerQueryService


class FieldEditorKind(str, Enum):
    TEXT = "text"
    MULTILINE_TEXT = "multiline_text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    CHOICE = "choice"
    REFERENCE = "reference"
    TABLE = "table"
    STATUS = "status"
    UNSUPPORTED = "unsupported"


class TrackerItemWriteErrorKind(str, Enum):
    WRITE_DISABLED = "write_disabled"
    CONFLICT = "conflict"
    INVALID_VALUE = "invalid_value"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    SERVER = "server"
    UNKNOWN = "unknown"


class TrackerItemWriteError(RuntimeError):
    def __init__(
        self,
        kind: TrackerItemWriteErrorKind,
        message: str,
        *,
        status_code: int | None = None,
        operation: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = TrackerItemWriteErrorKind(kind)
        self.status_code = status_code
        self.operation = str(operation or "")


@dataclass(frozen=True)
class EditableFieldOption:
    option_id: int
    name: str
    type_name: str = "ChoiceOptionReference"
    raw_reference: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_raw(cls, value: dict[str, Any]) -> EditableFieldOption | None:
        if not isinstance(value, dict):
            return None
        try:
            option_id = int(value.get("id"))
        except (TypeError, ValueError):
            return None
        return cls(
            option_id=option_id,
            name=str(value.get("name") or value.get("label") or option_id),
            type_name=str(value.get("type") or "ChoiceOptionReference"),
            raw_reference=deepcopy(value),
        )


@dataclass(frozen=True)
class EditableTrackerField:
    field_id: int
    name: str
    label: str
    type_name: str
    value_model: str
    tracker_item_field: str = ""
    reference_type: str = ""
    multiple_values: bool = False
    mandatory: bool = False
    editor_kind: FieldEditorKind = FieldEditorKind.UNSUPPORTED
    options: tuple[EditableFieldOption, ...] = field(default_factory=tuple)
    table_columns: tuple[EditableTrackerField, ...] = field(default_factory=tuple)
    current_value: Any = field(default=None, compare=False)
    unsupported_reason: str = ""
    raw_schema: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def editable(self) -> bool:
        return (
            self.editor_kind not in {FieldEditorKind.UNSUPPORTED, FieldEditorKind.STATUS}
            and not self.unsupported_reason
        )

    @property
    def is_status(self) -> bool:
        return self.editor_kind == FieldEditorKind.STATUS

    @property
    def current_display_value(self) -> str:
        if self.editor_kind == FieldEditorKind.TABLE:
            row_count = (
                len(self.current_value)
                if isinstance(self.current_value, list)
                else 0
            )
            return f"{row_count}행 × {len(self.table_columns)}열"
        return _display_value(self.current_value)


@dataclass(frozen=True)
class EditableTrackerSchema:
    tracker_id: int
    fields: tuple[EditableTrackerField, ...]
    status_field: EditableTrackerField | None = None

    @property
    def editable_fields(self) -> tuple[EditableTrackerField, ...]:
        return tuple(field_value for field_value in self.fields if field_value.editable)


@dataclass(frozen=True)
class TrackerItemFieldChange:
    field: EditableTrackerField
    value: Any


_REFERENCE_MODEL_PATTERN = re.compile(r"<\s*([^>]+?)\s*>")


def _optional_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, dict):
        for key in ("name", "value", "id"):
            if value.get(key) not in (None, ""):
                return _display_value(value.get(key))
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(
            text for text in (_display_value(item) for item in value) if text
        )
    return str(value)


def _schema_field_payloads(schema: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = [schema.get("fields")]
    for container_name in ("itemSchema", "trackerItemSchema", "schema"):
        container = schema.get(container_name)
        if isinstance(container, dict):
            candidates.append(container.get("fields"))
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _inferred_tracker_item_field(name: str, explicit: str) -> str:
    if str(explicit or "").strip():
        return str(explicit).strip()
    normalized = str(name or "").strip().casefold().replace(" ", "")
    return {
        "summary": "name",
        "name": "name",
        "description": "description",
        "status": "status",
        "assignedto": "assignedTo",
        "assignee": "assignedTo",
    }.get(normalized, "")


def _field_current_value(
    detail: TrackerItemDetail,
    *,
    field_id: int,
    name: str,
    tracker_item_field: str,
) -> Any:
    if tracker_item_field:
        if tracker_item_field == "name":
            return detail.summary.name
        if tracker_item_field == "description":
            return detail.description
        if tracker_item_field in detail.raw_payload:
            return deepcopy(detail.raw_payload.get(tracker_item_field))

    for custom_field in detail.custom_fields:
        if custom_field.field_id == field_id or custom_field.name.casefold() == name.casefold():
            raw_value = custom_field.raw_value
            if isinstance(raw_value, dict):
                if "values" in raw_value:
                    return deepcopy(raw_value.get("values"))
                if "value" in raw_value:
                    return deepcopy(raw_value.get("value"))
            return custom_field.display_value

    normalized_name = name.strip().casefold()
    if normalized_name == "summary":
        return detail.summary.name
    if normalized_name == "description":
        return detail.description
    if normalized_name == "status":
        return deepcopy(detail.raw_payload.get("status")) or detail.summary.status
    return None


def _editor_kind(
    *,
    name: str,
    type_name: str,
    value_model: str,
    tracker_item_field: str,
    reference_type: str,
    options: tuple[EditableFieldOption, ...],
) -> tuple[FieldEditorKind, str]:
    lowered_type = type_name.casefold()
    lowered_model = value_model.casefold()
    if tracker_item_field == "status" or name.strip().casefold() == "status":
        if not options:
            return FieldEditorKind.UNSUPPORTED, "상태 option을 schema에서 확인할 수 없습니다."
        return FieldEditorKind.STATUS, ""
    if "table" in lowered_type or "tablefieldvalue" in lowered_model:
        return FieldEditorKind.TABLE, ""
    if "bool" in lowered_type or "boolfieldvalue" in lowered_model:
        return FieldEditorKind.BOOLEAN, ""
    if "integer" in lowered_type or "integerfieldvalue" in lowered_model:
        return FieldEditorKind.INTEGER, ""
    if any(token in lowered_type for token in ("decimal", "float", "number")) or any(
        token in lowered_model for token in ("decimalfieldvalue", "floatfieldvalue")
    ):
        return FieldEditorKind.DECIMAL, ""
    if "datetime" in lowered_type or "datetimefieldvalue" in lowered_model:
        return FieldEditorKind.DATETIME, ""
    if "date" in lowered_type or "datefieldvalue" in lowered_model:
        return FieldEditorKind.DATE, ""
    if options and ("choice" in lowered_type or "choicefieldvalue" in lowered_model):
        return FieldEditorKind.CHOICE, ""
    if "memberfield" in lowered_type and not reference_type:
        return (
            FieldEditorKind.UNSUPPORTED,
            "사용자·역할·그룹이 섞인 멤버 필드는 유형별 조회가 필요합니다.",
        )
    looks_like_reference = (
        "reference" in lowered_type
        or "trackeritemchoice" in lowered_type
        or (
            "choicefieldvalue" in lowered_model
            and "choiceoptionreference" not in lowered_model
        )
    )
    if looks_like_reference and not reference_type:
        return FieldEditorKind.UNSUPPORTED, "참조 대상 유형을 schema에서 확인할 수 없습니다."
    if reference_type:
        return FieldEditorKind.REFERENCE, ""
    if any(token in lowered_type for token in ("text", "wiki")) or any(
        token in lowered_model for token in ("textfieldvalue", "wikitextfieldvalue")
    ):
        if tracker_item_field == "description" or name.strip().casefold() == "description":
            return FieldEditorKind.MULTILINE_TEXT, ""
        return FieldEditorKind.TEXT, ""
    if options:
        return FieldEditorKind.CHOICE, ""
    return FieldEditorKind.UNSUPPORTED, "현재 편집기가 이 필드 형식을 지원하지 않습니다."


def _field_options(raw_field: dict[str, Any]) -> tuple[EditableFieldOption, ...]:
    return tuple(
        option
        for option in (
            EditableFieldOption.from_raw(raw_option)
            for raw_option in raw_field.get("options", [])
        )
        if option is not None
    )


def _schema_value_model(raw_field: dict[str, Any], type_name: str) -> str:
    explicit = str(raw_field.get("valueModel") or "").strip()
    if explicit:
        return explicit
    return CONNECTED_FIELD_TYPE_VALUE_MODEL_MAP.get(
        type_name,
        type_name or "FieldValue",
    )


def _table_column_fields(raw_field: dict[str, Any]) -> tuple[EditableTrackerField, ...]:
    columns: list[EditableTrackerField] = []
    raw_columns = raw_field.get("columns")
    if not isinstance(raw_columns, list):
        return ()
    for raw_column in raw_columns:
        if not isinstance(raw_column, dict) or bool(raw_column.get("hidden", False)):
            continue
        field_id = _optional_int(raw_column.get("id") or raw_column.get("fieldId"))
        if field_id is None or field_id <= 0:
            continue
        name = str(raw_column.get("name") or raw_column.get("label") or field_id)
        label = str(raw_column.get("label") or name)
        type_name = str(raw_column.get("type") or "")
        value_model = _schema_value_model(raw_column, type_name)
        reference_type = str(raw_column.get("referenceType") or "")
        if not reference_type:
            model_match = _REFERENCE_MODEL_PATTERN.search(value_model)
            if model_match is not None:
                candidate = model_match.group(1).strip()
                if candidate.casefold() != "choiceoptionreference":
                    reference_type = candidate
        options = _field_options(raw_column)
        editor_kind, unsupported_reason = _editor_kind(
            name=name,
            type_name=type_name,
            value_model=value_model,
            tracker_item_field="",
            reference_type=reference_type,
            options=options,
        )
        if "wiki" in type_name.casefold() or "wiki" in value_model.casefold():
            editor_kind = FieldEditorKind.MULTILINE_TEXT
            unsupported_reason = ""
        if editor_kind == FieldEditorKind.TABLE:
            editor_kind = FieldEditorKind.UNSUPPORTED
            unsupported_reason = "중첩 TableField 열은 편집하지 않습니다."
        if editor_kind == FieldEditorKind.REFERENCE:
            editor_kind = FieldEditorKind.UNSUPPORTED
            unsupported_reason = "참조 열은 원본값을 보존하며 읽기 전용으로 표시합니다."
        if bool(raw_column.get("readOnly", False)) or raw_column.get("editable") is False:
            editor_kind = FieldEditorKind.UNSUPPORTED
            unsupported_reason = "읽기 전용 열입니다."
        columns.append(
            EditableTrackerField(
                field_id=field_id,
                name=name,
                label=label,
                type_name=type_name,
                value_model=value_model,
                reference_type=reference_type,
                multiple_values=bool(raw_column.get("multipleValues", False)),
                mandatory=bool(raw_column.get("mandatory", False)),
                editor_kind=editor_kind,
                options=options,
                unsupported_reason=unsupported_reason,
                raw_schema=deepcopy(raw_column),
            )
        )
    return tuple(columns)


def _build_tracker_schema(
    schema: dict[str, Any],
    *,
    tracker_id: int,
    detail: TrackerItemDetail | None,
) -> EditableTrackerSchema:
    normalized_fields: list[EditableTrackerField] = []
    status_field: EditableTrackerField | None = None
    for raw_field in _schema_field_payloads(schema):
        field_id = _optional_int(raw_field.get("id") or raw_field.get("fieldId"))
        if field_id is None or field_id <= 0:
            continue
        if bool(raw_field.get("hidden", False)):
            continue
        name = str(raw_field.get("name") or raw_field.get("label") or field_id)
        label = str(raw_field.get("label") or name)
        type_name = str(raw_field.get("type") or "")
        value_model = _schema_value_model(raw_field, type_name)
        tracker_item_field = _inferred_tracker_item_field(
            name,
            str(raw_field.get("trackerItemField") or ""),
        )
        reference_type = str(raw_field.get("referenceType") or "")
        if not reference_type:
            model_match = _REFERENCE_MODEL_PATTERN.search(value_model)
            if model_match is not None:
                candidate = model_match.group(1).strip()
                if candidate.casefold() != "choiceoptionreference":
                    reference_type = candidate
        options = _field_options(raw_field)
        editor_kind, unsupported_reason = _editor_kind(
            name=name,
            type_name=type_name,
            value_model=value_model,
            tracker_item_field=tracker_item_field,
            reference_type=reference_type,
            options=options,
        )
        if bool(raw_field.get("readOnly", False)) or raw_field.get("editable") is False:
            editor_kind = FieldEditorKind.UNSUPPORTED
            unsupported_reason = "읽기 전용 필드입니다."
        if tracker_item_field in {
            "id",
            "tracker",
            "createdAt",
            "createdBy",
            "modifiedAt",
            "modifiedBy",
            "parent",
            "children",
            "comments",
        }:
            editor_kind = FieldEditorKind.UNSUPPORTED
            unsupported_reason = "서버가 관리하는 읽기 전용 필드입니다."

        table_columns = (
            _table_column_fields(raw_field)
            if editor_kind == FieldEditorKind.TABLE
            else ()
        )
        if editor_kind == FieldEditorKind.TABLE and not table_columns:
            editor_kind = FieldEditorKind.UNSUPPORTED
            unsupported_reason = "TableField 열 정의를 schema에서 확인할 수 없습니다."
        elif editor_kind == FieldEditorKind.TABLE and not any(
            column.editable for column in table_columns
        ):
            editor_kind = FieldEditorKind.UNSUPPORTED
            unsupported_reason = "편집할 수 있는 TableField 열이 없습니다."

        normalized = EditableTrackerField(
            field_id=field_id,
            name=name,
            label=label,
            type_name=type_name,
            value_model=value_model,
            tracker_item_field=tracker_item_field,
            reference_type=reference_type,
            multiple_values=bool(raw_field.get("multipleValues", False)),
            mandatory=bool(raw_field.get("mandatory", False)),
            editor_kind=editor_kind,
            options=options,
            table_columns=table_columns,
            current_value=(
                None
                if detail is None
                else _field_current_value(
                    detail,
                    field_id=field_id,
                    name=name,
                    tracker_item_field=tracker_item_field,
                )
            ),
            unsupported_reason=unsupported_reason,
            raw_schema=deepcopy(raw_field),
        )
        normalized_fields.append(normalized)
        if normalized.is_status:
            status_field = normalized

    if not normalized_fields:
        raise ValueError("트래커 schema에서 편집 가능한 필드 정의를 찾을 수 없습니다.")
    return EditableTrackerSchema(
        tracker_id=int(tracker_id),
        fields=tuple(normalized_fields),
        status_field=status_field,
    )


def build_editable_tracker_schema(
    schema: dict[str, Any],
    detail: TrackerItemDetail,
) -> EditableTrackerSchema:
    tracker_id = detail.summary.tracker_id
    if tracker_id is None:
        raise ValueError("아이템의 소속 트래커 ID를 확인할 수 없습니다.")
    return _build_tracker_schema(
        schema,
        tracker_id=int(tracker_id),
        detail=detail,
    )


def build_create_tracker_schema(
    schema: dict[str, Any],
    tracker_id: int,
) -> EditableTrackerSchema:
    normalized_tracker_id = _optional_int(tracker_id)
    if normalized_tracker_id is None or normalized_tracker_id <= 0:
        raise ValueError("생성 대상 트래커 ID가 올바르지 않습니다.")
    normalized_schema = _build_tracker_schema(
        schema,
        tracker_id=normalized_tracker_id,
        detail=None,
    )
    fields: list[EditableTrackerField] = []
    for field_value in normalized_schema.fields:
        if field_value.tracker_item_field == "name" and not field_value.mandatory:
            field_value = replace(field_value, mandatory=True)
        fields.append(field_value)
    return EditableTrackerSchema(
        tracker_id=normalized_schema.tracker_id,
        fields=tuple(fields),
        status_field=normalized_schema.status_field,
    )


def _value_model_name(field_value: EditableTrackerField, fallback: str) -> str:
    model = str(field_value.value_model or "").strip()
    if model:
        return model.split("<", 1)[0].strip()
    return fallback


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _choice_references(
    field_value: EditableTrackerField,
    raw_value: Any,
) -> list[dict[str, Any]]:
    values = list(raw_value) if isinstance(raw_value, (list, tuple, set)) else [raw_value]
    if len(values) == 1 and values[0] in (None, ""):
        values = []
    by_id = {option.option_id: option for option in field_value.options}
    references: list[dict[str, Any]] = []
    for value in values:
        option_id = _optional_int(value.get("id")) if isinstance(value, dict) else _optional_int(value)
        if option_id is None or option_id not in by_id:
            raise ValueError(f"'{field_value.label}'에서 알 수 없는 선택값을 받았습니다.")
        option = by_id[option_id]
        references.append(
            {
                "id": option.option_id,
                "name": option.name,
                "type": option.type_name,
            }
        )
    if not field_value.multiple_values and len(references) > 1:
        raise ValueError(f"'{field_value.label}'은(는) 하나의 값만 선택할 수 있습니다.")
    return references


def _reference_ids(raw_value: Any) -> list[int]:
    if isinstance(raw_value, str):
        values: Iterable[Any] = re.split(r"[;\n\r]+", raw_value)
    elif isinstance(raw_value, (list, tuple, set)):
        values = raw_value
    elif raw_value in (None, ""):
        values = ()
    else:
        values = (raw_value,)
    normalized: list[int] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("id")
        if value in (None, ""):
            continue
        item_id = _optional_int(str(value).strip())
        if item_id is None or item_id <= 0:
            raise ValueError("참조 ID는 양의 정수여야 합니다.")
        if item_id not in normalized:
            normalized.append(item_id)
    return normalized


def _table_rows(
    field_value: EditableTrackerField,
    raw_value: Any,
) -> list[list[dict[str, Any]]]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"'{field_value.label}' 테이블 값은 행 목록이어야 합니다.")
    rows: list[list[dict[str, Any]]] = []
    for row_index, raw_row in enumerate(raw_value, start=1):
        if isinstance(raw_row, dict):
            raw_row = (
                raw_row.get("values")
                if "values" in raw_row
                else raw_row.get("fieldValues")
            )
        if not isinstance(raw_row, list):
            raise ValueError(f"'{field_value.label}' {row_index}행 구조가 올바르지 않습니다.")
        normalized_row: list[dict[str, Any]] = []
        seen_field_ids: set[int] = set()
        for raw_cell in raw_row:
            if not isinstance(raw_cell, dict):
                raise ValueError(
                    f"'{field_value.label}' {row_index}행의 셀 값이 객체가 아닙니다."
                )
            field_id = _optional_int(
                raw_cell.get("fieldId") or raw_cell.get("id")
            )
            type_name = str(raw_cell.get("type") or "").strip()
            if field_id is None or field_id <= 0 or not type_name:
                raise ValueError(
                    f"'{field_value.label}' {row_index}행 셀의 fieldId와 type이 필요합니다."
                )
            if field_id in seen_field_ids:
                raise ValueError(
                    f"'{field_value.label}' {row_index}행에 같은 열이 중복되어 있습니다."
                )
            seen_field_ids.add(field_id)
            normalized_row.append(deepcopy(raw_cell))
        rows.append(normalized_row)
    return rows


def build_field_value(change: TrackerItemFieldChange) -> dict[str, Any]:
    field_value = change.field
    if not field_value.editable and not field_value.is_status:
        raise ValueError(
            field_value.unsupported_reason or f"'{field_value.label}' 필드는 수정할 수 없습니다."
        )
    raw_value = change.value
    if field_value.mandatory and _is_empty(raw_value):
        raise ValueError(f"'{field_value.label}' 필수값을 비울 수 없습니다.")

    payload: dict[str, Any] = {
        "fieldId": field_value.field_id,
        "name": field_value.name,
    }
    kind = field_value.editor_kind
    if kind in {FieldEditorKind.TEXT, FieldEditorKind.MULTILINE_TEXT}:
        payload["type"] = _value_model_name(field_value, "TextFieldValue")
        payload["value"] = str(raw_value or "")
    elif kind == FieldEditorKind.BOOLEAN:
        payload["type"] = _value_model_name(field_value, "BoolFieldValue")
        if isinstance(raw_value, bool):
            payload["value"] = raw_value
        else:
            normalized = str(raw_value or "").strip().casefold()
            if normalized not in {"true", "false", "1", "0", "yes", "no", "예", "아니요"}:
                raise ValueError(f"'{field_value.label}' 값은 예 또는 아니요여야 합니다.")
            payload["value"] = normalized in {"true", "1", "yes", "예"}
    elif kind == FieldEditorKind.INTEGER:
        payload["type"] = _value_model_name(field_value, "IntegerFieldValue")
        payload["value"] = None if _is_empty(raw_value) else int(raw_value)
    elif kind == FieldEditorKind.DECIMAL:
        payload["type"] = _value_model_name(field_value, "DecimalFieldValue")
        payload["value"] = None if _is_empty(raw_value) else float(raw_value)
    elif kind in {FieldEditorKind.DATE, FieldEditorKind.DATETIME}:
        fallback = "DateFieldValue" if kind == FieldEditorKind.DATE else "DateTimeFieldValue"
        payload["type"] = _value_model_name(field_value, fallback)
        payload["value"] = str(raw_value or "").strip() or None
    elif kind in {FieldEditorKind.CHOICE, FieldEditorKind.STATUS}:
        references = _choice_references(field_value, raw_value)
        if kind == FieldEditorKind.STATUS and len(references) != 1:
            raise ValueError("상태 전환 대상은 하나만 선택해야 합니다.")
        payload["type"] = _value_model_name(field_value, "ChoiceFieldValue")
        payload["values"] = references
    elif kind == FieldEditorKind.REFERENCE:
        reference_ids = _reference_ids(raw_value)
        if not field_value.multiple_values and len(reference_ids) > 1:
            raise ValueError(f"'{field_value.label}'은(는) 하나의 참조만 입력할 수 있습니다.")
        reference_type = field_value.reference_type or "Reference"
        payload["type"] = _value_model_name(field_value, "ChoiceFieldValue")
        payload["values"] = [
            {"id": reference_id, "type": reference_type}
            for reference_id in reference_ids
        ]
    elif kind == FieldEditorKind.TABLE:
        payload["type"] = _value_model_name(field_value, "TableFieldValue")
        payload["values"] = _table_rows(field_value, raw_value)
    else:
        raise ValueError(
            field_value.unsupported_reason or f"'{field_value.label}' 형식을 지원하지 않습니다."
        )
    return payload


def _builtin_create_value(
    field_value: EditableTrackerField,
    field_payload: dict[str, Any],
) -> Any:
    if field_value.editor_kind in {
        FieldEditorKind.TEXT,
        FieldEditorKind.MULTILINE_TEXT,
        FieldEditorKind.BOOLEAN,
        FieldEditorKind.INTEGER,
        FieldEditorKind.DECIMAL,
        FieldEditorKind.DATE,
        FieldEditorKind.DATETIME,
    }:
        return deepcopy(field_payload.get("value"))
    if field_value.editor_kind in {
        FieldEditorKind.CHOICE,
        FieldEditorKind.REFERENCE,
    }:
        references = deepcopy(field_payload.get("values") or [])
        if field_value.multiple_values:
            return references
        return references[0] if references else None
    raise ValueError(f"'{field_value.label}'은(는) 생성 payload로 변환할 수 없습니다.")


def _is_create_status_field(field_value: EditableTrackerField) -> bool:
    return field_value.is_status or field_value.tracker_item_field == "status"


def build_create_item_payload(
    schema: EditableTrackerSchema,
    changes: Iterable[TrackerItemFieldChange],
) -> dict[str, Any]:
    """명시적으로 포함한 필드를 신규 item payload로 변환한다."""
    normalized_changes = tuple(changes)
    schema_fields = {field_value.field_id: field_value for field_value in schema.fields}
    field_ids = [change.field.field_id for change in normalized_changes]
    if len(field_ids) != len(set(field_ids)):
        raise ValueError("같은 필드가 생성 입력에 중복되어 있습니다.")

    unknown_ids = [field_id for field_id in field_ids if field_id not in schema_fields]
    if unknown_ids:
        raise ValueError("현재 트래커 schema에 없는 필드가 생성 입력에 포함되었습니다.")

    selected_by_id = {change.field.field_id: change.value for change in normalized_changes}
    required_fields = tuple(
        field_value
        for field_value in schema.fields
        if field_value.mandatory and not _is_create_status_field(field_value)
    )
    unsupported_required = [
        field_value.label for field_value in required_fields if not field_value.editable
    ]
    if unsupported_required:
        raise ValueError(
            "필수 필드의 입력 형식을 지원하지 않습니다: "
            + ", ".join(unsupported_required)
        )
    missing_required = [
        field_value.label
        for field_value in required_fields
        if field_value.field_id not in selected_by_id
    ]
    if missing_required:
        raise ValueError("필수 필드를 입력하세요: " + ", ".join(missing_required))

    payload: dict[str, Any] = {}
    custom_fields: list[dict[str, Any]] = []
    builtin_targets: set[str] = set()
    for change in normalized_changes:
        canonical_field = schema_fields[change.field.field_id]
        if _is_create_status_field(canonical_field):
            raise ValueError("상태는 생성 후 별도의 상태 전환으로 변경해야 합니다.")
        if not canonical_field.editable:
            raise ValueError(
                canonical_field.unsupported_reason
                or f"'{canonical_field.label}' 필드는 생성에 사용할 수 없습니다."
            )
        canonical_change = TrackerItemFieldChange(canonical_field, change.value)
        field_payload = build_field_value(canonical_change)
        tracker_item_field = str(canonical_field.tracker_item_field or "").strip()
        if tracker_item_field:
            if tracker_item_field in builtin_targets:
                raise ValueError(
                    f"'{canonical_field.label}'의 생성 대상 필드가 중복되었습니다."
                )
            builtin_targets.add(tracker_item_field)
            payload[tracker_item_field] = _builtin_create_value(
                canonical_field,
                field_payload,
            )
        else:
            custom_fields.append(field_payload)

    if _is_empty(payload.get("name")):
        raise ValueError("'Summary' 필수값을 입력하세요.")
    if custom_fields:
        payload["customFields"] = custom_fields
    return payload


_WRITE_MESSAGES = {
    TrackerItemWriteErrorKind.WRITE_DISABLED: "테스트 모드에서는 아이템을 생성·수정·삭제할 수 없습니다.",
    TrackerItemWriteErrorKind.CONFLICT: "다른 사용자가 이 아이템을 변경했습니다. 최신 상세를 다시 불러오세요.",
    TrackerItemWriteErrorKind.INVALID_VALUE: "변경값을 적용할 수 없습니다. 필드 값과 필수 조건을 확인하세요.",
    TrackerItemWriteErrorKind.UNAUTHORIZED: "Codebeamer 인증에 실패했습니다. 활성 연결 정보를 확인하세요.",
    TrackerItemWriteErrorKind.FORBIDDEN: "이 아이템을 변경할 권한이 없습니다.",
    TrackerItemWriteErrorKind.NOT_FOUND: "변경할 아이템을 찾을 수 없습니다.",
    TrackerItemWriteErrorKind.RATE_LIMITED: "서버 요청 제한에 도달했습니다. 잠시 후 다시 시도하세요.",
    TrackerItemWriteErrorKind.NETWORK: "Codebeamer 서버에 연결하지 못했습니다.",
    TrackerItemWriteErrorKind.SERVER: "Codebeamer 서버가 변경 요청을 처리하지 못했습니다.",
    TrackerItemWriteErrorKind.UNKNOWN: "아이템 변경 중 예상하지 못한 오류가 발생했습니다.",
}


def classify_tracker_item_write_error(
    exc: Exception,
) -> tuple[TrackerItemWriteErrorKind, int | None]:
    if isinstance(exc, TrackerItemWriteError):
        return exc.kind, exc.status_code
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 401:
        return TrackerItemWriteErrorKind.UNAUTHORIZED, status_code
    if status_code == 403:
        return TrackerItemWriteErrorKind.FORBIDDEN, status_code
    if status_code == 404:
        return TrackerItemWriteErrorKind.NOT_FOUND, status_code
    if status_code == 409:
        return TrackerItemWriteErrorKind.CONFLICT, status_code
    if status_code == 429:
        return TrackerItemWriteErrorKind.RATE_LIMITED, status_code
    if status_code in {400, 422}:
        return TrackerItemWriteErrorKind.INVALID_VALUE, status_code
    if isinstance(status_code, int) and status_code >= 500:
        return TrackerItemWriteErrorKind.SERVER, status_code
    if isinstance(exc, (TypeError, ValueError)):
        return TrackerItemWriteErrorKind.INVALID_VALUE, None
    class_name = type(exc).__name__.casefold()
    if "timeout" in class_name or "connection" in class_name:
        return TrackerItemWriteErrorKind.NETWORK, None
    return TrackerItemWriteErrorKind.UNKNOWN, status_code


class TrackerItemEditorService:
    """Schema 기반 단건 생성, 부분 수정, Status 필드 변경과 삭제를 실행한다."""

    def __init__(
        self,
        client_factory=CodebeamerClient,
        query_service: TrackerQueryService | None = None,
        logger=None,
    ) -> None:
        self.client_factory = client_factory
        self.logger = logger
        self.query_service = query_service or TrackerQueryService(
            client_factory=client_factory,
            logger=logger,
        )

    def _client(self, settings):
        return _build_gui_client(settings, self.client_factory, self.logger)

    @staticmethod
    def _run(operation: str, callback):
        try:
            return callback()
        except TrackerItemWriteError:
            raise
        except Exception as exc:
            kind, status_code = classify_tracker_item_write_error(exc)
            raise TrackerItemWriteError(
                kind,
                _WRITE_MESSAGES[kind],
                status_code=status_code,
                operation=operation,
            ) from exc

    @staticmethod
    def _ensure_write_enabled(settings) -> None:
        if bool(getattr(settings, "offline_mode", False)):
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.WRITE_DISABLED,
                _WRITE_MESSAGES[TrackerItemWriteErrorKind.WRITE_DISABLED],
                operation="write_guard",
            )

    @staticmethod
    def _verify_version(client: Any, item_id: int, expected_version: int | None) -> None:
        if expected_version is None:
            return
        raw_item = client.get_item(int(item_id))
        current_version = _optional_int(
            raw_item.get("version") if isinstance(raw_item, dict) else None
        )
        if current_version != int(expected_version):
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.CONFLICT,
                _WRITE_MESSAGES[TrackerItemWriteErrorKind.CONFLICT],
                operation="verify_version",
            )

    def load_schema(self, settings, detail: TrackerItemDetail) -> EditableTrackerSchema:
        tracker_id = detail.summary.tracker_id
        if tracker_id is None:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "아이템의 소속 트래커를 확인할 수 없습니다.",
                operation="load_editor_schema",
            )
        schema = self.query_service.load_tracker_schema(settings, int(tracker_id))
        return self._run(
            "load_editor_schema",
            lambda: build_editable_tracker_schema(schema, detail),
        )

    def load_create_schema(
        self,
        settings,
        tracker_id: int,
    ) -> EditableTrackerSchema:
        schema = self.query_service.load_tracker_schema(settings, int(tracker_id))
        return self._run(
            "load_create_schema",
            lambda: build_create_tracker_schema(schema, int(tracker_id)),
        )

    def create_item(
        self,
        settings,
        *,
        tracker_id: int,
        schema: EditableTrackerSchema,
        changes: Iterable[TrackerItemFieldChange],
        parent_item_id: int | None = None,
    ) -> TrackerItemDetail:
        self._ensure_write_enabled(settings)
        normalized_tracker_id = _optional_int(tracker_id)
        if normalized_tracker_id is None or normalized_tracker_id <= 0:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "생성 대상 트래커 ID가 올바르지 않습니다.",
                operation="create_item",
            )
        if schema.tracker_id != normalized_tracker_id:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "불러온 schema와 생성 대상 트래커가 일치하지 않습니다.",
                operation="create_item",
            )
        try:
            payload = build_create_item_payload(schema, changes)
        except (TypeError, ValueError) as exc:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                str(exc) or _WRITE_MESSAGES[TrackerItemWriteErrorKind.INVALID_VALUE],
                operation="build_create_payload",
            ) from exc

        normalized_parent_id = _optional_int(parent_item_id)
        if parent_item_id is not None and (
            normalized_parent_id is None or normalized_parent_id <= 0
        ):
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "상위 아이템 ID가 올바르지 않습니다.",
                operation="verify_create_parent",
            )
        if normalized_parent_id is not None:
            parent_detail = self._run(
                "verify_create_parent",
                lambda: self.query_service.load_detail(settings, normalized_parent_id),
            )
            if parent_detail.summary.tracker_id != normalized_tracker_id:
                raise TrackerItemWriteError(
                    TrackerItemWriteErrorKind.INVALID_VALUE,
                    "선택한 상위 아이템은 현재 트래커에 속하지 않습니다.",
                    operation="verify_create_parent",
                )

        client = self._run("build_write_client", lambda: self._client(settings))
        response = self._run(
            "create_item",
            lambda: client.create_item(
                normalized_tracker_id,
                payload,
                parent_item_id=normalized_parent_id,
            ),
        )
        item_id = _optional_int(response.get("id") if isinstance(response, dict) else None)
        if item_id is None or item_id <= 0:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.UNKNOWN,
                "서버가 생성된 아이템 ID를 반환하지 않았습니다. 중복 생성을 피하려면 트래커에서 결과를 확인하세요.",
                operation="create_item_response",
            )
        try:
            return self.query_service.load_detail(settings, item_id)
        except Exception as exc:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.UNKNOWN,
                f"아이템 #{item_id} 생성은 완료됐지만 상세를 다시 불러오지 못했습니다. ID 바로 열기로 확인하세요.",
                operation="load_created_detail",
            ) from exc

    def update_fields(
        self,
        settings,
        *,
        item_id: int,
        expected_version: int | None,
        changes: Iterable[TrackerItemFieldChange],
    ) -> TrackerItemDetail:
        self._ensure_write_enabled(settings)
        normalized_changes = tuple(changes)
        if not normalized_changes:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "저장할 변경 필드가 없습니다.",
                operation="update_fields",
            )
        if any(change.field.is_status for change in normalized_changes):
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "상태는 별도의 상태 전환 동작으로 변경해야 합니다.",
                operation="update_fields",
            )
        field_ids = [change.field.field_id for change in normalized_changes]
        if len(field_ids) != len(set(field_ids)):
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "같은 필드가 변경 목록에 중복되어 있습니다.",
                operation="update_fields",
            )
        field_values = self._run(
            "build_field_values",
            lambda: [build_field_value(change) for change in normalized_changes],
        )
        client = self._run("build_write_client", lambda: self._client(settings))
        self._run(
            "verify_version",
            lambda: self._verify_version(client, int(item_id), expected_version),
        )
        self._run(
            "update_fields",
            lambda: client.update_item_fields(int(item_id), field_values),
        )
        return self.query_service.load_detail(settings, int(item_id))

    def change_status_field(
        self,
        settings,
        *,
        item_id: int,
        expected_version: int | None,
        status_field: EditableTrackerField,
        option_id: int,
    ) -> TrackerItemDetail:
        self._ensure_write_enabled(settings)
        if not status_field.is_status:
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.INVALID_VALUE,
                "상태 필드 정의가 올바르지 않습니다.",
                operation="change_status_field",
            )
        field_value = self._run(
            "build_status_value",
            lambda: build_field_value(
                TrackerItemFieldChange(field=status_field, value=int(option_id))
            ),
        )
        client = self._run("build_write_client", lambda: self._client(settings))
        self._run(
            "verify_version",
            lambda: self._verify_version(client, int(item_id), expected_version),
        )
        self._run(
            "change_status_field",
            lambda: client.update_item_fields(int(item_id), [field_value]),
        )
        return self.query_service.load_detail(settings, int(item_id))

    def transition_status(self, *args, **kwargs) -> TrackerItemDetail:
        """호환용 별칭. 실제 동작은 workflow transition이 아닌 Status 필드 변경이다."""
        return self.change_status_field(*args, **kwargs)

    def delete_item(
        self,
        settings,
        *,
        item_id: int,
        expected_version: int | None,
    ) -> None:
        self._ensure_write_enabled(settings)
        client = self._run("build_write_client", lambda: self._client(settings))
        self._run(
            "verify_version",
            lambda: self._verify_version(client, int(item_id), expected_version),
        )
        self._run("delete_item", lambda: client.delete_item(int(item_id)))


__all__ = [
    "EditableFieldOption",
    "EditableTrackerField",
    "EditableTrackerSchema",
    "FieldEditorKind",
    "TrackerItemEditorService",
    "TrackerItemFieldChange",
    "TrackerItemWriteError",
    "TrackerItemWriteErrorKind",
    "build_create_item_payload",
    "build_create_tracker_schema",
    "build_editable_tracker_schema",
    "build_field_value",
    "classify_tracker_item_write_error",
]
