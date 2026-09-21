"""트래커 작업공간의 상세 영역을 맡는 자식 위젯.

아이템 상세 표시, 설명 렌더링, 첨부와 인라인 이미지, 수정 탭을 모두 들고 있다.
위젯도 여기서 만들기 때문에 작업공간 화면은 상세 위젯을 직접 들고 있지 않다.

작업공간과는 두 방향으로만 이어진다.

- 작업공간 -> panel: `load_detail`, `render_detail`, `reset_detail`
- panel -> 작업공간: `DetailPanelHost` 의 콜백

조회 로직은 각 service 에 있고 여기는 화면 조립만 한다.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtWidgets import QFrame
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPlainTextEdit
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtWidgets import QTabWidget
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .activity_history import ActivityOperation
from .activity_history import ActivityResult
from .settings_store import GuiSettings
from .tracker_content_models import ATTACHMENT_IMAGE_MIME_TYPES
from .tracker_content_models import ATTACHMENT_IMAGE_SUFFIXES
from .tracker_content_models import AttachmentResource
from .tracker_content_models import AttachmentSummary
from .tracker_content_models import WikiRenderContext
from .tracker_content_models import WikiRenderResult
from .tracker_content_models import WikiResourceReference
from .tracker_content_service import MAX_INLINE_IMAGE_BYTES
from .tracker_content_service import MAX_ITEM_INLINE_IMAGE_BYTES
from .tracker_item_editor import EditableTrackerField
from .tracker_item_editor import TrackerItemFieldChange
from .tracker_item_editor_dialog import TrackerItemEditorDialog
from .tracker_item_editor_panel import ConfirmItemDeleteDialog
from .tracker_item_editor_panel import TrackerItemEditorPanel
from .tracker_query_models import TrackerFieldValue
from .tracker_query_models import TrackerItemDetail
from .tracker_table_field_dialog import TrackerTableFieldDialog
from .tracker_table_field_dialog import is_table_field
from .tracker_table_field_dialog import table_field_summary
from .wiki_content_view import WikiContentDialog
from .wiki_content_view import WikiContentView
from .wiki_renderer import codebeamer_wiki_to_html
from .wiki_renderer import is_explicit_wiki_type
from .wiki_renderer import payload_uses_wiki


@dataclass(frozen=True)
class DetailPanelHost:
    """상세 영역이 작업공간 화면에 되돌려주는 일.

    상태 표시, 트리·검색 표 갱신, 요청 실행처럼 상세 영역 밖을 건드리는 동작이다.
    콜백으로 받아 두면 상세 영역이 화면 전체를 알 필요가 없다.
    """

    submit: Callable[..., int]
    show_error: Callable[..., None]
    set_workspace_status: Callable[..., None]
    record_item_activity: Callable[..., None]
    refresh_visible_item: Callable[[TrackerItemDetail], None]
    remove_visible_item: Callable[[int], None]
    invalidate_tracker_cache: Callable[[int], None]
    is_historical_read_only: Callable[[], bool]
    selected_hierarchy_baseline_id: Callable[[], int | None]
    reload_current_detail: Callable[[], None]
    open_detail_dialog: Callable[[], None]
    set_editor_expanded: Callable[[bool], None]


class TrackerDetailPanel(QFrame):
    """아이템 상세 표시와 수정을 맡는 영역."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        host: DetailPanelHost,
        settings_provider: Callable[[], GuiSettings],
        service: Any,
        content_service: Any,
        editor_service: Any,
        delete_confirmer: Callable[[TrackerItemDetail], bool] | None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self.settings_provider = settings_provider
        self.service = service
        self.content_service = content_service
        self.editor_service = editor_service
        self.delete_confirmer = delete_confirmer

        self._current_detail: TrackerItemDetail | None = None
        self._selected_item_id: int | None = None
        self._detail_baseline_id: int | None = None
        self._description_text = ""
        self._description_uses_wiki = False
        self._description_render_result: WikiRenderResult | None = None
        self._attachments: tuple[AttachmentSummary, ...] = ()
        self._attachment_preview_resources: dict[str, AttachmentResource] = {}
        self._inline_image_bytes = 0
        self._inline_resource_reservations: set[tuple[Any, ...]] = set()
        self._loaded_inline_resources: set[tuple[Any, ...]] = set()
        self._wiki_resource_generation = 0
        self._editor_dialog: TrackerItemEditorDialog | None = None

        self.setObjectName("tracker_workspace_panel")
        self.setMinimumWidth(300)
        detail_layout = QVBoxLayout(self)
        detail_layout.setContentsMargins(12, 10, 12, 10)
        detail_layout.setSpacing(8)

        detail_heading = QHBoxLayout()
        self.detail_title = QLabel("아이템 상세")
        self.detail_title.setObjectName("tracker_detail_title")
        detail_heading.addWidget(self.detail_title, 1)
        self.detail_open_button = QPushButton("상세 크게 보기", self)
        self.detail_open_button.setEnabled(False)
        self.detail_open_button.clicked.connect(self._host.open_detail_dialog)
        detail_heading.addWidget(self.detail_open_button)
        self.detail_refresh_button = QPushButton("상세 새로고침", self)
        self.detail_refresh_button.setToolTip("현재 아이템의 최신 version과 필드를 다시 조회합니다.")
        self.detail_refresh_button.clicked.connect(self._host.reload_current_detail)
        self.detail_refresh_button.setEnabled(False)
        detail_heading.addWidget(self.detail_refresh_button)
        self.detail_id_badge = QPushButton("", self)
        self.detail_id_badge.setObjectName("tracker_id_copy_button")
        self.detail_id_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_id_badge.setToolTip("클릭하면 아이템 ID 숫자만 복사합니다.")
        self.detail_id_badge.setAccessibleName("아이템 ID 복사")
        self.detail_id_badge.clicked.connect(self._copy_selected_item_id)
        self.detail_id_badge.hide()
        detail_heading.addWidget(self.detail_id_badge)
        detail_layout.addLayout(detail_heading)

        self.detail_breadcrumb = QLabel("선택한 아이템이 없습니다.")
        self.detail_breadcrumb.setObjectName("tracker_detail_breadcrumb")
        self.detail_breadcrumb.setWordWrap(True)
        detail_layout.addWidget(self.detail_breadcrumb)

        self.detail_warning = QLabel("")
        self.detail_warning.setObjectName("tracker_detail_warning")
        self.detail_warning.setWordWrap(True)
        self.detail_warning.hide()
        detail_layout.addWidget(self.detail_warning)

        self.detail_tabs = QTabWidget(self)
        self.detail_tabs.setObjectName("tracker_detail_tabs")
        self.detail_tabs.addTab(self._build_overview_tab(), "개요")
        self.detail_tabs.addTab(self._build_raw_tab(), "원본 JSON")

        self.editor_host = QWidget(self.detail_tabs)
        self.editor_host.setObjectName("tracker_item_editor_host")
        self.editor_host_layout = QVBoxLayout(self.editor_host)
        self.editor_host_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_host_layout.setSpacing(6)
        editor_toolbar = QHBoxLayout()
        editor_toolbar.addStretch(1)
        self.popout_editor_button = QPushButton(
            "새 창에서 크게 수정",
            self.editor_host,
        )
        self.popout_editor_button.clicked.connect(self._show_editor_in_window)
        editor_toolbar.addWidget(self.popout_editor_button)
        self.editor_host_layout.addLayout(editor_toolbar)
        self.editor_placeholder = QLabel(
            "수정 화면이 새 창에 열려 있습니다.",
            self.editor_host,
        )
        self.editor_placeholder.setObjectName("tracker_panel_status")
        self.editor_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.editor_placeholder.hide()
        self.editor_host_layout.addWidget(self.editor_placeholder, 1)
        self.editor_panel = TrackerItemEditorPanel(
            save_requested=self._save_item_changes,
            transition_requested=self._transition_item_status,
            delete_requested=self._delete_current_item,
            parent=self.editor_host,
        )
        self.editor_host_layout.addWidget(self.editor_panel, 1)
        self.editor_tab_index = self.detail_tabs.addTab(self.editor_host, "수정")
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
        detail_layout.addWidget(self.detail_tabs, 1)



    @property
    def current_detail(self) -> TrackerItemDetail | None:
        """지금 보고 있는 아이템. 상세 창이 같은 아이템을 연다."""
        return self._current_detail

    @property
    def attachments(self) -> tuple[AttachmentSummary, ...]:
        return self._attachments

    @property
    def preview_resources(self) -> tuple[AttachmentResource, ...]:
        return tuple(self._attachment_preview_resources.values())

    @property
    def baseline_id(self) -> int | None:
        return self._detail_baseline_id

    @property
    def selected_item_id(self) -> int | None:
        """마지막으로 고른 아이템. 다시 조회할 때 쓴다."""
        return self._selected_item_id

    def show_detail(self, detail: TrackerItemDetail) -> None:
        """다른 화면에서 연 아이템을 개요 탭에 바로 띄운다."""
        self.detail_tabs.setCurrentIndex(0)
        self._selected_item_id = detail.item_id
        self.render_detail(detail)

    def set_historical_read_only(self, historical: bool) -> None:
        """Baseline 상세는 읽기 전용이라 수정 탭을 잠근다."""
        self.detail_tabs.setTabEnabled(self.editor_tab_index, not historical)
        self.popout_editor_button.setEnabled(not historical)
        if historical and self._editor_dialog is not None:
            self._editor_dialog.close()

    def shutdown(self) -> None:
        """화면을 닫을 때 분리해 둔 수정 창을 함께 닫는다."""
        if self._editor_dialog is not None:
            self._editor_dialog.close()

    def _copy_selected_item_id(self) -> None:
        item_id = self._selected_item_id
        if item_id is None:
            return
        clipboard_text = str(int(item_id))
        QApplication.clipboard().setText(clipboard_text)
        self.detail_id_badge.setToolTip(f"ID {clipboard_text} 복사 완료")
        self._host.set_workspace_status(
            f"아이템 ID {clipboard_text}가 클립보드에 복사되었습니다."
        )

    def description_html(self) -> str:
        """상세 창에 넘길 설명 HTML 을 만든다.

        Wiki 인지 평문인지는 여기서만 알면 된다.
        """
        if self._description_uses_wiki:
            if self._description_render_result is not None:
                return self._description_render_result.html
            return codebeamer_wiki_to_html(self._description_text)
        return "<p>" + escape(self._description_text).replace("\n", "<br>") + "</p>"

    def _build_overview_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)
        description_header = QHBoxLayout()
        description_label = QLabel("설명")
        description_label.setObjectName("tracker_detail_section_title")
        description_header.addWidget(description_label, 1)
        self.description_source_toggle = QPushButton("Wiki 원문", tab)
        self.description_source_toggle.setObjectName("mode_toggle")
        self.description_source_toggle.setCheckable(True)
        self.description_source_toggle.setVisible(False)
        self.description_source_toggle.toggled.connect(self._render_description)
        description_header.addWidget(self.description_source_toggle)
        layout.addLayout(description_header)
        self.detail_description = WikiContentView(tab)
        self.detail_description.setObjectName("tracker_detail_description")
        self.detail_description.setReadOnly(True)
        self.detail_description.setOpenExternalLinks(False)
        self.detail_description.setPlaceholderText("아이템을 선택하면 설명을 표시합니다.")
        self.detail_description.setMaximumHeight(150)
        layout.addWidget(self.detail_description)

        attachment_header = QHBoxLayout()
        attachment_label = QLabel("첨부 파일")
        attachment_label.setObjectName("tracker_detail_section_title")
        attachment_header.addWidget(attachment_label, 1)
        self.attachment_reload_button = QPushButton("첨부 불러오기", tab)
        self.attachment_reload_button.setObjectName("tracker_attachment_reload")
        self.attachment_reload_button.setEnabled(False)
        self.attachment_reload_button.clicked.connect(self._load_attachments)
        attachment_header.addWidget(self.attachment_reload_button)
        self.attachment_preview_button = QPushButton("이미지 크게 보기", tab)
        self.attachment_preview_button.setObjectName("tracker_attachment_preview_open")
        self.attachment_preview_button.setEnabled(False)
        self.attachment_preview_button.setVisible(False)
        self.attachment_preview_button.clicked.connect(self._open_attachment_preview)
        attachment_header.addWidget(self.attachment_preview_button)
        layout.addLayout(attachment_header)
        self.attachment_status_label = QLabel("아이템을 선택하면 첨부를 확인할 수 있습니다.", tab)
        self.attachment_status_label.setWordWrap(True)
        layout.addWidget(self.attachment_status_label)
        self.attachment_preview = WikiContentView(tab)
        self.attachment_preview.setObjectName("tracker_attachment_preview")
        self.attachment_preview.setReadOnly(True)
        self.attachment_preview.setOpenExternalLinks(False)
        self.attachment_preview.setMaximumHeight(260)
        self.attachment_preview.setVisible(False)
        layout.addWidget(self.attachment_preview)
        self.attachment_table = QTableWidget(0, 4, tab)
        self.attachment_table.setObjectName("tracker_attachment_table")
        self.attachment_table.setHorizontalHeaderLabels(["파일명", "크기", "수정 시각", "작업"])
        self.attachment_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attachment_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.attachment_table.verticalHeader().setVisible(False)
        self.attachment_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.attachment_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.attachment_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.attachment_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.attachment_table.setMaximumHeight(150)
        layout.addWidget(self.attachment_table)

        fields_label = QLabel("필드")
        fields_label.setObjectName("tracker_detail_section_title")
        layout.addWidget(fields_label)
        self.detail_fields_table = QTableWidget(0, 3, tab)
        self.detail_fields_table.setObjectName("tracker_detail_fields")
        self.detail_fields_table.setHorizontalHeaderLabels(["필드", "값", "유형"])
        self.detail_fields_table.setAlternatingRowColors(True)
        self.detail_fields_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.detail_fields_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.detail_fields_table.verticalHeader().setVisible(False)
        self.detail_fields_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.detail_fields_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.detail_fields_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.detail_fields_table, 1)
        return tab


    def _build_raw_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 8, 6, 6)
        self.detail_raw_json = QPlainTextEdit(tab)
        self.detail_raw_json.setObjectName("tracker_detail_raw_json")
        self.detail_raw_json.setReadOnly(True)
        self.detail_raw_json.setPlaceholderText(
            "민감한 키가 마스킹된 Codebeamer 응답을 표시합니다."
        )
        layout.addWidget(self.detail_raw_json)
        return tab


    def _show_detail_id_badge(self, item_id: int) -> None:
        normalized_id = int(item_id)
        self.detail_id_badge.setText(f"#{normalized_id}")
        self.detail_id_badge.setToolTip(
            f"클릭하면 아이템 ID {normalized_id} 숫자만 복사합니다."
        )
        self.detail_id_badge.show()

    def load_detail(
        self,
        item_id: int,
        *,
        baseline_id: int | None = None,
    ) -> None:
        normalized_id = int(item_id)
        normalized_baseline_id = None if baseline_id is None else int(baseline_id)
        self._selected_item_id = normalized_id
        self._detail_baseline_id = normalized_baseline_id
        settings = self.settings_provider()
        self.detail_title.setText(
            "Baseline 아이템 상세를 불러오는 중입니다."
            if normalized_baseline_id is not None
            else "아이템 상세를 불러오는 중입니다."
        )
        self.detail_refresh_button.setEnabled(False)
        self._show_detail_id_badge(normalized_id)

        def loaded(detail: TrackerItemDetail) -> None:
            if (
                self._selected_item_id != normalized_id
                or self._detail_baseline_id != normalized_baseline_id
            ):
                return
            self.render_detail(detail, baseline_id=normalized_baseline_id)

        def failed(exc: Exception) -> None:
            if (
                self._selected_item_id != normalized_id
                or self._detail_baseline_id != normalized_baseline_id
            ):
                return
            self.detail_title.setText("아이템 상세")
            self.detail_refresh_button.setEnabled(True)
            self.detail_breadcrumb.setText(f"#{normalized_id} 상세를 불러오지 못했습니다.")
            self._host.show_error(exc, prefix="상세 조회 실패")

        self._host.submit(
            "detail",
            lambda: (
                self.service.load_detail(settings, normalized_id)
                if normalized_baseline_id is None
                else self.service.load_detail(
                    settings,
                    normalized_id,
                    baseline_id=normalized_baseline_id,
                )
            ),
            loaded,
            failed,
        )

    def _render_description(self, show_source: bool = False) -> None:
        self.description_source_toggle.setText(
            "렌더링 보기" if show_source else "Wiki 원문"
        )
        if self._description_uses_wiki and not show_source:
            if self._description_render_result is not None:
                self.detail_description.set_render_result(self._description_render_result)
                if self._current_detail is not None:
                    self._load_inline_resources(
                        self._description_render_result,
                        self.detail_description,
                        self._current_detail,
                        self._detail_baseline_id,
                    )
            else:
                self.detail_description.setHtml(codebeamer_wiki_to_html(self._description_text))
            return
        self.detail_description.setPlainText(self._description_text)

    @staticmethod
    def wiki_context(
        detail: TrackerItemDetail,
        baseline_id: int | None,
    ) -> WikiRenderContext | None:
        if detail.summary.project_id is None or detail.version is None:
            return None
        return WikiRenderContext(
            project_id=int(detail.summary.project_id),
            item_id=detail.item_id,
            item_version=int(detail.version),
            baseline_id=baseline_id,
        )

    def _request_description_render(
        self,
        detail: TrackerItemDetail,
        baseline_id: int | None,
    ) -> None:
        if not self._description_uses_wiki:
            return
        settings = self.settings_provider()
        item_id = detail.item_id
        version = detail.version
        context = self.wiki_context(detail, baseline_id)

        def loaded(result: WikiRenderResult) -> None:
            current = self._current_detail
            if (
                current is None
                or current.item_id != item_id
                or current.version != version
                or self._detail_baseline_id != baseline_id
            ):
                return
            self._description_render_result = result
            if not self.description_source_toggle.isChecked():
                self.detail_description.set_render_result(result)
                self._load_inline_resources(result, self.detail_description, detail, baseline_id)
            if result.warning:
                existing = self.detail_warning.text().strip()
                lines = [line for line in (existing, result.warning) if line]
                self.detail_warning.setText("\n".join(lines))
                self.detail_warning.show()

        self._host.submit(
            "wiki_description",
            lambda: self.content_service.render_wiki(
                settings,
                context,
                self._description_text,
            ),
            loaded,
            lambda _exc: None,
        )

    def _load_inline_resources(
        self,
        result: WikiRenderResult,
        view: WikiContentView,
        detail: TrackerItemDetail,
        baseline_id: int | None,
    ) -> None:
        if baseline_id is not None:
            return
        settings = self.settings_provider()
        item_id = detail.item_id
        version = detail.version
        for reference in result.resources:
            if (
                self._inline_image_bytes
                + len(self._inline_resource_reservations) * MAX_INLINE_IMAGE_BYTES
                + MAX_INLINE_IMAGE_BYTES
                > MAX_ITEM_INLINE_IMAGE_BYTES
            ):
                break
            reservation = (
                self._wiki_resource_generation,
                reference.resource_key,
                id(view),
            )
            if reservation in self._loaded_inline_resources:
                continue
            if reservation in self._inline_resource_reservations:
                continue
            self._inline_resource_reservations.add(reservation)

            def loaded(
                resource,
                *,
                target=view,
                expected_id=item_id,
                expected_version=version,
                reserved=reservation,
            ) -> None:
                self._inline_resource_reservations.discard(reserved)
                current = self._current_detail
                if current is None or current.item_id != expected_id or current.version != expected_version:
                    return
                if self._inline_image_bytes + len(resource.data) > MAX_ITEM_INLINE_IMAGE_BYTES:
                    return
                if target.add_attachment_resource(resource):
                    self._inline_image_bytes += len(resource.data)
                    self._loaded_inline_resources.add(reserved)

            def failed(_exc: Exception, *, reserved=reservation) -> None:
                self._inline_resource_reservations.discard(reserved)

            def download(selected: WikiResourceReference = reference) -> AttachmentResource:
                return self.content_service.download_resource(
                    settings,
                    resource_key=selected.resource_key,
                    source_url=selected.source_url,
                )

            self._host.submit(
                (
                    f"wiki_resource:{reservation[0]}:"
                    f"{reservation[2]}:{reference.resource_key}"
                ),
                download,
                loaded,
                failed,
            )

    def _open_wiki_field(self, field: TrackerFieldValue) -> None:
        detail = self._current_detail
        if detail is None:
            return
        settings = self.settings_provider()
        item_id = detail.item_id
        version = detail.version
        baseline_id = self._detail_baseline_id
        context = self.wiki_context(detail, baseline_id)

        def loaded(result: WikiRenderResult) -> None:
            current = self._current_detail
            if current is None or current.item_id != item_id or current.version != version:
                return
            dialog = WikiContentDialog(field.name, field.display_value, result, self)
            self._load_inline_resources(result, dialog.view, detail, baseline_id)
            dialog.exec()

        self._host.submit(
            f"wiki_field:{field.field_id or field.name}",
            lambda: self.content_service.render_wiki(settings, context, field.display_value),
            loaded,
            lambda exc: self._host.show_error(exc, prefix="Wiki 필드 렌더링 실패"),
        )

    def _open_table_field(self, field: TrackerFieldValue) -> None:
        detail = self._current_detail
        if detail is None:
            return
        settings = self.settings_provider()
        context = self.wiki_context(detail, self._detail_baseline_id)
        request_index = 0

        def request(markup: str, completed: Callable[[WikiRenderResult], None]) -> None:
            nonlocal request_index
            request_index += 1
            def render() -> WikiRenderResult:
                return self.content_service.render_wiki(settings, context, markup)

            def render_failed(_exc: Exception) -> None:
                completed(
                    WikiRenderResult(
                        html=codebeamer_wiki_to_html(markup),
                        used_fallback=True,
                        warning="서버 Wiki 렌더링에 실패했습니다.",
                    )
                )

            self._host.submit(
                f"wiki_table:{detail.item_id}:{request_index}",
                render,
                completed,
                render_failed,
            )

        dialog = TrackerTableFieldDialog(
            field,
            self,
            wiki_render_request=request,
            wiki_resource_loader=lambda result, view: self._load_inline_resources(
                result,
                view,
                detail,
                self._detail_baseline_id,
            ),
        )
        dialog.exec()

    @staticmethod
    def _attachment_size_text(size: int | None) -> str:
        if size is None:
            return "-"
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _load_attachments(self, _checked: bool = False) -> None:
        detail = self._current_detail
        if detail is None:
            return
        if self._detail_baseline_id is not None:
            self.attachment_status_label.setText(
                "과거 첨부 revision 계약이 확인되지 않아 Baseline 첨부 목록은 표시하지 않습니다."
            )
            self.attachment_table.setRowCount(0)
            return
        settings = self.settings_provider()
        item_id = detail.item_id
        version = detail.version
        self.attachment_reload_button.setEnabled(False)
        self.attachment_status_label.setText("첨부 파일을 불러오는 중입니다.")

        def loaded(attachments: tuple[AttachmentSummary, ...]) -> None:
            current = self._current_detail
            if current is None or current.item_id != item_id or current.version != version:
                return
            previews_need_refresh = attachments != self._attachments
            self._attachments = attachments
            self.attachment_reload_button.setEnabled(True)
            if previews_need_refresh:
                self._load_attachment_previews(attachments, detail)
            self.attachment_table.setRowCount(len(attachments))
            for row, attachment in enumerate(attachments):
                self.attachment_table.setItem(row, 0, QTableWidgetItem(attachment.name))
                self.attachment_table.setItem(row, 1, QTableWidgetItem(self._attachment_size_text(attachment.size)))
                self.attachment_table.setItem(row, 2, QTableWidgetItem(attachment.modified_at or "-"))
                save_button = QPushButton("저장", self.attachment_table)
                save_button.clicked.connect(
                    lambda _checked=False, selected=attachment: self.save_attachment(selected)
                )
                self.attachment_table.setCellWidget(row, 3, save_button)
            self.attachment_status_label.setText(
                f"첨부 파일 {len(attachments)}개" if attachments else "첨부 파일이 없습니다."
            )

        def failed(exc: Exception) -> None:
            current = self._current_detail
            if current is None or current.item_id != item_id:
                return
            self.attachment_reload_button.setEnabled(True)
            self.attachment_status_label.setText("첨부 목록을 불러오지 못했습니다.")
            self._host.show_error(exc, prefix="첨부 목록 조회 실패")

        self._host.submit(
            "attachments",
            lambda: self.content_service.load_attachments(
                settings,
                item_id,
                raw_payload=detail.raw_payload,
            ),
            loaded,
            failed,
        )

    @staticmethod
    def is_attachment_image(attachment: AttachmentSummary) -> bool:
        mime_type = str(attachment.mime_type or "").split(";", 1)[0].strip().casefold()
        if mime_type:
            return mime_type in ATTACHMENT_IMAGE_MIME_TYPES
        return str(attachment.name or "").strip().casefold().endswith(
            ATTACHMENT_IMAGE_SUFFIXES
        )

    def _load_attachment_previews(
        self,
        attachments: tuple[AttachmentSummary, ...],
        detail: TrackerItemDetail,
    ) -> None:
        settings = self.settings_provider()
        if bool(settings.offline_mode) or self._detail_baseline_id is not None:
            self._attachment_preview_resources.clear()
            self.attachment_preview_button.setEnabled(False)
            self.attachment_preview_button.setVisible(False)
            self.attachment_preview.clear()
            self.attachment_preview.setVisible(False)
            return
        available_slots = max(
            (
                MAX_ITEM_INLINE_IMAGE_BYTES
                - self._inline_image_bytes
                - len(self._inline_resource_reservations) * MAX_INLINE_IMAGE_BYTES
            )
            // MAX_INLINE_IMAGE_BYTES,
            0,
        )
        candidates = [
            attachment
            for attachment in attachments
            if self.is_attachment_image(attachment)
            and (attachment.size is None or attachment.size <= MAX_INLINE_IMAGE_BYTES)
        ][:available_slots]
        if not candidates:
            self._attachment_preview_resources.clear()
            self.attachment_preview_button.setEnabled(False)
            self.attachment_preview_button.setVisible(False)
            self.attachment_preview.clear()
            self.attachment_preview.setVisible(False)
            return

        blocks = []
        for attachment in candidates:
            resource_key = f"attachment-{attachment.attachment_id}"
            blocks.append(
                "<p><b>"
                f"{escape(attachment.name)}"
                "</b><br>"
                f'<img src="cb-attachment://{resource_key}" alt="{escape(attachment.name)}">'
                "</p>"
            )
        self._attachment_preview_resources.clear()
        self.attachment_preview_button.setEnabled(False)
        self.attachment_preview_button.setVisible(True)
        self.attachment_preview.setHtml("".join(blocks))
        self.attachment_preview.setVisible(True)
        item_id = detail.item_id
        version = detail.version

        for attachment in candidates:
            reservation = (
                self._wiki_resource_generation,
                f"attachment-{attachment.attachment_id}",
                id(self.attachment_preview),
            )
            if reservation in self._loaded_inline_resources:
                continue
            if reservation in self._inline_resource_reservations:
                continue
            self._inline_resource_reservations.add(reservation)

            def loaded(resource, *, reserved=reservation) -> None:
                self._inline_resource_reservations.discard(reserved)
                current = self._current_detail
                if current is None or current.item_id != item_id or current.version != version:
                    return
                if self._inline_image_bytes + len(resource.data) > MAX_ITEM_INLINE_IMAGE_BYTES:
                    return
                if self.attachment_preview.add_attachment_resource(resource):
                    self._inline_image_bytes += len(resource.data)
                    self._loaded_inline_resources.add(reserved)
                    self._attachment_preview_resources[resource.resource_key] = resource
                    self.attachment_preview_button.setEnabled(True)

            def failed(_exc: Exception, *, reserved=reservation) -> None:
                self._inline_resource_reservations.discard(reserved)

            def download_preview(selected: AttachmentSummary = attachment) -> AttachmentResource:
                return self.content_service.download_attachment(
                    settings,
                    selected,
                    max_bytes=MAX_INLINE_IMAGE_BYTES,
                )

            self._host.submit(
                f"attachment_preview:{self._wiki_resource_generation}:{attachment.attachment_id}",
                download_preview,
                loaded,
                failed,
            )

    def _open_attachment_preview(self, _checked: bool = False) -> None:
        if not self._attachment_preview_resources:
            return
        result = WikiRenderResult(html=self.attachment_preview.text())
        dialog = WikiContentDialog("첨부 이미지", "", result, self)
        dialog.resize(1100, 760)
        for resource in self._attachment_preview_resources.values():
            dialog.view.add_attachment_resource(resource)
        dialog.exec()

    def save_attachment(self, attachment: AttachmentSummary) -> None:
        output_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "첨부 파일 저장",
            attachment.name,
            "모든 파일 (*)",
        )
        if not output_path:
            return
        settings = self.settings_provider()
        item_id = self._selected_item_id
        self.attachment_status_label.setText(f"{attachment.name} 저장 중입니다.")

        def completed(byte_count: int) -> None:
            if self._selected_item_id != item_id:
                return
            self.attachment_status_label.setText(
                f"{attachment.name} 저장 완료 · {self._attachment_size_text(byte_count)}"
            )

        self._host.submit(
            f"attachment_save:{attachment.attachment_id}",
            lambda: self.content_service.save_attachment(
                settings,
                attachment,
                output_path,
            ),
            completed,
            lambda exc: self._host.show_error(exc, prefix="첨부 파일 저장 실패"),
        )

    def render_detail(
        self,
        detail: TrackerItemDetail,
        *,
        baseline_id: int | None = None,
    ) -> None:
        summary = detail.summary
        historical = baseline_id is not None
        write_locked = historical or self._host.selected_hierarchy_baseline_id() is not None
        previous_editor_detail = self.editor_panel.detail
        self._current_detail = detail
        self._selected_item_id = detail.item_id
        self._detail_baseline_id = baseline_id
        self._update_detached_editor_title(detail)
        self.detail_title.setText(
            f"{summary.name} · Baseline"
            if historical
            else summary.name
        )
        self.detail_refresh_button.setEnabled(True)
        self.detail_open_button.setEnabled(True)
        self.detail_refresh_button.setToolTip(
            "선택한 Baseline 시점의 아이템 상세를 다시 조회합니다."
            if historical
            else "현재 아이템의 최신 version과 필드를 다시 조회합니다."
        )
        self._show_detail_id_badge(detail.item_id)
        breadcrumb_parts = [
            summary.project_name or "프로젝트 정보 없음",
            summary.tracker_name or "트래커 정보 없음",
        ]
        if detail.parent is not None:
            breadcrumb_parts.append(f"상위 #{detail.parent.item_id}")
        if historical:
            breadcrumb_parts.append(f"Baseline #{baseline_id}")
        self.detail_breadcrumb.setText("  ›  ".join(breadcrumb_parts))
        warning_lines = list(detail.warnings)
        if historical:
            warning_lines.insert(
                0,
                f"읽기 전용 · Baseline #{baseline_id} 시점의 상세입니다.",
            )
        warnings = "\n".join(warning_lines)
        self.detail_warning.setText(warnings)
        self.detail_warning.setVisible(bool(warnings))
        self._description_text = detail.description
        self._description_uses_wiki = is_explicit_wiki_type(detail.description_format)
        self._description_render_result = None
        self._inline_image_bytes = 0
        self._wiki_resource_generation += 1
        self._inline_resource_reservations.clear()
        self._loaded_inline_resources.clear()
        self._attachments = ()
        self._attachment_preview_resources.clear()
        self.attachment_preview_button.setEnabled(False)
        self.attachment_preview_button.setVisible(False)
        self.attachment_preview.clear()
        self.attachment_preview.setVisible(False)
        self.attachment_table.setRowCount(0)
        self.attachment_reload_button.setEnabled(not historical)
        self.attachment_reload_button.setText("첨부 다시 불러오기")
        self.attachment_status_label.setText(
            "Baseline 첨부는 실서버 revision 계약 확인 후 제공됩니다."
            if historical
            else "첨부 파일을 불러오는 중입니다."
        )
        self.description_source_toggle.blockSignals(True)
        self.description_source_toggle.setChecked(False)
        self.description_source_toggle.blockSignals(False)
        self.description_source_toggle.setVisible(self._description_uses_wiki)
        self._render_description(False)
        self._request_description_render(detail, baseline_id)
        self._load_attachments()
        self.detail_raw_json.setPlainText(
            json.dumps(detail.raw_payload, ensure_ascii=False, indent=2, default=str)
        )

        rows: list[tuple[str, str, str]] = [
            ("ID", str(detail.item_id), "builtin"),
            ("프로젝트", summary.project_name or "-", "reference"),
            ("트래커", summary.tracker_name or "-", "reference"),
            ("상태", summary.status or "-", "reference"),
            ("담당자", ", ".join(summary.assignees) or "-", "reference"),
            ("버전", str(detail.version) if detail.version is not None else "-", "builtin"),
            ("수정 시각", summary.modified_at or "-", "builtin"),
            (
                "상위 아이템",
                (
                    f"#{detail.parent.item_id} {detail.parent.name}"
                    if detail.parent is not None
                    else "-"
                ),
                "reference",
            ),
            ("직접 하위", str(len(detail.children)), "reference"),
        ]
        self.detail_fields_table.clearContents()
        self.detail_fields_table.setRowCount(len(rows) + len(detail.custom_fields))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.detail_fields_table.setItem(row, column, QTableWidgetItem(value))
        field_row_offset = len(rows)
        for field_index, field in enumerate(detail.custom_fields):
            row = field_row_offset + field_index
            self.detail_fields_table.setItem(row, 0, QTableWidgetItem(field.name))
            self.detail_fields_table.setItem(row, 2, QTableWidgetItem(field.type_name))
            if is_table_field(field):
                table_summary = table_field_summary(field)
                value_item = QTableWidgetItem(table_summary)
                value_item.setToolTip(f"{field.name}의 행·열 데이터를 엽니다.")
                self.detail_fields_table.setItem(row, 1, value_item)
                open_button = QPushButton(
                    f"{table_summary} · 열어보기", self.detail_fields_table
                )
                open_button.clicked.connect(
                    lambda _checked=False, selected=field: self._open_table_field(selected)
                )
                self.detail_fields_table.setCellWidget(row, 1, open_button)
                continue
            text = field.display_value or "-"
            value_item = QTableWidgetItem(text)
            value_item.setToolTip(text)
            self.detail_fields_table.setItem(row, 1, value_item)
            if not (
                is_explicit_wiki_type(field.type_name)
                or payload_uses_wiki(field.raw_value)
            ):
                continue
            label = QPushButton("Wiki 내용 · 열어보기", self.detail_fields_table)
            label.setObjectName("tracker_wiki_cell")
            label.setToolTip(text)
            label.clicked.connect(
                lambda _checked=False, selected=field: self._open_wiki_field(selected)
            )
            value_item.setText("")
            self.detail_fields_table.setCellWidget(row, 1, label)
            self.detail_fields_table.setRowHeight(
                row,
                max(self.detail_fields_table.rowHeight(row), 36),
            )
        self.detail_fields_table.resizeRowsToContents()
        self.detail_tabs.setTabEnabled(self.editor_tab_index, not write_locked)
        self.popout_editor_button.setEnabled(not write_locked)
        if write_locked and self.detail_tabs.currentIndex() == self.editor_tab_index:
            self.detail_tabs.setCurrentIndex(0)
        if write_locked:
            self.editor_panel.clear()
        if (
            not write_locked
            and (
                previous_editor_detail is None
                or previous_editor_detail.item_id != detail.item_id
                or previous_editor_detail.version != detail.version
            )
        ):
            self.editor_panel.clear()
        if not write_locked and self.detail_tabs.currentIndex() == self.editor_tab_index:
            self._load_editor_schema(detail)

    def reset_detail(self) -> None:
        self._current_detail = None
        self._selected_item_id = None
        self._detail_baseline_id = None
        self._description_text = ""
        self._description_uses_wiki = False
        self._description_render_result = None
        self._attachments = ()
        self._attachment_preview_resources.clear()
        self._inline_image_bytes = 0
        self._wiki_resource_generation += 1
        self._inline_resource_reservations.clear()
        self._loaded_inline_resources.clear()
        self.description_source_toggle.blockSignals(True)
        self.description_source_toggle.setChecked(False)
        self.description_source_toggle.blockSignals(False)
        self.description_source_toggle.setVisible(False)
        self.detail_title.setText("아이템 상세")
        self.detail_refresh_button.setEnabled(False)
        self.detail_open_button.setEnabled(False)
        self.detail_refresh_button.setToolTip(
            "현재 아이템의 최신 version과 필드를 다시 조회합니다."
        )
        self.detail_id_badge.hide()
        self.detail_breadcrumb.setText("계층 또는 검색 결과에서 아이템을 선택하세요.")
        self.detail_warning.clear()
        self.detail_warning.hide()
        self.detail_description.clear()
        self.attachment_reload_button.setEnabled(False)
        self.attachment_reload_button.setText("첨부 불러오기")
        self.attachment_status_label.setText("아이템을 선택하면 첨부를 확인할 수 있습니다.")
        self.attachment_preview_button.setEnabled(False)
        self.attachment_preview_button.setVisible(False)
        self.attachment_preview.clear()
        self.attachment_preview.setVisible(False)
        self.attachment_table.setRowCount(0)
        self.detail_fields_table.setRowCount(0)
        self.detail_raw_json.clear()
        self.editor_panel.clear()
        self.detail_tabs.setTabEnabled(self.editor_tab_index, True)
        self.popout_editor_button.setEnabled(True)
        self._update_detached_editor_title(None)

    def _update_detached_editor_title(
        self,
        detail: TrackerItemDetail | None,
    ) -> None:
        dialog = self._editor_dialog
        if dialog is None:
            return
        title = (
            f"#{detail.item_id} {detail.summary.name} · 수정"
            if detail is not None
            else "트래커 아이템 수정"
        )
        dialog.setWindowTitle(title)
        dialog.title_label.setText(title)

    def _show_editor_in_window(self) -> None:
        if self._host.is_historical_read_only():
            self._host.set_workspace_status("Baseline 상세는 읽기 전용입니다.", tone="warning")
            return
        dialog = self._editor_dialog
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        detail = self._current_detail
        title = (
            f"#{detail.item_id} {detail.summary.name} · 수정"
            if detail is not None
            else "트래커 아이템 수정"
        )
        self.editor_host_layout.removeWidget(self.editor_panel)
        self.editor_placeholder.show()
        self.popout_editor_button.setText("열린 수정 창 보기")
        dialog = TrackerItemEditorDialog(
            self.editor_panel,
            title=title,
            parent=self,
        )
        self._editor_dialog = dialog
        dialog.finished.connect(self._restore_editor_panel)
        dialog.show()

    def _restore_editor_panel(self, *args) -> None:
        del args
        dialog = self._editor_dialog
        if dialog is None:
            return
        with contextlib.suppress(RuntimeError, TypeError):
            dialog.finished.disconnect(self._restore_editor_panel)
        panel = dialog.take_panel()
        if panel is not None:
            panel.setParent(self.editor_host)
            self.editor_host_layout.addWidget(panel, 1)
            panel.show()
        self.editor_placeholder.hide()
        self.popout_editor_button.setText("새 창에서 크게 수정")
        self._editor_dialog = None
        dialog.deleteLater()

    def _on_detail_tab_changed(self, index: int) -> None:
        # 수정 탭은 넓어야 쓸 만해서 화면 분할 비율을 바꾼다. 분할자는 작업공간이
        # 들고 있으므로 폭 조정만 맡긴다.
        editor_active = int(index) == self.editor_tab_index
        self._host.set_editor_expanded(editor_active)
        if not editor_active:
            return
        if self._current_detail is None:
            return
        editor_detail = self.editor_panel.detail
        if (
            editor_detail is not None
            and editor_detail.item_id == self._current_detail.item_id
            and editor_detail.version == self._current_detail.version
        ):
            return
        self._load_editor_schema(self._current_detail)

    def _load_editor_schema(self, detail: TrackerItemDetail) -> None:
        if self._host.is_historical_read_only():
            self.editor_panel.clear()
            self._host.set_workspace_status(
                "Baseline 상세는 읽기 전용입니다.",
                tone="warning",
            )
            return
        item_id = detail.item_id
        version = detail.version
        settings = self.settings_provider()
        self.editor_panel.set_loading("트래커 schema와 편집 가능한 필드를 확인하는 중입니다.")

        def loaded(schema) -> None:
            current = self._current_detail
            if current is None or current.item_id != item_id or current.version != version:
                return
            self.editor_panel.set_context(
                current,
                schema,
                write_enabled=not bool(settings.offline_mode),
            )

        def failed(exc: Exception) -> None:
            current = self._current_detail
            if current is None or current.item_id != item_id:
                return
            self.editor_panel.set_error(str(exc) or "편집 필드를 불러오지 못했습니다.")
            self._host.show_error(exc, prefix="편집 schema 조회 실패")

        self._host.submit(
            "editor_schema",
            lambda: self.editor_service.load_schema(settings, detail),
            loaded,
            failed,
        )

    def _save_item_changes(
        self,
        changes: tuple[TrackerItemFieldChange, ...],
    ) -> None:
        if self._host.is_historical_read_only():
            self._host.set_workspace_status("Baseline 상세는 수정할 수 없습니다.", tone="warning")
            return
        detail = self._current_detail
        if detail is None:
            return
        settings = self.settings_provider()
        item_id = detail.item_id
        self.editor_panel.set_busy(True)
        self.editor_panel.editor_status.setText(
            f"#{item_id}의 선택한 필드 {len(changes)}개를 저장하는 중입니다."
        )

        def loaded(updated_detail: TrackerItemDetail) -> None:
            self._host.record_item_activity(
                ActivityOperation.TRACKER_UPDATE,
                ActivityResult.SUCCESS,
                message=f"#{item_id}의 필드 {len(changes)}개를 저장했습니다.",
                detail=updated_detail,
                details={
                    "changed_fields": [change.field.label for change in changes],
                    "previous_version": detail.version,
                    "new_version": updated_detail.version,
                },
            )
            self._host.refresh_visible_item(updated_detail)
            self.render_detail(updated_detail)
            self._host.set_workspace_status(
                f"#{item_id}의 필드 {len(changes)}개를 저장했습니다."
            )

        def failed(exc: Exception) -> None:
            self._host.record_item_activity(
                ActivityOperation.TRACKER_UPDATE,
                ActivityResult.FAILED,
                message=f"#{item_id} 필드 저장에 실패했습니다.",
                detail=detail,
                details={
                    "changed_fields": [change.field.label for change in changes],
                    "error": str(exc),
                },
            )
            self.editor_panel.set_busy(False)
            self.editor_panel.set_error(str(exc) or "필드 저장에 실패했습니다.")
            self._host.show_error(exc, prefix="필드 저장 실패")

        self._host.submit(
            "item_write",
            lambda: self.editor_service.update_fields(
                settings,
                item_id=item_id,
                expected_version=detail.version,
                changes=changes,
            ),
            loaded,
            failed,
        )

    def _transition_item_status(
        self,
        status_field: EditableTrackerField,
        option_id: int,
    ) -> None:
        if self._host.is_historical_read_only():
            self._host.set_workspace_status(
                "Baseline 상세의 상태 필드를 변경할 수 없습니다.",
                tone="warning",
            )
            return
        detail = self._current_detail
        if detail is None:
            return
        settings = self.settings_provider()
        item_id = detail.item_id
        target_option = next(
            (option for option in status_field.options if option.option_id == int(option_id)),
            None,
        )
        target_name = target_option.name if target_option is not None else str(option_id)
        self.editor_panel.set_busy(True)
        self.editor_panel.editor_status.setText(
            f"#{item_id} 상태 필드를 '{target_name}'(으)로 변경하는 중입니다."
        )

        def loaded(updated_detail: TrackerItemDetail) -> None:
            self._host.record_item_activity(
                ActivityOperation.STATUS_TRANSITION,
                ActivityResult.SUCCESS,
                message=(
                    f"#{item_id} 상태를 "
                    f"'{updated_detail.summary.status or target_name}'(으)로 변경했습니다."
                ),
                detail=updated_detail,
                details={
                    "from_status": detail.summary.status,
                    "to_status": updated_detail.summary.status or target_name,
                    "previous_version": detail.version,
                    "new_version": updated_detail.version,
                },
            )
            self._host.refresh_visible_item(updated_detail)
            self.render_detail(updated_detail)
            self._host.set_workspace_status(
                f"#{item_id} 상태 필드를 '{updated_detail.summary.status or target_name}'(으)로 변경했습니다."
            )

        def failed(exc: Exception) -> None:
            self._host.record_item_activity(
                ActivityOperation.STATUS_TRANSITION,
                ActivityResult.FAILED,
                message=f"#{item_id} 상태 필드 변경에 실패했습니다.",
                detail=detail,
                details={
                    "from_status": detail.summary.status,
                    "to_status": target_name,
                    "error": str(exc),
                },
            )
            self.editor_panel.set_busy(False)
            self.editor_panel.set_error(str(exc) or "상태 필드 변경에 실패했습니다.")
            self._host.show_error(exc, prefix="상태 필드 변경 실패")

        self._host.submit(
            "item_write",
            lambda: self.editor_service.change_status_field(
                settings,
                item_id=item_id,
                expected_version=detail.version,
                status_field=status_field,
                option_id=int(option_id),
            ),
            loaded,
            failed,
        )

    def _delete_current_item(self) -> None:
        if self._host.is_historical_read_only():
            self._host.set_workspace_status("Baseline 상세는 삭제할 수 없습니다.", tone="warning")
            return
        detail = self._current_detail
        if detail is None:
            return
        confirmer = self.delete_confirmer
        confirmed = (
            bool(confirmer(detail))
            if confirmer is not None
            else ConfirmItemDeleteDialog.confirm(detail, self)
        )
        if not confirmed:
            return
        settings = self.settings_provider()
        item_id = detail.item_id
        tracker_id = detail.summary.tracker_id
        self.editor_panel.set_busy(True)
        self.editor_panel.editor_status.setText(f"#{item_id}을(를) 삭제하는 중입니다.")

        def loaded(result: Any) -> None:
            del result
            self._host.record_item_activity(
                ActivityOperation.TRACKER_DELETE,
                ActivityResult.SUCCESS,
                message=f"#{item_id} 아이템을 삭제했습니다.",
                detail=detail,
                details={"deleted_version": detail.version},
            )
            self._host.remove_visible_item(item_id)
            if tracker_id is not None:
                self._host.invalidate_tracker_cache(int(tracker_id))
            self._selected_item_id = None
            self.reset_detail()
            self._host.set_workspace_status(f"#{item_id}을(를) 삭제했습니다.")

        def failed(exc: Exception) -> None:
            self._host.record_item_activity(
                ActivityOperation.TRACKER_DELETE,
                ActivityResult.FAILED,
                message=f"#{item_id} 아이템 삭제에 실패했습니다.",
                detail=detail,
                details={"error": str(exc)},
            )
            self.editor_panel.set_busy(False)
            self.editor_panel.set_error(str(exc) or "아이템 삭제에 실패했습니다.")
            self._host.show_error(exc, prefix="아이템 삭제 실패")

        self._host.submit(
            "item_write",
            lambda: self.editor_service.delete_item(
                settings,
                item_id=item_id,
                expected_version=detail.version,
            ),
            loaded,
            failed,
        )
