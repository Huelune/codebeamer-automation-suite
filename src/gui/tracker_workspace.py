from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QFrame
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QSplitter
    from PySide6.QtWidgets import QTabWidget
    from PySide6.QtWidgets import QTreeWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

import contextlib

from src.diagnostics import DiagnosticSource

from .activity_history import ActivityOperation
from .activity_history import ActivityRecord
from .activity_history import ActivityResult
from .settings_store import GuiSettings
from .tracker_baseline_compare import BaselineComparisonSource
from .tracker_baseline_compare import TrackerBaseline
from .tracker_baseline_export import BaselineExportError
from .tracker_baseline_workspace import BaselineWorkspaceHost
from .tracker_baseline_workspace import BaselineWorkspacePanel
from .tracker_bulk_update import BulkUpdateRunStore
from .tracker_bulk_update import TrackerBulkUpdateService
from .tracker_bulk_update_dialog import BulkUpdateRequest
from .tracker_comment_service import TrackerCommentService
from .tracker_content_service import TrackerContentService
from .tracker_detail_dialog import DetailDialogController
from .tracker_detail_panel import DetailPanelHost
from .tracker_detail_panel import TrackerDetailPanel
from .tracker_hierarchy_export import TrackerHierarchyExportError
from .tracker_hierarchy_panel import HierarchyPanelHost
from .tracker_hierarchy_panel import TrackerHierarchyPanel
from .tracker_item_context_service import TrackerItemContextService
from .tracker_item_create_dialog import TrackerItemCreateDialog
from .tracker_item_create_dialog import TrackerItemCreateRequest
from .tracker_item_editor import EditableTrackerSchema
from .tracker_item_editor import TrackerItemEditorService
from .tracker_item_editor import TrackerItemWriteError
from .tracker_query_models import ProjectSummary
from .tracker_query_models import TrackerItemContext
from .tracker_query_models import TrackerItemDetail
from .tracker_query_models import TrackerItemSummary
from .tracker_query_models import TrackerQueryServiceError
from .tracker_query_models import TrackerSearchMode
from .tracker_query_models import TrackerSummary
from .tracker_query_service import TrackerQueryService
from .tracker_search_panel import SearchPanelHost
from .tracker_search_panel import TrackerSearchPanel
from .tracker_workspace_support import CHILDREN_LOADED_ROLE
from .tracker_workspace_support import DEFAULT_SEARCH_PAGE_SIZE
from .tracker_workspace_support import HIERARCHY_FETCH_PAGE_SIZE
from .tracker_workspace_support import ITEM_SUMMARY_ROLE
from .tracker_workspace_support import PLACEHOLDER_ROLE
from .tracker_workspace_support import DirectItemResult
from .worker import BackgroundTask


REQUEST_BUSY_MESSAGES = {
    "projects": "프로젝트 목록을 불러오는 중입니다.",
    "trackers": "트래커 목록을 불러오는 중입니다.",
    "roots": "최상위 아이템을 불러오는 중입니다.",
    "detail": "아이템 상세 정보를 불러오는 중입니다.",
    "create_schema": "새 아이템 생성 필드를 확인하는 중입니다.",
    "item_create": "새 트래커 아이템을 생성하는 중입니다.",
    "search": "현재 트래커에서 아이템을 검색하는 중입니다.",
    "search_schema": "상세 검색에 사용할 필드를 확인하는 중입니다.",
    "search_all": "검색 결과 전체 대상을 확인하는 중입니다.",
    "baseline_list": "비교 가능한 baseline 목록을 불러오는 중입니다.",
    "baseline_compare": "트래커 전체 아이템을 두 기준에서 비교하는 중입니다.",
    "baseline_export": "Baseline 비교 Excel 파일을 생성하는 중입니다.",
    "hierarchy_export_fields": "계층 내보내기 필드 정보를 확인하는 중입니다.",
    "hierarchy_export": "트래커 전체 계층 Excel 파일을 생성하는 중입니다.",
    "baseline_hierarchy": "선택한 Baseline의 전체 계층을 불러오는 중입니다.",
    "direct": "아이템 ID의 위치와 계층을 확인하는 중입니다.",
    "editor_schema": "수정 가능한 필드를 확인하는 중입니다.",
    "item_write": "트래커 아이템 변경 사항을 반영하는 중입니다.",
}


