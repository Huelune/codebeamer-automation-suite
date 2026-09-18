from __future__ import annotations

from pathlib import Path


_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_COMBO_ARROW_PATH = (_ASSETS_DIR / "chevron-down.svg").as_posix()
_CHECKMARK_PATH = (_ASSETS_DIR / "checkmark.svg").as_posix()

DEFAULT_GUI_THEME = "kefico"
GUI_THEME_LABELS = {
    "kefico": "케피코",
    "igloo": "이글루",
}
GUI_THEME_CHOICES = list(GUI_THEME_LABELS.items())

_BASE_GUI_STYLESHEET = """
QMainWindow {
    background: #F4F7FB;
}

QWidget#app_root {
    background: #F4F7FB;
}

QWidget#application_shell_root {
    background: #F4F7FB;
}

QFrame#application_header,
QFrame#application_navigation,
QFrame#application_content {
    background: #FFFFFF;
    border: 1px solid #D8E1EA;
    border-radius: 10px;
}

QLabel#application_title {
    color: #0E4A84;
    font-size: 18px;
    font-weight: 700;
}

QLabel#application_subtitle,
QLabel#application_route_description {
    color: #5B6B7F;
    font-size: 11px;
}

QLabel#application_mode_badge,
QLabel#application_phase_badge,
QPushButton#tracker_id_copy_button {
    color: #0E4A84;
    background: #EAF4FB;
    border: 1px solid #CBE4F3;
    border-radius: 10px;
    padding: 4px 9px;
    font-size: 10px;
    font-weight: 700;
}

QPushButton#tracker_id_copy_button {
    min-height: 18px;
}

QPushButton#tracker_id_copy_button:hover {
    background: #DCEFFD;
    border-color: #9CCBE5;
}

QPushButton#tracker_id_copy_button:pressed {
    background: #CBE4F3;
}

QLabel#application_mode_badge[mode="test"] {
    color: #8A4B08;
    background: #FFF3DC;
    border: 1px solid #F1D49A;
}

QLabel#application_mode_badge[mode="unconfigured"] {
    color: #6B7B8D;
    background: #EEF3F8;
    border: 1px solid #D8E1EA;
}

QLabel#application_navigation_title {
    color: #6B7B8D;
    padding: 2px 8px 6px 8px;
    font-size: 10px;
    font-weight: 700;
}

QPushButton#application_navigation_toggle {
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 0;
    color: #5B6B7F;
    background: transparent;
    border: 1px solid #D8E1EA;
    border-radius: 6px;
    font-size: 16px;
    font-weight: 700;
}

QPushButton#application_navigation_toggle:hover {
    color: #0E4A84;
    background: #F4F8FC;
    border-color: #B6DAEE;
}

QPushButton#application_nav_button {
    min-height: 36px;
    padding: 0 12px;
    border: 1px solid transparent;
    background: transparent;
    color: #425466;
    text-align: left;
}

QPushButton#application_nav_button[navigationCollapsed="true"] {
    padding: 0 3px;
    text-align: center;
}

QPushButton#application_nav_button:hover {
    background: #F4F8FC;
    border: 1px solid #E2EAF2;
}

QPushButton#application_nav_button:checked {
    color: #0E4A84;
    background: #DCEFFD;
    border: 1px solid #B6DAEE;
}

QWidget#application_route_page,
QWidget#batch_route_page {
    background: transparent;
}

QLabel#application_route_title {
    color: #13263A;
    font-size: 20px;
    font-weight: 700;
}

QFrame#application_placeholder_card {
    background: #F8FBFD;
    border: 1px solid #D8E1EA;
    border-radius: 10px;
}

QWidget#tracker_workspace_page,
QWidget#tracker_hierarchy_tab,
QWidget#tracker_search_tab,
QWidget#activity_history_page {
    background: transparent;
}

QFrame#tracker_context_card,
QFrame#tracker_workspace_panel,
QFrame#activity_summary_card,
QFrame#activity_detail_card {
    background: #F8FBFD;
    border: 1px solid #D8E1EA;
    border-radius: 10px;
}

QLabel#tracker_context_label,
QLabel#tracker_panel_status,
QLabel#tracker_page_label,
QLabel#tracker_detail_breadcrumb {
    color: #5B6B7F;
}

QLabel#tracker_workspace_status {
    min-height: 20px;
    color: #425466;
    padding: 2px 4px;
}

QLabel#tracker_workspace_status[tone="loading"] {
    color: #0E4A84;
}

QLabel#tracker_workspace_status[tone="warning"],
QLabel#tracker_detail_warning {
    color: #8A4B08;
    background: #FFF3DC;
    border: 1px solid #F1D49A;
    border-radius: 8px;
    padding: 5px 7px;
}

QLabel#tracker_workspace_status[tone="error"] {
    color: #A93636;
    background: #FDEEEE;
    border: 1px solid #F2C9C9;
    border-radius: 8px;
    padding: 5px 7px;
}

QLabel#activity_summary_value {
    color: #425466;
    font-weight: 700;
}

QLabel#activity_history_status {
    min-height: 20px;
    color: #425466;
    padding: 2px 4px;
}

QLabel#activity_history_status[tone="error"] {
    color: #A93636;
    background: #FDEEEE;
    border: 1px solid #F2C9C9;
    border-radius: 8px;
    padding: 5px 7px;
}

QLabel#tracker_detail_title {
    color: #13263A;
    font-size: 16px;
    font-weight: 700;
}

QLabel#tracker_detail_section_title {
    color: #425466;
    font-weight: 700;
}

QLabel#tracker_editor_status {
    min-height: 20px;
    color: #425466;
    padding: 5px 7px;
    background: #F4F8FC;
    border: 1px solid #D8E1EA;
    border-radius: 8px;
}

QLabel#tracker_editor_status[tone="loading"] {
    color: #0E4A84;
    background: #EAF4FB;
    border-color: #CBE4F3;
}

QLabel#tracker_editor_status[tone="warning"] {
    color: #8A4B08;
    background: #FFF3DC;
    border-color: #F1D49A;
}

QLabel#tracker_editor_status[tone="error"] {
    color: #A93636;
    background: #FDEEEE;
    border-color: #F2C9C9;
}

QLabel#tracker_current_status {
    color: #0E4A84;
    background: #EAF4FB;
    border: 1px solid #CBE4F3;
    border-radius: 9px;
    padding: 3px 7px;
    font-weight: 700;
}

QDialog#tracker_delete_dialog,
QDialog#tracker_item_create_dialog,
QDialog#activity_history_clear_dialog,
QDialog#api_monitor_window {
    background: #F4F7FB;
}

QFrame#api_monitor_stat_card,
QFrame#api_monitor_filters {
    background: #F8FBFD;
    border: 1px solid #D8E1EA;
    border-radius: 8px;
}

QLabel#api_monitor_stat_label {
    color: #6B7B8D;
    font-size: 10px;
}

QLabel#api_monitor_stat_value {
    color: #13263A;
    font-size: 14px;
    font-weight: 700;
}

QLabel#api_monitor_collection_state {
    color: #0E4A84;
    background: #EAF4FB;
    border: 1px solid #CBE4F3;
    border-radius: 10px;
    padding: 4px 9px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#api_monitor_collection_state[state="disabled"] {
    color: #6B7B8D;
    background: #EEF3F8;
    border-color: #D8E1EA;
}

QLabel#api_monitor_collection_state[state="test"] {
    color: #8A4B08;
    background: #FFF3DC;
    border-color: #F1D49A;
}

QTreeWidget#tracker_item_tree {
    background: #FFFFFF;
    color: #13263A;
    border: 1px solid #D8E1EA;
    border-radius: 8px;
    alternate-background-color: #F8FBFD;
    selection-background-color: #DCEFFD;
    selection-color: #13263A;
}

QTreeWidget#tracker_item_tree::item {
    min-height: 26px;
}

QTreeWidget#tracker_item_tree::item:hover {
    background: #EEF6FC;
}

QSplitter#tracker_workspace_splitter::handle {
    background: transparent;
    width: 8px;
}

QSplitter#activity_history_splitter::handle {
    background: transparent;
    height: 8px;
}

QFrame#settings_category_navigation,
QFrame#settings_footer,
QFrame#settings_card {
    background: #F8FBFD;
    border: 1px solid #D8E1EA;
    border-radius: 10px;
}

QWidget#settings_center_page,
QWidget#settings_category_page,
QScrollArea#settings_scroll_area,
QScrollArea#settings_scroll_area > QWidget > QWidget {
    background: transparent;
}

QScrollArea#settings_scroll_area {
    border: none;
}

QLabel#settings_category_title {
    color: #13263A;
    font-size: 16px;
    font-weight: 700;
}

QLabel#settings_dirty_badge {
    color: #8A4B08;
    background: #FFF3DC;
    border: 1px solid #F1D49A;
    border-radius: 10px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#settings_status_label {
    color: #425466;
    min-height: 22px;
}

QPushButton#settings_category_button {
    min-height: 34px;
    padding: 0 10px;
    border: 1px solid transparent;
    background: transparent;
    color: #425466;
    text-align: left;
}

QPushButton#settings_category_button:hover {
    background: #F0F6FB;
    border: 1px solid #E2EAF2;
}

QPushButton#settings_category_button:checked {
    color: #0E4A84;
    background: #DCEFFD;
    border: 1px solid #B6DAEE;
}

QLabel#application_placeholder_title {
    color: #13263A;
    font-size: 13px;
    font-weight: 700;
}

QWidget#header_card, QWidget#page_card {
    background: #FFFFFF;
    border: 1px solid #D8E1EA;
    border-radius: 10px;
}

QScrollArea#page_scroll_area {
    background: transparent;
    border: none;
}

QScrollArea#page_scroll_area > QWidget > QWidget {
    background: transparent;
}

QLabel {
    color: #13263A;
}

QLabel#app_title {
    color: #0E4A84;
    font-size: 17px;
    font-weight: 700;
}

QLabel#app_subtitle {
    color: #5B6B7F;
    font-size: 10px;
}

QLabel#page_title {
    color: #13263A;
    font-size: 17px;
    font-weight: 700;
    padding-bottom: 1px;
}

QLabel#section_label {
    color: #5B6B7F;
    font-size: 10px;
    padding-bottom: 1px;
}

QLabel#mode_title {
    color: #13263A;
    font-size: 14px;
    font-weight: 700;
}

QLabel#mode_badge {
    color: #0E4A84;
    background: #EAF4FB;
    border: 1px solid #CBE4F3;
    border-radius: 10px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#status_label {
    color: #0E4A84;
    background: #EAF4FB;
    border: 1px solid #CBE4F3;
    border-radius: 8px;
    padding: 6px 8px;
}

QToolButton#section_toggle {
    color: #0E4A84;
    background: transparent;
    border: none;
    padding: 2px 0;
    font-weight: 700;
}

QToolButton#section_toggle:hover {
    color: #1260A8;
}

QFrame#advanced_card {
    background: #F8FBFD;
    border: 1px solid #D8E1EA;
    border-radius: 10px;
}

QWidget#busy_overlay {
    background: rgba(19, 38, 58, 0.22);
}

QDialog#alert_dialog {
    background: #F4F7FB;
}

QFrame#alert_surface {
    background: #FFFFFF;
    border: 1px solid #D8E1EA;
    border-radius: 16px;
}

QFrame#alert_surface[tone="error"] {
    border: 1px solid #F1C9C9;
}

QFrame#alert_surface[tone="info"] {
    border: 1px solid #CBE4F3;
}

QLabel#alert_badge {
    color: #0E4A84;
    background: #EAF4FB;
    border: 1px solid #CBE4F3;
    border-radius: 20px;
    font-size: 18px;
    font-weight: 700;
}

QLabel#alert_badge[tone="error"] {
    color: #C24141;
    background: #FDEEEE;
    border: 1px solid #F2C9C9;
}

QLabel#alert_title {
    color: #13263A;
    font-size: 16px;
    font-weight: 700;
}

QLabel#alert_message {
    color: #4E5F72;
}

QPlainTextEdit#alert_details {
    color: #425466;
    background: #F8FBFD;
    border: 1px solid #D8E1EA;
    border-radius: 10px;
    padding: 6px 8px;
}

QFrame#busy_card {
    background: #FFFFFF;
    border: 1px solid #C8D6E3;
    border-radius: 16px;
}

QLabel#busy_title {
    color: #13263A;
    font-size: 16px;
    font-weight: 700;
}

QLabel#busy_message {
    color: #5B6B7F;
    font-size: 11px;
}

QLabel#summary_label {
    color: #13263A;
    background: #F7FAFD;
    border: 1px solid #D8E1EA;
    border-radius: 8px;
    padding: 6px 8px;
    font-weight: 600;
}

QLabel#step_badge {
    color: #6B7B8D;
    background: #EEF3F8;
    border: 1px solid #D8E1EA;
    border-radius: 11px;
    padding: 4px 8px;
    font-size: 10px;
    font-weight: 600;
}

QLabel#step_badge[active="true"] {
    color: #FFFFFF;
    background: #0E4A84;
    border: 1px solid #0E4A84;
}

QLabel#step_badge[complete="true"] {
    color: #0E4A84;
    background: #E4F3FB;
    border: 1px solid #B6DAEE;
}

QPushButton, QToolButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
QTableWidget, QPlainTextEdit, QTextBrowser, QTabBar::tab {
    outline: none;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 26px;
    padding: 1px 7px;
    border: 1px solid #C9D5E2;
    border-radius: 8px;
    background: #FFFFFF;
    color: #13263A;
}

QComboBox {
    padding-right: 24px;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    background: transparent;
}

QComboBox::down-arrow {
    image: url("{combo_arrow}");
    width: 12px;
    height: 12px;
}

QComboBox QAbstractItemView {
    color: #13263A;
    background: #FFFFFF;
    border: 1px solid #C9D5E2;
    selection-background-color: #DCEFFD;
    selection-color: #13263A;
    outline: 0;
}

QComboBox QAbstractItemView::item {
    min-height: 22px;
    padding: 3px 7px;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #00A7D6;
}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: #7E8B99;
    background: #EEF2F6;
    border: 1px solid #D5DEE7;
}

QPushButton {
    min-height: 26px;
    padding: 0 8px;
    border-radius: 8px;
    border: 1px solid #C9D5E2;
    background: #FFFFFF;
    color: #13263A;
    font-weight: 600;
}

QPushButton:hover {
    background: #F4F8FC;
}

QPushButton:disabled {
    color: #7E8B99;
    background: #E8EEF4;
    border-color: #CBD6E1;
}

QPushButton#primary_button {
    background: #0E4A84;
    color: #FFFFFF;
    border: 1px solid #0E4A84;
}

QPushButton#primary_button:hover {
    background: #1260A8;
}

QPushButton#primary_button:disabled {
    color: #F7FAFD;
    background: #A9BBCD;
    border: 1px solid #A9BBCD;
}

QPushButton#mode_toggle {
    min-width: 64px;
    min-height: 30px;
    padding: 0 12px;
    border-radius: 15px;
    border: 1px solid #C9D5E2;
    background: #FFFFFF;
    color: #5B6B7F;
    font-weight: 700;
}

QPushButton#mode_toggle:hover {
    background: #F4F8FC;
}

QPushButton#mode_toggle:checked {
    background: #0E4A84;
    color: #FFFFFF;
    border: 1px solid #0E4A84;
}

QPushButton#mode_toggle:checked:hover {
    background: #1260A8;
}

QPushButton#danger_button {
    background: #FFFFFF;
    color: #C24141;
    border: 1px solid #E8B7B7;
}

QPushButton#danger_button:hover {
    background: #FFF6F6;
}

QPushButton#danger_button:disabled {
    color: #C7A7A7;
    background: #F6EEEE;
    border: 1px solid #E7D7D7;
}

QTableWidget, QPlainTextEdit, QTextBrowser, QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #D8E1EA;
    border-radius: 8px;
}

QTabBar::tab {
    min-height: 24px;
    padding: 4px 10px;
    margin-right: 2px;
    border: 1px solid #D8E1EA;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    background: #EEF4F9;
    color: #5B6B7F;
    font-weight: 600;
}

QTabBar::tab:selected {
    background: #FFFFFF;
    color: #13263A;
}

QTabBar::tab:!selected:hover {
    background: #F5F9FC;
}

QTableWidget {
    color: #13263A;
    gridline-color: #E6EDF4;
    alternate-background-color: #F8FBFD;
    selection-background-color: #DCEFFD;
    selection-color: #13263A;
}

QTableWidget::item {
    color: #13263A;
}

QTableWidget::item:selected {
    color: #13263A;
}

QTableWidget:disabled {
    color: #7E8B99;
    background: #F5F8FB;
}

QTableWidget::item:disabled {
    color: #7E8B99;
}

QHeaderView {
    background-color: #EEF4F9;
}

QHeaderView::section {
    background-color: #EEF4F9;
    color: #425466;
    border: none;
    border-right: 1px solid #D8E1EA;
    border-bottom: 1px solid #D8E1EA;
    padding: 4px 5px;
    font-weight: 700;
}

QHeaderView::section:vertical {
    background-color: #EEF4F9;
    color: #425466;
    border-right: 1px solid #D8E1EA;
    border-bottom: 1px solid #D8E1EA;
}

QTableCornerButton::section {
    background-color: #EEF4F9;
    border-right: 1px solid #D8E1EA;
    border-bottom: 1px solid #D8E1EA;
}

QProgressBar {
    min-height: 12px;
    border: 1px solid #D8E1EA;
    border-radius: 6px;
    background: #ECF2F7;
    text-align: center;
}

QProgressBar::chunk {
    border-radius: 6px;
    background: #00A7D6;
}

QProgressBar#busy_progress {
    min-height: 10px;
    border-radius: 5px;
}

QCheckBox {
    spacing: 6px;
    color: #13263A;
}

QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #8FA2B5;
    border-radius: 4px;
    background-color: #FFFFFF;
}

QCheckBox::indicator:hover {
    border-color: #00A7D6;
    background-color: #F4FAFD;
}

QCheckBox::indicator:checked {
    image: url("{checkmark}");
    border-color: #0E4A84;
    background-color: #0E4A84;
}

QCheckBox::indicator:disabled {
    border-color: #CBD6E1;
    background-color: #EEF2F6;
}

QCheckBox::indicator:checked:disabled {
    image: url("{checkmark}");
    border-color: #A9BBCD;
    background-color: #A9BBCD;
}

QTableWidget QCheckBox {
    background: transparent;
}

QCheckBox:disabled {
    color: #7E8B99;
}

QStatusBar {
    background: #FFFFFF;
    color: #5B6B7F;
    border-top: 1px solid #D8E1EA;
}

QScrollBar:vertical {
    background: #EFF4F8;
    width: 10px;
    margin: 3px 2px 3px 2px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #B8C7D5;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #97AEC3;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    border: none;
}
"""
_BASE_GUI_STYLESHEET = _BASE_GUI_STYLESHEET.replace("{combo_arrow}", _COMBO_ARROW_PATH)
_BASE_GUI_STYLESHEET = _BASE_GUI_STYLESHEET.replace("{checkmark}", _CHECKMARK_PATH)

