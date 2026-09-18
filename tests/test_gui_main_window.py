from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.api_monitor import API_MONITOR
from src.app_metadata import APPLICATION_TITLE
from src.gui.activity_history_page import ActivityHistoryPage
from src.gui.batch_window import BatchUploadWindow
from src.gui.main_window import APP_ROUTE_COLLAPSED_LABELS
from src.gui.main_window import APP_ROUTE_LABELS
from src.gui.main_window import APPLICATION_NAVIGATION_COLLAPSED_WIDTH
from src.gui.main_window import ROUTE_ACTIVITY
from src.gui.main_window import ROUTE_BATCH_UPLOAD
from src.gui.main_window import ROUTE_SETTINGS
from src.gui.main_window import ROUTE_TRACKER_WORKSPACE
from src.gui.main_window import MainWindow
from src.gui.main_window import _estimate_upload_remaining_seconds
from src.gui.main_window import _format_clock_text
from src.gui.main_window import _format_upload_eta_text
from src.gui.main_window import _format_upload_progress_text
from src.gui.main_window import _merge_root_item_page_configs
from src.gui.main_window import _merge_window_preferences
from src.gui.main_window import _window_size_from_settings
from src.gui.settings_center import SettingsCenterPage
from src.gui.settings_store import AppSettings
from src.gui.settings_store import GuiSettings
from src.gui.settings_store import GuiSettingsStore
from src.gui.settings_store import test_mode_validation_signature
from src.gui.tracker_workspace import TrackerWorkspacePage
from src.gui.window_support import GuiSessionState
from src.gui.window_support import UploadProgressState
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class GuiMainWindowProgressTest(unittest.TestCase):
    def test_upload_progress_state_uses_independent_mutable_defaults(self) -> None:
        first = UploadProgressState()
        second = UploadProgressState()

        first.phase_counts["insert_success"] = 1

        self.assertEqual(second.phase_counts["insert_success"], 0)

    def test_estimate_upload_remaining_seconds_returns_none_without_completed_rows(self) -> None:
        self.assertIsNone(_estimate_upload_remaining_seconds(12.0, 0, 10))

    def test_estimate_upload_remaining_seconds_uses_average_per_completed_row(self) -> None:
        self.assertAlmostEqual(_estimate_upload_remaining_seconds(20.0, 4, 10), 30.0)

    def test_format_upload_progress_text_includes_percentage_and_counts(self) -> None:
        self.assertEqual(_format_upload_progress_text(3, 8), "진행률 37.5% (3 / 8)")

    def test_format_upload_eta_text_returns_unknown_when_estimate_is_not_ready(self) -> None:
        self.assertEqual(
            _format_upload_eta_text(
                now_timestamp=1_700_000_000.0,
                elapsed_seconds=5.0,
                completed_count=0,
                total_count=10,
            ),
            "예상 종료: -",
        )

    def test_format_upload_eta_text_returns_finish_clock_and_remaining_duration(self) -> None:
        now_timestamp = 1_700_000_000.0
        finish_timestamp = now_timestamp + 30.0
        self.assertEqual(
            _format_upload_eta_text(
                now_timestamp=now_timestamp,
                elapsed_seconds=30.0,
                completed_count=3,
                total_count=6,
            ),
            f"예상 종료: {_format_clock_text(finish_timestamp)} (남은 약 30.0초)",
        )

    def test_format_upload_eta_text_marks_completed_batches(self) -> None:
        now_timestamp = 1_700_000_000.0
        self.assertEqual(
            _format_upload_eta_text(
                now_timestamp=now_timestamp,
                elapsed_seconds=30.0,
                completed_count=6,
                total_count=6,
            ),
            f"예상 종료: 완료됨 ({_format_clock_text(now_timestamp)})",
        )


