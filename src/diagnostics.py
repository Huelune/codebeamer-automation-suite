from __future__ import annotations

import hashlib
import json
import platform
import re
import threading
import time
import traceback as traceback_module
import zipfile
from collections import deque
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from importlib import metadata
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


DEFAULT_DIAGNOSTIC_EVENT_LIMIT = 2_000
DIAGNOSTIC_BUNDLE_VERSION = 1

_CURRENT_OPERATION_ID: ContextVar[str] = ContextVar(
    "codebeamer_diagnostic_operation_id",
    default="",
)
_SENSITIVE_KEY_TOKENS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "passwd",
    "private_key",
    "secret",
    "session",
    "token",
    "username",
}
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?ix)"
    r"(?P<quote>['\"]?)"
    r"(?P<key>"
    r"password|passwd|username|authorization|proxy[-_]?authorization|"
    r"cookie|set[-_]?cookie|credential|secret(?:[-_]?key)?|private[-_]?key|"
    r"session(?:id)?|"
    r"api[-_]?key|x[-_]?api[-_]?key|"
    r"access[-_]?token|refresh[-_]?token|client[-_]?secret|token"
    r")"
    r"(?P=quote)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<value>"
    r"(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]+|"
    r"\"(?:\\.|[^\"\\])*\"|"
    r"'(?:\\.|[^'\\])*'|"
    r"[^\s,;}\]]+"
    r")"
)
_SENSITIVE_HEADER_RE = re.compile(
    r"(?im)^\s*(?P<key>Authorization|Proxy-Authorization|Cookie|Set-Cookie|X-Api-Key)"
    r"(?P<separator>\s*:\s*)[^\r\n]+"
)
_AUTH_VALUE_RE = re.compile(r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]+")
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>'\"]+")
_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?P<quote>['\"])(?:[A-Z]:[\\/]|\\\\[^\\/\r\n]+[\\/]|/)"
    r"[^'\"\r\n]+(?P=quote)"
)
_WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![\w])(?:[A-Z]:[\\/]|\\\\[^\\/\s]+[\\/])"
    r"[^\s,;\"'<>|]+"
)
_POSIX_PATH_RE = re.compile(
    r"(?<![\w.])/(?:Users|home|private|var|tmp)/[^\s,;\"'<>|)\]}]+"
)
_GENERIC_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![\w.])/(?:[^/\s]+/)+[^\s,;\"'<>|)\]}]+"
)
_IDENTIFIER_PATH_SEGMENT_RE = re.compile(
    r"^(?:-?\d+|[0-9a-fA-F]{8,}|"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,})$"
)
_ALLOWED_ACTIVITY_DETAIL_KEYS = {
    "atomic",
    "chunk_size",
    "dry_run",
    "duration_seconds",
    "failed_count",
    "file_count",
    "long_value_count",
    "rolled_back_count",
    "row_count",
    "split_row_count",
    "success_count",
    "target_count",
    "unattempted_count",
    "unresolved_count",
    "upload_mode",
}
_ALLOWED_DIAGNOSTIC_DETAIL_KEYS = _ALLOWED_ACTIVITY_DETAIL_KEYS | {
    "activity_count",
    "api_event_count",
    "diagnostic_count",
    "error_type",
    "offline_mode",
    "outcome",
}


class DiagnosticLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DiagnosticSource(str, Enum):
    APPLICATION = "application"
    SETTINGS = "settings"
    TRACKER = "tracker"
    BASELINE = "baseline"
    EXCEL = "excel"
    UPLOAD = "upload"


@dataclass(frozen=True)
class DiagnosticFrame:
    file: str
    line: int
    function: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "function": self.function,
        }


