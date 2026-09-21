from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

from .payload_values import as_mapping
from .payload_values import optional_int


DEFAULT_TRACKER_QUERY_PAGE_SIZE = 100
MAX_TRACKER_QUERY_PAGE_SIZE = 500


class TrackerSearchMode(str, Enum):
    SIMPLE = "simple"
    CONDITIONS = "conditions"
    CBQL = "cbql"


class LoadState(str, Enum):
    IDLE = "idle"
    LOADING = "loading"
    LOADED = "loaded"
    EMPTY = "empty"
    ERROR = "error"
    STALE = "stale"


class TrackerQueryErrorKind(str, Enum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    INVALID_QUERY = "invalid_query"
    NETWORK = "network"
    SERVER = "server"
    OFFLINE_DATA_UNAVAILABLE = "offline_data_unavailable"
    UNKNOWN = "unknown"


class TrackerQueryServiceError(RuntimeError):
    def __init__(
        self,
        kind: TrackerQueryErrorKind,
        message: str,
        *,
        status_code: int | None = None,
        operation: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = TrackerQueryErrorKind(kind)
        self.status_code = status_code
        self.operation = str(operation or "")


_OPERATOR_ALIASES = {
    "=": "=",
    "eq": "=",
    "equals": "=",
    "!=": "!=",
    "ne": "!=",
    "not_equals": "!=",
    ">": ">",
    "gt": ">",
    ">=": ">=",
    "gte": ">=",
    "<": "<",
    "lt": "<",
    "<=": "<=",
    "lte": "<=",
    "like": "LIKE",
    "contains": "CONTAINS",
    "not like": "NOT LIKE",
    "not_like": "NOT LIKE",
    "not_contains": "NOT CONTAINS",
    "in": "IN",
    "not in": "NOT IN",
    "not_in": "NOT IN",
}
_SORT_TERM_PATTERN = re.compile(
    r"^(?P<field>[A-Za-z_][A-Za-z0-9_.]*)(?:\s+(?P<direction>ASC|DESC))?$",
    re.IGNORECASE,
)
_SIMPLE_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_TRAILING_ORDER_PATTERN = re.compile(r"\s+ORDER\s+BY\s+(.+?)\s*$", re.IGNORECASE)


def _positive_int(value: Any, *, label: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}은(는) 양의 정수여야 합니다.") from exc
    if normalized <= 0:
        raise ValueError(f"{label}은(는) 양의 정수여야 합니다.")
    return normalized


def _display_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, dict):
        for key in ("name", "summary", "value", "id"):
            if value.get(key) not in (None, ""):
                return _display_text(value.get(key))
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(text for text in (_display_text(item) for item in value) if text)
    return str(value).strip()


def _quote_cbql_value(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict) and value.get("id") is not None:
        return str(_positive_int(value.get("id"), label="참조 ID"))
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _cbql_field_expression(field_name: str) -> str:
    normalized = str(field_name or "").strip()
    if not normalized:
        raise ValueError("검색 조건 필드가 비어 있습니다.")
    if any(character in normalized for character in ("\n", "\r", ";")):
        raise ValueError("검색 조건 필드에 허용되지 않는 문자가 있습니다.")
    if _SIMPLE_FIELD_PATTERN.fullmatch(normalized):
        return normalized
    return f"'{normalized.replace(chr(39), chr(39) * 2)}'"


def normalize_cbql_sort(sort_text: str | None) -> str:
    normalized = str(sort_text or "").strip()
    if not normalized:
        return "item.id ASC"
    terms: list[str] = []
    for raw_term in normalized.split(","):
        match = _SORT_TERM_PATTERN.fullmatch(raw_term.strip())
        if match is None:
            raise ValueError(f"지원하지 않는 정렬식입니다: {raw_term.strip()}")
        field_name = match.group("field")
        direction = (match.group("direction") or "ASC").upper()
        terms.append(f"{field_name} {direction}")
    return ", ".join(terms)


@dataclass(frozen=True)
class TrackerQueryCondition:
    field_name: str
    operator: str
    value: Any
    field_type: str = ""

    def to_cbql(self) -> str:
        field_expression = _cbql_field_expression(self.field_name)
        operator_key = str(self.operator or "").strip().lower()
        operator = _OPERATOR_ALIASES.get(operator_key)
        if operator is None:
            raise ValueError(f"지원하지 않는 검색 연산자입니다: {self.operator}")

        if operator in {"IN", "NOT IN"}:
            if not isinstance(self.value, (list, tuple, set)):
                raise ValueError(f"{operator} 조건에는 값 목록이 필요합니다.")
            values = list(self.value)
            if not values:
                raise ValueError(f"{operator} 조건의 값 목록이 비어 있습니다.")
            serialized = ", ".join(_quote_cbql_value(value) for value in values)
            return f"{field_expression} {operator} ({serialized})"

        if self.value in (None, ""):
            raise ValueError(f"{self.field_name} 조건의 값이 비어 있습니다.")
        if operator == "CONTAINS":
            return f"{field_expression} LIKE {_quote_cbql_value(f'%{self.value}%')}"
        if operator == "NOT CONTAINS":
            return f"{field_expression} NOT LIKE {_quote_cbql_value(f'%{self.value}%')}"
        return f"{field_expression} {operator} {_quote_cbql_value(self.value)}"


@dataclass(frozen=True)
class TrackerQueryGroup:
    conditions: tuple[TrackerQueryCondition, ...] = field(default_factory=tuple)

    def __init__(self, conditions: Iterable[TrackerQueryCondition] = ()) -> None:
        object.__setattr__(self, "conditions", tuple(conditions))

    def to_cbql(self) -> str:
        parts = [condition.to_cbql() for condition in self.conditions]
        if not parts:
            return ""
        return " AND ".join(parts)


@dataclass(frozen=True)
class TrackerQuery:
    tracker_id: int
    mode: TrackerSearchMode = TrackerSearchMode.SIMPLE
    text: str = ""
    status: str = ""
    assignee: str = ""
    groups: tuple[TrackerQueryGroup, ...] = field(default_factory=tuple)
    cbql: str = ""
    page: int = 1
    page_size: int = DEFAULT_TRACKER_QUERY_PAGE_SIZE
    sort: str = "item.id ASC"
    baseline_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tracker_id",
            _positive_int(self.tracker_id, label="트래커 ID"),
        )
        object.__setattr__(self, "mode", TrackerSearchMode(self.mode))
        object.__setattr__(self, "groups", tuple(self.groups))
        object.__setattr__(self, "page", _positive_int(self.page, label="페이지"))
        page_size = _positive_int(self.page_size, label="페이지 크기")
        object.__setattr__(self, "page_size", min(page_size, MAX_TRACKER_QUERY_PAGE_SIZE))
        object.__setattr__(self, "sort", normalize_cbql_sort(self.sort))
        if self.baseline_id is not None:
            object.__setattr__(
                self,
                "baseline_id",
                _positive_int(self.baseline_id, label="Baseline ID"),
            )

    def build_cbql(self) -> str:
        tracker_scope = f"tracker.id = {self.tracker_id}"
        condition = ""
        user_sort = ""

        if self.mode == TrackerSearchMode.SIMPLE:
            conditions: list[str] = []
            text = str(self.text or "").strip()
            if text:
                escaped = text.replace("'", "''")
                if text.isdigit():
                    conditions.append(
                        f"(item.id = {int(text)} OR summary LIKE '%{escaped}%')"
                    )
                else:
                    conditions.append(f"summary LIKE '%{escaped}%'")
            if str(self.status or "").strip():
                conditions.append(f"status = {_quote_cbql_value(str(self.status).strip())}")
            if str(self.assignee or "").strip():
                conditions.append(
                    f"assignedTo = {_quote_cbql_value(str(self.assignee).strip())}"
                )
            condition = " AND ".join(conditions)
        elif self.mode == TrackerSearchMode.CONDITIONS:
            groups = [group.to_cbql() for group in self.groups]
            groups = [group for group in groups if group]
            if not groups:
                raise ValueError("조건 조합 검색에는 하나 이상의 완성된 조건이 필요합니다.")
            condition = " OR ".join(f"({group})" for group in groups)
        else:
            condition = str(self.cbql or "").strip()
            if ";" in condition or "\n" in condition or "\r" in condition:
                raise ValueError("CbQL에는 한 개의 조건식만 입력할 수 있습니다.")
            if re.search(r"\b(SELECT|GROUP\s+BY)\b", condition, re.IGNORECASE):
                raise ValueError(
                    "현재 화면의 CbQL 모드는 조건식과 ORDER BY만 지원합니다. "
                    "SELECT 또는 GROUP BY는 사용할 수 없습니다."
                )
            if condition.upper().startswith("WHERE "):
                condition = condition[6:].strip()
            order_match = _TRAILING_ORDER_PATTERN.search(condition)
            if order_match is not None:
                user_sort = normalize_cbql_sort(order_match.group(1))
                condition = condition[: order_match.start()].strip()

        scoped_condition = tracker_scope
        if condition:
            scoped_condition = f"{tracker_scope} AND ({condition})"
        sort = user_sort or self.sort
        return f"{scoped_condition} ORDER BY {sort}"