class GuiMainWindowRootConfigMergeTest(unittest.TestCase):
    def test_merge_root_item_page_configs_preserves_structure_and_field_values(self) -> None:
        merged = _merge_root_item_page_configs(
            {"enabled": False, "group_enabled": False},
            structure_config={
                "enabled": True,
                "group_enabled": True,
                "group_by_column": "Folder",
            },
            field_config={
                "field_assignments": {
                    "Summary": {"enabled": True, "mode": "fixed_value", "value": "REQ"}
                },
                "field_sources": {"Summary": "__file_stem__"},
            },
        )

        self.assertTrue(merged["enabled"])
        self.assertTrue(merged["group_enabled"])
        self.assertEqual(merged["group_by_column"], "Folder")
        self.assertEqual(
            merged["field_assignments"],
            {"Summary": {"enabled": True, "mode": "fixed_value", "value": "REQ"}},
        )
        self.assertEqual(merged["field_sources"], {"Summary": "__file_stem__"})


class GuiMainWindowPreferencesTest(unittest.TestCase):
    def test_window_size_from_settings_clamps_invalid_values(self) -> None:
        settings = GuiSettings(window_width=400, window_height="bad")

        self.assertEqual(_window_size_from_settings(settings), (860, 780))

    def test_merge_window_preferences_preserves_current_window_state(self) -> None:
        current = GuiSettings(
            window_width=1440,
            window_height=900,
            window_is_maximized=False,
            window_is_fullscreen=True,
            navigation_collapsed=True,
            theme_name="kefico",
        )
        incoming = GuiSettings(
            window_width=1160,
            window_height=780,
            window_is_maximized=True,
            window_is_fullscreen=False,
            theme_name="igloo",
        )

        merged = _merge_window_preferences(current, incoming)

        self.assertEqual(merged.window_width, 1440)
        self.assertEqual(merged.window_height, 900)
        self.assertFalse(merged.window_is_maximized)
        self.assertTrue(merged.window_is_fullscreen)
        self.assertTrue(merged.navigation_collapsed)
        self.assertEqual(merged.theme_name, "igloo")


class GuiMainWindowSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_main_window_can_be_created_and_shown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GuiSettingsStore(root_dir=Path(temp_dir))

            window = MainWindow(store)
            window.show()
            self._app.processEvents()

            self.assertIs(type(window), MainWindow)
            self.assertEqual(window.windowTitle(), APPLICATION_TITLE)
            self.assertTrue(window.isVisible())
            self.assertEqual(window.route_stack.count(), len(APP_ROUTE_LABELS))
            self.assertGreaterEqual(window.application_header.height(), 56)
            self.assertEqual(window.current_route, ROUTE_TRACKER_WORKSPACE)
            self.assertIs(window.route_stack.currentWidget(), window.tracker_workspace_page)
            self.assertTrue(window.nav_buttons[ROUTE_TRACKER_WORKSPACE].isChecked())
            self.assertIsInstance(window.tracker_workspace_page, TrackerWorkspacePage)
            self.assertIsInstance(window.activity_page, ActivityHistoryPage)

            self.assertIsInstance(window.batch_window, BatchUploadWindow)
            self.assertIsInstance(window.batch_window.session_state, GuiSessionState)
            self.assertIsInstance(window.batch_window.upload_progress, UploadProgressState)
            self.assertEqual(len(window.batch_window.page_meta), 9)
            self.assertIs(
                window.batch_window.stack.currentWidget(),
                window.batch_window.page_scroll_areas[window.batch_window.settings_page],
            )

            window.nav_buttons[ROUTE_BATCH_UPLOAD].click()
            self._app.processEvents()
            self.assertEqual(window.current_route, ROUTE_BATCH_UPLOAD)
            self.assertIs(window.route_stack.currentWidget(), window.batch_page)
            self.assertTrue(window.nav_buttons[ROUTE_BATCH_UPLOAD].isChecked())
            self.assertFalse(window.statusBar().isVisible())

            window.close()
            self._app.processEvents()

    def test_main_window_exposes_all_planned_top_level_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = MainWindow(GuiSettingsStore(root_dir=Path(temp_dir)))

            self.assertEqual(
                [button.text() for button in window.nav_buttons.values()],
                ["트래커 작업공간", "배치 작업", "실행 기록", "설정"],
            )
            self.assertEqual(
                set(window.route_widgets),
                {
                    ROUTE_TRACKER_WORKSPACE,
                    ROUTE_BATCH_UPLOAD,
                    ROUTE_ACTIVITY,
                    ROUTE_SETTINGS,
                },
            )

            for route, page in window.route_widgets.items():
                window.nav_buttons[route].click()
                self._app.processEvents()
                self.assertEqual(window.current_route, route)
                self.assertIs(window.route_stack.currentWidget(), page)

            self.assertEqual(window.activity_page.table.rowCount(), 0)

            window.close()
            self._app.processEvents()

    def test_global_loading_overlay_uses_reference_counted_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = MainWindow(GuiSettingsStore(root_dir=Path(temp_dir)))
            window.show()
            self._app.processEvents()

            first = window._begin_busy("프로젝트를 불러오는 중입니다.")
            second = window._begin_busy("트래커를 불러오는 중입니다.")
            self._app.processEvents()

            self.assertTrue(window.loading_overlay.isVisible())
            self.assertEqual(window.loading_overlay.active_count, 2)
            self.assertEqual(
                window.loading_overlay.message_label.text(),
                "트래커를 불러오는 중입니다.",
            )
            self.assertEqual(
                window.loading_overlay.geometry(),
                window.centralWidget().rect(),
            )

            window._end_busy(first)
            self.assertTrue(window.loading_overlay.isVisible())
            self.assertEqual(window.loading_overlay.active_count, 1)

            window._end_busy(second)
            self._app.processEvents()
            self.assertFalse(window.loading_overlay.isVisible())
            self.assertEqual(window.loading_overlay.active_count, 0)

            window.close()
            self._app.processEvents()

    def test_application_navigation_can_collapse_and_restore_on_restart(self) -> None:
        from PySide6.QtCore import QPoint

        with tempfile.TemporaryDirectory() as temp_dir:
            store = GuiSettingsStore(root_dir=Path(temp_dir))
            window = MainWindow(store)
            window.show()
            self._app.processEvents()

            self.assertFalse(window.navigation_collapsed)
            self.assertTrue(window.navigation_title.isVisible())
            self.assertEqual(
                [button.text() for button in window.nav_buttons.values()],
                list(APP_ROUTE_LABELS.values()),
            )

            window.navigation_toggle_button.click()
            self._app.processEvents()

            self.assertTrue(window.navigation_collapsed)
            self.assertEqual(
                window.navigation_frame.minimumWidth(),
                APPLICATION_NAVIGATION_COLLAPSED_WIDTH,
            )
            self.assertEqual(
                window.navigation_frame.maximumWidth(),
                APPLICATION_NAVIGATION_COLLAPSED_WIDTH,
            )
            self.assertFalse(window.navigation_title.isVisible())
            self.assertEqual(
                [button.text() for button in window.nav_buttons.values()],
                list(APP_ROUTE_COLLAPSED_LABELS.values()),
            )
            for route, button in window.nav_buttons.items():
                self.assertEqual(button.toolTip(), APP_ROUTE_LABELS[route])
                self.assertEqual(button.accessibleName(), APP_ROUTE_LABELS[route])
            direct_button_position = window.tracker_workspace_page.direct_open_button.mapTo(
                window,
                QPoint(0, 0),
            )
            self.assertLessEqual(
                direct_button_position.x()
                + window.tracker_workspace_page.direct_open_button.width(),
                window.width(),
            )

            window.close()
            self._app.processEvents()
            self.assertTrue(store.load_app_settings().navigation_collapsed)

            restored = MainWindow(store)
            restored.show()
            self._app.processEvents()

            self.assertTrue(restored.navigation_collapsed)
            self.assertEqual(
                [button.text() for button in restored.nav_buttons.values()],
                list(APP_ROUTE_COLLAPSED_LABELS.values()),
            )

            restored.close()
            self._app.processEvents()

    def test_settings_route_uses_dedicated_center_and_batch_can_open_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = MainWindow(GuiSettingsStore(root_dir=Path(temp_dir)))

            window.nav_buttons[ROUTE_SETTINGS].click()
            self._app.processEvents()

            self.assertEqual(window.current_route, ROUTE_SETTINGS)
            self.assertIsInstance(window.settings_center_page, SettingsCenterPage)
            self.assertIs(window.route_stack.currentWidget(), window.settings_center_page)

            window.nav_buttons[ROUTE_BATCH_UPLOAD].click()
            window.batch_window.settings_page.global_settings_button.click()
            self._app.processEvents()

            self.assertEqual(window.current_route, ROUTE_SETTINGS)
            self.assertIs(window.route_stack.currentWidget(), window.settings_center_page)

            window.close()
            self._app.processEvents()

    def test_mode_badge_reflects_offline_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GuiSettingsStore(root_dir=Path(temp_dir))
            schema_path = Path(temp_dir) / "schema.json"
            schema_path.write_text("{}", encoding="utf-8")
            app_settings = AppSettings(
                offline_mode=True,
                offline_schema_path=str(schema_path),
            )
            app_settings.test_mode_validated_signature = test_mode_validation_signature(
                app_settings
            )
            store.save_app_settings(app_settings)

            window = MainWindow(store)

            self.assertEqual(window.mode_badge.text(), "테스트 모드")
            self.assertEqual(window.mode_badge.property("mode"), "test")

            window.close()
            self._app.processEvents()

    def test_batch_upload_window_still_runs_as_a_standalone_wizard(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = BatchUploadWindow(GuiSettingsStore(root_dir=Path(temp_dir)))
            window.show()
            self._app.processEvents()

            self.assertTrue(window.isVisible())
            self.assertIsInstance(window.session_state, GuiSessionState)
            self.assertEqual(len(window.page_meta), 9)
            self.assertIs(
                window.stack.currentWidget(),
                window.page_scroll_areas[window.settings_page],
            )

            window.close()
            self._app.processEvents()

    def test_enabled_api_monitor_opens_at_startup_and_follows_applied_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = GuiSettingsStore(root_dir=Path(temp_dir))
            store.save_app_settings(
                AppSettings(
                    api_monitor_enabled=True,
                    api_monitor_slow_threshold_ms=1800,
                )
            )

            window = MainWindow(store)
            window.show()
            self._app.processEvents()

            self.assertTrue(API_MONITOR.enabled)
            self.assertEqual(API_MONITOR.slow_threshold_ms, 1800)
            self.assertIsNotNone(window.api_monitor_window)
            assert window.api_monitor_window is not None
            self.assertTrue(window.api_monitor_window.isVisible())
            self.assertEqual(
                [
                    window.api_monitor_window.tabs.tabText(index)
                    for index in range(window.api_monitor_window.tabs.count())
                ],
                [
                    "진단 로그",
                    "API 모니터",
                    "Excel 도구",
                    "Payload",
                    "스키마·캐시",
                    "읽기 전용 Query",
                ],
            )

            disabled = GuiSettings(
                **{
                    **window.batch_window.session_state.settings.__dict__,
                    "api_monitor_enabled": False,
                    "api_monitor_slow_threshold_ms": 2400,
                }
            )
            window._on_global_settings_applied(disabled)

            self.assertFalse(API_MONITOR.enabled)
            self.assertEqual(API_MONITOR.slow_threshold_ms, 2400)
            self.assertIn(
                "수집 중지",
                window.api_monitor_window.collection_state_label.text(),
            )

            window.close()
            self._app.processEvents()
            self.assertFalse(window.api_monitor_window.isVisible())
            API_MONITOR.reset()


if __name__ == "__main__":
    unittest.main()