@dataclass(frozen=True)
class DiagnosticEvent:
    sequence: int
    occurred_at: str
    level: DiagnosticLevel
    source: DiagnosticSource
    event_kind: str
    message: str
    operation_id: str
    thread_name: str
    elapsed_ms: float | None
    details: dict[str, Any]
    exception_type: str = ""
    traceback_frames: tuple[DiagnosticFrame, ...] = ()

    @property
    def short_operation_id(self) -> str:
        return self.operation_id[:8] if self.operation_id else "-"

    @property
    def searchable_text(self) -> str:
        return " ".join(
            (
                self.occurred_at,
                self.level.value,
                self.source.value,
                self.event_kind,
                self.message,
                self.operation_id,
                self.exception_type,
            )
        ).casefold()

    def to_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "occurredAt": self.occurred_at,
            "level": self.level.value,
            "source": self.source.value,
            "eventKind": self.event_kind,
            "message": self.message,
            "operationId": self.operation_id,
            "threadName": self.thread_name,
            "elapsedMs": self.elapsed_ms,
            "details": sanitize_diagnostic_value(self.details),
            "exceptionType": self.exception_type,
            "tracebackFrames": [frame.to_payload() for frame in self.traceback_frames],
        }


@dataclass(frozen=True)
class DiagnosticSnapshot:
    version: int
    events: tuple[DiagnosticEvent, ...]


@dataclass(frozen=True)
class DiagnosticBundleSummary:
    path: Path
    diagnostic_count: int
    api_event_count: int
    activity_count: int
    files: tuple[str, ...]


def current_operation_id() -> str:
    return _CURRENT_OPERATION_ID.get()


def new_operation_id() -> str:
    return uuid4().hex


@contextmanager
def operation_context(operation_id: str) -> Iterator[str]:
    normalized = str(operation_id or "").strip()
    token = _CURRENT_OPERATION_ID.set(normalized)
    try:
        yield normalized
    finally:
        _CURRENT_OPERATION_ID.reset(token)


def _bounded_text(value: Any, *, limit: int = 1_000) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 0)].rstrip()}…"


def sanitize_diagnostic_text(value: Any, *, limit: int = 1_000) -> str:
    text = _bounded_text(value, limit=max(limit * 2, limit))
    text = _SENSITIVE_HEADER_RE.sub(r"\g<key>\g<separator>***", text)
    text = _AUTH_VALUE_RE.sub("<AUTH>", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: (
            f"{match.group('quote')}{match.group('key')}{match.group('quote')}"
            f'{match.group("separator")}"***"'
        ),
        text,
    )
    text = _EMAIL_RE.sub("<EMAIL>", text)
    text = _URL_RE.sub("<URL>", text)
    text = _QUOTED_ABSOLUTE_PATH_RE.sub(
        lambda match: f"{match.group('quote')}<PATH>{match.group('quote')}",
        text,
    )
    text = _WINDOWS_PATH_RE.sub("<PATH>", text)
    text = _POSIX_PATH_RE.sub("<PATH>", text)
    text = _GENERIC_ABSOLUTE_PATH_RE.sub("<PATH>", text)
    return _bounded_text(text, limit=limit)


def _is_sensitive_key(value: Any) -> bool:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def sanitize_diagnostic_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_diagnostic_text(value, limit=500)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (raw_key, child) in enumerate(value.items()):
            if index >= 30:
                sanitized["__truncated__"] = True
                break
            key = sanitize_diagnostic_text(raw_key, limit=80)
            sanitized[key] = (
                "***"
                if _is_sensitive_key(key)
                else sanitize_diagnostic_value(child, depth=depth + 1)
            )
        return sanitized
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        sanitized_items = [
            sanitize_diagnostic_value(child, depth=depth + 1)
            for child in values[:30]
        ]
        if len(values) > 30:
            sanitized_items.append("…")
        return sanitized_items
    return sanitize_diagnostic_text(value, limit=500)


def _safe_frame_path(value: str) -> str:
    try:
        resolved = Path(value).resolve()
        workspace = Path.cwd().resolve()
        relative = resolved.relative_to(workspace)
    except (OSError, ValueError):
        return Path(str(value or "unknown")).name or "unknown"
    return f"<APP>/{relative.as_posix()}"


