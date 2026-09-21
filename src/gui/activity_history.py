from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .payload_values import as_mapping


ACTIVITY_HISTORY_FILE_NAME = "activity_history.json"
ACTIVITY_HISTORY_VERSION = 1
DEFAULT_ACTIVITY_HISTORY_LIMIT = 500


class ActivityOperation(str, Enum):
    TRACKER_CREATE = "tracker_create"
    TRACKER_UPDATE = "tracker_update"
    STATUS_TRANSITION = "status_transition"
    TRACKER_DELETE = "tracker_delete"
    BULK_UPDATE = "bulk_update"
    BATCH_UPLOAD = "batch_upload"
    BASELINE_EXPORT = "baseline_export"
    TRACKER_HIERARCHY_EXPORT = "tracker_hierarchy_export"


class ActivityResult(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVITY_OPERATION_LABELS = {
    ActivityOperation.TRACKER_CREATE: "단건 생성",
    ActivityOperation.TRACKER_UPDATE: "필드 수정",
    ActivityOperation.STATUS_TRANSITION: "상태 필드 변경",
    ActivityOperation.TRACKER_DELETE: "아이템 삭제",
    ActivityOperation.BULK_UPDATE: "일괄 수정",
    ActivityOperation.BATCH_UPLOAD: "배치 작업",
    ActivityOperation.BASELINE_EXPORT: "Baseline Excel 내보내기",
    ActivityOperation.TRACKER_HIERARCHY_EXPORT: "트래커 계층 Excel 내보내기",
}

ACTIVITY_RESULT_LABELS = {
    ActivityResult.SUCCESS: "성공",
    ActivityResult.PARTIAL: "일부 실패",
    ActivityResult.FAILED: "실패",
    ActivityResult.CANCELLED: "중단",
}

_SENSITIVE_DETAIL_TOKENS = {
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "token",
}


class ActivityHistoryError(RuntimeError):
    pass


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _bounded_text(value: Any, *, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 0)]}…"


def _is_sensitive_detail_key(key: Any) -> bool:
    normalized = str(key or "").strip().casefold().replace("-", "_")
    return any(token in normalized for token in _SENSITIVE_DETAIL_TOKENS)


def sanitize_activity_details(value: Any, *, depth: int = 0) -> Any:
    """기록 파일에 저장 가능한 작은 비민감 payload로 제한한다."""
    if depth >= 4:
        return "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value, limit=500)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (raw_key, child) in enumerate(value.items()):
            if index >= 30:
                sanitized["__truncated__"] = True
                break
            key = _bounded_text(raw_key, limit=80)
            sanitized[key] = (
                "***"
                if _is_sensitive_detail_key(key)
                else sanitize_activity_details(child, depth=depth + 1)
            )
        return sanitized
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        sanitized_values = [
            sanitize_activity_details(child, depth=depth + 1)
            for child in values[:30]
        ]
        if len(values) > 30:
            sanitized_values.append("…")
        return sanitized_values
    return _bounded_text(value, limit=500)


