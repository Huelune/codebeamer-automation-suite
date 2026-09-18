from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.tracker_condition_builder import TrackerConditionBuilder
from src.gui.tracker_condition_builder import TrackerConditionDialog
from src.gui.tracker_condition_builder import query_field_specs
from src.gui.tracker_item_editor import build_create_tracker_schema


SCHEMA = {
    "id": 20,
    "fields": [
        {
            "id": 0,
            "name": "ID",
            "type": "IntegerField",
            "valueModel": "IntegerFieldValue",
            "trackerItemField": "id",
        },
        {
            "id": 3,
            "name": "Summary",
            "type": "TextField",
            "valueModel": "TextFieldValue",
            "trackerItemField": "name",
        },
        {
            "id": 7,
            "name": "Status",
            "type": "OptionChoiceField",
            "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            "trackerItemField": "status",
            "options": [{"id": 1, "name": "Open"}, {"id": 2, "name": "Closed"}],
        },
        {
            "id": 11,
            "name": "Risk Level",
            "type": "TextField",
            "valueModel": "TextFieldValue",
        },
        {
            "id": 12,
            "name": "Test Steps",
            "type": "TableField",
            "valueModel": "TableFieldValue",
            "columns": [{"id": 1201, "name": "Action", "type": "TextField"}],
        },
    ],
}


class TrackerConditionBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.schema = build_create_tracker_schema(SCHEMA, 20)
        self.builder = TrackerConditionBuilder()
        self.builder.set_schema(self.schema)

    def tearDown(self) -> None:
        self.builder.close()

    def test_query_fields_include_system_and_custom_but_exclude_table(self) -> None:
        specs = query_field_specs(self.schema)
        names = {spec.query_name for spec in specs}

        self.assertIn("item.id", names)
        self.assertIn("summary", names)
        self.assertIn("status", names)
        self.assertIn("Risk Level", names)
        self.assertNotIn("Test Steps", names)

    def test_groups_build_and_or_query_with_condition_not(self) -> None:
        first = self.builder.groups[0].rows[0]
        first.field_combo.setCurrentIndex(
            next(
                index
                for index in range(first.field_combo.count())
                if first.field_combo.itemData(index).query_name == "status"
            )
        )
        first.operator_combo.setCurrentIndex(first.operator_combo.findData("not_equals"))
        first.value_input.setText("Closed")

        second_group = self.builder.add_group()
        second = second_group.rows[0]
        second.field_combo.setCurrentIndex(
            next(
                index
                for index in range(second.field_combo.count())
                if second.field_combo.itemData(index).query_name == "Risk Level"
            )
        )
        second.operator_combo.setCurrentIndex(second.operator_combo.findData("contains"))
        second.value_input.setText("High")

        groups = self.builder.values()
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].conditions[0].to_cbql(), "status != 'Closed'")
        self.assertEqual(
            groups[1].conditions[0].to_cbql(),
            "'Risk Level' LIKE '%High%'",
        )

    def test_in_operator_uses_semicolon_separated_values(self) -> None:
        row = self.builder.groups[0].rows[0]
        row.field_combo.setCurrentIndex(
            next(
                index
                for index in range(row.field_combo.count())
                if row.field_combo.itemData(index).query_name == "summary"
            )
        )
        row.operator_combo.setCurrentIndex(row.operator_combo.findData("in"))
        row.value_input.setText("A; B")

        condition = row.condition()

        self.assertEqual(condition.value, ["A", "B"])

    def test_user_labels_explain_condition_logic_without_and_or_terms(self) -> None:
        group = self.builder.groups[0]
        labels = [
            self.builder.helper_label.text(),
            self.builder.add_group_button.text(),
            group.title_label.text(),
            group.add_row_button.text(),
            group.remove_button.text(),
        ]

        self.assertTrue(all("AND" not in label and "OR" not in label for label in labels))
        self.assertIn("모두 만족", group.title_label.text())
        self.assertIn("하나만 만족", self.builder.helper_label.text())

    def test_condition_dialog_provides_large_editor_and_preserves_builder(self) -> None:
        dialog = TrackerConditionDialog()
        try:
            dialog.builder.set_schema(self.schema)
            dialog.show_editor()
            self._app.processEvents()

            self.assertTrue(dialog.isVisible())
            self.assertGreaterEqual(dialog.minimumWidth(), 860)
            self.assertGreaterEqual(dialog.minimumHeight(), 600)
            self.assertIn("조건 묶음 1개", dialog.summary_label.text())
            self.assertIs(dialog.builder.parent(), dialog)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
