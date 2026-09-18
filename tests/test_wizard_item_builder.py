from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.wizard_item_builder import WizardItemBuilderService


class WizardItemBuilderServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = SimpleNamespace(
            schema_df=pd.DataFrame(),
            table_field_mapping={},
        )
        self.service = WizardItemBuilderService(
            state=self.state,
            mapper=Mock(),
            resolve_tracker_item_reference_value=Mock(),
            resolve_user_reference_value=Mock(),
            resolve_member_reference_value=Mock(),
        )

    def test_payload_error_keeps_structured_context(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"\[FIELD_UNSUPPORTED\].*_row_id=7",
        ):
            self.service._raise_payload_error(
                "FIELD_UNSUPPORTED",
                schema_field="Status",
                row_id=7,
                df_col="status",
                detail="unsupported",
            )

    def test_table_field_keeps_nested_payload_shape(self) -> None:
        self.state.table_field_mapping = {
            "Steps": {
                "table_field_name": "Test Steps",
                "column_name": "Action",
            }
        }
        self.state.schema_df = pd.DataFrame(
            [
                {
                    "field_name": "Test Steps",
                    "field_id": 10,
                    "is_table_field": True,
                    "table_columns": [
                        {
                            "id": 11,
                            "name": "Action",
                            "type": "TextField",
                            "valueModel": "TextFieldValue",
                        }
                    ],
                }
            ]
        )

        fields = self.service._build_table_custom_fields(
            pd.Series({"Steps": ["Open", "Close"]})
        )

        self.assertEqual(len(fields), 1)
        self.assertEqual(len(fields[0].values), 2)
        self.assertEqual(fields[0].values[0][0].value, "Open")


if __name__ == "__main__":
    unittest.main()