def _extract_traceback_frames(
    traceback: TracebackType | None,
) -> tuple[DiagnosticFrame, ...]:
    if traceback is None:
        return ()
    return tuple(
        DiagnosticFrame(
            file=_safe_frame_path(frame.filename),
            line=max(int(frame.lineno or 0), 0),
            function=sanitize_diagnostic_text(frame.name, limit=120),
        )
        for frame in traceback_module.extract_tb(traceback)[-30:]
    )


class DiagnosticService:
    """Thread-safe, session-only storage for privacy-bounded diagnostic events."""

    def __init__(
        self,
        *,
        max_events: int = DEFAULT_DIAGNOSTIC_EVENT_LIMIT,
        wall_clock=time.time,
        monotonic_clock=time.perf_counter,
    ) -> None:
        self._lock = threading.RLock()
        self._events: deque[DiagnosticEvent] = deque(
            maxlen=max(int(max_events), 1)
        )
        self._active: dict[str, float] = {}
        self._next_sequence = 1
        self._version = 0
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock

    def clear(self) -> None:
        with self._lock:
            if self._events:
                self._events.clear()
                self._version += 1

    def snapshot(self) -> DiagnosticSnapshot:
        with self._lock:
            return DiagnosticSnapshot(
                version=self._version,
                events=tuple(self._events),
            )

    def record(
        self,
        *,
        level: DiagnosticLevel | str,
        source: DiagnosticSource | str,
        event_kind: str,
        message: str,
        operation_id: str | None = None,
        elapsed_ms: float | None = None,
        details: dict[str, Any] | None = None,
        exception_type: str = "",
        traceback_frames: Iterable[DiagnosticFrame] = (),
    ) -> DiagnosticEvent:
        normalized_operation_id = str(
            current_operation_id() if operation_id is None else operation_id
        ).strip()
        occurred_at = datetime.fromtimestamp(
            float(self._wall_clock())
        ).astimezone().isoformat(timespec="milliseconds")
        with self._lock:
            event = DiagnosticEvent(
                sequence=self._next_sequence,
                occurred_at=occurred_at,
                level=DiagnosticLevel(level),
                source=DiagnosticSource(source),
                event_kind=sanitize_diagnostic_text(event_kind, limit=100),
                message=sanitize_diagnostic_text(message, limit=1_000),
                operation_id=sanitize_diagnostic_text(
                    normalized_operation_id,
                    limit=64,
                ),
                thread_name=sanitize_diagnostic_text(
                    threading.current_thread().name,
                    limit=100,
                ),
                elapsed_ms=(
                    None if elapsed_ms is None else max(float(elapsed_ms), 0.0)
                ),
                details=(
                    sanitize_diagnostic_value(details or {})
                    if isinstance(details or {}, dict)
                    else {}
                ),
                exception_type=sanitize_diagnostic_text(exception_type, limit=120),
                traceback_frames=tuple(
                    DiagnosticFrame(
                        file=sanitize_diagnostic_text(frame.file, limit=300),
                        line=max(int(frame.line), 0),
                        function=sanitize_diagnostic_text(frame.function, limit=120),
                    )
                    for frame in tuple(traceback_frames)[:30]
                ),
            )
            self._next_sequence += 1
            self._events.append(event)
            self._version += 1
            return event

    def start_operation(
        self,
        *,
        source: DiagnosticSource | str,
        event_kind: str,
        message: str,
        operation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        normalized_id = str(operation_id or new_operation_id()).strip()
        with self._lock:
            self._active[normalized_id] = float(self._monotonic_clock())
        self.record(
            level=DiagnosticLevel.INFO,
            source=source,
            event_kind=f"{event_kind}_started",
            message=message,
            operation_id=normalized_id,
            details=details,
        )
        return normalized_id

    def finish_operation(
        self,
        operation_id: str,
        *,
        source: DiagnosticSource | str,
        event_kind: str,
        message: str,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
    ) -> DiagnosticEvent:
        normalized_id = str(operation_id or "").strip()
        with self._lock:
            started = self._active.pop(normalized_id, None)
        elapsed_ms = (
            None
            if started is None
            else max((float(self._monotonic_clock()) - started) * 1_000.0, 0.0)
        )
        normalized_outcome = str(outcome or "success").strip().casefold()
        level = (
            DiagnosticLevel.ERROR
            if normalized_outcome == "failed"
            else DiagnosticLevel.WARNING
            if normalized_outcome in {"partial", "cancelled"}
            else DiagnosticLevel.INFO
        )
        payload_details = {"outcome": normalized_outcome}
        payload_details.update(details or {})
        return self.record(
            level=level,
            source=source,
            event_kind=f"{event_kind}_finished",
            message=message,
            operation_id=normalized_id,
            elapsed_ms=elapsed_ms,
            details=payload_details,
        )

    def record_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
        thread_name: str,
        *,
        operation_id: str | None = None,
    ) -> DiagnosticEvent:
        normalized_id = str(
            operation_id or current_operation_id() or new_operation_id()
        ).strip()
        return self.record(
            level=DiagnosticLevel.CRITICAL,
            source=DiagnosticSource.APPLICATION,
            event_kind="unhandled_exception",
            message="예상하지 못한 오류가 발생했습니다.",
            operation_id=normalized_id,
            details={"thread": thread_name},
            exception_type=getattr(exc_type, "__name__", "Exception"),
            traceback_frames=_extract_traceback_frames(traceback),
        )


