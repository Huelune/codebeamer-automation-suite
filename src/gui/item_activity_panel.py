"""변경 이력 탭의 활동 이력 패널.

기준 Baseline과 유형을 고르는 도구줄, 상태줄, 필드별 요약 표, 시간순 트리를 묶는다.
Baseline 비교 탭과 상세 창이 같은 패널을 쓰고, 조회는 생성자로 받은 콜백에 맡긴다.
받아 둔 데이터는 구간과 유형을 바꿔도 다시 묻지 않고 거르기만 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtCore import Signal
    from PySide6.QtGui import QStandardItemModel
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QCheckBox
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QSplitter
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .activity_history import ActivityOperation
from .activity_history import ActivityRecord
from .activity_history import ActivityResult
from .item_activity import ACTIVITY_KIND_LABELS
from .item_activity import ALL_SCOPE
from .item_activity import ActivityScope
from .item_activity import BaselineMarker
from .item_activity import FilteredActivity
from .item_activity import ItemActivityEntry
from .item_activity import ItemActivityKind
from .item_activity import ItemActivitySummary
from .item_activity import attachment_entries
from .item_activity import baseline_scope
from .item_activity import comment_entries
from .item_activity import filter_entries
from .item_activity import history_entries
from .item_activity import merge_entries
from .item_activity import summarize
from .item_activity_export import ItemActivityExportRequest
from .item_activity_export import export_item_activity_xlsx
from .item_change_history_view import MAX_CELL_TEXT
from .item_change_history_view import MAX_TOOLTIP_TEXT
from .item_change_history_view import ItemChangeHistoryView
from .item_change_history_view import history_time_text
from .item_change_history_view import plain_tooltip
from .tracker_baseline_compare import TrackerBaseline
from .tracker_baseline_compare import display_tracker_value
from .tracker_workspace_support import SortableTableItem


BETWEEN_POINTS = "between"
ALL_SCOPE_DATA = ""
_RELATION_TOOLTIP = "서버 응답에 시각 정보가 없어 지원하지 않습니다"
_NO_CREATED_AT_TOOLTIP = "생성 시각이 없어 기준으로 쓸 수 없습니다"


def _cell_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ItemActivityPanel(QWidget):
    """변경 이력 탭 하나. 아이템 하나의 활동 이력을 구간과 유형으로 걸러 보인다."""

    export_requested = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        request_kind: Callable[[ItemActivityKind, bool], None],
        between_points: bool = False,
    ) -> None:
        super().__init__(parent)
        self._request_kind = request_kind
        self._between_points = between_points
        self._item_id: int | None = None
        self._item_name = ""
        self._tracker_name = ""
        self._current_version: int | None = None
        self._marker: BaselineMarker | None = None
        self._between_scope: ActivityScope | None = None
        self._baselines: dict[int, TrackerBaseline] = {}
        self._sources: dict[ItemActivityKind, tuple[ItemActivityEntry, ...]] = {}
        self._loading: set[ItemActivityKind] = set()
        self._errors: dict[ItemActivityKind, str] = {}
        self._active = False
        self._export_busy = False
        self._export_message = ""
        self._note = ""
        self._waiting_message = "아이템을 고르면 변경 이력을 볼 수 있습니다."
        self._visible = FilteredActivity(())
        self._summary = ItemActivitySummary()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("기준 Baseline", self))
        self.baseline_combo = QComboBox(self)
        self.baseline_combo.setObjectName("activity_baseline_combo")
        # Baseline 이름이 길어도 창을 넓히지 않게 비교 탭 소스 콤보와 같은 정책을 쓴다.
        self.baseline_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.baseline_combo.setMinimumContentsLength(8)
        self.baseline_combo.currentIndexChanged.connect(self._render)
        toolbar.addWidget(self.baseline_combo, 1)
        self.kind_checks: dict[ItemActivityKind, QCheckBox] = {}
        for kind in ItemActivityKind:
            check = QCheckBox(ACTIVITY_KIND_LABELS[kind], self)
            check.setChecked(True)
            check.toggled.connect(self._on_kinds_changed)
            self.kind_checks[kind] = check
            toolbar.addWidget(check)
        self.relation_check = QCheckBox("관계", self)
        self.relation_check.setEnabled(False)
        self.relation_check.setToolTip(_RELATION_TOOLTIP)
        toolbar.addWidget(self.relation_check)
        self.retry_button = QPushButton("다시 시도", self)
        self.retry_button.hide()
        self.retry_button.clicked.connect(self._retry)
        toolbar.addWidget(self.retry_button)
        self.export_button = QPushButton("이력 Excel 내보내기", self)
        self.export_button.setObjectName("activity_export_button")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("tracker_panel_status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        summary_box = QWidget(splitter)
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_label = QLabel(summary_box)
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        self.summary_table = QTableWidget(0, 5, summary_box)
        self.summary_table.setObjectName("activity_field_summary")
        self.summary_table.setHorizontalHeaderLabels(
            ["필드", "구간 처음 값", "구간 마지막 값", "변경 횟수", "마지막 수정"]
        )
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.summary_table.setWordWrap(True)
        self.summary_table.verticalHeader().setVisible(False)
        header = self.summary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.summary_table.setColumnWidth(0, 180)
        self.summary_table.setSortingEnabled(True)
        header.setSortIndicator(3, Qt.SortOrder.DescendingOrder)
        summary_layout.addWidget(self.summary_table, 1)
        self.history_view = ItemChangeHistoryView(splitter)
        splitter.addWidget(summary_box)
        splitter.addWidget(self.history_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self._fill_baseline_combo()
        self._render()

    # 소유자가 부르는 메서드

    def set_baselines(self, baselines: tuple[TrackerBaseline, ...]) -> None:
        self._baselines = {baseline.baseline_id: baseline for baseline in baselines}
        self._fill_baseline_combo()
        self._render()

    def select_scope(self, data: int | str) -> None:
        """구간을 고른다. 고를 수 없는 Baseline이면 전체로 둔다."""
        index = self.baseline_combo.findData(data)
        if index < 0 or not self._selectable(index):
            index = self.baseline_combo.findData(ALL_SCOPE_DATA)
        self.baseline_combo.setCurrentIndex(index)
        self._render()

    def set_item(
        self,
        item_id: int | None,
        *,
        item_name: str = "",
        tracker_name: str = "",
        current_version: int | None = None,
        marker: BaselineMarker | None = None,
        between_scope: ActivityScope | None = None,
        waiting_message: str | None = None,
    ) -> None:
        """다른 아이템이나 범위로 바꾼다. 받아 둔 데이터는 버리고, 탭이 보이면 다시 묻는다."""
        self._item_id = item_id
        self._item_name = item_name
        self._tracker_name = tracker_name
        self._current_version = current_version
        self._marker = marker
        self._between_scope = between_scope
        if waiting_message is not None:
            self._waiting_message = waiting_message
        self._sources.clear()
        self._loading.clear()
        self._errors.clear()
        self._export_message = ""
        # 요청을 먼저 걸어야 상태줄이 `조회 중`을 보인다.
        self._request_missing()
        self._render()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._request_missing()
        self._render()

    def set_note(self, text: str) -> None:
        self._note = str(text or "")
        self._render()

    def set_source(self, item_id: int, kind: ItemActivityKind, data: Any) -> None:
        if item_id != self._item_id:
            return
        self._loading.discard(kind)
        self._errors.pop(kind, None)
        if kind is ItemActivityKind.FIELD_CHANGE:
            self._sources[kind] = history_entries(data)
        elif kind is ItemActivityKind.COMMENT:
            self._sources[kind] = comment_entries(data)
        else:
            self._sources[kind] = attachment_entries(data)
        self._render()

    def set_source_error(self, item_id: int, kind: ItemActivityKind, message: str) -> None:
        if item_id != self._item_id:
            return
        self._loading.discard(kind)
        self._errors[kind] = str(message)
        self._render()

    def set_export_busy(self, busy: bool, message: str = "") -> None:
        self._export_busy = bool(busy)
        self._export_message = message
        self._render()

    # 내부 동작

    def _checked_kinds(self) -> set[ItemActivityKind]:
        return {kind for kind, check in self.kind_checks.items() if check.isChecked()}

    def _selectable(self, index: int) -> bool:
        model = self.baseline_combo.model()
        if not isinstance(model, QStandardItemModel):
            return True
        item = model.item(index)
        return item is None or item.isEnabled()

    def _fill_baseline_combo(self) -> None:
        combo = self.baseline_combo
        selected = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if self._between_points:
            combo.addItem("비교 시점 사이", BETWEEN_POINTS)
        combo.addItem("전체", ALL_SCOPE_DATA)
        model = combo.model()
        for baseline in self._baselines.values():
            label = f"{baseline.name} ({baseline.created_at})" if baseline.created_at else baseline.name
            combo.addItem(label, baseline.baseline_id)
            if baseline_scope(baseline.name, baseline.created_at) is None and isinstance(model, QStandardItemModel):
                item = model.item(combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
                    item.setToolTip(_NO_CREATED_AT_TOOLTIP)
        index = combo.findData(selected) if selected is not None else -1
        combo.setCurrentIndex(index if index >= 0 and self._selectable(index) else 0)
        combo.blockSignals(False)

    def _scope(self) -> ActivityScope | None:
        data = self.baseline_combo.currentData()
        if data == BETWEEN_POINTS:
            return self._between_scope
        baseline = self._baselines.get(data) if isinstance(data, int) else None
        if baseline is None:
            return ALL_SCOPE
        return baseline_scope(baseline.name, baseline.created_at) or ALL_SCOPE

    def _request_missing(self) -> None:
        if not self._active or self._item_id is None:
            return
        for kind in ItemActivityKind:
            if kind not in self._checked_kinds():
                continue
            if kind in self._sources or kind in self._loading or kind in self._errors:
                continue
            self._loading.add(kind)
            self._request_kind(kind, False)

    def _retry(self) -> None:
        for kind in [kind for kind in ItemActivityKind if kind in self._errors]:
            del self._errors[kind]
            if kind in self._checked_kinds():
                self._loading.add(kind)
                self._request_kind(kind, True)
        self._render()

    def _on_kinds_changed(self, _checked: bool) -> None:
        self._request_missing()
        self._render()

    def _render(self, *_args: Any) -> None:
        kinds = self._checked_kinds()
        self.retry_button.setVisible(bool(self._errors))
        self._visible = FilteredActivity(())
        self._summary = ItemActivitySummary()
        scope = self._scope()
        if self._item_id is None or scope is None:
            self.history_view.clear()
            self._fill_summary_table(kinds)
            self.export_button.setEnabled(False)
            self.status_label.setText(
                self._waiting_message
                if self._item_id is None
                else f"#{self._item_id} · 두 시점의 버전 정보가 없어 사이 이력을 고를 수 없습니다."
            )
            return
        merged = merge_entries(*(self._sources[kind] for kind in ItemActivityKind if kind in self._sources))
        self._visible = filter_entries(merged, scope=scope, kinds=kinds)
        self._summary = summarize(self._visible.entries)
        self.history_view.show_entries(
            self._visible.entries, current_version=self._current_version, baseline=self._marker
        )
        self._fill_summary_table(kinds)
        ready = bool(kinds) and all(kind in self._sources for kind in kinds)
        self.export_button.setEnabled(ready and bool(self._visible.entries) and not self._export_busy)
        self.status_label.setText(self._status_text(scope, kinds))

    def _status_text(self, scope: ActivityScope, kinds: set[ItemActivityKind]) -> str:
        if not (self._active or self._sources or self._loading or self._errors):
            return f"#{self._item_id} · 탭을 열면 변경 이력을 조회합니다."
        parts = [f"#{self._item_id}", scope.label]
        loading = [ACTIVITY_KIND_LABELS[kind] for kind in ItemActivityKind if kind in self._loading and kind in kinds]
        if loading:
            parts.append(f"{'·'.join(loading)} 조회 중")
        summary = self._summary
        if ItemActivityKind.FIELD_CHANGE in kinds and ItemActivityKind.FIELD_CHANGE in self._sources:
            parts += [
                f"버전 {summary.version_count}건",
                f"필드 변경 {summary.field_change_count}건",
                f"바뀐 필드 {summary.changed_field_count}개",
            ]
            if summary.versions_without_changes:
                parts.append(f"필드 변경 정보 없는 버전 {summary.versions_without_changes}건")
        if ItemActivityKind.COMMENT in kinds and ItemActivityKind.COMMENT in self._sources:
            parts.append(f"댓글 {summary.comment_count}건")
        if ItemActivityKind.ATTACHMENT in kinds and ItemActivityKind.ATTACHMENT in self._sources:
            parts.append(f"첨부 {summary.attachment_count}건")
        if not kinds:
            parts.append("유형을 하나 이상 고르세요.")
        if self._visible.untimed_count:
            parts.append(f"시각 없는 항목 {self._visible.untimed_count}건 제외")
        if self._visible.undetermined_count:
            parts.append("Baseline 생성 시각이 없어 댓글·첨부 구간을 정할 수 없습니다")
        parts += [
            f"{ACTIVITY_KIND_LABELS[kind]} 조회 실패: {message}"
            for kind, message in self._errors.items()
            if kind in kinds
        ]
        parts += [text for text in (self._note, self._export_message) if text]
        return " · ".join(parts)

    def _fill_summary_table(self, kinds: set[ItemActivityKind]) -> None:
        table = self.summary_table
        header = table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        table.setSortingEnabled(False)
        table.setRowCount(0)
        fields = self._summary.fields
        if ItemActivityKind.FIELD_CHANGE not in kinds:
            self.summary_label.setText("필드 변경 유형을 켜면 필드별 요약을 보입니다.")
        elif fields:
            self.summary_label.setText(f"필드별 요약 · 바뀐 필드 {len(fields)}개")
        else:
            self.summary_label.setText("구간에 바뀐 필드가 없습니다.")
        if ItemActivityKind.FIELD_CHANGE in kinds:
            table.setRowCount(len(fields))
            for row, field in enumerate(fields):
                first = display_tracker_value(field.first_value)
                last = display_tracker_value(field.last_value)
                modified = " · ".join(part for part in (history_time_text(field.last_at), field.last_by) if part)
                values = (field.field_name, first, last, str(field.change_count), modified)
                sort_values = (
                    field.field_name.casefold(),
                    first.casefold(),
                    last.casefold(),
                    field.change_count,
                    field.last_at,
                )
                for column, value in enumerate(values):
                    cell = SortableTableItem(_cell_text(value, MAX_CELL_TEXT), sort_values[column])
                    cell.setToolTip(plain_tooltip(_cell_text(value, MAX_TOOLTIP_TEXT)))
                    table.setItem(row, column, cell)
        table.setSortingEnabled(True)
        table.sortItems(sort_column, sort_order)

    def _export(self) -> None:
        scope = self._scope()
        if self._item_id is None or scope is None or not self._visible.entries:
            return
        kinds = self._checked_kinds()
        self.export_requested.emit(
            ItemActivityExportRequest(
                item_id=self._item_id,
                item_name=self._item_name,
                tracker_name=self._tracker_name,
                scope_label=scope.label,
                kind_labels=tuple(ACTIVITY_KIND_LABELS[kind] for kind in ItemActivityKind if kind in kinds),
                entries=self._visible.entries,
                summary=self._summary,
                baseline=self._marker,
            )
        )


def run_activity_export(
    parent: QWidget,
    panel: ItemActivityPanel,
    request: ItemActivityExportRequest,
    *,
    submit: Callable[..., Any],
    record_activity: Callable[[ActivityRecord], None],
    show_error: Callable[..., None],
    source: str,
    project_id: int | None,
    project_name: str,
    tracker_id: int | None,
    tracker_name: str,
) -> None:
    """파일 위치를 묻고 백그라운드로 저장한 뒤 결과를 패널과 실행 기록에 남긴다.

    비교 탭과 상세 창이 같은 흐름을 쓴다.
    """
    output_path, _selected_filter = QFileDialog.getSaveFileName(
        parent,
        "변경 이력 Excel 저장",
        f"item_history_{request.item_id}.xlsx",
        "Excel 통합 문서 (*.xlsx)",
    )
    if not output_path:
        return

    def record(result: ActivityResult, summary: str, details: dict[str, Any]) -> None:
        record_activity(
            ActivityRecord.create(
                ActivityOperation.ITEM_HISTORY_EXPORT,
                result,
                source=source,
                summary=summary,
                project_id=project_id,
                project_name=project_name,
                tracker_id=tracker_id,
                tracker_name=tracker_name,
                item_id=request.item_id,
                item_name=request.item_name,
                details=details,
            )
        )

    def completed(summary: Any) -> None:
        panel.set_export_busy(False, f"Excel 내보내기 완료 · 항목 {summary.entry_count}건 · 행 {summary.row_count}개")
        record(
            ActivityResult.SUCCESS,
            f"#{request.item_id} 변경 이력 {summary.entry_count}건을 Excel로 내보냈습니다.",
            {
                "kindCount": len(request.kind_labels),
                "entryCount": summary.entry_count,
                "rowCount": summary.row_count,
                "longValueCount": summary.long_value_count,
            },
        )

    def failed(exc: Exception) -> None:
        panel.set_export_busy(False, "Excel 내보내기 실패")
        show_error(exc, prefix="변경 이력 Excel 내보내기 실패")
        record(
            ActivityResult.FAILED,
            "변경 이력 Excel 내보내기 실패",
            {"kindCount": len(request.kind_labels), "entryCount": len(request.entries)},
        )

    panel.set_export_busy(True, "Excel 파일을 만드는 중입니다.")
    submit("item_activity_export", lambda: export_item_activity_xlsx(request, output_path), completed, failed)
