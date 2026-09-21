from __future__ import annotations

import json
import threading
from collections.abc import Callable
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.codebeamer_client import CodebeamerClient

from .service_core import _build_gui_client
from .tracker_item_editor import EditableTrackerField
from .tracker_item_editor import EditableTrackerSchema
from .tracker_item_editor import FieldEditorKind
from .tracker_item_editor import TrackerItemFieldChange
from .tracker_item_editor import TrackerItemWriteError
from .tracker_item_editor import TrackerItemWriteErrorKind
from .tracker_item_editor import build_field_value
from .tracker_item_editor import classify_tracker_item_write_error


BULK_UPDATE_RUNS_FILE_NAME = "bulk_update_runs.json"
BULK_UPDATE_RUNS_VERSION = 1
DEFAULT_BULK_UPDATE_CHUNK_SIZE = 1000
DEFAULT_BULK_UPDATE_RUN_LIMIT = 100


@dataclass(frozen=True)
class BulkFieldChange:
    field: EditableTrackerField
    value: Any = None
    clear: bool = False


@dataclass(frozen=True)
class BulkUpdateFailure:
    item_id: int
    message: str = ""


@dataclass(frozen=True)
class BulkUpdateChunkResult:
    item_ids: tuple[int, ...]
    successful_item_ids: tuple[int, ...] = ()
    failures: tuple[BulkUpdateFailure, ...] = ()
    rolled_back_item_ids: tuple[int, ...] = ()
    atomic: bool = True

    @property
    def failed_item_ids(self) -> tuple[int, ...]:
        return tuple(failure.item_id for failure in self.failures)


@dataclass(frozen=True)
class BulkUpdateRunResult:
    run_id: str
    tracker_id: int
    target_item_ids: tuple[int, ...]
    field_ids: tuple[int, ...]
    clear_field_ids: tuple[int, ...]
    chunks: tuple[BulkUpdateChunkResult, ...]
    atomic: bool
    chunk_size: int
    cancelled: bool = False
    unattempted_item_ids: tuple[int, ...] = ()

    @property
    def successful_item_ids(self) -> tuple[int, ...]:
        return tuple(
            item_id
            for chunk in self.chunks
            for item_id in chunk.successful_item_ids
        )

    @property
    def failed_item_ids(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                item_id
                for chunk in self.chunks
                for item_id in chunk.failed_item_ids
            )
        )

    @property
    def rolled_back_item_ids(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                item_id
                for chunk in self.chunks
                for item_id in chunk.rolled_back_item_ids
            )
        )

    @property
    def retry_item_ids(self) -> tuple[int, ...]:
        values = [
            *self.failed_item_ids,
            *self.rolled_back_item_ids,
            *self.unattempted_item_ids,
        ]
        return tuple(dict.fromkeys(values))


def _clear_field_value(field_value: EditableTrackerField) -> dict[str, Any]:
    if field_value.mandatory or field_value.is_status:
        raise ValueError(f"'{field_value.label}' 필드는 값 비우기를 사용할 수 없습니다.")
    payload: dict[str, Any] = {
        "fieldId": field_value.field_id,
        "name": field_value.name,
        "type": str(field_value.value_model or "FieldValue").split("<", 1)[0],
    }
    if field_value.editor_kind in {
        FieldEditorKind.CHOICE,
        FieldEditorKind.REFERENCE,
        FieldEditorKind.TABLE,
    }:
        payload["values"] = []
    elif field_value.editor_kind in {
        FieldEditorKind.INTEGER,
        FieldEditorKind.DECIMAL,
        FieldEditorKind.BOOLEAN,
        FieldEditorKind.DATE,
        FieldEditorKind.DATETIME,
    }:
        payload["value"] = None
    elif field_value.editor_kind in {
        FieldEditorKind.TEXT,
        FieldEditorKind.MULTILINE_TEXT,
    }:
        payload["value"] = ""
    else:
        raise ValueError(f"'{field_value.label}' 필드는 값 비우기를 지원하지 않습니다.")
    return payload