def _json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        sort_keys=True,
    ).encode("utf-8")


def _ndjson_bytes(values: Iterable[dict[str, Any]]) -> bytes:
    lines = [
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in values
    ]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _safe_api_event_payload(event: Any) -> dict[str, Any]:
    raw_path = urlsplit(str(getattr(event, "path", "") or "")).path
    normalized_segments = [
        "{id}" if _IDENTIFIER_PATH_SEGMENT_RE.fullmatch(segment) else segment
        for segment in raw_path.split("/")
    ]
    safe_path = "/".join(normalized_segments) or "/"
    return {
        "sequence": int(getattr(event, "sequence", 0) or 0),
        "startedAt": float(getattr(event, "started_at", 0.0) or 0.0),
        "requestKind": sanitize_diagnostic_text(
            getattr(event, "request_kind", ""), limit=120
        ),
        "method": sanitize_diagnostic_text(getattr(event, "method", ""), limit=12),
        "path": _bounded_text(safe_path, limit=300),
        "statusCode": getattr(event, "status_code", None),
        "elapsedMs": round(float(getattr(event, "elapsed_ms", 0.0) or 0.0), 3),
        "outcome": sanitize_diagnostic_text(getattr(event, "outcome", ""), limit=30),
        "attempt": int(getattr(event, "attempt", 1) or 1),
        "maxAttempts": int(getattr(event, "max_attempts", 1) or 1),
        "errorKind": sanitize_diagnostic_text(
            getattr(event, "error_kind", ""), limit=50
        ),
        "operationId": sanitize_diagnostic_text(
            getattr(event, "operation_id", ""), limit=64
        ),
    }


def _safe_activity_payload(record: Any) -> dict[str, Any]:
    details = getattr(record, "details", {})
    safe_details = {
        key: sanitize_diagnostic_value(value)
        for key, value in (details.items() if isinstance(details, dict) else ())
        if str(key) in _ALLOWED_ACTIVITY_DETAIL_KEYS
    }
    operation = getattr(record, "operation", "")
    result = getattr(record, "result", "")
    return {
        "occurredAt": sanitize_diagnostic_text(
            getattr(record, "occurred_at", ""), limit=64
        ),
        "operation": sanitize_diagnostic_text(
            getattr(operation, "value", operation), limit=80
        ),
        "result": sanitize_diagnostic_text(getattr(result, "value", result), limit=40),
        "source": sanitize_diagnostic_text(getattr(record, "source", ""), limit=80),
        "details": safe_details,
    }


