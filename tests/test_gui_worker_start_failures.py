from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QPushButton

from src.gui.window_shell import WindowShellMixin
from src.gui.window_upload import WindowUploadMixin
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class _SignalStub:
    def connect(self, callback) -> None:
        self.callback = callback


class _FailingTask:
    def __init__(self, message: str = "thread start failed") -> None:
        self.message = message
        self.completed = _SignalStub()
        self.failed = _SignalStub()
        self.waited = False
        self.deleted = False

    def start(self) -> None:
        raise RuntimeError(self.message)

    def wait(self) -> None:
        self.waited = True

    def deleteLater(self) -> None:
        self.deleted = True


class _BusyHarness(WindowShellMixin, QObject):
    def __init__(self) -> None:
        super().__init__()
        self.qt = {"QEventLoop": QEventLoop}
        self.busy_task = None
        self.busy_events = []

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy_events.append((busy, message))


class _UploadHarness(WindowUploadMixin):
    def __init__(self) -> None:
        self.session_state = SimpleNamespace(
            mapping_context=object(),
            file_state={},
            settings=SimpleNamespace(
                offline_mode=False,
                output_dir="/tmp",
                upload_mode="create",
            ),
        )
        self.upload_page = SimpleNamespace(
            dry_run_checkbox=QCheckBox(),
            continue_checkbox=QCheckBox(),
            start_button=QPushButton(),
            pause_button=QPushButton(),
            cancel_button=QPushButton(),
            status_label=QLabel(),
            reset=lambda _total: None,
        )
        self.pipeline_service = object()
        self.failures = []
        self.upload_worker = None

    def _on_upload_failed(self, message: str) -> None:
        self.failures.append(message)


class GuiWorkerStartFailureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_busy_helper_releases_overlay_when_thread_does_not_start(self) -> None:
        harness = _BusyHarness()
        task = _FailingTask()

        with (
            patch("src.gui.window_shell.BackgroundTask", return_value=task),
            self.assertRaisesRegex(RuntimeError, "thread start failed"),
        ):
            harness._run_with_busy("조회 중", lambda: None)

        self.assertEqual(harness.busy_events, [(True, "조회 중"), (False, "")])
        self.assertTrue(task.waited)
        self.assertTrue(task.deleted)
        self.assertIsNone(harness.busy_task)

    def test_upload_start_failure_uses_existing_failure_handler(self) -> None:
        harness = _UploadHarness()
        task = _FailingTask("upload thread start failed")
        task.progress_changed = _SignalStub()
        task.upload_event = _SignalStub()
        task.upload_finished = _SignalStub()
        task.upload_failed = _SignalStub()

        with patch("src.gui.window_upload.UploadWorker", return_value=task):
            harness._start_upload()

        self.assertEqual(harness.failures, ["upload thread start failed"])


if __name__ == "__main__":
    unittest.main()
