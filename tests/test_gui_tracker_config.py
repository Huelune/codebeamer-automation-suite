from __future__ import annotations

import unittest

import pandas as pd

from src.gui.tracker_config import TrackerConfigurationService
from src.models import TrackerItemResolutionMode
from src.upload_policy import DEFAULT_TRACKER_ITEM_ID_REGEX
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class TrackerConfigurationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = TrackerConfigurationService()
        self.schema_df = pd.DataFrame(
            [
                {
                    "field_id": 101,
                    "field_name": "Related Item",
                    "field_label": "Related Item",
                    "field_type": "TrackerItemChoiceField",
                },
                {
                    "field_id": 102,
                    "field_name": "Summary",
                    "field_label": "Summary",
                    "field_type": "TextField",
                },
            ]
        )

    def test_only_mapped_tracker_item_fields_become_candidates(self) -> None:
        candidates = self.service.build_field_candidates(
            self.schema_df,
            {"related_item": "Related Item", "summary": "Summary"},
        )

        self.assertEqual(
            [(candidate.df_column, candidate.schema_field) for candidate in candidates],
            [("related_item", "Related Item")],
        )

    def test_legacy_query_setting_is_normalized_to_regex(self) -> None:
        candidates, settings = self.service.normalize_settings(
            self.schema_df,
            {"related_item": "Related Item"},
            {"Related Item": {"mode": TrackerItemResolutionMode.QUERY.value, "source_tracker_ids": [777]}},
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            settings["Related Item"],
            {"mode": TrackerItemResolutionMode.REGEX.value, "regex_pattern": DEFAULT_TRACKER_ITEM_ID_REGEX},
        )

    def test_saved_regex_pattern_is_kept(self) -> None:
        _candidates, settings = self.service.normalize_settings(
            self.schema_df,
            {"related_item": "Related Item"},
            {"Related Item": {"mode": "regex", "regex_pattern": r"REQ-(\d+)"}},
        )

        self.assertEqual(settings["Related Item"]["regex_pattern"], r"REQ-(\d+)")


if __name__ == "__main__":
    unittest.main()
