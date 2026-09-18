from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.upload_policy import UPLOAD_MODE_UPSERT
from src.wizard_option_resolution import WizardOptionResolutionService
from src.wizard_update_payload import WizardUpdatePayloadService


class WizardOptionResolutionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = SimpleNamespace(
            upload_mode=UPLOAD_MODE_UPSERT,
            selected_mapping_modes={
                "Status": {"create": False, "update": True}
            },
        )
        self.service = WizardOptionResolutionService(
            state=self.state,
            mapper=Mock(),
            update_item_id_column_name=WizardUpdatePayloadService._update_item_id_column_name,
            parse_update_item_id=WizardUpdatePayloadService._parse_update_item_id,
            has_configured_value=lambda value: value not in (None, ""),
            invalidate_payload_cache=Mock(),
            decorate_tracker_item_option_maps=Mock(),
            resolve_user_reference_fields=Mock(),
            resolve_tracker_item_reference_fields=Mock(),
            resolve_member_reference_fields=Mock(),
            resolve_default_field_values=Mock(),
        )

    def test_update_only_option_is_masked_for_upsert_create_row(self) -> None:
        source_df = pd.DataFrame(
            [
                {"id": "", "Status": "Open"},
                {"id": 100, "Status": "Closed"},
            ]
        )

        masked = self.service._mask_inapplicable_option_rows(
            source_df,
            {"Status": "Status"},
        )

        self.assertEqual(masked.iloc[0]["Status"], "")
        self.assertEqual(masked.iloc[1]["Status"], "Closed")

    def test_restore_option_source_columns_preserves_original_display(self) -> None:
        restored = self.service._restore_option_source_columns(
            pd.DataFrame([{"Status": "", "Status__resolved": {"id": 1}}]),
            pd.DataFrame([{"Status": "Open"}]),
            {"Status": "Status"},
        )

        self.assertEqual(restored.iloc[0]["Status"], "Open")


if __name__ == "__main__":
    unittest.main()
