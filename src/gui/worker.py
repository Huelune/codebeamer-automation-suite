from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any


if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance
import time

from src.diagnostics import DIAGNOSTICS
from src.diagnostics import DiagnosticSource
from src.diagnostics import new_operation_id
from src.diagnostics import operation_context


def _callable_diagnostic_metadata(func) -> tuple[DiagnosticSource, str]:
    name = str(getattr(func, "__name__", "background_task") or "background_task")
    module = str(getattr(func, "__module__", "") or "")
    descriptor = f"{module}.{name}".casefold()
    if "baseline" in descriptor:
        source = DiagnosticSource.BASELINE
    elif any(token in descriptor for token in ("excel", "workbook", "preview", "metadata")):
        source = DiagnosticSource.EXCEL
    elif any(token in descriptor for token in ("upload", "mapping", "payload", "validation")):
        source = DiagnosticSource.UPLOAD
    elif "setting" in descriptor or "connection" in descriptor:
        source = DiagnosticSource.SETTINGS
    elif any(token in descriptor for token in ("tracker", "item", "project", "search")):
        source = DiagnosticSource.TRACKER
    else:
        source = DiagnosticSource.APPLICATION
    safe_name = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in name
    ).strip("_") or "task"
    return source, f"background_{safe_name}"[:100]


def _require_qt():
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtCore import Signal
    except ImportError as exc:
        raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc
    return {"QThread": QThread, "Signal": Signal}


