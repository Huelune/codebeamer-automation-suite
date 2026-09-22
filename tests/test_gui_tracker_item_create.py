from __future__ import annotations

import os
import unittest
from copy import deepcopy


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.settings_store import GuiSettings
from src.gui.tracker_item_create_dialog import TrackerItemCreateDialog
from src.gui.tracker_item_editor import TrackerItemEditorService
from src.gui.tracker_item_editor import TrackerItemFieldChange
from src.gui.tracker_item_editor import TrackerItemWriteError
from src.gui.tracker_item_editor import TrackerItemWriteErrorKind
from src.gui.tracker_item_editor import build_create_item_payload
from src.gui.tracker_item_editor import build_create_tracker_schema
from src.gui.tracker_query_models import TrackerItemDetail
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


CREATE_SCHEMA = {
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
                    "valueModel": "WikiTextFieldValue",
                },
                {
                    "id": 1002,
                    "name": "Expected",
                    "type": "WikiTextField",
                    "valueModel": "WikiTextFieldValue",
                },
            ],
        },
    ],
}


def _detail(
    item_id: int,
    *,
    name: str,
    tracker_id: int = 20,
    parent_id: int | None = None,
) -> TrackerItemDetail:
    payload = {
        "id": item_id,
        "name": name,
        "version": 1,
        "tracker": {"id": tracker_id, "name": "Requirements"},
        "status": {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
        "customFields": [],
    }
    if parent_id is not None:
        payload["parent"] = {"id": parent_id, "name": "Parent"}
    return TrackerItemDetail.from_raw(
        payload,
        tracker_payload={
            "id": tracker_id,
            "name": "Requirements",
            "project": {"id": 10, "name": "Vehicle"},
        },
    )


class CreateClient:
    calls: list[tuple] = []

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    @classmethod
    def reset(cls) -> None:
        cls.calls = []

    def create_item(
        self,
        tracker_id: int,
        payload: dict,
        parent_item_id: int | None = None,
    ):
        self.__class__.calls.append(
            ("create", tracker_id, deepcopy(payload), parent_item_id)
        )
        return {"id": 2001}


class CreateQueryServiceStub:
    def __init__(self, *, parent_tracker_id: int = 20) -> None:
        self.parent_tracker_id = parent_tracker_id
        self.loaded_ids: list[int] = []

    def load_tracker_schema(self, settings, tracker_id: int):
        del settings
        self.schema_tracker_id = tracker_id
        return deepcopy(CREATE_SCHEMA)

    def load_detail(self, settings, item_id: int):
        del settings
        self.loaded_ids.append(item_id)
        if item_id == 1001:
            return _detail(
                1001,
                name="Parent",
                tracker_id=self.parent_tracker_id,
            )
        return _detail(2001, name="Created", parent_id=1001)


class TrackerItemCreateModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = build_create_tracker_schema(CREATE_SCHEMA, 20)

    def field(self, name: str):
        return next(field for field in self.schema.fields if field.name == name)

    def test_create_schema_has_empty_values_and_payload_separates_builtin_custom(self) -> None:
        payload = build_create_item_payload(
            self.schema,
            (
                TrackerItemFieldChange(self.field("Summary"), "New requirement"),
                TrackerItemFieldChange(self.field("Description"), "Details"),
                TrackerItemFieldChange(self.field("Priority"), 12),
                TrackerItemFieldChange(self.field("Reviewers"), "71\n72"),
            ),
        )

        self.assertTrue(all(field.current_value is None for field in self.schema.fields))
        self.assertEqual(payload["name"], "New requirement")
        self.assertEqual(payload["description"], "Details")
        custom_by_id = {field["fieldId"]: field for field in payload["customFields"]}
        self.assertEqual(custom_by_id[8]["values"][0]["id"], 12)
        self.assertEqual(
            custom_by_id[9]["values"],
            [
                {"id": 71, "type": "UserReference"},
                {"id": 72, "type": "UserReference"},
            ],
        )
        self.assertNotIn("status", payload)

    def test_create_payload_supports_table_field_rows(self) -> None:
        payload = build_create_item_payload(
            self.schema,
            (
                TrackerItemFieldChange(self.field("Summary"), "New requirement"),
                TrackerItemFieldChange(
                    self.field("Test Steps"),
                    [
                        [
                            {
                                "fieldId": 1001,
                                "name": "Action",
                                "type": "WikiTextFieldValue",
                                "value": "Run test",
                            },
                            {
                                "fieldId": 1002,
                                "name": "Expected",
                                "type": "WikiTextFieldValue",
                                "value": "Pass",
                            },
                        ]
                    ],
                ),
            ),
        )

        table_payload = next(
            field for field in payload["customFields"] if field["fieldId"] == 10
        )
        self.assertEqual(table_payload["type"], "TableFieldValue")
        self.assertEqual(table_payload["values"][0][0]["value"], "Run test")

    def test_mandatory_field_and_status_rules_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "필수 필드"):
            build_create_item_payload(self.schema, ())

        with self.assertRaisesRegex(ValueError, "별도의 상태 전환"):
            build_create_item_payload(
                self.schema,
                (
                    TrackerItemFieldChange(self.field("Summary"), "New"),
                    TrackerItemFieldChange(self.field("Status"), 2),
                ),
            )

    def test_unsupported_mandatory_field_blocks_create(self) -> None:
        schema_payload = deepcopy(CREATE_SCHEMA)
        table_field = next(
            field for field in schema_payload["fields"] if field["id"] == 10
        )
        table_field["mandatory"] = True
        table_field.pop("columns")
        schema = build_create_tracker_schema(schema_payload, 20)

        with self.assertRaisesRegex(ValueError, "입력 형식을 지원하지"):
            build_create_item_payload(
                schema,
                (
                    TrackerItemFieldChange(
                        next(field for field in schema.fields if field.name == "Summary"),
                        "New",
                    ),
                ),
            )

    def test_summary_is_required_for_create_even_if_schema_omits_flag(self) -> None:
        schema_payload = deepcopy(CREATE_SCHEMA)
        next(field for field in schema_payload["fields"] if field["id"] == 3)[
            "mandatory"
        ] = False

        schema = build_create_tracker_schema(schema_payload, 20)

        summary = next(field for field in schema.fields if field.name == "Summary")
        self.assertTrue(summary.mandatory)


class TrackerItemCreateServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        CreateClient.reset()
        self.query_service = CreateQueryServiceStub()
        self.service = TrackerItemEditorService(
            client_factory=CreateClient,
            query_service=self.query_service,
        )
        self.settings = GuiSettings(
            base_url="https://example.test/cb",
            username="sample",
            password="placeholder",
        )
        self.schema = self.service.load_create_schema(self.settings, 20)
        self.summary = next(
            field for field in self.schema.fields if field.name == "Summary"
        )

    def test_create_verifies_parent_scope_and_returns_loaded_detail(self) -> None:
        created = self.service.create_item(
            self.settings,
            tracker_id=20,
            schema=self.schema,
            changes=(TrackerItemFieldChange(self.summary, "Created"),),
            parent_item_id=1001,
        )

        self.assertEqual(created.item_id, 2001)
        self.assertEqual(self.query_service.loaded_ids, [1001, 2001])
        self.assertEqual(CreateClient.calls[0][0:2], ("create", 20))
        self.assertEqual(CreateClient.calls[0][2], {"name": "Created"})
        self.assertEqual(CreateClient.calls[0][3], 1001)

    def test_parent_from_another_tracker_is_rejected_before_create(self) -> None:
        service = TrackerItemEditorService(
            client_factory=CreateClient,
            query_service=CreateQueryServiceStub(parent_tracker_id=99),
        )

        with self.assertRaises(TrackerItemWriteError) as raised:
            service.create_item(
                self.settings,
                tracker_id=20,
                schema=self.schema,
                changes=(TrackerItemFieldChange(self.summary, "Created"),),
                parent_item_id=1001,
            )

        self.assertEqual(raised.exception.kind, TrackerItemWriteErrorKind.INVALID_VALUE)
        self.assertIn("현재 트래커", str(raised.exception))
        self.assertEqual(CreateClient.calls, [])

    def test_test_mode_blocks_create_before_client_request(self) -> None:
        with self.assertRaises(TrackerItemWriteError) as raised:
            self.service.create_item(
                GuiSettings(offline_mode=True),
                tracker_id=20,
                schema=self.schema,
                changes=(TrackerItemFieldChange(self.summary, "Created"),),
            )

        self.assertEqual(raised.exception.kind, TrackerItemWriteErrorKind.WRITE_DISABLED)
        self.assertEqual(CreateClient.calls, [])


class TrackerItemCreateDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.schema = build_create_tracker_schema(CREATE_SCHEMA, 20)
        self.parent_detail = _detail(1001, name="Parent")
        self.dialog = TrackerItemCreateDialog(
            self.schema,
            tracker_name="Requirements",
            selected_detail=self.parent_detail,
        )
        self.dialog.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.dialog.close()
        self._app.processEvents()

    def test_clicking_a_row_turns_on_include_and_opens_the_input(self) -> None:
        """값 칸을 눌렀을 때 그 행이 열리는지 확인한다.

        '포함'을 켜야 입력이 열린다는 것을 모르면 값 칸이 고장 난 것처럼 보인다.
        """
        from PySide6.QtCore import Qt

        description_row = self.dialog.rows[4]
        self.assertFalse(description_row.widget.isEnabled())

        self.dialog.field_table.cellClicked.emit(description_row.row, 2)
        self._app.processEvents()

        self.assertEqual(description_row.include_item.checkState(), Qt.CheckState.Checked)
        self.assertTrue(description_row.widget.isEnabled())

    def test_clicking_the_include_column_does_not_double_toggle(self) -> None:
        """포함 열은 Qt 가 직접 토글하므로 우리가 다시 켜면 안 된다."""
        from PySide6.QtCore import Qt

        description_row = self.dialog.rows[4]

        self.dialog.field_table.cellClicked.emit(description_row.row, 0)
        self._app.processEvents()

        self.assertEqual(description_row.include_item.checkState(), Qt.CheckState.Unchecked)

    def test_required_fields_are_fixed_and_optional_fields_are_explicit(self) -> None:
        from PySide6.QtCore import Qt

        summary_row = self.dialog.rows[3]
        description_row = self.dialog.rows[4]

        self.assertEqual(summary_row.include_item.checkState(), Qt.CheckState.Checked)
        self.assertFalse(
            bool(summary_row.include_item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        )
        self.assertTrue(summary_row.widget.isEnabled())
        self.assertEqual(description_row.include_item.checkState(), Qt.CheckState.Unchecked)
        self.assertFalse(description_row.widget.isEnabled())

        description_row.include_item.setCheckState(Qt.CheckState.Checked)
        self._app.processEvents()

        self.assertTrue(description_row.widget.isEnabled())
        self.assertNotIn(7, self.dialog.rows)
        self.assertIn(10, self.dialog.rows)
        self.assertTrue(self.dialog.root_radio.isChecked())
        self.dialog.child_radio.setChecked(True)
        self.assertEqual(self.dialog.selected_parent_item_id(), 1001)

    def test_empty_summary_is_rejected_in_dialog(self) -> None:
        self.dialog._validate_and_accept()

        self.assertIn("Summary", self.dialog.validation_label.text())
        self.assertNotEqual(
            self.dialog.result(),
            TrackerItemCreateDialog.DialogCode.Accepted,
        )

    def test_unsupported_required_field_disables_create(self) -> None:
        self.dialog.close()
        schema_payload = deepcopy(CREATE_SCHEMA)
        next(field for field in schema_payload["fields"] if field["id"] == 10)[
            "mandatory"
        ] = True
        next(field for field in schema_payload["fields"] if field["id"] == 10).pop(
            "columns"
        )
        self.dialog = TrackerItemCreateDialog(
            build_create_tracker_schema(schema_payload, 20),
            tracker_name="Requirements",
        )

        self.assertFalse(self.dialog.create_button.isEnabled())
        self.assertIn("Test Steps", self.dialog.validation_label.text())
        self.assertNotIn(10, self.dialog.rows)

    def test_table_field_uses_shared_row_editor_input(self) -> None:
        from PySide6.QtCore import Qt

        from src.gui.tracker_item_editor_panel import TrackerTableFieldInput

        table_row = self.dialog.rows[10]

        self.assertIsInstance(table_row.widget, TrackerTableFieldInput)
        self.assertFalse(table_row.widget.isEnabled())
        table_row.include_item.setCheckState(Qt.CheckState.Checked)
        self._app.processEvents()
        self.assertTrue(table_row.widget.isEnabled())

    def test_fullscreen_button_toggles_create_window_mode(self) -> None:
        self.dialog.fullscreen_button.setChecked(True)
        self._app.processEvents()

        self.assertTrue(self.dialog.isFullScreen())
        self.assertEqual(self.dialog.fullscreen_button.text(), "창 모드")

        self.dialog.fullscreen_button.setChecked(False)
        self._app.processEvents()

        self.assertFalse(self.dialog.isFullScreen())
        self.assertEqual(self.dialog.fullscreen_button.text(), "전체 화면")


if __name__ == "__main__":
    unittest.main()
