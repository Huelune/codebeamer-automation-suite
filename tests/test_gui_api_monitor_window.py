from __future__ import annotations

import os
import unittest
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.api_monitor import API_OUTCOME_FAILED
from src.api_monitor import API_OUTCOME_SUCCESS
from src.api_monitor import ApiMonitorService
from src.gui.api_monitor_window import ApiMonitorWindow
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, value: float) -> None:
        self.value += value / 1000.0


class GuiApiMonitorWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.wall_clock = _Clock(1_700_000_000.0)
        self.monotonic_clock = _Clock(100.0)
        self.monitor = ApiMonitorService(
            wall_clock=self.wall_clock,
            monotonic_clock=self.monotonic_clock,
        )
        self.monitor.configure(enabled=True, slow_threshold_ms=200)
        self.window = ApiMonitorWindow(
            self.monitor,
            settings_provider=lambda: SimpleNamespace(offline_mode=False),
        )

    def tearDown(self) -> None:
        self.window.close()
        self._app.processEvents()

    def _record(
        self,
        request_kind: str,
        *,
        method: str = "GET",
        path: str = "/v3/items/123",
        status_code: int | None = 200,
        outcome: str = API_OUTCOME_SUCCESS,
        elapsed_ms: float = 50,
        operation_id: str | None = None,
    ) -> None:
        token = self.monitor.start_request(
            request_kind=request_kind,
            method=method,
            path=path,
            operation_id=operation_id,
        )
        self.monotonic_clock.advance_ms(elapsed_ms)
        self.monitor.finish_request(
            token,
            status_code=status_code,
            outcome=outcome,
            error_kind=None if outcome == API_OUTCOME_SUCCESS else "HTTP",
        )

    def test_window_shows_summary_and_metadata_rows(self) -> None:
        self._record("get_item", elapsed_ms=40)
        self._record(
            "update_item",
            method="PUT",
            status_code=500,
            outcome=API_OUTCOME_FAILED,
            elapsed_ms=350,
        )

        self.window.refresh(force=True)

        self.assertEqual(self.window.table.rowCount(), 2)
        self.assertEqual(self.window.stat_value_labels["total"].text(), "2")
        self.assertEqual(self.window.stat_value_labels["failed"].text(), "1")
        self.assertEqual(self.window.stat_value_labels["slow"].text(), "1건")
        self.assertEqual(self.window.table.item(0, 3).text(), "/v3/items/{id}")
        self.assertIn("수집 중", self.window.collection_state_label.text())
        self.assertGreaterEqual(self.window.minimumWidth(), 900)

    def test_filters_can_narrow_by_method_status_result_and_slow_threshold(self) -> None:
        self._record("get_item", elapsed_ms=50)
        self._record(
            "update_item",
            method="PUT",
            status_code=500,
            outcome=API_OUTCOME_FAILED,
            elapsed_ms=350,
        )
        self.window.refresh(force=True)

        self.window.method_combo.setCurrentIndex(self.window.method_combo.findData("PUT"))
        self.assertEqual(self.window.table.rowCount(), 1)
        self.window.status_combo.setCurrentIndex(self.window.status_combo.findData("5xx"))
        self.window.outcome_combo.setCurrentIndex(
            self.window.outcome_combo.findData(API_OUTCOME_FAILED)
        )
        self.window.slow_only_checkbox.setChecked(True)

        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, 1).text(), "update_item")

    def test_pause_freezes_rows_until_resumed_but_capture_continues(self) -> None:
        self._record("get_projects")
        self.window.refresh(force=True)
        self.window.pause_button.click()
        self._record("get_trackers")

        self.window.refresh()
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(len(self.monitor.snapshot().events), 2)

        self.window.pause_button.click()
        self.assertEqual(self.window.table.rowCount(), 2)

    def test_copy_and_clear_actions_use_visible_metadata_only(self) -> None:
        self._record("get_item")
        self.window.refresh(force=True)
        self.window.table.selectRow(0)

        self.window.copy_selected_row()

        clipboard_text = self._app.clipboard().text()
        self.assertIn("get_item", clipboard_text)
        self.assertIn("/v3/items/{id}", clipboard_text)
        self.window.clear_events()
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertEqual(self.monitor.snapshot().events, ())

    def test_disabled_and_test_mode_states_are_explicit(self) -> None:
        self.monitor.configure(enabled=False, slow_threshold_ms=200)
        self.window.refresh(force=True)
        self.assertIn("수집 중지", self.window.collection_state_label.text())

        self.monitor.configure(enabled=True, slow_threshold_ms=200)
        self.window.settings_provider = lambda: SimpleNamespace(offline_mode=True)
        self.window.refresh(force=True)
        self.assertIn("테스트 모드", self.window.collection_state_label.text())

    def test_diagnostic_id_is_visible_and_searchable(self) -> None:
        self._record("get_item", operation_id="abcd1234" + ("0" * 24))
        self._record("get_projects", operation_id="ffff0000" + ("0" * 24))
        self.window.refresh(force=True)

        self.window.search_edit.setText("abcd1234")

        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, 8).text(), "abcd1234")


if __name__ == "__main__":
    unittest.main()