@dataclass(frozen=True)
class TrackerItemReferenceSummary:
    item_id: int
    name: str

    @classmethod
    def from_raw(cls, value: Any) -> TrackerItemReferenceSummary | None:
        if not isinstance(value, dict):
            return None
        item_id = optional_int(value.get("id"))
        if item_id is None:
            return None
        return cls(
            item_id=item_id,
            name=str(value.get("name") or value.get("summary") or item_id),
        )


@dataclass(frozen=True)
class ProjectSummary:
    project_id: int
    name: str
    raw_reference: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_raw(cls, value: dict[str, Any]) -> ProjectSummary:
        if not isinstance(value, dict):
            raise ValueError("프로젝트 응답은 객체여야 합니다.")
        project_id = _positive_int(value.get("id"), label="프로젝트 ID")
        return cls(
            project_id=project_id,
            name=str(value.get("name") or value.get("key") or project_id),
            raw_reference=mask_sensitive_payload(value),
        )


@dataclass(frozen=True)
class TrackerSummary:
    tracker_id: int
    name: str
    project_id: int | None = None
    project_name: str = ""
    type_name: str = ""
    raw_reference: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_raw(
        cls,
        value: dict[str, Any],
        *,
        project_id: int | None = None,
        project_name: str = "",
    ) -> TrackerSummary:
        if not isinstance(value, dict):
            raise ValueError("트래커 응답은 객체여야 합니다.")
        tracker_id = _positive_int(value.get("id"), label="트래커 ID")
        project = as_mapping(value.get("project"))
        return cls(
            tracker_id=tracker_id,
            name=str(value.get("name") or value.get("key") or tracker_id),
            project_id=(
                optional_int(project.get("id"))
                or optional_int(value.get("projectId"))
                or optional_int(project_id)
            ),
            project_name=str(
                project.get("name") or value.get("projectName") or project_name or ""
            ),
            type_name=str(value.get("type") or value.get("typeName") or ""),
            raw_reference=mask_sensitive_payload(value),
        )