_IGLOO_THEME_OVERRIDES = """
QMainWindow {
    background: #F2FBFC;
}

QWidget#app_root {
    background: #F2FBFC;
}

QWidget#application_shell_root {
    background: #F2FBFC;
}

QFrame#application_header,
QFrame#application_navigation,
QFrame#application_content {
    border: 1px solid #D3E7E9;
}

QLabel#application_title,
QLabel#application_mode_badge,
QLabel#application_phase_badge,
QPushButton#tracker_id_copy_button {
    color: #0B6E70;
}

QLabel#application_subtitle,
QLabel#application_route_description,
QLabel#application_navigation_title {
    color: #60797E;
}

QLabel#application_mode_badge,
QLabel#application_phase_badge,
QPushButton#tracker_id_copy_button {
    background: #E5F7F6;
    border: 1px solid #BFE6E2;
}

QPushButton#tracker_id_copy_button:hover {
    background: #D9F0EF;
    border-color: #9FD7D2;
}

QPushButton#tracker_id_copy_button:pressed {
    background: #CBE9E6;
}

QLabel#application_mode_badge[mode="test"] {
    color: #8A4B08;
    background: #FFF3DC;
    border: 1px solid #F1D49A;
}

QLabel#application_mode_badge[mode="unconfigured"] {
    color: #6C8489;
    background: #EEF7F8;
    border: 1px solid #D3E7E9;
}

QPushButton#application_nav_button {
    color: #486368;
}

QPushButton#application_nav_button:hover {
    background: #F1FAFB;
    border: 1px solid #D3E7E9;
}

QPushButton#application_nav_button:checked {
    color: #0B6E70;
    background: #D9F0EF;
    border: 1px solid #AEDFD9;
}

QFrame#application_placeholder_card {
    background: #F7FCFC;
    border: 1px solid #D3E7E9;
}

QFrame#tracker_context_card,
QFrame#tracker_workspace_panel,
QFrame#activity_summary_card,
QFrame#activity_detail_card {
    background: #F7FCFC;
    border: 1px solid #D3E7E9;
}

QLabel#tracker_context_label,
QLabel#tracker_panel_status,
QLabel#tracker_page_label,
QLabel#tracker_detail_breadcrumb {
    color: #60797E;
}

QLabel#tracker_workspace_status[tone="loading"] {
    color: #0B6E70;
}

QLabel#tracker_editor_status[tone="loading"],
QLabel#tracker_current_status {
    color: #0B6E70;
    background: #E5F7F6;
    border-color: #BFE6E2;
}

QDialog#tracker_delete_dialog,
QDialog#tracker_item_create_dialog,
QDialog#activity_history_clear_dialog,
QDialog#api_monitor_window {
    background: #F2FBFC;
}

QFrame#api_monitor_stat_card,
QFrame#api_monitor_filters {
    background: #F7FCFC;
    border: 1px solid #D3E7E9;
}

QLabel#api_monitor_stat_label {
    color: #60797E;
}

QLabel#api_monitor_stat_value {
    color: #17383B;
}

QLabel#api_monitor_collection_state {
    color: #0B6E70;
    background: #E5F7F6;
    border-color: #BFE6E2;
}

QTreeWidget#tracker_item_tree {
    border: 1px solid #D3E7E9;
    alternate-background-color: #F7FCFC;
    selection-background-color: #D9F0EF;
}

QTreeWidget#tracker_item_tree::item:hover {
    background: #EEF8F9;
}

QFrame#settings_category_navigation,
QFrame#settings_footer,
QFrame#settings_card {
    background: #F7FCFC;
    border: 1px solid #D3E7E9;
}

QPushButton#settings_category_button {
    color: #486368;
}

QPushButton#settings_category_button:hover {
    background: #EEF8F9;
    border: 1px solid #D3E7E9;
}

QPushButton#settings_category_button:checked {
    color: #0B6E70;
    background: #D9F0EF;
    border: 1px solid #AEDFD9;
}

QWidget#header_card, QWidget#page_card {
    border: 1px solid #D3E7E9;
}

QScrollArea#page_scroll_area > QWidget > QWidget {
    background: transparent;
}

QLabel#app_title {
    color: #0B6E70;
}

QLabel#app_subtitle, QLabel#section_label, QLabel#busy_message {
    color: #60797E;
}

QLabel#mode_title {
    color: #153A3F;
}

QLabel#mode_badge {
    color: #0B6E70;
    background: #E5F7F6;
    border: 1px solid #BFE6E2;
}

QLabel#status_label {
    color: #0B6E70;
    background: #E5F7F6;
    border: 1px solid #BFE6E2;
}

QToolButton#section_toggle {
    color: #0B6E70;
}

QToolButton#section_toggle:hover {
    color: #15918D;
}

QFrame#advanced_card {
    background: #F7FCFC;
    border: 1px solid #D3E7E9;
}

QDialog#alert_dialog {
    background: #F2FBFC;
}

QLabel#alert_badge {
    color: #0B6E70;
    background: #E5F7F6;
    border: 1px solid #BFE6E2;
}

QFrame#busy_card {
    border: 1px solid #C8E0E2;
}

QLabel#summary_label {
    background: #F6FCFC;
    border: 1px solid #D3E7E9;
}

QLabel#step_badge {
    color: #6C8489;
    background: #EEF7F8;
    border: 1px solid #D3E7E9;
}

QLabel#step_badge[active="true"] {
    background: #0B6E70;
    border: 1px solid #0B6E70;
}

QLabel#step_badge[complete="true"] {
    color: #0B6E70;
    background: #E0F5F3;
    border: 1px solid #AEDFD9;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #16B3AC;
}

QComboBox QAbstractItemView {
    color: #153A3F;
    background: #FFFFFF;
    border: 1px solid #C7DFE2;
    selection-background-color: #D9F0EF;
    selection-color: #153A3F;
}

QPushButton:hover {
    background: #F1FAFB;
}

QPushButton#primary_button {
    background: #0B6E70;
    border: 1px solid #0B6E70;
}

QPushButton#primary_button:hover {
    background: #15918D;
}

QPushButton#primary_button:disabled {
    background: #AAC8C8;
    border: 1px solid #AAC8C8;
}

QPushButton#mode_toggle {
    color: #60797E;
}

QPushButton#mode_toggle:hover {
    background: #F1FAFB;
}

QPushButton#mode_toggle:checked {
    background: #0B6E70;
    border: 1px solid #0B6E70;
}

QPushButton#mode_toggle:checked:hover {
    background: #15918D;
}

QTableWidget, QPlainTextEdit, QTextBrowser, QTabWidget::pane {
    border: 1px solid #D3E7E9;
}

QTableWidget {
    color: #153A3F;
    gridline-color: #E4EFF1;
    alternate-background-color: #F7FCFC;
    selection-background-color: #D9F0EF;
}

QTableWidget::item {
    color: #153A3F;
}

QTableWidget::item:selected {
    color: #153A3F;
}

QTableWidget:disabled {
    color: #6E8488;
    background: #F5FAFA;
}

QTableWidget::item:disabled {
    color: #6E8488;
}

QHeaderView {
    background-color: #EEF8F9;
}

QHeaderView::section {
    background-color: #EEF8F9;
    color: #486368;
    border-right: 1px solid #D3E7E9;
    border-bottom: 1px solid #D3E7E9;
}

QHeaderView::section:vertical {
    background-color: #EEF8F9;
    color: #486368;
    border-right: 1px solid #D3E7E9;
    border-bottom: 1px solid #D3E7E9;
}

QTableCornerButton::section {
    background-color: #EEF8F9;
    border-right: 1px solid #D3E7E9;
    border-bottom: 1px solid #D3E7E9;
}

QProgressBar {
    border: 1px solid #D3E7E9;
    background: #EAF4F5;
}

QProgressBar::chunk {
    background: #16B3AC;
}

QCheckBox::indicator:hover {
    border-color: #16B3AC;
    background-color: #F1FAFB;
}

QCheckBox::indicator:checked {
    border-color: #0B6E70;
    background-color: #0B6E70;
}

QCheckBox::indicator:checked:disabled {
    border-color: #AAC8C8;
    background-color: #AAC8C8;
}

QStatusBar {
    color: #60797E;
    border-top: 1px solid #D3E7E9;
}

QScrollBar:vertical {
    background: #EAF5F6;
}

QScrollBar::handle:vertical {
    background: #A6C9CC;
}

QScrollBar::handle:vertical:hover {
    background: #7FB4B8;
}
"""

_THEME_OVERRIDES = {
    "kefico": "",
    "igloo": _IGLOO_THEME_OVERRIDES,
}


def normalize_gui_theme_name(theme_name: str | None) -> str:
    normalized = str(theme_name or "").strip().lower()
    if normalized == "kepico":
        normalized = DEFAULT_GUI_THEME
    return normalized if normalized in GUI_THEME_LABELS else DEFAULT_GUI_THEME


def build_gui_stylesheet(theme_name: str | None = None) -> str:
    normalized_theme = normalize_gui_theme_name(theme_name)
    return f"{_BASE_GUI_STYLESHEET}\n{_THEME_OVERRIDES.get(normalized_theme, '')}".strip()


GUI_STYLESHEET = build_gui_stylesheet()
