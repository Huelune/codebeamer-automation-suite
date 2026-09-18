from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.gui.batch_validation import BatchValidationService
from src.upload_policy import UPLOAD_MODE_UPDATE
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class BatchValidationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = BatchValidationService(
            mapper=Mock(),
            reader_cls=object,
        )

    def test_normalize_file_paths_prefers_multi_file_selection(self) -> None:
        file_paths = self.service._normalize_file_paths(
            {
                "file_path": "fallback.xlsx",
                "file_paths": ["A.xlsx", "", "B.xlsx"],
            }
        )

        self.assertEqual(file_paths, ["A.xlsx", "B.xlsx"])

    def test_duplicate_update_ids_are_detected_across_files(self) -> None:
        mapping_context = SimpleNamespace(upload_mode=UPLOAD_MODE_UPDATE)
        duplicate_ids, issue_df = self.service._build_batch_update_duplicate_issue_df(
            mapping_context,
            file_upload_dfs={
                "A.xlsx": pd.DataFrame(
                    [{"_row_id": 1, "id": 100, "upload_name": "A"}]
                ),
                "B.xlsx": pd.DataFrame(
                    [{"_row_id": 1, "id": 100, "upload_name": "B"}]
                ),
            },
        )

        self.assertEqual(duplicate_ids, {100})
        self.assertEqual(len(issue_df), 1)
        self.assertIn("여러 파일", issue_df.iloc[0]["message"])


if __name__ == "__main__":
    unittest.main()
