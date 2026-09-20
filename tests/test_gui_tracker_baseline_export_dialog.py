from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QDialogButtonBox

from src.gui.tracker_baseline_compare import TrackerTableColumn
from src.gui.tracker_baseline_export import BaselineExportField
from src.gui.tracker_baseline_export_dialog import BaselineExportFieldDialog
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class BaselineExportFieldDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_initialization_updates_status_after_widgets_are_ready(self) -> None:
        dialog = BaselineExportFieldDialog(
            (
                BaselineExportField("name", "아이템명"),
                BaselineExportField(
                    "custom:10",
                    "검토표",
                    is_table=True,
                    table_columns=(TrackerTableColumn("id:101", "결과"),),
                ),
            )
        )

        self.assertEqual(dialog.status_label.text(), "선택 2개 / 전체 2개")
        self.assertTrue(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
        )

        dialog.field_list.item(0).setCheckState(Qt.CheckState.Unchecked)

        self.assertEqual(dialog.status_label.text(), "선택 1개 / 전체 2개")

    def test_select_all_and_clear_apply_to_fields_hidden_by_search(self) -> None:
        dialog = BaselineExportFieldDialog(
            (
                BaselineExportField("name", "아이템명"),
                BaselineExportField("status", "상태"),
            )
        )
        dialog.search_input.setText("아이템")
        self.assertTrue(dialog.field_list.item(1).isHidden())

        dialog._set_all_checks(Qt.CheckState.Unchecked)
        self.assertEqual(dialog.selected_field_keys(), ())

        dialog._set_all_checks(Qt.CheckState.Checked)
        self.assertEqual(dialog.selected_field_keys(), ("name", "status"))


if __name__ == "__main__":
    unittest.main()
