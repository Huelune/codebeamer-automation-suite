from __future__ import annotations

import contextlib
from copy import deepcopy
from datetime import UTC
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QDoubleSpinBox
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QFormLayout
from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QScrollArea
from PySide6.QtWidgets import QSpinBox
from PySide6.QtWidgets import QStackedWidget
from PySide6.QtWidgets import QVBoxLayout
from PySide6.QtWidgets import QWidget

from src.api_monitor import API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
from src.api_monitor import API_MONITOR_MAX_SLOW_THRESHOLD_MS
from src.api_monitor import API_MONITOR_MIN_SLOW_THRESHOLD_MS

from .settings_store import CREDENTIAL_STORAGE_LOCAL
from .settings_store import CREDENTIAL_STORAGE_NONE
from .settings_store import CREDENTIAL_STORAGE_OS
from .settings_store import ConnectionProfile
from .settings_store import GuiSettings
from .settings_store import GuiSettingsStore
from .settings_store import effective_gui_settings
from .settings_store import profile_validation_signature
from .settings_store import test_mode_validation_signature
from .styles import DEFAULT_GUI_THEME
from .styles import GUI_THEME_CHOICES
from .styles import normalize_gui_theme_name
from .worker import BackgroundTask


SETTINGS_CATEGORY_CONNECTION = "connection"
SETTINGS_CATEGORY_APPEARANCE = "appearance"
SETTINGS_CATEGORY_NETWORK_STORAGE = "network_storage"
SETTINGS_CATEGORY_TEST_MODE = "test_mode"
SETTINGS_CATEGORY_DEVELOPER = "developer"
SETTINGS_CATEGORY_DATA = "data"

SETTINGS_CATEGORY_LABELS = {
    SETTINGS_CATEGORY_CONNECTION: "연결",
    SETTINGS_CATEGORY_APPEARANCE: "화면",
    SETTINGS_CATEGORY_NETWORK_STORAGE: "네트워크·저장소",
    SETTINGS_CATEGORY_TEST_MODE: "테스트 모드",
    SETTINGS_CATEGORY_DEVELOPER: "개발자",
    SETTINGS_CATEGORY_DATA: "데이터 관리",
}


