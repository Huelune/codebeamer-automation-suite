from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QDialog
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QHeaderView
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QSplitter
from PySide6.QtWidgets import QTableWidget
from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtWidgets import QTabWidget
from PySide6.QtWidgets import QVBoxLayout
from PySide6.QtWidgets import QWidget

from src.api_monitor import ApiMonitorService
from src.diagnostics import DiagnosticBundleSummary
from src.diagnostics import DiagnosticEvent
from src.diagnostics import DiagnosticLevel
from src.diagnostics import DiagnosticService
from src.diagnostics import DiagnosticSnapshot
from src.diagnostics import DiagnosticSource
from src.diagnostics import export_diagnostic_bundle


if TYPE_CHECKING:
    from .developer_tool_panels import ExcelToolPanel
    from .developer_tool_panels import PayloadToolPanel
    from .developer_tool_panels import ReadOnlyQueryToolPanel
    from .developer_tool_panels import SchemaCacheToolPanel

from .api_monitor_window import ApiMonitorPanel
from .error_reporting import notify_user_error


DIAGNOSTIC_REFRESH_INTERVAL_MS = 500
DIAGNOSTIC_TABLE_ROW_LIMIT = 500

_LEVEL_LABELS = {
    DiagnosticLevel.INFO: "정보",
    DiagnosticLevel.WARNING: "경고",
    DiagnosticLevel.ERROR: "오류",
    DiagnosticLevel.CRITICAL: "치명적 오류",
}
_SOURCE_LABELS = {
    DiagnosticSource.APPLICATION: "앱",
    DiagnosticSource.SETTINGS: "설정",
    DiagnosticSource.TRACKER: "트래커",
    DiagnosticSource.BASELINE: "Baseline",
    DiagnosticSource.EXCEL: "Excel",
    DiagnosticSource.UPLOAD: "업로드",
}


