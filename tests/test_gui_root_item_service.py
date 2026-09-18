from __future__ import annotations

import unittest
from unittest.mock import Mock

import pandas as pd

from src.gui.root_item_service import ROOT_ASSIGNMENT_MODE_FILE_SOURCE
from src.gui.root_item_service import ROOT_ITEM_MODE_GROUP_BY_COLUMN
from src.gui.root_item_service import ROOT_REGEX_TARGET_FILE_STEM
from src.gui.root_item_service import ROOT_SOURCE_GROUP_VALUE
from src.gui.root_item_service import RootItemService
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class RootItemServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RootItemService(
            mapper=Mock(),
            reader_cls=object,
            is_schema_field_excluded=lambda row: False,
        )

    def test_root_sources_extract_named_regex_groups(self) -> None:
        sources, matched, error = self.service._root_sources_for_file(
            "ABC_REQ-001.xlsx",
            regex_pattern=r"(?P<domain>[A-Z]+)_(?P<item>REQ-\d+)",
            regex_target=ROOT_REGEX_TARGET_FILE_STEM,
        )

        self.assertTrue(matched)
        self.assertIsNone(error)
        self.assertEqual(sources["domain"], "ABC")
        self.assertEqual(sources["item"], "REQ-001")

    def test_group_mode_defaults_name_to_group_value(self) -> None:
        schema_df = pd.DataFrame(
            [
                {
                    "field_name": "Summary",
                    "tracker_item_field": "name",
                }
            ]
        )

        normalized = self.service._normalize_root_item_config(
            schema_df,
            {
                "root_mode": ROOT_ITEM_MODE_GROUP_BY_COLUMN,
                "group_by_column": "Domain",
            },
        )

        self.assertFalse(normalized["enabled"])
        self.assertTrue(normalized["group_enabled"])
        self.assertEqual(
            normalized["field_assignments"]["Summary"],
            {
                "enabled": True,
                "mode": ROOT_ASSIGNMENT_MODE_FILE_SOURCE,
                "value": ROOT_SOURCE_GROUP_VALUE,
            },
        )


if __name__ == "__main__":
    unittest.main()
