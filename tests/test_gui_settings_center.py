from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.main_window import ROUTE_BATCH_UPLOAD
from src.gui.main_window import ROUTE_SETTINGS
from src.gui.main_window import MainWindow
from src.gui.settings_center import SETTINGS_CATEGORY_DEVELOPER
from src.gui.settings_center import SETTINGS_CATEGORY_LABELS
from src.gui.settings_center import SETTINGS_CATEGORY_TEST_MODE
from src.gui.settings_center import SettingsCenterPage
from src.gui.settings_store import CREDENTIAL_STORAGE_NONE
from src.gui.settings_store import CREDENTIAL_STORAGE_OS
from src.gui.settings_store import GuiSettingsStore
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class _UnavailableCredentialStore:
    available = False
    availability_error = "테스트 환경에서는 OS 저장소를 사용할 수 없습니다."


class _DeterministicSettingsStore(GuiSettingsStore):
    def _encrypt_password(self, password: str) -> str:
        return f"encrypted::{password[::-1]}"

    def _decrypt_password(self, encrypted_password: str) -> str:
        return encrypted_password.removeprefix("encrypted::")[::-1]


class GuiSettingsCenterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _store(self, root: Path) -> GuiSettingsStore:
        return _DeterministicSettingsStore(
            root,
            credential_store=_UnavailableCredentialStore(),
        )

    def _finish_background_validation(self, page: SettingsCenterPage) -> None:
        task = page._validation_task
        self.assertIsNotNone(task)
        assert task is not None
        task.wait()
        for _ in range(5):
            self._app.processEvents()
            if page._validation_task is None:
                break
        self.assertIsNone(page._validation_task)

    def _configure_online_profile(self, page: SettingsCenterPage) -> None:
        page.add_profile()
        page.profile_name_edit.setText("개발 서버")
        page.base_url_edit.setText("https://example.test")
        page.username_edit.setText("tester")
        page.password_edit.setText("session-secret")
        index = page.credential_storage_combo.findData(CREDENTIAL_STORAGE_NONE)
        page.credential_storage_combo.setCurrentIndex(index)

    def test_settings_center_exposes_six_categories_and_optional_os_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            page = SettingsCenterPage(self._store(Path(tmp_dir)))

            self.assertEqual(
                [button.text() for button in page.category_buttons.values()],
                list(SETTINGS_CATEGORY_LABELS.values()),
            )
            self.assertEqual(page.category_stack.count(), len(SETTINGS_CATEGORY_LABELS))
            os_index = page.credential_storage_combo.findData(CREDENTIAL_STORAGE_OS)
            self.assertGreaterEqual(os_index, 0)
            self.assertFalse(page.credential_storage_combo.model().item(os_index).isEnabled())

    def test_developer_settings_are_saved_applied_and_can_open_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            applied = []
            opened = []
            page = SettingsCenterPage(
                self._store(Path(tmp_dir)),
                on_applied=applied.append,
                api_monitor_requested=lambda: opened.append(True),
            )
            page.show_category(SETTINGS_CATEGORY_DEVELOPER)

            self.assertTrue(page.api_monitor_open_button.isEnabled())
            self.assertEqual(page.api_monitor_open_button.text(), "개발자 도구 열기")
            page.api_monitor_checkbox.setChecked(True)
            page.api_monitor_slow_threshold_spin.setValue(2500)
            page.api_monitor_open_button.click()

            self.assertEqual(opened, [True])
            self.assertTrue(page.has_unsaved_changes())
            self.assertTrue(page.save_changes(), page.status_label.text())
            self.assertTrue(page.apply_saved_settings(), page.status_label.text())
            self.assertTrue(applied[0].api_monitor_enabled)
            self.assertEqual(applied[0].api_monitor_slow_threshold_ms, 2500)

            reloaded = page.settings_store.load_app_settings()
            self.assertTrue(reloaded.api_monitor_enabled)
            self.assertEqual(reloaded.api_monitor_slow_threshold_ms, 2500)

    def test_online_profile_requires_validation_then_explicit_save_and_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            applied = []
            busy_events = []
            page = SettingsCenterPage(
                self._store(Path(tmp_dir)),
                on_applied=applied.append,
                connection_tester=lambda settings: [{"id": 1, "name": "Project"}],
                busy_started=lambda message: busy_events.append(("start", message)) or 17,
                busy_finished=lambda token: busy_events.append(("finish", token)),
            )
            self._configure_online_profile(page)
            page.server_wiki_html_checkbox.setChecked(True)

            self.assertTrue(page.has_unsaved_changes())
            self.assertFalse(page.apply_saved_settings())

            page.start_validation()
            self._finish_background_validation(page)

            self.assertIn("검증에 성공", page.status_label.text())
            self.assertEqual(
                busy_events,
                [
                    ("start", "Codebeamer 연결 응답을 기다리는 중입니다."),
                    ("finish", 17),
                ],
            )
            self.assertTrue(page.has_unsaved_changes())
            self.assertTrue(page.save_changes(), page.status_label.text())
            self.assertFalse(page.has_unsaved_changes())
            self.assertTrue(page.apply_saved_settings(), page.status_label.text())
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0].base_url, "https://example.test")
            self.assertEqual(applied[0].password, "session-secret")
            self.assertTrue(applied[0].server_wiki_html_enabled)
            self.assertNotIn(
                "session-secret",
                page.settings_store.app_settings_path.read_text(encoding="utf-8"),
            )

    def test_test_mode_is_validated_and_applied_from_settings_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            schema_path = root / "schema.json"
            schema_path.write_text(json.dumps({"tracker": {"id": 100}}), encoding="utf-8")
            query_path = root / "query-items.json"
            query_path.write_text(
                json.dumps({"version": 1, "projects": [], "trackers": [], "items": []}),
                encoding="utf-8",
            )
            tested_modes: list[bool] = []
            tested_query_paths: list[str] = []
            applied = []

            def _tester(settings):
                tested_modes.append(settings.offline_mode)
                tested_query_paths.append(settings.offline_query_data_path)
                return [{"id": 1, "name": "Offline"}]

            page = SettingsCenterPage(
                self._store(root),
                on_applied=applied.append,
                connection_tester=_tester,
            )
            page.show_category(SETTINGS_CATEGORY_TEST_MODE)
            page.test_mode_checkbox.setChecked(True)
            page.schema_path_edit.setText(str(schema_path))
            page.query_data_path_edit.setText(str(query_path))

            page.start_validation()
            self._finish_background_validation(page)

            self.assertEqual(tested_modes, [True])
            self.assertEqual(tested_query_paths, [str(query_path)])
            self.assertTrue(page.save_changes(), page.status_label.text())
            self.assertTrue(page.apply_saved_settings(), page.status_label.text())
            self.assertTrue(applied[0].offline_mode)
            self.assertEqual(applied[0].offline_schema_path, str(schema_path))
            self.assertEqual(applied[0].offline_query_data_path, str(query_path))

    def test_unsaved_navigation_supports_cancel_and_discard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            window = MainWindow(self._store(Path(tmp_dir)))
            window.nav_buttons[ROUTE_SETTINGS].click()
            page = window.settings_center_page
            page.theme_combo.setCurrentIndex(1)
            self.assertTrue(page.has_unsaved_changes())

            page.leave_decision_callback = lambda: "cancel"
            window.nav_buttons[ROUTE_BATCH_UPLOAD].click()
            self._app.processEvents()
            self.assertEqual(window.current_route, ROUTE_SETTINGS)

            page.leave_decision_callback = lambda: "discard"
            window.nav_buttons[ROUTE_BATCH_UPLOAD].click()
            self._app.processEvents()
            self.assertEqual(window.current_route, ROUTE_BATCH_UPLOAD)
            self.assertFalse(page.has_unsaved_changes())

            window.close()
            self._app.processEvents()

    def test_main_window_applies_test_mode_to_badge_and_batch_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            schema_path = root / "schema.json"
            schema_path.write_text(json.dumps({"tracker": {"id": 100}}), encoding="utf-8")
            window = MainWindow(self._store(root))
            page = window.settings_center_page
            page.connection_tester = lambda settings: []
            window.nav_buttons[ROUTE_SETTINGS].click()
            page.test_mode_checkbox.setChecked(True)
            page.schema_path_edit.setText(str(schema_path))
            page.start_validation()
            self._finish_background_validation(page)

            self.assertTrue(page.save_changes(), page.status_label.text())
            self.assertTrue(page.apply_saved_settings(), page.status_label.text())
            self.assertEqual(window.mode_badge.text(), "테스트 모드")
            self.assertIn(
                "테스트 모드",
                window.batch_window.settings_page.environment_summary.text(),
            )

            window.close()
            self._app.processEvents()


if __name__ == "__main__":
    unittest.main()
