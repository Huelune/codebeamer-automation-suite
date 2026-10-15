from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.gui.batch_validation import BatchValidationService
from src.upload_policy import UPLOAD_MODE_CREATE
from src.upload_policy import UPLOAD_MODE_UPDATE
from src.upload_policy import UPLOAD_MODE_UPSERT
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

    @staticmethod
    def _duplicate_field_schema() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"field_name": "담당자", "is_table_field": False},
                {"field_name": "Steps", "is_table_field": True},
            ]
        )

    def test_same_field_from_columns_with_separate_create_and_update_scopes_is_allowed(self) -> None:
        """생성에는 A열, 수정에는 B열을 쓰는 것은 한 번에 한 열만 쓰므로 막지 않는다."""
        issue_df = BatchValidationService._build_duplicate_field_mapping_issue_df(
            self._duplicate_field_schema(),
            {"A": "담당자", "B": "담당자"},
            {"A": {"create": True, "update": False}, "B": {"create": False, "update": True}},
            upload_mode=UPLOAD_MODE_UPSERT,
        )

        self.assertTrue(issue_df.empty)

    def test_same_field_from_columns_with_overlapping_scope_is_one_blocking_issue(self) -> None:
        issue_df = BatchValidationService._build_duplicate_field_mapping_issue_df(
            self._duplicate_field_schema(),
            {"A": "담당자", "B": "담당자", "C": "담당자"},
            {"A": {"create": True, "update": True}, "B": {"create": False, "update": True}},
            upload_mode=UPLOAD_MODE_UPSERT,
        )

        self.assertEqual(len(issue_df), 1)
        self.assertEqual(issue_df.iloc[0]["severity"], "오류")
        self.assertEqual(issue_df.iloc[0]["column"], "A, B, C")

    def test_table_field_columns_may_share_their_table_field(self) -> None:
        issue_df = BatchValidationService._build_duplicate_field_mapping_issue_df(
            self._duplicate_field_schema(),
            {"Steps.Action": "Steps", "Steps.Expected": "Steps"},
            {},
            upload_mode=UPLOAD_MODE_CREATE,
        )

        self.assertTrue(issue_df.empty)


if __name__ == "__main__":
    unittest.main()
