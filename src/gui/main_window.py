from __future__ import annotations

import contextlib
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from src.api_monitor import API_MONITOR
from src.app_metadata import APPLICATION_TITLE
from src.diagnostics import DIAGNOSTICS
from src.diagnostics import DiagnosticLevel
from src.diagnostics import DiagnosticService
from src.diagnostics import DiagnosticSource
from src.diagnostics import operation_context

from .activity_history import ActivityHistoryStore
from .activity_history import ActivityRecord
from .activity_history import default_activity_history_path
from .activity_history_page import ActivityHistoryPage
from .batch_window import BatchUploadWindow
from .developer_tool_panels import ExcelToolPanel
from .developer_tool_panels import PayloadToolPanel
from .developer_tool_panels import ReadOnlyQueryToolPanel
from .developer_tool_panels import SchemaCacheToolPanel
from .developer_tools_window import DeveloperToolsWindow
from .error_reporting import notify_user_error
from .loading_overlay import LoadingOverlay
from .settings_center import SettingsCenterPage
from .settings_store import GuiSettings
from .settings_store import GuiSettingsStore
from .tracker_bulk_update import BulkUpdateRunStore
from .tracker_bulk_update import default_bulk_update_runs_path
from .tracker_workspace import TrackerWorkspacePage
from .window_support import _estimate_upload_remaining_seconds
from .window_support import _format_clock_text
from .window_support import _format_duration_text
from .window_support import _format_upload_eta_text
from .window_support import _format_upload_progress_text
from .window_support import _merge_root_item_page_configs
from .window_support import _merge_window_preferences
from .window_support import _require_qt
from .window_support import _window_size_from_settings


ROUTE_TRACKER_WORKSPACE = "tracker_workspace"
ROUTE_BATCH_UPLOAD = "batch_upload"
ROUTE_ACTIVITY = "activity"
ROUTE_SETTINGS = "settings"

APP_ROUTE_LABELS = {
    ROUTE_TRACKER_WORKSPACE: "트래커 작업공간",
    ROUTE_BATCH_UPLOAD: "배치 작업",
    ROUTE_ACTIVITY: "실행 기록",
    ROUTE_SETTINGS: "설정",
}
APP_ROUTE_COLLAPSED_LABELS = {
    ROUTE_TRACKER_WORKSPACE: "조회",
    ROUTE_BATCH_UPLOAD: "배치",
    ROUTE_ACTIVITY: "기록",
    ROUTE_SETTINGS: "설정",
}
APPLICATION_NAVIGATION_EXPANDED_MIN_WIDTH = 170
APPLICATION_NAVIGATION_EXPANDED_MAX_WIDTH = 220
APPLICATION_NAVIGATION_COLLAPSED_WIDTH = 68


_QT = _require_qt()
if TYPE_CHECKING:
    # 런타임 가드는 아래 else 가 유지한다. 타입 체커에는 실제 클래스를 알려준다.
    from PySide6.QtWidgets import QMainWindow
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QWidget
else:
    QMainWindow = _QT["QMainWindow"]


