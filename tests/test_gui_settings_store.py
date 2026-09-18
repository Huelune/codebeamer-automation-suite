from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.gui.settings_store import CREDENTIAL_STORAGE_LOCAL
from src.gui.settings_store import CREDENTIAL_STORAGE_NONE
from src.gui.settings_store import CREDENTIAL_STORAGE_OS
from src.gui.settings_store import AppSettings
from src.gui.settings_store import ConnectionProfile
from src.gui.settings_store import GuiSettings
from src.gui.settings_store import GuiSettingsStore
from src.gui.settings_store import GuiWorkflowPreset
from src.gui.settings_store import effective_gui_settings
from src.gui.settings_store import profile_validation_signature
from src.gui.settings_store import test_mode_validation_signature
from src.gui.styles import DEFAULT_GUI_THEME
from src.upload_policy import UPLOAD_MODE_UPDATE as GUI_UPLOAD_MODE_UPDATE
from src.upload_policy import UPLOAD_MODE_UPSERT as GUI_UPLOAD_MODE_UPSERT
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


try:
    import cryptography  # noqa: F401
except ImportError:  # pragma: no cover
    CRYPTOGRAPHY_AVAILABLE = False
else:
    CRYPTOGRAPHY_AVAILABLE = True


@unittest.skipUnless(CRYPTOGRAPHY_AVAILABLE, "cryptography 패키지가 설치된 환경에서만 실행")
class GuiSettingsStoreTest(unittest.TestCase):
    def test_save_without_password_does_not_store_encrypted_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            settings = GuiSettings(
                theme_name="igloo",
                base_url="https://example.com/cb",
                username="user",
                password="secret",
                save_password=False,
                offline_mode=True,
                offline_schema_path="/tmp/schema.json",
            )

            store.save(settings)
            payload = json.loads(store.settings_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["password_encrypted"], "")
            loaded = store.load()
            self.assertEqual(loaded.password, "")
            self.assertFalse(loaded.save_password)
            self.assertTrue(loaded.offline_mode)
            self.assertEqual(loaded.offline_schema_path, "/tmp/schema.json")
            self.assertEqual(loaded.theme_name, "igloo")

    def test_save_with_password_encrypts_and_restores_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            settings = GuiSettings(
                theme_name="kefico",
                window_width=1600,
                window_height=920,
                window_is_maximized=True,
                window_is_fullscreen=False,
                base_url="https://example.com/cb",
                username="user",
                password="secret",
                save_password=True,
                summary_column="Summary",
                upload_mode=GUI_UPLOAD_MODE_UPDATE,
            )

            store.save(settings)
            payload = json.loads(store.settings_path.read_text(encoding="utf-8"))

            self.assertNotEqual(payload["password_encrypted"], "")
            self.assertNotIn("secret", store.settings_path.read_text(encoding="utf-8"))

            loaded = store.load()
            self.assertEqual(loaded.password, "secret")
            self.assertTrue(loaded.save_password)
            self.assertEqual(loaded.summary_column, "Summary")
            self.assertEqual(loaded.theme_name, DEFAULT_GUI_THEME)
            self.assertEqual(loaded.upload_mode, GUI_UPLOAD_MODE_UPDATE)
            self.assertEqual(loaded.window_width, 1600)
            self.assertEqual(loaded.window_height, 920)
            self.assertTrue(loaded.window_is_maximized)
            self.assertFalse(loaded.window_is_fullscreen)

    def test_load_legacy_kepico_theme_name_as_kefico_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.settings_path.write_text(
                json.dumps({"theme_name": "kepico", "password_encrypted": ""}, ensure_ascii=False),
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(loaded.theme_name, DEFAULT_GUI_THEME)

    def test_save_and_load_workflow_preset_preserves_nested_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            preset = GuiWorkflowPreset(
                settings=GuiSettings(
                    theme_name="igloo",
                    base_url="https://example.com/cb",
                    username="user",
                    password="secret",
                    save_password=True,
                    default_project_id="10",
                    default_tracker_id="1000",
                    excel_header_row=2,
                    summary_column="요약",
                    excel_sheet_name="Main",
                    upload_mode=GUI_UPLOAD_MODE_UPDATE,
                ),
                file_options={
                    "sheet_name": "Main",
                    "header_row": 2,
                    "summary_column": "요약",
                },
                root_item_config={
                    "enabled": False,
                    "regex_pattern": r"^(?P<name>.+)$",
                    "field_assignments": {
                        "Summary": {
                            "enabled": True,
                            "mode": "file_source",
                            "value": "group1",
                        }
                    },
                },
                selected_mapping={"Summary": "Summary", "담당자": "담당자"},
                selected_mapping_modes={
                    "Summary": {"create": True, "update": True},
                    "담당자": {"create": True, "update": False},
                },
                selected_default_values={"담당자": "홍길동"},
                selected_default_value_modes={
                    "담당자": {"create": False, "update": True},
                },
                selected_tracker_item_settings={
                    "연관 요구사항": {
                        "mode": "query",
                        "query_match_strategy": "last",
                        "regex_pattern": r"(\\d+)",
                        "source_tracker_ids": [13526611],
                    }
                },
            )

            store.save_workflow_preset(preset)
            payload = json.loads(store.workflow_preset_path.read_text(encoding="utf-8"))

            self.assertIn("settings", payload)
            self.assertNotIn("secret", store.workflow_preset_path.read_text(encoding="utf-8"))

            loaded = store.load_workflow_preset()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.settings.password, "secret")
            self.assertEqual(loaded.settings.default_project_id, "10")
            self.assertEqual(loaded.settings.theme_name, "igloo")
            self.assertEqual(loaded.settings.upload_mode, GUI_UPLOAD_MODE_UPDATE)
            self.assertEqual(loaded.file_options["sheet_name"], "Main")
            self.assertFalse(loaded.root_item_config["enabled"])
            self.assertEqual(loaded.root_item_config["regex_pattern"], r"^(?P<name>.+)$")
            self.assertEqual(loaded.selected_mapping["담당자"], "담당자")
            self.assertEqual(loaded.selected_mapping_modes["Summary"], {"create": True, "update": True})
            self.assertEqual(loaded.selected_mapping_modes["담당자"], {"create": True, "update": False})
            self.assertEqual(loaded.selected_default_values["담당자"], "홍길동")
            self.assertEqual(loaded.selected_default_value_modes["담당자"], {"create": False, "update": True})
            self.assertEqual(
                loaded.selected_tracker_item_settings["연관 요구사항"]["source_tracker_ids"],
                [13526611],
            )
            self.assertEqual(
                loaded.selected_tracker_item_settings["연관 요구사항"]["query_match_strategy"],
                "last",
            )

    def test_load_normalizes_unknown_theme_name_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.root_dir.mkdir(parents=True, exist_ok=True)
            store.settings_path.write_text(
                json.dumps({"theme_name": "unknown", "password_encrypted": ""}, ensure_ascii=False),
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(loaded.theme_name, DEFAULT_GUI_THEME)

    def test_load_normalizes_unknown_upload_mode_to_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.root_dir.mkdir(parents=True, exist_ok=True)
            store.settings_path.write_text(
                json.dumps({"upload_mode": "unknown", "password_encrypted": ""}, ensure_ascii=False),
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(loaded.upload_mode, "create")

    def test_load_preserves_upsert_upload_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir))
            store.root_dir.mkdir(parents=True, exist_ok=True)
            store.settings_path.write_text(
                json.dumps({"upload_mode": GUI_UPLOAD_MODE_UPSERT, "password_encrypted": ""}, ensure_ascii=False),
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(loaded.upload_mode, GUI_UPLOAD_MODE_UPSERT)

    def test_app_profile_local_storage_encrypts_secret_with_real_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = GuiSettingsStore(Path(tmp_dir), credential_store=_FakeCredentialStore())
            profile = ConnectionProfile(
                profile_id="primary",
                name="기본",
                base_url="https://example.test",
                username="tester",
                password="profile-secret",
                credential_storage=CREDENTIAL_STORAGE_LOCAL,
                server_wiki_html_enabled=True,
            )

            store.save_app_settings(
                AppSettings(active_profile_id="primary", profiles=[profile])
            )
            serialized = store.app_settings_path.read_text(encoding="utf-8")
            loaded = store.load_app_settings()

            self.assertNotIn("profile-secret", serialized)
            self.assertEqual(loaded.active_profile().password, "profile-secret")
            self.assertTrue(loaded.active_profile().server_wiki_html_enabled)


class _FakeCredentialStore:
    available = True
    availability_error = ""

    def __init__(self) -> None:
        self.passwords: dict[str, str] = {}
        self.fail_on_set = False

    def get_password(self, profile_id: str) -> str | None:
        return self.passwords.get(profile_id)

    def set_password(self, profile_id: str, password: str) -> None:
        if self.fail_on_set:
            raise RuntimeError("OS credential write failed")
        self.passwords[profile_id] = password

    def delete_password(self, profile_id: str) -> None:
        self.passwords.pop(profile_id, None)


class _DeterministicSettingsStore(GuiSettingsStore):
    def _encrypt_password(self, password: str) -> str:
        return f"encrypted::{password[::-1]}"

    def _decrypt_password(self, encrypted_password: str) -> str:
        prefix = "encrypted::"
        if not encrypted_password.startswith(prefix):
            raise ValueError("invalid encrypted value")
        return encrypted_password[len(prefix):][::-1]


class GuiAppSettingsStoreTest(unittest.TestCase):
    def test_version_two_app_settings_load_with_safe_api_monitor_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )
            store.root_dir.mkdir(parents=True, exist_ok=True)
            store.app_settings_path.write_text(
                json.dumps({"version": 2, "profiles": []}),
                encoding="utf-8",
            )

            loaded = store.load_app_settings()

            self.assertEqual(loaded.version, 4)
            self.assertFalse(loaded.api_monitor_enabled)
            self.assertEqual(loaded.api_monitor_slow_threshold_ms, 1000)
            self.assertFalse(loaded.active_profile())

    def test_api_monitor_threshold_is_normalized_before_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )

            store.save_app_settings(
                AppSettings(
                    api_monitor_enabled=True,
                    api_monitor_slow_threshold_ms=999_999,
                )
            )

            loaded = store.load_app_settings()
            self.assertTrue(loaded.api_monitor_enabled)
            self.assertEqual(loaded.api_monitor_slow_threshold_ms, 60_000)

    def test_legacy_settings_are_migrated_without_removing_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )
            legacy = GuiSettings(
                base_url="https://example.test/cb",
                username="tester",
                password="legacy-secret",
                save_password=True,
                offline_mode=True,
                offline_schema_path="/tmp/schema.json",
                theme_name="igloo",
            )
            store.save(legacy)
            source_bytes = store.settings_path.read_bytes()

            migrated = store.ensure_app_settings()

            self.assertTrue(store.settings_path.exists())
            self.assertEqual(store.settings_path.read_bytes(), source_bytes)
            self.assertTrue(store.app_settings_path.exists())
            self.assertTrue(migrated.migrated_from_legacy)
            self.assertEqual(migrated.active_profile().name, "기존 연결")
            self.assertEqual(migrated.active_profile().password, "legacy-secret")
            self.assertEqual(migrated.theme_name, "igloo")
            self.assertTrue(migrated.offline_mode)
            self.assertNotIn("legacy-secret", store.app_settings_path.read_text(encoding="utf-8"))

    def test_multiple_profiles_round_trip_with_one_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            credential_store = _FakeCredentialStore()
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=credential_store
            )
            settings = AppSettings(
                active_profile_id="production",
                profiles=[
                    ConnectionProfile(
                        profile_id="development",
                        name="개발",
                        base_url="https://dev.example.test",
                        username="dev-user",
                        password="dev-secret",
                        credential_storage=CREDENTIAL_STORAGE_LOCAL,
                    ),
                    ConnectionProfile(
                        profile_id="production",
                        name="운영",
                        base_url="https://prod.example.test",
                        username="prod-user",
                        password="prod-secret",
                        credential_storage=CREDENTIAL_STORAGE_OS,
                    ),
                ],
            )

            store.save_app_settings(settings)
            loaded = store.load_app_settings()

            self.assertEqual(len(loaded.profiles), 2)
            self.assertEqual(loaded.active_profile().name, "운영")
            self.assertEqual(loaded.active_profile().password, "prod-secret")
            self.assertEqual(credential_store.passwords["production"], "prod-secret")
            serialized = store.app_settings_path.read_text(encoding="utf-8")
            self.assertNotIn("dev-secret", serialized)
            self.assertNotIn("prod-secret", serialized)

    def test_legacy_workflow_preset_globals_are_included_in_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )
            store.save_workflow_preset(
                GuiWorkflowPreset(
                    settings=GuiSettings(
                        base_url="https://preset.example.test",
                        username="preset-user",
                        password="preset-secret",
                        save_password=True,
                        theme_name="igloo",
                        output_dir="preset-output",
                    )
                )
            )

            migrated = store.ensure_app_settings()

            self.assertEqual(migrated.active_profile().base_url, "https://preset.example.test")
            self.assertEqual(migrated.active_profile().username, "preset-user")
            self.assertEqual(migrated.active_profile().password, "preset-secret")
            self.assertEqual(migrated.theme_name, "igloo")
            self.assertEqual(migrated.output_dir, "preset-output")
            self.assertTrue(store.workflow_preset_path.exists())

    def test_credential_transition_verifies_target_before_removing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            credential_store = _FakeCredentialStore()
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=credential_store
            )
            settings = AppSettings(
                active_profile_id="primary",
                profiles=[
                    ConnectionProfile(
                        profile_id="primary",
                        name="기본",
                        password="secret",
                        credential_storage=CREDENTIAL_STORAGE_LOCAL,
                    )
                ],
            )
            store.save_app_settings(settings)

            settings.profiles[0].credential_storage = CREDENTIAL_STORAGE_OS
            store.save_app_settings(settings)
            payload = json.loads(store.app_settings_path.read_text(encoding="utf-8"))

            self.assertEqual(credential_store.passwords["primary"], "secret")
            self.assertNotIn("password_encrypted", payload["profiles"][0])

            settings.profiles[0].credential_storage = CREDENTIAL_STORAGE_LOCAL
            store.save_app_settings(settings)

            self.assertNotIn("primary", credential_store.passwords)
            payload = json.loads(store.app_settings_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["profiles"][0]["password_encrypted"])

    def test_failed_os_credential_transition_restores_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            credential_store = _FakeCredentialStore()
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=credential_store
            )
            settings = AppSettings(
                active_profile_id="primary",
                profiles=[
                    ConnectionProfile(
                        profile_id="primary",
                        name="기본",
                        password="secret",
                        credential_storage=CREDENTIAL_STORAGE_LOCAL,
                    )
                ],
            )
            store.save_app_settings(settings)
            previous_bytes = store.app_settings_path.read_bytes()
            settings.profiles[0].credential_storage = CREDENTIAL_STORAGE_OS
            credential_store.fail_on_set = True

            with self.assertRaisesRegex(RuntimeError, "OS credential write failed"):
                store.save_app_settings(settings)

            self.assertEqual(store.app_settings_path.read_bytes(), previous_bytes)
            self.assertEqual(credential_store.passwords, {})

    def test_export_and_import_exclude_all_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            store = _DeterministicSettingsStore(
                root, credential_store=_FakeCredentialStore()
            )
            settings = AppSettings(
                active_profile_id="primary",
                navigation_collapsed=True,
                offline_query_data_path="query-items.json",
                api_monitor_enabled=True,
                api_monitor_slow_threshold_ms=2750,
                profiles=[
                    ConnectionProfile(
                        profile_id="primary",
                        name="기본",
                        base_url="https://example.test",
                        username="tester",
                        password="secret",
                        credential_storage=CREDENTIAL_STORAGE_LOCAL,
                        validated_signature="signature",
                    )
                ],
            )
            export_path = root / "export.json"

            store.export_app_settings(export_path, settings)
            serialized = export_path.read_text(encoding="utf-8")
            imported = store.import_app_settings(export_path)

            self.assertNotIn("secret", serialized)
            self.assertNotIn("password", serialized)
            self.assertNotIn("validated_signature", serialized)
            self.assertEqual(imported.profiles[0].password, "")
            self.assertEqual(
                imported.profiles[0].credential_storage,
                CREDENTIAL_STORAGE_NONE,
            )
            self.assertTrue(imported.navigation_collapsed)
            self.assertEqual(imported.offline_query_data_path, "query-items.json")
            self.assertTrue(imported.api_monitor_enabled)
            self.assertEqual(imported.api_monitor_slow_threshold_ms, 2750)

    def test_test_mode_signature_changes_when_query_snapshot_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            schema_path = root / "schema.json"
            query_path = root / "query-items.json"
            schema_path.write_text("{}", encoding="utf-8")
            query_path.write_text('{"version": 1}', encoding="utf-8")
            settings = AppSettings(
                offline_mode=True,
                offline_schema_path=str(schema_path),
                offline_query_data_path=str(query_path),
            )

            before = test_mode_validation_signature(settings)
            query_path.write_text('{"version": 1, "items": []}', encoding="utf-8")
            after = test_mode_validation_signature(settings)

            self.assertNotEqual(before, after)

    def test_effective_settings_use_active_profile_and_keep_batch_values(self) -> None:
        app_settings = AppSettings(
            active_profile_id="second",
            profiles=[
                ConnectionProfile(profile_id="first", name="첫 번째", base_url="https://one"),
                ConnectionProfile(
                    profile_id="second",
                    name="두 번째",
                    base_url="https://two",
                    username="user",
                    password="secret",
                ),
            ],
            theme_name="igloo",
            navigation_collapsed=True,
            offline_mode=False,
            output_dir="global-output",
            api_monitor_enabled=True,
            api_monitor_slow_threshold_ms=1750,
        )
        batch_settings = GuiSettings(
            upload_mode=GUI_UPLOAD_MODE_UPDATE,
            excel_header_row=3,
            summary_column="요약",
        )

        effective = effective_gui_settings(app_settings, batch_settings)

        self.assertEqual(effective.base_url, "https://two")
        self.assertEqual(effective.password, "secret")
        self.assertEqual(effective.theme_name, "igloo")
        self.assertTrue(effective.navigation_collapsed)
        self.assertEqual(effective.output_dir, "global-output")
        self.assertTrue(effective.api_monitor_enabled)
        self.assertEqual(effective.api_monitor_slow_threshold_ms, 1750)
        self.assertEqual(effective.upload_mode, GUI_UPLOAD_MODE_UPDATE)
        self.assertEqual(effective.excel_header_row, 3)
        self.assertEqual(effective.summary_column, "요약")

    def test_version_three_workflow_preset_contains_only_batch_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )
            store.ensure_app_settings()
            store.save_workflow_preset(
                GuiWorkflowPreset(
                    settings=GuiSettings(
                        base_url="https://example.test",
                        username="tester",
                        password="secret",
                        save_password=True,
                        theme_name="igloo",
                        upload_mode=GUI_UPLOAD_MODE_UPDATE,
                        excel_header_row=3,
                        summary_column="요약",
                    )
                )
            )

            payload = json.loads(store.workflow_preset_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["version"], 4)
            self.assertEqual(payload["settings"]["upload_mode"], GUI_UPLOAD_MODE_UPDATE)
            self.assertEqual(payload["settings"]["excel_header_row"], 3)
            self.assertEqual(payload["settings"]["summary_column"], "요약")
            self.assertNotIn("base_url", payload["settings"])
            self.assertNotIn("username", payload["settings"])
            self.assertNotIn("theme_name", payload["settings"])
            self.assertNotIn("secret", store.workflow_preset_path.read_text(encoding="utf-8"))

    def test_profile_validation_signature_changes_with_connection_secret(self) -> None:
        profile = ConnectionProfile(
            profile_id="primary",
            base_url="https://example.test",
            username="tester",
            password="one",
        )
        original = profile_validation_signature(profile)

        profile.password = "two"

        self.assertNotEqual(profile_validation_signature(profile), original)

    def test_unvalidated_saved_profile_is_not_activated_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )
            settings = AppSettings(
                active_profile_id="primary",
                profiles=[
                    ConnectionProfile(
                        profile_id="primary",
                        name="기본",
                        base_url="https://example.test",
                        username="tester",
                        password="secret",
                        credential_storage=CREDENTIAL_STORAGE_LOCAL,
                    )
                ],
            )
            store.save_app_settings(settings)

            effective = store.load()

            self.assertEqual(effective.base_url, "")
            self.assertEqual(effective.username, "")
            self.assertEqual(effective.password, "")

    def test_validated_saved_profile_is_activated_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )
            profile = ConnectionProfile(
                profile_id="primary",
                name="기본",
                base_url="https://example.test",
                username="tester",
                password="secret",
                credential_storage=CREDENTIAL_STORAGE_LOCAL,
            )
            profile.validated_signature = profile_validation_signature(profile)
            store.save_app_settings(
                AppSettings(active_profile_id="primary", profiles=[profile])
            )

            effective = store.load()

            self.assertEqual(effective.base_url, "https://example.test")
            self.assertEqual(effective.username, "tester")
            self.assertEqual(effective.password, "secret")

    def test_bulk_update_chunk_size_is_remembered_in_app_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = _DeterministicSettingsStore(
                Path(tmp_dir), credential_store=_FakeCredentialStore()
            )
            store.ensure_app_settings()

            store.save_bulk_update_chunk_size(2500)

            self.assertEqual(store.load().bulk_update_chunk_size, 2500)
            payload = json.loads(store.app_settings_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["bulk_update_chunk_size"], 2500)
