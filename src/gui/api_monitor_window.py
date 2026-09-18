from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QGridLayout
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QHeaderView
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QTableWidget
from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtWidgets import QVBoxLayout

from src.api_monitor import API_OUTCOME_FAILED
from src.api_monitor import API_OUTCOME_RETRY
from src.api_monitor import API_OUTCOME_SUCCESS
from src.api_monitor import ApiMonitorService
from src.api_monitor import ApiMonitorSnapshot
from src.api_monitor import ApiRequestEvent


API_MONITOR_REFRESH_INTERVAL_MS = 200

_OUTCOME_LABELS = {
    API_OUTCOME_SUCCESS: "성공",
    API_OUTCOME_FAILED: "실패",
    API_OUTCOME_RETRY: "재시도",
}
_ERROR_KIND_LABELS = {
    "Timeout": "시간 초과",
    "Connection": "연결 실패",
    "RateLimit": "요청 제한",
    "HTTP": "HTTP 오류",
    "Parse": "응답 해석 실패",
    "Unknown": "알 수 없는 오류",
}


class ApiMonitorPanel(QFrame):
    """Reusable live view over metadata-only API monitor events."""

    TABLE_HEADERS = (
        "시각",
        "요청 종류",
        "Method",
        "API 경로",
        "Status",
        "소요 시간",
        "결과",
        "시도",
        "진단 ID",
    )

    def __init__(
        self,
        monitor: ApiMonitorService,
        *,
        settings_provider=None,
        embedded: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.monitor = monitor
        self.settings_provider = settings_provider
        self.paused = False
        self._last_table_version = -1
        self._last_snapshot: ApiMonitorSnapshot | None = None

        self.embedded = bool(embedded)
        self.setObjectName("api_monitor_panel")
        if not self.embedded:
            self.setWindowTitle("Codebeamer API 모니터")
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.WindowMinMaxButtonsHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            self.setMinimumSize(900, 600)
            self.resize(1280, 760)
        self._build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(API_MONITOR_REFRESH_INTERVAL_MS)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.refresh(force=True)

    @property
    def last_snapshot(self) -> ApiMonitorSnapshot | None:
        return self._last_snapshot

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 12, 14, 12)
        root_layout.setSpacing(10)

        heading = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("Codebeamer API 모니터", self)
        title.setObjectName("application_route_title")
        description = QLabel(
            "최근 최대 500건 기준 · 요청/응답 본문, 인증 정보, 쿼리 값은 수집하지 않습니다.",
            self,
        )
        description.setObjectName("application_route_description")
        title_group.addWidget(title)
        title_group.addWidget(description)
        heading.addLayout(title_group)
        heading.addStretch(1)
        self.collection_state_label = QLabel("", self)
        self.collection_state_label.setObjectName("api_monitor_collection_state")
        heading.addWidget(self.collection_state_label)
        root_layout.addLayout(heading)

        stats_frame = QFrame(self)
        stats_frame.setObjectName("api_monitor_stats")
        stats_layout = QGridLayout(stats_frame)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setHorizontalSpacing(7)
        stats_layout.setVerticalSpacing(7)
        stat_specs = (
            ("total", "완료 요청"),
            ("active", "진행 중"),
            ("success_rate", "성공률"),
            ("failed", "실패"),
            ("average", "평균"),
            ("p50", "P50"),
            ("p95", "P95"),
            ("maximum", "최대"),
            ("rpm", "최근 1분"),
            ("rate_limit", "429"),
            ("retries", "재시도"),
            ("slow", "느린 요청"),
        )
        self.stat_value_labels: dict[str, QLabel] = {}
        for index, (key, label_text) in enumerate(stat_specs):
            card = QFrame(stats_frame)
            card.setObjectName("api_monitor_stat_card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(9, 7, 9, 7)
            card_layout.setSpacing(2)
            label = QLabel(label_text, card)
            label.setObjectName("api_monitor_stat_label")
            value = QLabel("-", card)
            value.setObjectName("api_monitor_stat_value")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            self.stat_value_labels[key] = value
            stats_layout.addWidget(card, index // 6, index % 6)
        for column in range(6):
            stats_layout.setColumnStretch(column, 1)
        root_layout.addWidget(stats_frame)

        filters = QFrame(self)
        filters.setObjectName("api_monitor_filters")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(8, 7, 8, 7)
        filter_layout.setSpacing(7)
        self.search_edit = QLineEdit(filters)
        self.search_edit.setPlaceholderText("요청 종류, API 경로 또는 진단 ID 검색")
        self.method_combo = QComboBox(filters)
        for option_label, option_value in (
            ("모든 Method", ""),
            ("GET", "GET"),
            ("POST", "POST"),
            ("PUT", "PUT"),
            ("DELETE", "DELETE"),
        ):
            self.method_combo.addItem(option_label, option_value)
        self.status_combo = QComboBox(filters)
        for label, value in (
            ("모든 Status", ""),
            ("2xx", "2xx"),
            ("3xx", "3xx"),
            ("4xx", "4xx"),
            ("5xx", "5xx"),
            ("429", "429"),
            ("Status 없음", "none"),
        ):
            self.status_combo.addItem(label, value)
        self.outcome_combo = QComboBox(filters)
        for label, value in (
            ("모든 결과", ""),
            ("성공", API_OUTCOME_SUCCESS),
            ("실패", API_OUTCOME_FAILED),
            ("재시도", API_OUTCOME_RETRY),
        ):
            self.outcome_combo.addItem(label, value)
        self.slow_only_checkbox = QCheckBox("느린 요청만", filters)
        filter_layout.addWidget(self.search_edit, 1)
        filter_layout.addWidget(self.method_combo)
        filter_layout.addWidget(self.status_combo)
        filter_layout.addWidget(self.outcome_combo)
        filter_layout.addWidget(self.slow_only_checkbox)
        root_layout.addWidget(filters)

        self.table = QTableWidget(0, len(self.TABLE_HEADERS), self)
        self.table.setObjectName("api_monitor_table")
        self.table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        for column, width in enumerate((90, 180, 70, 310, 75, 100, 130, 80, 90)):
            self.table.setColumnWidth(column, width)
        root_layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.table_state_label = QLabel("표시 0건", self)
        self.table_state_label.setObjectName("section_label")
        footer.addWidget(self.table_state_label)
        footer.addStretch(1)
        self.pause_button = QPushButton("화면 업데이트 일시정지", self)
        self.pause_button.setCheckable(True)
        self.auto_scroll_checkbox = QCheckBox("새 요청 자동 스크롤", self)
        self.auto_scroll_checkbox.setChecked(True)
        self.copy_button = QPushButton("선택 행 복사", self)
        self.clear_button = QPushButton("기록 지우기", self)
        self.close_button = QPushButton("닫기", self)
        footer.addWidget(self.pause_button)
        footer.addWidget(self.auto_scroll_checkbox)
        footer.addWidget(self.copy_button)
        footer.addWidget(self.clear_button)
        footer.addWidget(self.close_button)
        self.close_button.setVisible(not self.embedded)
        root_layout.addLayout(footer)

        self.search_edit.textChanged.connect(lambda _text: self.refresh(force=True))
        self.method_combo.currentIndexChanged.connect(lambda _index: self.refresh(force=True))
        self.status_combo.currentIndexChanged.connect(lambda _index: self.refresh(force=True))
        self.outcome_combo.currentIndexChanged.connect(lambda _index: self.refresh(force=True))
        self.slow_only_checkbox.toggled.connect(lambda _checked: self.refresh(force=True))
        self.pause_button.toggled.connect(self._set_paused)
        self.copy_button.clicked.connect(self.copy_selected_row)
        self.clear_button.clicked.connect(self.clear_events)
        self.close_button.clicked.connect(self.close)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.start_refresh()
        self.refresh(force=True)

    def hideEvent(self, event) -> None:
        self.stop_refresh()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.stop_refresh()
        super().closeEvent(event)

    def start_refresh(self) -> None:
        self.refresh_timer.start()

    def stop_refresh(self) -> None:
        self.refresh_timer.stop()

    def _set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self.pause_button.setText(
            "화면 업데이트 다시 시작" if self.paused else "화면 업데이트 일시정지"
        )
        if not self.paused:
            self.refresh(force=True)

    def _is_test_mode(self) -> bool:
        if not callable(self.settings_provider):
            return False
        try:
            settings = self.settings_provider()
        except Exception:
            return False
        return bool(getattr(settings, "offline_mode", False))

    def _update_collection_state(self, snapshot: ApiMonitorSnapshot) -> None:
        if snapshot.enabled:
            if self._is_test_mode():
                text = "수집 대기 · 테스트 모드에는 외부 API 요청이 없습니다"
                state = "test"
            else:
                text = "수집 중"
                state = "enabled"
        else:
            text = "수집 중지 · 설정 > 개발자에서 켤 수 있습니다"
            state = "disabled"
        if self.paused:
            text += " · 화면 일시정지"
        self.collection_state_label.setText(text)
        self.collection_state_label.setProperty("state", state)
        self.collection_state_label.style().unpolish(self.collection_state_label)
        self.collection_state_label.style().polish(self.collection_state_label)

    def refresh(self, *, force: bool = False) -> None:
        snapshot = self.monitor.snapshot()
        self._update_collection_state(snapshot)
        if self.paused and not force:
            return
        self._last_snapshot = snapshot
        self._update_stats(snapshot)
        if force or snapshot.version != self._last_table_version:
            self._rebuild_table(snapshot)
            self._last_table_version = snapshot.version

    def _update_stats(self, snapshot: ApiMonitorSnapshot) -> None:
        stats = snapshot.stats
        values = {
            "total": str(stats.total),
            "active": str(stats.active),
            "success_rate": f"{stats.success_rate:.1f}%",
            "failed": str(stats.failed),
            "average": f"{stats.average_ms:.1f} ms",
            "p50": f"{stats.p50_ms:.1f} ms",
            "p95": f"{stats.p95_ms:.1f} ms",
            "maximum": f"{stats.max_ms:.1f} ms",
            "rpm": f"{stats.requests_last_minute}건",
            "rate_limit": str(stats.rate_limited),
            "retries": str(stats.retries),
            "slow": f"{stats.slow}건",
        }
        for key, value in values.items():
            self.stat_value_labels[key].setText(value)

    def _event_matches(self, event: ApiRequestEvent, snapshot: ApiMonitorSnapshot) -> bool:
        search_text = self.search_edit.text().strip().casefold()
        if (
            search_text
            and search_text not in event.request_kind.casefold()
            and search_text not in event.path.casefold()
            and search_text not in event.operation_id.casefold()
        ):
            return False
        method = str(self.method_combo.currentData() or "")
        if method and event.method != method:
            return False
        outcome = str(self.outcome_combo.currentData() or "")
        if outcome and event.outcome != outcome:
            return False
        status_filter = str(self.status_combo.currentData() or "")
        if status_filter == "none" and event.status_code is not None:
            return False
        if status_filter == "429" and event.status_code != 429:
            return False
        if status_filter.endswith("xx") and (
            event.status_code is None or event.status_code // 100 != int(status_filter[0])
        ):
            return False
        return not (self.slow_only_checkbox.isChecked() and event.elapsed_ms < snapshot.slow_threshold_ms)

    def _rebuild_table(self, snapshot: ApiMonitorSnapshot) -> None:
        events = [event for event in snapshot.events if self._event_matches(event, snapshot)]
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(events))
            for row, event in enumerate(events):
                result = _OUTCOME_LABELS.get(event.outcome, event.outcome)
                if event.error_kind:
                    result = f"{result} · {_ERROR_KIND_LABELS.get(event.error_kind, event.error_kind)}"
                values = (
                    datetime.fromtimestamp(event.started_at).strftime("%H:%M:%S.%f")[:-3],
                    event.request_kind,
                    event.method,
                    event.path,
                    "-" if event.status_code is None else str(event.status_code),
                    f"{event.elapsed_ms:.1f} ms",
                    result,
                    f"{event.attempt}/{event.max_attempts}",
                    event.operation_id[:8] if event.operation_id else "-",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, event.sequence)
                    if column in {2, 4, 5, 7, 8}:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row, column, item)
        finally:
            self.table.setUpdatesEnabled(True)
        self.table_state_label.setText(
            f"표시 {len(events)}건 / 보관 {len(snapshot.events)}건 · "
            f"느린 요청 기준 {snapshot.slow_threshold_ms} ms"
        )
        if events and self.auto_scroll_checkbox.isChecked():
            self.table.scrollToBottom()

    def copy_selected_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.table_state_label.setText("복사할 행을 먼저 선택하세요.")
            return
        values = []
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            values.append("" if item is None else item.text())
        QApplication.clipboard().setText("\t".join(values))
        self.table_state_label.setText("선택한 요청 메타데이터를 복사했습니다.")

    def clear_events(self) -> None:
        self.monitor.clear()
        self.refresh(force=True)


class ApiMonitorWindow(ApiMonitorPanel):
    """Compatibility wrapper that keeps the existing stand-alone API window."""

    def __init__(
        self,
        monitor: ApiMonitorService,
        *,
        settings_provider=None,
        parent=None,
    ) -> None:
        super().__init__(
            monitor,
            settings_provider=settings_provider,
            embedded=False,
            parent=parent,
        )
        self.setObjectName("api_monitor_window")


__all__ = [
    "API_MONITOR_REFRESH_INTERVAL_MS",
    "ApiMonitorPanel",
    "ApiMonitorWindow",
]