class MainWindow(QMainWindow):
    """조회·배치·기록·설정을 전환하는 최상위 애플리케이션 셸."""

    def __init__(
        self,
        settings_store: GuiSettingsStore,
        *,
        diagnostics: DiagnosticService = DIAGNOSTICS,
    ) -> None:
        super().__init__()
        self.qt = _QT
        self.settings_store = settings_store
        self.diagnostics = diagnostics
        settings_store.ensure_app_settings()
        initial_settings = settings_store.load()
        API_MONITOR.reset(
            enabled=bool(initial_settings.api_monitor_enabled),
            slow_threshold_ms=int(initial_settings.api_monitor_slow_threshold_ms),
        )
        self._last_normal_window_width = max(int(initial_settings.window_width), 860)
        self._last_normal_window_height = max(int(initial_settings.window_height), 620)
        self.current_route = ""
        self.navigation_collapsed = bool(initial_settings.navigation_collapsed)
        self.route_widgets: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.developer_tools_window: DeveloperToolsWindow | None = None
        self.api_monitor_window: DeveloperToolsWindow | None = None
        self._busy_tokens: set[int] = set()

        self._build_application_shell(initial_settings)
        self.setWindowTitle(APPLICATION_TITLE)
        self.setMinimumSize(860, 620)
        self.resize(*_window_size_from_settings(initial_settings))
        self._show_route(ROUTE_TRACKER_WORKSPACE)
        self.diagnostics.record(
            level=DiagnosticLevel.INFO,
            source=DiagnosticSource.APPLICATION,
            event_kind="application_started",
            message="GUI 작업공간을 시작했습니다.",
            details={"offline_mode": bool(initial_settings.offline_mode)},
        )

        if bool(getattr(initial_settings, "window_is_fullscreen", False)):
            self.showFullScreen()
        elif bool(getattr(initial_settings, "window_is_maximized", False)):
            self.showMaximized()
        if bool(initial_settings.api_monitor_enabled):
            QTimer.singleShot(0, self._show_api_monitor)

    def _build_application_shell(self, initial_settings: GuiSettings) -> None:
        QWidget = self.qt["QWidget"]
        QFrame = self.qt["QFrame"]
        QHBoxLayout = self.qt["QHBoxLayout"]
        QLabel = self.qt["QLabel"]
        QPushButton = self.qt["QPushButton"]
        QStackedWidget = self.qt["QStackedWidget"]
        QVBoxLayout = self.qt["QVBoxLayout"]

        root = QWidget(self)
        root.setObjectName("application_shell_root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 8, 10, 8)
        root_layout.setSpacing(8)

        header = QFrame(root)
        header.setObjectName("application_header")
        header.setMinimumHeight(56)
        self.application_header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(10)

        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("Codebeamer Automation Suite")
        title.setObjectName("application_title")
        subtitle = QLabel("트래커 조회와 배치 작업을 한 곳에서 관리합니다.")
        subtitle.setObjectName("application_subtitle")
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        header_layout.addLayout(title_group)
        header_layout.addStretch(1)

        self.mode_badge = QLabel("")
        self.mode_badge.setObjectName("application_mode_badge")
        header_layout.addWidget(self.mode_badge)
        self._update_mode_badge(initial_settings)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(8)
        self.application_body_layout = body_layout

        navigation = QFrame(root)
        navigation.setObjectName("application_navigation")
        self.navigation_frame = navigation
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(10, 12, 10, 12)
        navigation_layout.setSpacing(6)

        navigation_header = QHBoxLayout()
        navigation_header.setContentsMargins(0, 0, 0, 0)
        navigation_header.setSpacing(4)
        self.navigation_title = QLabel("작업 영역")
        self.navigation_title.setObjectName("application_navigation_title")
        navigation_header.addWidget(self.navigation_title)
        navigation_header.addStretch(1)

        self.navigation_toggle_button = QPushButton(navigation)
        self.navigation_toggle_button.setObjectName("application_navigation_toggle")
        self.navigation_toggle_button.clicked.connect(
            lambda checked=False: self._set_navigation_collapsed(
                not self.navigation_collapsed
            )
        )
        navigation_header.addWidget(self.navigation_toggle_button)
        navigation_layout.addLayout(navigation_header)

        for route, label in APP_ROUTE_LABELS.items():
            button = QPushButton(label, navigation)
            button.setObjectName("application_nav_button")
            button.setCheckable(True)
            button.setAccessibleName(label)
            button.setToolTip(label)
            button.clicked.connect(
                lambda checked=False, selected_route=route: self._show_route(selected_route)
            )
            navigation_layout.addWidget(button)
            self.nav_buttons[route] = button
        self._set_navigation_collapsed(self.navigation_collapsed, announce=False)
        navigation_layout.addStretch(1)

        content = QFrame(root)
        content.setObjectName("application_content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.route_stack = QStackedWidget(content)
        self.route_stack.setObjectName("application_route_stack")
        content_layout.addWidget(self.route_stack)

        self.activity_store = ActivityHistoryStore(
            default_activity_history_path(self.settings_store.root_dir)
        )
        self.bulk_run_store = BulkUpdateRunStore(
            default_bulk_update_runs_path(self.settings_store.root_dir)
        )
        self.activity_page = ActivityHistoryPage(
            self.activity_store,
            bulk_retry_requested=self._open_bulk_retry,
            parent=content,
        )

        self.tracker_workspace_page = TrackerWorkspacePage(
            settings_provider=self.settings_store.load,
            open_settings=self._open_global_settings,
            activity_recorder=self._record_activity,
            bulk_run_store=self.bulk_run_store,
            bulk_chunk_size_saver=self.settings_store.save_bulk_update_chunk_size,
            busy_started=self._begin_busy,
            busy_finished=self._end_busy,
            error_notifier=self._show_error_dialog,
            parent=content,
        )

        self.batch_page = QWidget(content)
        self.batch_page.setObjectName("batch_route_page")
        batch_layout = QVBoxLayout(self.batch_page)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(0)
        self.batch_window = BatchUploadWindow(
            self.settings_store,
            parent=self.batch_page,
            embedded=True,
            settings_changed_callback=self._on_batch_settings_changed,
            global_settings_requested_callback=self._open_global_settings,
            activity_recorder=self._record_activity,
            busy_started_callback=self._begin_busy,
            busy_finished_callback=self._end_busy,
        )
        batch_layout.addWidget(self.batch_window)
        self.settings_center_page = SettingsCenterPage(
            self.settings_store,
            on_applied=self._on_global_settings_applied,
            connection_tester=(
                self.batch_window.codebeamer_service.test_connection_and_load_projects
            ),
            api_monitor_requested=self._show_developer_tools,
            busy_started=self._begin_busy,
            busy_finished=self._end_busy,
            parent=content,
        )

        self.route_widgets = {
            ROUTE_TRACKER_WORKSPACE: self.tracker_workspace_page,
            ROUTE_BATCH_UPLOAD: self.batch_page,
            ROUTE_ACTIVITY: self.activity_page,
            ROUTE_SETTINGS: self.settings_center_page,
        }
        for route in APP_ROUTE_LABELS:
            self.route_stack.addWidget(self.route_widgets[route])

        body_layout.addWidget(navigation)
        body_layout.addWidget(content, 1)

        root_layout.addWidget(header)
        root_layout.addLayout(body_layout, 1)
        self.loading_overlay = LoadingOverlay(root)
        self.setCentralWidget(root)
        self.loading_overlay.sync_geometry()

    def _begin_busy(self, message: str = "") -> int:
        token = self.loading_overlay.start(message)
        self._busy_tokens.add(token)
        return token

    def _end_busy(self, token: object) -> None:
        # 콜백 경계라 object 로 들어온다. `_begin_busy` 가 돌려준 int 만 유효하다.
        if not isinstance(token, int):
            return
        self._busy_tokens.discard(token)
        self.loading_overlay.finish(token)

    def _create_placeholder_page(
        self,
        *,
        title: str,
        phase: str,
        description: str,
        scope_text: str,
        action_text: str | None = None,
        action_handler=None,
    ):
        QWidget = self.qt["QWidget"]
        QFrame = self.qt["QFrame"]
        QHBoxLayout = self.qt["QHBoxLayout"]
        QLabel = self.qt["QLabel"]
        QPushButton = self.qt["QPushButton"]
        QVBoxLayout = self.qt["QVBoxLayout"]

        page = QWidget()
        page.setObjectName("application_route_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        heading_row = QHBoxLayout()
        heading_row.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("application_route_title")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        phase_badge = QLabel(phase)
        phase_badge.setObjectName("application_phase_badge")
        heading_row.addWidget(phase_badge)
        layout.addLayout(heading_row)

        description_label = QLabel(description)
        description_label.setObjectName("application_route_description")
        description_label.setWordWrap(True)
        layout.addWidget(description_label)

        scope_card = QFrame(page)
        scope_card.setObjectName("application_placeholder_card")
        scope_layout = QVBoxLayout(scope_card)
        scope_layout.setContentsMargins(16, 14, 16, 14)
        scope_layout.setSpacing(8)

        scope_title = QLabel("현재 구현 범위")
        scope_title.setObjectName("application_placeholder_title")
        scope_label = QLabel(scope_text)
        scope_label.setObjectName("application_route_description")
        scope_label.setWordWrap(True)
        scope_layout.addWidget(scope_title)
        scope_layout.addWidget(scope_label)

        if action_text and action_handler is not None:
            action_row = QHBoxLayout()
            action_row.addStretch(1)
            action_button = QPushButton(action_text)
            action_button.setObjectName("primary_button")
            action_button.clicked.connect(action_handler)
            action_row.addWidget(action_button)
            scope_layout.addLayout(action_row)

        layout.addWidget(scope_card)
        layout.addStretch(1)
        return page

    def _show_route(self, route: str) -> bool:
        if route not in self.route_widgets:
            raise ValueError(f"알 수 없는 작업 영역입니다: {route}")
        if (
            self.current_route == ROUTE_SETTINGS
            and route != ROUTE_SETTINGS
            and not self.settings_center_page.request_leave()
        ):
            for button_route, button in self.nav_buttons.items():
                button.setChecked(button_route == ROUTE_SETTINGS)
            return False
        self.current_route = route
        self.route_stack.setCurrentWidget(self.route_widgets[route])
        for button_route, button in self.nav_buttons.items():
            button.setChecked(button_route == route)
        if route == ROUTE_BATCH_UPLOAD:
            self.statusBar().hide()
            return True
        self.statusBar().show()
        self.statusBar().showMessage(f"{APP_ROUTE_LABELS[route]} 화면을 열었습니다.")
        if route == ROUTE_TRACKER_WORKSPACE:
            self.tracker_workspace_page.activate()
        elif route == ROUTE_ACTIVITY:
            self.activity_page.activate()
        return True

    def _record_activity(self, record: ActivityRecord) -> None:
        try:
            self.activity_store.append(record)
        except Exception:
            self.statusBar().showMessage(
                "작업은 완료됐지만 실행 기록을 저장하지 못했습니다."
            )
            return
        self.activity_page.on_activity_recorded(record)

    def _show_error_dialog(self, title: str, message: str) -> None:
        notify_user_error(title, message, parent=self)

    def _open_global_settings(self) -> None:
        self._show_route(ROUTE_SETTINGS)

    def _open_bulk_retry(self, run_id: str) -> None:
        self._show_route(ROUTE_TRACKER_WORKSPACE)
        self.tracker_workspace_page.open_bulk_retry(run_id)

    def _set_navigation_collapsed(self, collapsed: bool, *, announce: bool = True) -> None:
        self.navigation_collapsed = bool(collapsed)
        if self.navigation_collapsed:
            self.navigation_frame.setMinimumWidth(0)
            self.navigation_frame.setMaximumWidth(APPLICATION_NAVIGATION_COLLAPSED_WIDTH)
            self.navigation_frame.setMinimumWidth(APPLICATION_NAVIGATION_COLLAPSED_WIDTH)
        else:
            self.navigation_frame.setMaximumWidth(
                APPLICATION_NAVIGATION_EXPANDED_MAX_WIDTH
            )
            self.navigation_frame.setMinimumWidth(
                APPLICATION_NAVIGATION_EXPANDED_MIN_WIDTH
            )

        self.navigation_title.setVisible(not self.navigation_collapsed)
        toggle_text = "›" if self.navigation_collapsed else "‹"
        toggle_tooltip = (
            "메뉴 펼치기" if self.navigation_collapsed else "메뉴 접기"
        )
        self.navigation_toggle_button.setText(toggle_text)
        self.navigation_toggle_button.setToolTip(toggle_tooltip)
        self.navigation_toggle_button.setAccessibleName(toggle_tooltip)

        for route, button in self.nav_buttons.items():
            button.setText(
                APP_ROUTE_COLLAPSED_LABELS[route]
                if self.navigation_collapsed
                else APP_ROUTE_LABELS[route]
            )
            button.setProperty("navigationCollapsed", self.navigation_collapsed)
            button.style().unpolish(button)
            button.style().polish(button)

        self.navigation_frame.updateGeometry()
        self.application_body_layout.invalidate()
        self.application_body_layout.activate()
        central_widget = self.centralWidget()
        if central_widget is not None and central_widget.layout() is not None:
            central_widget.layout().invalidate()
            central_widget.layout().activate()

        settings_center = getattr(self, "settings_center_page", None)
        if settings_center is not None:
            settings_center.update_navigation_preference(self.navigation_collapsed)

        if announce:
            state_text = "접었습니다" if self.navigation_collapsed else "펼쳤습니다"
            self.statusBar().showMessage(f"왼쪽 메뉴를 {state_text}.")

    def _on_global_settings_applied(self, settings: GuiSettings) -> None:
        operation_id = self.diagnostics.start_operation(
            source=DiagnosticSource.SETTINGS,
            event_kind="settings_apply",
            message="전역 설정 적용을 시작했습니다.",
        )
        try:
            with operation_context(operation_id):
                was_monitor_enabled = API_MONITOR.enabled
                applied = self.batch_window.apply_global_settings(settings)
                API_MONITOR.configure(
                    enabled=bool(applied.api_monitor_enabled),
                    slow_threshold_ms=int(applied.api_monitor_slow_threshold_ms),
                )
                self._update_mode_badge(applied)
                self.batch_window._apply_theme(applied.theme_name)
                self.tracker_workspace_page.on_settings_applied(applied)
                if bool(applied.api_monitor_enabled) and not was_monitor_enabled:
                    self._show_api_monitor()
                elif self.developer_tools_window is not None:
                    self.developer_tools_window.refresh(force=True)
                self.statusBar().showMessage("전역 설정을 현재 작업에 적용했습니다.")
        except Exception as exc:
            self.diagnostics.finish_operation(
                operation_id,
                source=DiagnosticSource.SETTINGS,
                event_kind="settings_apply",
                message="전역 설정을 적용하지 못했습니다.",
                outcome="failed",
                details={"error_type": type(exc).__name__},
            )
            raise
        self.diagnostics.finish_operation(
            operation_id,
            source=DiagnosticSource.SETTINGS,
            event_kind="settings_apply",
            message="전역 설정을 적용했습니다.",
        )

    def _show_developer_tools(self) -> None:
        if self.developer_tools_window is None:
            self.developer_tools_window = DeveloperToolsWindow(
                self.diagnostics,
                API_MONITOR,
                settings_provider=lambda: self.batch_window.session_state.settings,
                activity_provider=self.activity_store.load,
                default_directory=self.settings_store.root_dir,
                parent=self,
            )
            self.developer_tools_window.excel_tool_panel = ExcelToolPanel(
                default_directory=self.settings_store.root_dir,
                operation_runner=lambda message, callback: self.batch_window._run_with_busy(
                    message,
                    callback,
                ),
                parent=self.developer_tools_window.tabs,
            )
            self.developer_tools_window.payload_tool_panel = PayloadToolPanel(
                self._current_payload_frame,
                parent=self.developer_tools_window.tabs,
            )
            self.developer_tools_window.schema_cache_tool_panel = SchemaCacheToolPanel(
                lambda: self.batch_window.session_state.mapping_context,
                parent=self.developer_tools_window.tabs,
            )
            self.developer_tools_window.read_only_query_tool_panel = ReadOnlyQueryToolPanel(
                self._execute_developer_read_only_query,
                tracker_id_provider=self._current_developer_tracker_id,
                parent=self.developer_tools_window.tabs,
            )
            self.developer_tools_window.add_tool_tab(
                self.developer_tools_window.excel_tool_panel,
                "Excel 도구",
            )
            self.developer_tools_window.add_tool_tab(
                self.developer_tools_window.payload_tool_panel,
                "Payload",
            )
            self.developer_tools_window.add_tool_tab(
                self.developer_tools_window.schema_cache_tool_panel,
                "스키마·캐시",
            )
            self.developer_tools_window.add_tool_tab(
                self.developer_tools_window.read_only_query_tool_panel,
                "읽기 전용 Query",
            )
            # Keep the previous public attribute while callers migrate to the
            # combined developer tools window.
            self.api_monitor_window = self.developer_tools_window
        self.developer_tools_window.select_diagnostics_tab()
        self.developer_tools_window.show()
        self.developer_tools_window.raise_()
        self.developer_tools_window.activateWindow()
        self.developer_tools_window.refresh(force=True)

    def _current_payload_frame(self):
        validation_context = self.batch_window.session_state.validation_context
        validated = getattr(validation_context, "payload_df", None)
        if validated is not None:
            return validated
        mapping_context = self.batch_window.session_state.mapping_context
        if mapping_context is None:
            return None
        wizard = getattr(mapping_context, "wizard", None)
        state = getattr(wizard, "state", None)
        return getattr(state, "payload_df", None)

    def _current_developer_tracker_id(self) -> int | None:
        tracker = getattr(self.tracker_workspace_page, "_current_tracker", None)
        tracker_id = getattr(tracker, "tracker_id", None)
        if tracker_id not in (None, ""):
            return int(tracker_id)
        fallback = self.batch_window.session_state.settings.default_tracker_id
        try:
            normalized = int(fallback)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    def _execute_developer_read_only_query(self, query):
        return self.batch_window._run_with_busy(
            "읽기 전용 Tracker Query를 실행하는 중입니다.",
            self.tracker_workspace_page.service.search,
            self.batch_window.session_state.settings,
            query,
        )

    def _show_api_monitor(self) -> None:
        self._show_developer_tools()
        assert self.developer_tools_window is not None
        self.developer_tools_window.select_api_tab()

    def _on_batch_settings_changed(self, settings: GuiSettings) -> None:
        self._update_mode_badge(settings)

    def _update_mode_badge(self, settings: GuiSettings) -> None:
        if bool(getattr(settings, "offline_mode", False)):
            text = "테스트 모드"
            mode = "test"
        elif all(
            (
                str(getattr(settings, "base_url", "") or "").strip(),
                str(getattr(settings, "username", "") or "").strip(),
                str(getattr(settings, "password", "") or ""),
            )
        ):
            text = "온라인 설정"
            mode = "online"
        else:
            text = "연결 미설정"
            mode = "unconfigured"
        self.mode_badge.setText(text)
        self.mode_badge.setProperty("mode", mode)
        self.mode_badge.style().unpolish(self.mode_badge)
        self.mode_badge.style().polish(self.mode_badge)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.isFullScreen() and not self.isMaximized():
            self._last_normal_window_width = max(int(self.width()), self.minimumWidth())
            self._last_normal_window_height = max(int(self.height()), self.minimumHeight())
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.sync_geometry()

    def closeEvent(self, event) -> None:
        if self.settings_center_page.has_unsaved_changes() and not self.settings_center_page.request_leave():
            event.ignore()
            return
        current_settings = replace(self.batch_window.session_state.settings)
        updated_settings = replace(
            current_settings,
            window_width=max(int(self._last_normal_window_width), self.minimumWidth()),
            window_height=max(int(self._last_normal_window_height), self.minimumHeight()),
            window_is_maximized=bool(self.isMaximized()),
            window_is_fullscreen=bool(self.isFullScreen()),
            navigation_collapsed=self.navigation_collapsed,
        )
        self.batch_window.session_state.settings = updated_settings
        # 창 설정 저장 실패로 앱 종료가 막히면 안 된다. 저장은 다음 실행에서 다시 시도한다.
        with contextlib.suppress(Exception):
            self.settings_store.save_window_preferences(updated_settings)
        self.diagnostics.record(
            level=DiagnosticLevel.INFO,
            source=DiagnosticSource.APPLICATION,
            event_kind="application_closing",
            message="GUI 작업공간을 종료합니다.",
        )
        if self.developer_tools_window is not None:
            self.developer_tools_window.close()
        self.tracker_workspace_page.shutdown()
        self._busy_tokens.clear()
        self.loading_overlay.clear()
        super().closeEvent(event)


__all__ = [
    "APPLICATION_NAVIGATION_COLLAPSED_WIDTH",
    "APP_ROUTE_COLLAPSED_LABELS",
    "APP_ROUTE_LABELS",
    "ROUTE_ACTIVITY",
    "ROUTE_BATCH_UPLOAD",
    "ROUTE_SETTINGS",
    "ROUTE_TRACKER_WORKSPACE",
    "BatchUploadWindow",
    "MainWindow",
    "TrackerWorkspacePage",
    "_estimate_upload_remaining_seconds",
    "_format_clock_text",
    "_format_duration_text",
    "_format_upload_eta_text",
    "_format_upload_progress_text",
    "_merge_root_item_page_configs",
    "_merge_window_preferences",
    "_window_size_from_settings",
]
