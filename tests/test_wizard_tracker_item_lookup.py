from __future__ import annotations

import unittest

import pandas as pd

from src.mapping_service import MappingService
from src.models import TrackerItemResolutionMode
from src.wizard import CodebeamerUploadWizard


class FakeTrackerItemClient:
    def __init__(self) -> None:
        self.search_calls: list[tuple[int, str]] = []

    def search_tracker_items_by_name(self, *, tracker_id: int, name: str, **kwargs):
        del kwargs
        self.search_calls.append((tracker_id, name))
        return [{"id": 999, "name": name, "type": "TrackerItemReference"}]


class WizardTrackerItemLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeTrackerItemClient()
        self.mapper = MappingService()
        self.wizard = CodebeamerUploadWizard(
            client=self.client,
            processor=None,
            mapper=self.mapper,
        )
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 15,
                "name": "연관 요구사항",
                "type": "TrackerItemChoiceField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            }
        ])
        self.wizard.state.schema_df["tracker_item_source_tracker_ids"] = [[13526611]]

    def test_legacy_query_setting_is_forced_to_id_extraction_without_api_call(self) -> None:
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "related_items": ["[REQ:100]", "[REQ:200]"]},
        ])

        self.wizard.process_option_mapping(
            {"related_items": "연관 요구사항"},
            selected_tracker_item_settings={
                "연관 요구사항": {
                    "mode": TrackerItemResolutionMode.QUERY.value,
                    "source_tracker_ids": [13526611],
                }
            },
        )

        self.assertEqual(self.client.search_calls, [])
        converted = self.wizard.state.converted_upload_df
        self.assertIsNotNone(converted)
        values = converted.iloc[0]["related_items__resolved"]
        self.assertEqual([value["id"] for value in values], [100, 200])

    def test_custom_regex_is_used_even_when_legacy_query_mode_is_saved(self) -> None:
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "related_items": ["item=100", "item=200"]},
        ])

        self.wizard.process_option_mapping(
            {"related_items": "연관 요구사항"},
            selected_tracker_item_settings={
                "연관 요구사항": {
                    "mode": TrackerItemResolutionMode.QUERY.value,
                    "regex_pattern": r"item=(\d+)",
                }
            },
        )

        self.assertEqual(self.client.search_calls, [])
        converted = self.wizard.state.converted_upload_df
        self.assertIsNotNone(converted)
        self.assertEqual(
            [value["id"] for value in converted.iloc[0]["related_items__resolved"]],
            [100, 200],
        )

    def test_non_id_value_fails_validation_without_query_fallback(self) -> None:
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "related_items": ["요구사항 이름만 입력"]},
        ])

        _, option_check_df = self.wizard.process_option_mapping(
            {"related_items": "연관 요구사항"},
            selected_tracker_item_settings={
                "연관 요구사항": {"mode": TrackerItemResolutionMode.QUERY.value}
            },
        )

        self.assertEqual(self.client.search_calls, [])
        self.assertIn("DIRECT_PARSE_FAILED", option_check_df["status"].tolist())
        self.assertNotIn("LOOKUP_REQUIRED", option_check_df["status"].tolist())


if __name__ == "__main__":
    unittest.main()
