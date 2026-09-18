from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from src.gui.settings_store import GuiSettings
from src.gui.tracker_bulk_update import BulkFieldChange
from src.gui.tracker_bulk_update import BulkUpdateRunStore
from src.gui.tracker_bulk_update import TrackerBulkUpdateService
from src.gui.tracker_bulk_update import build_bulk_field_values
from src.gui.tracker_bulk_update_dialog import TrackerBulkUpdateDialog
from src.gui.tracker_item_editor import build_create_tracker_schema


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
            "name": "Reviewers",
            "type": "ReferenceField",
            "valueModel": "ChoiceFieldValue<UserReference>",
            "referenceType": "UserReference",
            "multipleValues": True,
        },
        {
            "id": 10,
            "name": "Steps",
            "type": "TableField",
            "valueModel": "TableFieldValue",
            "columns": [
                {
                    "id": 1001,
                    "name": "Action",
                    "type": "WikiTextField",
                    "valueModel": "WikiTextFieldValue",
                }
            ],
        },
    ],
}


class BulkClient:
    calls: list[tuple] = []
    failure_ids: set[int] = set()

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.failure_ids = set()

    def bulk_update_item_fields(self, operations, *, atomic=True):
        copied = deepcopy(operations)
        self.__class__.calls.append((copied, atomic))
        failed = [
            {"id": operation["itemId"], "exceptionMessage": "failed"}
            for operation in copied
            if operation["itemId"] in self.__class__.failure_ids
        ]
        if failed:
            return {
                "successfulOperationsCount": 0 if atomic else len(copied) - len(failed),
                "failedOperations": failed,
            }
        return {"successfulOperationsCount": len(copied)}


class TrackerBulkUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        BulkClient.reset()
        self.settings = GuiSettings(
            base_url="https://example.test/cb",
            username="sample",
            password="placeholder",
        )
        self.schema = build_create_tracker_schema(SCHEMA, 20)
        self.service = TrackerBulkUpdateService(client_factory=BulkClient)

    def field(self, field_id: int):
        return next(value for value in self.schema.fields if value.field_id == field_id)

    def test_payload_supports_status_table_and_explicit_clear(self) -> None:
        values = build_bulk_field_values(
            self.schema,
            (
                BulkFieldChange(self.field(7), 2),
                BulkFieldChange(
                    self.field(10),
                    [[{"fieldId": 1001, "type": "WikiTextFieldValue", "value": "Run"}]],
                ),
                BulkFieldChange(self.field(8), clear=True),
            ),
        )

        by_id = {value["fieldId"]: value for value in values}
        self.assertEqual(by_id[7]["values"][0]["id"], 2)
        self.assertEqual(by_id[10]["values"][0][0]["value"], "Run")
        self.assertEqual(by_id[8]["values"], [])

    def test_mandatory_and_status_fields_cannot_be_cleared(self) -> None:
        for field_id in (3, 7):
            with self.subTest(field_id=field_id), self.assertRaisesRegex(ValueError, "값 비우기"):
                build_bulk_field_values(
                    self.schema,
                    (BulkFieldChange(self.field(field_id), clear=True),),
                )

    def test_service_chunks_without_total_limit(self) -> None:
        result = self.service.execute(
            self.settings,
            tracker_id=20,
            item_ids=range(1, 2502),
            schema=self.schema,
            changes=(BulkFieldChange(self.field(3), "Changed"),),
            atomic=True,
            chunk_size=1000,
        )

        self.assertEqual([len(call[0]) for call in BulkClient.calls], [1000, 1000, 501])
        self.assertTrue(all(call[1] for call in BulkClient.calls))
        self.assertEqual(len(result.successful_item_ids), 2501)
        self.assertEqual(result.retry_item_ids, ())

    def test_atomic_failure_rolls_back_whole_chunk_for_retry(self) -> None:
        BulkClient.failure_ids = {2}

        result = self.service.execute(
            self.settings,
            tracker_id=20,
            item_ids=(1, 2, 3, 4),
            schema=self.schema,
            changes=(BulkFieldChange(self.field(3), "Changed"),),
            atomic=True,
            chunk_size=3,
        )

        self.assertEqual(result.failed_item_ids, (2,))
        self.assertEqual(result.rolled_back_item_ids, (1, 3))
        self.assertEqual(result.successful_item_ids, (4,))
        self.assertEqual(result.retry_item_ids, (2, 1, 3))

    def test_non_atomic_failure_retries_only_failed_items(self) -> None:
        BulkClient.failure_ids = {2}

        result = self.service.execute(
            self.settings,
            tracker_id=20,
            item_ids=(1, 2, 3),
            schema=self.schema,
            changes=(BulkFieldChange(self.field(3), "Changed"),),
            atomic=False,
            chunk_size=1000,
        )

        self.assertEqual(result.successful_item_ids, (1, 3))
        self.assertEqual(result.rolled_back_item_ids, ())
        self.assertEqual(result.retry_item_ids, (2,))

    def test_cancel_is_applied_between_chunks(self) -> None:
        should_cancel = False

        def event_callback(event):
            nonlocal should_cancel
            should_cancel = event["completed"] >= 2

        result = self.service.execute(
            self.settings,
            tracker_id=20,
            item_ids=(1, 2, 3, 4),
            schema=self.schema,
            changes=(BulkFieldChange(self.field(3), "Changed"),),
            chunk_size=2,
            event_callback=event_callback,
            cancel_requested=lambda: should_cancel,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(result.unattempted_item_ids, (3, 4))

    def test_persistent_retry_store_excludes_field_values(self) -> None:
        BulkClient.failure_ids = {2}
        result = self.service.execute(
            self.settings,
            tracker_id=20,
            item_ids=(1, 2),
            schema=self.schema,
            changes=(BulkFieldChange(self.field(3), "secret business value"),),
            atomic=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bulk.json"
            store = BulkUpdateRunStore(path)
            store.append(result)
            restored = store.get(result.run_id)
            raw = path.read_text(encoding="utf-8")

        self.assertEqual(restored.retry_item_ids, (2,))
        self.assertNotIn("secret business value", raw)
        self.assertEqual(json.loads(raw)["version"], 1)

    def test_dialog_supports_status_and_remembers_chunk_request(self) -> None:
        from PySide6.QtCore import Qt

        dialog = TrackerBulkUpdateDialog(
            self.schema,
            tracker_name="Requirements",
            target_count=3,
            initial_chunk_size=2500,
        )
        status_row = dialog.rows[7]
        status_row.include_item.setCheckState(Qt.CheckState.Checked)
        status_row.input_widget.setCurrentIndex(
            status_row.input_widget.findData(2)
        )

        request = dialog._build_request()

        self.assertEqual(request.chunk_size, 2500)
        self.assertTrue(request.atomic)
        self.assertEqual(request.changes[0].field.field_id, 7)
        self.assertEqual(request.changes[0].value, 2)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
