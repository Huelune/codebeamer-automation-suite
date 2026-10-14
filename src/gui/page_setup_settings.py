from __future__ import annotations

from .error_reporting import safe_exception_message
from .page_common import _configure_constrained_panel
from .page_common import _configure_form_field
from .page_common import _configure_form_layout
from .page_common import _configure_inline_layout
from .page_common import _configure_page_layout
from .page_common import _project_selection_refresh_button_text
from .page_common import _project_selection_source_signature
from .page_common import _project_selection_status_text
from .page_common import _require_qt


def create_project_selection_page(
    initial_settings,
    on_settings_changed,
    on_connection_test,
    on_project_selected,
    on_error=None,
):
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QFormLayout = qt["QFormLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QComboBox = qt["QComboBox"]
    QPushButton = qt["QPushButton"]

    page = QWidget()
    page.selected_project_id = initial_settings.default_project_id
    page.selected_tracker_id = initial_settings.default_tracker_id

    layout = QVBoxLayout(page)
    _configure_page_layout(layout, top_align=True)

    form = QFormLayout()
    _configure_form_layout(form)
    project_combo = QComboBox()
    project_combo.setEnabled(False)
    tracker_combo = QComboBox()
    tracker_combo.setEnabled(False)
    _configure_form_field(project_combo)
    _configure_form_field(tracker_combo)
    form.addRow("프로젝트", project_combo)
    form.addRow("트래커", tracker_combo)
    form_container = QWidget()
    form_container.setLayout(form)
    _configure_constrained_panel(form_container)
    layout.addWidget(form_container)

    status_label = QLabel(_project_selection_status_text(bool(getattr(initial_settings, "offline_mode", False))))
    status_label.setObjectName("status_label")
    _configure_constrained_panel(status_label)
    layout.addWidget(status_label)

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    previous_button = QPushButton("이전")
    refresh_button = QPushButton(
        _project_selection_refresh_button_text(bool(getattr(initial_settings, "offline_mode", False)))
    )
    next_button = QPushButton("다음")
    refresh_button.setObjectName("primary_button")
    next_button.setObjectName("primary_button")
    next_button.setEnabled(bool(page.selected_project_id and page.selected_tracker_id))
    buttons.addWidget(previous_button)
    buttons.addWidget(refresh_button)
    buttons.addStretch(1)
    buttons.addWidget(next_button)
    layout.addLayout(buttons)
    layout.addStretch(1)

    def _update_next_button_state() -> None:
        next_button.setEnabled(bool(page.selected_project_id and page.selected_tracker_id))

    def _clear_combo_items() -> None:
        """`clear_combo_items` 상태를 비운다."""
        project_combo.blockSignals(True)
        tracker_combo.blockSignals(True)
        project_combo.clear()
        tracker_combo.clear()
        project_combo.setEnabled(False)
        tracker_combo.setEnabled(False)
        project_combo.blockSignals(False)
        tracker_combo.blockSignals(False)
        _update_next_button_state()

    def _set_items(combo, items: list[dict], selected_id: str) -> None:
        """`set_items` 값을 설정한다."""
        combo.blockSignals(True)
        combo.clear()
        for item in items:
            combo.addItem(item["name"], item["id"])
        combo.setEnabled(bool(items))
        if selected_id:
            index = combo.findData(int(selected_id)) if selected_id.isdigit() else -1
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _current_settings():
        return on_settings_changed(None)

    def _sync_from_settings(*, auto_load: bool = False) -> None:
        """`sync_from_settings` 상태를 동기화한다."""
        settings = _current_settings()
        is_offline = bool(getattr(settings, "offline_mode", False))
        refresh_button.setText(_project_selection_refresh_button_text(is_offline))
        source_signature = _project_selection_source_signature(settings)
        source_changed = source_signature != getattr(page, "_source_signature", None)
        if source_changed:
            page._source_signature = source_signature
            page.selected_project_id = str(getattr(settings, "default_project_id", "") or "")
            page.selected_tracker_id = str(getattr(settings, "default_tracker_id", "") or "")
            _clear_combo_items()
            status_label.setText(_project_selection_status_text(is_offline))
        elif not str(status_label.text() or "").strip():
            status_label.setText(_project_selection_status_text(is_offline))

        if auto_load and is_offline and project_combo.count() == 0:
            _refresh_projects()

    def _refresh_projects() -> None:
        """`refresh_projects` 표시를 새로 고친다."""
        settings = _current_settings()
        try:
            projects = on_connection_test(settings)
        except Exception as exc:
            message = f"프로젝트 조회 실패: {safe_exception_message(exc)}"
            status_label.setText(message)
            if callable(on_error):
                on_error("프로젝트 조회 실패", message)
            _clear_combo_items()
            page.selected_project_id = ""
            page.selected_tracker_id = ""
            _update_next_button_state()
            return
        _set_items(project_combo, projects, page.selected_project_id)
        status_label.setText(
            "테스트 프로젝트 목록을 불러왔습니다."
            if bool(getattr(settings, "offline_mode", False))
            else "프로젝트 목록을 불러왔습니다."
        )
        if project_combo.count() > 0:
            selected_index = project_combo.currentIndex()
            if selected_index < 0:
                selected_index = 0
                project_combo.setCurrentIndex(0)
            _handle_project_changed(selected_index)

    def _refresh_projects_for_current_settings() -> None:
        """`refresh_projects_for_current_settings` 표시를 새로 고친다."""
        _sync_from_settings(auto_load=False)
        _refresh_projects()

    def _handle_project_changed(index: int) -> None:
        project_id = project_combo.itemData(index)
        if project_id in (None, ""):
            tracker_combo.clear()
            tracker_combo.setEnabled(False)
            page.selected_project_id = ""
            page.selected_tracker_id = ""
            _update_next_button_state()
            return
        page.selected_project_id = str(project_id)
        page.selected_tracker_id = ""
        _update_next_button_state()
        settings = _current_settings()
        settings.default_project_id = page.selected_project_id
        try:
            trackers = on_project_selected(settings, int(project_id))
        except Exception as exc:
            message = f"트래커 조회 실패: {safe_exception_message(exc)}"
            status_label.setText(message)
            if callable(on_error):
                on_error("트래커 조회 실패", message)
            tracker_combo.clear()
            tracker_combo.setEnabled(False)
            _update_next_button_state()
            return
        _set_items(tracker_combo, trackers, page.selected_tracker_id)
        if tracker_combo.currentData() not in (None, ""):
            page.selected_tracker_id = str(tracker_combo.currentData())
        _update_next_button_state()
        if bool(getattr(settings, "offline_mode", False)):
            status_label.setText("테스트 tracker snapshot 정보를 불러왔습니다.")
        else:
            status_label.setText(f"프로젝트 {project_combo.currentText()}의 트래커를 불러왔습니다.")

    def _handle_tracker_changed(index: int) -> None:
        tracker_id = tracker_combo.itemData(index)
        if tracker_id not in (None, ""):
            page.selected_tracker_id = str(tracker_id)
        else:
            page.selected_tracker_id = ""
        _update_next_button_state()

    def _go_next() -> None:
        """`go_next` 단계 이동을 처리한다."""
        if not page.selected_project_id or not page.selected_tracker_id:
            status_label.setText("프로젝트와 트래커를 모두 선택해야 합니다.")
            return
        settings = _current_settings()
        settings.default_project_id = page.selected_project_id
        settings.default_tracker_id = page.selected_tracker_id
        on_settings_changed(settings)
        page.request_next()

    previous_button.clicked.connect(lambda: page.request_previous())
    refresh_button.clicked.connect(_refresh_projects_for_current_settings)
    next_button.clicked.connect(_go_next)
    project_combo.currentIndexChanged.connect(_handle_project_changed)
    tracker_combo.currentIndexChanged.connect(_handle_tracker_changed)

    def _load_selection(project_id: str, tracker_id: str) -> None:
        page.selected_project_id = str(project_id or "")
        page.selected_tracker_id = str(tracker_id or "")
        if page.selected_project_id.isdigit() and project_combo.count() > 0:
            project_index = project_combo.findData(int(page.selected_project_id))
            if project_index >= 0:
                project_combo.setCurrentIndex(project_index)
        if page.selected_tracker_id.isdigit() and tracker_combo.count() > 0:
            tracker_index = tracker_combo.findData(int(page.selected_tracker_id))
            if tracker_index >= 0:
                tracker_combo.setCurrentIndex(tracker_index)
        _update_next_button_state()

    def _get_selection() -> dict[str, str]:
        return {
            "project_id": str(page.selected_project_id or ""),
            "tracker_id": str(page.selected_tracker_id or ""),
        }

    page.load_selection = _load_selection
    page.get_selection = _get_selection
    page.on_page_shown = lambda: _sync_from_settings(auto_load=True)
    _sync_from_settings(auto_load=False)
    return page


