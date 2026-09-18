from __future__ import annotations

import unittest

import pandas as pd

from src.gui.tracker_config import TRACKER_ITEM_QUERY_STATUS_SUPPORTED
from src.gui.tracker_config import TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED
from src.gui.tracker_config import TrackerConfigurationService
from src.models import TrackerItemResolutionMode
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
                }
            ]
        )

    def test_tracker_configuration_enables_query_by_reference_id(self) -> None:
        configuration = {
            "fields": [
                {
                    "referenceId": 101,
                    "label": "Localized Label",
                    "choiceOptionSetting": {
                        "referenceFilters": [
                            {"domainType": "TRACKER", "domainId": 777}
                        ]
                    },
                }
            ]
        }

        enriched = self.service.enrich_schema(self.schema_df, configuration)

        self.assertEqual(enriched.iloc[0]["tracker_item_source_tracker_ids"], [777])
        self.assertEqual(
            enriched.iloc[0]["tracker_item_query_status"],
            TRACKER_ITEM_QUERY_STATUS_SUPPORTED,
        )

    def test_non_tracker_configuration_forces_regex_fallback(self) -> None:
        configuration = {
            "fields": [
                {
                    "referenceId": 101,
                    "choiceOptionSetting": {
                        "referenceFilters": [
                            {"domainType": "PROJECT", "domainId": 777}
                        ]
                    },
                }
            ]
        }
        enriched = self.service.enrich_schema(self.schema_df, configuration)

        candidates, settings = self.service.normalize_settings(
            enriched,
            {"related_item": "Related Item"},
            {"Related Item": {"mode": TrackerItemResolutionMode.QUERY.value}},
        )

        self.assertFalse(candidates[0].supports_query)
        self.assertEqual(
            candidates[0].query_status,
            TRACKER_ITEM_QUERY_STATUS_UNSUPPORTED,
        )
        self.assertEqual(
            settings["Related Item"]["mode"],
            TrackerItemResolutionMode.REGEX.value,
        )

    def test_duplicate_tracker_filters_are_deduplicated(self) -> None:
        configuration = {
            "fields": [
                {
                    "referenceId": 101,
                    "referenceFilters": [
                        {"domainType": "TRACKER", "domainId": 777},
                        {"domainType": "TRACKER", "domainId": 777},
                    ],
                }
            ]
        }

        enriched = self.service.enrich_schema(self.schema_df, configuration)

        self.assertEqual(enriched.iloc[0]["tracker_item_source_tracker_ids"], [777])


if __name__ == "__main__":
    unittest.main()
