from __future__ import annotations

import unittest
from dataclasses import fields

from src.api_monitor import API_OUTCOME_FAILED
from src.api_monitor import API_OUTCOME_RETRY
from src.api_monitor import API_OUTCOME_SUCCESS
from src.api_monitor import ApiMonitorService
from src.api_monitor import ApiRequestEvent
from src.api_monitor import normalize_api_path


class _Clock:
    def __init__(self, value: float = 1_700_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, milliseconds: float) -> None:
        self.value += milliseconds / 1000.0


class ApiMonitorServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wall_clock = _Clock()
        self.monotonic_clock = _Clock(100.0)
        self.monitor = ApiMonitorService(
            max_events=3,
            wall_clock=self.wall_clock,
            monotonic_clock=self.monotonic_clock,
        )
        self.monitor.configure(enabled=True, slow_threshold_ms=200)

    def _record(
        self,
        *,
        elapsed_ms: float,
        outcome: str = API_OUTCOME_SUCCESS,
        status_code: int | None = 200,
        attempt: int = 1,
        max_attempts: int = 1,
    ) -> None:
        token = self.monitor.start_request(
            request_kind="get_item",
            method="GET",
            path="/v3/items/12345?token=hidden",
            attempt=attempt,
            max_attempts=max_attempts,
        )
        self.monotonic_clock.advance_ms(elapsed_ms)
        self.monitor.finish_request(
            token,
            status_code=status_code,
            outcome=outcome,
            error_kind=None if outcome == API_OUTCOME_SUCCESS else "HTTP",
        )

    def test_normalize_api_path_removes_query_and_identifier_segments(self) -> None:
        self.assertEqual(
            normalize_api_path(
                "https://example.test/v3/items/12345/fields/"
                "550e8400-e29b-41d4-a716-446655440000?token=secret"
            ),
            "/v3/items/{id}/fields/{id}",
        )
        self.assertEqual(
            normalize_api_path("/v3/items/deadbeef/children"),
            "/v3/items/{id}/children",
        )

    def test_disabled_monitor_does_not_create_active_or_completed_event(self) -> None:
        self.monitor.configure(enabled=False, slow_threshold_ms=200)

        token = self.monitor.start_request(
            request_kind="get_projects",
            method="GET",
            path="/v3/projects",
        )

        self.assertIsNone(token)
        snapshot = self.monitor.snapshot(now=self.wall_clock.value)
        self.assertEqual(snapshot.stats.active, 0)
        self.assertEqual(snapshot.stats.total, 0)

    def test_snapshot_tracks_active_request_then_completed_stats(self) -> None:
        token = self.monitor.start_request(
            request_kind="get_item",
            method="GET",
            path="/v3/items/12345",
        )
        active_snapshot = self.monitor.snapshot(now=self.wall_clock.value)
        self.assertEqual(active_snapshot.stats.active, 1)

        self.monotonic_clock.advance_ms(250)
        event = self.monitor.finish_request(
            token,
            status_code=200,
            outcome=API_OUTCOME_SUCCESS,
        )

        self.assertIsNotNone(event)
        snapshot = self.monitor.snapshot(now=self.wall_clock.value)
        self.assertEqual(snapshot.stats.active, 0)
        self.assertEqual(snapshot.stats.total, 1)
        self.assertEqual(snapshot.stats.success, 1)
        self.assertEqual(snapshot.stats.slow, 1)
        self.assertEqual(snapshot.stats.success_rate, 100.0)
        self.assertAlmostEqual(snapshot.stats.average_ms, 250.0)
        self.assertEqual(snapshot.events[0].path, "/v3/items/{id}")

    def test_bounded_buffer_and_percentiles_use_recent_events(self) -> None:
        for elapsed_ms in (10, 20, 30, 400):
            self._record(elapsed_ms=elapsed_ms)

        snapshot = self.monitor.snapshot(now=self.wall_clock.value)

        self.assertEqual(len(snapshot.events), 3)
        self.assertEqual([round(item.elapsed_ms) for item in snapshot.events], [20, 30, 400])
        self.assertAlmostEqual(snapshot.stats.p50_ms, 30.0)
        self.assertAlmostEqual(snapshot.stats.p95_ms, 400.0)
        self.assertAlmostEqual(snapshot.stats.max_ms, 400.0)

    def test_failed_retry_and_rate_limit_counts_are_separate(self) -> None:
        self._record(
            elapsed_ms=50,
            outcome=API_OUTCOME_RETRY,
            status_code=429,
            attempt=1,
            max_attempts=2,
        )
        self._record(
            elapsed_ms=60,
            outcome=API_OUTCOME_FAILED,
            status_code=500,
        )

        stats = self.monitor.snapshot(now=self.wall_clock.value).stats

        self.assertEqual(stats.retries, 1)
        self.assertEqual(stats.failed, 1)
        self.assertEqual(stats.rate_limited, 1)
        self.assertEqual(stats.success, 0)

    def test_clear_removes_completed_events_but_keeps_capture_enabled(self) -> None:
        self._record(elapsed_ms=25)

        self.monitor.clear()

        snapshot = self.monitor.snapshot(now=self.wall_clock.value)
        self.assertTrue(snapshot.enabled)
        self.assertEqual(snapshot.events, ())

    def test_event_schema_cannot_store_payload_headers_or_query_values(self) -> None:
        field_names = {field.name for field in fields(ApiRequestEvent)}

        self.assertFalse(
            field_names
            & {
                "body",
                "request_body",
                "response_body",
                "headers",
                "params",
                "query",
                "url",
            }
        )


if __name__ == "__main__":
    unittest.main()
