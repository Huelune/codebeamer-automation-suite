from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.batch_window import BatchUploadWindow
from src.gui.settings_store import AppSettings
from src.gui.settings_store import ConnectionProfile
from src.gui.settings_store import GuiSettings
from src.gui.settings_store import GuiSettingsStore
from src.gui.settings_store import GuiWorkflowPreset
from src.upload_policy import UPLOAD_MODE_UPDATE as GUI_UPLOAD_MODE_UPDATE


class GuiWorkflowPresetCollectionTest(unittest.TestCase):
    def test_tracker_presets_are_named_filtered_and_fully_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            first = store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="preset-a",
                    name="요구사항 신규",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                    settings=GuiSettings(
                        default_project_id="10",
                        default_tracker_id="1000",
                        upload_mode=GUI_UPLOAD_MODE_UPDATE,
                    ),
                    file_options={"sheet_name": "Main", "header_row": 2},
                    root_item_config={"enabled": True, "group_by_column": "Group"},
                    selected_mapping={"Summary": "Summary"},
                    selected_mapping_modes={
                        "Summary": {"create": True, "update": True}
                    },
                    selected_default_values={"Status": "Open"},
                    selected_default_value_modes={
                        "Status": {"create": True, "update": False}
                    },
                    selected_tracker_item_settings={
                        "Parent": {"mode": "query", "source_tracker_ids": [99]}
                    },
                )
            )
            store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="preset-b",
                    name="요구사항 수정",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                    settings=GuiSettings(
                        default_project_id="10",
                        default_tracker_id="1000",
                    ),
                )
            )
            store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="preset-c",
                    name="다른 트래커",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="2000",
                    settings=GuiSettings(
                        default_project_id="10",
                        default_tracker_id="2000",
                    ),
                )
            )

            tracker_presets = store.list_tracker_workflow_presets(
                connection_scope="profile:primary",
                project_id="10",
                tracker_id="1000",
            )
            loaded = store.get_tracker_workflow_preset(first.preset_id)

            self.assertEqual(
                {preset.preset_id for preset in tracker_presets},
                {"preset-a", "preset-b"},
            )
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertTrue(first.is_default)
            self.assertEqual(loaded.file_options["sheet_name"], "Main")
            self.assertEqual(loaded.root_item_config["group_by_column"], "Group")
            self.assertTrue(loaded.selected_mapping_modes["Summary"]["update"])
            self.assertEqual(loaded.selected_default_values["Status"], "Open")
            self.assertEqual(
                loaded.selected_tracker_item_settings["Parent"]["source_tracker_ids"],
                [99],
            )

    def test_duplicate_name_is_rejected_and_named_delete_does_not_touch_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            preset = store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="preset-a",
                    name="기본 업로드",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                    settings=GuiSettings(
                        default_project_id="10",
                        default_tracker_id="1000",
                    ),
                )
            )
            store.save_workflow_preset(preset)

            with self.assertRaisesRegex(ValueError, "이미 있습니다"):
                store.save_tracker_workflow_preset(
                    GuiWorkflowPreset(
                        preset_id="preset-b",
                        name="기본 업로드",
                        connection_scope="profile:primary",
                        project_id="10",
                        tracker_id="1000",
                        settings=GuiSettings(
                            default_project_id="10",
                            default_tracker_id="1000",
                        ),
                    )
                )

            self.assertTrue(store.delete_tracker_workflow_preset("preset-a"))
            self.assertEqual(store.list_tracker_workflow_presets(), [])
            self.assertTrue(store.workflow_preset_path.exists())

    def test_legacy_single_preset_is_not_automatically_added_to_named_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.save_workflow_preset(
                GuiWorkflowPreset(
                    name="기존 설정",
                    settings=GuiSettings(
                        default_project_id="10",
                        default_tracker_id="1000",
                    ),
                )
            )

            self.assertEqual(store.list_tracker_workflow_presets(), [])
            self.assertFalse(store.workflow_preset_collection_path.exists())

    def test_scope_default_can_change_and_default_delete_promotes_successor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            first = store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="first",
                    name="첫 설정",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                )
            )
            second = store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="second",
                    name="두 번째 설정",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                    is_default=True,
                )
            )

            self.assertTrue(first.is_default)
            self.assertTrue(second.is_default)
            self.assertFalse(store.get_tracker_workflow_preset("first").is_default)
            self.assertEqual(
                store.get_default_tracker_workflow_preset(
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                ).preset_id,
                "second",
            )

            self.assertTrue(store.delete_tracker_workflow_preset("second"))

            promoted = store.get_default_tracker_workflow_preset(
                connection_scope="profile:primary",
                project_id="10",
                tracker_id="1000",
            )
            self.assertIsNotNone(promoted)
            assert promoted is not None
            self.assertEqual(promoted.preset_id, "first")

    def test_named_collection_omits_credentials_paths_and_global_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    name="보안 설정",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                    settings=GuiSettings(
                        base_url="https://sensitive.example.test/cb",
                        username="sensitive-user",
                        password="sensitive-password",
                        save_password=True,
                        output_dir="/private/sensitive/output",
                        offline_schema_path="/private/sensitive/schema.json",
                        offline_tracker_configuration_path="/private/sensitive/config.json",
                        offline_query_data_path="/private/sensitive/query.json",
                        last_file_path="/private/sensitive/input.xlsx",
                        upload_mode=GUI_UPLOAD_MODE_UPDATE,
                        excel_header_row=3,
                        summary_column="요약",
                        excel_sheet_name="Main",
                    ),
                    file_options={
                        "file_path": "/private/sensitive/input.xlsx",
                        "sheet_name": "Main",
                        "header_row": 3,
                        "summary_column": "요약",
                    },
                )
            )

            payload_text = store.workflow_preset_collection_path.read_text(
                encoding="utf-8"
            )

            for forbidden in (
                "https://sensitive.example.test/cb",
                "sensitive-user",
                "sensitive-password",
                "/private/sensitive",
                '"base_url"',
                '"username"',
                '"password"',
                '"password_encrypted"',
                '"save_password"',
                '"output_dir"',
                '"offline_mode"',
                '"offline_schema_path"',
                '"offline_tracker_configuration_path"',
                '"offline_query_data_path"',
                '"last_file_path"',
                '"file_path"',
            ):
                self.assertNotIn(forbidden, payload_text)
            self.assertIn('"connection_scope": "profile:primary"', payload_text)

    def test_named_collection_uses_same_safe_serializer_when_app_settings_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.save_app_settings(
                AppSettings(
                    active_profile_id="primary",
                    profiles=[ConnectionProfile(profile_id="primary", name="기본")],
                )
            )
            store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    name="보안 설정",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                    settings=GuiSettings(
                        base_url="https://sensitive.example.test/cb",
                        username="sensitive-user",
                        password="sensitive-password",
                        last_file_path="/private/sensitive/input.xlsx",
                    ),
                )
            )

            payload_text = store.workflow_preset_collection_path.read_text(
                encoding="utf-8"
            )

            self.assertNotIn("sensitive.example.test", payload_text)
            self.assertNotIn("sensitive-user", payload_text)
            self.assertNotIn("sensitive-password", payload_text)
            self.assertNotIn("/private/sensitive", payload_text)

    def test_connection_scope_uses_profile_id_offline_marker_or_legacy_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))

            offline_scope = store.workflow_connection_scope(
                GuiSettings(offline_mode=True)
            )
            first_legacy = store.workflow_connection_scope(
                GuiSettings(
                    base_url="https://legacy.example.test/cb",
                    username="legacy-user",
                )
            )
            second_legacy = store.workflow_connection_scope(
                GuiSettings(
                    base_url="https://legacy.example.test/cb",
                    username="legacy-user",
                )
            )
            store.save_app_settings(
                AppSettings(
                    active_profile_id="primary",
                    profiles=[
                        ConnectionProfile(
                            profile_id="primary",
                            name="기본 연결",
                        )
                    ],
                )
            )
            profile_scope = store.workflow_connection_scope(GuiSettings())

            self.assertEqual(offline_scope, "offline")
            self.assertEqual(profile_scope, "profile:primary")
            self.assertEqual(first_legacy, second_legacy)
            self.assertTrue(first_legacy.startswith("legacy:"))
            self.assertNotIn("legacy.example.test", first_legacy)
            self.assertNotIn("legacy-user", first_legacy)


class GuiWorkflowPresetWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_window_lists_only_current_connection_scope_and_selects_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.save_app_settings(
                AppSettings(
                    active_profile_id="primary",
                    profiles=[
                        ConnectionProfile(
                            profile_id="primary",
                            name="기본 연결",
                        )
                    ],
                    default_project_id="10",
                    default_tracker_id="1000",
                )
            )
            store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="default",
                    name="기본 업로드",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                )
            )
            store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="secondary",
                    name="보조 업로드",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                )
            )
            store.save_tracker_workflow_preset(
                GuiWorkflowPreset(
                    preset_id="other-profile",
                    name="다른 연결",
                    connection_scope="profile:other",
                    project_id="10",
                    tracker_id="1000",
                )
            )

            window = BatchUploadWindow(store, embedded=True)
            try:
                combo = window.workflow_preset_combo
                self.assertGreaterEqual(combo.findData("default"), 0)
                self.assertGreaterEqual(combo.findData("secondary"), 0)
                self.assertEqual(combo.findData("other-profile"), -1)
                self.assertEqual(combo.currentData(), "default")
                self.assertIn("기본", combo.currentText())
                self.assertFalse(window.default_workflow_button.isEnabled())
                self.assertIsNone(window.session_state.workflow_preset)

                combo.setCurrentIndex(combo.findData("secondary"))

                self.assertTrue(window.default_workflow_button.isEnabled())
            finally:
                window.close()

    def test_loading_named_preset_invalidates_existing_mapping_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.save_app_settings(
                AppSettings(
                    active_profile_id="primary",
                    profiles=[
                        ConnectionProfile(
                            profile_id="primary",
                            name="기본 연결",
                        )
                    ],
                    default_project_id="10",
                    default_tracker_id="1000",
                )
            )
            window = BatchUploadWindow(store, embedded=True)
            try:
                stale_mapping = object()
                window.session_state.mapping_context = stale_mapping
                window.session_state.validation_context = object()
                window.session_state.upload_result = {"success_df": object()}
                preset = GuiWorkflowPreset(
                    preset_id="saved",
                    name="저장 설정",
                    connection_scope="profile:primary",
                    project_id="10",
                    tracker_id="1000",
                    settings=GuiSettings(
                        upload_mode=GUI_UPLOAD_MODE_UPDATE,
                        excel_sheet_name="Main",
                        excel_header_row=2,
                        summary_column="요약",
                    ),
                    file_options={
                        "sheet_name": "Main",
                        "header_row": 2,
                        "summary_column": "요약",
                    },
                    selected_mapping={"요약": "Summary"},
                )

                window._apply_workflow_preset(preset)

                self.assertIsNone(window.session_state.mapping_context)
                self.assertIsNone(window.session_state.validation_context)
                self.assertIsNone(window.session_state.upload_result)
                self.assertIs(window._current_page, window.file_page)
                self.assertFalse(window.file_page._preview_ready)
                self.assertIn("전체 데이터 로드", window.statusBar().currentMessage())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
