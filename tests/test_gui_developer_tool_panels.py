from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QWidget

from src.gui.developer_tool_panels import PAYLOAD_TABLE_ROW_LIMIT
from src.gui.developer_tool_panels import ExcelToolPanel
from src.gui.developer_tool_panels import PayloadToolPanel
from src.gui.developer_tool_panels import ReadOnlyQueryToolPanel
from src.gui.developer_tool_panels import SchemaCacheToolPanel
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class DeveloperToolPanelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_payload_panel_shows_only_masked_payload(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "_row_id": 1,
                    "payload_status": "READY",
                    "payload_json": '{"name":"REQ-1","token":"secret"}',
                }
            ]
        )
        panel = PayloadToolPanel(lambda: frame)
        try:
            panel.refresh_payloads()
            self.assertEqual(panel.table.rowCount(), 1)
            self.assertIn('"token": "***"', panel.detail_view.toPlainText())
            self.assertNotIn("secret", panel.detail_view.toPlainText())
        finally:
            panel.close()

    def test_payload_panel_selects_duplicate_row_id_by_source_file(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "source_file": "first.xlsx",
                    "source_file_path": "/safe/first.xlsx",
                    "_row_id": 1,
                    "payload": {"name": "first"},
                },
                {
                    "source_file": "second.xlsx",
                    "source_file_path": "/safe/second.xlsx",
                    "_row_id": 1,
                    "payload": {"name": "second"},
                },
            ]
        )
        panel = PayloadToolPanel(lambda: frame)
        try:
            panel.refresh_payloads()
            panel.table.selectRow(1)

            self.assertEqual(panel.table.item(1, 0).text(), "second.xlsx")
            self.assertIn('"name": "second"', panel.detail_view.toPlainText())
            self.assertNotIn('"name": "first"', panel.detail_view.toPlainText())
        finally:
            panel.close()

    def test_payload_panel_limits_large_result_table(self) -> None:
        frame = pd.DataFrame(
            [
                {"_row_id": index, "payload": {"name": f"item-{index}"}}
                for index in range(PAYLOAD_TABLE_ROW_LIMIT + 25)
            ]
        )
        panel = PayloadToolPanel(lambda: frame)
        try:
            panel.refresh_payloads()

            self.assertEqual(panel.table.rowCount(), PAYLOAD_TABLE_ROW_LIMIT)
            self.assertIn(
                f"{PAYLOAD_TABLE_ROW_LIMIT + 25}건 중",
                panel.status_label.text(),
            )
        finally:
            panel.close()

    def test_excel_panel_converts_cp949_semicolon_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.csv"
            source.write_text("Summary;설명\nREQ-1;한글\n", encoding="cp949")
            output = Path(temp_dir) / "converted.csv"
            panel = ExcelToolPanel(default_directory=temp_dir)
            try:
                panel.file_edit.setText(str(source))
                panel.encoding_combo.setCurrentText("cp949")
                panel.delimiter_edit.setText(";")
                panel.convert_to_csv(output)

                self.assertTrue(output.is_file())
                self.assertIn("저장했습니다", panel.summary_label.text())
                self.assertIn("한글", output.read_text(encoding="cp949"))
            finally:
                panel.close()

    def test_excel_operation_locks_excel_and_query_buttons_in_same_window(self) -> None:
        host = QWidget()
        query_calls = []
        query_panel = ReadOnlyQueryToolPanel(
            lambda query: query_calls.append(query) or [],
            parent=host,
        )
        panel = None

        def run_operation(_message, callback):
            buttons = (
                panel.browse_button,
                panel.inspect_button,
                panel.xlsx_button,
                panel.csv_button,
                query_panel.use_current_button,
                query_panel.preview_button,
                query_panel.execute_button,
            )
            self.assertTrue(all(not button.isEnabled() for button in buttons))
            query_panel.execute_query()
            self.assertEqual(query_calls, [])
            return callback()

        service = SimpleNamespace(
            inspect=lambda **_options: SimpleNamespace(
                issues=(),
                selected_sheet="Sheet1",
                row_count=1,
                column_count=1,
                formula_count=0,
            )
        )
        panel = ExcelToolPanel(
            service=service,
            operation_runner=run_operation,
            parent=host,
        )
        try:
            panel.file_edit.setText("sample.xlsx")
            panel.inspect_current_file()

            self.assertTrue(panel.inspect_button.isEnabled())
            self.assertTrue(query_panel.execute_button.isEnabled())
            self.assertIn("데이터 1행", panel.summary_label.text())
        finally:
            host.close()

    def test_query_operation_restores_all_buttons_after_failure(self) -> None:
        panel = None

        def execute(_query):
            self.assertFalse(panel.use_current_button.isEnabled())
            self.assertFalse(panel.preview_button.isEnabled())
            self.assertFalse(panel.execute_button.isEnabled())
            raise RuntimeError("서버 오류")

        panel = ReadOnlyQueryToolPanel(execute)
        try:
            panel.execute_query()

            self.assertTrue(panel.use_current_button.isEnabled())
            self.assertTrue(panel.preview_button.isEnabled())
            self.assertTrue(panel.execute_button.isEnabled())
            self.assertEqual(panel.status_label.text(), "서버 오류")
        finally:
            panel.close()

    def test_schema_and_cache_panel_reports_support_and_counts_only(self) -> None:
        context = SimpleNamespace(
            schema_df=pd.DataFrame(
                [
                    {"field_id": 1, "field_name": "Summary", "field_type": "TextField", "is_supported": True},
                    {
                        "field_id": 2,
                        "field_name": "Unknown",
                        "field_type": "ReferenceField",
                        "is_supported": False,
                        "unsupported_reason": "referenceType 없음",
                    },
                ]
            ),
            tracker_item_lookup_cache={"private-key": "private-value"},
            user_lookup_cache={},
            member_lookup_cache={},
            group_lookup_cache={},
            tracker_role_cache={},
            existing_item_cache={},
        )
        panel = SchemaCacheToolPanel(lambda: context)
        try:
            panel.refresh_schema()
            panel.refresh_caches()
            self.assertEqual(panel.schema_table.rowCount(), 2)
            self.assertIn("미지원 1개", panel.schema_status_label.text())
            self.assertEqual(panel.cache_table.item(0, 2).text(), "1")
            self.assertNotIn("private", panel.cache_status_label.text())
        finally:
            panel.close()

    def test_read_only_query_panel_previews_fixed_endpoint_and_executes_callback(self) -> None:
        captured = []
        panel = ReadOnlyQueryToolPanel(
            lambda query: captured.append(query) or SimpleNamespace(
                items=(SimpleNamespace(item_id=1, name="REQ-1", status="Open"),)
            ),
            tracker_id_provider=lambda: 17,
        )
        try:
            panel.use_current_tracker()
            panel.cbql_edit.setPlainText("status = 'Open'")
            panel.preview_query()
            self.assertIn('"path": "/v3/items/query"', panel.output_view.toPlainText())
            panel.execute_query()
            self.assertEqual(captured[0].tracker_id, 17)
            self.assertIn("REQ-1", panel.output_view.toPlainText())
        finally:
            panel.close()


if __name__ == "__main__":
    unittest.main()
