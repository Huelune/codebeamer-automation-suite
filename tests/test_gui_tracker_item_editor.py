from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.settings_store import GuiSettings
from src.gui.tracker_item_editor import FieldEditorKind
from src.gui.tracker_item_editor import TrackerItemEditorService
from src.gui.tracker_item_editor import TrackerItemFieldChange
from src.gui.tracker_item_editor import TrackerItemWriteError
from src.gui.tracker_item_editor import TrackerItemWriteErrorKind
from src.gui.tracker_item_editor import build_editable_tracker_schema
from src.gui.tracker_item_editor import build_field_value
from src.gui.tracker_item_editor_panel import ConfirmItemDeleteDialog
from src.gui.tracker_item_editor_panel import TrackerItemEditorPanel
from src.gui.tracker_query_models import TrackerItemDetail


SCHEMA = {
    "id": 20,
    "fields": [
        {
            "id": 3,
            "name": "Summary",
            "type": "TextField",
            "valueModel": "TextFieldValue",
            "trackerItemField": "name",
            "mandatory": True,
        },
        {
            "id": 4,
            "name": "Description",
            "type": "TextField",
            "valueModel": "TextFieldValue",
            "trackerItemField": "description",
        },
        {
            "id": 5,
            "name": "Approved",
            "type": "BoolField",
            "valueModel": "BoolFieldValue",
        },
        {
            "id": 6,
            "name": "Estimate",
            "type": "IntegerField",
            "valueModel": "IntegerFieldValue",
        },
        {
            "id": 7,
            "name": "Status",
            "type": "OptionChoiceField",
            "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            "trackerItemField": "status",
            "options": [
                {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
                {"id": 2, "name": "Review", "type": "ChoiceOptionReference"},
            ],
        },
        {
            "id": 8,
            "name": "Priority",
            "type": "OptionChoiceField",
            "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            "options": [
                {"id": 11, "name": "High", "type": "ChoiceOptionReference"},
                {"id": 12, "name": "Low", "type": "ChoiceOptionReference"},
            ],
        },
        {
            "id": 9,
            "name": "Reviewers",
            "type": "ReferenceField",
            "referenceType": "UserReference",
            "valueModel": "ChoiceFieldValue<UserReference>",
            "multipleValues": True,
        },
        {
            "id": 10,
            "name": "Test Steps",
            "type": "TableField",
            "valueModel": "TableFieldValue",
            "columns": [
                {
                    "id": 1001,
                    "name": "Action",
                    "type": "WikiTextField",
                },
                {
                    "id": 1002,
                    "name": "Expected",
                    "type": "WikiTextField",
                    "valueModel": "WikiTextFieldValue",
                },
                {
                    "id": 1003,
                    "name": "Critical",
                    "type": "BoolField",
                    "valueModel": "BoolFieldValue",
                },
                {
                    "id": 1004,
                    "name": "Internal ID",
                    "type": "WikiTextField",
                    "valueModel": "WikiTextFieldValue",
                    "hidden": True,
                },
                {
                    "id": 1005,
                    "name": "Linked item",
                    "type": "ReferenceField",
                    "referenceType": "TrackerItemReference",
                    "valueModel": "ChoiceFieldValue<TrackerItemReference>",
                },
            ],
        },
        {
            "id": 11,
            "name": "Server Value",
            "type": "TextField",
            "valueModel": "TextFieldValue",
            "readOnly": True,
        },
        {
            "id": 12,
            "name": "Hidden",
            "type": "TextField",
            "valueModel": "TextFieldValue",
            "hidden": True,
        },
    ],
}