@dataclass(frozen=True)
class TrackerItemSummary:
    item_id: int
    name: str
    tracker_id: int | None = None
    tracker_name: str = ""
    project_id: int | None = None
    project_name: str = ""
    status: str = ""
    assignees: tuple[str, ...] = field(default_factory=tuple)
    modified_at: str = ""
    parent_id: int | None = None
    parent_name: str = ""
    child_count: int | None = None
    has_children: bool = False
    version: int | None = None
    raw_reference: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_raw(
        cls,
        value: dict[str, Any],
        *,
        tracker_id: int | None = None,
        tracker_name: str = "",
        project_id: int | None = None,
        project_name: str = "",
    ) -> TrackerItemSummary:
        if not isinstance(value, dict):
            raise ValueError("트래커 아이템 응답은 객체여야 합니다.")
        item_id = _positive_int(value.get("id"), label="아이템 ID")
        tracker = as_mapping(value.get("tracker"))
        project = as_mapping(value.get("project"))
        if not project:
            project = as_mapping(tracker.get("project"))
        parent = as_mapping(value.get("parent"))
        children = value.get("children") if isinstance(value.get("children"), list) else []
        raw_assignees = value.get("assignedTo")
        if raw_assignees is None:
            raw_assignees = value.get("assignees")
        if not isinstance(raw_assignees, list):
            raw_assignees = [] if raw_assignees in (None, "") else [raw_assignees]
        child_count = optional_int(value.get("childCount"))
        if child_count is None and children:
            child_count = len(children)
        has_children = bool(
            value.get("hasChildren", False)
            or value.get("leaf") is False
            or (child_count is not None and child_count > 0)
            or children
        )
        return cls(
            item_id=item_id,
            name=str(
                value.get("name")
                or value.get("summary")
                or value.get("key")
                or item_id
            ),
            tracker_id=optional_int(tracker.get("id")) or optional_int(tracker_id),
            tracker_name=str(tracker.get("name") or tracker_name or ""),
            project_id=(
                optional_int(project.get("id"))
                or optional_int(value.get("projectId"))
                or optional_int(project_id)
            ),
            project_name=str(
                project.get("name") or value.get("projectName") or project_name or ""
            ),
            status=_display_text(value.get("status")),
            assignees=tuple(
                text for text in (_display_text(item) for item in raw_assignees) if text
            ),
            modified_at=str(value.get("modifiedAt") or value.get("modified_at") or ""),
            parent_id=optional_int(parent.get("id")),
            parent_name=str(parent.get("name") or ""),
            child_count=child_count,
            has_children=has_children,
            version=optional_int(value.get("version")),
            raw_reference=deepcopy(value),
        )


