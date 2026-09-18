from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from .diagnostics import current_operation_id


API_MONITOR_MAX_EVENTS = 500
API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS = 1000
API_MONITOR_MIN_SLOW_THRESHOLD_MS = 100
API_MONITOR_MAX_SLOW_THRESHOLD_MS = 60_000

API_OUTCOME_SUCCESS = "success"
API_OUTCOME_FAILED = "failed"
API_OUTCOME_RETRY = "retry"
API_OUTCOMES = {
    API_OUTCOME_SUCCESS,
    API_OUTCOME_FAILED,
    API_OUTCOME_RETRY,
}

_UUID_SEGMENT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_HEX_IDENTIFIER_SEGMENT = re.compile(r"^[0-9a-fA-F]{8,}$")
_NUMERIC_SEGMENT = re.compile(r"^-?\d+$")


def normalize_api_path(path: object) -> str:
    """Remove query data and replace identifier-like path segments."""

    raw_path = urlsplit(str(path or "")).path
    if not raw_path:
        return "/"
    segments = []
    for segment in raw_path.split("/"):
        if (
            _NUMERIC_SEGMENT.fullmatch(segment)
            or _UUID_SEGMENT.fullmatch(segment)
            or _HEX_IDENTIFIER_SEGMENT.fullmatch(segment)
        ):
            segments.append("{id}")
        else:
            segments.append(segment)
    normalized = "/".join(segments)
    return normalized if normalized.startswith("/") else f"/{normalized}"


@dataclass(frozen=True)
class ApiRequestEvent:
    sequence: int
    started_at: float
    request_kind: str
    method: str
    path: str
    status_code: int | None
    elapsed_ms: float
    outcome: str
    attempt: int
    max_attempts: int
    error_kind: str | None = None
    operation_id: str = ""


@dataclass(frozen=True)
class ApiMonitorStats:
    total: int
    active: int
    success: int
    failed: int
    retries: int
    rate_limited: int
    slow: int
    requests_last_minute: int
    success_rate: float
    average_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True)
class ApiMonitorSnapshot:
    enabled: bool
    slow_threshold_ms: int
    version: int
    events: tuple[ApiRequestEvent, ...]
    stats: ApiMonitorStats


@dataclass(frozen=True)
class _ActiveRequest:
    sequence: int
    started_at: float
    started_monotonic: float
    request_kind: str
    method: str
    path: str
    attempt: int
    max_attempts: int
    operation_id: str


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(math.ceil((percentile / 100.0) * len(ordered)) - 1, 0)
    return float(ordered[min(rank, len(ordered) - 1)])