class DiagnosticsPanel(QWidget):
    TABLE_HEADERS = ("시각", "수준", "출처", "종류", "진단 ID", "메시지")

    def __init__(
        self,
        service: DiagnosticService,
        *,
        export_requested: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.export_requested = export_requested
        self.paused = False
        self._last_version = -1
        self._last_snapshot: DiagnosticSnapshot | None = None
        self._visible_events: tuple[DiagnosticEvent, ...] = ()
        self.setObjectName("diagnostics_panel")
        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(DIAGNOSTIC_REFRESH_INTERVAL_MS)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.refresh(force=True)

    @property
    def last_snapshot(self) -> DiagnosticSnapshot | None:
        return self._last_snapshot

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)

        heading = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("진단 로그", self)
        title.setObjectName("application_route_title")
        description = QLabel(
            "논리 작업과 오류의 안전한 메타데이터만 세션 메모리에 최대 2,000건 보관합니다.",
            self,
        )
        description.setObjectName("application_route_description")
        description.setWordWrap(True)
        title_group.addWidget(title)
        title_group.addWidget(description)
        heading.addLayout(title_group, 1)
        self.state_label = QLabel("", self)
        self.state_label.setObjectName("diagnostics_collection_state")
        heading.addWidget(self.state_label)
        layout.addLayout(heading)

        filters = QFrame(self)
        filters.setObjectName("diagnostics_filters")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(8, 7, 8, 7)
        filter_layout.setSpacing(7)
        self.search_edit = QLineEdit(filters)
        self.search_edit.setPlaceholderText("메시지, 종류 또는 진단 ID 검색")
        self.level_combo = QComboBox(filters)
        self.level_combo.addItem("모든 수준", "")
        for level, label in _LEVEL_LABELS.items():
            self.level_combo.addItem(label, level.value)
        self.source_combo = QComboBox(filters)
        self.source_combo.addItem("모든 출처", "")
        for source, label in _SOURCE_LABELS.items():
            self.source_combo.addItem(label, source.value)
        filter_layout.addWidget(self.search_edit, 1)
        filter_layout.addWidget(self.level_combo)
        filter_layout.addWidget(self.source_combo)
        layout.addWidget(filters)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.table = QTableWidget(0, len(self.TABLE_HEADERS), splitter)
        self.table.setObjectName("diagnostics_table")
        self.table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((105, 90, 90, 180, 90, 360)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._show_selected_detail)
        splitter.addWidget(self.table)

        detail_frame = QFrame(splitter)
        detail_frame.setObjectName("diagnostics_detail")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(8, 7, 8, 7)
        detail_title = QLabel("선택한 이벤트 상세", detail_frame)
        detail_title.setObjectName("section_title")
        self.detail_view = QPlainTextEdit(detail_frame)
        self.detail_view.setObjectName("diagnostics_detail_view")
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlaceholderText("진단 로그를 선택하면 안전한 상세 정보를 표시합니다.")
        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.detail_view, 1)
        splitter.addWidget(detail_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([430, 240])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.table_state_label = QLabel("표시 0건", self)
        self.table_state_label.setObjectName("section_label")
        footer.addWidget(self.table_state_label)
        footer.addStretch(1)
        self.pause_button = QPushButton("화면 업데이트 일시정지", self)
        self.pause_button.setCheckable(True)
        self.auto_scroll_checkbox = QCheckBox("새 로그 자동 스크롤", self)
        self.auto_scroll_checkbox.setChecked(True)
        self.copy_button = QPushButton("선택 행 복사", self)
        self.clear_button = QPushButton("세션 로그 지우기", self)
        self.export_button = QPushButton("진단 패키지 내보내기", self)
        self.export_button.setObjectName("primary_button")
        footer.addWidget(self.pause_button)
        footer.addWidget(self.auto_scroll_checkbox)
        footer.addWidget(self.copy_button)
        footer.addWidget(self.clear_button)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)

        self.search_edit.textChanged.connect(lambda _text: self.refresh(force=True))
        self.level_combo.currentIndexChanged.connect(
            lambda _index: self.refresh(force=True)
        )
        self.source_combo.currentIndexChanged.connect(
            lambda _index: self.refresh(force=True)
        )
        self.pause_button.toggled.connect(self._set_paused)
        self.copy_button.clicked.connect(self.copy_selected_row)
        self.clear_button.clicked.connect(self.clear_events)
        self.export_button.clicked.connect(self._request_export)

    def _request_export(self) -> None:
        if callable(self.export_requested):
            self.export_requested()

    def _set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self.pause_button.setText(
            "화면 업데이트 다시 시작" if self.paused else "화면 업데이트 일시정지"
        )
        self._update_state_label()
        if not self.paused:
            self.refresh(force=True)

    def _update_state_label(self) -> None:
        text = "세션 수집 중"
        if self.paused:
            text += " · 화면 일시정지"
        self.state_label.setText(text)

    def refresh(self, *, force: bool = False) -> None:
        self._update_state_label()
        if self.paused and not force:
            return
        snapshot = self.service.snapshot()
        self._last_snapshot = snapshot
        if force or snapshot.version != self._last_version:
            self._rebuild_table(snapshot)
            self._last_version = snapshot.version

    def _event_matches(self, event: DiagnosticEvent) -> bool:
        search = self.search_edit.text().strip().casefold()
        if search and search not in event.searchable_text:
            return False
        level = str(self.level_combo.currentData() or "")
        if level and event.level.value != level:
            return False
        source = str(self.source_combo.currentData() or "")
        return not (source and event.source.value != source)

    def _rebuild_table(self, snapshot: DiagnosticSnapshot) -> None:
        selected_sequence = None
        row = self.table.currentRow()
        if row >= 0 and row < len(self._visible_events):
            selected_sequence = self._visible_events[row].sequence
        matched = tuple(
            event for event in snapshot.events if self._event_matches(event)
        )
        visible = matched[-DIAGNOSTIC_TABLE_ROW_LIMIT:]
        self._visible_events = visible
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        selected_row = -1
        try:
            self.table.setRowCount(len(visible))
            for row_index, event in enumerate(visible):
                if event.sequence == selected_sequence:
                    selected_row = row_index
                try:
                    timestamp = datetime.fromisoformat(event.occurred_at).astimezone()
                    display_time = timestamp.strftime("%H:%M:%S.%f")[:-3]
                except ValueError:
                    display_time = event.occurred_at
                values = (
                    display_time,
                    _LEVEL_LABELS.get(event.level, event.level.value),
                    _SOURCE_LABELS.get(event.source, event.source.value),
                    event.event_kind,
                    event.short_operation_id,
                    event.message,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, event.sequence)
                    item.setToolTip(value)
                    self.table.setItem(row_index, column, item)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)
        matched_note = (
            f" / 필터 결과 {len(matched)}건"
            if len(matched) > len(visible)
            else ""
        )
        self.table_state_label.setText(
            f"표시 {len(visible)}건{matched_note} / 세션 보관 {len(snapshot.events)}건"
        )
        if visible:
            if selected_row >= 0:
                self.table.selectRow(selected_row)
            elif self.auto_scroll_checkbox.isChecked():
                self.table.selectRow(len(visible) - 1)
                self.table.scrollToBottom()
            else:
                self.table.selectRow(0)
            self._show_selected_detail()
        else:
            self.detail_view.clear()

    def _show_selected_detail(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._visible_events):
            self.detail_view.clear()
            return
        event = self._visible_events[row]
        payload = event.to_payload()
        self.detail_view.setPlainText(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        )

    def copy_selected_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.table_state_label.setText("복사할 로그를 먼저 선택하세요.")
            return
        values = []
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            values.append("" if item is None else item.text())
        QApplication.clipboard().setText("\t".join(values))
        self.table_state_label.setText("선택한 안전한 진단 메타데이터를 복사했습니다.")

    def clear_events(self) -> None:
        self.service.clear()
        self.refresh(force=True)

    def start_refresh(self) -> None:
        self.refresh_timer.start()

    def stop_refresh(self) -> None:
        self.refresh_timer.stop()