class UploadWorker:
    """배치 업로드를 백그라운드에서 실행하고 진행 상황을 signal 로 알린다."""

    if TYPE_CHECKING:
        # `__new__` 가 만들어 돌려주는 배치 업로드 QThread 인스턴스의 공개 표면이다.
        # 런타임 정의는 아래 `__new__` 안에 있다.
        log_message: SignalInstance
        progress_changed: SignalInstance
        upload_event: SignalInstance
        upload_finished: SignalInstance
        upload_failed: SignalInstance

        def request_pause(self) -> None: ...
        def request_resume(self) -> None: ...
        def request_cancel(self) -> None: ...
        def start(self) -> None: ...
        def wait(self) -> bool: ...
        def deleteLater(self) -> None: ...
        def isRunning(self) -> bool: ...

    def __new__(
        cls,
        pipeline_service,
        *,
        settings,
        file_state,
        mapping_context,
        dry_run: bool,
        continue_on_error: bool,
        output_dir: str,
        retry_context=None,
    ):
        qt = _require_qt()
        base_cls = qt["QThread"]
        Signal = qt["Signal"]

        # base_cls 는 런타임에 결정되는 QThread 다. 타입 체커는 동적 기반 클래스를
        # 다루지 못하므로 이 줄에서만 무시한다. 공개 표면은 위에 선언해 두었다.
        class _UploadWorker(base_cls):  # type: ignore[misc, valid-type]
            log_message = Signal(str)
            progress_changed = Signal(int, int, str)
            upload_event = Signal(object)
            upload_finished = Signal(object)
            upload_failed = Signal(str)

            def __init__(
                self,
                pipeline_service,
                settings,
                file_state,
                mapping_context,
                dry_run: bool,
                continue_on_error: bool,
                output_dir: str,
                retry_context,
            ) -> None:
                super().__init__()
                self.pipeline_service = pipeline_service
                self.settings = settings
                self.file_state = dict(file_state)
                self.mapping_context = mapping_context
                self.dry_run = dry_run
                self.continue_on_error = continue_on_error
                self.output_dir = output_dir
                self.retry_context = retry_context
                self._pause_requested = False
                self._cancel_requested = False

            def request_pause(self) -> None:
                self._pause_requested = True

            def request_resume(self) -> None:
                self._pause_requested = False

            def request_cancel(self) -> None:
                self._cancel_requested = True
                self._pause_requested = False

            def run(self) -> None:
                operation_id = new_operation_id()
                event_kind = (
                    "failed_upload_retry"
                    if self.retry_context is not None
                    else "batch_upload"
                )
                DIAGNOSTICS.start_operation(
                    source=DiagnosticSource.UPLOAD,
                    event_kind=event_kind,
                    message="업로드 백그라운드 작업을 시작했습니다.",
                    operation_id=operation_id,
                )
                try:
                    with operation_context(operation_id):
                        progress_state = {"completed": 0, "total": 1}

                        def _event_callback(event: dict[str, object]) -> None:
                            while self._pause_requested and not self._cancel_requested:
                                time.sleep(0.1)

                            event_type = str(event.get("type"))
                            self.upload_event.emit(dict(event))
                            if event_type == "batch_total":
                                total_value: Any = event.get("total")
                                try:
                                    progress_state["total"] = max(int(total_value), 1)
                                except Exception:
                                    progress_state["total"] = 1
                                self.progress_changed.emit(
                                    progress_state["completed"],
                                    progress_state["total"],
                                    "",
                                )
                            elif event_type == "row_started":
                                self.progress_changed.emit(
                                    progress_state["completed"],
                                    progress_state["total"],
                                    str(event.get("upload_name") or ""),
                                )
                            elif event_type in {"row_success", "row_failed"}:
                                progress_state["completed"] += 1
                                self.progress_changed.emit(
                                    progress_state["completed"],
                                    progress_state["total"],
                                    str(event.get("upload_name") or ""),
                                )
                            elif event_type == "log":
                                message = str(event.get("message") or "")
                                if message:
                                    self.log_message.emit(message)

                        if self.retry_context is None:
                            result = self.pipeline_service.run_batch_upload(
                                self.settings,
                                self.file_state,
                                self.mapping_context,
                                dry_run=self.dry_run,
                                continue_on_error=self.continue_on_error,
                                output_dir=self.output_dir,
                                event_callback=_event_callback,
                                cancel_requested=lambda: self._cancel_requested,
                                pause_requested=lambda: self._pause_requested,
                            )
                        else:
                            result = self.pipeline_service.run_failed_upload_retry(
                                self.retry_context,
                                continue_on_error=self.continue_on_error,
                                event_callback=_event_callback,
                                cancel_requested=lambda: self._cancel_requested,
                                pause_requested=lambda: self._pause_requested,
                            )
                    cancelled = bool(self._cancel_requested)
                    if cancelled and isinstance(result, dict):
                        result = dict(result)
                        result["cancelled"] = True
                    DIAGNOSTICS.finish_operation(
                        operation_id,
                        source=DiagnosticSource.UPLOAD,
                        event_kind=event_kind,
                        message=(
                            "업로드 백그라운드 작업을 사용자 요청으로 중단했습니다."
                            if cancelled
                            else "업로드 백그라운드 작업을 완료했습니다."
                        ),
                        outcome="cancelled" if cancelled else "success",
                    )
                    self.upload_finished.emit(result)
                except Exception as exc:
                    DIAGNOSTICS.finish_operation(
                        operation_id,
                        source=DiagnosticSource.UPLOAD,
                        event_kind=event_kind,
                        message="업로드 백그라운드 작업을 완료하지 못했습니다.",
                        outcome="failed",
                        details={"error_type": type(exc).__name__},
                    )
                    self.upload_failed.emit(str(exc))

        return _UploadWorker(
            pipeline_service,
            settings,
            file_state,
            mapping_context,
            dry_run=dry_run,
            continue_on_error=continue_on_error,
            output_dir=output_dir,
            retry_context=retry_context,
        )


