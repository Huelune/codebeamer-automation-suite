from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QHeaderView

from src.gui.tracker_query_models import TrackerFieldValue
from src.gui.tracker_table_field_dialog import TrackerTableFieldDialog
from src.gui.tracker_table_field_dialog import table_field_dimensions
from src.gui.tracker_table_field_dialog import table_field_summary
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class TrackerTableFieldDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.field = TrackerFieldValue.from_raw(
            {
                "fieldId": 1000000,
                "name": "Test Steps",
                "type": "TableFieldValue",
                "columns": [
                    {"id": 1000001, "name": "Action", "type": "WikiTextField"},
                    {"id": 1000002, "name": "Expected", "type": "TextField"},
                ],
                "values": [
                    [
                        {
                            "fieldId": 1000001,
                            "name": "Action",
                            "value": "%%(color:red)__Run__%%",
                        },
                        {
                            "fieldId": 1000002,
                            "name": "Expected",
                            "value": "%%(color:red)raw text%%",
                        },
                    ],
                    [
                        {
                            "fieldId": 1000001,
                            "name": "Action",
                            "type": "WikiTextFieldValue",
                            "value": "Second",
                        }
                    ],
                ],
            }
        )
        self.dialog = TrackerTableFieldDialog(self.field)

    def tearDown(self) -> None:
        self.dialog.close()
        self._app.processEvents()

    def test_table_dimensions_preserve_rows_and_columns(self) -> None:
        self.assertEqual(table_field_dimensions(self.field), (2, 2))
        self.assertEqual(table_field_summary(self.field), "2행 × 2열")
        self.assertEqual(self.dialog.table.rowCount(), 2)
        self.assertEqual(self.dialog.table.columnCount(), 2)

    def test_only_explicit_wiki_column_uses_rich_text_widget(self) -> None:
        wiki_widget = self.dialog.table.cellWidget(0, 0)
        plain_widget = self.dialog.table.cellWidget(0, 1)

        self.assertIsNotNone(wiki_widget)
        self.assertIn("color: red", wiki_widget.text())
        self.assertNotIn("%%", wiki_widget.text())
        self.assertIsNone(plain_widget)
        self.assertEqual(
            self.dialog.table.item(0, 1).text(),
            "%%(color:red)raw text%%",
        )

    def test_source_toggle_restores_raw_wiki_text(self) -> None:
        resized_width = self.dialog.table.columnWidth(0) + 37
        self.dialog.table.setColumnWidth(0, resized_width)
        self.dialog.source_toggle.setChecked(True)
        self._app.processEvents()

        self.assertIsNone(self.dialog.table.cellWidget(0, 0))
        self.assertEqual(self.dialog.table.columnWidth(0), resized_width)
        self.assertEqual(
            self.dialog.table.item(0, 0).text(),
            "%%(color:red)__Run__%%",
        )

    def test_columns_are_user_resizable_and_scrollbars_are_available(self) -> None:
        header = self.dialog.table.horizontalHeader()

        self.assertEqual(
            header.sectionResizeMode(0),
            QHeaderView.ResizeMode.Interactive,
        )
        self.assertEqual(
            self.dialog.table.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            self.dialog.table.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )

    def test_rows_are_user_resizable_and_height_survives_source_toggle(self) -> None:
        row_header = self.dialog.table.verticalHeader()
        resized_height = self.dialog.table.rowHeight(0) + 19
        self.dialog.table.setRowHeight(0, resized_height)
        self.dialog.source_toggle.setChecked(True)
        self._app.processEvents()

        self.assertFalse(row_header.isHidden())
        self.assertEqual(
            row_header.sectionResizeMode(0),
            QHeaderView.ResizeMode.Interactive,
        )
        self.assertEqual(self.dialog.table.rowHeight(0), resized_height)

    def test_fullscreen_button_toggles_dialog_window_mode(self) -> None:
        self.dialog.show()
        self.dialog.fullscreen_button.setChecked(True)
        self._app.processEvents()

        self.assertTrue(self.dialog.isFullScreen())
        self.assertEqual(self.dialog.fullscreen_button.text(), "창 모드")

        self.dialog.fullscreen_button.setChecked(False)
        self._app.processEvents()

        self.assertFalse(self.dialog.isFullScreen())
        self.assertEqual(self.dialog.fullscreen_button.text(), "전체 화면")

    def test_many_rows_and_columns_enable_both_scroll_directions(self) -> None:
        columns = [
            {"id": 2000 + index, "name": f"Column {index}", "type": "TextField"}
            for index in range(8)
        ]
        rows = [
            [
                {"fieldId": column["id"], "value": f"R{row_index} C{index}"}
                for index, column in enumerate(columns)
            ]
            for row_index in range(60)
        ]
        field = TrackerFieldValue.from_raw(
            {
                "fieldId": 1999,
                "name": "Large table",
                "type": "TableFieldValue",
                "columns": columns,
                "values": rows,
            }
        )
        dialog = TrackerTableFieldDialog(field)
        dialog.show()
        self._app.processEvents()

        try:
            self.assertGreater(dialog.table.horizontalScrollBar().maximum(), 0)
            self.assertGreater(dialog.table.verticalScrollBar().maximum(), 0)
        finally:
            dialog.close()
            self._app.processEvents()


if __name__ == "__main__":
    unittest.main()
