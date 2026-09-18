from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.models import PayloadStatus
from src.wizard_update_payload import WizardUpdatePayloadService


class WizardUpdatePayloadServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WizardUpdatePayloadService(
            state=SimpleNamespace(existing_item_cache={}),
            client=Mock(),
            build_row_item=Mock(),
            serialize_payload_value=lambda value: value,
            raise_payload_error=Mock(),
        )

    def test_parse_update_item_id_accepts_excel_integer_float(self) -> None:
        self.assertEqual(self.service._parse_update_item_id(123.0), 123)

    def test_merge_custom_fields_preserves_unmodified_existing_fields(self) -> None:
        merged = self.service._merge_custom_fields(
            [
                {"fieldId": 1, "value": "old"},
                {"fieldId": 2, "value": "preserved"},
            ],
            [{"fieldId": 1, "value": "new"}],
        )

        self.assertEqual(
            merged,
            [
                {"fieldId": 1, "value": "new"},
                {"fieldId": 2, "value": "preserved"},
            ],
        )

    def test_upsert_update_below_new_parent_is_blocked(self) -> None:
        source_df = pd.DataFrame(
            [
                {"_row_id": 1, "parent_row_id": None},
                {"_row_id": 2, "parent_row_id": 1},
            ]
        )
        payload_df = pd.DataFrame(
            [
                {
                    "_row_id": 1,
                    "_operation": "create",
                    "payload_status": PayloadStatus.READY.value,
                    "payload_json": {"name": "new parent"},
                    "payload_error": None,
                },
                {
                    "_row_id": 2,
                    "_operation": "update",
                    "payload_status": PayloadStatus.READY.value,
                    "payload_json": {"id": 20},
                    "payload_error": None,
                },
            ]
        )

        self.service._apply_upsert_hierarchy_validation(payload_df, source_df)

        self.assertEqual(
            payload_df.iloc[1]["payload_status"],
            PayloadStatus.FAILED.value,
        )
        self.assertIn(
            "UPSERT_UPDATE_WITH_NEW_ANCESTOR",
            payload_df.iloc[1]["payload_error"],
        )


if __name__ == "__main__":
    unittest.main()
