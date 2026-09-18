from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QWidget

from src.api_monitor import ApiMonitorService
from src.diagnostics import DiagnosticLevel
from src.diagnostics import DiagnosticService
from src.diagnostics import DiagnosticSource
from src.gui.developer_tools_window import DIAGNOSTIC_TABLE_ROW_LIMIT
from src.gui.developer_tools_window import DeveloperToolsWindow
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class GuiDeveloperToolsWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.diagnostics = DiagnosticService()
        self.api_monitor = ApiMonitorService()
        self.api_monitor.configure(enabled=True)
        self.window = DeveloperToolsWindow(
            self.diagnostics,
            self.api_monitor,
            settings_provider=lambda: SimpleNamespace(offline_mode=True),
            activity_provider=lambda: (),
            default_directory=Path(self.temp_dir.name),
        )

    def tearDown(self) -> None:
        self.window.close()
        self._app.processEvents()
        self.temp_dir.cleanup()

    def _record(self, message: str, *, level=DiagnosticLevel.INFO) -> None:
        self.diagnostics.record(
            level=level,
            source=DiagnosticSource.APPLICATION,
            event_kind="sample_event",
            message=message,
            operation_id="c" * 32,
        )

    def test_window_exposes_extensible_tabs_and_filters_safe_session_events(self) -> None:
        self._record("first")
        self._record("second", level=DiagnosticLevel.ERROR)
        self.window.show()
        self.window.select_diagnostics_tab()
        self.window.refresh(force=True)

        panel = self.window.diagnostics_panel
        self.assertEqual(self.window.tabs.count(), 2)
        self.assertEqual(
            [self.window.tabs.tabText(index) for index in range(self.window.tabs.count())],
            ["진단 로그", "API 모니터"],
        )
        extra_index = self.window.add_tool_tab(QWidget(), "Excel 검사")
        self.assertEqual(extra_index, 2)
        self.assertEqual(self.window.tabs.tabText(extra_index), "Excel 검사")
        self.assertEqual(panel.table.rowCount(), 2)
        panel.level_combo.setCurrentIndex(
            panel.level_combo.findData(DiagnosticLevel.ERROR.value)
        )
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(panel.table.item(0, 4).text(), "cccccccc")
        self.assertIn("second", panel.detail_view.toPlainText())

    def test_pause_freezes_display_but_not_collection(self) -> None:
        self._record("first")
        panel = self.window.diagnostics_panel
        panel.refresh(force=True)
        panel.pause_button.click()
        self._record("second")

        panel.refresh()
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertEqual(len(self.diagnostics.snapshot().events), 2)

        panel.pause_button.click()
        self.assertEqual(panel.table.rowCount(), 2)

    def test_large_session_keeps_full_buffer_but_limits_table_rows(self) -> None:
        for index in range(DIAGNOSTIC_TABLE_ROW_LIMIT + 25):
            self._record(f"event-{index}")

        panel = self.window.diagnostics_panel
        panel.refresh(force=True)

        self.assertEqual(panel.table.rowCount(), DIAGNOSTIC_TABLE_ROW_LIMIT)
        self.assertEqual(
            len(self.diagnostics.snapshot().events),
            DIAGNOSTIC_TABLE_ROW_LIMIT + 25,
        )
        self.assertIn("필터 결과", panel.table_state_label.text())

    def test_bundle_export_uses_current_safe_snapshots(self) -> None:
        self._record("token=secret-value")
        handle = self.api_monitor.start_request(
            request_kind="get_item",
            method="GET",
            path="/v3/items/123",
        )
        self.api_monitor.finish_request(
            handle,
            status_code=200,
            outcome="success",
        )
        target = Path(self.temp_dir.name) / "diagnostics.zip"

        summary = self.window.export_to_path(target)

        self.assertTrue(target.exists())
        self.assertEqual(summary.diagnostic_count, 1)
        self.assertEqual(summary.api_event_count, 1)
        with zipfile.ZipFile(target) as archive:
            content = b"\n".join(archive.read(name) for name in archive.namelist())
        self.assertNotIn(b"secret-value", content)
        self.assertIn("진단 패키지를 저장했습니다", self.window.status_label.text())
        self.assertEqual(len(self.diagnostics.snapshot().events), 2)


if __name__ == "__main__":
    unittest.main()
