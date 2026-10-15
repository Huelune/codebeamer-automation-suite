"""Baseline 전체 비교 기준 선택과 결과 표를 담당하는 패널.

조회와 내보내기는 생성자로 받은 콜백에 위임하고, 이 모듈은 표시만 담당한다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTabWidget
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .item_activity import ActivityScope
from .item_activity import ItemActivityKind
from .item_activity import parse_server_time
from .item_activity_export import ItemActivityExportRequest
from .item_activity_panel import ItemActivityPanel
from .tracker_baseline_compare import BaselineComparisonKind
from .tracker_baseline_compare import BaselineComparisonResult
from .tracker_baseline_compare import BaselineComparisonSource
from .tracker_baseline_compare import TrackerBaseline
from .tracker_baseline_compare import TrackerItemComparison
from .tracker_workspace_support import SortableTableItem
from .tracker_workspace_support import blend_colors


BASELINE_KIND_BADGES = {
    BaselineComparisonKind.ADDED: "＋ 신규",
    BaselineComparisonKind.REMOVED: "－ 삭제",
    BaselineComparisonKind.CHANGED: "● 변경",
    BaselineComparisonKind.UNCHANGED: "✓ 변경 없음",
}

BASELINE_KIND_ACCENTS = {
    BaselineComparisonKind.ADDED: QColor("#16A34A"),
    BaselineComparisonKind.REMOVED: QColor("#DC2626"),
    BaselineComparisonKind.CHANGED: QColor("#D97706"),
    BaselineComparisonKind.UNCHANGED: QColor("#16A34A"),
}


class BaselineComparisonPanel(QWidget):
    """전체 비교 기준 선택과 선택 아이템 상세를 함께 표시한다."""

    def __init__(
        self,
        run_comparison: Callable[[BaselineComparisonSource, BaselineComparisonSource], None],
        sources_changed: Callable[[], None],
        export_comparison: Callable[[], None],
        parent=None,
        *,
        request_activity: Callable[[TrackerItemComparison, ItemActivityKind, bool], None] | None = None,
        export_activity: Callable[[ItemActivityExportRequest], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._run_comparison = run_comparison
        self._sources_changed = sources_changed
        self._export_comparison = export_comparison
        # 고른 아이템의 이력·댓글·첨부를 유형마다 받는다. 두 시점 사이 구간은 활동 패널이 거른다.
        self._request_activity = request_activity
        self._baselines: dict[int, TrackerBaseline] = {}
        self._selected_comparison: TrackerItemComparison | None = None
        self._result: BaselineComparisonResult | None = None
        self._comparison_busy = False
        self._export_busy = False

        layout = QVBoxLayout(self)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("기준", self))
        self.before_combo = QComboBox(self)
        self.before_combo.addItem("현재 상태", None)
        source_row.addWidget(self.before_combo, 1)
        source_row.addWidget(QLabel("비교", self))
        self.after_combo = QComboBox(self)
        self.after_combo.addItem("선택하세요", "")
        self.after_combo.addItem("현재 상태", None)
        source_row.addWidget(self.after_combo, 1)
        # 기본 정책은 가장 긴 Baseline 이름만큼 최소 폭을 잡아 작업공간 창을 줄일 수 없게 만든다.
        # 6자 폭이면 "선택하세요"까지 잘리지 않고, 남는 폭은 늘어나는 칸이 채운다.
        for combo in (self.before_combo, self.after_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        self.run_button = QPushButton("전체 비교 실행", self)
        self.run_button.setObjectName("primary_button")
        self.run_button.clicked.connect(self._run)
        source_row.addWidget(self.run_button)
        self.export_button = QPushButton("Excel 내보내기", self)
        self.export_button.setObjectName("baseline_export_button")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_comparison)
        source_row.addWidget(self.export_button)
        layout.addLayout(source_row)

        self.before_combo.currentIndexChanged.connect(self._on_source_changed)
        self.after_combo.currentIndexChanged.connect(self._on_source_changed)

        self.status_label = QLabel("비교할 두 기준을 선택하세요.", self)
        self.status_label.setObjectName("tracker_panel_status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.detail = QTableWidget(0, 4, self)
        self.detail.setHorizontalHeaderLabels(["필드", "기준", "비교", "결과"])
        self.detail.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.detail.setWordWrap(True)
        self.detail.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.detail.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.detail.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.detail.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.detail.setColumnWidth(3, 64)
        self.detail.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.detail.setSortingEnabled(True)
        self.detail.horizontalHeader().setSortIndicator(
            3, Qt.SortOrder.AscendingOrder
        )
        self.detail.horizontalHeader().setToolTip(
            "열 제목을 클릭하면 해당 값으로 정렬합니다."
        )
        # 이력은 탭을 열 때만 조회한다. 아이템을 고를 때마다 서버에 묻지 않게 한다.
        self.detail_tabs = QTabWidget(self)
        self.detail_tabs.addTab(self.detail, "필드 비교")
        self.history_tab = QWidget(self.detail_tabs)
        history_layout = QVBoxLayout(self.history_tab)
        history_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_panel = ItemActivityPanel(
            self.history_tab,
            request_kind=self._request_activity_kind,
            between_points=True,
        )
        if export_activity is not None:
            self.activity_panel.export_requested.connect(export_activity)
        history_layout.addWidget(self.activity_panel, 1)
        self.detail_tabs.addTab(self.history_tab, "변경 이력")
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
        layout.addWidget(self.detail_tabs, 1)
        self._select_comparison(None)

    def _source(self, combo: QComboBox) -> BaselineComparisonSource | None:
        value = combo.currentData()
        if value == "":
            return None
        return BaselineComparisonSource(None if value is None else int(value))

    def _run(self) -> None:
        before = self._source(self.before_combo)
        after = self._source(self.after_combo)
        if before is None or after is None:
            self.status_label.setText("비교할 두 기준을 선택하세요.")
            return
        if before == after:
            self.status_label.setText("서로 다른 두 비교 기준을 선택하세요.")
            return
        self._run_comparison(before, after)

    def _on_source_changed(self, *_args) -> None:
        self._sources_changed()

    def set_baselines(self, baselines: tuple[TrackerBaseline, ...]) -> None:
        self.before_combo.blockSignals(True)
        self.after_combo.blockSignals(True)
        self.before_combo.clear()
        self.after_combo.clear()
        self.before_combo.addItem("현재 상태", None)
        self.after_combo.addItem("선택하세요", "")
        self.after_combo.addItem("현재 상태", None)
        for baseline in baselines:
            label = baseline.name
            if baseline.created_at:
                label = f"{label} ({baseline.created_at})"
            self.before_combo.addItem(label, baseline.baseline_id)
            self.after_combo.addItem(label, baseline.baseline_id)
        self.before_combo.blockSignals(False)
        self.after_combo.blockSignals(False)
        self._baselines = {baseline.baseline_id: baseline for baseline in baselines}
        self.activity_panel.set_baselines(baselines)
        self.status_label.setText(
            f"현재 트래커에서 비교 가능한 baseline {len(baselines)}개를 불러왔습니다."
        )

    def sources(self) -> tuple[BaselineComparisonSource | None, BaselineComparisonSource | None]:
        return self._source(self.before_combo), self._source(self.after_combo)

    def source_labels(self) -> tuple[str, str]:
        return self.before_combo.currentText(), self.after_combo.currentText()

    def set_loading(self, message: str) -> None:
        self._comparison_busy = True
        self.run_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status_label.setText(message)

    def set_export_busy(self, busy: bool, message: str | None = None) -> None:
        self._export_busy = bool(busy)
        self.export_button.setEnabled(
            not self._export_busy
            and not self._comparison_busy
            and self._result is not None
            and bool(self._result.items)
        )
        if message:
            self.status_label.setText(message)

    def set_result(
        self,
        result: BaselineComparisonResult,
        *,
        selected_item_id: int | None = None,
    ) -> None:
        self._result = result
        self._comparison_busy = False
        self.run_button.setEnabled(True)
        self.run_button.setText("전체 비교 다시 불러오기")
        self.export_button.setEnabled(
            not self._export_busy and not self._comparison_busy and bool(result.items)
        )
        if selected_item_id is None and len(result.items) == 1:
            selected_item_id = result.items[0].item_id
        if selected_item_id is None:
            self.detail.setRowCount(0)
            self._select_comparison(None)
            self._show_result_summary(result)
            return
        self.select_item(selected_item_id)

    def _show_result_summary(self, result: BaselineComparisonResult) -> None:
        self.status_label.setText(
            f"전체 {len(result.items)}개 · "
            f"신규 {result.count(BaselineComparisonKind.ADDED)} · "
            f"삭제 {result.count(BaselineComparisonKind.REMOVED)} · "
            f"변경 {result.count(BaselineComparisonKind.CHANGED)} · "
            f"동일 {result.count(BaselineComparisonKind.UNCHANGED)} · "
            "왼쪽에서 아이템을 선택하면 상세 비교를 표시합니다."
        )

    def select_item(self, item_id: int) -> None:
        result = self._result
        if result is None:
            self.detail.setRowCount(0)
            self._select_comparison(None)
            self.status_label.setText("전체 비교 데이터를 먼저 불러오세요.")
            return
        comparison = next(
            (item for item in result.items if item.item_id == int(item_id)),
            None,
        )
        if comparison is None:
            self.detail.setRowCount(0)
            self._select_comparison(None)
            self.status_label.setText(f"#{item_id}은(는) 전체 비교 결과에 없습니다.")
            return
        self._render_comparison(comparison)
        self._select_comparison(comparison)

    def _select_comparison(self, comparison: TrackerItemComparison | None) -> None:
        # 같은 비교 결과에서 같은 아이템을 다시 고르면 받아 둔 이력을 그대로 둔다.
        if comparison is not None and comparison is self._selected_comparison:
            return
        self._selected_comparison = comparison
        if comparison is None:
            self.activity_panel.set_item(
                None, waiting_message="아이템을 고르면 두 시점 사이 변경 이력을 볼 수 있습니다."
            )
            return
        self.activity_panel.set_item(
            comparison.item_id,
            item_name=comparison.name,
            between_scope=self._between_points_scope(comparison),
        )

    def _on_detail_tab_changed(self, _index: int) -> None:
        self.activity_panel.set_active(self.detail_tabs.currentWidget() is self.history_tab)

    def _request_activity_kind(self, kind: ItemActivityKind, force: bool) -> None:
        comparison = self._selected_comparison
        if comparison is not None and self._request_activity is not None:
            self._request_activity(comparison, kind, force)

    @staticmethod
    def history_range(comparison: TrackerItemComparison) -> tuple[int, int] | None:
        """두 시점 사이 버전 범위(앞 버전 제외, 뒤 버전 포함). 한쪽에만 있으면 처음부터 그 버전까지."""
        versions = [
            item.version
            for item in (comparison.reference, comparison.comparison)
            if item is not None and item.version is not None
        ]
        if not versions:
            return None
        if len(versions) == 1:
            return 0, versions[0]
        return min(versions), max(versions)

    def _between_points_scope(self, comparison: TrackerItemComparison) -> ActivityScope | None:
        """두 시점 사이 구간. 필드 변경은 버전 범위, 댓글·첨부는 두 시점의 생성 시각 사이로 거른다."""
        version_range = self.history_range(comparison)
        result = self._result
        if version_range is None or result is None:
            return None
        present = [
            source
            for summary, source in (
                (comparison.reference, result.reference_source),
                (comparison.comparison, result.comparison_source),
            )
            if summary is not None
        ]
        times: list[datetime | None] = []
        unknown = False
        for source in present:
            if source.is_head:
                # 현재 상태는 상한이 없다.
                times.append(None)
                continue
            baseline = self._baselines.get(int(source.baseline_id or 0))
            created_at = parse_server_time(baseline.created_at if baseline is not None else "")
            unknown = unknown or created_at is None
            times.append(created_at)
        if len(times) == 1:
            # 한쪽에만 있는 아이템은 처음부터 그 시점까지다.
            start, end = None, times[0]
        else:
            earliest = datetime.min.replace(tzinfo=UTC)
            start, end = sorted(times, key=lambda value: (value is None, value or earliest))
        return ActivityScope(
            "비교 시점 사이",
            after=start,
            until=end,
            versions=version_range,
            time_undetermined=unknown,
        )

    def set_activity(self, item_id: int, kind: ItemActivityKind, data: Any) -> None:
        self.activity_panel.set_source(int(item_id), kind, data)

    def set_activity_error(self, item_id: int, kind: ItemActivityKind, message: str) -> None:
        self.activity_panel.set_source_error(int(item_id), kind, message)

    def _render_comparison(self, comparison) -> None:
        header = self.detail.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        if sort_column < 0:
            sort_column = 3
            sort_order = Qt.SortOrder.AscendingOrder
        self.detail.setSortingEnabled(False)
        self.detail.setRowCount(0)
        changed_count = sum(field.is_changed for field in comparison.fields)
        if comparison.kind == BaselineComparisonKind.ADDED:
            detail_summary = f"신규 아이템 · 기준 필드 {len(comparison.fields)}개"
        elif comparison.kind == BaselineComparisonKind.REMOVED:
            detail_summary = f"삭제 아이템 · 비교 필드 {len(comparison.fields)}개"
        else:
            detail_summary = (
                f"변경 필드 {changed_count}개 / 전체 필드 {len(comparison.fields)}개"
            )
        self.status_label.setText(
            f"#{comparison.item_id} · {BASELINE_KIND_BADGES[comparison.kind]} · "
            f"{detail_summary}"
        )
        palette = self.detail.palette()
        base_color = palette.base().color()
        text_color = palette.text().color()
        change_accent = BASELINE_KIND_ACCENTS[comparison.kind]
        same_accent = BASELINE_KIND_ACCENTS[BaselineComparisonKind.UNCHANGED]
        changed_background = QBrush(blend_colors(base_color, change_accent, 0.18))
        changed_result_background = QBrush(
            blend_colors(base_color, change_accent, 0.32)
        )
        changed_foreground = QBrush(blend_colors(text_color, change_accent, 0.62))
        same_result_background = QBrush(
            blend_colors(base_color, same_accent, 0.16)
        )
        same_foreground = QBrush(blend_colors(text_color, same_accent, 0.52))
        self.detail.setRowCount(len(comparison.fields))
        for row, field in enumerate(comparison.fields):
            reference_text = field.after_text()
            comparison_text = field.before_text()
            if comparison.kind == BaselineComparisonKind.ADDED:
                result_text = "＋ 신규"
                result_sort = (0, row)
            elif comparison.kind == BaselineComparisonKind.REMOVED:
                result_text = "－ 삭제"
                result_sort = (1, row)
            elif field.is_changed:
                result_text = "● 변경"
                result_sort = (2, row)
            else:
                result_text = "✓ 동일"
                result_sort = (3, row)
            values = (
                field.label,
                reference_text,
                comparison_text,
                result_text,
            )
            sort_values = (
                field.label.casefold(),
                reference_text.casefold(),
                comparison_text.casefold(),
                result_sort,
            )
            for column, value in enumerate(values):
                cell = SortableTableItem(value, sort_values[column])
                cell.setToolTip(value)
                cell.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                )
                if field.is_changed:
                    cell.setBackground(
                        changed_result_background
                        if column == 3
                        else changed_background
                    )
                elif column == 3:
                    cell.setBackground(same_result_background)
                if column == 3:
                    font = cell.font()
                    font.setBold(True)
                    cell.setFont(font)
                    cell.setForeground(
                        changed_foreground if field.is_changed else same_foreground
                    )
                self.detail.setItem(row, column, cell)
        self.detail.setSortingEnabled(True)
        self.detail.sortItems(sort_column, sort_order)
        self.detail.resizeRowsToContents()

    def set_error(self, message: str) -> None:
        self._comparison_busy = False
        self.run_button.setEnabled(True)
        self.run_button.setText(
            "전체 비교 다시 불러오기" if self._result is not None else "전체 비교 실행"
        )
        self.export_button.setEnabled(
            not self._export_busy
            and not self._comparison_busy
            and self._result is not None
            and bool(self._result.items)
        )
        self.status_label.setText(message)

    def clear_result(self, message: str) -> None:
        self._result = None
        self._comparison_busy = False
        self.run_button.setEnabled(True)
        self.run_button.setText("전체 비교 실행")
        self.export_button.setEnabled(False)
        self.detail.setRowCount(0)
        self._select_comparison(None)
        self.status_label.setText(message)

    def reset_state(self, message: str) -> None:
        self.before_combo.blockSignals(True)
        self.after_combo.blockSignals(True)
        self.before_combo.clear()
        self.after_combo.clear()
        self.before_combo.addItem("현재 상태", None)
        self.after_combo.addItem("선택하세요", "")
        self.after_combo.addItem("현재 상태", None)
        self.before_combo.blockSignals(False)
        self.after_combo.blockSignals(False)
        self._baselines = {}
        self.activity_panel.set_baselines(())
        self.clear_result(message)
