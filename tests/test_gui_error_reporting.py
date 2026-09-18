from __future__ import annotations

import os
import sys
import threading
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton

from src.diagnostics import DiagnosticService
from src.gui.error_reporting import install_global_exception_handler
from src.gui.error_reporting import safe_exception_message


class GuiErrorReportingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        existing = getattr(self._app, "_codebeamer_gui_exception_reporter", None)
        if existing is not None:
            existing.restore()
        self.alerts: list[tuple[str, str]] = []
        self.logged: list[tuple[str, str, str]] = []
        self.diagnostics = DiagnosticService()
        self.reporter = install_global_exception_handler(
            self._app,
            alert_handler=lambda title, message: self.alerts.append((title, message)),
            exception_logger=lambda exc_type, exc_value, _traceback, thread_name: (
                self.logged.append((exc_type.__name__, str(exc_value), thread_name))
            ),
            diagnostics=self.diagnostics,
        )

    def tearDown(self) -> None:
        self.reporter.restore()

    def test_unhandled_qt_slot_exception_is_logged_and_alerted(self) -> None:
        button = QPushButton("실행")

        def fail() -> None:
            raise AttributeError("status_label이 없습니다")

        button.clicked.connect(fail)
        button.click()
        self._app.processEvents()

        self.assertEqual(
            self.logged[0][:2],
            ("AttributeError", "status_label이 없습니다"),
        )
        self.assertEqual(self.alerts[0][0], "예상하지 못한 오류")
        self.assertIn("AttributeError", self.alerts[0][1])
        self.assertIn("status_label", self.alerts[0][1])
        self.assertIn("진단 ID", self.alerts[0][1])
        event = self.diagnostics.snapshot().events[0]
        self.assertEqual(event.event_kind, "unhandled_exception")
        self.assertEqual(event.exception_type, "AttributeError")

    def test_unhandled_python_thread_exception_is_forwarded_to_gui(self) -> None:
        def fail() -> None:
            raise RuntimeError("worker failed")

        thread = threading.Thread(target=fail, name="sample-worker")
        thread.start()
        thread.join()
        self._app.processEvents()

        self.assertEqual(
            self.logged[0],
            ("RuntimeError", "worker failed", "sample-worker"),
        )
        self.assertEqual(self.alerts[0][0], "예상하지 못한 오류")
        self.assertIn("worker failed", self.alerts[0][1])

    def test_install_is_idempotent_and_restore_recovers_hooks(self) -> None:
        sys_hook = self.reporter._previous_sys_hook
        thread_hook = self.reporter._previous_thread_hook

        same = install_global_exception_handler(self._app)

        self.assertIs(same, self.reporter)
        self.reporter.restore()
        self.assertIs(sys.excepthook, sys_hook)
        self.assertIs(threading.excepthook, thread_hook)

    def test_safe_message_redacts_credentials_and_limits_length(self) -> None:
        message = safe_exception_message(
            RuntimeError(
                "token=secret password:guess https://private.example.test/path "
                "person@example.test /Users/private/file.xlsx "
                + ("x" * 2000)
            )
        )

        self.assertNotIn("secret", message)
        self.assertNotIn("guess", message)
        self.assertNotIn("private.example", message)
        self.assertNotIn("person@example", message)
        self.assertNotIn("/Users/private", message)
        self.assertLessEqual(len(message), 1200)

    def test_user_notification_keeps_business_message_out_of_diagnostic_buffer(self) -> None:
        self.reporter.notify(
            "Private Project 오류",
            "Private Item ABC-123 처리에 실패했습니다.",
        )

        event = self.diagnostics.snapshot().events[-1]
        serialized = repr(event.to_payload())
        self.assertEqual(event.event_kind, "user_notified_error")
        self.assertNotIn("Private Project", serialized)
        self.assertNotIn("Private Item", serialized)
        self.assertNotIn("ABC-123", serialized)
        self.assertIn("Private Item", self.alerts[-1][1])

    def test_exception_observer_does_not_replace_previous_console_hook(self) -> None:
        previous_calls = []
        self.reporter._previous_sys_hook = (
            lambda exc_type, exc_value, traceback: previous_calls.append(
                (exc_type.__name__, str(exc_value), traceback)
            )
        )
        try:
            raise ValueError("sample failure")
        except ValueError as exc:
            self.reporter._handle_sys_exception(type(exc), exc, exc.__traceback__)

        self.assertEqual(previous_calls[0][:2], ("ValueError", "sample failure"))
        self.assertEqual(
            self.diagnostics.snapshot().events[-1].exception_type,
            "ValueError",
        )


if __name__ == "__main__":
    unittest.main()