class TrackerWorkspacePage(QWidget):
    """프로젝트와 트래커를 기준으로 계층, 검색, 상세를 연결한다."""

    def __init__(
        self,
        *,
        settings_provider: Callable[[], GuiSettings],
        service: TrackerQueryService | None = None,
        content_service: TrackerContentService | None = None,
        context_service: TrackerItemContextService | None = None,
        comment_service: TrackerCommentService | None = None,
        editor_service: TrackerItemEditorService | None = None,
        open_settings: Callable[[], None] | None = None,
        delete_confirmer: Callable[[TrackerItemDetail], bool] | None = None,
        baseline_compare_confirmer: Callable[
            [BaselineComparisonSource, BaselineComparisonSource], bool
        ]
        | None = None,
        create_request_provider: Callable[
            [EditableTrackerSchema, TrackerSummary, TrackerItemDetail | None],
            TrackerItemCreateRequest | None,
        ]
        | None = None,
        activity_recorder: Callable[[ActivityRecord], None] | None = None,
        bulk_update_service: TrackerBulkUpdateService | None = None,
        bulk_run_store: BulkUpdateRunStore | None = None,
        bulk_chunk_size_saver: Callable[[int], None] | None = None,
        bulk_request_provider: Callable[..., BulkUpdateRequest | None] | None = None,
        busy_started: Callable[[str], object] | None = None,
        busy_finished: Callable[[object], None] | None = None,
        error_notifier: Callable[[str, str], None] | None = None,
        task_factory=BackgroundTask,
        synchronous: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tracker_workspace_page")
        self.settings_provider = settings_provider
        self.service = service or TrackerQueryService()
        self.content_service = content_service or TrackerContentService()
        self.context_service = context_service or TrackerItemContextService()
        self.comment_service = comment_service or TrackerCommentService()
        self.editor_service = editor_service or TrackerItemEditorService(
            query_service=self.service
        )
        self.open_settings = open_settings
        self.delete_confirmer = delete_confirmer
        self.baseline_compare_confirmer = baseline_compare_confirmer
        self.create_request_provider = create_request_provider
        self.activity_recorder = activity_recorder
        self.bulk_update_service = bulk_update_service or TrackerBulkUpdateService()
        self.bulk_run_store = bulk_run_store
        self.bulk_chunk_size_saver = bulk_chunk_size_saver
        self.bulk_request_provider = bulk_request_provider
        self.busy_started = busy_started
        self.busy_finished = busy_finished
        self.error_notifier = error_notifier
        self.task_factory = task_factory
        self.synchronous = bool(synchronous)

        self._activated = False
        self._settings_fingerprint: tuple[Any, ...] | None = None
        self._projects: tuple[ProjectSummary, ...] = ()
        self._trackers: tuple[TrackerSummary, ...] = ()
        self._current_project: ProjectSummary | None = None
        self._current_tracker: TrackerSummary | None = None
        self._request_tokens: dict[str, int] = {}
        self._tasks: set[Any] = set()
        # Baseline 목록 조회는 계층 탭 소스 선택과 비교 탭 양쪽에 결과를 넘긴다.
        self._baseline_loaded_tracker_id: int | None = None
        self._baseline_loading_tracker_id: int | None = None
        self._pre_editor_splitter_sizes: list[int] | None = None
        self._create_busy = False
        # 상세 창 배선은 _build_ui 안에서 참조하므로 그 전에 만든다.
        self.detail_dialog = DetailDialogController(self)

        self._build_ui()
        self._reset_workspace("프로젝트와 트래커를 불러오면 조회를 시작할 수 있습니다.")

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 16, 18, 16)
        root_layout.setSpacing(10)

        heading_row = QHBoxLayout()
        heading_row.setSpacing(8)
        title_group = QVBoxLayout()
        title_group.setSpacing(2)
        title = QLabel("트래커 작업공간")
        title.setObjectName("application_route_title")
        subtitle = QLabel(
            "프로젝트와 트래커를 선택해 계층을 탐색하거나, 현재 트래커 안에서 아이템을 검색합니다."
        )
        subtitle.setObjectName("application_route_description")
        subtitle.setWordWrap(True)
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        heading_row.addLayout(title_group, 1)

        self.direct_id_input = QLineEdit(self)
        self.direct_id_input.setObjectName("tracker_direct_id_input")
        self.direct_id_input.setPlaceholderText("아이템 ID")
        self.direct_id_input.setAccessibleName("아이템 ID 바로 열기")
        self.direct_id_input.setMaximumWidth(130)
        self.direct_id_input.returnPressed.connect(self._open_direct_item)
        heading_row.addWidget(self.direct_id_input)
        self.direct_open_button = QPushButton("ID 바로 열기", self)
        self.direct_open_button.setObjectName("primary_button")
        self.direct_open_button.clicked.connect(self._open_direct_item)
        heading_row.addWidget(self.direct_open_button)
        root_layout.addLayout(heading_row)

        context_card = QFrame(self)
        context_card.setObjectName("tracker_context_card")
        context_layout = QHBoxLayout(context_card)
        context_layout.setContentsMargins(12, 10, 12, 10)
        context_layout.setSpacing(8)

        project_label = QLabel("프로젝트")
        project_label.setObjectName("tracker_context_label")
        context_layout.addWidget(project_label)
        self.project_combo = QComboBox(context_card)
        self.project_combo.setObjectName("tracker_project_combo")
        self.project_combo.setMinimumWidth(150)
        self.project_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.project_combo.setMinimumContentsLength(18)
        self.project_combo.activated.connect(self._on_project_activated)
        context_layout.addWidget(self.project_combo, 1)

        tracker_label = QLabel("트래커")
        tracker_label.setObjectName("tracker_context_label")
        context_layout.addWidget(tracker_label)
        self.tracker_combo = QComboBox(context_card)
        self.tracker_combo.setObjectName("tracker_tracker_combo")
        self.tracker_combo.setMinimumWidth(150)
        self.tracker_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.tracker_combo.setMinimumContentsLength(18)
        self.tracker_combo.activated.connect(self._on_tracker_activated)
        context_layout.addWidget(self.tracker_combo, 1)

        self.create_item_button = QPushButton("새 아이템", context_card)
        self.create_item_button.setObjectName("primary_button")
        self.create_item_button.setToolTip(
            "현재 트래커에 최상위 또는 선택 아이템의 하위 항목을 만듭니다."
        )
        self.create_item_button.clicked.connect(self._create_item)
        context_layout.addWidget(self.create_item_button)

        self.refresh_context_button = QPushButton("새로고침", context_card)
        self.refresh_context_button.clicked.connect(lambda: self.activate(force=True))
        context_layout.addWidget(self.refresh_context_button)
        root_layout.addWidget(context_card)

        status_row = QHBoxLayout()
        self.workspace_status_label = QLabel("")
        self.workspace_status_label.setObjectName("tracker_workspace_status")
        self.workspace_status_label.setWordWrap(True)
        status_row.addWidget(self.workspace_status_label, 1)
        self.open_settings_button = QPushButton("설정 열기", self)
        self.open_settings_button.setVisible(self.open_settings is not None)
        if self.open_settings is not None:
            self.open_settings_button.clicked.connect(self.open_settings)
        status_row.addWidget(self.open_settings_button)
        root_layout.addLayout(status_row)

        self.workspace_mode_tabs = QTabWidget(self)
        self.workspace_mode_tabs.setObjectName("tracker_workspace_mode_tabs")
        browse_page = QWidget(self.workspace_mode_tabs)
        browse_page_layout = QVBoxLayout(browse_page)
        browse_page_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal, browse_page)
        splitter.setObjectName("tracker_workspace_splitter")
        splitter.setChildrenCollapsible(False)
        self.workspace_splitter = splitter

        browser_panel = QFrame(splitter)
        browser_panel.setObjectName("tracker_workspace_panel")
        browser_panel.setMinimumWidth(300)
        browser_layout = QVBoxLayout(browser_panel)
        browser_layout.setContentsMargins(10, 10, 10, 10)
        browser_layout.setSpacing(8)

        self.browser_tabs = QTabWidget(browser_panel)
        self.browser_tabs.setObjectName("tracker_browser_tabs")
        self.hierarchy_panel = self._build_hierarchy_panel()
        self.browser_tabs.addTab(self.hierarchy_panel, "계층")
        self.search_panel = self._build_search_panel()
        self.browser_tabs.addTab(self.search_panel, "트래커 검색")
        browser_layout.addWidget(self.browser_tabs, 1)

        self.detail_panel = self._build_detail_panel(splitter)

        splitter.addWidget(browser_panel)
        splitter.addWidget(self.detail_panel)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([560, 470])
        browse_page_layout.addWidget(splitter, 1)
        self.workspace_mode_tabs.addTab(browse_page, "트래커 조회")
        self.baseline_workspace = self._build_baseline_workspace()
        self.baseline_mode_index = self.workspace_mode_tabs.addTab(
            self.baseline_workspace, "Baseline 비교"
        )
        self.workspace_mode_tabs.currentChanged.connect(self._on_workspace_mode_changed)
        root_layout.addWidget(self.workspace_mode_tabs, 1)

    def _build_hierarchy_panel(self) -> TrackerHierarchyPanel:
        """계층 탭을 만들고 화면 쪽 동작을 콜백으로 넘긴다."""
        host = HierarchyPanelHost(
            submit=self._submit,
            show_error=self._show_error,
            set_workspace_status=self._set_workspace_status,
            set_available=self._set_available,
            record_activity=self._record_activity,
            next_token=self._next_token,
            invalidate_tracker_cache=self._invalidate_tracker_cache,
            current_tracker=lambda: self._current_tracker,
            current_project=lambda: self._current_project,
            detail_panel=lambda: self.detail_panel,
            search_panel=lambda: self.search_panel,
            baseline_workspace=lambda: self.baseline_workspace,
            browser_tabs=lambda: self.browser_tabs,
        )
        return TrackerHierarchyPanel(
            self,
            host=host,
            settings_provider=self.settings_provider,
            service=self.service,
        )

    def _build_detail_panel(self, parent: QWidget) -> TrackerDetailPanel:
        """상세 영역을 만들고 화면 쪽 동작을 콜백으로 넘긴다."""
        host = DetailPanelHost(
            submit=self._submit,
            show_error=self._show_error,
            set_workspace_status=self._set_workspace_status,
            record_item_activity=self._record_item_activity,
            refresh_visible_item=self._refresh_visible_item,
            remove_visible_item=self._remove_visible_item,
            invalidate_tracker_cache=self._invalidate_tracker_cache,
            is_historical_read_only=self._is_historical_read_only,
            selected_hierarchy_baseline_id=self.hierarchy_panel.selected_baseline_id,
            reload_current_detail=self._reload_current_detail,
            open_detail_dialog=self.detail_dialog.open_dialog,
            set_editor_expanded=self._set_editor_expanded,
        )
        return TrackerDetailPanel(
            parent,
            host=host,
            settings_provider=self.settings_provider,
            service=self.service,
            content_service=self.content_service,
            editor_service=self.editor_service,
            delete_confirmer=self.delete_confirmer,
        )

    def _set_editor_expanded(self, expanded: bool) -> None:
        """수정 탭을 볼 때만 상세 영역을 넓힌다.

        분할자는 화면 전체 배치라 상세 영역이 직접 건드리지 않는다.
        """
        if not expanded:
            if self._pre_editor_splitter_sizes is not None:
                self.workspace_splitter.setSizes(self._pre_editor_splitter_sizes)
                self._pre_editor_splitter_sizes = None
            return
        if self._pre_editor_splitter_sizes is None:
            self._pre_editor_splitter_sizes = self.workspace_splitter.sizes()
        available_width = sum(self.workspace_splitter.sizes())
        if available_width > 0:
            browser_width = max(300, int(available_width * 0.38))
            detail_width = max(300, available_width - browser_width)
            self.workspace_splitter.setSizes([browser_width, detail_width])

    def _build_baseline_workspace(self) -> BaselineWorkspacePanel:
        """Baseline 비교 탭을 만들고 화면 쪽 동작을 콜백으로 넘긴다."""
        host = BaselineWorkspaceHost(
            submit=self._submit,
            show_error=self._show_error,
            set_workspace_status=self._set_workspace_status,
            record_activity=self._record_activity,
            load_roots=self.hierarchy_panel.load_roots,
            placeholder_item=self.hierarchy_panel.placeholder_item,
            tree_item=self.hierarchy_panel.tree_item,
            replace_tree_children=self.hierarchy_panel.replace_tree_children,
            refresh_baselines=self._refresh_baseline_comparison,
            current_tracker=lambda: self._current_tracker,
            current_project=lambda: self._current_project,
            child_cache=lambda: self.hierarchy_panel.child_cache(),
            compare_confirmer=lambda: self.baseline_compare_confirmer,
        )
        return BaselineWorkspacePanel(
            self,
            host=host,
            settings_provider=self.settings_provider,
            service=self.service,
        )

    def _reset_baseline_state(self, message: str) -> None:
        """Baseline 탭과 목록 조회 상태를 함께 되돌린다.

        목록 조회는 계층 탭의 Baseline 선택과도 이어져 있어 화면이 들고 있다.
        """
        self._baseline_loaded_tracker_id = None
        self._baseline_loading_tracker_id = None
        self.baseline_workspace.reset_state(message)

    def _build_search_panel(self) -> TrackerSearchPanel:
        """검색 탭을 만들고 화면 쪽 동작을 콜백으로 넘긴다."""
        host = SearchPanelHost(
            submit=self._submit,
            show_error=self._show_error,
            set_workspace_status=self._set_workspace_status,
            open_baseline_comparison=self._open_baseline_comparison,
            selected_hierarchy_baseline_id=self.hierarchy_panel.selected_baseline_id,
            current_tracker=lambda: self._current_tracker,
            current_project=lambda: self._current_project,
            detail_panel=lambda: self.detail_panel,
        )
        return TrackerSearchPanel(
            self,
            host=host,
            settings_provider=self.settings_provider,
            service=self.service,
            editor_service=self.editor_service,
            bulk_update_service=self.bulk_update_service,
            bulk_run_store=self.bulk_run_store,
            bulk_request_provider=self.bulk_request_provider,
            bulk_chunk_size_saver=self.bulk_chunk_size_saver,
            activity_recorder=self.activity_recorder,
        )

    def open_bulk_retry(self, run_id: str) -> None:
        """실행 기록 화면에서 고른 일괄 수정을 다시 연다."""
        self.search_panel.open_bulk_retry(run_id)




    @staticmethod
    def _settings_key(settings: GuiSettings) -> tuple[Any, ...]:
        return (
            bool(settings.offline_mode),
            bool(getattr(settings, "server_wiki_html_enabled", False)),
            str(settings.base_url or "").strip().rstrip("/"),
            str(settings.username or "").strip(),
            bool(settings.password),
            str(settings.offline_schema_path or "").strip(),
            str(settings.offline_query_data_path or "").strip(),
        )

    @staticmethod
    def _settings_available(settings: GuiSettings) -> tuple[bool, str]:
        if bool(settings.offline_mode):
            if not str(settings.offline_query_data_path or "").strip():
                return (
                    False,
                    "테스트 모드 조회 데이터 Snapshot이 필요합니다. 설정에서 파일을 지정하고 적용하세요.",
                )
            return True, "테스트 모드 조회 데이터를 사용합니다."
        if all(
            (
                str(settings.base_url or "").strip(),
                str(settings.username or "").strip(),
                str(settings.password or ""),
            )
        ):
            return True, "온라인 연결을 사용합니다."
        return False, "활성 연결이 없습니다. 설정에서 연결을 검증하고 적용하세요."

    def activate(self, *, force: bool = False) -> None:
        settings = self.settings_provider()
        fingerprint = self._settings_key(settings)
        settings_changed = fingerprint != self._settings_fingerprint
        if force or settings_changed:
            clear_cache = getattr(self.service, "clear_cache", None)
            if callable(clear_cache):
                clear_cache()
            self.content_service.clear_cache()
            self.context_service.clear_cache()
            self.comment_service.clear_cache()
        if settings_changed:
            self._settings_fingerprint = fingerprint
            self._clear_context_state()
        available, message = self._settings_available(settings)
        self._set_available(available)
        if not available:
            self._set_workspace_status(message, tone="warning")
            self._activated = True
            return
        if self._activated and self._projects and not force and not settings_changed:
            return
        self._activated = True
        self._load_projects(force=force or settings_changed)

    def on_settings_applied(self, settings: GuiSettings | None = None) -> None:
        del settings
        self._activated = False
        self._settings_fingerprint = None
        self.activate(force=True)

    def _clear_context_state(self) -> None:
        self._invalidate_requests()
        self._projects = ()
        self._trackers = ()
        self._current_project = None
        self._current_tracker = None
        self.hierarchy_panel.root_cache().clear()
        self.hierarchy_panel.child_cache().clear()
        self.project_combo.clear()
        self.tracker_combo.clear()
        self.search_panel.reset_results("트래커를 선택하면 상세 조건을 설정할 수 있습니다.")
        self._baseline_loaded_tracker_id = None
        self._baseline_loading_tracker_id = None
        self.hierarchy_panel.clear_baseline_cache()
        self.hierarchy_panel.reset_source()
        self.detail_panel.reset_detail()
        self._reset_workspace("프로젝트와 트래커를 불러오는 중입니다.")

    def _reset_workspace(self, message: str) -> None:
        self.hierarchy_panel.item_tree.clear()
        self.hierarchy_panel.tree_status_label.setText(message)
        self._reset_baseline_state(message)
        self.search_panel.reset_scope()


    def _set_available(self, available: bool) -> None:
        settings = self.settings_provider()
        historical = self.hierarchy_panel.selected_baseline_id() is not None
        self.direct_id_input.setEnabled(available)
        self.direct_open_button.setEnabled(available)
        self.refresh_context_button.setEnabled(available)
        self.project_combo.setEnabled(available and bool(self._projects))
        self.tracker_combo.setEnabled(available and bool(self._trackers))
        self.hierarchy_panel.reload_roots_button.setEnabled(available and self._current_tracker is not None)
        self.hierarchy_panel.hierarchy_source_combo.setEnabled(
            available and self._current_tracker is not None
        )
        self.hierarchy_panel.set_export_available(
            available and self._current_tracker is not None,
            tracker_id=None if self._current_tracker is None else self._current_tracker.tracker_id,
            historical=historical,
        )
        self.baseline_workspace.set_available(
            available and self._current_tracker is not None
        )
        self.search_panel.set_available(
            available,
            has_tracker=self._current_tracker is not None,
            offline=bool(settings.offline_mode),
            historical=historical,
        )
        self.create_item_button.setEnabled(
            available
            and self._current_tracker is not None
            and not bool(settings.offline_mode)
            and not historical
            and not self._create_busy
        )

    def _set_workspace_status(self, message: str, *, tone: str = "info") -> None:
        self.workspace_status_label.setText(str(message or ""))
        self.workspace_status_label.setProperty("tone", tone)
        self.workspace_status_label.style().unpolish(self.workspace_status_label)
        self.workspace_status_label.style().polish(self.workspace_status_label)

    def _record_activity(self, record: ActivityRecord) -> None:
        if self.activity_recorder is None:
            return
        # 실행 기록 저장은 부가 기능이다. 기록이 실패해도 조회 흐름을 끊지 않는다.
        with contextlib.suppress(Exception):
            self.activity_recorder(record)

    def _record_item_activity(
        self,
        operation: ActivityOperation,
        result: ActivityResult,
        *,
        message: str,
        detail: TrackerItemDetail | None = None,
        item_id: int | None = None,
        item_name: str = "",
        parent_item_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        item_summary = detail.summary if detail is not None else None
        tracker = self._current_tracker
        project = self._current_project
        self._record_activity(
            ActivityRecord.create(
                operation,
                result,
                source="tracker_workspace",
                summary=message,
                project_id=(
                    item_summary.project_id
                    if item_summary is not None
                    else project.project_id if project is not None else None
                ),
                project_name=(
                    item_summary.project_name
                    if item_summary is not None
                    else project.name if project is not None else ""
                ),
                tracker_id=(
                    item_summary.tracker_id
                    if item_summary is not None
                    else tracker.tracker_id if tracker is not None else None
                ),
                tracker_name=(
                    item_summary.tracker_name
                    if item_summary is not None
                    else tracker.name if tracker is not None else ""
                ),
                item_id=(detail.item_id if detail is not None else item_id),
                item_name=(
                    item_summary.name if item_summary is not None else item_name
                ),
                parent_item_id=(
                    parent_item_id
                    if parent_item_id is not None
                    else detail.parent.item_id
                    if detail is not None and detail.parent is not None
                    else None
                ),
                details=details,
            )
        )

    def _next_token(self, key: str) -> int:
        token = self._request_tokens.get(key, 0) + 1
        self._request_tokens[key] = token
        return token

    def _is_current_token(self, key: str, token: int) -> bool:
        return self._request_tokens.get(key) == token

    def _invalidate_requests(self) -> None:
        for key in tuple(self._request_tokens):
            self._next_token(key)

    def _submit(
        self,
        key: str,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[Exception], None] | None = None,
    ) -> int:
        token = self._next_token(key)
        busy_token = self._start_request_busy(key)

        def success(result: Any) -> None:
            if self._is_current_token(key, token):
                on_success(result)

        def failure(exc: Exception) -> None:
            if not self._is_current_token(key, token):
                return
            if on_failure is not None:
                on_failure(exc)
            else:
                self._show_error(exc)

        if self.synchronous:
            try:
                success(operation())
            except Exception as exc:
                failure(exc)
            finally:
                self._finish_request_busy(busy_token)
            return token

        task = self.task_factory(operation)
        task.diagnostic_source = (
            DiagnosticSource.BASELINE
            if key.startswith("baseline")
            else DiagnosticSource.TRACKER
        )
        task.diagnostic_kind = (
            f"{'baseline' if key.startswith('baseline') else 'tracker'}_"
            f"{key.partition(':')[0]}"
        )[:100]
        self._tasks.add(task)
        task.completed.connect(success)
        task.failed.connect(failure)

        def cleanup() -> None:
            self._tasks.discard(task)
            self._finish_request_busy(busy_token)
            task.deleteLater()

        task.finished.connect(cleanup)
        try:
            task.start()
        except Exception as exc:
            cleanup()
            failure(exc)
        return token

    def _start_request_busy(self, key: str) -> object | None:
        if not callable(self.busy_started):
            return None
        if key.startswith(("wiki_", "attachments", "attachment_save:")):
            return None
        message = REQUEST_BUSY_MESSAGES.get(key)
        if message is None and key.startswith("children:"):
            item_id = key.partition(":")[2]
            message = f"#{item_id}의 하위 아이템을 불러오는 중입니다."
        if message is None:
            message = "Codebeamer 응답을 기다리는 중입니다."
        try:
            return self.busy_started(message)
        except Exception:
            return None

    def _finish_request_busy(self, token: object | None) -> None:
        if token is None or not callable(self.busy_finished):
            return
        # 이미 삭제된 위젯이면 RuntimeError, 시그니처가 맞지 않으면 TypeError 가 난다.
        with contextlib.suppress(RuntimeError, TypeError):
            self.busy_finished(token)

    def _show_error(self, exc: Exception, *, prefix: str = "") -> None:
        if isinstance(
            exc,
            (
                TrackerQueryServiceError,
                TrackerItemWriteError,
                BaselineExportError,
                TrackerHierarchyExportError,
                ValueError,
            ),
        ):
            message = str(exc)
        else:
            message = "조회 중 예상하지 못한 오류가 발생했습니다."
        if prefix:
            message = f"{prefix}: {message}"
        self._set_workspace_status(message, tone="error")
        if callable(self.error_notifier):
            self.error_notifier(prefix or "트래커 작업 실패", message)

    def _load_projects(self, *, force: bool = False) -> None:
        del force
        settings = self.settings_provider()
        self.project_combo.setEnabled(False)
        self.tracker_combo.setEnabled(False)
        self.refresh_context_button.setEnabled(False)
        self._set_workspace_status("프로젝트를 불러오는 중입니다.", tone="loading")

        def loaded(projects: tuple[ProjectSummary, ...]) -> None:
            self.refresh_context_button.setEnabled(True)
            self._projects = tuple(projects)
            self.project_combo.blockSignals(True)
            self.project_combo.clear()
            for project in self._projects:
                self.project_combo.addItem(
                    f"{project.name}  ·  {project.project_id}", project.project_id
                )
            preferred_id = self._preferred_id(
                str(settings.default_project_id or ""),
                self._current_project.project_id if self._current_project else None,
            )
            index = self._combo_index_for_id(self.project_combo, preferred_id)
            if index < 0 and self.project_combo.count():
                index = 0
            self.project_combo.setCurrentIndex(index)
            self.project_combo.blockSignals(False)
            if index < 0:
                self._current_project = None
                self._trackers = ()
                self.tracker_combo.clear()
                self._set_available(True)
                self._set_workspace_status("조회 가능한 프로젝트가 없습니다.", tone="warning")
                self._reset_workspace("조회 가능한 프로젝트가 없습니다.")
                return
            self.project_combo.setEnabled(True)
            self._current_project = self._projects[index]
            self._set_workspace_status(
                f"{len(self._projects)}개 프로젝트를 불러왔습니다. 트래커를 조회합니다."
            )
            self._load_trackers(self._current_project)

        def failed(exc: Exception) -> None:
            self.refresh_context_button.setEnabled(True)
            self._set_available(True)
            self._show_error(exc, prefix="프로젝트 조회 실패")

        self._submit("projects", lambda: self.service.load_projects(settings), loaded, failed)

    @staticmethod
    def _preferred_id(primary: str, fallback: int | None) -> int | None:
        for value in (primary, fallback):
            if value is None or value == "":
                continue
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                continue
            if normalized > 0:
                return normalized
        return None

    @staticmethod
    def _combo_index_for_id(combo: QComboBox, entity_id: int | None) -> int:
        if entity_id is None:
            return -1
        for index in range(combo.count()):
            try:
                if int(combo.itemData(index)) == int(entity_id):
                    return index
            except (TypeError, ValueError):
                continue
        return -1

    def _on_project_activated(self, index: int) -> None:
        if not (0 <= int(index) < len(self._projects)):
            return
        project = self._projects[int(index)]
        if self._current_project == project and self._trackers:
            return
        self._current_project = project
        self._current_tracker = None
        self.hierarchy_panel.clear_baseline_cache()
        self.hierarchy_panel.reset_source()
        self.search_panel.reset_condition_search("트래커를 불러오는 중입니다.")
        self._reset_baseline_state("트래커를 불러오는 중입니다.")
        self.detail_panel.reset_detail()
        self._load_trackers(project)

    def _load_trackers(self, project: ProjectSummary) -> None:
        settings = self.settings_provider()
        project_id = project.project_id
        self.tracker_combo.setEnabled(False)
        self.hierarchy_panel.reload_roots_button.setEnabled(False)
        self.search_panel.set_available(False, has_tracker=False, offline=False, historical=False)
        self._set_workspace_status(
            f"'{project.name}' 프로젝트의 트래커를 불러오는 중입니다.",
            tone="loading",
        )

        def loaded(trackers: tuple[TrackerSummary, ...]) -> None:
            if self._current_project is None or self._current_project.project_id != project_id:
                return
            self._trackers = tuple(trackers)
            self.tracker_combo.blockSignals(True)
            self.tracker_combo.clear()
            for tracker in self._trackers:
                self.tracker_combo.addItem(
                    self._tracker_combo_text(tracker), tracker.tracker_id
                )
            preferred_id = self._preferred_id(
                str(settings.default_tracker_id or ""),
                self._current_tracker.tracker_id if self._current_tracker else None,
            )
            index = self._combo_index_for_id(self.tracker_combo, preferred_id)
            if index < 0 and self.tracker_combo.count():
                index = 0
            self.tracker_combo.setCurrentIndex(index)
            self.tracker_combo.blockSignals(False)
            if index < 0:
                self._current_tracker = None
                self._set_available(True)
                self._set_workspace_status(
                    f"'{project.name}' 프로젝트에 조회 가능한 트래커가 없습니다.",
                    tone="warning",
                )
                self._reset_workspace("조회 가능한 트래커가 없습니다.")
                return
            self._current_tracker = self._trackers[index]
            self.hierarchy_panel.clear_baseline_cache()
            self.hierarchy_panel.reset_source()
            self._reset_baseline_state("Baseline 목록을 불러오는 중입니다.")
            self._set_available(True)
            self.search_panel.update_scope()
            self._set_workspace_status(
                f"'{self._current_tracker.name}' 트래커의 최상위 아이템을 조회합니다."
            )
            self.hierarchy_panel.load_roots()
            self._refresh_baseline_comparison()
            if self.search_panel.search_mode_combo.currentData() == TrackerSearchMode.CONDITIONS.value:
                self.search_panel.load_schema()

        def failed(exc: Exception) -> None:
            self._trackers = ()
            self.tracker_combo.clear()
            self._current_tracker = None
            self._set_available(True)
            self._show_error(exc, prefix="트래커 조회 실패")
            self._reset_workspace("트래커를 불러오지 못했습니다.")

        self._submit(
            "trackers",
            lambda: self.service.load_trackers(
                settings,
                project.project_id,
                project_name=project.name,
            ),
            loaded,
            failed,
        )

    def _on_tracker_activated(self, index: int) -> None:
        if not (0 <= int(index) < len(self._trackers)):
            return
        tracker = self._trackers[int(index)]
        if self._current_tracker == tracker:
            return
        self._current_tracker = tracker
        self.hierarchy_panel.clear_baseline_cache()
        self.hierarchy_panel.reset_source()
        self._reset_baseline_state("Baseline 목록을 불러오는 중입니다.")
        self.search_panel.reset_results("상세 검색 필드 정보를 불러오는 중입니다.")
        self.detail_panel.reset_detail()
        self.search_panel.update_scope()
        self._set_available(True)
        self.hierarchy_panel.load_roots()
        if self.search_panel.search_mode_combo.currentData() == TrackerSearchMode.CONDITIONS.value:
            self.search_panel.load_schema()
        self._refresh_baseline_comparison()



    def _is_historical_read_only(self) -> bool:
        return (
            self.detail_panel.baseline_id is not None
            or self.hierarchy_panel.selected_baseline_id() is not None
        )



    @staticmethod
    def _tracker_combo_text(tracker: TrackerSummary) -> str:
        type_name = str(tracker.type_name or "").strip()
        suffix = ""
        if type_name and type_name.casefold() not in {
            "tracker",
            "trackerreference",
        }:
            suffix = f" · {type_name}"
        return f"{tracker.name}  ·  {tracker.tracker_id}{suffix}"


























    def _reload_current_detail(self) -> None:
        selected_item_id = self.detail_panel.selected_item_id
        if selected_item_id is not None:
            self.content_service.clear_item_cache(
                self.settings_provider(),
                selected_item_id,
            )
            self.context_service.clear_item_cache(
                self.settings_provider(),
                selected_item_id,
            )
            self.comment_service.clear_item_cache(
                self.settings_provider(),
                selected_item_id,
            )
            self.detail_panel.load_detail(
                selected_item_id,
                baseline_id=self.detail_panel.baseline_id,
            )

    def _create_item(self) -> None:
        if self.hierarchy_panel.selected_baseline_id() is not None:
            self._set_workspace_status(
                "Baseline 조회 중에는 아이템을 생성할 수 없습니다.",
                tone="warning",
            )
            return
        tracker = self._current_tracker
        if tracker is None:
            self._set_workspace_status("생성할 트래커를 먼저 선택하세요.", tone="warning")
            return
        settings = self.settings_provider()
        if bool(settings.offline_mode):
            self._set_workspace_status(
                "테스트 모드에서는 새 아이템을 생성할 수 없습니다.",
                tone="warning",
            )
            return

        tracker_id = tracker.tracker_id
        current_detail = self.detail_panel.current_detail
        selected_detail = (
            current_detail
            if current_detail is not None
            and current_detail.summary.tracker_id == tracker_id
            else None
        )
        self._create_busy = True
        self._set_available(True)
        self._set_workspace_status(
            f"'{tracker.name}' 트래커의 생성 필드를 확인하는 중입니다.",
            tone="loading",
        )

        def schema_loaded(schema: EditableTrackerSchema) -> None:
            current_tracker = self._current_tracker
            if current_tracker is None or current_tracker.tracker_id != tracker_id:
                self._finish_create_busy()
                return
            try:
                request = (
                    self.create_request_provider(schema, current_tracker, selected_detail)
                    if self.create_request_provider is not None
                    else TrackerItemCreateDialog.request(
                        schema,
                        tracker_name=current_tracker.name,
                        selected_detail=selected_detail,
                        parent=self,
                    )
                )
            except Exception as exc:
                self._finish_create_busy()
                self._show_error(exc, prefix="생성 입력 준비 실패")
                return
            if request is None:
                self._finish_create_busy()
                self._set_workspace_status("새 아이템 생성을 취소했습니다.")
                return
            parent_detail = (
                selected_detail
                if selected_detail is not None
                and request.parent_item_id == selected_detail.item_id
                else None
            )
            requested_name = next(
                (
                    str(change.value or "").strip()
                    for change in request.changes
                    if change.field.tracker_item_field == "name"
                ),
                "",
            )
            self._set_workspace_status(
                f"'{current_tracker.name}' 트래커에 새 아이템을 생성하는 중입니다.",
                tone="loading",
            )

            def created(detail: TrackerItemDetail) -> None:
                self._finish_create_busy()
                self._record_item_activity(
                    ActivityOperation.TRACKER_CREATE,
                    ActivityResult.SUCCESS,
                    message=f"#{detail.item_id} 아이템을 생성했습니다.",
                    detail=detail,
                    parent_item_id=request.parent_item_id,
                    details={
                        "field_count": len(request.changes),
                        "position": (
                            "child" if request.parent_item_id is not None else "root"
                        ),
                    },
                )
                self.hierarchy_panel.show_created_item(
                    detail,
                    parent_item_id=request.parent_item_id,
                    parent_detail=parent_detail,
                )

            def create_failed(exc: Exception) -> None:
                self._finish_create_busy()
                result = (
                    ActivityResult.PARTIAL
                    if isinstance(exc, TrackerItemWriteError)
                    and exc.operation in {
                        "create_item_response",
                        "load_created_detail",
                    }
                    else ActivityResult.FAILED
                )
                self._record_item_activity(
                    ActivityOperation.TRACKER_CREATE,
                    result,
                    message=(
                        "아이템 생성 결과를 확인해야 합니다."
                        if result == ActivityResult.PARTIAL
                        else "아이템 생성에 실패했습니다."
                    ),
                    item_name=requested_name,
                    parent_item_id=request.parent_item_id,
                    details={"error": str(exc)},
                )
                prefix = (
                    "생성 결과 확인 필요"
                    if isinstance(exc, TrackerItemWriteError)
                    and exc.operation in {
                        "create_item_response",
                        "load_created_detail",
                    }
                    else "아이템 생성 실패"
                )
                self._show_error(exc, prefix=prefix)

            self._submit(
                "item_create",
                lambda: self.editor_service.create_item(
                    settings,
                    tracker_id=tracker_id,
                    schema=schema,
                    changes=request.changes,
                    parent_item_id=request.parent_item_id,
                ),
                created,
                create_failed,
            )

        def schema_failed(exc: Exception) -> None:
            self._finish_create_busy()
            self._show_error(exc, prefix="생성 schema 조회 실패")

        self._submit(
            "create_schema",
            lambda: self.editor_service.load_create_schema(settings, tracker_id),
            schema_loaded,
            schema_failed,
        )

    def _finish_create_busy(self) -> None:
        self._create_busy = False
        available, _ = self._settings_available(self.settings_provider())
        self._set_available(available)




    def _open_baseline_comparison(self) -> None:
        if self.workspace_mode_tabs.currentIndex() == self.baseline_mode_index:
            self._refresh_baseline_comparison()
        else:
            self.workspace_mode_tabs.setCurrentIndex(self.baseline_mode_index)

    def _on_workspace_mode_changed(self, index: int) -> None:
        if int(index) == self.baseline_mode_index:
            self._refresh_baseline_comparison()





    def _refresh_baseline_comparison(self, *, force: bool = False) -> None:
        tracker = self._current_tracker
        if tracker is None:
            self.baseline_workspace.set_error("비교할 트래커를 먼저 선택하세요.")
            return
        if not force and tracker.tracker_id in {
            self._baseline_loaded_tracker_id,
            self._baseline_loading_tracker_id,
        }:
            return
        settings = self.settings_provider()
        self._baseline_loading_tracker_id = tracker.tracker_id

        def loaded(baselines: tuple[TrackerBaseline, ...]) -> None:
            if self._current_tracker is not None and self._current_tracker.tracker_id == tracker.tracker_id:
                self._baseline_loading_tracker_id = None
                self._baseline_loaded_tracker_id = tracker.tracker_id
                self.hierarchy_panel.set_baselines(baselines)
                self.baseline_workspace.set_baselines(baselines)
                roots = self.hierarchy_panel.root_cache().get(tracker.tracker_id)
                if roots is not None:
                    self.baseline_workspace.render_roots(roots)

        def failed(exc: Exception) -> None:
            if self._baseline_loading_tracker_id == tracker.tracker_id:
                self._baseline_loading_tracker_id = None
            self.hierarchy_panel.set_baselines(())
            self.baseline_workspace.set_error(f"Baseline 목록 조회 실패: {exc}")
            self._show_error(exc, prefix="Baseline 목록 조회 실패")

        self._submit(
            "baseline_list",
            lambda: self.service.load_tracker_baselines(settings, tracker.tracker_id),
            loaded,
            failed,
        )





















    def _open_direct_item(self) -> None:
        raw_id = self.direct_id_input.text().strip()
        try:
            item_id = int(raw_id)
        except (TypeError, ValueError):
            item_id = 0
        if item_id <= 0:
            self._set_workspace_status("ID 바로 열기에는 양의 정수 아이템 ID가 필요합니다.", tone="warning")
            return
        settings = self.settings_provider()
        self.direct_open_button.setEnabled(False)
        self._set_workspace_status(
            f"#{item_id}의 프로젝트, 트래커와 계층 경로를 확인하는 중입니다.",
            tone="loading",
        )

        def resolve() -> DirectItemResult:
            context = self.service.resolve_item_context(settings, item_id)
            path = self.service.load_ancestor_path(settings, item_id)
            return DirectItemResult(context=context, ancestor_path=path)

        def loaded(result: DirectItemResult) -> None:
            self.direct_open_button.setEnabled(True)
            self._apply_direct_item_result(result)

        def failed(exc: Exception) -> None:
            self.direct_open_button.setEnabled(True)
            self._show_error(exc, prefix="ID 바로 열기 실패")

        self._submit("direct", resolve, loaded, failed)

    def _apply_direct_item_result(self, result: DirectItemResult) -> None:
        context = result.context
        project = self._project_for_context(context)
        tracker = self._tracker_for_context(context, project)
        previous_tracker_id = (
            self._current_tracker.tracker_id
            if self._current_tracker is not None
            else None
        )
        if project is not None:
            self._ensure_project_option(project)
        self._ensure_tracker_option(tracker)
        self._current_project = project
        self._current_tracker = tracker
        if previous_tracker_id != tracker.tracker_id:
            self.search_panel.reset_condition_search(
                "트래커가 변경되었습니다. 상세 검색 조건을 다시 설정하세요."
            )
            self._reset_baseline_state("Baseline 비교 기준을 다시 불러오세요.")
            self.hierarchy_panel.clear_baseline_cache()
            self.hierarchy_panel.reset_source()
        self.project_combo.setCurrentIndex(
            -1
            if project is None
            else self._combo_index_for_id(self.project_combo, project.project_id)
        )
        self.tracker_combo.setCurrentIndex(
            self._combo_index_for_id(self.tracker_combo, tracker.tracker_id)
        )
        self.search_panel.update_scope()
        self._set_available(True)
        self.browser_tabs.setCurrentIndex(0)
        self._render_ancestor_path(result.ancestor_path)
        self.detail_panel.show_detail(context.item)
        if previous_tracker_id != tracker.tracker_id:
            self._refresh_baseline_comparison()
        self._set_workspace_status(
            f"#{context.item.item_id}을(를) 직접 열고 소속 트래커와 조상 경로를 표시했습니다."
        )

    @staticmethod
    def _project_for_context(context: TrackerItemContext) -> ProjectSummary | None:
        project_id = context.project_id or context.item.summary.project_id
        if project_id is None:
            return None
        return ProjectSummary(
            project_id=int(project_id),
            name=context.project_name or context.item.summary.project_name or "프로젝트 정보 없음",
        )

    @staticmethod
    def _tracker_for_context(
        context: TrackerItemContext,
        project: ProjectSummary | None,
    ) -> TrackerSummary:
        return TrackerSummary(
            tracker_id=context.tracker_id,
            name=context.tracker_name or context.item.summary.tracker_name or str(context.tracker_id),
            project_id=project.project_id if project else context.project_id,
            project_name=project.name if project else context.project_name,
        )

    def _ensure_project_option(self, project: ProjectSummary) -> None:
        projects = list(self._projects)
        for index, existing in enumerate(projects):
            if existing.project_id == project.project_id:
                projects[index] = project
                break
        else:
            projects.append(project)
        self._projects = tuple(projects)
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for value in self._projects:
            self.project_combo.addItem(f"{value.name}  ·  {value.project_id}", value.project_id)
        self.project_combo.blockSignals(False)

    def _ensure_tracker_option(self, tracker: TrackerSummary) -> None:
        trackers = [
            existing
            for existing in self._trackers
            if existing.project_id in (None, tracker.project_id)
        ]
        for index, existing in enumerate(trackers):
            if existing.tracker_id == tracker.tracker_id:
                trackers[index] = tracker
                break
        else:
            trackers.append(tracker)
        self._trackers = tuple(trackers)
        self.tracker_combo.blockSignals(True)
        self.tracker_combo.clear()
        for value in self._trackers:
            self.tracker_combo.addItem(self._tracker_combo_text(value), value.tracker_id)
        self.tracker_combo.blockSignals(False)

    def _render_ancestor_path(self, path: tuple[TrackerItemSummary, ...]) -> None:
        self.hierarchy_panel.item_tree.blockSignals(True)
        self.hierarchy_panel.item_tree.clear()
        parent_item: QTreeWidgetItem | None = None
        target_item: QTreeWidgetItem | None = None
        for summary in path:
            tree_item = self.hierarchy_panel.tree_item(summary)
            tree_item.takeChildren()
            tree_item.setData(0, CHILDREN_LOADED_ROLE, True)
            if parent_item is None:
                self.hierarchy_panel.item_tree.addTopLevelItem(tree_item)
            else:
                parent_item.addChild(tree_item)
                parent_item.setExpanded(True)
            parent_item = tree_item
            target_item = tree_item
        if target_item is not None:
            target_item.setSelected(True)
            self.hierarchy_panel.item_tree.scrollToItem(target_item)
        self.hierarchy_panel.item_tree.blockSignals(False)
        self.hierarchy_panel.tree_status_label.setText(
            f"ID 직접 접근 경로 · {len(path)}단계 · 전체 형제 노드는 '최상위 다시 불러오기'로 조회"
        )































    def _invalidate_tracker_cache(self, tracker_id: int) -> None:
        self.hierarchy_panel.root_cache().pop(int(tracker_id), None)
        self.hierarchy_panel.child_cache().clear()

    def _refresh_visible_item(self, detail: TrackerItemDetail) -> None:
        summary = detail.summary
        if summary.tracker_id is not None:
            self._invalidate_tracker_cache(summary.tracker_id)

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

        for top_index in range(self.hierarchy_panel.item_tree.topLevelItemCount()):
            update_tree_item(self.hierarchy_panel.item_tree.topLevelItem(top_index))

        self.search_panel.refresh_item(detail)

    def _remove_visible_item(self, item_id: int) -> None:
        def remove_from(parent: QTreeWidgetItem | None) -> bool:
            count = self.hierarchy_panel.item_tree.topLevelItemCount() if parent is None else parent.childCount()
            for index in range(count - 1, -1, -1):
                item = (
                    self.hierarchy_panel.item_tree.topLevelItem(index)
                    if parent is None
                    else parent.child(index)
                )
                if item is None:
                    continue
                summary = item.data(0, ITEM_SUMMARY_ROLE)
                if isinstance(summary, TrackerItemSummary) and summary.item_id == int(item_id):
                    if parent is None:
                        self.hierarchy_panel.item_tree.takeTopLevelItem(index)
                    else:
                        parent.takeChild(index)
                    return True
                if remove_from(item):
                    return True
            return False

        remove_from(None)
        self.search_panel.remove_item(item_id)

    def shutdown(self) -> None:
        """창 종료 뒤 완료되는 요청이 화면 상태를 갱신하지 않도록 무효화한다."""
        self.detail_panel.shutdown()
        self._invalidate_requests()
        for task in tuple(self._tasks):
            try:
                task.completed.disconnect()
                task.failed.disconnect()
            except Exception:
                pass


__all__ = [
    "CHILDREN_LOADED_ROLE",
    "DEFAULT_SEARCH_PAGE_SIZE",
    "HIERARCHY_FETCH_PAGE_SIZE",
    "ITEM_SUMMARY_ROLE",
    "PLACEHOLDER_ROLE",
    "REQUEST_BUSY_MESSAGES",
    "TrackerWorkspacePage",
]