class BackgroundTask:
    """짧은 GUI 보조 작업을 백그라운드에서 실행하는 범용 worker다."""

    if TYPE_CHECKING:
        # `__new__` 가 만들어 돌려주는 짧은 GUI 보조 작업 QThread 인스턴스의 공개 표면이다.
        # 런타임 정의는 아래 `__new__` 안에 있다.
        completed: SignalInstance
        failed: SignalInstance

        def start(self) -> None: ...
        def wait(self) -> bool: ...
        def deleteLater(self) -> None: ...
        def isRunning(self) -> bool: ...

    def __new__(cls, func, *args, **kwargs):
        qt = _require_qt()
        base_cls = qt["QThread"]
        Signal = qt["Signal"]

        class _BackgroundTask(base_cls):
            completed = Signal(object)
            failed = Signal(object)

            def __init__(self, func, args, kwargs) -> None:
                super().__init__()
                self.func = func
                self.args = args
                self.kwargs = kwargs
                self.diagnostic_source, self.diagnostic_kind = (
                    _callable_diagnostic_metadata(func)
                )

            def run(self) -> None:
                operation_id = new_operation_id()
                DIAGNOSTICS.start_operation(
                    source=self.diagnostic_source,
                    event_kind=self.diagnostic_kind,
                    message="백그라운드 작업을 시작했습니다.",
                    operation_id=operation_id,
                )
                try:
                    with operation_context(operation_id):
                        result = self.func(*self.args, **self.kwargs)
                    DIAGNOSTICS.finish_operation(
                        operation_id,
                        source=self.diagnostic_source,
                        event_kind=self.diagnostic_kind,
                        message="백그라운드 작업을 완료했습니다.",
                    )
                    self.completed.emit(result)
                except Exception as exc:
                    DIAGNOSTICS.finish_operation(
                        operation_id,
                        source=self.diagnostic_source,
                        event_kind=self.diagnostic_kind,
                        message="백그라운드 작업을 완료하지 못했습니다.",
                        outcome="failed",
                        details={"error_type": type(exc).__name__},
                    )
                    self.failed.emit(exc)

        return _BackgroundTask(func, args, kwargs)


class BulkUpdateWorker:
    """일괄 수정을 실행하면서 청크 진행률과 취소 상태를 전달한다."""

    if TYPE_CHECKING:
        # `__new__` 가 만들어 돌려주는 일괄 수정 QThread 인스턴스의 공개 표면이다.
        # 런타임 정의는 아래 `__new__` 안에 있다.
        progress_changed: SignalInstance
        completed: SignalInstance
        failed: SignalInstance

        def request_cancel(self) -> None: ...
        def start(self) -> None: ...
        def wait(self) -> bool: ...
        def deleteLater(self) -> None: ...
        def isRunning(self) -> bool: ...

    def __new__(cls, service, settings, **request):
        qt = _require_qt()
        base_cls = qt["QThread"]
        Signal = qt["Signal"]

        class _BulkUpdateWorker(base_cls):
            progress_changed = Signal(object)
            completed = Signal(object)
            failed = Signal(object)

            def __init__(self, service, settings, request) -> None:
                super().__init__()
                self.service = service
                self.settings = settings
                self.request = dict(request)
                self._cancel_requested = False

            def request_cancel(self) -> None:
                self._cancel_requested = True

            def run(self) -> None:
                operation_id = new_operation_id()
                DIAGNOSTICS.start_operation(
                    source=DiagnosticSource.TRACKER,
                    event_kind="bulk_update",
                    message="일괄 수정 작업을 시작했습니다.",
                    operation_id=operation_id,
                )
                try:
                    with operation_context(operation_id):
                        result = self.service.execute(
                            self.settings,
                            **self.request,
                            event_callback=lambda event: self.progress_changed.emit(
                                dict(event)
                            ),
                            cancel_requested=lambda: self._cancel_requested,
                        )
                except Exception as exc:
                    DIAGNOSTICS.finish_operation(
                        operation_id,
                        source=DiagnosticSource.TRACKER,
                        event_kind="bulk_update",
                        message="일괄 수정 작업을 완료하지 못했습니다.",
                        outcome="failed",
                        details={"error_type": type(exc).__name__},
                    )
                    self.failed.emit(exc)
                    return
                DIAGNOSTICS.finish_operation(
                    operation_id,
                    source=DiagnosticSource.TRACKER,
                    event_kind="bulk_update",
                    message="일괄 수정 작업을 완료했습니다.",
                )
                self.completed.emit(result)

        return _BulkUpdateWorker(service, settings, request)
