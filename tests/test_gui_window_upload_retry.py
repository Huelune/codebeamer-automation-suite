from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from src.gui.activity_history import ActivityResult
from src.gui.batch_window import BatchUploadWindow
from src.gui.settings_store import GuiSettingsStore
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class WindowUploadRetryResultTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_retry_progress_and_activity_use_attempt_frames_while_result_keeps_cumulative_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = BatchUploadWindow(
                GuiSettingsStore(root_dir=Path(temp_dir)),
            )
            try:
                window._retry_in_progress = True
                window._record_batch_activity = Mock()
                window._show_error_dialog = Mock()
                cumulative_success = pd.DataFrame(
                    [
                        {"_row_id": 0, "upload_name": "기존 성공 1", "phase": "insert"},
                        {"_row_id": 1, "upload_name": "기존 성공 2", "phase": "insert"},
                        {"_row_id": 2, "upload_name": "재시도 성공", "phase": "insert"},
                    ]
                )
                cumulative_failed = pd.DataFrame(
                    [
                        {
                            "_row_id": 3,
                            "upload_name": "검증 수정 필요",
                            "phase": "insert",
                            "error": "payload 생성 오류",
                        }
                    ]
                )
                retry_success = cumulative_success.iloc[[2]].copy()
                result = {
                    "success_df": cumulative_success,
                    "failed_df": cumulative_failed,
                    "unresolved_df": pd.DataFrame(),
                    "phase_results": {
                        "insert": {"total": 4, "success": 3, "failed": 1, "unresolved": 0},
                        "update": {"total": 0, "success": 0, "failed": 0, "unresolved": 0},
                    },
                    "retry_attempted_count": 1,
                    "retry_success_df": retry_success,
                    "retry_failed_df": pd.DataFrame(),
                    "retry_unresolved_df": pd.DataFrame(),
                    "retry_context": None,
                    "retry_unavailable_reason": "검증 단계에서 수정하세요.",
                }

                window._on_upload_finished(result)

                self.assertEqual(window.upload_progress.success_count, 1)
                self.assertEqual(window.upload_progress.failed_count, 0)
                self.assertEqual(window.upload_progress.retry_count, 1)
                self.assertEqual(window.upload_progress.total, 1)
                self.assertEqual(window.result_page.tables["success_df"].rowCount(), 3)
                activity_kwargs = window._record_batch_activity.call_args.kwargs
                self.assertEqual(activity_kwargs["success_count"], 1)
                self.assertEqual(activity_kwargs["failed_count"], 0)
                self.assertEqual(activity_kwargs["unresolved_count"], 0)
                window._show_error_dialog.assert_called_once()
            finally:
                window.close()

    def test_cancelled_partial_result_is_preserved_without_failure_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = BatchUploadWindow(
                GuiSettingsStore(root_dir=Path(temp_dir)),
            )
            try:
                window._record_batch_activity = Mock()
                window._show_error_dialog = Mock()
                result = {
                    "cancelled": True,
                    "success_df": pd.DataFrame(
                        [
                            {
                                "_row_id": 0,
                                "upload_name": "성공 항목",
                                "phase": "insert",
                            }
                        ]
                    ),
                    "failed_df": pd.DataFrame(),
                    "unresolved_df": pd.DataFrame(
                        [
                            {
                                "_row_id": 1,
                                "upload_name": "미실행 항목",
                                "phase": "insert",
                            }
                        ]
                    ),
                    "phase_results": {
                        "insert": {
                            "total": 2,
                            "success": 1,
                            "failed": 0,
                            "unresolved": 1,
                        },
                        "update": {
                            "total": 0,
                            "success": 0,
                            "failed": 0,
                            "unresolved": 0,
                        },
                    },
                    "retry_context": object(),
                }

                window._on_upload_finished(result)

                self.assertIs(window.session_state.upload_result, result)
                self.assertEqual(window.upload_page.status_label.text(), "업로드 중단됨")
                self.assertIn("중단됨", window.upload_page.eta_label.text())
                self.assertEqual(
                    window._record_batch_activity.call_args.args[0],
                    ActivityResult.CANCELLED,
                )
                window._show_error_dialog.assert_not_called()
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