def _safe_diagnostic_event_payload(event: DiagnosticEvent) -> dict[str, Any]:
    """진단 ZIP에는 원문 메시지 대신 상관관계용 메타데이터만 포함한다."""
    payload = event.to_payload()
    payload["message"] = (
        "오류 이벤트가 기록되었습니다."
        if event.level in {DiagnosticLevel.ERROR, DiagnosticLevel.CRITICAL}
        else "진단 이벤트가 기록되었습니다."
    )
    payload["details"] = {
        str(key): sanitize_diagnostic_value(value)
        for key, value in event.details.items()
        if str(key) in _ALLOWED_DIAGNOSTIC_DETAIL_KEYS
    }
    return payload


def _dependency_versions() -> dict[str, str]:
    values: dict[str, str] = {}
    for package in ("PySide6", "openpyxl", "pandas", "requests"):
        try:
            values[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            values[package] = "not-installed"
    return values


def export_diagnostic_bundle(
    path: str | Path,
    *,
    diagnostics_snapshot: DiagnosticSnapshot,
    api_events: Iterable[Any] = (),
    activity_records: Iterable[Any] = (),
    offline_mode: bool = False,
    app_version: str = "development",
    build_id: str = "unknown",
) -> DiagnosticBundleSummary:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_payloads = [
        _safe_diagnostic_event_payload(event)
        for event in diagnostics_snapshot.events
    ]
    api_payloads = [_safe_api_event_payload(event) for event in api_events]
    activity_payloads = [_safe_activity_payload(record) for record in activity_records]
    environment_payload = {
        "appVersion": sanitize_diagnostic_text(app_version, limit=80),
        "buildId": sanitize_diagnostic_text(build_id, limit=80),
        "mode": "test" if offline_mode else "online-or-unconfigured",
        "python": platform.python_version(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "dependencies": _dependency_versions(),
    }
    files: dict[str, bytes] = {
        "diagnostics.ndjson": _ndjson_bytes(diagnostic_payloads),
        "api-events.ndjson": _ndjson_bytes(api_payloads),
        "activity-summary.json": _json_bytes(activity_payloads),
        "environment.json": _json_bytes(environment_payload),
        "README.txt": (
            "Codebeamer Automation Suite diagnostic bundle\n\n"
            "이 패키지는 세션 진단 이벤트, API 메타데이터, 실행 결과 요약과 "
            "환경 버전만 포함합니다. 인증 정보, 서버 주소, 요청/응답 본문, query 값, "
            "Excel 셀 값과 원본 설정 파일은 포함하지 않습니다.\n"
        ).encode(),
    }
    manifest = {
        "schemaVersion": DIAGNOSTIC_BUNDLE_VERSION,
        "exportedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "counts": {
            "diagnostics": len(diagnostic_payloads),
            "apiEvents": len(api_payloads),
            "activities": len(activity_payloads),
        },
        "redactionPolicy": "safe-metadata-only",
        "files": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(files.items())
        },
    }
    files["manifest.json"] = _json_bytes(manifest)

    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        temporary.replace(target)
    except Exception:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise

    return DiagnosticBundleSummary(
        path=target,
        diagnostic_count=len(diagnostic_payloads),
        api_event_count=len(api_payloads),
        activity_count=len(activity_payloads),
        files=tuple(sorted(files)),
    )


DIAGNOSTICS = DiagnosticService()


__all__ = [
    "DEFAULT_DIAGNOSTIC_EVENT_LIMIT",
    "DIAGNOSTICS",
    "DIAGNOSTIC_BUNDLE_VERSION",
    "DiagnosticBundleSummary",
    "DiagnosticEvent",
    "DiagnosticFrame",
    "DiagnosticLevel",
    "DiagnosticService",
    "DiagnosticSnapshot",
    "DiagnosticSource",
    "current_operation_id",
    "export_diagnostic_bundle",
    "new_operation_id",
    "operation_context",
    "sanitize_diagnostic_text",
    "sanitize_diagnostic_value",
]
