from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pandas as pd
from PySide6.QtWidgets import QMessageBox

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


class _SignalStub:
    def connect(self, callback) -> None:
        self.callback = callback


class _RecordingWorker:
    started: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        del args
        self.kwargs = kwargs
        self.progress_changed = _SignalStub()
        self.upload_event = _SignalStub()
        self.upload_finished = _SignalStub()
        self.upload_failed = _SignalStub()

    def start(self) -> None:
        self.__class__.started.append(self.kwargs)


class _AnswerBox:
    """확인 창 대신 미리 정한 답을 돌려준다."""

    answers: list[object] = []
    asked: list[str] = []

    StandardButton = QMessageBox.StandardButton

    @classmethod
    def question(cls, parent, title, text, buttons, default):
        del parent, title, buttons
        cls.asked.append(text)
        assert default == cls.StandardButton.No
        return cls.answers.pop(0)


class WindowUploadRepeatGuardTest(unittest.TestCase):
    """실제 업로드를 마친 같은 데이터로 처음부터 다시 실행하면 먼저 묻는다."""

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.window = BatchUploadWindow(GuiSettingsStore(root_dir=Path(temp_dir.name)))
        self.addCleanup(self.window.close)
        self.window._record_batch_activity = Mock()
        self.window._show_error_dialog = Mock()
        self.window.qt = dict(self.window.qt, QMessageBox=_AnswerBox)
        self.window.session_state.mapping_context = object()
        self.window.upload_page.dry_run_checkbox.setChecked(False)
        _RecordingWorker.started = []
        _AnswerBox.answers = []
        _AnswerBox.asked = []
        worker_patch = patch("src.gui.window_upload.UploadWorker", _RecordingWorker)
        worker_patch.start()
        self.addCleanup(worker_patch.stop)

    @staticmethod
    def _finished_result() -> dict:
        return {
            "success_df": pd.DataFrame([{"_row_id": 0, "upload_name": "생성됨", "phase": "insert"}]),
            "failed_df": pd.DataFrame(),
            "unresolved_df": pd.DataFrame(),
            "phase_results": {"insert": {"total": 1, "success": 1, "failed": 0, "unresolved": 0}},
        }

    def test_restarting_after_real_upload_asks_before_running_again(self) -> None:
        window = self.window
        window._start_upload()
        self.assertEqual(len(_RecordingWorker.started), 1)
        self.assertEqual(_AnswerBox.asked, [])
        window._on_upload_finished(self._finished_result())

        _AnswerBox.answers = [_AnswerBox.StandardButton.No]
        window._start_upload()

        self.assertEqual(len(_RecordingWorker.started), 1)
        self.assertEqual(len(_AnswerBox.asked), 1)
        self.assertIn("한 번 더", _AnswerBox.asked[0])
        self.assertIn("실패 항목 재시도", window.upload_page.status_label.text())

        _AnswerBox.answers = [_AnswerBox.StandardButton.Yes]
        window._start_upload()

        self.assertEqual(len(_RecordingWorker.started), 2)

    def test_restart_after_failed_real_upload_also_asks(self) -> None:
        window = self.window
        window._start_upload()
        window._on_upload_failed("중간에 실패했습니다.")

        _AnswerBox.answers = [_AnswerBox.StandardButton.No]
        window._start_upload()

        self.assertEqual(len(_RecordingWorker.started), 1)
        self.assertEqual(len(_AnswerBox.asked), 1)

    def test_dry_run_and_revalidated_data_do_not_ask(self) -> None:
        window = self.window
        window.upload_page.dry_run_checkbox.setChecked(True)
        window._start_upload()
        window._on_upload_finished(self._finished_result())
        # Dry Run 은 서버에 아무것도 만들지 않았다.
        window.upload_page.dry_run_checkbox.setChecked(False)
        window._start_upload()
        window._on_upload_finished(self._finished_result())
        # 검증을 다시 하면 새 준비 데이터다. 사용자가 다시 고른 것으로 본다.
        window.session_state.mapping_context = object()
        window._start_upload()

        self.assertEqual(len(_RecordingWorker.started), 3)
        self.assertEqual(_AnswerBox.asked, [])


if __name__ == "__main__":
    unittest.main()