class ApiMonitorService:
    """Thread-safe, metadata-only storage for recent Codebeamer API attempts."""

    def __init__(
        self,
        *,
        max_events: int = API_MONITOR_MAX_EVENTS,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._lock = threading.RLock()
        self._events: deque[ApiRequestEvent] = deque(maxlen=max(int(max_events), 1))
        self._active: dict[int, _ActiveRequest] = {}
        self._enabled = False
        self._slow_threshold_ms = API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
        self._next_handle = 1
        self._next_sequence = 1
        self._version = 0
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def slow_threshold_ms(self) -> int:
        with self._lock:
            return self._slow_threshold_ms

    def configure(
        self,
        *,
        enabled: bool,
        slow_threshold_ms: int = API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS,
    ) -> None:
        threshold = min(
            max(int(slow_threshold_ms), API_MONITOR_MIN_SLOW_THRESHOLD_MS),
            API_MONITOR_MAX_SLOW_THRESHOLD_MS,
        )
        with self._lock:
            changed = self._enabled != bool(enabled) or self._slow_threshold_ms != threshold
            self._enabled = bool(enabled)
            self._slow_threshold_ms = threshold
            if changed:
                self._version += 1

    def reset(
        self,
        *,
        enabled: bool = False,
        slow_threshold_ms: int = API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS,
    ) -> None:
        threshold = min(
            max(int(slow_threshold_ms), API_MONITOR_MIN_SLOW_THRESHOLD_MS),
            API_MONITOR_MAX_SLOW_THRESHOLD_MS,
        )
        with self._lock:
            self._events.clear()
            self._active.clear()
            self._enabled = bool(enabled)
            self._slow_threshold_ms = threshold
            self._next_handle = 1
            self._next_sequence = 1
            self._version += 1

    def clear(self) -> None:
        with self._lock:
            if self._events:
                self._events.clear()
                self._version += 1

    def start_request(
        self,
        *,
        request_kind: str,
        method: str,
        path: object,
        attempt: int = 1,
        max_attempts: int = 1,
        operation_id: str | None = None,
    ) -> int | None:
        with self._lock:
            if not self._enabled:
                return None
            handle = self._next_handle
            self._next_handle += 1
            sequence = self._next_sequence
            self._next_sequence += 1
            current_attempt = max(int(attempt), 1)
            total_attempts = max(int(max_attempts), current_attempt)
            self._active[handle] = _ActiveRequest(
                sequence=sequence,
                started_at=float(self._wall_clock()),
                started_monotonic=float(self._monotonic_clock()),
                request_kind=str(request_kind or "API 요청"),
                method=str(method or "").upper(),
                path=normalize_api_path(path),
                attempt=current_attempt,
                max_attempts=total_attempts,
                operation_id=str(
                    current_operation_id()
                    if operation_id is None
                    else operation_id
                ).strip()[:64],
            )
            self._version += 1
            return handle

    def finish_request(
        self,
        handle: int | None,
        *,
        status_code: int | None,
        outcome: str,
        error_kind: str | None = None,
    ) -> ApiRequestEvent | None:
        if handle is None:
            return None
        normalized_outcome = outcome if outcome in API_OUTCOMES else API_OUTCOME_FAILED
        with self._lock:
            active = self._active.pop(int(handle), None)
            if active is None:
                return None
            elapsed_ms = max(
                (float(self._monotonic_clock()) - active.started_monotonic) * 1000.0,
                0.0,
            )
            event = ApiRequestEvent(
                sequence=active.sequence,
                started_at=active.started_at,
                request_kind=active.request_kind,
                method=active.method,
                path=active.path,
                status_code=None if status_code is None else int(status_code),
                elapsed_ms=elapsed_ms,
                outcome=normalized_outcome,
                attempt=active.attempt,
                max_attempts=active.max_attempts,
                error_kind=str(error_kind) if error_kind else None,
                operation_id=active.operation_id,
            )
            self._events.append(event)
            self._version += 1
            return event

    def snapshot(self, *, now: float | None = None) -> ApiMonitorSnapshot:
        with self._lock:
            events = tuple(self._events)
            enabled = self._enabled
            threshold = self._slow_threshold_ms
            version = self._version
            active_count = len(self._active)
        current_time = float(self._wall_clock() if now is None else now)
        elapsed_values = [event.elapsed_ms for event in events]
        success = sum(event.outcome == API_OUTCOME_SUCCESS for event in events)
        failed = sum(event.outcome == API_OUTCOME_FAILED for event in events)
        retries = sum(event.outcome == API_OUTCOME_RETRY for event in events)
        total = len(events)
        stats = ApiMonitorStats(
            total=total,
            active=active_count,
            success=success,
            failed=failed,
            retries=retries,
            rate_limited=sum(event.status_code == 429 for event in events),
            slow=sum(event.elapsed_ms >= threshold for event in events),
            requests_last_minute=sum(event.started_at >= current_time - 60.0 for event in events),
            success_rate=(success / total * 100.0) if total else 0.0,
            average_ms=(sum(elapsed_values) / total) if total else 0.0,
            p50_ms=_percentile(elapsed_values, 50.0),
            p95_ms=_percentile(elapsed_values, 95.0),
            max_ms=max(elapsed_values, default=0.0),
        )
        return ApiMonitorSnapshot(
            enabled=enabled,
            slow_threshold_ms=threshold,
            version=version,
            events=events,
            stats=stats,
        )


API_MONITOR = ApiMonitorService()


__all__ = [
    "API_MONITOR",
    "API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS",
    "API_MONITOR_MAX_EVENTS",
    "API_MONITOR_MAX_SLOW_THRESHOLD_MS",
    "API_MONITOR_MIN_SLOW_THRESHOLD_MS",
    "API_OUTCOME_FAILED",
    "API_OUTCOME_RETRY",
    "API_OUTCOME_SUCCESS",
    "ApiMonitorService",
    "ApiMonitorSnapshot",
    "ApiMonitorStats",
    "ApiRequestEvent",
    "normalize_api_path",
]
