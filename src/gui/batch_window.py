from __future__ import annotations

import contextlib
from collections.abc import Callable

from .activity_history import ActivityRecord
from .service_core import GuiCodebeamerService
from .service_core import GuiExcelService
from .settings_store import GuiSettings
from .settings_store import GuiSettingsStore
from .upload_service import GuiUploadPipelineService
from .window_shell import WindowShellMixin
from .window_support import GuiSessionState
from .window_support import UploadProgressState
from .window_support import _require_qt
from .window_support import _window_size_from_settings
from .window_upload import WindowUploadMixin
from .window_workflow import WindowWorkflowMixin


_QT = _require_qt()
QMainWindow = _QT["QMainWindow"]


class BatchUploadWindow(WindowShellMixin, WindowWorkflowMixin, WindowUploadMixin, QMainWindow):
    """기존 9단계 create/update/upsert 마법사를 제공한다."""

    def __init__(
        self,
        settings_store: GuiSettingsStore,
        *,
        parent=None,
        embedded: bool = False,
        settings_changed_callback: Callable[[GuiSettings], None] | None = None,
        global_settings_requested_callback: Callable[[], None] | None = None,
        activity_recorder: Callable[[ActivityRecord], None] | None = None,
        busy_started_callback: Callable[[str], object] | None = None,
        busy_finished_callback: Callable[[object], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.qt = _QT
        self.settings_store = settings_store
        self._embedded = bool(embedded)
        self._persist_window_preferences_on_close = not self._embedded
        self._settings_changed_callback = settings_changed_callback
        self._global_settings_requested_callback = global_settings_requested_callback
        self._activity_recorder = activity_recorder
        self._busy_started_callback = busy_started_callback
        self._busy_finished_callback = busy_finished_callback
        if self._embedded:
            self.setWindowFlags(self.qt["Qt"].WindowType.Widget)

        initial_settings = settings_store.load()
        self.session_state = GuiSessionState(
            settings=initial_settings,
            file_state={},
            projects=[],
            trackers=[],
            workflow_preset=None,
            mapping_context=None,
            validation_context=None,
            upload_result=None,
        )
        self.codebeamer_service = GuiCodebeamerService()
        self.excel_service = GuiExcelService()
        self.pipeline_service = GuiUploadPipelineService()
        self.upload_worker = None
        self.background_task = None
        self.upload_progress = UploadProgressState()
        self._activity_dry_run = False
        self._build_shell()
        self._build_pages()
        self._connect_upload_workbook_actions()

        self.setWindowTitle("Codebeamer Upload Studio")
        if not self._embedded:
            self.resize(*_window_size_from_settings(initial_settings))
        normalized_theme = self._apply_theme(initial_settings.theme_name)
        self.session_state.settings = GuiSettings(
            **{
                **initial_settings.__dict__,
                "theme_name": normalized_theme,
            }
        )
        self.statusBar().showMessage("설정 페이지를 확인하세요.")
        self._show_page(self.settings_page)

        if not self._embedded:
            if bool(getattr(initial_settings, "window_is_fullscreen", False)):
                self.showFullScreen()
            elif bool(getattr(initial_settings, "window_is_maximized", False)):
                self.showMaximized()
    def _on_settings_changed(self, settings: GuiSettings | None) -> GuiSettings:
        updated_settings = WindowWorkflowMixin._on_settings_changed(self, settings)
        if self._settings_changed_callback is not None:
            self._settings_changed_callback(updated_settings)
        return updated_settings

    def apply_global_settings(self, settings: GuiSettings) -> GuiSettings:
        """전용 설정 센터에서 적용한 전역 설정을 현재 배치 세션에 반영한다."""

        current = self.session_state.settings
        merged = GuiSettings(
            **{
                **settings.__dict__,
                "upload_mode": current.upload_mode,
                "excel_header_row": current.excel_header_row,
                "summary_column": current.summary_column,
                "excel_sheet_name": current.excel_sheet_name,
                "last_file_path": current.last_file_path,
            }
        )
        updated = self._on_settings_changed(merged)
        set_settings = getattr(self.settings_page, "set_settings", None)
        if callable(set_settings):
            set_settings(updated)
        return updated

    def _record_activity(self, record: ActivityRecord) -> None:
        if self._activity_recorder is None:
            return
        # 실행 기록 저장은 부가 기능이다. 기록이 실패해도 업로드 흐름을 끊지 않는다.
        with contextlib.suppress(Exception):
            self._activity_recorder(record)

__all__ = ["BatchUploadWindow"]
