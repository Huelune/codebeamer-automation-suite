from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QDialog
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
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .activity_history import ACTIVITY_OPERATION_LABELS
from .activity_history import ACTIVITY_RESULT_LABELS
from .activity_history import ActivityHistoryError
from .activity_history import ActivityHistoryStore
from .activity_history import ActivityOperation
from .activity_history import ActivityRecord
from .activity_history import ActivityResult


ACTIVITY_RECORD_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def _display_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return str(value or "-")
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


class ConfirmActivityHistoryClearDialog(QDialog):
    def __init__(self, record_count: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("activity_history_clear_dialog")
        self.setWindowTitle("실행 기록 비우기")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QLabel("저장된 실행 기록을 비웁니다.", self)
        title.setObjectName("alert_title")
        layout.addWidget(title)
        message = QLabel(
            f"현재 기록 {int(record_count)}건이 로컬 파일에서 제거됩니다. "
            "이 작업은 되돌릴 수 없습니다.",
            self,
        )
        message.setObjectName("alert_message")
        message.setWordWrap(True)
        layout.addWidget(message)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소", self)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        clear_button = QPushButton("기록 비우기", self)
        clear_button.setObjectName("danger_button")
        clear_button.clicked.connect(self.accept)
        button_row.addWidget(clear_button)
        layout.addLayout(button_row)

    @classmethod
    def confirm(cls, record_count: int, parent=None) -> bool:
        dialog = cls(record_count, parent)
        return dialog.exec() == QDialog.DialogCode.Accepted


class ActivityHistoryPage(QWidget):
    """최근 쓰기 작업과 배치 결과를 필터링해 확인하는 화면."""

    def __init__(
        self,
        store: ActivityHistoryStore,
        *,
        clear_confirmer: Callable[[int], bool] | None = None,
        bulk_retry_requested: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("activity_history_page")
        self.store = store
        self.clear_confirmer = clear_confirmer
        self.bulk_retry_requested = bulk_retry_requested
        self._records: tuple[ActivityRecord, ...] = ()
        self._visible_records: tuple[ActivityRecord, ...] = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("실행 기록", self)
        title.setObjectName("application_route_title")
        subtitle = QLabel(
            "단건 쓰기와 배치 작업의 최종 결과를 최근 500건까지 로컬에 보관합니다.",
            self,
        )
        subtitle.setObjectName("application_route_description")
        subtitle.setWordWrap(True)
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        heading_row.addLayout(title_group, 1)
        badge = QLabel("통합 기록", self)
        badge.setObjectName("application_phase_badge")
        heading_row.addWidget(badge)
        layout.addLayout(heading_row)

        summary_card = QFrame(self)
        summary_card.setObjectName("activity_summary_card")
        summary_layout = QHBoxLayout(summary_card)
        summary_layout.setContentsMargins(12, 9, 12, 9)
        summary_layout.setSpacing(14)
        self.total_label = QLabel("전체 0", summary_card)
        self.success_label = QLabel("성공 0", summary_card)
        self.partial_label = QLabel("일부 실패 0", summary_card)
        self.failed_label = QLabel("실패·중단 0", summary_card)
        for value in (
            self.total_label,
            self.success_label,
            self.partial_label,
            self.failed_label,
        ):
            value.setObjectName("activity_summary_value")
            summary_layout.addWidget(value)
        summary_layout.addStretch(1)
        layout.addWidget(summary_card)

        filter_row = QHBoxLayout()
        self.operation_combo = QComboBox(self)
        self.operation_combo.setObjectName("activity_operation_filter")
        self.operation_combo.addItem("모든 작업", None)
        for operation, label in ACTIVITY_OPERATION_LABELS.items():
            self.operation_combo.addItem(label, operation.value)
        self.operation_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.operation_combo)

        self.result_combo = QComboBox(self)
        self.result_combo.setObjectName("activity_result_filter")
        self.result_combo.addItem("모든 결과", None)
        for result, label in ACTIVITY_RESULT_LABELS.items():
            self.result_combo.addItem(label, result.value)
        self.result_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.result_combo)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("activity_search_input")
        self.search_input.setPlaceholderText(
            "ID, 아이템, 프로젝트, 트래커 또는 요약 검색"
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_input, 1)

        refresh_button = QPushButton("새로고침", self)
        refresh_button.clicked.connect(self.activate)
        filter_row.addWidget(refresh_button)
        self.clear_button = QPushButton("기록 비우기", self)
        self.clear_button.setObjectName("danger_button")
        self.clear_button.clicked.connect(self._clear_history)
        filter_row.addWidget(self.clear_button)
        self.retry_button = QPushButton("실패 대상 재시도", self)
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(self._retry_selected_bulk_update)
        filter_row.addWidget(self.retry_button)
        layout.addLayout(filter_row)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("activity_history_status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setObjectName("activity_history_splitter")
        splitter.setChildrenCollapsible(False)

        self.table = QTableWidget(0, 6, splitter)
        self.table.setObjectName("activity_history_table")
        self.table.setHorizontalHeaderLabels(
            ["시각", "작업", "결과", "프로젝트 / 트래커", "대상", "요약"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self.table.itemSelectionChanged.connect(self._show_selected_detail)
        splitter.addWidget(self.table)

        detail_frame = QFrame(splitter)
        detail_frame.setObjectName("activity_detail_card")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(10, 8, 10, 8)
        detail_layout.setSpacing(5)
        detail_title = QLabel("선택 기록 상세", detail_frame)
        detail_title.setObjectName("tracker_detail_section_title")
        detail_layout.addWidget(detail_title)
        self.detail_view = QPlainTextEdit(detail_frame)
        self.detail_view.setObjectName("activity_detail_view")
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlaceholderText("기록을 선택하면 세부 결과를 표시합니다.")
        detail_layout.addWidget(self.detail_view, 1)
        splitter.addWidget(detail_frame)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([360, 180])
        layout.addWidget(splitter, 1)

        self.activate()

    def activate(self) -> None:
        try:
            self._records = self.store.load()
        except ActivityHistoryError as exc:
            self._records = ()
            self._set_status(str(exc), tone="error")
        else:
            self._set_status(
                "저장된 실행 기록을 최신 순으로 표시합니다. "
                "서버 원본 응답과 자격증명은 저장하지 않습니다."
            )
        self._apply_filters()

    def on_activity_recorded(self, record: ActivityRecord) -> None:
        del record
        self.activate()

    def _set_status(self, message: str, *, tone: str = "info") -> None:
        self.status_label.setText(str(message or ""))
        self.status_label.setProperty("tone", tone)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _apply_filters(self, *args) -> None:
        del args
        operation_value = self.operation_combo.currentData()
        result_value = self.result_combo.currentData()
        search_text = self.search_input.text().strip().casefold()
        visible = []
        for record in self._records:
            if operation_value and record.operation.value != operation_value:
                continue
            if result_value and record.result.value != result_value:
                continue
            if search_text and search_text not in record.searchable_text:
                continue
            visible.append(record)
        self._visible_records = tuple(visible)
        self._render_records()
        self._update_summary()

    def _render_records(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._visible_records))
        for row, record in enumerate(self._visible_records):
            values = (
                _display_timestamp(record.occurred_at),
                record.operation_label,
                record.result_label,
                record.context_text,
                record.target_text,
                record.summary or "-",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(ACTIVITY_RECORD_ROLE, record)
                self.table.setItem(row, column, item)
        if self._visible_records:
            self.table.selectRow(0)
        else:
            self.detail_view.clear()
            self.retry_button.setEnabled(False)
        self.table.blockSignals(False)
        if self._visible_records:
            self._show_record_detail(self._visible_records[0])
        self.clear_button.setEnabled(bool(self._records))

    def _update_summary(self) -> None:
        records = self._visible_records
        success = sum(record.result == ActivityResult.SUCCESS for record in records)
        partial = sum(record.result == ActivityResult.PARTIAL for record in records)
        failed = sum(
            record.result in {ActivityResult.FAILED, ActivityResult.CANCELLED}
            for record in records
        )
        self.total_label.setText(f"전체 {len(records)}")
        self.success_label.setText(f"성공 {success}")
        self.partial_label.setText(f"일부 실패 {partial}")
        self.failed_label.setText(f"실패·중단 {failed}")

    def _show_selected_detail(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        record_item = self.table.item(row, 0)
        record = (
            record_item.data(ACTIVITY_RECORD_ROLE)
            if record_item is not None
            else None
        )
        if isinstance(record, ActivityRecord):
            self._show_record_detail(record)

    def _show_record_detail(self, record: ActivityRecord) -> None:
        lines = [
            f"시각: {_display_timestamp(record.occurred_at)}",
            f"작업: {record.operation_label}",
            f"결과: {record.result_label}",
            f"위치: {record.context_text}",
            f"대상: {record.target_text}",
            f"요약: {record.summary or '-'}",
        ]
        if record.parent_item_id is not None:
            lines.append(f"상위 아이템: #{record.parent_item_id}")
        if record.details:
            lines.extend(
                (
                    "",
                    "세부 정보:",
                    json.dumps(record.details, ensure_ascii=False, indent=2),
                )
            )
        self.detail_view.setPlainText("\n".join(lines))
        self.retry_button.setEnabled(
            record.operation == ActivityOperation.BULK_UPDATE
            and bool(record.details.get("run_id"))
            and int(record.details.get("failed_count") or 0)
            + int(record.details.get("rolled_back_count") or 0)
            + int(record.details.get("unattempted_count") or 0)
            > 0
            and callable(self.bulk_retry_requested)
        )

    def _retry_selected_bulk_update(self) -> None:
        selected = self.table.selectedItems()
        if not selected or not callable(self.bulk_retry_requested):
            return
        item = self.table.item(selected[0].row(), 0)
        record = item.data(ACTIVITY_RECORD_ROLE) if item is not None else None
        if not isinstance(record, ActivityRecord):
            return
        run_id = str(record.details.get("run_id") or "")
        if run_id:
            self.bulk_retry_requested(run_id)

    def _clear_history(self) -> None:
        if not self._records:
            return
        confirmed = (
            bool(self.clear_confirmer(len(self._records)))
            if self.clear_confirmer is not None
            else ConfirmActivityHistoryClearDialog.confirm(len(self._records), self)
        )
        if not confirmed:
            return
        try:
            self.store.clear()
        except ActivityHistoryError as exc:
            self._set_status(str(exc), tone="error")
            return
        self._records = ()
        self._set_status("실행 기록을 비웠습니다.")
        self._apply_filters()


__all__ = [
    "ACTIVITY_RECORD_ROLE",
    "ActivityHistoryPage",
    "ConfirmActivityHistoryClearDialog",
]