def build_bulk_field_values(
    schema: EditableTrackerSchema,
    changes: Iterable[BulkFieldChange],
) -> list[dict[str, Any]]:
    normalized = tuple(changes)
    if not normalized:
        raise ValueError("Bulk 수정할 필드를 하나 이상 선택하세요.")
    schema_fields = {value.field_id: value for value in schema.fields}
    field_ids = [change.field.field_id for change in normalized]
    if len(field_ids) != len(set(field_ids)):
        raise ValueError("같은 필드가 Bulk 수정 목록에 중복되어 있습니다.")
    payload: list[dict[str, Any]] = []
    for change in normalized:
        canonical = schema_fields.get(change.field.field_id)
        if canonical is None:
            raise ValueError("현재 트래커 schema에 없는 필드가 포함되었습니다.")
        if canonical.editor_kind == FieldEditorKind.UNSUPPORTED:
            raise ValueError(
                canonical.unsupported_reason
                or f"'{canonical.label}' 필드는 Bulk 수정할 수 없습니다."
            )
        if change.clear:
            payload.append(_clear_field_value(canonical))
        else:
            payload.append(
                build_field_value(TrackerItemFieldChange(canonical, change.value))
            )
    return payload


def _failure_payload(exc: Exception) -> dict[str, Any] | None:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        response = getattr(current, "response", None)
        if response is not None:
            try:
                payload = response.json()
            except (AttributeError, ValueError):
                payload = None
            if isinstance(payload, dict):
                return payload
        current = current.__cause__ or current.__context__
    return None


def _normalized_failures(payload: Any) -> tuple[BulkUpdateFailure, ...]:
    raw_failures = payload.get("failedOperations") if isinstance(payload, dict) else None
    if not isinstance(raw_failures, list):
        return ()
    failures: list[BulkUpdateFailure] = []
    for raw_value in raw_failures:
        if not isinstance(raw_value, dict):
            continue
        raw_id: Any = raw_value.get("id") or raw_value.get("itemId")
        try:
            item_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        failures.append(
            BulkUpdateFailure(
                item_id=item_id,
                message=str(raw_value.get("exceptionMessage") or "")[:500],
            )
        )
    return tuple(failures)