@dataclass(frozen=True)
class ActivityRecord:
    record_id: str
    occurred_at: str
    operation: ActivityOperation
    result: ActivityResult
    source: str
    summary: str
    project_id: int | None = None
    project_name: str = ""
    tracker_id: int | None = None
    tracker_name: str = ""
    item_id: int | None = None
    item_name: str = ""
    parent_item_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def create(
        cls,
        operation: ActivityOperation,
        result: ActivityResult,
        *,
        source: str,
        summary: str,
        project_id: int | None = None,
        project_name: str = "",
        tracker_id: int | None = None,
        tracker_name: str = "",
        item_id: int | None = None,
        item_name: str = "",
        parent_item_id: int | None = None,
        details: dict[str, Any] | None = None,
        occurred_at: str | None = None,
        record_id: str | None = None,
    ) -> ActivityRecord:
        return cls(
            record_id=_bounded_text(record_id or uuid4().hex, limit=64),
            occurred_at=_bounded_text(
                occurred_at
                or datetime.now().astimezone().isoformat(timespec="seconds"),
                limit=64,
            ),
            operation=ActivityOperation(operation),
            result=ActivityResult(result),
            source=_bounded_text(source, limit=80),
            summary=_bounded_text(summary, limit=500),
            project_id=_optional_positive_int(project_id),
            project_name=_bounded_text(project_name, limit=200),
            tracker_id=_optional_positive_int(tracker_id),
            tracker_name=_bounded_text(tracker_name, limit=200),
            item_id=_optional_positive_int(item_id),
            item_name=_bounded_text(item_name, limit=300),
            parent_item_id=_optional_positive_int(parent_item_id),
            details=sanitize_activity_details(details or {}),
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ActivityRecord:
        if not isinstance(payload, dict):
            raise ValueError("실행 기록 항목은 객체여야 합니다.")
        return cls.create(
            ActivityOperation(payload.get("operation")),
            ActivityResult(payload.get("result")),
            source=str(payload.get("source") or ""),
            summary=str(payload.get("summary") or ""),
            project_id=payload.get("projectId"),
            project_name=str(payload.get("projectName") or ""),
            tracker_id=payload.get("trackerId"),
            tracker_name=str(payload.get("trackerName") or ""),
            item_id=payload.get("itemId"),
            item_name=str(payload.get("itemName") or ""),
            parent_item_id=payload.get("parentItemId"),
            details=(as_mapping(payload.get("details"))),
            occurred_at=str(payload.get("occurredAt") or ""),
            record_id=str(payload.get("recordId") or ""),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "recordId": self.record_id,
            "occurredAt": self.occurred_at,
            "operation": self.operation.value,
            "result": self.result.value,
            "source": self.source,
            "summary": self.summary,
            "projectId": self.project_id,
            "projectName": self.project_name,
            "trackerId": self.tracker_id,
            "trackerName": self.tracker_name,
            "itemId": self.item_id,
            "itemName": self.item_name,
            "parentItemId": self.parent_item_id,
            "details": sanitize_activity_details(self.details),
        }

    @property
    def operation_label(self) -> str:
        return ACTIVITY_OPERATION_LABELS[self.operation]

    @property
    def result_label(self) -> str:
        return ACTIVITY_RESULT_LABELS[self.result]

    @property
    def context_text(self) -> str:
        project = (
            f"{self.project_name} ({self.project_id})"
            if self.project_name and self.project_id is not None
            else self.project_name
            or (f"프로젝트 {self.project_id}" if self.project_id is not None else "")
        )
        tracker = (
            f"{self.tracker_name} ({self.tracker_id})"
            if self.tracker_name and self.tracker_id is not None
            else self.tracker_name
            or (f"트래커 {self.tracker_id}" if self.tracker_id is not None else "")
        )
        return " / ".join(value for value in (project, tracker) if value) or "-"

    @property
    def target_text(self) -> str:
        if self.item_id is not None:
            suffix = f" {self.item_name}" if self.item_name else ""
            return f"#{self.item_id}{suffix}"
        return self.item_name or "-"

    @property
    def searchable_text(self) -> str:
        return " ".join(
            (
                self.occurred_at,
                self.operation_label,
                self.result_label,
                str(self.project_id or ""),
                str(self.tracker_id or ""),
                str(self.item_id or ""),
                self.context_text,
                self.target_text,
                self.summary,
            )
        ).casefold()


class ActivityHistoryStore:
    """민감정보를 제외한 최근 실행 결과를 원자적으로 저장한다."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_records: int = DEFAULT_ACTIVITY_HISTORY_LIMIT,
    ) -> None:
        self.path = Path(path)
        self.max_records = max(int(max_records), 1)
        self._lock = threading.RLock()

    def load(self) -> tuple[ActivityRecord, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ActivityHistoryError(
                    "실행 기록 파일을 읽지 못했습니다. 파일 형식을 확인하세요."
                ) from exc
            raw_records = payload.get("records") if isinstance(payload, dict) else None
            if not isinstance(raw_records, list):
                raise ActivityHistoryError(
                    "실행 기록 파일의 records 목록이 올바르지 않습니다."
                )
            records: list[ActivityRecord] = []
            for raw_record in raw_records:
                try:
                    records.append(ActivityRecord.from_payload(raw_record))
                except (TypeError, ValueError):
                    continue
                if len(records) >= self.max_records:
                    break
            return tuple(records)

    def append(self, record: ActivityRecord) -> tuple[ActivityRecord, ...]:
        if not isinstance(record, ActivityRecord):
            raise TypeError("ActivityRecord만 실행 기록에 저장할 수 있습니다.")
        with self._lock:
            existing = [
                value for value in self.load() if value.record_id != record.record_id
            ]
            records = tuple([record, *existing][: self.max_records])
            self._write(records)
            return records

    def clear(self) -> None:
        with self._lock:
            self._write(())

    def _write(self, records: tuple[ActivityRecord, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        payload = {
            "version": ACTIVITY_HISTORY_VERSION,
            "records": [record.to_payload() for record in records],
        }
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except Exception as exc:
            raise ActivityHistoryError("실행 기록 파일을 저장하지 못했습니다.") from exc


def default_activity_history_path(root_dir: str | Path) -> Path:
    return Path(root_dir) / ACTIVITY_HISTORY_FILE_NAME


__all__ = [
    "ACTIVITY_HISTORY_FILE_NAME",
    "ACTIVITY_HISTORY_VERSION",
    "ACTIVITY_OPERATION_LABELS",
    "ACTIVITY_RESULT_LABELS",
    "DEFAULT_ACTIVITY_HISTORY_LIMIT",
    "ActivityHistoryError",
    "ActivityHistoryStore",
    "ActivityOperation",
    "ActivityRecord",
    "ActivityResult",
    "default_activity_history_path",
    "sanitize_activity_details",
]
