from __future__ import annotations

from enum import Enum
from typing import Any
from typing import TypedDict

from .models import OptionCheckStatus


class UploadMode(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class OperationScope(TypedDict):
    create: bool
    update: bool


UPLOAD_MODE_CREATE = UploadMode.CREATE.value
UPLOAD_MODE_UPDATE = UploadMode.UPDATE.value
UPLOAD_MODE_UPSERT = UploadMode.UPSERT.value
DEFAULT_TRACKER_ITEM_ID_REGEX = r"\[(?:[^:\]]+:)?(\d+)[^\]]*\]|^(\d+)(?:\.0)?$"

BLOCKING_OPTION_STATUSES = frozenset(
    {
        OptionCheckStatus.DIRECT_PARSE_FAILED.value,
        OptionCheckStatus.DF_COLUMN_MISSING.value,
        OptionCheckStatus.FIELD_UNSUPPORTED.value,
        OptionCheckStatus.LOOKUP_REQUIRED.value,
        OptionCheckStatus.OPTION_MAP_MISSING.value,
        OptionCheckStatus.OPTION_NOT_FOUND.value,
        OptionCheckStatus.OPTION_SOURCE_UNAVAILABLE.value,
        OptionCheckStatus.TRACKER_ITEM_LOOKUP_AMBIGUOUS.value,
        OptionCheckStatus.TRACKER_ITEM_LOOKUP_NOT_FOUND.value,
        OptionCheckStatus.TRACKER_ITEM_REGEX_MISSING.value,
    }
)

USER_LOOKUP_FAILURE_SUFFIXES = (
    "USER_LOOKUP_NOT_RUN",
    "USER_LOOKUP_FAILED",
    "USER_LOOKUP_AMBIGUOUS",
    "USER_NOT_FOUND",
    "MEMBER_LOOKUP_FAILED",
    "MEMBER_LOOKUP_AMBIGUOUS",
    "MEMBER_NOT_FOUND",
)


def normalize_upload_mode(upload_mode: Any) -> str:
    normalized = str(upload_mode or "").strip().lower()
    if normalized in {UPLOAD_MODE_CREATE, UPLOAD_MODE_UPDATE, UPLOAD_MODE_UPSERT}:
        return normalized
    return UPLOAD_MODE_CREATE


def upload_mode_supports_create(upload_mode: Any) -> bool:
    return normalize_upload_mode(upload_mode) in {UPLOAD_MODE_CREATE, UPLOAD_MODE_UPSERT}


def upload_mode_supports_update(upload_mode: Any) -> bool:
    return normalize_upload_mode(upload_mode) in {UPLOAD_MODE_UPDATE, UPLOAD_MODE_UPSERT}


def upload_mode_allows_root_items(upload_mode: Any) -> bool:
    return upload_mode_supports_create(upload_mode)


def upload_mode_action_label(upload_mode: Any) -> str:
    normalized_mode = normalize_upload_mode(upload_mode)
    if normalized_mode == UPLOAD_MODE_UPDATE:
        return "업데이트"
    if normalized_mode == UPLOAD_MODE_UPSERT:
        return "혼합 처리"
    return "업로드"


def as_operation_scope(raw_scope: Any) -> OperationScope:
    """임의의 값을 OperationScope 형태로 복사한다. 없는 키는 False 로 채운다."""
    mapping = raw_scope if isinstance(raw_scope, dict) else {}
    return OperationScope(
        create=bool(mapping.get("create", False)),
        update=bool(mapping.get("update", False)),
    )


def default_operation_scope(upload_mode: Any) -> OperationScope:
    normalized_mode = normalize_upload_mode(upload_mode)
    return {
        "create": normalized_mode in {UPLOAD_MODE_CREATE, UPLOAD_MODE_UPSERT},
        "update": normalized_mode in {UPLOAD_MODE_UPDATE, UPLOAD_MODE_UPSERT},
    }


def normalize_operation_scope(raw_scope: Any, *, upload_mode: Any) -> OperationScope:
    default_scope = default_operation_scope(upload_mode)
    scope_payload = dict(raw_scope) if isinstance(raw_scope, dict) else {}
    return {
        "create": bool(scope_payload.get("create", default_scope["create"])),
        "update": bool(scope_payload.get("update", default_scope["update"])),
    }


def scope_applies_to_operation(raw_scope: Any, operation: Any, *, upload_mode: Any) -> bool:
    scope = normalize_operation_scope(raw_scope, upload_mode=upload_mode)
    if str(operation or UPLOAD_MODE_CREATE).strip().lower() == UPLOAD_MODE_UPDATE:
        return scope["update"]
    return scope["create"]


def scope_applies_to_upload_mode(raw_scope: Any, upload_mode: Any) -> bool:
    normalized_mode = normalize_upload_mode(upload_mode)
    scope = normalize_operation_scope(raw_scope, upload_mode=upload_mode)
    if normalized_mode == UPLOAD_MODE_UPDATE:
        return scope["update"]
    if normalized_mode == UPLOAD_MODE_UPSERT:
        return scope["create"] or scope["update"]
    return scope["create"]


def normalize_all_or_none_operation_scope(raw_scope: Any, *, upload_mode: Any) -> OperationScope:
    default_scope = default_operation_scope(upload_mode)
    if not isinstance(raw_scope, dict) or not raw_scope:
        return default_scope
    if scope_applies_to_upload_mode(raw_scope, upload_mode=upload_mode):
        return default_scope
    return {"create": False, "update": False}
