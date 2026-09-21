"""트래커 작업공간의 검색 탭을 맡는 자식 위젯.

트래커 범위 검색, 결과 표 선택, 선택한 아이템의 일괄 수정을 들고 있다.

작업공간과는 두 방향으로만 이어진다.

- 작업공간 -> panel: `update_scope`, `load_schema`, `clear_selection`,
  `reset_condition_search`, `selected_count`, `refresh_item`, `remove_item`,
  `open_bulk_retry`
- panel -> 작업공간: `SearchPanelHost` 의 콜백
"""

from __future__ import annotations

from dataclasses import dataclass


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
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
from .tracker_bulk_update_dialog import BulkUpdateProgressDialog
from .tracker_bulk_update_dialog import BulkUpdateRequest
from .tracker_bulk_update_dialog import TrackerBulkUpdateDialog
from .tracker_condition_builder import TrackerConditionDialog
from .tracker_item_editor import EditableTrackerSchema
from .tracker_query_models import PageResult
from .tracker_query_models import ProjectSummary
from .tracker_query_models import TrackerItemSummary
from .tracker_query_models import TrackerQuery
from .tracker_query_models import TrackerSearchMode
from .tracker_query_models import TrackerSummary
from .tracker_workspace_support import DEFAULT_SEARCH_PAGE_SIZE
from .tracker_workspace_support import ITEM_SUMMARY_ROLE
from .worker import BulkUpdateWorker


@dataclass(frozen=True)
class SearchPanelHost:
    """검색 탭이 작업공간 화면에 되돌려주는 일."""

    submit: Callable[..., int]
    show_error: Callable[..., None]
    set_workspace_status: Callable[..., None]
    open_baseline_comparison: Callable[[], None]
    selected_hierarchy_baseline_id: Callable[[], int | None]
    current_tracker: Callable[[], TrackerSummary | None]
    current_project: Callable[[], ProjectSummary | None]
    detail_panel: Callable[[], Any]