class SettingsCenterPage(QWidget):
    """전역 연결·화면·테스트 설정을 명시적으로 저장하고 적용한다."""

    def __init__(
        self,
        settings_store: GuiSettingsStore,
        *,
        on_applied=None,
        connection_tester=None,
        api_monitor_requested=None,
        busy_started=None,
        busy_finished=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_center_page")
        self.settings_store = settings_store
        self.on_applied = on_applied
        self.connection_tester = connection_tester
        self.api_monitor_requested = api_monitor_requested
        self.busy_started = busy_started
        self.busy_finished = busy_finished
        self.persisted_settings = settings_store.ensure_app_settings()
        self.draft_settings = deepcopy(self.persisted_settings)
        self.current_category = SETTINGS_CATEGORY_CONNECTION
        self.selected_profile_id = (
            self.draft_settings.active_profile_id
            or (self.draft_settings.profiles[0].profile_id if self.draft_settings.profiles else "")
        )
        self.leave_decision_callback = None
        self._dirty = False
        self._updating_controls = False
        self._validation_task = None
        self._validation_busy_token = None
        self._build_ui()
        self._load_draft_into_controls()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 18, 20, 16)
        root_layout.setSpacing(12)

        heading_layout = QHBoxLayout()
        heading_layout.setSpacing(10)
        title = QLabel("설정")
        title.setObjectName("application_route_title")
        heading_layout.addWidget(title)
        self.dirty_badge = QLabel("저장되지 않은 변경")
        self.dirty_badge.setObjectName("settings_dirty_badge")
        self.dirty_badge.hide()
        heading_layout.addWidget(self.dirty_badge)
        heading_layout.addStretch(1)
        self.applied_mode_label = QLabel("")
        self.applied_mode_label.setObjectName("application_phase_badge")
        heading_layout.addWidget(self.applied_mode_label)
        root_layout.addLayout(heading_layout)

        description = QLabel(
            "연결과 앱 전역 설정을 관리합니다. 변경은 자동 저장되지 않으며, "
            "검증·저장 후 적용해야 현재 작업에 반영됩니다."
        )
        description.setObjectName("application_route_description")
        description.setWordWrap(True)
        root_layout.addWidget(description)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(10)

        navigation = QFrame(self)
        navigation.setObjectName("settings_category_navigation")
        navigation.setMinimumWidth(155)
        navigation.setMaximumWidth(195)
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(8, 10, 8, 10)
        navigation_layout.setSpacing(5)
        navigation_title = QLabel("설정 영역")
        navigation_title.setObjectName("application_navigation_title")
        navigation_layout.addWidget(navigation_title)
        self.category_buttons: dict[str, QPushButton] = {}
        for category, label in SETTINGS_CATEGORY_LABELS.items():
            button = QPushButton(label)
            button.setObjectName("settings_category_button")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, selected=category: self.show_category(selected)
            )
            navigation_layout.addWidget(button)
            self.category_buttons[category] = button
        navigation_layout.addStretch(1)
        body_layout.addWidget(navigation)

        self.category_stack = QStackedWidget(self)
        self.category_stack.setObjectName("settings_category_stack")
        self.category_pages = {
            SETTINGS_CATEGORY_CONNECTION: self._build_connection_page(),
            SETTINGS_CATEGORY_APPEARANCE: self._build_appearance_page(),
            SETTINGS_CATEGORY_NETWORK_STORAGE: self._build_network_storage_page(),
            SETTINGS_CATEGORY_TEST_MODE: self._build_test_mode_page(),
            SETTINGS_CATEGORY_DEVELOPER: self._build_developer_page(),
            SETTINGS_CATEGORY_DATA: self._build_data_page(),
        }
        for category in SETTINGS_CATEGORY_LABELS:
            self.category_stack.addWidget(self._wrap_scroll(self.category_pages[category]))
        body_layout.addWidget(self.category_stack, 1)
        root_layout.addLayout(body_layout, 1)

        footer = QFrame(self)
        footer.setObjectName("settings_footer")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 9, 12, 9)
        footer_layout.setSpacing(7)
        self.status_label = QLabel("")
        self.status_label.setObjectName("settings_status_label")
        self.status_label.setWordWrap(True)
        footer_layout.addWidget(self.status_label)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(7)
        self.reset_category_button = QPushButton("현재 영역 초기화")
        self.validate_button = QPushButton("연결 테스트")
        self.save_button = QPushButton("저장")
        self.apply_button = QPushButton("적용")
        self.apply_button.setObjectName("primary_button")
        action_layout.addWidget(self.reset_category_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.validate_button)
        action_layout.addWidget(self.save_button)
        action_layout.addWidget(self.apply_button)
        footer_layout.addLayout(action_layout)
        root_layout.addWidget(footer)

        self.reset_category_button.clicked.connect(self.reset_current_category)
        self.validate_button.clicked.connect(self.start_validation)
        self.save_button.clicked.connect(self.save_changes)
        self.apply_button.clicked.connect(self.apply_saved_settings)

    def _wrap_scroll(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setObjectName("settings_scroll_area")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def _new_category_page(title_text: str, description_text: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("settings_category_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        title = QLabel(title_text)
        title.setObjectName("settings_category_title")
        description = QLabel(description_text)
        description.setObjectName("application_route_description")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)
        return page, layout

    @staticmethod
    def _new_card(parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("settings_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(8)
        return card, layout

    @staticmethod
    def _configure_form(form: QFormLayout) -> None:
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(7)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    def _build_connection_page(self) -> QWidget:
        page, layout = self._new_category_page(
            "연결 프로필",
            "이름이 있는 여러 Codebeamer 연결을 관리하고, 현재 작업에서 사용할 "
            "활성 프로필 하나를 선택합니다.",
        )

        selector_card, selector_layout = self._new_card(page)
        selector_row = QHBoxLayout()
        selector_row.setSpacing(7)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(150)
        self.profile_add_button = QPushButton("추가")
        self.profile_remove_button = QPushButton("삭제")
        self.profile_remove_button.setObjectName("danger_button")
        self.profile_activate_button = QPushButton("활성 프로필로 지정")
        selector_row.addWidget(self.profile_combo, 1)
        selector_row.addWidget(self.profile_add_button)
        selector_row.addWidget(self.profile_remove_button)
        selector_layout.addLayout(selector_row)
        state_row = QHBoxLayout()
        state_row.setSpacing(7)
        self.profile_state_label = QLabel("")
        self.profile_state_label.setObjectName("section_label")
        self.profile_state_label.setWordWrap(True)
        state_row.addWidget(self.profile_state_label, 1)
        state_row.addWidget(self.profile_activate_button)
        selector_layout.addLayout(state_row)
        layout.addWidget(selector_card)

        details_card, details_layout = self._new_card(page)
        form = QFormLayout()
        self._configure_form(form)
        self.profile_name_edit = QLineEdit()
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://codebeamer.example.com")
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.credential_storage_combo = QComboBox()
        self.credential_storage_combo.addItem("로컬 암호화 파일", CREDENTIAL_STORAGE_LOCAL)
        os_label = (
            "OS 자격증명 저장소"
            if self.settings_store.os_credential_available
            else "OS 자격증명 저장소 (현재 환경에서 사용 불가)"
        )
        self.credential_storage_combo.addItem(os_label, CREDENTIAL_STORAGE_OS)
        if not self.settings_store.os_credential_available:
            model_item = self.credential_storage_combo.model().item(1)
            if model_item is not None:
                model_item.setEnabled(False)
        self.credential_storage_combo.addItem("저장하지 않음", CREDENTIAL_STORAGE_NONE)
        self.server_wiki_html_checkbox = QCheckBox("서버 Wiki HTML 렌더링 사용")
        form.addRow("프로필 이름", self.profile_name_edit)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        form.addRow("비밀번호 저장", self.credential_storage_combo)
        form.addRow("Wiki HTML", self.server_wiki_html_checkbox)
        details_layout.addLayout(form)
        self.wiki_html_help_label = QLabel(
            "서버가 /v3/projects/{projectId}/wiki2html을 제공할 때만 켜세요. "
            "끄면 서버 호출 없이 제한된 로컬 Wiki 렌더러를 사용합니다."
        )
        self.wiki_html_help_label.setObjectName("section_label")
        self.wiki_html_help_label.setWordWrap(True)
        details_layout.addWidget(self.wiki_html_help_label)
        self.credential_help_label = QLabel("")
        self.credential_help_label.setObjectName("section_label")
        self.credential_help_label.setWordWrap(True)
        details_layout.addWidget(self.credential_help_label)
        layout.addWidget(details_card)
        layout.addStretch(1)

        self.profile_combo.currentIndexChanged.connect(self._select_profile_from_combo)
        self.profile_add_button.clicked.connect(self.add_profile)
        self.profile_remove_button.clicked.connect(self._request_remove_profile)
        self.profile_activate_button.clicked.connect(self.activate_selected_profile)
        self.profile_name_edit.textChanged.connect(self._profile_fields_changed)
        self.base_url_edit.textChanged.connect(self._profile_fields_changed)
        self.username_edit.textChanged.connect(self._profile_fields_changed)
        self.password_edit.textChanged.connect(self._profile_fields_changed)
        self.credential_storage_combo.currentIndexChanged.connect(
            self._profile_fields_changed
        )
        self.server_wiki_html_checkbox.toggled.connect(self._profile_fields_changed)
        return page

    def _build_appearance_page(self) -> QWidget:
        page, layout = self._new_category_page(
            "화면",
            "테마는 저장 후 적용할 때 앱 전체와 배치 작업에 함께 반영됩니다.",
        )
        card, card_layout = self._new_card(page)
        form = QFormLayout()
        self._configure_form(form)
        self.theme_combo = QComboBox()
        for value, label in GUI_THEME_CHOICES:
            self.theme_combo.addItem(label, value)
        form.addRow("테마", self.theme_combo)
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        self.theme_combo.currentIndexChanged.connect(self._appearance_changed)
        return page

    def _build_network_storage_page(self) -> QWidget:
        page, layout = self._new_category_page(
            "네트워크·저장소",
            "조회와 업로드에서 함께 쓰는 재시도 정책과 기본 출력 위치를 관리합니다.",
        )
        card, card_layout = self._new_card(page)
        form = QFormLayout()
        self._configure_form(form)
        self.retry_delay_spin = QDoubleSpinBox()
        self.retry_delay_spin.setRange(0.0, 3600.0)
        self.retry_delay_spin.setDecimals(2)
        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(0, 999)
        self.output_dir_edit = QLineEdit()
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)
        self.output_dir_button = QPushButton("폴더 선택")
        output_layout.addWidget(self.output_dir_edit, 1)
        output_layout.addWidget(self.output_dir_button)
        form.addRow("Retry Delay", self.retry_delay_spin)
        form.addRow("Max Retries", self.retry_count_spin)
        form.addRow("Output Directory", output_row)
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        self.retry_delay_spin.valueChanged.connect(self._network_storage_changed)
        self.retry_count_spin.valueChanged.connect(self._network_storage_changed)
        self.output_dir_edit.textChanged.connect(self._network_storage_changed)
        self.output_dir_button.clicked.connect(self._choose_output_directory)
        return page

    def _build_test_mode_page(self) -> QWidget:
        page, layout = self._new_category_page(
            "테스트 모드",
            "전역 토글을 켜면 실제 서버 대신 익명 snapshot을 사용하고 모든 업로드를 "
            "Dry Run으로 제한합니다.",
        )
        card, card_layout = self._new_card(page)
        self.test_mode_checkbox = QCheckBox("테스트 모드 사용")
        self.test_mode_checkbox.setObjectName("settings_test_mode_toggle")
        card_layout.addWidget(self.test_mode_checkbox)

        form = QFormLayout()
        self._configure_form(form)
        self.schema_path_edit = QLineEdit()
        self.schema_path_button = QPushButton("파일 선택")
        schema_row = QWidget()
        schema_layout = QHBoxLayout(schema_row)
        schema_layout.setContentsMargins(0, 0, 0, 0)
        schema_layout.setSpacing(6)
        schema_layout.addWidget(self.schema_path_edit, 1)
        schema_layout.addWidget(self.schema_path_button)
        self.tracker_config_path_edit = QLineEdit()
        self.tracker_config_path_button = QPushButton("파일 선택")
        config_row = QWidget()
        config_layout = QHBoxLayout(config_row)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(6)
        config_layout.addWidget(self.tracker_config_path_edit, 1)
        config_layout.addWidget(self.tracker_config_path_button)
        self.query_data_path_edit = QLineEdit()
        self.query_data_path_button = QPushButton("파일 선택")
        query_data_row = QWidget()
        query_data_layout = QHBoxLayout(query_data_row)
        query_data_layout.setContentsMargins(0, 0, 0, 0)
        query_data_layout.setSpacing(6)
        query_data_layout.addWidget(self.query_data_path_edit, 1)
        query_data_layout.addWidget(self.query_data_path_button)
        form.addRow("Schema Snapshot", schema_row)
        form.addRow("Config Snapshot", config_row)
        form.addRow("조회 데이터 Snapshot", query_data_row)
        card_layout.addLayout(form)
        self.test_mode_help_label = QLabel("")
        self.test_mode_help_label.setObjectName("section_label")
        self.test_mode_help_label.setWordWrap(True)
        card_layout.addWidget(self.test_mode_help_label)
        layout.addWidget(card)
        layout.addStretch(1)

        self.test_mode_checkbox.toggled.connect(self._test_mode_changed)
        self.schema_path_edit.textChanged.connect(self._test_mode_changed)
        self.tracker_config_path_edit.textChanged.connect(self._test_mode_changed)
        self.query_data_path_edit.textChanged.connect(self._test_mode_changed)
        self.schema_path_button.clicked.connect(
            lambda: self._choose_snapshot_file(self.schema_path_edit, "Schema Snapshot 선택")
        )
        self.tracker_config_path_button.clicked.connect(
            lambda: self._choose_snapshot_file(
                self.tracker_config_path_edit,
                "Tracker Configuration Snapshot 선택",
            )
        )
        self.query_data_path_button.clicked.connect(
            lambda: self._choose_snapshot_file(
                self.query_data_path_edit,
                "트래커 조회 데이터 Snapshot 선택",
            )
        )
        return page

    def _build_data_page(self) -> QWidget:
        page, layout = self._new_category_page(
            "데이터 관리",
            "설정 파일에는 연결 메타데이터만 포함하며 비밀번호·토큰·암호화 "
            "credential 값은 내보내지 않습니다.",
        )
        card, card_layout = self._new_card(page)
        self.migration_label = QLabel("")
        self.migration_label.setObjectName("section_label")
        self.migration_label.setWordWrap(True)
        card_layout.addWidget(self.migration_label)
        action_row = QHBoxLayout()
        action_row.setSpacing(7)
        self.import_button = QPushButton("설정 가져오기")
        self.export_button = QPushButton("설정 내보내기")
        action_row.addWidget(self.import_button)
        action_row.addWidget(self.export_button)
        action_row.addStretch(1)
        card_layout.addLayout(action_row)
        layout.addWidget(card)
        layout.addStretch(1)
        self.import_button.clicked.connect(self._choose_import_path)
        self.export_button.clicked.connect(self._choose_export_path)
        return page

    def _build_developer_page(self) -> QWidget:
        page, layout = self._new_category_page(
            "개발자",
            "세션 진단 로그와 Codebeamer API 호출 메타데이터를 별도 개발자 도구 "
            "창에서 확인합니다. 인증 정보와 요청·응답 본문은 수집하지 않습니다.",
        )
        card, card_layout = self._new_card(page)
        self.api_monitor_checkbox = QCheckBox("API 모니터 사용")
        self.api_monitor_checkbox.setObjectName("settings_api_monitor_toggle")
        card_layout.addWidget(self.api_monitor_checkbox)

        form = QFormLayout()
        self._configure_form(form)
        self.api_monitor_slow_threshold_spin = QSpinBox()
        self.api_monitor_slow_threshold_spin.setRange(
            API_MONITOR_MIN_SLOW_THRESHOLD_MS,
            API_MONITOR_MAX_SLOW_THRESHOLD_MS,
        )
        self.api_monitor_slow_threshold_spin.setSuffix(" ms")
        form.addRow("느린 요청 기준", self.api_monitor_slow_threshold_spin)
        card_layout.addLayout(form)

        help_label = QLabel(
            "진단 로그는 현재 세션에서 최대 2,000건, API 모니터는 최근 최대 500건을 "
            "메모리에만 보관합니다. API 모니터 설정을 꺼도 진단 로그는 계속 사용할 수 "
            "있으며, 원본 서버 응답과 Excel 값은 수집하지 않습니다."
        )
        help_label.setObjectName("section_label")
        help_label.setWordWrap(True)
        card_layout.addWidget(help_label)

        action_row = QHBoxLayout()
        self.api_monitor_open_button = QPushButton("개발자 도구 열기")
        self.api_monitor_open_button.setObjectName("primary_button")
        action_row.addWidget(self.api_monitor_open_button)
        action_row.addStretch(1)
        card_layout.addLayout(action_row)
        layout.addWidget(card)
        layout.addStretch(1)

        self.api_monitor_checkbox.toggled.connect(self._developer_changed)
        self.api_monitor_slow_threshold_spin.valueChanged.connect(
            self._developer_changed
        )
        self.api_monitor_open_button.clicked.connect(self._request_api_monitor)
        return page

    def show_category(self, category: str) -> None:
        if category not in self.category_pages:
            raise ValueError(f"알 수 없는 설정 영역입니다: {category}")
        self.current_category = category
        self.category_stack.setCurrentIndex(list(SETTINGS_CATEGORY_LABELS).index(category))
        for item, button in self.category_buttons.items():
            button.setChecked(item == category)
        self.reset_category_button.setEnabled(category != SETTINGS_CATEGORY_DATA)
        self._refresh_validation_controls()

    def _active_profile(self) -> ConnectionProfile | None:
        return self.draft_settings.active_profile()

    def _selected_profile(self) -> ConnectionProfile | None:
        for profile in self.draft_settings.profiles:
            if profile.profile_id == self.selected_profile_id:
                return profile
        return None

    def _load_draft_into_controls(self) -> None:
        self._updating_controls = True
        try:
            self._refresh_profile_combo()
            theme_index = self.theme_combo.findData(
                normalize_gui_theme_name(self.draft_settings.theme_name)
            )
            self.theme_combo.setCurrentIndex(max(theme_index, 0))
            self.retry_delay_spin.setValue(
                float(self.draft_settings.rate_limit_retry_delay_seconds or 0)
            )
            self.retry_count_spin.setValue(
                int(self.draft_settings.rate_limit_max_retries or 0)
            )
            self.output_dir_edit.setText(str(self.draft_settings.output_dir or "output"))
            self.test_mode_checkbox.setChecked(bool(self.draft_settings.offline_mode))
            self.schema_path_edit.setText(str(self.draft_settings.offline_schema_path or ""))
            self.tracker_config_path_edit.setText(
                str(self.draft_settings.offline_tracker_configuration_path or "")
            )
            self.query_data_path_edit.setText(
                str(self.draft_settings.offline_query_data_path or "")
            )
            self.api_monitor_checkbox.setChecked(
                bool(self.draft_settings.api_monitor_enabled)
            )
            self.api_monitor_slow_threshold_spin.setValue(
                int(
                    self.draft_settings.api_monitor_slow_threshold_ms
                    or API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
                )
            )
        finally:
            self._updating_controls = False
        self._load_selected_profile_controls()
        self._sync_test_mode_controls()
        self._sync_developer_controls()
        self.migration_label.setText(
            "기존 gui_settings.json 및 workflow preset을 보존한 상태로 "
            "새 전역 설정 구조를 사용합니다."
            if self.draft_settings.migrated_from_legacy
            else "새 전역 설정 형식을 사용 중입니다."
        )
        self._update_dirty_state(False)
        self._refresh_applied_mode_label()
        self.show_category(self.current_category)

    def _refresh_profile_combo(self) -> None:
        previous_id = self.selected_profile_id
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.draft_settings.profiles:
            suffix = " · 활성" if profile.profile_id == self.draft_settings.active_profile_id else ""
            self.profile_combo.addItem(
                f"{profile.name or '이름 없는 연결'}{suffix}", profile.profile_id
            )
        selected_index = self.profile_combo.findData(previous_id)
        if selected_index < 0 and self.profile_combo.count() > 0:
            selected_index = 0
        self.profile_combo.setCurrentIndex(selected_index)
        self.profile_combo.blockSignals(False)
        self.selected_profile_id = str(self.profile_combo.currentData() or "")

    def _load_selected_profile_controls(self) -> None:
        profile = self._selected_profile()
        self._updating_controls = True
        try:
            enabled = profile is not None
            for widget in (
                self.profile_name_edit,
                self.base_url_edit,
                self.username_edit,
                self.password_edit,
                self.credential_storage_combo,
                self.server_wiki_html_checkbox,
                self.profile_remove_button,
                self.profile_activate_button,
            ):
                widget.setEnabled(enabled)
            self.profile_activate_button.setEnabled(
                enabled
                and profile is not None
                and profile.profile_id != self.draft_settings.active_profile_id
            )
            if profile is None:
                self.profile_name_edit.clear()
                self.base_url_edit.clear()
                self.username_edit.clear()
                self.password_edit.clear()
                self.profile_state_label.setText(
                    "연결 프로필이 없습니다. '추가'로 첫 프로필을 만들 수 있습니다."
                )
                self.credential_help_label.setText("")
                self.server_wiki_html_checkbox.setChecked(False)
                return
            self.profile_name_edit.setText(profile.name)
            self.base_url_edit.setText(profile.base_url)
            self.username_edit.setText(profile.username)
            self.password_edit.setText(profile.password)
            self.server_wiki_html_checkbox.setChecked(
                bool(profile.server_wiki_html_enabled)
            )
            storage_index = self.credential_storage_combo.findData(
                profile.credential_storage
            )
            self.credential_storage_combo.setCurrentIndex(max(storage_index, 0))
        finally:
            self._updating_controls = False
        self._refresh_profile_status()

    def _refresh_profile_status(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        is_active = profile.profile_id == self.draft_settings.active_profile_id
        current_signature = profile_validation_signature(profile)
        is_validated = bool(
            profile.validated_signature
            and profile.validated_signature == current_signature
            and not profile.credential_error
        )
        state_parts = ["활성 프로필" if is_active else "비활성 프로필"]
        state_parts.append("검증 완료" if is_validated else "검증 필요")
        if profile.credential_error:
            state_parts.append("자격증명 복원 실패")
        self.profile_state_label.setText(" · ".join(state_parts))
        storage = profile.credential_storage
        if profile.credential_error:
            help_text = self._safe_message(profile.credential_error)
        elif storage == CREDENTIAL_STORAGE_LOCAL:
            help_text = (
                "기본 방식입니다. 앱 전용 키로 암호화한 뒤 로컬 설정 영역에 저장합니다."
            )
        elif storage == CREDENTIAL_STORAGE_OS:
            help_text = (
                "운영체제 자격증명 저장소에 저장하며 설정 파일에는 "
                "비밀번호가 포함되지 않습니다."
            )
        else:
            help_text = "앱을 종료하면 비밀번호를 복원하지 않습니다."
        if not self.settings_store.os_credential_available:
            help_text = f"{help_text} OS 저장소는 현재 환경에서 선택할 수 없습니다."
        self.credential_help_label.setText(help_text)

    def _select_profile_from_combo(self, _index: int) -> None:
        if self._updating_controls:
            return
        self.selected_profile_id = str(self.profile_combo.currentData() or "")
        self._load_selected_profile_controls()
        self._refresh_validation_controls()

    def add_profile(self) -> None:
        ordinal = len(self.draft_settings.profiles) + 1
        profile = ConnectionProfile(name=f"새 연결 {ordinal}")
        self.draft_settings.profiles.append(profile)
        if not self.draft_settings.active_profile_id:
            self.draft_settings.active_profile_id = profile.profile_id
        self.selected_profile_id = profile.profile_id
        self._refresh_profile_combo()
        self._load_selected_profile_controls()
        self._mark_dirty("connection")

    def _request_remove_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        answer = QMessageBox.question(
            self,
            "연결 프로필 삭제",
            f"'{profile.name}' 프로필을 삭제하시겠습니까? "
            "저장 전에는 변경 취소할 수 있습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.remove_selected_profile()

    def remove_selected_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self.draft_settings.profiles = [
            item for item in self.draft_settings.profiles if item.profile_id != profile.profile_id
        ]
        if self.draft_settings.active_profile_id == profile.profile_id:
            self.draft_settings.active_profile_id = (
                self.draft_settings.profiles[0].profile_id
                if self.draft_settings.profiles
                else ""
            )
        self.selected_profile_id = self.draft_settings.active_profile_id
        self._refresh_profile_combo()
        self._load_selected_profile_controls()
        self._mark_dirty("connection")

    def activate_selected_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None or profile.profile_id == self.draft_settings.active_profile_id:
            return
        self.draft_settings.active_profile_id = profile.profile_id
        self._refresh_profile_combo()
        self._load_selected_profile_controls()
        self._mark_dirty("connection")

    def _profile_fields_changed(self, *_args) -> None:
        if self._updating_controls:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        previous_signature = profile_validation_signature(profile)
        profile.name = self.profile_name_edit.text().strip()
        profile.base_url = self.base_url_edit.text().strip()
        profile.username = self.username_edit.text().strip()
        profile.password = self.password_edit.text()
        profile.credential_storage = str(
            self.credential_storage_combo.currentData() or CREDENTIAL_STORAGE_LOCAL
        )
        profile.server_wiki_html_enabled = bool(
            self.server_wiki_html_checkbox.isChecked()
        )
        if profile_validation_signature(profile) != previous_signature:
            profile.validated_signature = ""
            profile.validated_at = ""
        profile.credential_error = ""
        self._refresh_profile_combo()
        self._refresh_profile_status()
        self._mark_dirty("connection")

    def _appearance_changed(self, *_args) -> None:
        if self._updating_controls:
            return
        self.draft_settings.theme_name = normalize_gui_theme_name(
            self.theme_combo.currentData()
        )
        self._mark_dirty("appearance")

    def _network_storage_changed(self, *_args) -> None:
        if self._updating_controls:
            return
        self.draft_settings.rate_limit_retry_delay_seconds = float(
            self.retry_delay_spin.value()
        )
        self.draft_settings.rate_limit_max_retries = int(self.retry_count_spin.value())
        self.draft_settings.output_dir = self.output_dir_edit.text().strip() or "output"
        self._mark_dirty("network_storage")

    def _test_mode_changed(self, *_args) -> None:
        if self._updating_controls:
            return
        self.draft_settings.offline_mode = bool(self.test_mode_checkbox.isChecked())
        self.draft_settings.offline_schema_path = self.schema_path_edit.text().strip()
        self.draft_settings.offline_tracker_configuration_path = (
            self.tracker_config_path_edit.text().strip()
        )
        self.draft_settings.offline_query_data_path = self.query_data_path_edit.text().strip()
        self.draft_settings.test_mode_validated_signature = ""
        self.draft_settings.test_mode_validated_at = ""
        self._sync_test_mode_controls()
        self._mark_dirty("test_mode")

    def _developer_changed(self, *_args) -> None:
        if self._updating_controls:
            return
        self.draft_settings.api_monitor_enabled = bool(
            self.api_monitor_checkbox.isChecked()
        )
        self.draft_settings.api_monitor_slow_threshold_ms = int(
            self.api_monitor_slow_threshold_spin.value()
        )
        self._sync_developer_controls()
        self._mark_dirty("developer")

    def _sync_developer_controls(self) -> None:
        enabled = bool(self.api_monitor_checkbox.isChecked())
        self.api_monitor_slow_threshold_spin.setEnabled(enabled)
        self.api_monitor_open_button.setEnabled(True)

    def _request_api_monitor(self) -> None:
        if callable(self.api_monitor_requested):
            self.api_monitor_requested()

    def _sync_test_mode_controls(self) -> None:
        enabled = bool(self.test_mode_checkbox.isChecked())
        for widget in (
            self.schema_path_edit,
            self.schema_path_button,
            self.tracker_config_path_edit,
            self.tracker_config_path_button,
            self.query_data_path_edit,
            self.query_data_path_button,
        ):
            widget.setEnabled(enabled)
        signature = test_mode_validation_signature(self.draft_settings)
        validated = bool(
            self.draft_settings.test_mode_validated_signature
            and self.draft_settings.test_mode_validated_signature == signature
        )
        if not enabled:
            self.test_mode_help_label.setText("현재는 활성 온라인 연결 프로필을 사용합니다.")
        elif validated:
            self.test_mode_help_label.setText("현재 snapshot 조합은 검증되었습니다.")
        else:
            self.test_mode_help_label.setText(
                "snapshot 경로를 지정하고 검증해야 적용할 수 있습니다."
            )
        self._refresh_validation_controls()

    def _choose_snapshot_file(self, target: QLineEdit, title: str) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            title,
            target.text().strip() or str(self.settings_store.root_dir),
            "JSON Files (*.json);;All Files (*)",
        )
        if selected:
            target.setText(selected)

    def _choose_output_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "기본 출력 폴더 선택",
            self.output_dir_edit.text().strip() or str(self.settings_store.root_dir),
        )
        if selected:
            self.output_dir_edit.setText(selected)

    def _mark_dirty(self, _category: str) -> None:
        self._update_dirty_state(True)
        self.status_label.setText("저장되지 않은 변경이 있습니다.")

    def _update_dirty_state(self, dirty: bool) -> None:
        self._dirty = bool(dirty)
        self.dirty_badge.setVisible(self._dirty)
        self.save_button.setEnabled(self._dirty and self._validation_task is None)
        self._refresh_validation_controls()

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def _validation_is_current(self) -> bool:
        if self.draft_settings.offline_mode:
            expected = test_mode_validation_signature(self.draft_settings)
            return bool(
                self.draft_settings.test_mode_validated_signature
                and self.draft_settings.test_mode_validated_signature == expected
            )
        profile = self._active_profile()
        if profile is None:
            return True
        if not (profile.base_url or profile.username or profile.password):
            return True
        expected = profile_validation_signature(profile)
        return bool(profile.validated_signature and profile.validated_signature == expected)

    def _refresh_validation_controls(self) -> None:
        if not hasattr(self, "validate_button"):
            return
        is_testing = self._validation_task is not None
        self.validate_button.setText(
            "Snapshot 검증" if self.draft_settings.offline_mode else "연결 테스트"
        )
        self.validate_button.setEnabled(not is_testing)
        self.apply_button.setEnabled(
            not is_testing and not self._dirty and self._validation_is_current()
        )
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(self._dirty and not is_testing)

    def _effective_draft_settings(self) -> GuiSettings:
        return effective_gui_settings(self.draft_settings, self.settings_store.load())

    def _prevalidate(self) -> None:
        if self.draft_settings.offline_mode:
            schema_path = Path(self.draft_settings.offline_schema_path).expanduser()
            if not schema_path.is_file():
                raise ValueError("Schema Snapshot 파일을 확인해야 합니다.")
            configuration_path = str(
                self.draft_settings.offline_tracker_configuration_path or ""
            ).strip()
            if configuration_path and not Path(configuration_path).expanduser().is_file():
                raise ValueError("Config Snapshot 파일을 확인해야 합니다.")
            query_data_path = str(self.draft_settings.offline_query_data_path or "").strip()
            if query_data_path and not Path(query_data_path).expanduser().is_file():
                raise ValueError("조회 데이터 Snapshot 파일을 확인해야 합니다.")
            return
        profile = self._active_profile()
        if profile is None:
            raise ValueError("활성 연결 프로필을 먼저 추가해야 합니다.")
        if not profile.base_url or not profile.username or not profile.password:
            raise ValueError("활성 프로필의 Base URL, Username, Password를 모두 입력해야 합니다.")
        if profile.credential_error:
            raise ValueError("활성 프로필의 자격증명을 복원하지 못했습니다.")

    def start_validation(self) -> None:
        if self._validation_task is not None:
            return
        try:
            self._prevalidate()
        except Exception as exc:
            self.status_label.setText(self._safe_message(exc))
            return
        if not callable(self.connection_tester):
            self.status_label.setText("연결 검증 기능을 사용할 수 없습니다.")
            return

        settings = self._effective_draft_settings()
        self.status_label.setText(
            "Snapshot을 검증하는 중입니다."
            if settings.offline_mode
            else "Codebeamer 연결을 검증하는 중입니다."
        )
        task = BackgroundTask(self.connection_tester, settings)
        self._validation_task = task
        task.completed.connect(self._validation_completed)
        task.failed.connect(self._validation_failed)
        self._refresh_validation_controls()
        if callable(self.busy_started):
            message = (
                "테스트 Snapshot을 검증하는 중입니다."
                if settings.offline_mode
                else "Codebeamer 연결 응답을 기다리는 중입니다."
            )
            try:
                self._validation_busy_token = self.busy_started(message)
            except Exception:
                self._validation_busy_token = None
        try:
            task.start()
        except Exception as exc:
            self.status_label.setText(f"검증 실패: {self._safe_message(exc)}")
            self._finish_validation_task()

    def _validation_completed(self, result) -> None:
        try:
            self._record_validation_success()
            count = len(result) if isinstance(result, list) else 0
            detail = f" 접근 가능한 프로젝트 {count}개를 확인했습니다." if count else ""
            self.status_label.setText(f"검증에 성공했습니다.{detail} 저장 후 적용할 수 있습니다.")
        finally:
            self._finish_validation_task()

    def _validation_failed(self, error) -> None:
        self.status_label.setText(f"검증 실패: {self._safe_message(error)}")
        self._finish_validation_task()

    def _record_validation_success(self) -> None:
        validated_at = datetime.now(UTC).isoformat(timespec="seconds")
        if self.draft_settings.offline_mode:
            self.draft_settings.test_mode_validated_signature = (
                test_mode_validation_signature(self.draft_settings)
            )
            self.draft_settings.test_mode_validated_at = validated_at
        else:
            profile = self._active_profile()
            if profile is None:
                raise ValueError("활성 연결 프로필이 없습니다.")
            profile.validated_signature = profile_validation_signature(profile)
            profile.validated_at = validated_at
        self._update_dirty_state(True)
        self._refresh_profile_status()
        self._sync_test_mode_controls()

    def _finish_validation_task(self) -> None:
        task = self._validation_task
        self._validation_task = None
        busy_token = self._validation_busy_token
        self._validation_busy_token = None
        if busy_token is not None and callable(self.busy_finished):
            # 이미 삭제된 위젯이면 RuntimeError, 시그니처가 맞지 않으면 TypeError 가 난다.
            with contextlib.suppress(RuntimeError, TypeError):
                self.busy_finished(busy_token)
        if task is not None:
            task.deleteLater()
        self._refresh_validation_controls()

    def _validate_profiles_for_save(self) -> None:
        names: set[str] = set()
        ids: set[str] = set()
        for profile in self.draft_settings.profiles:
            normalized_name = str(profile.name or "").strip()
            if not normalized_name:
                raise ValueError("모든 연결 프로필에는 이름이 필요합니다.")
            name_key = normalized_name.casefold()
            if name_key in names:
                raise ValueError("연결 프로필 이름은 중복될 수 없습니다.")
            if profile.profile_id in ids:
                raise ValueError("연결 프로필 식별자가 중복되었습니다.")
            names.add(name_key)
            ids.add(profile.profile_id)
            if (
                profile.credential_storage == CREDENTIAL_STORAGE_OS
                and not self.settings_store.os_credential_available
            ):
                raise ValueError(
                    self.settings_store.os_credential_availability_error
                    or "OS 자격증명 저장소를 사용할 수 없습니다."
                )
        if self.draft_settings.active_profile_id and self.draft_settings.active_profile_id not in ids:
            raise ValueError("활성 연결 프로필을 찾을 수 없습니다.")

    def save_changes(self) -> bool:
        if self._validation_task is not None:
            return False
        ephemeral_passwords = {
            profile.profile_id: profile.password
            for profile in self.draft_settings.profiles
            if profile.credential_storage == CREDENTIAL_STORAGE_NONE and profile.password
        }
        try:
            self._validate_profiles_for_save()
            self.settings_store.save_app_settings(self.draft_settings)
            self.persisted_settings = self.settings_store.load_app_settings()
            for profile in self.persisted_settings.profiles:
                if profile.credential_storage == CREDENTIAL_STORAGE_NONE:
                    profile.password = ephemeral_passwords.get(profile.profile_id, "")
            self.draft_settings = deepcopy(self.persisted_settings)
            self.selected_profile_id = (
                self.draft_settings.active_profile_id
                or (self.draft_settings.profiles[0].profile_id if self.draft_settings.profiles else "")
            )
            self._load_draft_into_controls()
        except Exception as exc:
            self.status_label.setText(f"설정 저장 실패: {self._safe_message(exc)}")
            return False
        self.status_label.setText(
            "전역 설정을 저장했습니다. 현재 작업에 반영하려면 '적용'을 누르세요."
        )
        self._refresh_validation_controls()
        return True

    def apply_saved_settings(self) -> bool:
        if self._dirty:
            self.status_label.setText("변경 내용을 먼저 저장해야 적용할 수 있습니다.")
            return False
        if not self._validation_is_current():
            self.status_label.setText(
                "현재 연결 또는 snapshot을 검증한 뒤 저장해야 적용할 수 있습니다."
            )
            return False
        settings = self._effective_draft_settings()
        if callable(self.on_applied):
            try:
                self.on_applied(settings)
            except Exception as exc:
                self.status_label.setText(f"설정 적용 실패: {self._safe_message(exc)}")
                return False
        self.status_label.setText(
            "저장된 전역 설정을 현재 작업공간과 배치 작업에 적용했습니다."
        )
        self._refresh_applied_mode_label()
        return True

    def discard_changes(self) -> None:
        self.persisted_settings = self.settings_store.load_app_settings()
        self.draft_settings = deepcopy(self.persisted_settings)
        self.selected_profile_id = (
            self.draft_settings.active_profile_id
            or (self.draft_settings.profiles[0].profile_id if self.draft_settings.profiles else "")
        )
        self._load_draft_into_controls()
        self.status_label.setText("저장되지 않은 변경을 취소했습니다.")

    def request_leave(self) -> bool:
        if not self._dirty:
            return True
        decision = None
        if callable(self.leave_decision_callback):
            decision = self.leave_decision_callback()
        if decision is None:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("저장되지 않은 설정")
            dialog.setText("저장되지 않은 설정 변경이 있습니다.")
            save_button = dialog.addButton("저장", QMessageBox.ButtonRole.AcceptRole)
            discard_button = dialog.addButton("변경 취소", QMessageBox.ButtonRole.DestructiveRole)
            cancel_button = dialog.addButton("돌아가기", QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(cancel_button)
            dialog.exec()
            clicked = dialog.clickedButton()
            if clicked is save_button:
                decision = "save"
            elif clicked is discard_button:
                decision = "discard"
            else:
                decision = "cancel"
        if decision == "save":
            return self.save_changes()
        if decision == "discard":
            self.discard_changes()
            return True
        return False

    def reset_current_category(self) -> None:
        if self.current_category == SETTINGS_CATEGORY_CONNECTION:
            profile = self._selected_profile()
            if profile is not None:
                profile.base_url = ""
                profile.username = ""
                profile.password = ""
                profile.credential_storage = CREDENTIAL_STORAGE_LOCAL
                profile.validated_signature = ""
                profile.validated_at = ""
                profile.credential_error = ""
                self._load_selected_profile_controls()
        elif self.current_category == SETTINGS_CATEGORY_APPEARANCE:
            self.draft_settings.theme_name = DEFAULT_GUI_THEME
            self._updating_controls = True
            self.theme_combo.setCurrentIndex(
                max(self.theme_combo.findData(DEFAULT_GUI_THEME), 0)
            )
            self._updating_controls = False
        elif self.current_category == SETTINGS_CATEGORY_NETWORK_STORAGE:
            self.draft_settings.rate_limit_retry_delay_seconds = 1.0
            self.draft_settings.rate_limit_max_retries = 5
            self.draft_settings.output_dir = "output"
            self._updating_controls = True
            self.retry_delay_spin.setValue(1.0)
            self.retry_count_spin.setValue(5)
            self.output_dir_edit.setText("output")
            self._updating_controls = False
        elif self.current_category == SETTINGS_CATEGORY_TEST_MODE:
            self.draft_settings.offline_mode = False
            self.draft_settings.offline_schema_path = ""
            self.draft_settings.offline_tracker_configuration_path = ""
            self.draft_settings.offline_query_data_path = ""
            self.draft_settings.test_mode_validated_signature = ""
            self.draft_settings.test_mode_validated_at = ""
            self._updating_controls = True
            self.test_mode_checkbox.setChecked(False)
            self.schema_path_edit.clear()
            self.tracker_config_path_edit.clear()
            self.query_data_path_edit.clear()
            self._updating_controls = False
            self._sync_test_mode_controls()
        elif self.current_category == SETTINGS_CATEGORY_DEVELOPER:
            self.draft_settings.api_monitor_enabled = False
            self.draft_settings.api_monitor_slow_threshold_ms = (
                API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
            )
            self._updating_controls = True
            self.api_monitor_checkbox.setChecked(False)
            self.api_monitor_slow_threshold_spin.setValue(
                API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
            )
            self._updating_controls = False
            self._sync_developer_controls()
        else:
            return
        self._mark_dirty(self.current_category)
        self.status_label.setText(
            f"{SETTINGS_CATEGORY_LABELS[self.current_category]} 영역을 기본값으로 "
            "되돌렸습니다. 저장 전에는 취소할 수 있습니다."
        )

    def import_from_path(self, path: Path) -> None:
        imported = self.settings_store.import_app_settings(Path(path))
        imported.window_width = self.draft_settings.window_width
        imported.window_height = self.draft_settings.window_height
        imported.window_is_maximized = self.draft_settings.window_is_maximized
        imported.window_is_fullscreen = self.draft_settings.window_is_fullscreen
        imported.navigation_collapsed = self.draft_settings.navigation_collapsed
        self.draft_settings = imported
        self.selected_profile_id = (
            imported.active_profile_id
            or (imported.profiles[0].profile_id if imported.profiles else "")
        )
        self._load_draft_into_controls()
        self._update_dirty_state(True)
        self.status_label.setText(
            "설정을 가져왔습니다. 자격증명은 포함되지 않았으므로 "
            "연결 정보를 확인하고 저장하세요."
        )

    def update_navigation_preference(self, collapsed: bool) -> None:
        """앱 셸 전용 상태를 설정 편집 중에도 덮어쓰지 않도록 동기화한다."""
        value = bool(collapsed)
        self.persisted_settings.navigation_collapsed = value
        self.draft_settings.navigation_collapsed = value

    def export_to_path(self, path: Path) -> None:
        self.settings_store.export_app_settings(Path(path), self.draft_settings)
        self.status_label.setText("자격증명을 제외한 설정을 내보냈습니다.")

    def _choose_import_path(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "전역 설정 가져오기",
            str(self.settings_store.root_dir),
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected:
            return
        try:
            self.import_from_path(Path(selected))
        except Exception as exc:
            self.status_label.setText(f"설정 가져오기 실패: {self._safe_message(exc)}")

    def _choose_export_path(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "전역 설정 내보내기",
            str(self.settings_store.root_dir / "gui_app_settings_export.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected:
            return
        try:
            self.export_to_path(Path(selected))
        except Exception as exc:
            self.status_label.setText(f"설정 내보내기 실패: {self._safe_message(exc)}")

    def _refresh_applied_mode_label(self) -> None:
        if self.persisted_settings.offline_mode:
            text = "테스트 모드"
        else:
            profile = self.persisted_settings.active_profile()
            text = "연결 미설정" if profile is None else profile.name
        self.applied_mode_label.setText(f"저장됨 · {text}")

    def _safe_message(self, value) -> str:
        message = str(value or "").strip() or "알 수 없는 오류"
        secrets = [
            profile.password
            for profile in self.draft_settings.profiles
            if profile.password
        ]
        for secret in secrets:
            message = message.replace(secret, "***")
        return message


__all__ = [
    "SETTINGS_CATEGORY_APPEARANCE",
    "SETTINGS_CATEGORY_CONNECTION",
    "SETTINGS_CATEGORY_DATA",
    "SETTINGS_CATEGORY_DEVELOPER",
    "SETTINGS_CATEGORY_LABELS",
    "SETTINGS_CATEGORY_NETWORK_STORAGE",
    "SETTINGS_CATEGORY_TEST_MODE",
    "SettingsCenterPage",
]
