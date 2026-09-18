from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from typing import Any

from .loading_overlay import LoadingOverlay
from .page_batch_settings import create_batch_settings_page
from .page_execution_mapping import create_mapping_page
from .page_execution_run import create_result_page
from .page_execution_run import create_upload_page
from .page_execution_run import create_validation_page
from .page_setup_file import create_file_selection_page
from .page_setup_file import create_root_item_page
from .page_setup_settings import create_project_selection_page
from .styles import build_gui_stylesheet
from .styles import normalize_gui_theme_name
from .worker import BackgroundTask


if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    from .settings_store import GuiSettings
    from .settings_store import GuiSettingsStore
    from .settings_store import GuiWorkflowPreset
    from .window_support import GuiSessionState

    class _WindowShellMixinComposition(QMainWindow):
        """WindowShellMixin 이 조립된 뒤에야 쓸 수 있는 이름들의 선언이다.

        `BatchUploadWindow` 가 QMainWindow 와 함께 조립한다.
        Qt 메서드(height, isFullScreen, isMaximized, minimumHeight, minimumWidth,
        screen 등)는 QMainWindow 상속으로 해결한다.
        런타임에는 object 이므로 실제 상속 관계는 바뀌지 않는다.
        """

        # 조립 클래스가 설정하는 속성이다.
        qt: dict[str, Any]
        session_state: GuiSessionState
        settings_store: GuiSettingsStore

        # 형제 믹스인이 제공하는 메서드다. 시그니처는 정의 위치에서 옮겼다.
        def _apply_workflow_preset(self, preset: GuiWorkflowPreset, *, startup: bool=False) -> None:
            ...

        def _cancel_upload(self) -> None:
            ...

        def _delete_workflow_preset(self) -> None:
            ...

        def _enter_result_page(self) -> None:
            ...

        def _enter_upload_page(self) -> None:
            ...

        def _enter_validation_page(self) -> None:
            ...

        def _load_file_metadata(self, file_path: str):
            ...

        def _load_file_preview(
            self,
            file_path: str,
            *,
            file_paths: list[str] | None = None,
            sheet_name: str,
            header_row: int,
            summary_column: str,
        ): ...

        def _load_full_file_data(
            self,
            file_path: str,
            *,
            file_paths: list[str] | None,
            sheet_name: str,
            header_row: int,
            summary_column: str,
            sheet_preview=None,
        ): ...

        def _load_sheet_preview(self, file_path: str, *, sheet_name: str, header_row: int, summary_column: str):
            ...

        def _load_trackers(self, settings: GuiSettings, project_id: int) -> list[dict[str, object]]:
            ...

        def _load_workflow_preset(self) -> None:
            ...

        def _on_confirm_root_item_field_config(self) -> None:
            ...

        def _on_confirm_root_item_structure_config(self) -> None:
            ...

        def _on_file_state_changed(self, file_state: dict[str, object]) -> None:
            ...

        def _on_prepare_root_item_context(self) -> None:
            ...

        def _on_settings_changed(self, settings: GuiSettings | None) -> GuiSettings:
            ...

        def _pause_upload(self) -> None:
            ...

        def _preview_root_item_config(self, root_item_config: dict[str, object]):
            ...

        def _refresh_workflow_preset_choices(self, selected_id: str | None=None) -> None:
            ...

        def _rename_workflow_preset(self) -> None:
            ...

        def _restart_upload_flow(self) -> None:
            ...

        def _resume_upload(self) -> None:
            ...

        def _save_workflow_preset(self) -> None:
            ...

        def _save_workflow_preset_as(self) -> None:
            ...

        def _set_default_workflow_preset(self) -> None:
            ...

        def _start_upload(self) -> None:
            ...

        def _sync_workflow_preset_action_state(self, _index: int | None=None) -> None:
            ...

        def _test_connection(self, settings: GuiSettings) -> list[dict[str, object]]:
            ...

        def _validate_mapping(
            self,
            selected_mapping: dict[str, str],
            selected_mapping_modes: dict[str, dict[str, bool]],
            selected_default_values: dict[str, str],
            selected_default_value_modes: dict[str, dict[str, bool]],
            selected_tracker_item_settings: dict[str, dict[str, object]],
        ) -> None: ...

