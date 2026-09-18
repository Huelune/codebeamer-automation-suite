from __future__ import annotations

import contextlib
import sys
import threading
import time
from collections.abc import Callable
from types import TracebackType

from PySide6.QtCore import QObject
from PySide6.QtCore import Qt
from PySide6.QtCore import QThread
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox

from src.diagnostics import DiagnosticLevel
from src.diagnostics import DiagnosticService
from src.diagnostics import DiagnosticSource
from src.diagnostics import current_operation_id
from src.diagnostics import new_operation_id
from src.diagnostics import sanitize_diagnostic_text


_REPORTER_ATTRIBUTE = "_codebeamer_gui_exception_reporter"
_MAX_ERROR_MESSAGE_LENGTH = 1200
_DUPLICATE_WINDOW_SECONDS = 1.0
def safe_exception_message(value: BaseException | object) -> str:
    """사용자 알림에 넣을 예외 메시지에서 민감값과 과도한 길이를 제거한다."""
    message = sanitize_diagnostic_text(value, limit=_MAX_ERROR_MESSAGE_LENGTH)
    if not message:
        return "세부 오류 메시지가 없습니다."
    return message


def show_error_alert(parent, title: str, message: str) -> None:
    dialog = QMessageBox(parent)
    dialog.setObjectName("unexpected_error_dialog")
    dialog.setIcon(QMessageBox.Icon.Critical)
    dialog.setWindowTitle(str(title or "오류"))
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.setText(str(message or "알 수 없는 오류가 발생했습니다."))
    dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    dialog.exec()


