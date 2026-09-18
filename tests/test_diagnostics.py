from __future__ import annotations

import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.api_monitor import ApiMonitorService
from src.diagnostics import DiagnosticLevel
from src.diagnostics import DiagnosticService
from src.diagnostics import DiagnosticSource
from src.diagnostics import current_operation_id
from src.diagnostics import export_diagnostic_bundle
from src.diagnostics import operation_context
from src.diagnostics import sanitize_diagnostic_text
from src.diagnostics import sanitize_diagnostic_value


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class DiagnosticServiceTest(unittest.TestCase):
    def test_session_buffer_is_thread_safe_bounded_and_ordered(self) -> None:
        service = DiagnosticService(max_events=3)

        threads = [
            threading.Thread(
                target=lambda index=index: service.record(
                    level=DiagnosticLevel.INFO,
                    source=DiagnosticSource.APPLICATION,
                    event_kind="worker_event",
                    message=f"worker {index}",
                )
            )
            for index in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = service.snapshot()
        self.assertEqual(len(snapshot.events), 3)
        self.assertEqual(
            [event.sequence for event in snapshot.events],
            sorted(event.sequence for event in snapshot.events),
        )
        self.assertGreater(snapshot.version, 0)

    def test_operation_context_and_elapsed_time_are_correlated(self) -> None:
        clock = _Clock(10.0)
        service = DiagnosticService(monotonic_clock=clock)
        operation_id = service.start_operation(
            source=DiagnosticSource.SETTINGS,
            event_kind="settings_apply",
            message="설정 적용 시작",
        )

        with operation_context(operation_id):
            self.assertEqual(current_operation_id(), operation_id)
            service.record(
                level=DiagnosticLevel.INFO,
                source=DiagnosticSource.SETTINGS,
                event_kind="settings_step",
                message="설정 적용 중",
            )
        clock.advance(0.25)
        finished = service.finish_operation(
            operation_id,
            source=DiagnosticSource.SETTINGS,
            event_kind="settings_apply",
            message="설정 적용 완료",
        )

        self.assertEqual(finished.operation_id, operation_id)
        self.assertEqual(finished.elapsed_ms, 250.0)
        self.assertEqual(
            {event.operation_id for event in service.snapshot().events},
            {operation_id},
        )
        self.assertEqual(current_operation_id(), "")

    def test_api_monitor_reads_current_operation_id(self) -> None:
        monitor = ApiMonitorService()
        monitor.configure(enabled=True)

        with operation_context("a" * 32):
            handle = monitor.start_request(
                request_kind="get_item",
                method="GET",
                path="/v3/items/123",
            )
            monitor.finish_request(handle, status_code=200, outcome="success")

        event = monitor.snapshot().events[0]
        self.assertEqual(event.operation_id, "a" * 32)

    def test_sanitizer_masks_credentials_urls_email_paths_and_nested_values(self) -> None:
        sanitized = sanitize_diagnostic_text(
            "password=guess authorization=Bearer abc.def https://private.example/a?q=secret "
            "person@example.test /Users/private/work/file.xlsx"
        )
        nested = sanitize_diagnostic_value(
            {
                "authorization": "Basic hidden",
                "child": {
                    "token": "secret-token",
                    "private_key": "private-key-value",
                    "safe": "ok",
                },
            }
        )

        for secret in (
            "guess",
            "abc.def",
            "private.example",
            "person@example",
            "/Users/private",
            "hidden",
            "secret-token",
            "private-key-value",
        ):
            self.assertNotIn(secret, f"{sanitized!r}{nested!r}")
        self.assertEqual(nested["authorization"], "***")
        self.assertEqual(nested["child"]["token"], "***")
        self.assertEqual(nested["child"]["private_key"], "***")

    def test_sanitizer_masks_wrapped_json_headers_and_api_keys(self) -> None:
        sanitized = sanitize_diagnostic_text(
            'HTTP 400: {"token":"json-secret","name":"REQ-PRIVATE"}\n'
            "Authorization: Bearer bearer-secret\n"
            "X-Api-Key: header-secret\n"
            "api_key='assignment-secret' username=private-user; "
            "X-Api-Key: inline-secret; reason=Denied"
        )

        for secret in (
            "json-secret",
            "bearer-secret",
            "header-secret",
            "assignment-secret",
            "private-user",
            "inline-secret",
        ):
            self.assertNotIn(secret, sanitized)
        self.assertIn("REQ-PRIVATE", sanitized)
        self.assertIn("reason=Denied", sanitized)

    def test_sanitizer_masks_quoted_and_windows_absolute_paths(self) -> None:
        sanitized = sanitize_diagnostic_text(
            'source="/Users/Private User/work/private.xlsx" '
            r"windows=C:\Users\Private\work\private.xlsx "
            r"unix=/opt/private/work/private.xlsx"
        )

        for secret in (
            "/Users/Private User",
            r"C:\Users\Private",
            "/opt/private",
        ):
            self.assertNotIn(secret, sanitized)
        self.assertGreaterEqual(sanitized.count("<PATH>"), 3)

    def test_record_exception_keeps_only_generic_message(self) -> None:
        service = DiagnosticService()
        error = RuntimeError('HTTP 400: {"token":"secret","name":"Private Item"}')

        event = service.record_exception(
            RuntimeError,
            error,
            None,
            "worker",
        )

        self.assertEqual(event.exception_type, "RuntimeError")
        self.assertNotIn("secret", event.message)
        self.assertNotIn("Private Item", event.message)


class DiagnosticBundleTest(unittest.TestCase):
    def _fixture(self):
        service = DiagnosticService()
        service.record(
            level=DiagnosticLevel.ERROR,
            source=DiagnosticSource.APPLICATION,
            event_kind="sample_error",
            message="token=private-token at https://private.example.test/path?q=value",
            details={"password": "private-password", "failed_count": 2},
        )
        api_event = SimpleNamespace(
            sequence=1,
            started_at=1_700_000_000.0,
            request_kind="get_item",
            method="GET",
            path="https://api.private.example.test/v3/items/123?email=private-value",
            status_code=500,
            elapsed_ms=125.0,
            outcome="failed",
            attempt=1,
            max_attempts=1,
            error_kind="HTTP",
            operation_id="b" * 32,
        )
        activity = SimpleNamespace(
            occurred_at="2026-08-09T10:00:00+09:00",
            operation=SimpleNamespace(value="batch_upload"),
            result=SimpleNamespace(value="failed"),
            source="batch_upload",
            project_name="Private Project",
            item_name="Private Item",
            details={
                "failed_count": 2,
                "error": "private server response",
                "file_path": "/Users/private/private.xlsx",
            },
        )
        return service, api_event, activity

    def test_bundle_contains_only_whitelisted_safe_files_and_metadata(self) -> None:
        service, api_event, activity = self._fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "diagnostics.zip"

            summary = export_diagnostic_bundle(
                target,
                diagnostics_snapshot=service.snapshot(),
                api_events=[api_event],
                activity_records=[activity],
                offline_mode=True,
            )

            self.assertEqual(summary.diagnostic_count, 1)
            self.assertEqual(summary.api_event_count, 1)
            self.assertEqual(summary.activity_count, 1)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()), set(summary.files))
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["redactionPolicy"], "safe-metadata-only")
                bundle_bytes = b"\n".join(
                    archive.read(name) for name in archive.namelist()
                )
            bundle_text = bundle_bytes.decode("utf-8")
            for secret in (
                "private-token",
                "private-password",
                "private.example",
                "private-value",
                "Private Project",
                "Private Item",
                "private server response",
                "private.xlsx",
            ):
                self.assertNotIn(secret, bundle_text)
            self.assertIn("failed_count", bundle_text)
            self.assertIn("/v3/items/{id}", bundle_text)

    def test_atomic_failure_preserves_existing_bundle_and_removes_temporary_file(self) -> None:
        service, _api_event, _activity = self._fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "diagnostics.zip"
            target.write_bytes(b"existing")

            with (
                patch.object(Path, "replace", side_effect=OSError("replace failed")),
                self.assertRaises(OSError),
            ):
                export_diagnostic_bundle(
                    target,
                    diagnostics_snapshot=service.snapshot(),
                )

            self.assertEqual(target.read_bytes(), b"existing")
            self.assertEqual(
                [path.name for path in Path(temp_dir).iterdir()],
                ["diagnostics.zip"],
            )

    def test_bundle_replaces_event_messages_and_drops_unapproved_details(self) -> None:
        service = DiagnosticService()
        service.record(
            level=DiagnosticLevel.ERROR,
            source=DiagnosticSource.APPLICATION,
            event_kind="user_notified_error",
            message='Private Item: {"token":"secret-token"}',
            details={
                "title": "Private Project",
                "failed_count": 2,
                "raw_response": "Private server response",
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "diagnostics.zip"
            export_diagnostic_bundle(
                target,
                diagnostics_snapshot=service.snapshot(),
            )
            with zipfile.ZipFile(target) as archive:
                payload = json.loads(
                    archive.read("diagnostics.ndjson").decode("utf-8")
                )

        serialized = json.dumps(payload, ensure_ascii=False)
        for secret in (
            "Private Item",
            "secret-token",
            "Private Project",
            "Private server response",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual(payload["details"], {"failed_count": 2})
        self.assertEqual(payload["eventKind"], "user_notified_error")


if __name__ == "__main__":
    unittest.main()