else:
    _WindowShellMixinComposition = object


class WindowShellMixin(_WindowShellMixinComposition):
    def _build_shell(self) -> None:
        QWidget = self.qt["QWidget"]
        QVBoxLayout = self.qt["QVBoxLayout"]
        QHBoxLayout = self.qt["QHBoxLayout"]
        QLabel = self.qt["QLabel"]
        QFrame = self.qt["QFrame"]
        QPushButton = self.qt["QPushButton"]
        QComboBox = self.qt["QComboBox"]

        self.page_scroll_areas: dict[str, Any] = {}
        self.page_meta: dict[str, Any] = {}
        self._current_page = None
        self._initial_window_state_applied = False
        self._last_normal_window_width = self.minimumWidth()
        self._last_normal_window_height = self.minimumHeight()

        root = QWidget()
        root.setObjectName("app_root")
        self.root_widget = root
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 8, 10, 8)
        root_layout.setSpacing(8)

        header_card = QFrame()
        header_card.setObjectName("header_card")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(6)

        title = QLabel("Codebeamer Upload Studio")
        title.setObjectName("app_title")
        subtitle = QLabel("현대케피코용 업로드 작업을 단계별로 확인하고 실행하는 도구")
        subtitle.setObjectName("app_subtitle")

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(title)
        title_row.addStretch(1)

        self.workflow_preset_combo = QComboBox()
        self.workflow_preset_combo.setMinimumWidth(170)
        self.workflow_preset_combo.setToolTip(
            "현재 연결 프로필·프로젝트·트래커에 저장된 전체 업로드 설정"
        )
        self.load_workflow_button = QPushButton("불러오기")
        self.save_workflow_button = QPushButton("저장")
        self.save_workflow_as_button = QPushButton("새로 저장")
        self.rename_workflow_button = QPushButton("이름 변경")
        self.default_workflow_button = QPushButton("기본 지정")
        self.delete_workflow_button = QPushButton("삭제")

        header_layout.addLayout(title_row)
        header_layout.addWidget(subtitle)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_label = QLabel("전체 업로드 설정")
        preset_label.setObjectName("section_label")
        preset_row.addWidget(preset_label)
        preset_row.addWidget(self.workflow_preset_combo, 1)
        preset_row.addWidget(self.load_workflow_button)
        preset_row.addWidget(self.save_workflow_button)
        preset_row.addWidget(self.save_workflow_as_button)
        preset_row.addWidget(self.rename_workflow_button)
        preset_row.addWidget(self.default_workflow_button)
        preset_row.addWidget(self.delete_workflow_button)
        header_layout.addLayout(preset_row)

        steps_row = QHBoxLayout()
        steps_row.setSpacing(6)
        self.step_labels = []
        for step_name in ("배치 설정", "프로젝트", "파일", "상단 구조", "상단 필드", "매핑", "검증", "업로드", "결과"):
            label = QLabel(step_name)
            label.setObjectName("step_badge")
            steps_row.addWidget(label)
            self.step_labels.append(label)
        steps_row.addStretch(1)
        header_layout.addLayout(steps_row)

        self.page_title_label = QLabel("")
        self.page_title_label.setObjectName("page_title")
        self.page_subtitle_label = QLabel("")
        self.page_subtitle_label.setObjectName("app_subtitle")
        header_layout.addWidget(self.page_title_label)
        header_layout.addWidget(self.page_subtitle_label)

        self.stack_card = QFrame()
        self.stack_card.setObjectName("page_card")
        stack_layout = QVBoxLayout(self.stack_card)
        stack_layout.setContentsMargins(6, 6, 6, 6)
        stack_layout.setSpacing(0)
        self.stack = self.qt["QStackedWidget"]()
        stack_layout.addWidget(self.stack)

        root_layout.addWidget(header_card)
        root_layout.addWidget(self.stack_card, 1)

        self.busy_overlay = LoadingOverlay(root)
        self.busy_message_label = self.busy_overlay.message_label
        self.busy_spinner = self.busy_overlay.spinner
        self._local_busy_token: int | None = None
        self._external_busy_token = None

        self.setCentralWidget(root)
        self._update_busy_overlay_geometry()

    def _create_page_scroll_area(self, page):
        QFrame = self.qt["QFrame"]
        QScrollArea = self.qt["QScrollArea"]
        Qt = self.qt["Qt"]

        scroll_area = QScrollArea()
        scroll_area.setObjectName("page_scroll_area")
        scroll_area.setWidget(page)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.verticalScrollBar().setSingleStep(20)
        self.page_scroll_areas[page] = scroll_area
        return scroll_area

    def _content_height_for_page(self, page) -> int:
        if page is None:
            return self.height()

        root_layout = self.root_widget.layout()
        stack_layout = self.stack_card.layout()
        header_item = root_layout.itemAt(0)
        header_widget = None if header_item is None else header_item.widget()
        header_height = 0 if header_widget is None else header_widget.sizeHint().height()

        page_layout = page.layout()
        if page_layout is not None:
            page_layout.invalidate()
            page_layout.activate()
        page.adjustSize()

        root_margins = root_layout.contentsMargins()
        stack_margins = stack_layout.contentsMargins()
        status_height = 0 if self.statusBar() is None else self.statusBar().sizeHint().height()
        stack_frame_height = self.stack_card.frameWidth() * 2

        return (
            root_margins.top()
            + header_height
            + root_layout.spacing()
            + stack_frame_height
            + stack_margins.top()
            + page.sizeHint().height()
            + stack_margins.bottom()
            + root_margins.bottom()
            + status_height
        )

    def _window_height_cap(self) -> int:
        screen = self.screen()
        available_height = 1080
        if screen is not None:
            available_height = max(screen.availableGeometry().height(), self.minimumHeight())
        return max(self.minimumHeight(), int(available_height * 0.88))

    def _fit_window_to_current_page(self, *, allow_grow: bool) -> None:
        if bool(getattr(self, "_embedded", False)):
            return
        page = self._current_page if hasattr(self, "_current_page") else None
        if page is None:
            return
        if self.isFullScreen() or self.isMaximized():
            return

        target_height = min(
            max(self.minimumHeight(), self._content_height_for_page(page)),
            self._window_height_cap(),
        )
        current_height = self.height()
        if not allow_grow and target_height > current_height and current_height <= self._window_height_cap():
            return

        self.resize(self.width(), target_height)
        self.updateGeometry()

    def _update_busy_overlay_geometry(self) -> None:
        if hasattr(self, "busy_overlay") and hasattr(self, "root_widget"):
            self.busy_overlay.sync_geometry()

    def resizeEvent(self, event) -> None:
        """Qt 리사이즈 이벤트를 처리한다."""
        super().resizeEvent(event)
        if (
            not bool(getattr(self, "_embedded", False))
            and not self.isFullScreen()
            and not self.isMaximized()
        ):
            self._last_normal_window_width = max(int(self.width()), self.minimumWidth())
            self._last_normal_window_height = max(int(self.height()), self.minimumHeight())
        self._update_busy_overlay_geometry()

    def showEvent(self, event) -> None:
        """Qt 표시 이벤트를 처리한다."""
        super().showEvent(event)
        if bool(getattr(self, "_embedded", False)):
            return
        if self._initial_window_state_applied:
            return
        self._initial_window_state_applied = True
        if bool(getattr(self.session_state.settings, "window_is_fullscreen", False)):
            self.showFullScreen()
        elif bool(getattr(self.session_state.settings, "window_is_maximized", False)):
            self.showMaximized()

    def closeEvent(self, event) -> None:
        """Qt 종료 이벤트를 처리한다."""
        if bool(getattr(self, "_persist_window_preferences_on_close", True)):
            self._persist_window_preferences()
        super().closeEvent(event)

    def _persist_window_preferences(self) -> None:
        """`persist_window_preferences` 상태를 저장한다."""
        current_settings = replace(self.session_state.settings)
        updated_settings = replace(
            current_settings,
            window_width=max(int(self._last_normal_window_width), self.minimumWidth()),
            window_height=max(int(self._last_normal_window_height), self.minimumHeight()),
            window_is_maximized=bool(self.isMaximized()),
            window_is_fullscreen=bool(self.isFullScreen()),
        )
        self.session_state.settings = updated_settings
        try:
            self.settings_store.save(updated_settings)
        except Exception:
            return

    def _set_busy(self, busy: bool, message: str = "") -> None:
        """`set_busy` 값을 설정한다."""
        QApplication = self.qt["QApplication"]

        external_start = getattr(self, "_busy_started_callback", None)
        external_finish = getattr(self, "_busy_finished_callback", None)
        if bool(getattr(self, "_embedded", False)) and callable(external_start):
            if busy and self._external_busy_token is None:
                self._external_busy_token = external_start(message)
            elif not busy and self._external_busy_token is not None:
                if callable(external_finish):
                    external_finish(self._external_busy_token)
                self._external_busy_token = None
            QApplication.processEvents()
            return

        if busy:
            if self._local_busy_token is None:
                self._local_busy_token = self.busy_overlay.start(message)
            QApplication.processEvents()
            return

        self.busy_overlay.finish(self._local_busy_token)
        self._local_busy_token = None
        QApplication.processEvents()

    def _run_with_busy(self, message: str, func, *args, **kwargs):
        QEventLoop = self.qt["QEventLoop"]
        loop = QEventLoop(self)
        task = BackgroundTask(func, *args, **kwargs)
        result_box: dict[str, object] = {}

        def _on_completed(result: object) -> None:
            result_box["result"] = result
            loop.quit()

        def _on_failed(error: object) -> None:
            result_box["error"] = error
            loop.quit()

        task.completed.connect(_on_completed)
        task.failed.connect(_on_failed)
        self.busy_task = task
        self._set_busy(True, message)

        try:
            task.start()
            loop.exec()
        finally:
            task.wait()
            task.deleteLater()
            self.busy_task = None
            self._set_busy(False)

        if "error" in result_box:
            error = result_box["error"]
            if isinstance(error, Exception):
                raise error
            raise RuntimeError(str(error))

        return result_box.get("result")

    def _build_pages(self) -> None:
        self.settings_page = create_batch_settings_page(
            self.session_state.settings,
            self._on_settings_changed,
            getattr(self, "_global_settings_requested_callback", None),
        )
        self.project_page = create_project_selection_page(
            self.session_state.settings,
            self._on_settings_changed,
            self._test_connection,
            self._load_trackers,
            self._show_error_dialog,
        )
        self.file_page = create_file_selection_page(
            self.session_state.settings,
            self._on_file_state_changed,
            self._load_file_preview,
            self._show_error_dialog,
            on_file_metadata_requested=self._load_file_metadata,
            on_sheet_preview_requested=self._load_sheet_preview,
            on_full_data_requested=self._load_full_file_data,
        )
        self.root_item_structure_page = create_root_item_page(
            self._preview_root_item_config,
            page_mode="structure",
        )
        self.root_item_field_page = create_root_item_page(
            self._preview_root_item_config,
            page_mode="fields",
        )
        self.mapping_page = create_mapping_page(
            self._validate_mapping,
            self._show_error_dialog,
        )
        self.validation_page = create_validation_page()
        self.upload_page = create_upload_page(
            self._start_upload,
            self._pause_upload,
            self._resume_upload,
            self._cancel_upload,
        )
        self.result_page = create_result_page()

        self.load_workflow_button.clicked.connect(self._load_workflow_preset)
        self.save_workflow_button.clicked.connect(self._save_workflow_preset)
        self.save_workflow_as_button.clicked.connect(self._save_workflow_preset_as)
        self.rename_workflow_button.clicked.connect(self._rename_workflow_preset)
        self.default_workflow_button.clicked.connect(self._set_default_workflow_preset)
        self.delete_workflow_button.clicked.connect(self._delete_workflow_preset)
        self.workflow_preset_combo.currentIndexChanged.connect(
            self._sync_workflow_preset_action_state
        )

        self._attach_navigation(self.settings_page, next_page=self.project_page)
        self._attach_navigation(
            self.project_page,
            previous_page=self.settings_page,
            next_page=self.file_page,
        )
        self._attach_navigation(
            self.file_page,
            previous_page=self.project_page,
            next_handler=self._on_prepare_root_item_context,
        )
        self._attach_navigation(
            self.root_item_structure_page,
            previous_page=self.file_page,
            next_handler=self._on_confirm_root_item_structure_config,
        )
        self._attach_navigation(
            self.root_item_field_page,
            previous_page=self.root_item_structure_page,
            next_handler=self._on_confirm_root_item_field_config,
        )
        self._attach_navigation(
            self.mapping_page,
            previous_page=self.root_item_field_page,
            next_page=self.validation_page,
            next_handler=self._enter_validation_page,
        )
        self._attach_navigation(
            self.validation_page,
            previous_page=self.mapping_page,
            next_page=self.upload_page,
            next_handler=self._enter_upload_page,
        )
        self._attach_navigation(
            self.upload_page,
            previous_page=self.validation_page,
            next_page=self.result_page,
            next_handler=self._enter_result_page,
        )
        self._attach_navigation(
            self.result_page,
            previous_page=self.upload_page,
            restart_handler=self._restart_upload_flow,
        )

        for page in (
            self.settings_page,
            self.project_page,
            self.file_page,
            self.root_item_structure_page,
            self.root_item_field_page,
            self.mapping_page,
            self.validation_page,
            self.upload_page,
            self.result_page,
        ):
            self.stack.addWidget(self._create_page_scroll_area(page))

        self.page_meta = {
            self.settings_page: ("배치 설정", "작업 모드와 Excel 해석 기준을 확인합니다.", 0),
            self.project_page: ("프로젝트 선택", "업로드 대상 프로젝트와 트래커를 선택합니다.", 1),
            self.file_page: ("파일 선택", "Excel 파일과 시트, 헤더 정보를 확인합니다.", 2),
            self.root_item_structure_page: ("상단 구조", "상단 폴더를 어떤 구조로 만들지 결정합니다.", 3),
            self.root_item_field_page: ("상단 필드", "상단 폴더에 들어갈 이름과 필드 값을 설정합니다.", 4),
            self.mapping_page: ("컬럼 매핑", "업로드할 컬럼만 선택하고 Codebeamer 필드와 연결합니다.", 5),
            self.validation_page: ("검증", "문제가 있는 항목만 먼저 확인하고 수정 여부를 판단합니다.", 6),
            self.upload_page: ("업로드", "진행 상황을 확인하면서 업로드를 제어합니다.", 7),
            self.result_page: ("결과", "성공, 실패, 미해결 항목을 정리해서 확인합니다.", 8),
        }
        for page in (
            self.settings_page,
            self.project_page,
            self.file_page,
            self.root_item_structure_page,
            self.root_item_field_page,
            self.mapping_page,
            self.validation_page,
            self.upload_page,
            self.result_page,
        ):
            page.request_content_reflow = self._fit_window_to_current_page
        self._show_page(self.settings_page)
        if self.session_state.workflow_preset is not None:
            self._apply_workflow_preset(self.session_state.workflow_preset, startup=True)
        else:
            self._apply_theme(self.session_state.settings.theme_name)
            self.statusBar().showMessage("GUI 스켈레톤이 준비되었습니다.")
        self._refresh_workflow_preset_choices()

    def _show_page(self, page) -> None:
        self._current_page = page
        page_scroll_area = self.page_scroll_areas.get(page, page)
        self.stack.setCurrentWidget(page_scroll_area)
        title, subtitle, active_index = self.page_meta.get(page, ("", "", -1))
        self.page_title_label.setText(title)
        self.page_subtitle_label.setText(subtitle)
        for index, label in enumerate(self.step_labels):
            label.setProperty("active", index == active_index)
            label.setProperty("complete", active_index >= 0 and index < active_index)
            label.style().unpolish(label)
            label.style().polish(label)
        on_page_shown = getattr(page, "on_page_shown", None)
        if callable(on_page_shown):
            on_page_shown()
        if page_scroll_area is not None and hasattr(page_scroll_area, "verticalScrollBar"):
            page_scroll_area.verticalScrollBar().setValue(0)
        self._fit_window_to_current_page(allow_grow=True)

    def _attach_navigation(
        self,
        page,
        previous_page=None,
        next_page=None,
        next_handler=None,
        restart_handler=None,
    ) -> None:
        """`attach_navigation` 연결을 구성한다."""
        def _go_previous():
            """`go_previous` 단계 이동을 처리한다."""
            if previous_page is not None:
                self._show_page(previous_page)

        def _go_next():
            """`go_next` 단계 이동을 처리한다."""
            try:
                if next_handler is not None:
                    next_handler()
                    return
                if next_page is not None:
                    self._show_page(next_page)
            except Exception as exc:
                self.statusBar().showMessage(str(exc))
                self._show_error_dialog("작업 실패", str(exc))

        def _restart():
            try:
                if restart_handler is not None:
                    restart_handler()
            except Exception as exc:
                self.statusBar().showMessage(str(exc))
                self._show_error_dialog("작업 실패", str(exc))

        page.request_previous = _go_previous
        page.request_next = _go_next
        page.request_restart = _restart

    def _apply_theme(self, theme_name: str | None) -> str:
        """`apply_theme` 변경을 적용한다."""
        QApplication = self.qt["QApplication"]
        normalized_theme = normalize_gui_theme_name(theme_name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_gui_stylesheet(normalized_theme))
        return normalized_theme

    @staticmethod
    def _dialog_message_parts(message: str, fallback: str) -> tuple[str, str]:
        text = str(message or "").strip()
        if not text:
            return fallback, ""

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        compact = " ".join(lines) if lines else text
        if "\n" not in text and len(compact) <= 160:
            return compact, ""

        summary = lines[0] if lines else compact
        if len(summary) > 160:
            summary = f"{summary[:157].rstrip()}..."
        return summary, text

    def _show_message_dialog(self, title: str, message: str, *, tone: str) -> None:
        QDialog = self.qt["QDialog"]
        QFrame = self.qt["QFrame"]
        QHBoxLayout = self.qt["QHBoxLayout"]
        QLabel = self.qt["QLabel"]
        QPlainTextEdit = self.qt["QPlainTextEdit"]
        QPushButton = self.qt["QPushButton"]
        QVBoxLayout = self.qt["QVBoxLayout"]
        Qt = self.qt["Qt"]

        fallback_message = (
            "알 수 없는 오류가 발생했습니다."
            if tone == "error"
            else "작업이 완료되었습니다."
        )
        header_text = str(title or ("오류" if tone == "error" else "안내")).strip()
        summary_text, detail_text = self._dialog_message_parts(message, fallback_message)

        dialog = QDialog(self)
        dialog.setObjectName("alert_dialog")
        dialog.setWindowTitle(header_text)
        dialog.setModal(True)
        dialog.setMinimumWidth(400)

        root_layout = QVBoxLayout(dialog)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(0)

        surface = QFrame(dialog)
        surface.setObjectName("alert_surface")
        surface.setProperty("tone", tone)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(16, 14, 16, 14)
        surface_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        badge = QLabel("!" if tone == "error" else "i")
        badge.setObjectName("alert_badge")
        badge.setProperty("tone", tone)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(40, 40)
        header_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        copy_layout = QVBoxLayout()
        copy_layout.setSpacing(4)

        title_label = QLabel(header_text)
        title_label.setObjectName("alert_title")
        copy_layout.addWidget(title_label)

        message_label = QLabel(summary_text)
        message_label.setObjectName("alert_message")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy_layout.addWidget(message_label)
        header_row.addLayout(copy_layout, 1)

        surface_layout.addLayout(header_row)

        if detail_text:
            details = QPlainTextEdit(surface)
            details.setObjectName("alert_details")
            details.setReadOnly(True)
            details.setPlainText(detail_text)
            details.setFixedHeight(104)
            surface_layout.addWidget(details)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        confirm_button = QPushButton("확인")
        confirm_button.setObjectName("primary_button")
        confirm_button.setDefault(True)
        confirm_button.setAutoDefault(True)
        confirm_button.clicked.connect(dialog.accept)
        button_row.addWidget(confirm_button)
        surface_layout.addLayout(button_row)

        root_layout.addWidget(surface)
        dialog.adjustSize()
        dialog.exec()

    def _show_error_dialog(self, title: str, message: str) -> None:
        self._show_message_dialog(title, message, tone="error")

    def _show_info_dialog(self, title: str, message: str) -> None:
        self._show_message_dialog(title, message, tone="info")