class TrackerBulkUpdateService:
    def __init__(self, client_factory=CodebeamerClient, logger=None) -> None:
        self.client_factory = client_factory
        self.logger = logger

    def _client(self, settings):
        return _build_gui_client(settings, self.client_factory, self.logger)

    def _execute_chunk(
        self,
        client: Any,
        item_ids: tuple[int, ...],
        field_values: list[dict[str, Any]],
        *,
        atomic: bool,
    ) -> BulkUpdateChunkResult:
        operations = [
            {
                "itemId": item_id,
                "fieldValues": deepcopy(field_values),
            }
            for item_id in item_ids
        ]
        try:
            response = client.bulk_update_item_fields(operations, atomic=atomic)
        except Exception as exc:
            payload = _failure_payload(exc)
            failures = _normalized_failures(payload)
            if failures:
                failed_ids = {failure.item_id for failure in failures}
                return BulkUpdateChunkResult(
                    item_ids=item_ids,
                    failures=failures,
                    rolled_back_item_ids=(
                        tuple(item_id for item_id in item_ids if item_id not in failed_ids)
                        if atomic
                        else ()
                    ),
                    atomic=atomic,
                )
            kind, status_code = classify_tracker_item_write_error(exc)
            raise TrackerItemWriteError(
                kind,
                "Bulk 수정 요청을 처리하지 못했습니다.",
                status_code=status_code,
                operation="bulk_update_item_fields",
            ) from exc

        failures = _normalized_failures(response)
        failed_ids = {failure.item_id for failure in failures}
        if atomic and failures:
            successful_ids: tuple[int, ...] = ()
            rolled_back_ids = tuple(
                item_id for item_id in item_ids if item_id not in failed_ids
            )
        else:
            successful_ids = tuple(
                item_id for item_id in item_ids if item_id not in failed_ids
            )
            rolled_back_ids = ()
        return BulkUpdateChunkResult(
            item_ids=item_ids,
            successful_item_ids=successful_ids,
            failures=failures,
            rolled_back_item_ids=rolled_back_ids,
            atomic=atomic,
        )

    def execute(
        self,
        settings,
        *,
        tracker_id: int,
        item_ids: Iterable[int],
        schema: EditableTrackerSchema,
        changes: Iterable[BulkFieldChange],
        atomic: bool = True,
        chunk_size: int = DEFAULT_BULK_UPDATE_CHUNK_SIZE,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> BulkUpdateRunResult:
        if bool(getattr(settings, "offline_mode", False)):
            raise TrackerItemWriteError(
                TrackerItemWriteErrorKind.WRITE_DISABLED,
                "테스트 모드에서는 Bulk 수정할 수 없습니다.",
                operation="bulk_update_guard",
            )
        normalized_tracker_id = int(tracker_id)
        if schema.tracker_id != normalized_tracker_id:
            raise ValueError("불러온 schema와 Bulk 수정 대상 트래커가 일치하지 않습니다.")
        normalized_ids = tuple(
            dict.fromkeys(int(value) for value in item_ids if int(value) > 0)
        )
        if not normalized_ids:
            raise ValueError("Bulk 수정할 아이템이 없습니다.")
        normalized_chunk_size = int(chunk_size)
        if normalized_chunk_size <= 0:
            raise ValueError("청크 크기는 양의 정수여야 합니다.")
        normalized_changes = tuple(changes)
        field_values = build_bulk_field_values(schema, normalized_changes)
        client = self._client(settings)
        chunks: list[BulkUpdateChunkResult] = []
        completed = 0
        cancelled = False
        for start in range(0, len(normalized_ids), normalized_chunk_size):
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                break
            chunk_ids = normalized_ids[start : start + normalized_chunk_size]
            result = self._execute_chunk(
                client,
                chunk_ids,
                field_values,
                atomic=bool(atomic),
            )
            chunks.append(result)
            completed += len(chunk_ids)
            if event_callback is not None:
                event_callback(
                    {
                        "completed": completed,
                        "total": len(normalized_ids),
                        "chunk": len(chunks),
                        "successful": len(result.successful_item_ids),
                        "failed": len(result.failures),
                        "rolled_back": len(result.rolled_back_item_ids),
                    }
                )
        unattempted = normalized_ids[completed:]
        return BulkUpdateRunResult(
            run_id=uuid4().hex,
            tracker_id=normalized_tracker_id,
            target_item_ids=normalized_ids,
            field_ids=tuple(change.field.field_id for change in normalized_changes),
            clear_field_ids=tuple(
                change.field.field_id for change in normalized_changes if change.clear
            ),
            chunks=tuple(chunks),
            atomic=bool(atomic),
            chunk_size=normalized_chunk_size,
            cancelled=cancelled,
            unattempted_item_ids=unattempted,
        )


@dataclass(frozen=True)
class BulkUpdateRunRecord:
    run_id: str
    occurred_at: str
    tracker_id: int
    target_item_ids: tuple[int, ...]
    field_ids: tuple[int, ...]
    clear_field_ids: tuple[int, ...]
    successful_item_ids: tuple[int, ...]
    failed_item_ids: tuple[int, ...]
    rolled_back_item_ids: tuple[int, ...]
    unattempted_item_ids: tuple[int, ...]
    atomic: bool
    chunk_size: int
    cancelled: bool

    @classmethod
    def from_result(cls, result: BulkUpdateRunResult) -> BulkUpdateRunRecord:
        return cls(
            run_id=result.run_id,
            occurred_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            tracker_id=result.tracker_id,
            target_item_ids=result.target_item_ids,
            field_ids=result.field_ids,
            clear_field_ids=result.clear_field_ids,
            successful_item_ids=result.successful_item_ids,
            failed_item_ids=result.failed_item_ids,
            rolled_back_item_ids=result.rolled_back_item_ids,
            unattempted_item_ids=result.unattempted_item_ids,
            atomic=result.atomic,
            chunk_size=result.chunk_size,
            cancelled=result.cancelled,
        )

    @property
    def retry_item_ids(self) -> tuple[int, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *self.failed_item_ids,
                    *self.rolled_back_item_ids,
                    *self.unattempted_item_ids,
                ]
            )
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "occurredAt": self.occurred_at,
            "trackerId": self.tracker_id,
            "targetItemIds": list(self.target_item_ids),
            "fieldIds": list(self.field_ids),
            "clearFieldIds": list(self.clear_field_ids),
            "successfulItemIds": list(self.successful_item_ids),
            "failedItemIds": list(self.failed_item_ids),
            "rolledBackItemIds": list(self.rolled_back_item_ids),
            "unattemptedItemIds": list(self.unattempted_item_ids),
            "atomic": self.atomic,
            "chunkSize": self.chunk_size,
            "cancelled": self.cancelled,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BulkUpdateRunRecord:
        def ids(key: str) -> tuple[int, ...]:
            values = payload.get(key)
            if not isinstance(values, list):
                return ()
            return tuple(dict.fromkeys(int(value) for value in values if int(value) > 0))

        return cls(
            run_id=str(payload.get("runId") or ""),
            occurred_at=str(payload.get("occurredAt") or ""),
            tracker_id=int(payload.get("trackerId") or 0),
            target_item_ids=ids("targetItemIds"),
            field_ids=ids("fieldIds"),
            clear_field_ids=ids("clearFieldIds"),
            successful_item_ids=ids("successfulItemIds"),
            failed_item_ids=ids("failedItemIds"),
            rolled_back_item_ids=ids("rolledBackItemIds"),
            unattempted_item_ids=ids("unattemptedItemIds"),
            atomic=bool(payload.get("atomic", True)),
            chunk_size=max(int(payload.get("chunkSize") or 1), 1),
            cancelled=bool(payload.get("cancelled", False)),
        )