def _detail(*, version: int = 4, name: str = "Original") -> TrackerItemDetail:
    return TrackerItemDetail.from_raw(
        {
            "id": 1001,
            "name": name,
            "description": "Before",
            "descriptionFormat": "PlainText",
            "version": version,
            "tracker": {"id": 20, "name": "Requirements"},
            "status": {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
            "customFields": [
                {
                    "fieldId": 5,
                    "name": "Approved",
                    "type": "BoolFieldValue",
                    "value": False,
                },
                {
                    "fieldId": 8,
                    "name": "Priority",
                    "type": "ChoiceFieldValue",
                    "values": [
                        {"id": 11, "name": "High", "type": "ChoiceOptionReference"}
                    ],
                },
                {
                    "fieldId": 9,
                    "name": "Reviewers",
                    "type": "ChoiceFieldValue",
                    "values": [
                        {"id": 71, "name": "sample_user", "type": "UserReference"}
                    ],
                },
                {
                    "fieldId": 10,
                    "name": "Test Steps",
                    "type": "TableFieldValue",
                    "values": [
                        [
                            {
                                "fieldId": 1001,
                                "name": "Action",
                                "type": "WikiTextFieldValue",
                                "value": "Run",
                            },
                            {
                                "fieldId": 1002,
                                "name": "Expected",
                                "type": "WikiTextFieldValue",
                                "value": "Pass",
                            },
                            {
                                "fieldId": 1003,
                                "name": "Critical",
                                "type": "BoolFieldValue",
                                "value": False,
                            },
                            {
                                "fieldId": 1004,
                                "name": "Internal ID",
                                "type": "WikiTextFieldValue",
                                "value": "hidden-1",
                            },
                            {
                                "fieldId": 1005,
                                "name": "Linked item",
                                "type": "ChoiceFieldValue",
                                "values": [
                                    {"id": 9001, "type": "TrackerItemReference"}
                                ],
                            },
                        ]
                    ],
                },
            ],
        },
        tracker_payload={
            "id": 20,
            "name": "Requirements",
            "project": {"id": 10, "name": "Vehicle"},
        },
    )


class EditorFakeClient:
    calls: list[tuple] = []
    current_version = 4

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.current_version = 4

    def get_item(self, item_id: int):
        self.__class__.calls.append(("get", item_id))
        return {"id": item_id, "version": self.__class__.current_version}

    def update_item_fields(self, item_id: int, field_values: list[dict]):
        self.__class__.calls.append(("update", item_id, field_values))
        self.__class__.current_version += 1
        return {"id": item_id, "version": self.__class__.current_version}

    def delete_item(self, item_id: int):
        self.__class__.calls.append(("delete", item_id))
        return {}


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _UnsafeHttpError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.response = _Response(status_code)
        super().__init__("unsafe server response containing sensitive detail")


class ForbiddenEditorClient(EditorFakeClient):
    def update_item_fields(self, item_id: int, field_values: list[dict]):
        del item_id, field_values
        raise _UnsafeHttpError(403)


class EditorQueryServiceStub:
    def __init__(self) -> None:
        self.updated_detail = _detail(version=5, name="Changed")

    def load_tracker_schema(self, settings, tracker_id: int):
        del settings
        self.last_tracker_id = tracker_id
        return SCHEMA

    def load_detail(self, settings, item_id: int):
        del settings
        self.last_item_id = item_id
        return self.updated_detail


class TrackerItemEditorModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.detail = _detail()
        self.schema = build_editable_tracker_schema(SCHEMA, self.detail)

    def field(self, name: str):
        return next(field for field in self.schema.fields if field.name == name)

    def test_schema_normalizes_supported_fields_and_keeps_unsupported_reason(self) -> None:
        self.assertEqual(self.field("Summary").editor_kind, FieldEditorKind.TEXT)
        self.assertEqual(
            self.field("Description").editor_kind,
            FieldEditorKind.MULTILINE_TEXT,
        )
        self.assertEqual(self.field("Approved").current_value, False)
        self.assertEqual(self.field("Priority").current_display_value, "High")
        self.assertEqual(self.field("Reviewers").reference_type, "UserReference")
        self.assertEqual(self.schema.status_field.name, "Status")
        table_field = self.field("Test Steps")
        self.assertTrue(table_field.editable)
        self.assertEqual(table_field.editor_kind, FieldEditorKind.TABLE)
        self.assertEqual(table_field.current_display_value, "1행 × 4열")
        self.assertEqual(
            [column.name for column in table_field.table_columns],
            ["Action", "Expected", "Critical", "Linked item"],
        )
        self.assertFalse(table_field.table_columns[-1].editable)
        self.assertEqual(
            table_field.table_columns[0].value_model,
            "WikiTextFieldValue",
        )
        self.assertFalse(self.field("Server Value").editable)
        self.assertNotIn("Hidden", {field.name for field in self.schema.fields})

    def test_build_field_values_uses_schema_value_models(self) -> None:
        summary = build_field_value(
            TrackerItemFieldChange(self.field("Summary"), "Changed")
        )
        approved = build_field_value(
            TrackerItemFieldChange(self.field("Approved"), True)
        )
        priority = build_field_value(
            TrackerItemFieldChange(self.field("Priority"), 12)
        )
        reviewers = build_field_value(
            TrackerItemFieldChange(self.field("Reviewers"), "71\n72")
        )

        self.assertEqual(summary["value"], "Changed")
        self.assertEqual(summary["type"], "TextFieldValue")
        self.assertIs(approved["value"], True)
        self.assertEqual(priority["values"][0]["name"], "Low")
        self.assertEqual(
            reviewers["values"],
            [
                {"id": 71, "type": "UserReference"},
                {"id": 72, "type": "UserReference"},
            ],
        )

    def test_table_field_payload_preserves_nested_rows_and_hidden_cells(self) -> None:
        table_field = self.field("Test Steps")
        rows = deepcopy(table_field.current_value)
        rows[0][0]["value"] = "Changed action"

        payload = build_field_value(TrackerItemFieldChange(table_field, rows))

        self.assertEqual(payload["type"], "TableFieldValue")
        self.assertEqual(payload["values"][0][0]["value"], "Changed action")
        hidden = next(
            cell for cell in payload["values"][0] if cell["fieldId"] == 1004
        )
        self.assertEqual(hidden["value"], "hidden-1")

    def test_table_field_rejects_flat_or_duplicate_cell_payloads(self) -> None:
        table_field = self.field("Test Steps")

        with self.assertRaisesRegex(ValueError, "행 구조"):
            build_field_value(
                TrackerItemFieldChange(table_field, [{"fieldId": 1001}])
            )

        duplicate = deepcopy(table_field.current_value)
        duplicate[0].append(deepcopy(duplicate[0][0]))
        with self.assertRaisesRegex(ValueError, "중복"):
            build_field_value(TrackerItemFieldChange(table_field, duplicate))

    def test_mandatory_and_single_value_rules_are_validated_before_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "필수값"):
            build_field_value(TrackerItemFieldChange(self.field("Summary"), ""))

        single_reference = self.field("Reviewers")
        single_reference = type(single_reference)(
            **{**single_reference.__dict__, "multiple_values": False}
        )
        with self.assertRaisesRegex(ValueError, "하나의 참조"):
            build_field_value(
                TrackerItemFieldChange(single_reference, "71\n72")
            )

    def test_status_is_built_as_choice_field_value_but_not_general_edit_field(self) -> None:
        status = self.schema.status_field

        payload = build_field_value(TrackerItemFieldChange(status, 2))

        self.assertFalse(status.editable)
        self.assertEqual(payload["type"], "ChoiceFieldValue")
        self.assertEqual(payload["values"][0]["name"], "Review")


class TrackerItemEditorServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        EditorFakeClient.reset()
        self.query_service = EditorQueryServiceStub()
        self.service = TrackerItemEditorService(
            client_factory=EditorFakeClient,
            query_service=self.query_service,
        )
        self.settings = GuiSettings(
            base_url="https://example.test/cb",
            username="sample",
            password="placeholder",
        )
        self.detail = _detail()
        self.schema = self.service.load_schema(self.settings, self.detail)

    def field(self, name: str):
        return next(field for field in self.schema.fields if field.name == name)

    def test_update_checks_version_and_sends_only_selected_fields(self) -> None:
        updated = self.service.update_fields(
            self.settings,
            item_id=1001,
            expected_version=4,
            changes=(
                TrackerItemFieldChange(self.field("Summary"), "Changed"),
                TrackerItemFieldChange(self.field("Approved"), True),
            ),
        )

        self.assertEqual(updated.summary.name, "Changed")
        self.assertEqual(EditorFakeClient.calls[0], ("get", 1001))
        update_call = EditorFakeClient.calls[1]
        self.assertEqual(update_call[0:2], ("update", 1001))
        self.assertEqual(
            {field_value["fieldId"] for field_value in update_call[2]},
            {3, 5},
        )

    def test_update_sends_table_field_as_nested_rows(self) -> None:
        table_field = self.field("Test Steps")

        self.service.update_fields(
            self.settings,
            item_id=1001,
            expected_version=4,
            changes=(
                TrackerItemFieldChange(table_field, table_field.current_value),
            ),
        )

        table_payload = EditorFakeClient.calls[1][2][0]
        self.assertEqual(table_payload["type"], "TableFieldValue")
        self.assertIsInstance(table_payload["values"][0], list)
        self.assertEqual(table_payload["values"][0][0]["fieldId"], 1001)

    def test_version_conflict_stops_before_update(self) -> None:
        EditorFakeClient.current_version = 9

        with self.assertRaises(TrackerItemWriteError) as raised:
            self.service.update_fields(
                self.settings,
                item_id=1001,
                expected_version=4,
                changes=(TrackerItemFieldChange(self.field("Summary"), "Changed"),),
            )

        self.assertEqual(raised.exception.kind, TrackerItemWriteErrorKind.CONFLICT)
        self.assertEqual(EditorFakeClient.calls, [("get", 1001)])

    def test_status_field_change_uses_status_field_only(self) -> None:
        self.service.change_status_field(
            self.settings,
            item_id=1001,
            expected_version=4,
            status_field=self.schema.status_field,
            option_id=2,
        )

        update_call = EditorFakeClient.calls[1]
        self.assertEqual(len(update_call[2]), 1)
        self.assertEqual(update_call[2][0]["fieldId"], 7)
        self.assertEqual(update_call[2][0]["values"][0]["id"], 2)

    def test_delete_checks_version_before_destructive_request(self) -> None:
        self.service.delete_item(
            self.settings,
            item_id=1001,
            expected_version=4,
        )

        self.assertEqual(EditorFakeClient.calls, [("get", 1001), ("delete", 1001)])

    def test_test_mode_blocks_all_write_requests(self) -> None:
        offline_settings = GuiSettings(offline_mode=True)

        with self.assertRaises(TrackerItemWriteError) as raised:
            self.service.delete_item(
                offline_settings,
                item_id=1001,
                expected_version=4,
            )

        self.assertEqual(raised.exception.kind, TrackerItemWriteErrorKind.WRITE_DISABLED)
        self.assertEqual(EditorFakeClient.calls, [])

    def test_http_write_error_is_classified_without_leaking_server_message(self) -> None:
        service = TrackerItemEditorService(
            client_factory=ForbiddenEditorClient,
            query_service=self.query_service,
        )

        with self.assertRaises(TrackerItemWriteError) as raised:
            service.update_fields(
                self.settings,
                item_id=1001,
                expected_version=4,
                changes=(TrackerItemFieldChange(self.field("Summary"), "Changed"),),
            )

        self.assertEqual(raised.exception.kind, TrackerItemWriteErrorKind.FORBIDDEN)
        self.assertNotIn("unsafe server response", str(raised.exception))


class TrackerItemEditorPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.detail = _detail()
        self.schema = build_editable_tracker_schema(SCHEMA, self.detail)
        self.saved_changes = None
        self.transition = None
        self.delete_requested = False
        self.panel = TrackerItemEditorPanel(
            save_requested=lambda changes: setattr(self, "saved_changes", changes),
            transition_requested=lambda field, option_id: setattr(
                self,
                "transition",
                (field, option_id),
            ),
            delete_requested=lambda: setattr(self, "delete_requested", True),
        )
        self.panel.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.panel.close()
        self._app.processEvents()

    def test_panel_uses_explicit_checkboxes_and_type_aware_widgets(self) -> None:
        from PySide6.QtCore import Qt

        self.panel.set_context(self.detail, self.schema, write_enabled=True)
        summary_field = next(field for field in self.schema.fields if field.name == "Summary")
        summary_row = self.panel.rows[summary_field.field_id]
        check_item = self.panel.field_table.item(summary_row.row, 0)

        self.assertFalse(summary_row.widget.isEnabled())
        check_item.setCheckState(Qt.CheckState.Checked)
        self._app.processEvents()
        summary_row.widget.setText("Changed in GUI")

        self.assertTrue(summary_row.widget.isEnabled())
        self.assertTrue(self.panel.save_button.isEnabled())
        self.panel.save_button.click()
        self.assertEqual(len(self.saved_changes), 1)
        self.assertEqual(self.saved_changes[0].value, "Changed in GUI")

    def test_panel_shows_table_editor_and_hides_uneditable_fields(self) -> None:
        from src.gui.tracker_item_editor_panel import TrackerTableFieldInput

        self.panel.set_context(self.detail, self.schema, write_enabled=True)

        self.assertNotIn(11, self.panel.rows)
        table_row = self.panel.rows[10]
        self.assertIsInstance(table_row.widget, TrackerTableFieldInput)
        self.assertEqual(table_row.widget.summary_label.text(), "1행 × 4열")
        self.assertIn("1개", self.panel.editor_helper.text())

    def test_panel_applies_table_dialog_value_to_selected_change(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog

        self.panel.set_context(self.detail, self.schema, write_enabled=True)
        table_row = self.panel.rows[10]
        check_item = self.panel.field_table.item(table_row.row, 0)
        check_item.setCheckState(Qt.CheckState.Checked)
        changed_rows = deepcopy(table_row.field.current_value)
        changed_rows.append(deepcopy(changed_rows[0]))

        with patch(
            "src.gui.tracker_table_field_editor_dialog."
            "TrackerTableFieldEditorDialog"
        ) as dialog_class:
            dialog = dialog_class.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.value.return_value = changed_rows
            table_row.widget.edit_button.click()

        changes = self.panel.selected_changes()
        self.assertEqual(table_row.widget.summary_label.text(), "2행 × 4열")
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].field.field_id, 10)
        self.assertEqual(changes[0].value, changed_rows)

    def test_status_transition_is_separate_from_general_field_save(self) -> None:
        self.panel.set_context(self.detail, self.schema, write_enabled=True)

        self.assertEqual(self.panel.current_status_label.text(), "Open")
        self.assertFalse(self.panel.transition_button.isEnabled())
        self.panel.status_combo.setCurrentIndex(self.panel.status_combo.findData(2))
        self._app.processEvents()

        self.assertTrue(self.panel.transition_button.isEnabled())
        self.assertEqual(self.panel.transition_button.text(), "상태 필드 변경")
        self.panel.transition_button.click()
        self.assertEqual(self.transition[0].name, "Status")
        self.assertEqual(self.transition[1], 2)

    def test_test_mode_shows_fields_but_disables_all_write_actions(self) -> None:
        self.panel.set_context(self.detail, self.schema, write_enabled=False)

        self.assertGreater(self.panel.field_table.rowCount(), 0)
        self.assertFalse(self.panel.save_button.isEnabled())
        self.assertFalse(self.panel.transition_button.isEnabled())
        self.assertFalse(self.panel.delete_button.isEnabled())
        self.assertIn("테스트 모드", self.panel.editor_status.text())
        self.assertTrue(self.panel.rows[10].widget.isEnabled())

    def test_delete_dialog_requires_exact_item_id(self) -> None:
        dialog = ConfirmItemDeleteDialog(self.detail)
        try:
            dialog.confirm_input.setText("100")
            self.assertFalse(dialog.delete_button.isEnabled())
            dialog.confirm_input.setText("1001")
            self.assertTrue(dialog.delete_button.isEnabled())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