class DeveloperToolsWindow(QDialog):
    """Non-modal home for diagnostics and the existing API monitor."""

    if TYPE_CHECKING:
        # 패널은 `MainWindow` 가 개발자 도구를 열 때 밖에서 붙인다.
        # 여기서는 그 계약을 선언만 해 둔다.
        excel_tool_panel: ExcelToolPanel
        payload_tool_panel: PayloadToolPanel
        schema_cache_tool_panel: SchemaCacheToolPanel
        read_only_query_tool_panel: ReadOnlyQueryToolPanel

    def __init__(
        self,
        diagnostics: DiagnosticService,
        api_monitor: ApiMonitorService,
        *,
        settings_provider=None,
        activity_provider=None,
        default_directory: str | Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.diagnostics = diagnostics
        self.api_monitor = api_monitor
        self.settings_provider = settings_provider
        self.activity_provider = activity_provider
        self.default_directory = Path(default_directory or Path.cwd())

        self.setObjectName("developer_tools_window")
        self.setWindowTitle("개발자 도구")
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(960, 640)
        self.resize(1320, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(8)
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("developer_tools_tabs")
        self.diagnostics_panel = DiagnosticsPanel(
            diagnostics,
            export_requested=self._choose_export_path,
            parent=self.tabs,
        )
        self.api_panel = ApiMonitorPanel(
            api_monitor,
            settings_provider=settings_provider,
            embedded=True,
            parent=self.tabs,
        )
        self.tabs.addTab(self.diagnostics_panel, "진단 로그")
        self.tabs.addTab(self.api_panel, "API 모니터")
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel(
            "로그는 세션 메모리에만 보관되며, 원본 요청·응답과 Excel 값은 수집하지 않습니다.",
            self,
        )
        self.status_label.setObjectName("section_label")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        close_button = QPushButton("닫기", self)
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    @property
    def collection_state_label(self):
        """Compatibility proxy for callers that used ApiMonitorWindow directly."""
        return self.api_panel.collection_state_label

    @property
    def last_snapshot(self):
        return self.api_panel.last_snapshot

    def refresh(self, *, force: bool = False) -> None:
        self.diagnostics_panel.refresh(force=force)
        self.api_panel.refresh(force=force)

    def select_api_tab(self) -> None:
        self.tabs.setCurrentWidget(self.api_panel)
        self.api_panel.refresh(force=True)

    def select_diagnostics_tab(self) -> None:
        self.tabs.setCurrentWidget(self.diagnostics_panel)
        self.diagnostics_panel.refresh(force=True)

    def add_tool_tab(self, widget: QWidget, label: str) -> int:
        """Register an independently implemented developer tool panel."""
        if not isinstance(widget, QWidget):
            raise TypeError("개발자 도구 탭은 QWidget이어야 합니다.")
        normalized_label = str(label or "").strip()
        if not normalized_label:
            raise ValueError("개발자 도구 탭 이름이 필요합니다.")
        return self.tabs.addTab(widget, normalized_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.diagnostics_panel.start_refresh()
        self.api_panel.start_refresh()
        self.refresh(force=True)

    def closeEvent(self, event) -> None:
        self.diagnostics_panel.stop_refresh()
        self.api_panel.stop_refresh()
        super().closeEvent(event)

    def _current_settings(self):
        if not callable(self.settings_provider):
            return None
        try:
            return self.settings_provider()
        except Exception:
            return None

    def _activity_records(self):
        if not callable(self.activity_provider):
            return ()
        try:
            return tuple(self.activity_provider())
        except Exception:
            return ()

    def export_to_path(self, path: str | Path) -> DiagnosticBundleSummary:
        settings = self._current_settings()
        diagnostics_snapshot = self.diagnostics.snapshot()
        api_snapshot = self.api_monitor.snapshot()
        summary = export_diagnostic_bundle(
            path,
            diagnostics_snapshot=diagnostics_snapshot,
            api_events=api_snapshot.events,
            activity_records=self._activity_records(),
            offline_mode=bool(getattr(settings, "offline_mode", False)),
        )
        self.diagnostics.record(
            level=DiagnosticLevel.INFO,
            source=DiagnosticSource.APPLICATION,
            event_kind="diagnostic_bundle_exported",
            message="진단 패키지를 저장했습니다.",
            details={
                "diagnostic_count": summary.diagnostic_count,
                "api_event_count": summary.api_event_count,
                "activity_count": summary.activity_count,
            },
        )
        self.status_label.setText(
            f"진단 패키지를 저장했습니다: 진단 {summary.diagnostic_count}건, "
            f"API {summary.api_event_count}건, 실행 요약 {summary.activity_count}건"
        )
        self.diagnostics_panel.refresh(force=True)
        return summary

    def _choose_export_path(self) -> None:
        default_name = datetime.now().strftime("diagnostics-%Y%m%d-%H%M%S.zip")
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "진단 패키지 저장",
            str(self.default_directory / default_name),
            "ZIP 파일 (*.zip)",
        )
        if not selected:
            return
        target = Path(selected)
        if target.suffix.casefold() != ".zip":
            target = target.with_suffix(".zip")
        try:
            self.export_to_path(target)
        except Exception as exc:
            self.status_label.setText("진단 패키지를 저장하지 못했습니다.")
            notify_user_error(
                "진단 패키지 저장 실패",
                str(exc) or "진단 패키지를 저장하지 못했습니다.",
                parent=self,
            )


__all__ = [
    "DIAGNOSTIC_REFRESH_INTERVAL_MS",
    "DeveloperToolsWindow",
    "DiagnosticsPanel",
]
