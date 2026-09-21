"""트래커 작업공간의 계층 탭을 맡는 자식 위젯.

최상위 아이템 조회, 하위 펼치기, Baseline 스냅샷으로 보기, 계층 Excel 내보내기를
들고 있다. 트리는 상세 영역과 검색 결과 표와 함께 같은 아이템을 비추므로
갱신·삭제를 화면이 한 번에 알린다.

작업공간과는 두 방향으로만 이어진다.

- 작업공간 -> panel: `load_roots`, `reset_source`, `set_baselines`,
  `selected_baseline_id`, `show_created_item`, `tree_item`, `placeholder_item`,
  `replace_tree_children`, `refresh_item`, `remove_item`
- panel -> 작업공간: `HierarchyPanelHost` 의 콜백
"""

from __future__ import annotations

from dataclasses import dataclass


try:
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QTreeWidget
    from PySide6.QtWidgets import QTreeWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc


from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .activity_history import ActivityOperation
from .activity_history import ActivityRecord
from .activity_history import ActivityResult
from .settings_store import GuiSettings
from .tracker_baseline_compare import TrackerBaseline
from .tracker_hierarchy import TrackerHierarchySnapshot
from .tracker_hierarchy_export import TrackerHierarchyExportError
from .tracker_hierarchy_export import build_tracker_hierarchy_export_snapshot
from .tracker_hierarchy_export import export_tracker_hierarchy_xlsx
from .tracker_hierarchy_export import hierarchy_export_fields_from_schema
from .tracker_hierarchy_export_dialog import TrackerHierarchyExportFieldDialog
from .tracker_query_models import ProjectSummary
from .tracker_query_models import TrackerItemDetail
from .tracker_query_models import TrackerItemSummary
from .tracker_query_models import TrackerSummary
from .tracker_workspace_support import CHILDREN_LOADED_ROLE
from .tracker_workspace_support import HIERARCHY_FETCH_PAGE_SIZE
from .tracker_workspace_support import ITEM_SUMMARY_ROLE
from .tracker_workspace_support import PLACEHOLDER_ROLE


@dataclass(frozen=True)
class HierarchyPanelHost:
    """계층 탭이 작업공간 화면에 되돌려주는 일."""

    submit: Callable[..., int]
    show_error: Callable[..., None]
    set_workspace_status: Callable[..., None]
    set_available: Callable[[bool], None]
    record_activity: Callable[..., None]
    next_token: Callable[[str], int]
    invalidate_tracker_cache: Callable[[int], None]
    current_tracker: Callable[[], TrackerSummary | None]
    current_project: Callable[[], ProjectSummary | None]
    detail_panel: Callable[[], Any]
    search_panel: Callable[[], Any]
    baseline_workspace: Callable[[], Any]
    browser_tabs: Callable[[], Any]


