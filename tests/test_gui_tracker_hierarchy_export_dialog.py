from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.gui.tracker_baseline_compare import TrackerTableColumn
from src.gui.tracker_hierarchy_export import TrackerHierarchyExportField
from src.gui.tracker_hierarchy_export_dialog import TrackerHierarchyExportFieldDialog
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class TrackerHierarchyExportFieldDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_general_fields_start_selected_and_table_fields_start_clear(self) -> None:
        dialog = TrackerHierarchyExportFieldDialog(
            (
                TrackerHierarchyExportField("status", "상태"),
                TrackerHierarchyExportField(
                    "custom:10",
                    "검증 표",
                    is_table=True,
                    table_columns=(TrackerTableColumn("id:101", "결과"),),
                    default_selected=False,
                ),
            )
        )

        self.assertEqual(dialog.selected_field_keys(), ("status",))
        self.assertEqual(
            dialog.status_label.text(),
            "추가 필드 1개 / 전체 2개 · 고정 열 4개",
        )

    def test_select_all_and_clear_include_fields_hidden_by_search(self) -> None:
        dialog = TrackerHierarchyExportFieldDialog(
            (
                TrackerHierarchyExportField("description", "설명"),
                TrackerHierarchyExportField("status", "상태"),
            )
        )
        dialog.search_input.setText("설명")
        self.assertTrue(dialog.field_list.item(1).isHidden())

        dialog._set_all_checks(Qt.CheckState.Unchecked)
        self.assertEqual(dialog.selected_field_keys(), ())

        dialog._set_all_checks(Qt.CheckState.Checked)
        self.assertEqual(dialog.selected_field_keys(), ("description", "status"))


if __name__ == "__main__":
    unittest.main()
