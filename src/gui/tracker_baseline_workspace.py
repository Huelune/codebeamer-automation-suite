"""트래커 작업공간의 Baseline 비교 탭을 맡는 자식 위젯.

Baseline 두 개를 골라 비교하고, 결과 표를 걸러 보고, Excel 로 내보내는 화면이다.
계층 탭과는 트래커 선택과 하위 아이템 캐시만 공유한다.

작업공간과는 두 방향으로만 이어진다.

- 작업공간 -> panel: `reset_state`, `render_roots`, `reload`, `set_baselines`, `set_error`
- panel -> 작업공간: `BaselineWorkspaceHost` 의 콜백
"""

from __future__ import annotations

from dataclasses import dataclass


try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtWidgets import QFrame
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QSplitter
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTabWidget
    from PySide6.QtWidgets import QTreeWidget
    from PySide6.QtWidgets import QTreeWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc


from collections.abc import Callable
from typing import Any

from .activity_history import ActivityOperation
from .activity_history import ActivityRecord
from .activity_history import ActivityResult
from .settings_store import GuiSettings
from .tracker_baseline_compare import BaselineComparisonKind
from .tracker_baseline_compare import BaselineComparisonResult
from .tracker_baseline_compare import BaselineComparisonSource
from .tracker_baseline_compare import TrackerBaseline
from .tracker_baseline_export import baseline_export_fields
from .tracker_baseline_export import export_baseline_comparison_xlsx
from .tracker_baseline_export_dialog import BaselineExportFieldDialog
from .tracker_baseline_panel import BASELINE_KIND_ACCENTS
from .tracker_baseline_panel import BASELINE_KIND_BADGES
from .tracker_baseline_panel import BaselineComparisonPanel
from .tracker_query_models import ProjectSummary
from .tracker_query_models import TrackerItemSummary
from .tracker_query_models import TrackerSummary
from .tracker_workspace_support import BASELINE_COMPARISON_ROLE
from .tracker_workspace_support import CHILDREN_LOADED_ROLE
from .tracker_workspace_support import HIERARCHY_FETCH_PAGE_SIZE
from .tracker_workspace_support import ITEM_SUMMARY_ROLE
from .tracker_workspace_support import SortableTableItem
from .tracker_workspace_support import blend_colors


@dataclass(frozen=True)
class BaselineWorkspaceHost:
    """Baseline 탭이 작업공간 화면에 되돌려주는 일.

    선택한 트래커와 하위 아이템 캐시는 계층 탭과 공유하므로 화면에서 읽어 온다.
    """

    submit: Callable[..., int]
    show_error: Callable[..., None]
    set_workspace_status: Callable[..., None]
    record_activity: Callable[..., None]
    load_roots: Callable[..., None]
    placeholder_item: Callable[[str], QTreeWidgetItem]
    tree_item: Callable[..., QTreeWidgetItem]
    replace_tree_children: Callable[..., None]
    refresh_baselines: Callable[..., None]
    current_tracker: Callable[[], TrackerSummary | None]
    current_project: Callable[[], ProjectSummary | None]
    child_cache: Callable[[], dict[int, tuple[TrackerItemSummary, ...]]]
    # 확인 대화상자는 화면이 갈아 끼울 수 있어 호출할 때마다 읽는다.
    compare_confirmer: Callable[[], Callable[..., bool] | None]