@dataclass(frozen=True)
class TrackerFieldValue:
    field_id: int | None
    name: str
    type_name: str
    display_value: str
    raw_value: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_raw(cls, value: dict[str, Any]) -> TrackerFieldValue:
        raw_value = value.get("value")
        if "values" in value:
            raw_value = value.get("values")
        return cls(
            field_id=optional_int(value.get("fieldId") or value.get("id")),
            name=str(value.get("name") or "이름 없는 필드"),
            type_name=str(value.get("type") or value.get("valueModel") or "Unknown"),
            display_value=_display_text(raw_value),
            raw_value=deepcopy(value),
        )


_SENSITIVE_RAW_KEYS = {
    "access_token",
    "apikey",
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "password",
    "refresh_token",
    "secret",
    "session",
    "sessionid",
    "token",
}
_SENSITIVE_RAW_KEYS_COMPACT = {
    key.replace("_", "") for key in _SENSITIVE_RAW_KEYS
}


def mask_sensitive_payload(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, child in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            masked[key] = (
                "***"
                if (
                    normalized_key in _SENSITIVE_RAW_KEYS
                    or normalized_key.replace("_", "") in _SENSITIVE_RAW_KEYS_COMPACT
                )
                else mask_sensitive_payload(child)
            )
        return masked
    if isinstance(value, list):
        return [mask_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_sensitive_payload(item) for item in value)
    return deepcopy(value)


_NON_BUILTIN_DETAIL_KEYS = {"customFields"}


@dataclass(frozen=True)
class TrackerItemDetail:
    summary: TrackerItemSummary
    description: str = ""
    description_format: str = ""
    parent: TrackerItemReferenceSummary | None = None
    children: tuple[TrackerItemReferenceSummary, ...] = field(default_factory=tuple)
    custom_fields: tuple[TrackerFieldValue, ...] = field(default_factory=tuple)
    builtin_fields: dict[str, Any] = field(default_factory=dict, compare=False)
    raw_payload: dict[str, Any] = field(default_factory=dict, compare=False)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def item_id(self) -> int:
        return self.summary.item_id

    @property
    def version(self) -> int | None:
        return self.summary.version

    @classmethod
    def from_raw(
        cls,
        value: dict[str, Any],
        *,
        tracker_payload: dict[str, Any] | None = None,
    ) -> TrackerItemDetail:
        if not isinstance(value, dict):
            raise ValueError("아이템 상세 응답은 객체여야 합니다.")
        tracker_payload = as_mapping(tracker_payload)
        project = (
            as_mapping(tracker_payload.get("project"))
        )
        summary = TrackerItemSummary.from_raw(
            value,
            tracker_id=optional_int(tracker_payload.get("id")),
            tracker_name=str(tracker_payload.get("name") or ""),
            project_id=(
                optional_int(project.get("id"))
                or optional_int(tracker_payload.get("projectId"))
            ),
            project_name=str(
                project.get("name") or tracker_payload.get("projectName") or ""
            ),
        )
        parent = TrackerItemReferenceSummary.from_raw(value.get("parent"))
        children = tuple(
            item
            for item in (
                TrackerItemReferenceSummary.from_raw(raw_child)
                for raw_child in value.get("children", [])
            )
            if item is not None
        )
        custom_fields = tuple(
            TrackerFieldValue.from_raw(raw_field)
            for raw_field in value.get("customFields", [])
            if isinstance(raw_field, dict)
        )
        builtin_fields = {
            key: mask_sensitive_payload(raw_value)
            for key, raw_value in value.items()
            if key not in _NON_BUILTIN_DETAIL_KEYS
        }
        return cls(
            summary=summary,
            description=str(value.get("description") or ""),
            description_format=str(value.get("descriptionFormat") or ""),
            parent=parent,
            children=children,
            custom_fields=custom_fields,
            builtin_fields=builtin_fields,
            raw_payload=mask_sensitive_payload(value),
        )

    def normalized_payload(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "name": self.summary.name,
            "trackerId": self.summary.tracker_id,
            "trackerName": self.summary.tracker_name,
            "projectId": self.summary.project_id,
            "projectName": self.summary.project_name,
            "status": self.summary.status,
            "assignees": list(self.summary.assignees),
            "modifiedAt": self.summary.modified_at,
            "version": self.version,
            "parent": (
                None
                if self.parent is None
                else {"id": self.parent.item_id, "name": self.parent.name}
            ),
            "children": [
                {"id": child.item_id, "name": child.name} for child in self.children
            ],
            "customFields": [
                {
                    "fieldId": custom_field.field_id,
                    "name": custom_field.name,
                    "type": custom_field.type_name,
                    "displayValue": custom_field.display_value,
                }
                for custom_field in self.custom_fields
            ],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class TrackerItemContext:
    item: TrackerItemDetail
    tracker_id: int
    tracker_name: str
    project_id: int | None = None
    project_name: str = ""


@dataclass(frozen=True)
class PageResult[ItemT]:
    items: tuple[ItemT, ...]
    page: int
    page_size: int
    total: int
    requested_page: int
    requested_page_size: int
    server_metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total

    @property
    def server_honored_pagination(self) -> bool:
        return (
            self.page == self.requested_page
            and self.page_size == self.requested_page_size
        )

    @property
    def load_state(self) -> LoadState:
        return LoadState.LOADED if self.items else LoadState.EMPTY

    @classmethod
    def create(
        cls,
        items: Iterable[ItemT],
        *,
        raw_page: Any,
        requested_page: int,
        requested_page_size: int,
    ) -> PageResult[ItemT]:
        normalized_items = tuple(items)
        payload = as_mapping(raw_page)
        page = optional_int(payload.get("page")) or int(requested_page)
        page_size = optional_int(payload.get("pageSize")) or len(normalized_items)
        if page_size <= 0:
            page_size = int(requested_page_size)
        total = optional_int(payload.get("total"))
        if total is None:
            total = len(normalized_items)
        metadata = {
            key: mask_sensitive_payload(value)
            for key, value in payload.items()
            if key not in {"items", "itemRefs"}
        }
        return cls(
            items=normalized_items,
            page=page,
            page_size=page_size,
            total=max(total, 0),
            requested_page=int(requested_page),
            requested_page_size=int(requested_page_size),
            server_metadata=metadata,
        )


__all__ = [
    "DEFAULT_TRACKER_QUERY_PAGE_SIZE",
    "MAX_TRACKER_QUERY_PAGE_SIZE",
    "LoadState",
    "PageResult",
    "ProjectSummary",
    "TrackerFieldValue",
    "TrackerItemContext",
    "TrackerItemDetail",
    "TrackerItemReferenceSummary",
    "TrackerItemSummary",
    "TrackerQuery",
    "TrackerQueryCondition",
    "TrackerQueryErrorKind",
    "TrackerQueryGroup",
    "TrackerQueryServiceError",
    "TrackerSearchMode",
    "TrackerSummary",
    "mask_sensitive_payload",
    "normalize_cbql_sort",
]
