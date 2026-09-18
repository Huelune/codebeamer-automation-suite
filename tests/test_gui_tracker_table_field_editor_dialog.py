from __future__ import annotations

import os
import unittest
from dataclasses import replace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QHeaderView
from PySide6.QtWidgets import QPlainTextEdit

from src.gui.tracker_item_editor import EditableFieldOption
from src.gui.tracker_item_editor import EditableTrackerField
from src.gui.tracker_item_editor import FieldEditorKind
from src.gui.tracker_table_field_editor_dialog import TrackerTableFieldEditorDialog
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


def _column(
    field_id: int,
    name: str,
    kind: FieldEditorKind,
    value_model: str,
    *,
    options: tuple[EditableFieldOption, ...] = (),
    unsupported_reason: str = "",
) -> EditableTrackerField:
    return EditableTrackerField(
        field_id=field_id,
        name=name,
        label=name,
        type_name=value_model.removesuffix("Value"),
        value_model=value_model,
        editor_kind=kind,
        options=options,
        unsupported_reason=unsupported_reason,
    )


def _field() -> EditableTrackerField:
    columns = (
        _column(1, "Action", FieldEditorKind.MULTILINE_TEXT, "WikiTextFieldValue"),
        _column(2, "Critical", FieldEditorKind.BOOLEAN, "BoolFieldValue"),
        _column(
            3,
            "Priority",
            FieldEditorKind.CHOICE,
            "ChoiceFieldValue",
            options=(
                EditableFieldOption(11, "High"),
                EditableFieldOption(12, "Low"),
            ),
        ),
        _column(
            4,
            "Linked item",
            FieldEditorKind.UNSUPPORTED,
            "ChoiceFieldValue",
            unsupported_reason="참조 열은 읽기 전용입니다.",
        ),
    )
    return EditableTrackerField(
        field_id=100,
        name="Test Steps",
        label="Test Steps",
        type_name="TableField",
        value_model="TableFieldValue",
        editor_kind=FieldEditorKind.TABLE,
        table_columns=columns,
        current_value=[
            [
                {
                    "fieldId": 1,
                    "name": "Action",
                    "type": "WikiTextFieldValue",
                    "value": "%%(color:red)__Run__%%",
                    "serverMetadata": {"preserve": True},
                },
                {
                    "fieldId": 2,
                    "name": "Critical",
                    "type": "BoolFieldValue",
                    "value": False,
                },
                {
                    "fieldId": 3,
                    "name": "Priority",
                    "type": "ChoiceFieldValue",
                    "values": [
                        {
                            "id": 11,
                            "name": "High",
                            "type": "ChoiceOptionReference",
                        }
                    ],
                },
                {
                    "fieldId": 4,
                    "name": "Linked item",
                    "type": "ChoiceFieldValue",
                    "values": [{"id": 9001, "type": "TrackerItemReference"}],
                },
                {
                    "fieldId": 99,
                    "name": "Internal ID",
                    "type": "WikiTextFieldValue",
                    "value": "hidden-1",
                },
            ]
        ],
    )


def _cell(row: list[dict], field_id: int) -> dict:
    return next(cell for cell in row if cell.get("fieldId") == field_id)


class TrackerTableFieldEditorDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.field = _field()
        self.dialog = TrackerTableFieldEditorDialog(self.field)
        self.dialog.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.dialog.close()
        self._app.processEvents()

    def test_edits_supported_cells_and_preserves_hidden_and_read_only_cells(self) -> None:
        action = self.dialog.cell_widgets[(0, 1)]
        critical = self.dialog.cell_widgets[(0, 2)]
        priority = self.dialog.cell_widgets[(0, 3)]

        self.assertIsInstance(action, QPlainTextEdit)
        self.assertIsInstance(critical, QComboBox)
        action.setPlainText("Changed action")
        critical.setCurrentIndex(0)
        priority.setCurrentIndex(priority.findData(12))

        row = self.dialog.value()[0]

        self.assertEqual(_cell(row, 1)["value"], "Changed action")
        self.assertEqual(
            _cell(row, 1)["serverMetadata"],
            {"preserve": True},
        )
        self.assertTrue(_cell(row, 2)["value"])
        self.assertEqual(_cell(row, 3)["values"][0]["id"], 12)
        self.assertEqual(_cell(row, 4)["values"][0]["id"], 9001)
        self.assertEqual(_cell(row, 99)["value"], "hidden-1")

    def test_invalid_existing_row_structure_is_rejected_instead_of_dropped(self) -> None:
        with self.assertRaisesRegex(ValueError, "행 구조"):
            TrackerTableFieldEditorDialog(
                replace(self.field, current_value=["invalid row"])
            )

    def test_missing_existing_cell_is_added_only_after_user_changes_it(self) -> None:
        row_without_bool = [
            cell for cell in self.field.current_value[0] if cell["fieldId"] != 2
        ]
        self.dialog.close()
        self.dialog = TrackerTableFieldEditorDialog(
            replace(self.field, current_value=[row_without_bool])
        )
        self.dialog.show()
        self._app.processEvents()

        unchanged = self.dialog.value()[0]
        self.assertNotIn(2, {cell["fieldId"] for cell in unchanged})

        critical = self.dialog.cell_widgets[(0, 2)]
        critical.setCurrentIndex(0)
        changed = self.dialog.value()[0]
        self.assertTrue(_cell(changed, 2)["value"])

    def test_new_row_initializes_editable_columns_only(self) -> None:
        self.dialog._add_row()

        rows = self.dialog.value()

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {cell["fieldId"] for cell in rows[1]},
            {1, 2, 3},
        )

    def test_duplicate_copies_only_editable_visible_cells(self) -> None:
        self.dialog.table.selectRow(0)
        self.dialog._duplicate_row()

        rows = self.dialog.value()

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {cell["fieldId"] for cell in rows[1]},
            {1, 2, 3},
        )

    def test_delete_all_rows_requires_explicit_confirmation(self) -> None:
        self.dialog.table.selectRow(0)
        self.dialog._delete_row()

        self.assertEqual(self.dialog.table.rowCount(), 0)
        self.assertTrue(self.dialog.clear_confirmation.isVisible())
        self.assertFalse(self.dialog.apply_button.isEnabled())

        self.dialog.clear_confirmation.setChecked(True)
        self._app.processEvents()

        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertEqual(self.dialog.value(), [])

    def test_referred_test_step_row_is_locked(self) -> None:
        referred_row = [
            {
                "fieldId": 500,
                "name": "Reference",
                "type": "ReferredTestStepFieldValue",
                "value": "Locked",
            }
        ]
        self.dialog.close()
        self.dialog = TrackerTableFieldEditorDialog(
            replace(self.field, current_value=[referred_row])
        )
        self.dialog.show()
        self._app.processEvents()
        self.dialog.table.selectRow(0)

        self.assertFalse(self.dialog.duplicate_row_button.isEnabled())
        self.assertFalse(self.dialog.delete_row_button.isEnabled())
        self.assertFalse(self.dialog.move_up_button.isEnabled())
        self.assertFalse(self.dialog.move_down_button.isEnabled())
        self.assertIn("🔒", self.dialog.table.verticalHeaderItem(0).text())

    def test_columns_rows_scroll_and_window_are_user_resizable(self) -> None:
        self.assertEqual(
            self.dialog.table.horizontalHeader().sectionResizeMode(0),
            QHeaderView.ResizeMode.Interactive,
        )
        self.assertEqual(
            self.dialog.table.verticalHeader().sectionResizeMode(0),
            QHeaderView.ResizeMode.Interactive,
        )
        self.assertEqual(
            self.dialog.table.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertLessEqual(self.dialog.table.rowHeight(0), 140)

        self.dialog.fullscreen_button.setChecked(True)
        self._app.processEvents()
        self.assertTrue(self.dialog.isFullScreen())

        self.dialog.fullscreen_button.setChecked(False)
        self._app.processEvents()
        self.assertFalse(self.dialog.isFullScreen())


if __name__ == "__main__":
    unittest.main()
