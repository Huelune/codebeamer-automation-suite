from __future__ import annotations

import unittest

import pandas as pd

from src.gui.validation_presenter import ValidationPresenter
from src.models import PayloadStatus
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class ValidationPresenterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.presenter = ValidationPresenter()

    def test_build_user_issue_df_formats_structured_update_error(self) -> None:
        payload_df = pd.DataFrame(
            [
                {
                    "_row_id": 1,
                    "upload_name": "Requirement",
                    "payload_status": PayloadStatus.FAILED.value,
                    "payload_error": (
                        "[UPDATE_ITEM_ID_INVALID] field='id' df_column='id' "
                        "_row_id=1 value='invalid'"
                    ),
                }
            ]
        )

        issue_df = self.presenter.build_user_issue_df(
            pd.DataFrame(),
            pd.DataFrame(),
            payload_df,
        )

        self.assertEqual(len(issue_df), 1)
        self.assertEqual(issue_df.iloc[0]["column"], "id")
        self.assertEqual(issue_df.iloc[0]["field"], "id")
        self.assertIn("숫자", issue_df.iloc[0]["message"])

    def test_build_summary_stats_scopes_same_row_id_by_file(self) -> None:
        row_context_df = pd.DataFrame(
            [
                {"_row_id": 1, "source_file_path": "A.xlsx"},
                {"_row_id": 1, "source_file_path": "B.xlsx"},
            ]
        )

        summary = self.presenter.build_summary_stats(pd.DataFrame(), row_context_df)

        self.assertEqual(summary["total_rows"], 2)
        self.assertEqual(summary["ready_rows"], 2)

    def test_finalize_issue_df_prioritizes_errors(self) -> None:
        issue_df = pd.DataFrame(
            [
                {
                    "severity": "안내",
                    "category": "값 검증",
                    "row_id": "2",
                    "column": "B",
                    "field": "B",
                },
                {
                    "severity": "오류",
                    "category": "Payload 생성",
                    "row_id": "1",
                    "column": "A",
                    "field": "A",
                },
            ]
        )

        finalized = self.presenter.finalize_issue_df(issue_df)

        self.assertEqual(finalized.iloc[0]["severity"], "오류")


if __name__ == "__main__":
    unittest.main()
