from __future__ import annotations

import unittest

from src.gui.styles import DEFAULT_GUI_THEME
from src.gui.styles import build_gui_stylesheet
from src.gui.styles import normalize_gui_theme_name
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class GuiStylesTest(unittest.TestCase):
    def test_normalize_gui_theme_name_falls_back_to_default(self) -> None:
        self.assertEqual(normalize_gui_theme_name(None), DEFAULT_GUI_THEME)
        self.assertEqual(normalize_gui_theme_name(""), DEFAULT_GUI_THEME)
        self.assertEqual(normalize_gui_theme_name("unknown"), DEFAULT_GUI_THEME)
        self.assertEqual(normalize_gui_theme_name("kepico"), DEFAULT_GUI_THEME)

    def test_build_gui_stylesheet_includes_igloo_palette_overrides(self) -> None:
        stylesheet = build_gui_stylesheet("igloo")

        self.assertIn("#0B6E70", stylesheet)
        self.assertIn("#16B3AC", stylesheet)
        self.assertIn("QPushButton#primary_button", stylesheet)
        self.assertIn("QPushButton#mode_toggle", stylesheet)
        self.assertIn("QPushButton#application_nav_button:checked", stylesheet)
        self.assertIn("QPushButton#application_navigation_toggle", stylesheet)
        self.assertIn('application_nav_button[navigationCollapsed="true"]', stylesheet)
        self.assertIn("QFrame#application_placeholder_card", stylesheet)
        self.assertIn("QFrame#settings_category_navigation", stylesheet)
        self.assertIn("QPushButton#settings_category_button:checked", stylesheet)
        self.assertIn("QFrame#tracker_workspace_panel", stylesheet)
        self.assertIn("QTreeWidget#tracker_item_tree", stylesheet)
        self.assertIn("QPushButton#tracker_id_copy_button", stylesheet)
        self.assertIn("QLabel#tracker_editor_status", stylesheet)
        self.assertIn("QDialog#tracker_delete_dialog", stylesheet)
        self.assertIn("QDialog#tracker_item_create_dialog", stylesheet)
        self.assertIn("QFrame#activity_summary_card", stylesheet)
        self.assertIn("QDialog#activity_history_clear_dialog", stylesheet)

    def test_build_gui_stylesheet_defaults_to_kefico_when_theme_is_invalid(self) -> None:
        default_stylesheet = build_gui_stylesheet(DEFAULT_GUI_THEME)
        invalid_stylesheet = build_gui_stylesheet("nope")

        self.assertEqual(invalid_stylesheet, default_stylesheet)
        self.assertIn("QWidget#application_shell_root", default_stylesheet)
        self.assertIn("QLabel#settings_dirty_badge", default_stylesheet)

    def test_build_gui_stylesheet_includes_table_readability_rules(self) -> None:
        stylesheet = build_gui_stylesheet("kefico")

        self.assertIn("QTableWidget::item", stylesheet)
        self.assertIn("QTableWidget:disabled", stylesheet)
        self.assertIn("QHeaderView::section:vertical", stylesheet)
        self.assertIn("QTableCornerButton::section", stylesheet)
        self.assertIn("color: #13263A;", stylesheet)

    def test_build_gui_stylesheet_includes_visible_checkbox_states(self) -> None:
        stylesheet = build_gui_stylesheet("kefico")

        self.assertIn("QCheckBox::indicator {", stylesheet)
        self.assertIn("QCheckBox::indicator:checked {", stylesheet)
        self.assertIn("QCheckBox::indicator:checked:disabled {", stylesheet)
        self.assertIn("QTableWidget QCheckBox", stylesheet)
        self.assertIn("checkmark.svg", stylesheet)

    def test_build_gui_stylesheet_uses_igloo_checkbox_colors(self) -> None:
        stylesheet = build_gui_stylesheet("igloo")

        self.assertIn("border-color: #0B6E70;", stylesheet)
        self.assertIn("background-color: #0B6E70;", stylesheet)


if __name__ == "__main__":
    unittest.main()