class TrackerHierarchyPanel(QWidget):
    """트래커 계층 탐색과 내보내기 화면."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        host: HierarchyPanelHost,
        settings_provider: Callable[[], GuiSettings],
        service: Any,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self.settings_provider = settings_provider
        self.service = service

        self._root_cache: dict[int, tuple[TrackerItemSummary, ...]] = {}
        self._child_cache: dict[int, tuple[TrackerItemSummary, ...]] = {}
        self._baselines: tuple[TrackerBaseline, ...] = ()
        self._baseline_hierarchy_cache: dict[Any, Any] = {}
        self._baseline_hierarchy_loading_key: Any = None
        self._hierarchy_export_in_progress = False

        self.setObjectName("tracker_hierarchy_tab")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        source_toolbar = QHBoxLayout()
        source_toolbar.addWidget(QLabel("조회 기준", self))
        self.hierarchy_source_combo = QComboBox(self)
        self.hierarchy_source_combo.setObjectName("tracker_hierarchy_source_combo")
        self.hierarchy_source_combo.addItem("현재 상태", None)
        self.hierarchy_source_combo.currentIndexChanged.connect(
            self._on_hierarchy_source_changed
        )
        source_toolbar.addWidget(self.hierarchy_source_combo, 1)
        self.reload_roots_button = QPushButton("현재 계층 다시 불러오기", self)
        self.reload_roots_button.clicked.connect(self._reload_selected_hierarchy)
        source_toolbar.addWidget(self.reload_roots_button)
        layout.addLayout(source_toolbar)

        action_toolbar = QHBoxLayout()
        self.tree_status_label = QLabel("트래커를 선택하세요.")
        self.tree_status_label.setObjectName("tracker_panel_status")
        action_toolbar.addWidget(self.tree_status_label, 1)
        self.hierarchy_export_button = QPushButton("계층 Excel 내보내기", self)
        self.hierarchy_export_button.setObjectName("tracker_hierarchy_export_button")
        self.hierarchy_export_button.clicked.connect(self._start_hierarchy_export)
        action_toolbar.addWidget(self.hierarchy_export_button)
        layout.addLayout(action_toolbar)

        self.item_tree = QTreeWidget(self)
        self.item_tree.setObjectName("tracker_item_tree")
        self.item_tree.setColumnCount(2)
        self.item_tree.setHeaderLabels(["ID", "요약"])
        self.item_tree.setAlternatingRowColors(True)
        self.item_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.item_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.item_tree.setUniformRowHeights(True)
        self.item_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.item_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.item_tree.itemExpanded.connect(self._on_tree_item_expanded)
        self.item_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        layout.addWidget(self.item_tree, 1)

    def set_export_available(
        self,
        available: bool,
        *,
        tracker_id: int | None,
        historical: bool,
    ) -> None:
        """Baseline 스냅샷은 이미 받아 둔 것만 내보낼 수 있다."""
        ready = available and not self._hierarchy_export_in_progress
        if ready and historical:
            ready = (tracker_id, self.selected_baseline_id()) in self._baseline_hierarchy_cache
        self.hierarchy_export_button.setEnabled(ready)

    def clear_baseline_cache(self) -> None:
        self._baseline_hierarchy_cache.clear()
        self._baseline_hierarchy_loading_key = None

    def child_cache(self) -> dict[int, tuple[TrackerItemSummary, ...]]:
        """하위 아이템 캐시. Baseline 탭도 같은 트래커를 보므로 함께 쓴다."""
        return self._child_cache

    def root_cache(self) -> dict[int, tuple[TrackerItemSummary, ...]]:
        return self._root_cache

    def clear_caches(self) -> None:
        self._root_cache.clear()
        self._child_cache.clear()
        self._baseline_hierarchy_cache.clear()
        self._baseline_hierarchy_loading_key = None

    def clear_tree(self, message: str) -> None:
        self.item_tree.clear()
        self._baseline_hierarchy_loading_key = None
        self.tree_status_label.setText(message)

    def set_reload_enabled(self, enabled: bool) -> None:
        self.reload_roots_button.setEnabled(enabled)

    def refresh_item(self, detail: Any) -> None:
        """수정 결과를 계층 트리에도 반영한다."""
        summary = detail.summary

        def update_tree_item(item: QTreeWidgetItem | None) -> None:
            if item is None:
                return
            existing = item.data(0, ITEM_SUMMARY_ROLE)
            if isinstance(existing, TrackerItemSummary) and existing.item_id == detail.item_id:
                updated = replace(
                    existing,
                    name=summary.name,
                    status=summary.status,
                    assignees=summary.assignees,
                    modified_at=summary.modified_at,
                    version=summary.version,
                )
                item.setData(0, ITEM_SUMMARY_ROLE, updated)
                item.setText(1, updated.name)
            for child_index in range(item.childCount()):
                update_tree_item(item.child(child_index))

        for top_index in range(self.item_tree.topLevelItemCount()):
            update_tree_item(self.item_tree.topLevelItem(top_index))

    def remove_item(self, item_id: int) -> None:
        def remove_from(parent: QTreeWidgetItem | None) -> bool:
            count = self.item_tree.topLevelItemCount() if parent is None else parent.childCount()
            for index in range(count - 1, -1, -1):
                item = (
                    self.item_tree.topLevelItem(index)
                    if parent is None
                    else parent.child(index)
                )
                if item is None:
                    continue
                summary = item.data(0, ITEM_SUMMARY_ROLE)
                if isinstance(summary, TrackerItemSummary) and summary.item_id == int(item_id):
                    if parent is None:
                        self.item_tree.takeTopLevelItem(index)
                    else:
                        parent.takeChild(index)
                    return True
                if remove_from(item):
                    return True
            return False

        remove_from(None)

    def reset_source(self) -> None:
        self.hierarchy_source_combo.blockSignals(True)
        self.hierarchy_source_combo.clear()
        self.hierarchy_source_combo.addItem("현재 상태", None)
        self.hierarchy_source_combo.setCurrentIndex(0)
        self.hierarchy_source_combo.blockSignals(False)
        self.reload_roots_button.setText("현재 계층 다시 불러오기")

    def set_baselines(
        self,
        baselines: tuple[TrackerBaseline, ...],
    ) -> None:
        selected = self.selected_baseline_id()
        self.hierarchy_source_combo.blockSignals(True)
        self.hierarchy_source_combo.clear()
        self.hierarchy_source_combo.addItem("현재 상태", None)
        for baseline in baselines:
            label = baseline.name
            if baseline.created_at:
                label = f"{label} ({baseline.created_at})"
            self.hierarchy_source_combo.addItem(label, baseline.baseline_id)
        selected_index = (
            self.hierarchy_source_combo.findData(selected)
            if selected is not None
            else 0
        )
        self.hierarchy_source_combo.setCurrentIndex(max(selected_index, 0))
        self.hierarchy_source_combo.blockSignals(False)
        if selected is not None and selected_index < 0:
            self._on_hierarchy_source_changed()

    def load_roots(self, *, force: bool = False) -> None:
        tracker = self._host.current_tracker()
        project = self._host.current_project()
        if tracker is None:
            self._host.set_workspace_status("트래커를 먼저 선택하세요.", tone="warning")
            return
        cache_key = tracker.tracker_id
        if cache_key in self._root_cache and not force:
            self._render_roots(self._root_cache[cache_key])
            return
        if force:
            self._root_cache.pop(tracker.tracker_id, None)
            self._child_cache.clear()

        settings = self.settings_provider()
        tracker_id = tracker.tracker_id
        self.tree_status_label.setText("최상위 아이템을 불러오는 중입니다.")
        self.reload_roots_button.setEnabled(False)

        def loaded(items: tuple[TrackerItemSummary, ...]) -> None:
            still_selected = self._host.current_tracker()
            if still_selected is None or still_selected.tracker_id != tracker_id:
                return
            self._root_cache[cache_key] = items
            self.reload_roots_button.setEnabled(True)
            self._render_roots(items)
            if self.selected_baseline_id() is None:
                self._host.set_workspace_status(
                    f"'{tracker.name}' 트래커의 계층을 조회할 수 있습니다."
                )

        def failed(exc: Exception) -> None:
            self.reload_roots_button.setEnabled(True)
            if self.selected_baseline_id() is None:
                self.item_tree.clear()
                self.tree_status_label.setText("최상위 아이템을 불러오지 못했습니다.")
            self._host.show_error(exc, prefix="계층 조회 실패")

        self._host.submit(
            "roots",
            lambda: self.service.load_all_top_level_items(
                settings,
                tracker_id,
                tracker_name=tracker.name,
                project_id=project.project_id if project else tracker.project_id,
                project_name=project.name if project else tracker.project_name,
                page_size=HIERARCHY_FETCH_PAGE_SIZE,
            ),
            loaded,
            failed,
        )

    def _on_hierarchy_source_changed(self, *_args) -> None:
        self._host.next_token("detail")
        self._host.detail_panel().reset_detail()
        baseline_id = self.selected_baseline_id()
        historical = baseline_id is not None
        self._host.detail_panel().set_historical_read_only(historical)
        self._host.set_available(True)
        if baseline_id is None:
            self.reload_roots_button.setText("현재 계층 다시 불러오기")
            self.load_roots()
            return
        self.reload_roots_button.setText("Baseline 계층 조회")
        tracker = self._host.current_tracker()
        if tracker is None:
            return
        cached = self._baseline_hierarchy_cache.get((tracker.tracker_id, baseline_id))
        if cached is not None:
            self._render_baseline_hierarchy(cached)
            self.reload_roots_button.setText("Baseline 계층 다시 불러오기")
            return
        self.item_tree.clear()
        self.tree_status_label.setText(
            "선택한 Baseline의 전체 계층을 보려면 'Baseline 계층 조회'를 누르세요."
        )

    def _reload_selected_hierarchy(self) -> None:
        baseline_id = self.selected_baseline_id()
        if baseline_id is None:
            self.load_roots(force=True)
            return
        self._load_baseline_hierarchy(baseline_id, force=True)

    def _load_baseline_hierarchy(
        self,
        baseline_id: int,
        *,
        force: bool = False,
    ) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            self._host.set_workspace_status("트래커를 먼저 선택하세요.", tone="warning")
            return
        key = (tracker.tracker_id, int(baseline_id))
        cached = self._baseline_hierarchy_cache.get(key)
        if cached is not None and not force:
            self._render_baseline_hierarchy(cached)
            return
        if self._baseline_hierarchy_loading_key == key:
            return
        settings = self.settings_provider()
        self._baseline_hierarchy_loading_key = key
        self.reload_roots_button.setEnabled(False)
        self.item_tree.clear()
        self.tree_status_label.setText("Baseline 전체 아이템과 계층을 불러오는 중입니다.")

        def loaded(snapshot: TrackerHierarchySnapshot) -> None:
            self._baseline_hierarchy_loading_key = None
            current = self._host.current_tracker()
            if (
                current is None
                or current.tracker_id != key[0]
                or self.selected_baseline_id() != key[1]
            ):
                return
            self._baseline_hierarchy_cache[key] = snapshot
            self.reload_roots_button.setEnabled(True)
            self.reload_roots_button.setText("Baseline 계층 다시 불러오기")
            self._host.set_available(True)
            self._render_baseline_hierarchy(snapshot)
            self._host.set_workspace_status(
                f"Baseline #{key[1]}의 계층 {len(snapshot.nodes):,}개 아이템을 불러왔습니다."
            )

        def failed(exc: Exception) -> None:
            if self._baseline_hierarchy_loading_key == key:
                self._baseline_hierarchy_loading_key = None
            current = self._host.current_tracker()
            if (
                current is None
                or current.tracker_id != key[0]
                or self.selected_baseline_id() != key[1]
            ):
                return
            self.reload_roots_button.setEnabled(True)
            self.item_tree.clear()
            self.tree_status_label.setText("Baseline 계층을 불러오지 못했습니다.")
            self._host.show_error(exc, prefix="Baseline 계층 조회 실패")

        self._host.submit(
            "baseline_hierarchy",
            lambda: self.service.load_baseline_hierarchy_snapshot(
                settings,
                key[0],
                key[1],
                page_size=HIERARCHY_FETCH_PAGE_SIZE,
            ),
            loaded,
            failed,
        )

    def _render_baseline_hierarchy(
        self,
        snapshot: TrackerHierarchySnapshot,
    ) -> None:
        self.item_tree.blockSignals(True)
        self.item_tree.clear()
        tree_items: dict[int, QTreeWidgetItem] = {}
        root_count = 0
        for node in snapshot.nodes:
            tree_item = self.tree_item(node.item)
            tree_item.takeChildren()
            tree_item.setData(0, CHILDREN_LOADED_ROLE, True)
            tree_items[node.item.item_id] = tree_item
            if node.parent_id is None:
                self.item_tree.addTopLevelItem(tree_item)
                root_count += 1
            else:
                tree_items[node.parent_id].addChild(tree_item)
        self.item_tree.blockSignals(False)
        self.tree_status_label.setText(
            f"Baseline 계층 · 최상위 {root_count}개 · 전체 {len(snapshot.nodes):,}개"
            if snapshot.nodes
            else "선택한 Baseline에 아이템이 없습니다."
        )

    def _render_roots(self, items: tuple[TrackerItemSummary, ...]) -> None:
        if self.selected_baseline_id() is None:
            self.item_tree.blockSignals(True)
            self.item_tree.clear()
            for summary in items:
                self.item_tree.addTopLevelItem(self.tree_item(summary))
            self.item_tree.blockSignals(False)
            if items:
                self.tree_status_label.setText(f"최상위 아이템 {len(items)}개 · 전체 표시")
            else:
                self.tree_status_label.setText("최상위 아이템이 없습니다.")
        self._host.baseline_workspace().render_roots(items)

    def _start_hierarchy_export(self) -> None:
        if self._hierarchy_export_in_progress:
            return
        tracker = self._host.current_tracker()
        if tracker is None:
            self._host.set_workspace_status("트래커를 먼저 선택하세요.", tone="warning")
            return
        baseline_id = self.selected_baseline_id()
        baseline_snapshot = None
        baseline_name = ""
        if baseline_id is not None:
            baseline_snapshot = self._baseline_hierarchy_cache.get(
                (tracker.tracker_id, baseline_id)
            )
            if baseline_snapshot is None:
                self._host.set_workspace_status(
                    "Baseline 계층을 먼저 조회한 뒤 Excel로 내보내세요.",
                    tone="warning",
                )
                return
            baseline_name = self.hierarchy_source_combo.currentText().strip()
        tracker_id = tracker.tracker_id
        settings = self.settings_provider()
        self.hierarchy_export_button.setEnabled(False)
        self.tree_status_label.setText("내보낼 필드 정보를 확인하는 중입니다.")

        def loaded(schema: dict[str, Any]) -> None:
            current = self._host.current_tracker()
            if (
                current is None
                or current.tracker_id != tracker_id
                or self.selected_baseline_id() != baseline_id
            ):
                return
            self.hierarchy_export_button.setEnabled(True)
            fields = hierarchy_export_fields_from_schema(schema)
            dialog = TrackerHierarchyExportFieldDialog(fields, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.tree_status_label.setText("계층 Excel 내보내기를 취소했습니다.")
                return
            default_name = (
                f"tracker_hierarchy_{tracker_id}_baseline_{baseline_id}.xlsx"
                if baseline_id is not None
                else f"tracker_hierarchy_{tracker_id}.xlsx"
            )
            output_path, _selected_filter = QFileDialog.getSaveFileName(
                self,
                "트래커 계층 Excel 저장",
                default_name,
                "Excel 통합 문서 (*.xlsx)",
            )
            if not output_path:
                self.tree_status_label.setText("계층 Excel 내보내기를 취소했습니다.")
                return
            self._run_hierarchy_export(
                tracker,
                selected_field_keys=dialog.selected_field_keys(),
                output_path=output_path,
                tracker_schema=schema,
                baseline_id=baseline_id,
                baseline_name=baseline_name,
                baseline_snapshot=baseline_snapshot,
            )

        def failed(exc: Exception) -> None:
            current = self._host.current_tracker()
            if current is None or current.tracker_id != tracker_id:
                return
            self.hierarchy_export_button.setEnabled(True)
            self.tree_status_label.setText("내보낼 필드 정보를 불러오지 못했습니다.")
            self._host.show_error(exc, prefix="계층 내보내기 필드 조회 실패")

        self._host.submit(
            "hierarchy_export_fields",
            lambda: self.service.load_tracker_schema(settings, tracker_id),
            loaded,
            failed,
        )

    def _run_hierarchy_export(
        self,
        tracker: TrackerSummary,
        *,
        selected_field_keys: tuple[str, ...],
        output_path: str,
        tracker_schema: dict[str, Any] | None = None,
        baseline_id: int | None = None,
        baseline_name: str = "",
        baseline_snapshot: TrackerHierarchySnapshot | None = None,
    ) -> None:
        if self._hierarchy_export_in_progress:
            return
        tracker_id = tracker.tracker_id
        project = self._host.current_project()
        project_id = project.project_id if project else tracker.project_id
        project_name = project.name if project else tracker.project_name
        settings = self.settings_provider()

        def export():
            if baseline_id is not None:
                if baseline_snapshot is None or tracker_schema is None:
                    raise TrackerHierarchyExportError(
                        "Baseline 계층 조회 결과 또는 필드 정보가 없습니다."
                    )
                snapshot = build_tracker_hierarchy_export_snapshot(
                    baseline_snapshot,
                    tracker_schema,
                )
            else:
                snapshot = self.service.load_tracker_hierarchy_export_snapshot(
                    settings,
                    tracker_id,
                    tracker_name=tracker.name,
                    project_id=project_id,
                    project_name=project_name,
                    page_size=HIERARCHY_FETCH_PAGE_SIZE,
                )
            return export_tracker_hierarchy_xlsx(
                snapshot,
                output_path,
                tracker_name=f"{tracker.name} (ID {tracker_id})",
                project_name=project_name,
                selected_field_keys=selected_field_keys,
                baseline_id=baseline_id,
                baseline_name=baseline_name,
            )

        def failed(exc: Exception) -> None:
            self._hierarchy_export_in_progress = False
            self._host.set_available(True)
            current = self._host.current_tracker()
            if current is not None and current.tracker_id == tracker_id:
                self.tree_status_label.setText("트래커 계층 Excel 내보내기에 실패했습니다.")
                self._host.show_error(exc, prefix="트래커 계층 Excel 내보내기 실패")
            self._host.record_activity(
                ActivityRecord.create(
                    ActivityOperation.TRACKER_HIERARCHY_EXPORT,
                    ActivityResult.FAILED,
                    source="tracker_workspace",
                    summary="트래커 계층 Excel 내보내기 실패",
                    project_id=project_id,
                    project_name=project_name,
                    tracker_id=tracker_id,
                    tracker_name=tracker.name,
                    details={
                        "selectedFieldCount": len(selected_field_keys),
                        "baselineId": baseline_id,
                    },
                )
            )

        def completed(summary) -> None:
            self._hierarchy_export_in_progress = False
            self._host.set_available(True)
            self._host.record_activity(
                ActivityRecord.create(
                    ActivityOperation.TRACKER_HIERARCHY_EXPORT,
                    ActivityResult.SUCCESS,
                    source="tracker_workspace",
                    summary=(
                        f"트래커 계층 {summary.item_count:,}개 아이템을 Excel로 내보냈습니다."
                    ),
                    project_id=project_id,
                    project_name=project_name,
                    tracker_id=tracker_id,
                    tracker_name=tracker.name,
                    details={
                        "selectedFieldCount": summary.selected_field_count,
                        "itemCount": summary.item_count,
                        "dataRowCount": summary.data_row_count,
                        "longValueCount": summary.long_value_count,
                        "longValuePartCount": summary.long_value_part_count,
                        "baselineId": baseline_id,
                    },
                )
            )
            still_selected = self._host.current_tracker()
            if still_selected is not None and still_selected.tracker_id == tracker_id:
                long_value_status = (
                    f" · 긴 값 {summary.long_value_count}개 별도 시트 분할"
                    if summary.long_value_count
                    else ""
                )
                self.tree_status_label.setText(
                    f"Excel 내보내기 완료 · 아이템 {summary.item_count:,}개 · "
                    f"데이터 행 {summary.data_row_count:,}개{long_value_status}"
                )
                source_label = (
                    "Baseline 계층"
                    if baseline_id is not None
                    else "트래커 전체 계층"
                )
                self._host.set_workspace_status(f"{source_label} Excel 파일을 저장했습니다.")

        self._hierarchy_export_in_progress = True
        self._host.set_available(True)
        self.tree_status_label.setText(
            "Baseline 계층 Excel 파일을 생성하는 중입니다."
            if baseline_id is not None
            else "트래커 전체 계층 Excel 파일을 생성하는 중입니다."
        )
        self._host.submit("hierarchy_export", export, completed, failed)

    def tree_item(self, summary: TrackerItemSummary) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [
                str(summary.item_id),
                summary.name,
            ]
        )
        item.setData(0, ITEM_SUMMARY_ROLE, summary)
        children_known = summary.child_count is not None or any(
            key in summary.raw_reference for key in ("hasChildren", "leaf", "children")
        )
        children_may_exist = summary.has_children or not children_known
        item.setData(0, CHILDREN_LOADED_ROLE, not children_may_exist)
        if children_may_exist:
            item.addChild(self.placeholder_item("펼치면 직접 하위 아이템을 불러옵니다."))
        return item

    @staticmethod
    def placeholder_item(text: str) -> QTreeWidgetItem:
        placeholder = QTreeWidgetItem(["", text])
        placeholder.setData(0, PLACEHOLDER_ROLE, True)
        placeholder.setDisabled(True)
        return placeholder

    def _on_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        if self.selected_baseline_id() is not None:
            return
        summary = item.data(0, ITEM_SUMMARY_ROLE)
        if not isinstance(summary, TrackerItemSummary):
            return
        if bool(item.data(0, CHILDREN_LOADED_ROLE)):
            return
        cached = self._child_cache.get(summary.item_id)
        if cached is not None:
            self.replace_tree_children(item, cached)
            return

        tracker = self._host.current_tracker()
        project = self._host.current_project()
        if tracker is None:
            return
        tracker_id = tracker.tracker_id
        settings = self.settings_provider()
        item.takeChildren()
        item.addChild(self.placeholder_item("하위 아이템을 불러오는 중입니다."))

        def loaded(children: tuple[TrackerItemSummary, ...]) -> None:
            still_selected = self._host.current_tracker()
            if still_selected is None or still_selected.tracker_id != tracker_id:
                return
            self._child_cache[summary.item_id] = children
            self.replace_tree_children(item, children)
            self._host.set_workspace_status(
                f"#{summary.item_id}의 직접 하위 아이템 {len(children)}개를 모두 불러왔습니다."
            )

        def failed(exc: Exception) -> None:
            item.takeChildren()
            item.addChild(self.placeholder_item("하위 조회 실패 · 접었다가 다시 펼쳐 재시도"))
            item.setData(0, CHILDREN_LOADED_ROLE, False)
            self._host.show_error(exc, prefix=f"#{summary.item_id} 하위 조회 실패")

        self._host.submit(
            f"children:{summary.item_id}",
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

    def replace_tree_children(
        self,
        parent_item: QTreeWidgetItem,
        children: tuple[TrackerItemSummary, ...] | list[TrackerItemSummary],
    ) -> None:
        parent_item.takeChildren()
        for summary in children:
            parent_item.addChild(self.tree_item(summary))
        parent_item.setData(0, CHILDREN_LOADED_ROLE, True)

    def _on_tree_selection_changed(self) -> None:
        selected = self.item_tree.selectedItems()
        if not selected:
            return
        summary = selected[0].data(0, ITEM_SUMMARY_ROLE)
        if isinstance(summary, TrackerItemSummary):
            self._host.detail_panel().load_detail(
                summary.item_id,
                baseline_id=self.selected_baseline_id(),
            )

    def _find_tree_item(self, item_id: int) -> QTreeWidgetItem | None:
        def find_from(item: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
            if item is None:
                return None
            summary = item.data(0, ITEM_SUMMARY_ROLE)
            if isinstance(summary, TrackerItemSummary) and summary.item_id == int(item_id):
                return item
            for child_index in range(item.childCount()):
                found = find_from(item.child(child_index))
                if found is not None:
                    return found
            return None

        for top_index in range(self.item_tree.topLevelItemCount()):
            found = find_from(self.item_tree.topLevelItem(top_index))
            if found is not None:
                return found
        return None

    def show_created_item(
        self,
        detail: TrackerItemDetail,
        *,
        parent_item_id: int | None,
        parent_detail: TrackerItemDetail | None,
    ) -> None:
        tracker_id = detail.summary.tracker_id
        if tracker_id is not None:
            self._host.invalidate_tracker_cache(tracker_id)

        self.item_tree.blockSignals(True)
        try:
            created_item = self.tree_item(detail.summary)
            if parent_item_id is None:
                self.item_tree.insertTopLevelItem(0, created_item)
            else:
                parent_item = self._find_tree_item(parent_item_id)
                if parent_item is None:
                    parent_summary = (
                        parent_detail.summary
                        if parent_detail is not None
                        else TrackerItemSummary(
                            item_id=int(parent_item_id),
                            name=(
                                detail.parent.name
                                if detail.parent is not None
                                else str(parent_item_id)
                            ),
                            tracker_id=detail.summary.tracker_id,
                            tracker_name=detail.summary.tracker_name,
                            project_id=detail.summary.project_id,
                            project_name=detail.summary.project_name,
                            has_children=True,
                        )
                    )
                    parent_item = self.tree_item(
                        replace(parent_summary, has_children=True)
                    )
                    parent_item.takeChildren()
                    parent_item.setData(0, CHILDREN_LOADED_ROLE, False)
                    self.item_tree.clear()
                    self.item_tree.addTopLevelItem(parent_item)
                parent_summary = parent_item.data(0, ITEM_SUMMARY_ROLE)
                if isinstance(parent_summary, TrackerItemSummary):
                    current_count = parent_summary.child_count or 0
                    parent_item.setData(
                        0,
                        ITEM_SUMMARY_ROLE,
                        replace(
                            parent_summary,
                            has_children=True,
                            child_count=max(current_count + 1, 1),
                        ),
                    )
                placeholder_index = next(
                    (
                        index
                        for index in range(parent_item.childCount())
                        if bool(parent_item.child(index).data(0, PLACEHOLDER_ROLE))
                    ),
                    -1,
                )
                if placeholder_index >= 0:
                    parent_item.insertChild(placeholder_index, created_item)
                else:
                    parent_item.addChild(created_item)
                parent_item.setExpanded(True)
            self.item_tree.clearSelection()
            self.item_tree.setCurrentItem(created_item)
            created_item.setSelected(True)
            self.item_tree.scrollToItem(created_item)
        finally:
            self.item_tree.blockSignals(False)

        self._host.browser_tabs().setCurrentIndex(0)
        self._host.detail_panel().show_detail(detail)
        position_text = (
            "최상위"
            if parent_item_id is None
            else f"#{parent_item_id}의 하위"
        )
        self.tree_status_label.setText(
            f"새 아이템 #{detail.item_id} · {position_text} · 전체 목록은 다시 불러오기로 갱신"
        )
        self._host.set_workspace_status(
            f"#{detail.item_id} '{detail.summary.name}' 아이템을 생성했습니다."
        )

    def selected_baseline_id(self) -> int | None:
        value = self.hierarchy_source_combo.currentData()
        return None if value is None else int(value)