class TrackerSearchPanel(QWidget):
    """트래커 검색과 일괄 수정 화면."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        host: SearchPanelHost,
        settings_provider: Callable[[], GuiSettings],
        service: Any,
        editor_service: Any,
        bulk_update_service: Any,
        bulk_run_store: Any,
        bulk_request_provider: Any = None,
        bulk_chunk_size_saver: Any = None,
        activity_recorder: Any = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self.settings_provider = settings_provider
        self.service = service
        self.editor_service = editor_service
        self.bulk_update_service = bulk_update_service
        self.bulk_run_store = bulk_run_store
        self.bulk_request_provider = bulk_request_provider
        self.bulk_chunk_size_saver = bulk_chunk_size_saver
        self.activity_recorder = activity_recorder

        self._search_page = 1
        self._last_search_query: Any = None
        self._last_search_result: Any = None
        self._search_schema: Any = None
        self._selected_search_ids: set[int] = set()
        self._excluded_search_ids: set[int] = set()
        self._all_search_selected = False
        self._bulk_worker: BulkUpdateWorker | None = None
        self._bulk_progress_dialog: BulkUpdateProgressDialog | None = None

        self.setObjectName("tracker_search_tab")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("검색 방식", self))
        self.search_mode_combo = QComboBox(self)
        self.search_mode_combo.addItem("간편 검색", TrackerSearchMode.SIMPLE.value)
        self.search_mode_combo.addItem("상세 조건 검색", TrackerSearchMode.CONDITIONS.value)
        self.search_mode_combo.currentIndexChanged.connect(self._on_search_mode_changed)
        mode_row.addWidget(self.search_mode_combo)
        mode_row.addStretch(1)
        self.search_button = QPushButton("현재 트래커 검색", self)
        self.search_button.setObjectName("primary_button")
        self.search_button.clicked.connect(self._run_search)
        mode_row.addWidget(self.search_button)
        self.baseline_compare_button = QPushButton("Baseline 비교", self)
        self.baseline_compare_button.setObjectName("tracker_baseline_compare_button")
        self.baseline_compare_button.setToolTip("Baseline 비교 탭으로 이동합니다.")
        self.baseline_compare_button.clicked.connect(self._host.open_baseline_comparison)
        self.baseline_compare_button.hide()
        layout.addLayout(mode_row)

        self.simple_search_host = QWidget(self)
        first_row = QHBoxLayout(self.simple_search_host)
        first_row.setContentsMargins(0, 0, 0, 0)
        self.search_text_input = QLineEdit(self.simple_search_host)
        self.search_text_input.setObjectName("tracker_search_text")
        self.search_text_input.setPlaceholderText("ID 또는 요약")
        self.search_text_input.returnPressed.connect(self._run_search)
        first_row.addWidget(self.search_text_input, 2)
        self.search_status_input = QLineEdit(self.simple_search_host)
        self.search_status_input.setObjectName("tracker_search_status")
        self.search_status_input.setPlaceholderText("상태")
        self.search_status_input.returnPressed.connect(self._run_search)
        first_row.addWidget(self.search_status_input, 1)
        self.search_assignee_input = QLineEdit(self.simple_search_host)
        self.search_assignee_input.setObjectName("tracker_search_assignee")
        self.search_assignee_input.setPlaceholderText("담당자")
        self.search_assignee_input.returnPressed.connect(self._run_search)
        first_row.addWidget(self.search_assignee_input, 1)
        layout.addWidget(self.simple_search_host)

        self.condition_dialog = TrackerConditionDialog(self)
        self.condition_builder = self.condition_dialog.builder
        self.condition_builder.changed.connect(self._update_condition_summary)
        self.condition_search_host = QWidget(self)
        condition_row = QHBoxLayout(self.condition_search_host)
        condition_row.setContentsMargins(0, 0, 0, 0)
        condition_row.setSpacing(8)
        self.condition_summary_label = QLabel(
            "상세 검색 조건을 설정하세요.", self.condition_search_host
        )
        self.condition_summary_label.setObjectName("tracker_panel_status")
        self.condition_summary_label.setWordWrap(True)
        condition_row.addWidget(self.condition_summary_label, 1)
        self.condition_open_button = QPushButton(
            "상세 조건 설정", self.condition_search_host
        )
        self.condition_open_button.clicked.connect(self._open_condition_dialog)
        condition_row.addWidget(self.condition_open_button)
        self.condition_search_host.hide()
        layout.addWidget(self.condition_search_host)

        self.search_scope_label = QLabel("프로젝트와 트래커를 먼저 선택하세요.")
        self.search_scope_label.setObjectName("tracker_panel_status")
        self.search_scope_label.setWordWrap(True)
        layout.addWidget(self.search_scope_label)

        selection_row = QHBoxLayout()
        self.search_selection_label = QLabel("선택 0개", self)
        self.search_selection_label.setObjectName("tracker_panel_status")
        selection_row.addWidget(self.search_selection_label)
        selection_row.addStretch(1)
        self.select_page_button = QPushButton("현재 페이지 선택", self)
        self.select_page_button.clicked.connect(self._select_current_search_page)
        selection_row.addWidget(self.select_page_button)
        self.select_all_results_button = QPushButton("검색 결과 전체 선택", self)
        self.select_all_results_button.clicked.connect(self._select_all_search_results)
        selection_row.addWidget(self.select_all_results_button)
        self.clear_search_selection_button = QPushButton("선택 해제", self)
        self.clear_search_selection_button.clicked.connect(self.clear_selection)
        selection_row.addWidget(self.clear_search_selection_button)
        self.bulk_update_button = QPushButton("선택 항목 일괄 수정", self)
        self.bulk_update_button.setObjectName("primary_button")
        self.bulk_update_button.clicked.connect(self._start_bulk_update)
        selection_row.addWidget(self.bulk_update_button)
        layout.addLayout(selection_row)

        self.search_table = QTableWidget(0, 5, self)
        self.search_table.setObjectName("tracker_search_results")
        self.search_table.setHorizontalHeaderLabels(["선택", "ID", "요약", "상태", "담당자"])
        self.search_table.setAlternatingRowColors(True)
        self.search_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.search_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.search_table.verticalHeader().setVisible(False)
        self.search_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.search_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.search_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.search_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.search_table.itemChanged.connect(self._on_search_check_changed)
        self.search_table.itemSelectionChanged.connect(self._on_search_selection_changed)
        layout.addWidget(self.search_table, 1)

        page_row = QHBoxLayout()
        self.search_previous_button = QPushButton("이전", self)
        self.search_previous_button.clicked.connect(
            lambda: self._run_search(page=max(self._search_page - 1, 1), reuse=True)
        )
        self.search_page_label = QLabel("1 페이지")
        self.search_page_label.setObjectName("tracker_page_label")
        self.search_next_button = QPushButton("다음", self)
        self.search_next_button.clicked.connect(
            lambda: self._run_search(page=self._search_page + 1, reuse=True)
        )
        page_row.addStretch(1)
        page_row.addWidget(self.search_previous_button)
        page_row.addWidget(self.search_page_label)
        page_row.addWidget(self.search_next_button)
        layout.addLayout(page_row)

    def reset_results(self, message: str) -> None:
        """트래커 선택이 바뀌어 검색 결과가 더 이상 맞지 않을 때 비운다."""
        self.search_table.setRowCount(0)
        self._last_search_query = None
        self._last_search_result = None
        self._search_page = 1
        self.reset_condition_search(message)
        self.clear_selection()

    def reset_scope(self) -> None:
        self.search_scope_label.setText("프로젝트와 트래커를 먼저 선택하세요.")
        self.search_previous_button.setEnabled(False)
        self.search_next_button.setEnabled(False)

    def set_available(
        self,
        available: bool,
        *,
        has_tracker: bool,
        offline: bool,
        historical: bool,
    ) -> None:
        """조회 준비가 됐을 때만 검색과 일괄 수정을 연다."""
        ready = available and has_tracker
        self.search_text_input.setEnabled(ready)
        self.search_status_input.setEnabled(ready)
        self.search_assignee_input.setEnabled(ready)
        self.search_button.setEnabled(ready)
        self.search_mode_combo.setEnabled(ready)
        self.condition_open_button.setEnabled(ready)
        self.baseline_compare_button.setEnabled(ready and self._last_search_query is not None)
        self.bulk_update_button.setEnabled(
            ready and not offline and not historical and self.selected_count() > 0
        )

    def refresh_item(self, detail: Any) -> None:
        """수정 결과를 검색 결과 표에도 반영한다."""
        summary = detail.summary
        for row in range(self.search_table.rowCount()):
            id_item = self.search_table.item(row, 0)
            if id_item is None:
                continue
            existing = id_item.data(ITEM_SUMMARY_ROLE)
            if not isinstance(existing, TrackerItemSummary) or existing.item_id != detail.item_id:
                continue
            updated = replace(
                existing,
                name=summary.name,
                status=summary.status,
                assignees=summary.assignees,
                modified_at=summary.modified_at,
                version=summary.version,
            )
            id_item.setData(ITEM_SUMMARY_ROLE, updated)
            # 셀이 아직 만들어지지 않았으면 갱신할 대상이 없다.
            for column, text in (
                (1, updated.name),
                (2, updated.status or "-"),
                (3, ", ".join(updated.assignees) or "-"),
            ):
                cell = self.search_table.item(row, column)
                if cell is not None:
                    cell.setText(text)

    def remove_item(self, item_id: int) -> None:
        for row in range(self.search_table.rowCount() - 1, -1, -1):
            id_item = self.search_table.item(row, 0)
            summary = id_item.data(ITEM_SUMMARY_ROLE) if id_item is not None else None
            if isinstance(summary, TrackerItemSummary) and summary.item_id == int(item_id):
                self.search_table.removeRow(row)

    def update_scope(self) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            self.search_scope_label.setText("프로젝트와 트래커를 먼저 선택하세요.")
            return
        self.search_scope_label.setText(
            f"검색 범위: {tracker.name} ({tracker.tracker_id}) · "
            "ID 바로 열기와 달리 이 트래커 밖의 아이템은 검색하지 않습니다."
        )

    def _on_search_selection_changed(self) -> None:
        selected = self.search_table.selectedItems()
        if not selected:
            return
        summary_cell = self.search_table.item(selected[0].row(), 1)
        if summary_cell is None:
            return
        summary = summary_cell.data(ITEM_SUMMARY_ROLE)
        if isinstance(summary, TrackerItemSummary):
            self._host.detail_panel().load_detail(summary.item_id)

    def _on_search_check_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        id_item = self.search_table.item(item.row(), 1)
        summary = id_item.data(ITEM_SUMMARY_ROLE) if id_item is not None else None
        if not isinstance(summary, TrackerItemSummary):
            return
        checked = item.checkState() == Qt.CheckState.Checked
        if self._all_search_selected:
            if checked:
                self._excluded_search_ids.discard(summary.item_id)
            else:
                self._excluded_search_ids.add(summary.item_id)
        elif checked:
            self._selected_search_ids.add(summary.item_id)
        else:
            self._selected_search_ids.discard(summary.item_id)
        self._update_search_selection_ui()

    def _run_search(self, *, page: int = 1, reuse: bool = False) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            self._host.set_workspace_status("검색할 트래커를 먼저 선택하세요.", tone="warning")
            return
        if reuse and self._last_search_query is not None:
            query = replace(self._last_search_query, page=max(int(page), 1))
        elif self.search_mode_combo.currentData() == TrackerSearchMode.CONDITIONS.value:
            if self._search_schema is None:
                self.load_schema(run_after=True)
                return
            try:
                groups = self.condition_builder.values()
                query = TrackerQuery(
                    tracker_id=tracker.tracker_id,
                    mode=TrackerSearchMode.CONDITIONS,
                    groups=groups,
                    page=max(int(page), 1),
                    page_size=DEFAULT_SEARCH_PAGE_SIZE,
                    sort="item.id ASC",
                )
                query.build_cbql()
            except Exception as exc:
                self._host.set_workspace_status(str(exc), tone="warning")
                return
        else:
            text = self.search_text_input.text().strip()
            status = self.search_status_input.text().strip()
            assignee = self.search_assignee_input.text().strip()
            if not any((text, status, assignee)):
                self._host.set_workspace_status(
                    "트래커 검색에는 ID/요약, 상태, 담당자 중 하나 이상을 입력하세요.",
                    tone="warning",
                )
                return
            query = TrackerQuery(
                tracker_id=tracker.tracker_id,
                mode=TrackerSearchMode.SIMPLE,
                text=text,
                status=status,
                assignee=assignee,
                page=max(int(page), 1),
                page_size=DEFAULT_SEARCH_PAGE_SIZE,
                sort="item.id ASC",
            )
        if not reuse:
            self.clear_selection()
        self._last_search_query = replace(query, page=1)
        tracker_id = tracker.tracker_id
        settings = self.settings_provider()
        self.search_button.setEnabled(False)
        self.search_scope_label.setText(
            f"{tracker.name} ({tracker_id}) 안에서 검색하는 중입니다."
        )

        def loaded(result: PageResult[TrackerItemSummary]) -> None:
            still_selected = self._host.current_tracker()
            if still_selected is None or still_selected.tracker_id != tracker_id:
                return
            self.search_button.setEnabled(True)
            self.baseline_compare_button.setEnabled(True)
            self._render_search_results(result)
            self._host.set_workspace_status(
                f"현재 트래커에서 검색 결과 {result.total}개를 찾았습니다."
            )

        def failed(exc: Exception) -> None:
            self.search_button.setEnabled(True)
            self.baseline_compare_button.setEnabled(self._last_search_query is not None)
            self.update_scope()
            self._host.show_error(exc, prefix="트래커 검색 실패")

        self._host.submit("search", lambda: self.service.search(settings, query), loaded, failed)

    def _render_search_results(self, result: PageResult[TrackerItemSummary]) -> None:
        self.search_table.blockSignals(True)
        self.search_table.setRowCount(len(result.items))
        for row, summary in enumerate(result.items):
            check_item = QTableWidgetItem("")
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            selected = (
                summary.item_id not in self._excluded_search_ids
                if self._all_search_selected
                else summary.item_id in self._selected_search_ids
            )
            check_item.setCheckState(
                Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
            )
            self.search_table.setItem(row, 0, check_item)
            values = (
                str(summary.item_id),
                summary.name,
                summary.status or "-",
                ", ".join(summary.assignees) or "-",
            )
            for column, value in enumerate(values, start=1):
                cell = QTableWidgetItem(value)
                if column == 1:
                    cell.setData(ITEM_SUMMARY_ROLE, summary)
                self.search_table.setItem(row, column, cell)
        self.search_table.blockSignals(False)
        self._last_search_result = result
        self._search_page = result.page
        visible_end = min(result.page * result.page_size, result.total)
        visible_start = 0 if not result.items else ((result.page - 1) * result.page_size) + 1
        scope_tracker = self._host.current_tracker()
        tracker_text = (
            "-"
            if scope_tracker is None
            else f"{scope_tracker.name} ({scope_tracker.tracker_id})"
        )
        self.search_scope_label.setText(
            f"검색 범위: {tracker_text} · {result.total}개 중 {visible_start}–{visible_end}개"
        )
        self.search_page_label.setText(f"{result.page} 페이지")
        pagination_available = result.server_honored_pagination
        self.search_previous_button.setEnabled(pagination_available and result.has_previous)
        self.search_next_button.setEnabled(pagination_available and result.has_next)
        self._update_search_selection_ui()

    def _on_search_mode_changed(self, *args) -> None:
        del args
        condition_mode = (
            self.search_mode_combo.currentData() == TrackerSearchMode.CONDITIONS.value
        )
        self.simple_search_host.setVisible(not condition_mode)
        self.condition_search_host.setVisible(condition_mode)
        self.search_button.setText(
            "상세 조건으로 검색" if condition_mode else "현재 트래커 검색"
        )
        if not condition_mode:
            self.condition_dialog.close()
        self._last_search_query = None
        self._last_search_result = None
        self.search_table.setRowCount(0)
        self.clear_selection()
        if condition_mode and self._host.current_tracker() is not None:
            self.load_schema()

    def _open_condition_dialog(self) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            self._host.set_workspace_status(
                "상세 검색 조건을 설정할 트래커를 먼저 선택하세요.",
                tone="warning",
            )
            return
        if self._search_schema is None or self._search_schema.tracker_id != tracker.tracker_id:
            self.condition_summary_label.setText(
                "상세 검색에 사용할 필드 정보를 불러오는 중입니다."
            )
            self.load_schema(open_after=True)
            return
        self.condition_dialog.show_editor()

    def _update_condition_summary(self) -> None:
        self.condition_dialog.refresh_summary()
        self.condition_summary_label.setText(
            f"{self.condition_builder.summary_text()} · 버튼을 눌러 조건을 편집할 수 있습니다."
        )

    def reset_condition_search(self, message: str) -> None:
        self._search_schema = None
        self.condition_dialog.close()
        self.condition_builder.clear_schema()
        self.condition_summary_label.setText(message)

    def load_schema(
        self,
        *,
        run_after: bool = False,
        open_after: bool = False,
    ) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            return
        if self._search_schema is not None and self._search_schema.tracker_id == tracker.tracker_id:
            if run_after:
                self._run_search()
            if open_after:
                self.condition_dialog.show_editor()
            return
        tracker_id = tracker.tracker_id
        settings = self.settings_provider()
        self.condition_summary_label.setText(
            "상세 검색에 사용할 필드 정보를 불러오는 중입니다."
        )

        def loaded(schema: EditableTrackerSchema) -> None:
            still_selected = self._host.current_tracker()
            if still_selected is None or still_selected.tracker_id != tracker_id:
                return
            self._search_schema = schema
            self.condition_builder.set_schema(schema)
            self._update_condition_summary()
            if run_after:
                self._run_search()
            if open_after:
                self.condition_dialog.show_editor()

        def failed(exc: Exception) -> None:
            self.condition_summary_label.setText(
                "상세 검색 필드 정보를 불러오지 못했습니다. 다시 시도하세요."
            )
            self._host.show_error(exc, prefix="검색 schema 조회 실패")

        self._host.submit(
            "search_schema",
            lambda: self.editor_service.load_create_schema(settings, tracker_id),
            loaded,
            failed,
        )

    def selected_count(self) -> int:
        if self._all_search_selected and self._last_search_result is not None:
            return max(self._last_search_result.total - len(self._excluded_search_ids), 0)
        return len(self._selected_search_ids)

    def _update_search_selection_ui(self) -> None:
        count = self.selected_count()
        suffix = " · 검색 결과 전체 기준" if self._all_search_selected else ""
        self.search_selection_label.setText(f"선택 {count:,}개{suffix}")
        has_result = self._last_search_result is not None and bool(
            self._last_search_result.items
        )
        self.select_page_button.setEnabled(has_result)
        self.select_all_results_button.setEnabled(has_result)
        self.clear_search_selection_button.setEnabled(count > 0)
        settings = self.settings_provider()
        self.bulk_update_button.setEnabled(
            count > 0
            and self._host.current_tracker() is not None
            and not bool(settings.offline_mode)
        )

    def _select_current_search_page(self) -> None:
        result = self._last_search_result
        if result is None:
            return
        if self._all_search_selected:
            self._excluded_search_ids.difference_update(
                summary.item_id for summary in result.items
            )
        else:
            self._selected_search_ids.update(summary.item_id for summary in result.items)
        self._render_search_results(result)

    def _select_all_search_results(self) -> None:
        if self._last_search_result is None:
            return
        self._all_search_selected = True
        self._selected_search_ids.clear()
        self._excluded_search_ids.clear()
        self._render_search_results(self._last_search_result)

    def clear_selection(self) -> None:
        self._selected_search_ids.clear()
        self._all_search_selected = False
        self._excluded_search_ids.clear()
        if hasattr(self, "search_table"):
            self.search_table.blockSignals(True)
            for row in range(self.search_table.rowCount()):
                item = self.search_table.item(row, 0)
                if item is not None:
                    item.setCheckState(Qt.CheckState.Unchecked)
            self.search_table.blockSignals(False)
        if hasattr(self, "search_selection_label"):
            self._update_search_selection_ui()

    def _start_bulk_update(self) -> None:
        if self._host.selected_hierarchy_baseline_id() is not None:
            self._host.set_workspace_status(
                "Baseline 조회 중에는 일괄 수정할 수 없습니다.",
                tone="warning",
            )
            return
        if self.selected_count() <= 0:
            return
        if self._all_search_selected:
            query = self._last_search_query
            if query is None:
                return
            settings = self.settings_provider()
            exclusions = set(self._excluded_search_ids)

            def loaded(items: tuple[TrackerItemSummary, ...]) -> None:
                item_ids = tuple(
                    item.item_id for item in items if item.item_id not in exclusions
                )
                self._prepare_bulk_update(item_ids)

            self._host.submit(
                "search_all",
                lambda: self.service.load_all_search_items(settings, query),
                loaded,
                lambda exc: self._host.show_error(exc, prefix="전체 검색 결과 조회 실패"),
            )
            return
        self._prepare_bulk_update(tuple(sorted(self._selected_search_ids)))

    def _prepare_bulk_update(
        self,
        item_ids: tuple[int, ...],
        *,
        initial_field_ids: tuple[int, ...] = (),
        initial_clear_field_ids: tuple[int, ...] = (),
        initial_atomic: bool = True,
        initial_chunk_size: int | None = None,
    ) -> None:
        if self._host.selected_hierarchy_baseline_id() is not None:
            self._host.set_workspace_status(
                "Baseline 조회 중에는 일괄 수정할 수 없습니다.",
                tone="warning",
            )
            return
        tracker = self._host.current_tracker()
        if tracker is None or not item_ids:
            return
        settings = self.settings_provider()
        if bool(settings.offline_mode):
            self._host.set_workspace_status(
                "테스트 모드에서는 일괄 수정할 수 없습니다.", tone="warning"
            )
            return
        tracker_id = tracker.tracker_id

        def loaded(schema: EditableTrackerSchema) -> None:
            still_selected = self._host.current_tracker()
            if still_selected is None or still_selected.tracker_id != tracker_id:
                return
            kwargs = {
                "tracker_name": tracker.name,
                "target_count": len(item_ids),
                "initial_chunk_size": (
                    initial_chunk_size
                    if initial_chunk_size is not None
                    else int(getattr(settings, "bulk_update_chunk_size", 1000) or 1000)
                ),
                "initial_field_ids": initial_field_ids,
                "initial_clear_field_ids": initial_clear_field_ids,
                "initial_atomic": initial_atomic,
                "parent": self,
            }
            request = (
                self.bulk_request_provider(schema, **kwargs)
                if self.bulk_request_provider is not None
                else TrackerBulkUpdateDialog.request(schema, **kwargs)
            )
            if request is None:
                return
            if callable(self.bulk_chunk_size_saver):
                self.bulk_chunk_size_saver(request.chunk_size)
            self._execute_bulk_update(item_ids, schema, request)

        self._host.submit(
            "editor_schema",
            lambda: self.editor_service.load_create_schema(settings, tracker_id),
            loaded,
            lambda exc: self._host.show_error(exc, prefix="일괄 수정 schema 조회 실패"),
        )

    def _execute_bulk_update(
        self,
        item_ids: tuple[int, ...],
        schema: EditableTrackerSchema,
        request: BulkUpdateRequest,
    ) -> None:
        tracker = self._host.current_tracker()
        if tracker is None:
            return
        settings = self.settings_provider()
        progress = BulkUpdateProgressDialog(len(item_ids), self)
        worker = BulkUpdateWorker(
            self.bulk_update_service,
            settings,
            tracker_id=tracker.tracker_id,
            item_ids=item_ids,
            schema=schema,
            changes=request.changes,
            atomic=request.atomic,
            chunk_size=request.chunk_size,
        )
        self._bulk_progress_dialog = progress
        self._bulk_worker = worker
        progress.cancel_button.clicked.connect(worker.request_cancel)
        progress.cancel_button.clicked.connect(
            lambda _checked=False: progress.cancel_button.setEnabled(False)
        )
        worker.progress_changed.connect(progress.update_event)
        worker.completed.connect(self._finish_bulk_update)
        worker.failed.connect(self._fail_bulk_update)
        worker.finished.connect(self._cleanup_bulk_worker)
        progress.show()
        try:
            worker.start()
        except Exception as exc:
            progress.reject()
            self._bulk_progress_dialog = None
            self._cleanup_bulk_worker()
            self._host.show_error(exc, prefix="일괄 수정 시작 실패")

    def _finish_bulk_update(self, result) -> None:
        progress = self._bulk_progress_dialog
        if progress is not None:
            progress.accept()
        self._bulk_progress_dialog = None
        if self.bulk_run_store is not None:
            self.bulk_run_store.append(result)
        success_count = len(result.successful_item_ids)
        retry_count = len(result.retry_item_ids)
        if result.cancelled:
            activity_result = ActivityResult.CANCELLED
        elif retry_count and success_count:
            activity_result = ActivityResult.PARTIAL
        elif retry_count:
            activity_result = ActivityResult.FAILED
        else:
            activity_result = ActivityResult.SUCCESS
        tracker = self._host.current_tracker()
        project = self._host.current_project()
        if callable(self.activity_recorder):
            self.activity_recorder(
                ActivityRecord.create(
                    ActivityOperation.BULK_UPDATE,
                    activity_result,
                    source="tracker_workspace",
                    summary=(
                        f"일괄 수정 성공 {success_count:,}건, 재시도 대상 {retry_count:,}건"
                    ),
                    project_id=project.project_id if project else None,
                    project_name=project.name if project else "",
                    tracker_id=tracker.tracker_id if tracker else result.tracker_id,
                    tracker_name=tracker.name if tracker else "",
                    details={
                        "run_id": result.run_id,
                        "target_count": len(result.target_item_ids),
                        "success_count": success_count,
                        "failed_count": len(result.failed_item_ids),
                        "rolled_back_count": len(result.rolled_back_item_ids),
                        "unattempted_count": len(result.unattempted_item_ids),
                        "atomic": result.atomic,
                        "chunk_size": result.chunk_size,
                    },
                )
            )
        self._host.set_workspace_status(
            f"일괄 수정 완료: 성공 {success_count:,}건, 재시도 대상 {retry_count:,}건.",
            tone="warning" if retry_count else "info",
        )
        self.clear_selection()

    def _fail_bulk_update(self, exc: Exception) -> None:
        if self._bulk_progress_dialog is not None:
            self._bulk_progress_dialog.reject()
        self._bulk_progress_dialog = None
        self._host.show_error(exc, prefix="일괄 수정 실패")

    def _cleanup_bulk_worker(self) -> None:
        worker = self._bulk_worker
        self._bulk_worker = None
        if worker is not None:
            worker.deleteLater()

    def open_bulk_retry(self, run_id: str) -> None:
        if self.bulk_run_store is None:
            return
        record = self.bulk_run_store.get(run_id)
        if record is None:
            self._host.set_workspace_status("재시도 실행 기록을 찾지 못했습니다.", tone="warning")
            return
        still_selected = self._host.current_tracker()
        if still_selected is None or still_selected.tracker_id != record.tracker_id:
            self._host.set_workspace_status(
                f"트래커 {record.tracker_id}을 선택한 뒤 재시도하세요.", tone="warning"
            )
            return
        if not record.retry_item_ids:
            self._host.set_workspace_status("이 실행 기록에는 재시도 대상이 없습니다.")
            return
        self._prepare_bulk_update(
            record.retry_item_ids,
            initial_field_ids=record.field_ids,
            initial_clear_field_ids=record.clear_field_ids,
            initial_atomic=record.atomic,
            initial_chunk_size=record.chunk_size,
        )