class GuiExceptionReporter(QObject):
    """Qt 슬롯과 Python thread의 처리되지 않은 예외를 사용자에게 알린다."""

    alert_requested = Signal(str, str)

    def __init__(
        self,
        app: QApplication,
        *,
        alert_handler: Callable[[str, str], None] | None = None,
        exception_logger: Callable[
            [type[BaseException], BaseException, TracebackType | None, str],
            None,
        ]
        | None = None,
        diagnostics: DiagnosticService | None = None,
    ) -> None:
        super().__init__(app)
        self.app = app
        self._alert_handler = alert_handler
        self._exception_logger = exception_logger
        self._diagnostics = diagnostics
        self._previous_sys_hook = sys.excepthook
        self._previous_thread_hook = getattr(threading, "excepthook", None)
        self._reporting = False
        self._last_report_key: tuple[str, str] | None = None
        self._last_reported_at = 0.0
        self._sys_hook = self._handle_sys_exception
        self._thread_hook = self._handle_thread_exception
        self.alert_requested.connect(
            self._show_alert,
            Qt.ConnectionType.QueuedConnection,
        )

    def install(self) -> None:
        sys.excepthook = self._sys_hook
        if hasattr(threading, "excepthook"):
            threading.excepthook = self._thread_hook

    def restore(self) -> None:
        if sys.excepthook is self._sys_hook:
            sys.excepthook = self._previous_sys_hook
        if (
            self._previous_thread_hook is not None
            and getattr(threading, "excepthook", None) is self._thread_hook
        ):
            threading.excepthook = self._previous_thread_hook
        if getattr(self.app, _REPORTER_ATTRIBUTE, None) is self:
            delattr(self.app, _REPORTER_ATTRIBUTE)

    def notify(self, title: str, message: str) -> None:
        normalized_title = str(title or "오류")
        normalized_message = safe_exception_message(message)
        operation_id = current_operation_id() or new_operation_id()
        if self._diagnostics is not None:
            try:
                event = self._diagnostics.record(
                    level=DiagnosticLevel.ERROR,
                    source=DiagnosticSource.APPLICATION,
                    event_kind="user_notified_error",
                    message="사용자에게 오류를 알렸습니다.",
                    operation_id=operation_id,
                    details={},
                )
                operation_id = event.operation_id
            except Exception:
                pass
        diagnostic_suffix = (
            f"\n\n진단 ID: {operation_id[:8]}" if operation_id else ""
        )
        self._dispatch_alert(
            normalized_title,
            f"{normalized_message}{diagnostic_suffix}",
            duplicate_key=(normalized_title, normalized_message),
        )

    def _handle_sys_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        operation_id = self._record_exception(
            exc_type,
            exc_value,
            traceback,
            "MainThread",
        )
        self._log_exception(exc_type, exc_value, traceback, "MainThread")
        self._report_exception(exc_type, exc_value, operation_id=operation_id)

    def _handle_thread_exception(self, args) -> None:
        thread_name = str(getattr(getattr(args, "thread", None), "name", "worker"))
        operation_id = self._record_exception(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            thread_name,
        )
        self._log_exception(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            thread_name,
            thread_args=args,
        )
        self._report_exception(
            args.exc_type,
            args.exc_value,
            operation_id=operation_id,
        )

    def _record_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
        thread_name: str,
    ) -> str:
        if self._diagnostics is None:
            return current_operation_id()
        try:
            event = self._diagnostics.record_exception(
                exc_type,
                exc_value,
                traceback,
                thread_name,
            )
        except Exception:
            return current_operation_id()
        return event.operation_id

    def _log_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
        thread_name: str,
        *,
        thread_args=None,
    ) -> None:
        if self._exception_logger is not None:
            # 전역 예외 처리기 안이다. 여기서 다시 예외가 나면 원래 예외 보고를 잃는다.
            with contextlib.suppress(Exception):
                self._exception_logger(exc_type, exc_value, traceback, thread_name)
        if thread_args is not None and self._previous_thread_hook is not None:
            # 이전 hook 이 남의 코드일 수 있어 어떤 예외든 우리 보고를 막게 두지 않는다.
            with contextlib.suppress(Exception):
                self._previous_thread_hook(thread_args)
            return
        # 이전 hook 이 남의 코드일 수 있어 어떤 예외든 우리 보고를 막게 두지 않는다.
        with contextlib.suppress(Exception):
            self._previous_sys_hook(exc_type, exc_value, traceback)

    def _report_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        *,
        operation_id: str = "",
    ) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return
        type_name = getattr(exc_type, "__name__", "Exception")
        detail = safe_exception_message(exc_value)
        diagnostic_suffix = (
            f"\n진단 ID: {operation_id[:8]}" if operation_id else ""
        )
        self._dispatch_alert(
            "예상하지 못한 오류",
            "작업 중 예상하지 못한 오류가 발생했습니다.\n\n"
            f"{type_name}: {detail}\n\n"
            "같은 작업을 다시 시도해 주세요. 반복되면 작업 단계와 발생 시각을 전달해 주세요."
            f"{diagnostic_suffix}",
            duplicate_key=("예상하지 못한 오류", f"{type_name}: {detail}"),
        )

    def _dispatch_alert(
        self,
        title: str,
        message: str,
        *,
        duplicate_key: tuple[str, str] | None = None,
    ) -> None:
        key = duplicate_key or (title, message)
        now = time.monotonic()
        if (
            key == self._last_report_key
            and now - self._last_reported_at < _DUPLICATE_WINDOW_SECONDS
        ):
            return
        self._last_report_key = key
        self._last_reported_at = now
        if QThread.currentThread() == self.app.thread():
            self._show_alert(title, message)
        else:
            self.alert_requested.emit(title, message)

    def _show_alert(self, title: str, message: str) -> None:
        if self._reporting:
            return
        self._reporting = True
        try:
            if self._alert_handler is not None:
                self._alert_handler(title, message)
            else:
                show_error_alert(self.app.activeWindow(), title, message)
        except Exception as exc:
            # windowed EXE 에서는 sys.__stderr__ 가 None(AttributeError)이거나
            # 이미 닫혀 있을(ValueError/OSError) 수 있다.
            with contextlib.suppress(AttributeError, OSError, ValueError):
                sys.__stderr__.write(f"GUI error alert failed: {exc}\n")
        finally:
            self._reporting = False


def install_global_exception_handler(
    app: QApplication,
    *,
    alert_handler: Callable[[str, str], None] | None = None,
    exception_logger: Callable[
        [type[BaseException], BaseException, TracebackType | None, str],
        None,
    ]
    | None = None,
    diagnostics: DiagnosticService | None = None,
) -> GuiExceptionReporter:
    existing = getattr(app, _REPORTER_ATTRIBUTE, None)
    if isinstance(existing, GuiExceptionReporter):
        if diagnostics is not None:
            existing._diagnostics = diagnostics
        return existing
    reporter = GuiExceptionReporter(
        app,
        alert_handler=alert_handler,
        exception_logger=exception_logger,
        diagnostics=diagnostics,
    )
    setattr(app, _REPORTER_ATTRIBUTE, reporter)
    reporter.install()
    return reporter


def notify_user_error(title: str, message: str, *, parent=None) -> None:
    app = QApplication.instance()
    reporter = getattr(app, _REPORTER_ATTRIBUTE, None) if app is not None else None
    if isinstance(reporter, GuiExceptionReporter):
        reporter.notify(title, message)
        return
    show_error_alert(parent, title, safe_exception_message(message))


__all__ = [
    "GuiExceptionReporter",
    "install_global_exception_handler",
    "notify_user_error",
    "safe_exception_message",
    "show_error_alert",
]