class BaselineWorkspacePanel(QWidget):
    """Baseline 비교 화면."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        host: BaselineWorkspaceHost,
        settings_provider: Callable[[], GuiSettings],
        service: Any,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self.settings_provider = settings_provider
        self.service = service

        self._baseline_selected_item_id: int | None = None
        self._baseline_comparison_result: BaselineComparisonResult | None = None
        self._baseline_comparison_cache_key: tuple[Any, ...] | None = None
        self._baseline_comparison_loading_key: tuple[Any, ...] | None = None
        self._baseline_export_in_progress = False

        self.setObjectName("tracker_baseline_comparison_page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        browser_panel = QFrame(splitter)
        browser_layout = QVBoxLayout(browser_panel)
        tree_toolbar = QHBoxLayout()
        self.baseline_tree_status_label = QLabel("트래커를 선택하세요.", browser_panel)
        tree_toolbar.addWidget(self.baseline_tree_status_label, 1)
        self.baseline_reload_button = QPushButton("다시 불러오기", browser_panel)
        self.baseline_reload_button.clicked.connect(self.reload)
        tree_toolbar.addWidget(self.baseline_reload_button)
        browser_layout.addLayout(tree_toolbar)

        self.baseline_browser_tabs = QTabWidget(browser_panel)
        self.baseline_browser_tabs.setObjectName("baseline_browser_tabs")
        hierarchy_tab = QWidget(self.baseline_browser_tabs)
        hierarchy_layout = QVBoxLayout(hierarchy_tab)
        hierarchy_layout.setContentsMargins(0, 0, 0, 0)
        self.baseline_item_tree = QTreeWidget(hierarchy_tab)
        self.baseline_item_tree.setColumnCount(2)
        self.baseline_item_tree.setHeaderLabels(["ID", "요약"])
        self.baseline_item_tree.setAlternatingRowColors(True)
        self.baseline_item_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.baseline_item_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.baseline_item_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.baseline_item_tree.itemExpanded.connect(self._on_baseline_tree_item_expanded)
        self.baseline_item_tree.itemSelectionChanged.connect(self._on_baseline_tree_selection_changed)
        hierarchy_layout.addWidget(self.baseline_item_tree, 1)
        self.baseline_browser_tabs.addTab(hierarchy_tab, "현재 계층")

        results_tab = QWidget(self.baseline_browser_tabs)
        results_layout = QVBoxLayout(results_tab)
        results_layout.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        self.baseline_result_filter = QComboBox(results_tab)
        self.baseline_result_filter.setObjectName("baseline_result_filter")
        self.baseline_result_filter.addItem("전체 결과", "")
        self.baseline_result_filter.addItem("신규", BaselineComparisonKind.ADDED.value)
        self.baseline_result_filter.addItem("삭제", BaselineComparisonKind.REMOVED.value)
        self.baseline_result_filter.addItem("변경", BaselineComparisonKind.CHANGED.value)
        self.baseline_result_filter.addItem("변경 없음", BaselineComparisonKind.UNCHANGED.value)
        self.baseline_result_filter.currentIndexChanged.connect(
            self._render_baseline_comparison_results
        )
        filter_row.addWidget(self.baseline_result_filter)
        self.baseline_field_filter = QComboBox(results_tab)
        self.baseline_field_filter.setObjectName("baseline_field_filter")
        self.baseline_field_filter.addItem("전체 변경 필드", "")
        self.baseline_field_filter.currentIndexChanged.connect(
            self._render_baseline_comparison_results
        )
        filter_row.addWidget(self.baseline_field_filter)
        self.baseline_result_search = QLineEdit(results_tab)
        self.baseline_result_search.setObjectName("baseline_result_search")
        self.baseline_result_search.setPlaceholderText("ID 또는 아이템명 검색")
        self.baseline_result_search.textChanged.connect(
            self._render_baseline_comparison_results
        )
        filter_row.addWidget(self.baseline_result_search, 1)
        results_layout.addLayout(filter_row)
        self.baseline_result_table = QTableWidget(0, 5, results_tab)
        self.baseline_result_table.setObjectName("baseline_result_table")
        self.baseline_result_table.setHorizontalHeaderLabels(
            ["결과", "ID", "요약", "변경 필드", "전체 필드"]
        )
        self.baseline_result_table.setAlternatingRowColors(True)
        self.baseline_result_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.baseline_result_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.baseline_result_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.baseline_result_table.verticalHeader().setVisible(False)
        self.baseline_result_table.setSortingEnabled(True)
        self.baseline_result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.baseline_result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.baseline_result_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.baseline_result_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.baseline_result_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.baseline_result_table.itemSelectionChanged.connect(
            self._on_baseline_result_selection_changed
        )
        results_layout.addWidget(self.baseline_result_table, 1)
        self.baseline_browser_tabs.addTab(results_tab, "전체 비교 결과")
        browser_layout.addWidget(self.baseline_browser_tabs, 1)

        panel = BaselineComparisonPanel(
            self._request_baseline_comparison,
            self._on_baseline_sources_changed,
            self._export_baseline_comparison,
            splitter,
        )
        panel.setObjectName("tracker_baseline_comparison_panel")
        self.baseline_comparison_panel = panel
        splitter.addWidget(browser_panel)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([420, 620])
        layout.addWidget(splitter, 1)


    def set_available(self, available: bool) -> None:
        """트래커를 고르기 전에는 다시 불러오기를 막는다."""
        self.baseline_reload_button.setEnabled(available)

    def set_baselines(self, baselines: tuple[TrackerBaseline, ...]) -> None:
        """조회한 Baseline 목록을 비교 패널에 넘긴다."""
        self.baseline_comparison_panel.set_baselines(baselines)

    def set_error(self, message: str) -> None:
        self.baseline_comparison_panel.set_error(message)

    def reset_state(self, message: str) -> None:
        self._baseline_selected_item_id = None
        self._baseline_loaded_tracker_id = None
        self._baseline_loading_tracker_id = None
        self._baseline_comparison_result = None
        self._baseline_comparison_cache_key = None
        self._baseline_comparison_loading_key = None
        self.baseline_item_tree.clear()
        self.baseline_result_table.setRowCount(0)
        self.baseline_result_filter.setCurrentIndex(0)
        self.reset_field_filter()
        self.baseline_result_search.clear()
        self.baseline_tree_status_label.setText(message)
        self.baseline_comparison_panel.reset_state(message)

    def render_roots(self, items: tuple[TrackerItemSummary, ...]) -> None:
        self.baseline_item_tree.blockSignals(True)
        self.baseline_item_tree.clear()
        for summary in items:
            self.baseline_item_tree.addTopLevelItem(self._host.tree_item(summary))
        self.baseline_item_tree.blockSignals(False)
        self.baseline_tree_status_label.setText(
            f"현재 최상위 아이템 {len(items)}개" if items else "현재 최상위 아이템이 없습니다."
        )

    def _on_baseline_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        summary = item.data(0, ITEM_SUMMARY_ROLE)
        if not isinstance(summary, TrackerItemSummary):
            return
        if bool(item.data(0, CHILDREN_LOADED_ROLE)):
            return
        cached = self._host.child_cache().get(summary.item_id)
        if cached is not None:
            self._host.replace_tree_children(item, cached)
            return
        tracker = self._host.current_tracker()
        project = self._host.current_project()
        if tracker is None:
            return
        tracker_id = tracker.tracker_id
        settings = self.settings_provider()
        item.takeChildren()
        item.addChild(self._host.placeholder_item("하위 아이템을 불러오는 중입니다."))

        def loaded(children: tuple[TrackerItemSummary, ...]) -> None:
            still_selected = self._host.current_tracker()
            if still_selected is None or still_selected.tracker_id != tracker_id:
                return
            self._host.child_cache()[summary.item_id] = children
            self._host.replace_tree_children(item, children)

        def failed(exc: Exception) -> None:
            item.takeChildren()
            item.addChild(self._host.placeholder_item("하위 조회 실패 · 다시 펼쳐 재시도"))
            item.setData(0, CHILDREN_LOADED_ROLE, False)
            self.baseline_comparison_panel.set_error(str(exc))
            self._host.show_error(exc, prefix=f"#{summary.item_id} 하위 조회 실패")

        self._host.submit(
            f"baseline_children:{summary.item_id}",
            lambda: self.service.load_all_child_items(
                settings,
                summary.item_id,
                tracker_id=tracker_id,
                tracker_name=tracker.name,
                project_id=project.project_id if project else tracker.project_id,
                project_name=project.name if project else tracker.project_name,
                page_size=HIERARCHY_FETCH_PAGE_SIZE,
            ),
            loaded,
            failed,
        )

    def _on_baseline_tree_selection_changed(self) -> None:
        selected = self.baseline_item_tree.selectedItems()
        if not selected:
            return
        summary = selected[0].data(0, ITEM_SUMMARY_ROLE)
        if not isinstance(summary, TrackerItemSummary):
            return
        self._baseline_selected_item_id = summary.item_id
        if self._baseline_comparison_result is not None:
            self.baseline_comparison_panel.select_item(summary.item_id)
        else:
            self.baseline_comparison_panel.set_error(
                f"#{summary.item_id}을(를) 선택했습니다. 전체 비교 데이터를 먼저 불러오세요."
            )

    def _on_baseline_result_selection_changed(self) -> None:
        selected = self.baseline_result_table.selectedItems()
        if not selected:
            return
        id_cell = self.baseline_result_table.item(selected[0].row(), 1)
        comparison = (
            id_cell.data(BASELINE_COMPARISON_ROLE) if id_cell is not None else None
        )
        if comparison is None:
            return
        self._baseline_selected_item_id = int(comparison.item_id)
        self.baseline_comparison_panel.select_item(comparison.item_id)

    def _render_baseline_comparison_results(self, *_args) -> None:
        result = self._baseline_comparison_result
        self.baseline_result_table.setSortingEnabled(False)
        self.baseline_result_table.setRowCount(0)
        if result is None:
            self.baseline_result_table.setSortingEnabled(True)
            return
        visible = self._filtered_baseline_comparisons(result)
        self.baseline_result_table.setRowCount(len(visible))
        palette = self.baseline_result_table.palette()
        base_color = palette.base().color()
        for row, comparison in enumerate(visible):
            changed_count = sum(field.is_changed for field in comparison.fields)
            changed_count_text = (
                "—"
                if comparison.kind
                in {BaselineComparisonKind.ADDED, BaselineComparisonKind.REMOVED}
                else str(changed_count)
            )
            values = (
                BASELINE_KIND_BADGES[comparison.kind],
                str(comparison.item_id),
                comparison.name,
                changed_count_text,
                str(len(comparison.fields)),
            )
            sort_values = (
                comparison.kind.value,
                comparison.item_id,
                comparison.name.casefold(),
                -1
                if comparison.kind
                in {BaselineComparisonKind.ADDED, BaselineComparisonKind.REMOVED}
                else changed_count,
                len(comparison.fields),
            )
            accent = BASELINE_KIND_ACCENTS[comparison.kind]
            background = QBrush(blend_colors(base_color, accent, 0.16))
            for column, value in enumerate(values):
                cell = SortableTableItem(value, sort_values[column])
                cell.setToolTip(value)
                cell.setBackground(background)
                if column == 1:
                    cell.setData(BASELINE_COMPARISON_ROLE, comparison)
                self.baseline_result_table.setItem(row, column, cell)
        self.baseline_result_table.setSortingEnabled(True)
        self.baseline_result_table.sortItems(1, Qt.SortOrder.AscendingOrder)
        self.baseline_tree_status_label.setText(
            f"전체 비교 {len(result.items)}개 · 현재 표시 {len(visible)}개"
        )

    def _filtered_baseline_comparisons(
        self,
        result: BaselineComparisonResult | None = None,
    ) -> tuple:
        source = result or self._baseline_comparison_result
        if source is None:
            return ()
        kind_filter = str(self.baseline_result_filter.currentData() or "")
        field_filter = str(self.baseline_field_filter.currentData() or "")
        needle = self.baseline_result_search.text().strip().casefold()
        visible = []
        for comparison in source.items:
            if kind_filter and comparison.kind.value != kind_filter:
                continue
            if (
                needle
                and needle not in str(comparison.item_id)
                and needle not in comparison.name.casefold()
            ):
                continue
            if field_filter and not any(
                field.field_key == field_filter and field.is_changed
                for field in comparison.fields
            ):
                continue
            visible.append(comparison)
        return tuple(visible)

    def _populate_baseline_field_filter(
        self,
        result: BaselineComparisonResult,
    ) -> None:
        selected_key = str(self.baseline_field_filter.currentData() or "")
        fields = baseline_export_fields(result)
        self.baseline_field_filter.blockSignals(True)
        self.baseline_field_filter.clear()
        self.baseline_field_filter.addItem("전체 변경 필드", "")
        for field in fields:
            self.baseline_field_filter.addItem(field.label, field.field_key)
        selected_index = self.baseline_field_filter.findData(selected_key)
        self.baseline_field_filter.setCurrentIndex(max(selected_index, 0))
        self.baseline_field_filter.blockSignals(False)

    def reset_field_filter(self) -> None:
        self.baseline_field_filter.blockSignals(True)
        self.baseline_field_filter.clear()
        self.baseline_field_filter.addItem("전체 변경 필드", "")
        self.baseline_field_filter.blockSignals(False)

    def _baseline_comparison_key(
        self,
        reference_source: BaselineComparisonSource,
        comparison_source: BaselineComparisonSource,
    ) -> tuple[int, int | None, int | None] | None:
        tracker = self._host.current_tracker()
        if tracker is None:
            return None
        return (
            tracker.tracker_id,
            reference_source.baseline_id,
            comparison_source.baseline_id,
        )

    def _on_baseline_sources_changed(self) -> None:
        self._baseline_comparison_result = None
        self._baseline_comparison_cache_key = None
        self._baseline_comparison_loading_key = None
        self.baseline_result_table.setRowCount(0)
        self.baseline_result_filter.setCurrentIndex(0)
        self.reset_field_filter()
        self.baseline_result_search.clear()
        self.baseline_comparison_panel.clear_result(
            "비교 기준이 변경되었습니다. '전체 비교 실행'을 눌러 데이터를 불러오세요."
        )
        reference, comparison = self.baseline_comparison_panel.sources()
        if reference is None or comparison is None:
            self.baseline_comparison_panel.clear_result("비교할 두 기준을 선택하세요.")
            return
        if reference == comparison:
            self.baseline_comparison_panel.clear_result(
                "서로 다른 두 비교 기준을 선택하세요."
            )
            return

    def _request_baseline_comparison(
        self,
        reference_source: BaselineComparisonSource,
        comparison_source: BaselineComparisonSource,
    ) -> None:
        confirmer = self._host.compare_confirmer()
        if confirmer is not None:
            confirmed = bool(confirmer(reference_source, comparison_source))
        else:
            reference_label, comparison_label = (
                self.baseline_comparison_panel.source_labels()
            )
            answer = QMessageBox.warning(
                self,
                "Baseline 전체 비교",
                (
                    "현재 트래커의 전체 아이템을 두 기준에서 조회합니다.\n"
                    "아이템 수에 따라 시간이 오래 걸리고 서버 요청이 여러 번 발생할 수 있습니다.\n\n"
                    f"기준: {reference_label}\n"
                    f"비교: {comparison_label}\n\n"
                    "전체 비교를 실행하시겠습니까?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            confirmed = answer == QMessageBox.StandardButton.Yes
        if not confirmed:
            return
        self._run_baseline_comparison(
            reference_source,
            comparison_source,
            force=True,
        )

    def reload(self) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            self.baseline_comparison_panel.set_error("비교할 트래커를 먼저 선택하세요.")
            return
        self.reset_state("현재 계층과 Baseline 목록을 다시 불러오는 중입니다.")
        self._host.load_roots(force=True)
        self._host.refresh_baselines(force=True)

    def _run_baseline_comparison(
        self,
        reference_source: BaselineComparisonSource,
        comparison_source: BaselineComparisonSource,
        *,
        force: bool = False,
    ) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            self.baseline_comparison_panel.set_error("비교할 트래커를 먼저 선택하세요.")
            return
        key = self._baseline_comparison_key(reference_source, comparison_source)
        if key is None:
            return
        if not force and self._baseline_comparison_cache_key == key:
            result = self._baseline_comparison_result
            if result is not None:
                self._populate_baseline_field_filter(result)
                self.baseline_comparison_panel.set_result(
                    result,
                    selected_item_id=self._baseline_selected_item_id,
                )
                self._render_baseline_comparison_results()
                return
        if not force and self._baseline_comparison_loading_key == key:
            return
        settings = self.settings_provider()
        self._baseline_comparison_loading_key = key
        self.baseline_comparison_panel.set_loading(
            "트래커 전체 아이템을 두 기준에서 조회하는 중입니다."
        )

        def loaded(result: BaselineComparisonResult) -> None:
            current_reference, current_comparison = self.baseline_comparison_panel.sources()
            current_key = (
                self._baseline_comparison_key(current_reference, current_comparison)
                if current_reference is not None and current_comparison is not None
                else None
            )
            if current_key != key:
                return
            self._baseline_comparison_loading_key = None
            self._baseline_comparison_result = result
            self._baseline_comparison_cache_key = key
            self._populate_baseline_field_filter(result)
            self.baseline_comparison_panel.set_result(
                result,
                selected_item_id=self._baseline_selected_item_id,
            )
            self._render_baseline_comparison_results()

        def failed(exc: Exception) -> None:
            current_reference, current_comparison = self.baseline_comparison_panel.sources()
            current_key = (
                self._baseline_comparison_key(current_reference, current_comparison)
                if current_reference is not None and current_comparison is not None
                else None
            )
            if self._baseline_comparison_loading_key != key or current_key != key:
                return
            self._baseline_comparison_loading_key = None
            self.baseline_comparison_panel.set_error(str(exc))
            self._host.show_error(exc, prefix="Baseline 전체 비교 실패")

        self._host.submit(
            "baseline_compare",
            lambda: self.service.compare_tracker_at_sources(
                settings,
                tracker.tracker_id,
                reference_source=reference_source,
                comparison_source=comparison_source,
            ),
            loaded,
            failed,
        )

    def _export_baseline_comparison(self) -> None:
        if self._baseline_export_in_progress:
            return
        result = self._baseline_comparison_result
        tracker = self._host.current_tracker()
        export_key = self._baseline_comparison_cache_key
        if result is None or tracker is None or export_key is None:
            self.baseline_comparison_panel.set_error(
                "전체 비교 데이터를 불러온 뒤 Excel로 내보낼 수 있습니다."
            )
            return
        filtered_result = BaselineComparisonResult(
            result.before_source,
            result.after_source,
            self._filtered_baseline_comparisons(result),
        )
        if not filtered_result.items:
            self.baseline_comparison_panel.set_error(
                "현재 필터에 표시된 아이템이 없어 내보낼 수 없습니다."
            )
            return
        fields = baseline_export_fields(filtered_result)
        if not fields:
            self.baseline_comparison_panel.set_error("내보낼 비교 필드가 없습니다.")
            return
        field_dialog = BaselineExportFieldDialog(fields, self)
        if field_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected_keys = field_dialog.selected_field_keys()
        default_name = f"baseline_comparison_{tracker.tracker_id}.xlsx"
        output_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Baseline 비교 Excel 저장",
            default_name,
            "Excel 통합 문서 (*.xlsx)",
        )
        if not output_path:
            return
        reference_label, comparison_label = self.baseline_comparison_panel.source_labels()
        project = self._host.current_project()

        def export():
            return export_baseline_comparison_xlsx(
                filtered_result,
                output_path,
                tracker_name=f"{tracker.name} (ID {tracker.tracker_id})",
                reference_label=reference_label,
                comparison_label=comparison_label,
                selected_field_keys=selected_keys,
            )

        def failed(exc: Exception) -> None:
            self._baseline_export_in_progress = False
            self.baseline_comparison_panel.set_export_busy(False)
            if self._baseline_comparison_cache_key == export_key:
                self.baseline_comparison_panel.set_error(str(exc))
            self._host.show_error(exc, prefix="Baseline Excel 내보내기 실패")
            self._host.record_activity(
                ActivityRecord.create(
                    ActivityOperation.BASELINE_EXPORT,
                    ActivityResult.FAILED,
                    source="tracker_workspace",
                    summary="Baseline 비교 Excel 내보내기 실패",
                    project_id=project.project_id if project else tracker.project_id,
                    project_name=project.name if project else tracker.project_name,
                    tracker_id=tracker.tracker_id,
                    tracker_name=tracker.name,
                    details={
                        "selectedFieldCount": len(selected_keys),
                        "itemCount": len(filtered_result.items),
                    },
                )
            )

        def completed(summary) -> None:
            self._baseline_export_in_progress = False
            self.baseline_comparison_panel.set_export_busy(False)
            self._host.record_activity(
                ActivityRecord.create(
                    ActivityOperation.BASELINE_EXPORT,
                    ActivityResult.SUCCESS,
                    source="tracker_workspace",
                    summary=(
                        f"Baseline 비교 {summary.item_count}개 아이템을 Excel로 내보냈습니다."
                    ),
                    project_id=project.project_id if project else tracker.project_id,
                    project_name=project.name if project else tracker.project_name,
                    tracker_id=tracker.tracker_id,
                    tracker_name=tracker.name,
                    details={
                        "selectedFieldCount": summary.selected_field_count,
                        "itemCount": summary.item_count,
                        "dataRowCount": summary.data_row_count,
                        "longValueCount": summary.long_value_count,
                        "longValuePartCount": summary.long_value_part_count,
                    },
                )
            )
            if self._baseline_comparison_cache_key == export_key:
                long_value_status = (
                    f" · 긴 값 {summary.long_value_count}개 별도 시트 분할"
                    if summary.long_value_count
                    else ""
                )
                self.baseline_comparison_panel.status_label.setText(
                    f"Excel 내보내기 완료 · 아이템 {summary.item_count}개 · "
                    f"데이터 행 {summary.data_row_count}개{long_value_status}"
                )
            self._host.set_workspace_status("Baseline 비교 Excel 파일을 저장했습니다.")

        self._baseline_export_in_progress = True
        self.baseline_comparison_panel.set_export_busy(
            True,
            "Baseline 비교 Excel 파일을 생성하는 중입니다.",
        )
        self._host.submit("baseline_export", export, completed, failed)
