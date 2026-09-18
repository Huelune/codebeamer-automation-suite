from __future__ import annotations

from pathlib import Path

from src.upload_policy import normalize_upload_mode as normalize_gui_upload_mode
from src.upload_policy import upload_mode_supports_update as gui_upload_mode_supports_update

from .page_common import WIDE_FORM_PANEL_MAX_WIDTH
from .page_common import _configure_card_layout
from .page_common import _configure_constrained_panel
from .page_common import _configure_form_field
from .page_common import _configure_form_layout
from .page_common import _configure_inline_layout
from .page_common import _configure_page_layout
from .page_common import _project_selection_refresh_button_text
from .page_common import _project_selection_source_signature
from .page_common import _project_selection_status_text
from .page_common import _require_qt
from .page_common import _settings_mode_description
from .page_common import _settings_mode_toggle_text
from .page_common import _settings_upload_mode_choices
from .styles import GUI_THEME_CHOICES
from .styles import normalize_gui_theme_name


def create_settings_page(
    settings_store,
    initial_settings,
    on_settings_changed,
    on_theme_changed=None,
):
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QFormLayout = qt["QFormLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QFrame = qt["QFrame"]
    QCheckBox = qt["QCheckBox"]
    QComboBox = qt["QComboBox"]
    QFileDialog = qt["QFileDialog"]
    QSpinBox = qt["QSpinBox"]
    QDoubleSpinBox = qt["QDoubleSpinBox"]
    QPushButton = qt["QPushButton"]
    QToolButton = qt["QToolButton"]
    Qt = qt["Qt"]

    page = QWidget()
    page.setObjectName("settings_page")
    layout = QVBoxLayout(page)
    _configure_page_layout(layout, top_align=True)

    form = QFormLayout()
    _configure_form_layout(form)
    base_url = QLineEdit(initial_settings.base_url)
    username = QLineEdit(initial_settings.username)
    password = QLineEdit(initial_settings.password)
    password.setEchoMode(QLineEdit.EchoMode.Password)
    save_password = QCheckBox("비밀번호 저장")
    save_password.setChecked(initial_settings.save_password)
    mode_toggle = QPushButton()
    mode_toggle.setObjectName("mode_toggle")
    mode_toggle.setCheckable(True)
    mode_toggle.setChecked(bool(getattr(initial_settings, "offline_mode", False)))
    mode_toggle.setToolTip("저장된 schema/config snapshot으로 검증하는 테스트 모드입니다.")
    mode_badge = QLabel("테스트 모드")
    mode_badge.setObjectName("mode_badge")
    mode_badge.hide()
    mode_row_widget = QWidget()
    mode_row = QHBoxLayout(mode_row_widget)
    _configure_inline_layout(mode_row)
    mode_row.addStretch(1)
    mode_row.addWidget(mode_badge, 0, Qt.AlignmentFlag.AlignVCenter)
    mode_row.addWidget(mode_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
    offline_schema_path = QLineEdit(str(getattr(initial_settings, "offline_schema_path", "") or ""))
    offline_schema_button = QPushButton("스키마 선택")
    offline_config_path = QLineEdit(
        str(getattr(initial_settings, "offline_tracker_configuration_path", "") or "")
    )
    offline_config_button = QPushButton("설정 선택")
    theme_combo = QComboBox()
    upload_mode_combo = QComboBox()
    header_row = QSpinBox()
    header_row.setMinimum(1)
    header_row.setValue(initial_settings.excel_header_row)
    summary_column = QLineEdit(initial_settings.summary_column)
    sheet_name = QLineEdit(initial_settings.excel_sheet_name)
    retry_delay = QDoubleSpinBox()
    retry_delay.setMinimum(0.0)
    retry_delay.setMaximum(3600.0)
    retry_delay.setValue(initial_settings.rate_limit_retry_delay_seconds)
    retry_delay.setDecimals(2)
    retry_count = QSpinBox()
    retry_count.setMinimum(0)
    retry_count.setMaximum(999)
    retry_count.setValue(initial_settings.rate_limit_max_retries)
    output_dir = QLineEdit(initial_settings.output_dir)

    for field_widget in (
        base_url,
        username,
        password,
        offline_schema_path,
        offline_config_path,
        theme_combo,
        upload_mode_combo,
    ):
        _configure_form_field(field_widget)

    offline_schema_row_widget = QWidget()
    offline_schema_row = QHBoxLayout(offline_schema_row_widget)
    _configure_inline_layout(offline_schema_row)
    offline_schema_row.addWidget(offline_schema_path, 1)
    offline_schema_row.addWidget(offline_schema_button)

    offline_config_row_widget = QWidget()
    offline_config_row = QHBoxLayout(offline_config_row_widget)
    _configure_inline_layout(offline_config_row)
    offline_config_row.addWidget(offline_config_path, 1)
    offline_config_row.addWidget(offline_config_button)

    form.addRow("Base URL", base_url)
    form.addRow("Username", username)
    form.addRow("Password", password)
    form.addRow("", save_password)
    form.addRow("작업 모드", upload_mode_combo)
    form.addRow("테마", theme_combo)
    form.addRow("", mode_row_widget)
    form_container = QWidget()
    form_container.setLayout(form)
    _configure_constrained_panel(form_container, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(form_container)

    offline_card = QFrame()
    offline_card.setObjectName("advanced_card")
    _configure_constrained_panel(offline_card, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    offline_layout = QVBoxLayout(offline_card)
    _configure_card_layout(offline_layout)
    offline_description = QLabel("테스트 모드에서만 사용하는 snapshot 경로입니다.")
    offline_description.setObjectName("section_label")
    offline_layout.addWidget(offline_description)
    offline_form = QFormLayout()
    _configure_form_layout(offline_form)
    offline_form.setContentsMargins(0, 0, 0, 0)
    offline_form.addRow("Schema Snapshot", offline_schema_row_widget)
    offline_form.addRow("Config Snapshot", offline_config_row_widget)
    offline_layout.addLayout(offline_form)
    layout.addWidget(offline_card)

    advanced_toggle = QToolButton()
    advanced_toggle.setObjectName("section_toggle")
    advanced_toggle.setText("추가 설정")
    advanced_toggle.setCheckable(True)
    advanced_toggle.setChecked(False)
    advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
    advanced_toggle.setAutoRaise(True)
    layout.addWidget(advanced_toggle)

    advanced_card = QFrame()
    advanced_card.setObjectName("advanced_card")
    advanced_card.hide()
    _configure_constrained_panel(advanced_card, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    advanced_layout = QVBoxLayout(advanced_card)
    _configure_card_layout(advanced_layout)

    advanced_description = QLabel("자주 바꾸지 않는 업로드 옵션입니다.")
    advanced_description.setObjectName("section_label")
    advanced_layout.addWidget(advanced_description)

    advanced_form = QFormLayout()
    _configure_form_layout(advanced_form)
    advanced_form.setContentsMargins(0, 0, 0, 0)

    for field_widget in (
        header_row,
        summary_column,
        sheet_name,
        retry_delay,
        retry_count,
        output_dir,
    ):
        _configure_form_field(field_widget)

    advanced_form.addRow("Header Row", header_row)
    advanced_form.addRow("Summary Column", summary_column)
    advanced_form.addRow("Sheet Name", sheet_name)
    advanced_form.addRow("Retry Delay", retry_delay)
    advanced_form.addRow("Max Retries", retry_count)
    advanced_form.addRow("Output Directory", output_dir)
    advanced_layout.addLayout(advanced_form)
    layout.addWidget(advanced_card)

    status_label = QLabel("")
    status_label.setObjectName("status_label")
    status_label.hide()
    _configure_constrained_panel(status_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(status_label)
    page._current_settings = initial_settings

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    load_button = QPushButton("불러오기")
    save_button = QPushButton("저장")
    next_button = QPushButton("다음")
    next_button.setObjectName("primary_button")
    next_button.setEnabled(
        bool(
            getattr(initial_settings, "offline_mode", False)
            and str(getattr(initial_settings, "offline_schema_path", "") or "").strip()
            and not gui_upload_mode_supports_update(getattr(initial_settings, "upload_mode", None))
        ) or bool(initial_settings.base_url and initial_settings.username and initial_settings.password)
    )
    buttons.addWidget(load_button)
    buttons.addWidget(save_button)
    buttons.addStretch(1)
    buttons.addWidget(next_button)
    layout.addLayout(buttons)
    layout.addStretch(1)

    def _update_next_button_state() -> None:
        blocks_offline_mode = gui_upload_mode_supports_update(upload_mode_combo.currentData())
        if mode_toggle.isChecked():
            next_button.setEnabled(
                bool(Path(offline_schema_path.text().strip()).is_file()) and not blocks_offline_mode
            )
            return
        next_button.setEnabled(bool(base_url.text().strip() and username.text().strip() and password.text()))

    def _request_settings_reflow() -> None:
        """`request_settings_reflow` 요청을 수행한다."""
        request_content_reflow = getattr(page, "request_content_reflow", None)
        if callable(request_content_reflow):
            request_content_reflow(
                allow_grow=bool(
                    mode_toggle.isChecked()
                    or advanced_toggle.isChecked()
                    or status_label.isVisible()
                )
            )

    def _sync_offline_mode_state() -> None:
        """`sync_offline_mode_state` 상태를 동기화한다."""
        is_offline = bool(mode_toggle.isChecked())
        mode_toggle.setText(_settings_mode_toggle_text(is_offline))
        mode_badge.setVisible(is_offline)
        mode_badge.setToolTip(_settings_mode_description(is_offline))
        mode_toggle.setToolTip(_settings_mode_description(is_offline))
        base_url.setEnabled(not is_offline)
        username.setEnabled(not is_offline)
        password.setEnabled(not is_offline)
        save_password.setEnabled(not is_offline)
        offline_card.setVisible(is_offline)
        offline_schema_path.setEnabled(is_offline)
        offline_schema_button.setEnabled(is_offline)
        offline_config_path.setEnabled(is_offline)
        offline_config_button.setEnabled(is_offline)
        _update_next_button_state()
        _request_settings_reflow()

    def _collect_settings():
        """`collect_settings` 정보를 수집한다."""
        current_settings = getattr(page, "_current_settings", initial_settings)
        return type(initial_settings)(
            theme_name=normalize_gui_theme_name(theme_combo.currentData()),
            upload_mode=normalize_gui_upload_mode(upload_mode_combo.currentData()),
            window_width=int(getattr(current_settings, "window_width", 1160) or 1160),
            window_height=int(getattr(current_settings, "window_height", 780) or 780),
            window_is_maximized=bool(getattr(current_settings, "window_is_maximized", False)),
            window_is_fullscreen=bool(getattr(current_settings, "window_is_fullscreen", False)),
            base_url=base_url.text().strip(),
            username=username.text().strip(),
            password=password.text(),
            save_password=save_password.isChecked(),
            offline_mode=mode_toggle.isChecked(),
            offline_schema_path=offline_schema_path.text().strip(),
            offline_tracker_configuration_path=offline_config_path.text().strip(),
            default_project_id=str(getattr(current_settings, "default_project_id", "") or ""),
            default_tracker_id=str(getattr(current_settings, "default_tracker_id", "") or ""),
            excel_header_row=header_row.value(),
            summary_column=summary_column.text().strip() or "Summary",
            excel_sheet_name=sheet_name.text().strip() or "0",
            rate_limit_retry_delay_seconds=retry_delay.value(),
            rate_limit_max_retries=retry_count.value(),
            output_dir=output_dir.text().strip() or "output",
            last_file_path=str(getattr(current_settings, "last_file_path", "") or ""),
        )

    def _set_status(message: str) -> None:
        """`set_status` 값을 설정한다."""
        status_label.setVisible(bool(message))
        status_label.setText(message)
        _request_settings_reflow()

    def _apply_settings(loaded) -> None:
        """`apply_settings` 변경을 적용한다."""
        page._current_settings = loaded
        base_url.setText(loaded.base_url)
        username.setText(loaded.username)
        password.setText(loaded.password)
        save_password.setChecked(loaded.save_password)
        _select_theme(normalize_gui_theme_name(getattr(loaded, "theme_name", None)))
        _select_upload_mode(normalize_gui_upload_mode(getattr(loaded, "upload_mode", None)))
        mode_toggle.setChecked(bool(getattr(loaded, "offline_mode", False)))
        offline_schema_path.setText(str(getattr(loaded, "offline_schema_path", "") or ""))
        offline_config_path.setText(str(getattr(loaded, "offline_tracker_configuration_path", "") or ""))
        header_row.setValue(loaded.excel_header_row)
        summary_column.setText(loaded.summary_column)
        sheet_name.setText(loaded.excel_sheet_name)
        retry_delay.setValue(loaded.rate_limit_retry_delay_seconds)
        retry_count.setValue(loaded.rate_limit_max_retries)
        output_dir.setText(loaded.output_dir)
        _sync_offline_mode_state()

    def _select_theme(theme_name: str) -> None:
        normalized_theme = normalize_gui_theme_name(theme_name)
        index = theme_combo.findData(normalized_theme)
        if index < 0:
            index = 0
        theme_combo.setCurrentIndex(index)

    def _select_upload_mode(upload_mode: str) -> None:
        normalized_mode = normalize_gui_upload_mode(upload_mode)
        index = upload_mode_combo.findData(normalized_mode)
        if index < 0:
            index = 0
        upload_mode_combo.setCurrentIndex(index)

    def _preview_theme() -> None:
        """`preview_theme` 미리보기를 계산한다."""
        if callable(on_theme_changed):
            on_theme_changed(normalize_gui_theme_name(theme_combo.currentData()))

    def _choose_snapshot_path(target_widget, *, title: str) -> None:
        """`choose_snapshot_path` 선택 동작을 처리한다."""
        start_path = target_widget.text().strip() or str(getattr(page, "_current_settings", initial_settings).last_file_path or "")
        selected, _ = QFileDialog.getOpenFileName(
            page,
            title,
            start_path,
            "JSON Files (*.json)",
        )
        if selected:
            target_widget.setText(str(selected))

    def _load():
        loaded = settings_store.load()
        _apply_settings(loaded)
        on_settings_changed(loaded)
        _set_status("설정을 불러왔습니다.")

    def _save():
        current = _collect_settings()
        page._current_settings = current
        settings_store.save(current)
        on_settings_changed(current)
        _set_status("설정을 저장했습니다.")

    def _go_next():
        """`go_next` 단계 이동을 처리한다."""
        current = _collect_settings()
        if current.offline_mode:
            if gui_upload_mode_supports_update(current.upload_mode):
                _set_status("테스트 모드에서는 기존 수정 또는 혼합 처리를 지원하지 않습니다.")
                return
            if not current.offline_schema_path:
                _set_status("테스트 모드에서는 schema snapshot JSON 경로가 필요합니다.")
                return
            if not Path(current.offline_schema_path).is_file():
                _set_status("선택한 schema snapshot JSON 파일을 찾을 수 없습니다.")
                return
            if current.offline_tracker_configuration_path and not Path(current.offline_tracker_configuration_path).is_file():
                _set_status("선택한 tracker configuration snapshot JSON 파일을 찾을 수 없습니다.")
                return
        elif not current.base_url or not current.username or not current.password:
            _set_status("Base URL, Username, Password 는 필수입니다.")
            return
        on_settings_changed(current)
        page.request_next()

    load_button.clicked.connect(_load)
    save_button.clicked.connect(_save)
    next_button.clicked.connect(_go_next)
    base_url.textChanged.connect(lambda _: _update_next_button_state())
    username.textChanged.connect(lambda _: _update_next_button_state())
    password.textChanged.connect(lambda _: _update_next_button_state())
    mode_toggle.toggled.connect(lambda _: _sync_offline_mode_state())
    offline_schema_button.clicked.connect(
        lambda: _choose_snapshot_path(offline_schema_path, title="테스트 schema snapshot 선택")
    )
    offline_config_button.clicked.connect(
        lambda: _choose_snapshot_path(offline_config_path, title="테스트 tracker configuration 선택")
    )
    offline_schema_path.textChanged.connect(lambda _: _update_next_button_state())
    upload_mode_combo.currentIndexChanged.connect(lambda _: _update_next_button_state())
    theme_combo.currentIndexChanged.connect(lambda _: _preview_theme())
    advanced_toggle.toggled.connect(
        lambda checked: (
            advanced_card.setVisible(checked),
            advanced_toggle.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
            ),
            _request_settings_reflow(),
        )
    )

    for theme_key, theme_label in GUI_THEME_CHOICES:
        theme_combo.addItem(theme_label, theme_key)
    for upload_mode, upload_mode_label in _settings_upload_mode_choices():
        upload_mode_combo.addItem(upload_mode_label, upload_mode)
    _select_theme(normalize_gui_theme_name(getattr(initial_settings, "theme_name", None)))
    _select_upload_mode(normalize_gui_upload_mode(getattr(initial_settings, "upload_mode", None)))
    _sync_offline_mode_state()
    page.get_settings = _collect_settings
    page.set_settings = _apply_settings
    return page


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
    qt["Qt"]

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
            message = f"프로젝트 조회 실패: {exc}"
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
            message = f"트래커 조회 실패: {exc}"
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


