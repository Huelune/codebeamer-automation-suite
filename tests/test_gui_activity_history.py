from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.activity_history import ActivityHistoryError
from src.gui.activity_history import ActivityHistoryStore
from src.gui.activity_history import ActivityOperation
from src.gui.activity_history import ActivityRecord
from src.gui.activity_history import ActivityResult
from src.gui.activity_history import sanitize_activity_details
from src.gui.activity_history_page import ActivityHistoryPage
from src.gui.batch_window import BatchUploadWindow
from src.gui.settings_store import GuiSettings
from src.gui.settings_store import GuiSettingsStore
from src.gui.window_support import UploadProgressState


def _record(
    operation: ActivityOperation,
    result: ActivityResult,
    *,
    record_id: str,
    item_id: int | None = None,
    item_name: str = "",
) -> ActivityRecord:
    return ActivityRecord.create(
        operation,
        result,
        source="test",
        summary=f"{record_id} summary",
        project_id=10,
        project_name="Vehicle",
        tracker_id=20,
        tracker_name="Requirements",
        item_id=item_id,
        item_name=item_name,
        occurred_at="2026-08-03T13:00:00+09:00",
        record_id=record_id,
    )


class ActivityHistoryStoreTest(unittest.TestCase):
    def test_store_round_trip_keeps_latest_records_with_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activity.json"
            store = ActivityHistoryStore(path, max_records=3)

            for index in range(5):
                store.append(
                    _record(
                        ActivityOperation.TRACKER_CREATE,
                        ActivityResult.SUCCESS,
                        record_id=f"record-{index}",
                        item_id=1000 + index,
                    )
                )

            records = store.load()

            self.assertEqual(
                [record.record_id for record in records],
                ["record-4", "record-3", "record-2"],
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(len(payload["records"]), 3)

    def test_sensitive_details_are_masked_and_large_values_are_bounded(self) -> None:
        sanitized = sanitize_activity_details(
            {
                "password": "secret-value",
                "access_token": "token-value",
                "safe": "x" * 700,
                "nested": {"Authorization": "Bearer secret"},
            }
        )

        self.assertEqual(sanitized["password"], "***")
        self.assertEqual(sanitized["access_token"], "***")
        self.assertEqual(sanitized["nested"]["Authorization"], "***")
        self.assertLessEqual(len(sanitized["safe"]), 500)
        self.assertNotIn("secret-value", json.dumps(sanitized))

    def test_invalid_history_file_reports_safe_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "activity.json"
            path.write_text("not json", encoding="utf-8")

            with self.assertRaises(ActivityHistoryError) as raised:
                ActivityHistoryStore(path).load()

            self.assertNotIn("Expecting value", str(raised.exception))


class ActivityHistoryPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ActivityHistoryStore(Path(self.temp_dir.name) / "activity.json")
        self.store.append(
            _record(
                ActivityOperation.TRACKER_CREATE,
                ActivityResult.SUCCESS,
                record_id="create",
                item_id=1001,
                item_name="Steering requirement",
            )
        )
        self.store.append(
            _record(
                ActivityOperation.TRACKER_DELETE,
                ActivityResult.FAILED,
                record_id="delete",
                item_id=1002,
                item_name="Brake requirement",
            )
        )
        self.clear_requests = []
        self.page = ActivityHistoryPage(
            self.store,
            clear_confirmer=lambda count: self.clear_requests.append(count) or True,
        )
        self.page.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self._app.processEvents()
        self.temp_dir.cleanup()

    def test_page_renders_filters_and_detail_without_raw_server_payload(self) -> None:
        self.assertEqual(self.page.table.rowCount(), 2)
        self.assertEqual(self.page.total_label.text(), "전체 2")
        self.assertIn("#1002", self.page.detail_view.toPlainText())

        operation_index = self.page.operation_combo.findData(
            ActivityOperation.TRACKER_CREATE.value
        )
        self.page.operation_combo.setCurrentIndex(operation_index)
        self._app.processEvents()

        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertEqual(self.page.table.item(0, 4).text(), "#1001 Steering requirement")

        self.page.operation_combo.setCurrentIndex(0)
        self.page.search_input.setText("Brake")
        self._app.processEvents()
        self.assertEqual(self.page.table.rowCount(), 1)
        self.assertIn("삭제", self.page.table.item(0, 1).text())

    def test_clear_requires_confirmation_and_persists_empty_history(self) -> None:
        self.page.clear_button.click()
        self._app.processEvents()

        self.assertEqual(self.clear_requests, [2])
        self.assertEqual(self.store.load(), ())
        self.assertEqual(self.page.table.rowCount(), 0)
        self.assertFalse(self.page.clear_button.isEnabled())

    def test_bulk_failure_record_enables_retry_without_storing_field_values(self) -> None:
        requested = []
        self.page.bulk_retry_requested = requested.append
        self.store.append(
            ActivityRecord.create(
                ActivityOperation.BULK_UPDATE,
                ActivityResult.PARTIAL,
                source="test",
                summary="일괄 수정 일부 실패",
                tracker_id=20,
                details={
                    "run_id": "bulk-run-1",
                    "failed_count": 1,
                    "rolled_back_count": 2,
                    "unattempted_count": 0,
                },
            )
        )
        self.page.activate()

        self.assertTrue(self.page.retry_button.isEnabled())
        self.page.retry_button.click()

        self.assertEqual(requested, ["bulk-run-1"])
        self.assertNotIn("fieldValues", self.page.detail_view.toPlainText())


class BatchActivityIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_completed_dry_run_records_only_aggregate_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            records = []
            window = BatchUploadWindow(
                GuiSettingsStore(root_dir=Path(temp_dir)),
                activity_recorder=records.append,
            )
            try:
                window.session_state.settings = GuiSettings(
                    upload_mode="create",
                    default_project_id="10",
                    default_tracker_id="20",
                )
                window.session_state.projects = [{"id": 10, "name": "Vehicle"}]
                window.session_state.trackers = [{"id": 20, "name": "Requirements"}]
                window.session_state.mapping_context = SimpleNamespace(
                    file_paths=["sensitive-a.xlsx", "sensitive-b.xlsx"]
                )
                window._activity_dry_run = True
                window.upload_progress = UploadProgressState(
                    batch_started_at=time.perf_counter() - 2.0
                )

                window._on_upload_finished(
                    {
                        "success_df": pd.DataFrame([{"phase": "insert"}]),
                        "failed_df": pd.DataFrame(),
                        "unresolved_df": pd.DataFrame(),
                        "phase_results": {
                            "insert": {
                                "total": 1,
                                "success": 1,
                                "failed": 0,
                                "unresolved": 0,
                            }
                        },
                    }
                )

                self.assertEqual(len(records), 1)
                record = records[0]
                self.assertEqual(record.operation, ActivityOperation.BATCH_UPLOAD)
                self.assertEqual(record.result, ActivityResult.SUCCESS)
                self.assertTrue(record.details["dry_run"])
                self.assertEqual(record.details["file_count"], 2)
                serialized = json.dumps(record.to_payload(), ensure_ascii=False)
                self.assertNotIn("sensitive-a.xlsx", serialized)
                self.assertNotIn("sensitive-b.xlsx", serialized)
            finally:
                window.close()
                self._app.processEvents()


if __name__ == "__main__":
    unittest.main()