class BulkUpdateRunStore:
    def __init__(
        self,
        path: str | Path,
        *,
        max_records: int = DEFAULT_BULK_UPDATE_RUN_LIMIT,
    ) -> None:
        self.path = Path(path)
        self.max_records = max(int(max_records), 1)
        self._lock = threading.RLock()

    def load(self) -> tuple[BulkUpdateRunRecord, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return ()
            raw_records = payload.get("records") if isinstance(payload, dict) else None
            if not isinstance(raw_records, list):
                return ()
            records: list[BulkUpdateRunRecord] = []
            for value in raw_records:
                if not isinstance(value, dict):
                    continue
                try:
                    record = BulkUpdateRunRecord.from_payload(value)
                except (TypeError, ValueError):
                    continue
                if record.run_id and record.tracker_id > 0:
                    records.append(record)
                if len(records) >= self.max_records:
                    break
            return tuple(records)

    def get(self, run_id: str) -> BulkUpdateRunRecord | None:
        return next(
            (record for record in self.load() if record.run_id == str(run_id)),
            None,
        )

    def append(self, result: BulkUpdateRunResult) -> BulkUpdateRunRecord:
        record = BulkUpdateRunRecord.from_result(result)
        with self._lock:
            records = [value for value in self.load() if value.run_id != record.run_id]
            records = [record, *records][: self.max_records]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "version": BULK_UPDATE_RUNS_VERSION,
                        "records": [value.to_payload() for value in records],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        return record


def default_bulk_update_runs_path(root_dir: str | Path) -> Path:
    return Path(root_dir) / BULK_UPDATE_RUNS_FILE_NAME


__all__ = [
    "BULK_UPDATE_RUNS_FILE_NAME",
    "DEFAULT_BULK_UPDATE_CHUNK_SIZE",
    "BulkFieldChange",
    "BulkUpdateChunkResult",
    "BulkUpdateFailure",
    "BulkUpdateRunRecord",
    "BulkUpdateRunResult",
    "BulkUpdateRunStore",
    "TrackerBulkUpdateService",
    "build_bulk_field_values",
    "default_bulk_update_runs_path",
]
