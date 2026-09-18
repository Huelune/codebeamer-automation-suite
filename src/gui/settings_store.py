from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.api_monitor import API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
from src.api_monitor import API_MONITOR_MAX_SLOW_THRESHOLD_MS
from src.api_monitor import API_MONITOR_MIN_SLOW_THRESHOLD_MS
from src.upload_policy import UPLOAD_MODE_CREATE as GUI_UPLOAD_MODE_CREATE
from src.upload_policy import OperationScope
from src.upload_policy import as_operation_scope
from src.upload_policy import normalize_upload_mode as normalize_gui_upload_mode

from .payload_values import as_mapping
from .styles import DEFAULT_GUI_THEME
from .styles import normalize_gui_theme_name


APP_DIR_NAME = ".codebeamer-automation-suite"
SETTINGS_FILE_NAME = "gui_settings.json"
APP_SETTINGS_FILE_NAME = "gui_app_settings.json"
KEY_FILE_NAME = "gui_settings.key"
WORKFLOW_PRESET_FILE_NAME = "gui_workflow_preset.json"
WORKFLOW_PRESET_COLLECTION_FILE_NAME = "gui_workflow_presets.json"
WORKFLOW_PRESET_COLLECTION_VERSION = 2
APP_SETTINGS_VERSION = 4

CREDENTIAL_STORAGE_NONE = "none"
CREDENTIAL_STORAGE_LOCAL = "local_encrypted"
CREDENTIAL_STORAGE_OS = "os_credential"
CREDENTIAL_STORAGE_CHOICES = {
    CREDENTIAL_STORAGE_LOCAL,
    CREDENTIAL_STORAGE_OS,
    CREDENTIAL_STORAGE_NONE,
}
OS_CREDENTIAL_SERVICE_NAME = "codebeamer-automation-suite"


@dataclass
class GuiSettings:
    theme_name: str = DEFAULT_GUI_THEME
    upload_mode: str = GUI_UPLOAD_MODE_CREATE
    window_width: int = 1160
    window_height: int = 780
    window_is_maximized: bool = False
    window_is_fullscreen: bool = False
    navigation_collapsed: bool = False
    base_url: str = ""
    username: str = ""
    password: str = ""
    save_password: bool = False
    offline_mode: bool = False
    server_wiki_html_enabled: bool = False
    offline_schema_path: str = ""
    offline_tracker_configuration_path: str = ""
    offline_query_data_path: str = ""
    default_project_id: str = ""
    default_tracker_id: str = ""
    excel_header_row: int = 1
    summary_column: str = "Summary"
    excel_sheet_name: str = "0"
    rate_limit_retry_delay_seconds: float = 1.0
    rate_limit_max_retries: int = 5
    api_monitor_enabled: bool = False
    api_monitor_slow_threshold_ms: int = API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
    bulk_update_chunk_size: int = 1000
    output_dir: str = "output"
    last_file_path: str = ""


@dataclass
class ConnectionProfile:
    profile_id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "새 연결"
    base_url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    credential_storage: str = CREDENTIAL_STORAGE_LOCAL
    server_wiki_html_enabled: bool = False
    validated_signature: str = ""
    validated_at: str = ""
    credential_error: str = field(default="", repr=False, compare=False)


@dataclass
class AppSettings:
    version: int = APP_SETTINGS_VERSION
    active_profile_id: str = ""
    profiles: list[ConnectionProfile] = field(default_factory=list)
    theme_name: str = DEFAULT_GUI_THEME
    window_width: int = 1160
    window_height: int = 780
    window_is_maximized: bool = False
    window_is_fullscreen: bool = False
    navigation_collapsed: bool = False
    rate_limit_retry_delay_seconds: float = 1.0
    rate_limit_max_retries: int = 5
    api_monitor_enabled: bool = False
    api_monitor_slow_threshold_ms: int = API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
    bulk_update_chunk_size: int = 1000
    output_dir: str = "output"
    offline_mode: bool = False
    offline_schema_path: str = ""
    offline_tracker_configuration_path: str = ""
    offline_query_data_path: str = ""
    test_mode_validated_signature: str = ""
    test_mode_validated_at: str = ""
    default_project_id: str = ""
    default_tracker_id: str = ""
    migrated_from_legacy: bool = False

    def active_profile(self) -> ConnectionProfile | None:
        for profile in self.profiles:
            if profile.profile_id == self.active_profile_id:
                return profile
        return None


@dataclass
class GuiWorkflowPreset:
    version: int = 1
    preset_id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "기본 설정"
    connection_scope: str = ""
    project_id: str = ""
    tracker_id: str = ""
    is_default: bool = False
    settings: GuiSettings = field(default_factory=GuiSettings)
    file_options: dict[str, Any] = field(default_factory=dict)
    root_item_config: dict[str, Any] = field(default_factory=dict)
    selected_mapping: dict[str, str] = field(default_factory=dict)
    selected_mapping_modes: dict[str, OperationScope] = field(default_factory=dict)
    selected_default_values: dict[str, str] = field(default_factory=dict)
    selected_default_value_modes: dict[str, OperationScope] = field(default_factory=dict)
    selected_tracker_item_settings: dict[str, dict[str, Any]] = field(default_factory=dict)


class KeyringCredentialStore:
    """설치된 keyring backend를 통해 OS 자격증명 저장소를 사용한다."""

    def __init__(self, service_name: str = OS_CREDENTIAL_SERVICE_NAME) -> None:
        self.service_name = service_name
        self._keyring = None
        self._availability_error = ""
        try:
            import keyring

            backend = keyring.get_keyring()
            priority = float(getattr(backend, "priority", 0) or 0)
            if priority <= 0:
                self._availability_error = "사용 가능한 OS 자격증명 backend가 없습니다."
            else:
                self._keyring = keyring
        except ModuleNotFoundError:
            self._availability_error = (
                "현재 실행 환경에서 OS 자격증명 저장소를 사용할 수 없습니다."
            )
        except Exception as exc:
            self._availability_error = str(exc) or "OS 자격증명 저장소를 사용할 수 없습니다."

    @property
    def available(self) -> bool:
        return self._keyring is not None

    @property
    def availability_error(self) -> str:
        return self._availability_error

    def get_password(self, profile_id: str) -> str | None:
        if self._keyring is None:
            raise RuntimeError(self._availability_error or "OS 자격증명 저장소를 사용할 수 없습니다.")
        return self._keyring.get_password(self.service_name, profile_id)

    def set_password(self, profile_id: str, password: str) -> None:
        if self._keyring is None:
            raise RuntimeError(self._availability_error or "OS 자격증명 저장소를 사용할 수 없습니다.")
        self._keyring.set_password(self.service_name, profile_id, password)

    def delete_password(self, profile_id: str) -> None:
        if self._keyring is None:
            raise RuntimeError(self._availability_error or "OS 자격증명 저장소를 사용할 수 없습니다.")
        try:
            self._keyring.delete_password(self.service_name, profile_id)
        except Exception as exc:
            if exc.__class__.__name__ != "PasswordDeleteError":
                raise


def _normalized_credential_storage(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in CREDENTIAL_STORAGE_CHOICES else CREDENTIAL_STORAGE_LOCAL


def _file_validation_marker(path_text: str) -> dict[str, object]:
    path = Path(str(path_text or "").strip()).expanduser()
    marker: dict[str, object] = {"path": str(path)}
    try:
        stat = path.stat()
    except OSError:
        marker["missing"] = True
    else:
        marker["size"] = int(stat.st_size)
        marker["mtime_ns"] = int(stat.st_mtime_ns)
    return marker


def profile_validation_signature(profile: ConnectionProfile) -> str:
    payload = {
        "profile_id": str(profile.profile_id),
        "base_url": str(profile.base_url or "").strip().rstrip("/"),
        "username": str(profile.username or "").strip(),
        "password_digest": hashlib.sha256(str(profile.password or "").encode("utf-8")).hexdigest(),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_mode_validation_signature(settings: AppSettings) -> str:
    payload = {
        "schema": _file_validation_marker(settings.offline_schema_path),
        "tracker_configuration": _file_validation_marker(
            settings.offline_tracker_configuration_path
        ),
        "query_data": _file_validation_marker(settings.offline_query_data_path),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def effective_gui_settings(
    app_settings: AppSettings,
    batch_settings: GuiSettings | None = None,
) -> GuiSettings:
    base = batch_settings or GuiSettings()
    active_profile = app_settings.active_profile()
    return GuiSettings(
        **{
            **asdict(base),
            "theme_name": normalize_gui_theme_name(app_settings.theme_name),
            "window_width": int(app_settings.window_width or 1160),
            "window_height": int(app_settings.window_height or 780),
            "window_is_maximized": bool(app_settings.window_is_maximized),
            "window_is_fullscreen": bool(app_settings.window_is_fullscreen),
            "navigation_collapsed": bool(app_settings.navigation_collapsed),
            "base_url": "" if active_profile is None else str(active_profile.base_url or ""),
            "username": "" if active_profile is None else str(active_profile.username or ""),
            "password": "" if active_profile is None else str(active_profile.password or ""),
            "save_password": bool(
                active_profile is not None
                and active_profile.credential_storage != CREDENTIAL_STORAGE_NONE
            ),
            "offline_mode": bool(app_settings.offline_mode),
            "server_wiki_html_enabled": bool(
                active_profile is not None and active_profile.server_wiki_html_enabled
            ),
            "offline_schema_path": str(app_settings.offline_schema_path or ""),
            "offline_tracker_configuration_path": str(
                app_settings.offline_tracker_configuration_path or ""
            ),
            "offline_query_data_path": str(app_settings.offline_query_data_path or ""),
            "default_project_id": str(app_settings.default_project_id or ""),
            "default_tracker_id": str(app_settings.default_tracker_id or ""),
            "rate_limit_retry_delay_seconds": float(
                app_settings.rate_limit_retry_delay_seconds or 0
            ),
            "rate_limit_max_retries": int(app_settings.rate_limit_max_retries or 0),
            "api_monitor_enabled": bool(app_settings.api_monitor_enabled),
            "api_monitor_slow_threshold_ms": int(
                app_settings.api_monitor_slow_threshold_ms
                or API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
            ),
            "bulk_update_chunk_size": max(
                int(app_settings.bulk_update_chunk_size or 1000), 1
            ),
            "output_dir": str(app_settings.output_dir or "output"),
        }
    )


class GuiSettingsStore:
    """전역 앱 설정, legacy 설정과 배치 preset을 저장하고 변환한다."""

    def __init__(self, root_dir: Path | None = None, credential_store=None) -> None:
        self.root_dir = root_dir or (Path.home() / APP_DIR_NAME)
        self.settings_path = self.root_dir / SETTINGS_FILE_NAME
        self.app_settings_path = self.root_dir / APP_SETTINGS_FILE_NAME
        self.key_path = self.root_dir / KEY_FILE_NAME
        self.workflow_preset_path = self.root_dir / WORKFLOW_PRESET_FILE_NAME
        self.workflow_preset_collection_path = (
            self.root_dir / WORKFLOW_PRESET_COLLECTION_FILE_NAME
        )
        self.credential_store = credential_store or KeyringCredentialStore()

    @property
    def os_credential_available(self) -> bool:
        return bool(getattr(self.credential_store, "available", False))

    @property
    def os_credential_availability_error(self) -> str:
        return str(getattr(self.credential_store, "availability_error", "") or "")

    def workflow_connection_scope(self, settings: GuiSettings | None = None) -> str:
        """민감한 연결 값을 저장하지 않는 workflow preset 범위를 만든다."""
        current = settings or self.load()
        if bool(getattr(current, "offline_mode", False)):
            return "offline"
        if self.app_settings_path.exists():
            app_settings = self.load_app_settings()
            if bool(app_settings.offline_mode):
                return "offline"
            profile_id = str(app_settings.active_profile_id or "").strip()
            if profile_id:
                return f"profile:{profile_id}"

        legacy_identity = {
            "base_url": str(getattr(current, "base_url", "") or "").strip().rstrip("/"),
            "username": str(getattr(current, "username", "") or "").strip(),
        }
        if not legacy_identity["base_url"] and not legacy_identity["username"]:
            return ""
        serialized = json.dumps(
            legacy_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"legacy:{digest}"

    def load(self) -> GuiSettings:
        legacy_settings = self._load_legacy_settings()
        if not self.app_settings_path.exists():
            return legacy_settings
        app_settings = self.load_app_settings()
        effective = effective_gui_settings(app_settings, legacy_settings)
        if app_settings.offline_mode:
            if (
                app_settings.test_mode_validated_signature
                and app_settings.test_mode_validated_signature
                == test_mode_validation_signature(app_settings)
            ):
                return effective
            effective = replace(effective, offline_mode=False)

        profile = app_settings.active_profile()
        if (
            profile is not None
            and not profile.credential_error
            and profile.validated_signature
            and profile.validated_signature == profile_validation_signature(profile)
        ):
            return effective
        return replace(
            effective,
            base_url="",
            username="",
            password="",
            save_password=False,
        )

    def save(self, settings: GuiSettings) -> None:
        """호환용 legacy 설정을 저장한다.

        새 전역 설정 파일이 존재하면 자격증명은 중복 저장하지 않는다.
        """
        self.root_dir.mkdir(parents=True, exist_ok=True)
        value = settings
        if self.app_settings_path.exists():
            value = GuiSettings(**{**asdict(settings), "password": "", "save_password": False})
        payload = self._settings_payload(value)
        self._write_json_atomic(self.settings_path, payload)

    def ensure_app_settings(self) -> AppSettings:
        if self.app_settings_path.exists():
            return self.load_app_settings()
        migrated = self.migrate_legacy_settings()
        self.save_app_settings(migrated)
        return self.load_app_settings()

    def migrate_legacy_settings(self) -> AppSettings:
        legacy = self._load_legacy_settings()
        legacy_preset = self.load_workflow_preset()
        if legacy_preset is not None and int(legacy_preset.version or 1) < APP_SETTINGS_VERSION:
            preset_settings = legacy_preset.settings
            legacy = GuiSettings(
                **{
                    **asdict(preset_settings),
                    "window_width": legacy.window_width,
                    "window_height": legacy.window_height,
                    "window_is_maximized": legacy.window_is_maximized,
                    "window_is_fullscreen": legacy.window_is_fullscreen,
                    "navigation_collapsed": legacy.navigation_collapsed,
                }
            )
        has_legacy_file = self.settings_path.exists()
        has_profile = bool(
            str(legacy.base_url or "").strip()
            or str(legacy.username or "").strip()
            or str(legacy.password or "")
        )
        profiles: list[ConnectionProfile] = []
        active_profile_id = ""
        if has_profile:
            active_profile_id = "legacy-default"
            profiles.append(
                ConnectionProfile(
                    profile_id=active_profile_id,
                    name="기존 연결",
                    base_url=str(legacy.base_url or ""),
                    username=str(legacy.username or ""),
                    password=str(legacy.password or ""),
                    credential_storage=(
                        CREDENTIAL_STORAGE_LOCAL
                        if legacy.save_password
                        else CREDENTIAL_STORAGE_NONE
                    ),
                    server_wiki_html_enabled=bool(legacy.server_wiki_html_enabled),
                )
            )
        return AppSettings(
            active_profile_id=active_profile_id,
            profiles=profiles,
            theme_name=normalize_gui_theme_name(legacy.theme_name),
            window_width=int(legacy.window_width or 1160),
            window_height=int(legacy.window_height or 780),
            window_is_maximized=bool(legacy.window_is_maximized),
            window_is_fullscreen=bool(legacy.window_is_fullscreen),
            navigation_collapsed=bool(legacy.navigation_collapsed),
            rate_limit_retry_delay_seconds=float(legacy.rate_limit_retry_delay_seconds or 0),
            rate_limit_max_retries=int(legacy.rate_limit_max_retries or 0),
            api_monitor_enabled=bool(legacy.api_monitor_enabled),
            api_monitor_slow_threshold_ms=int(
                legacy.api_monitor_slow_threshold_ms
                or API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
            ),
            bulk_update_chunk_size=max(
                int(getattr(legacy, "bulk_update_chunk_size", 1000) or 1000), 1
            ),
            output_dir=str(legacy.output_dir or "output"),
            offline_mode=bool(legacy.offline_mode),
            offline_schema_path=str(legacy.offline_schema_path or ""),
            offline_tracker_configuration_path=str(
                legacy.offline_tracker_configuration_path or ""
            ),
            offline_query_data_path=str(legacy.offline_query_data_path or ""),
            default_project_id=str(legacy.default_project_id or ""),
            default_tracker_id=str(legacy.default_tracker_id or ""),
            migrated_from_legacy=has_legacy_file or self.workflow_preset_path.exists(),
        )

    def load_app_settings(self) -> AppSettings:
        if not self.app_settings_path.exists():
            return self.migrate_legacy_settings()
        payload = json.loads(self.app_settings_path.read_text(encoding="utf-8"))
        return self._app_settings_from_payload(payload)

    def save_app_settings(self, settings: AppSettings) -> None:
        normalized = self._normalize_app_settings(settings)
        previous_bytes = (
            self.app_settings_path.read_bytes() if self.app_settings_path.exists() else None
        )
        previous_raw = self._read_json_object(self.app_settings_path)
        previous_os_ids = {
            str(item.get("profile_id") or "")
            for item in previous_raw.get("profiles", [])
            if isinstance(item, dict)
            and item.get("credential_storage") == CREDENTIAL_STORAGE_OS
            and str(item.get("profile_id") or "")
        }
        target_os_profiles = {
            profile.profile_id: profile
            for profile in normalized.profiles
            if profile.credential_storage == CREDENTIAL_STORAGE_OS
        }
        affected_os_ids = previous_os_ids | set(target_os_profiles)
        previous_os_secrets: dict[str, str | None] = {}

        if affected_os_ids and self.os_credential_available:
            for profile_id in affected_os_ids:
                previous_os_secrets[profile_id] = self.credential_store.get_password(profile_id)
        elif target_os_profiles:
            raise RuntimeError(
                self.os_credential_availability_error
                or "OS 자격증명 저장소를 사용할 수 없습니다."
            )

        try:
            for profile_id, profile in target_os_profiles.items():
                secret = str(profile.password or "")
                if not secret:
                    secret = str(previous_os_secrets.get(profile_id) or "")
                if not secret:
                    raise ValueError(f"'{profile.name}' 프로필의 비밀번호가 비어 있습니다.")
                self.credential_store.set_password(profile_id, secret)
                if self.credential_store.get_password(profile_id) != secret:
                    raise RuntimeError(f"'{profile.name}' OS 자격증명 검증에 실패했습니다.")

            payload = self._app_settings_payload(normalized, previous_raw)
            self._write_json_atomic(self.app_settings_path, payload)

            for profile_id in previous_os_ids - set(target_os_profiles):
                self.credential_store.delete_password(profile_id)
        except Exception:
            if previous_bytes is None:
                self.app_settings_path.unlink(missing_ok=True)
            else:
                self.root_dir.mkdir(parents=True, exist_ok=True)
                self.app_settings_path.write_bytes(previous_bytes)
            if self.os_credential_available:
                for profile_id in affected_os_ids:
                    old_secret = previous_os_secrets.get(profile_id)
                    if old_secret is None:
                        self.credential_store.delete_password(profile_id)
                    else:
                        self.credential_store.set_password(profile_id, old_secret)
            raise

    def save_window_preferences(self, settings: GuiSettings) -> None:
        app_settings = self.ensure_app_settings()
        app_settings.window_width = int(settings.window_width or 1160)
        app_settings.window_height = int(settings.window_height or 780)
        app_settings.window_is_maximized = bool(settings.window_is_maximized)
        app_settings.window_is_fullscreen = bool(settings.window_is_fullscreen)
        app_settings.navigation_collapsed = bool(settings.navigation_collapsed)
        self.save_app_settings(app_settings)

    def save_bulk_update_chunk_size(self, chunk_size: int) -> None:
        app_settings = self.ensure_app_settings()
        app_settings.bulk_update_chunk_size = max(int(chunk_size), 1)
        self.save_app_settings(app_settings)

    def export_app_settings(self, path: Path, settings: AppSettings | None = None) -> None:
        value = self._normalize_app_settings(settings or self.load_app_settings())
        payload = {
            "version": APP_SETTINGS_VERSION,
            "active_profile_id": value.active_profile_id,
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "name": profile.name,
                    "base_url": profile.base_url,
                    "username": profile.username,
                    "credential_storage": CREDENTIAL_STORAGE_NONE,
                    "server_wiki_html_enabled": profile.server_wiki_html_enabled,
                }
                for profile in value.profiles
            ],
            "theme_name": value.theme_name,
            "navigation_collapsed": value.navigation_collapsed,
            "rate_limit_retry_delay_seconds": value.rate_limit_retry_delay_seconds,
            "rate_limit_max_retries": value.rate_limit_max_retries,
            "api_monitor_enabled": value.api_monitor_enabled,
            "api_monitor_slow_threshold_ms": value.api_monitor_slow_threshold_ms,
            "bulk_update_chunk_size": value.bulk_update_chunk_size,
            "output_dir": value.output_dir,
            "offline_mode": value.offline_mode,
            "offline_schema_path": value.offline_schema_path,
            "offline_tracker_configuration_path": value.offline_tracker_configuration_path,
            "offline_query_data_path": value.offline_query_data_path,
            "default_project_id": value.default_project_id,
            "default_tracker_id": value.default_tracker_id,
        }
        self._write_json_atomic(Path(path), payload)

    def import_app_settings(self, path: Path) -> AppSettings:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        imported = self._app_settings_from_payload(payload, load_credentials=False)
        for profile in imported.profiles:
            profile.password = ""
            profile.credential_storage = CREDENTIAL_STORAGE_NONE
            profile.validated_signature = ""
            profile.validated_at = ""
            profile.credential_error = ""
        imported.test_mode_validated_signature = ""
        imported.test_mode_validated_at = ""
        return imported

    def load_workflow_preset(self) -> GuiWorkflowPreset | None:
        if not self.workflow_preset_path.exists():
            return None

        payload = json.loads(self.workflow_preset_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("전체 설정 파일 형식이 올바르지 않습니다.")
        return self._workflow_preset_from_payload(payload)

    def _workflow_preset_from_payload(
        self,
        payload: dict[str, Any],
    ) -> GuiWorkflowPreset:
        raw_settings = payload.get("settings")
        settings_payload = as_mapping(raw_settings)
        return GuiWorkflowPreset(
            version=int(payload.get("version") or 1),
            preset_id=str(payload.get("preset_id") or uuid4().hex),
            name=str(payload.get("name") or "기본 설정").strip() or "기본 설정",
            connection_scope=str(payload.get("connection_scope") or "").strip(),
            project_id=str(payload.get("project_id") or "").strip(),
            tracker_id=str(payload.get("tracker_id") or "").strip(),
            is_default=bool(payload.get("is_default", False)),
            settings=self._settings_from_payload(settings_payload),
            file_options=self._dict_payload(payload.get("file_options")),
            root_item_config=self._dict_payload(payload.get("root_item_config")),
            selected_mapping={
                str(key): str(value)
                for key, value in self._dict_payload(payload.get("selected_mapping")).items()
                if str(key).strip() and str(value).strip()
            },
            selected_mapping_modes={
                str(key): self._operation_scope_payload(value)
                for key, value in self._dict_payload(payload.get("selected_mapping_modes")).items()
                if str(key).strip() and isinstance(value, dict)
            },
            selected_default_values={
                str(key): str(value)
                for key, value in self._dict_payload(payload.get("selected_default_values")).items()
                if str(key).strip() and str(value).strip()
            },
            selected_default_value_modes={
                str(key): self._operation_scope_payload(value)
                for key, value in self._dict_payload(payload.get("selected_default_value_modes")).items()
                if str(key).strip() and isinstance(value, dict)
            },
            selected_tracker_item_settings={
                str(key): dict(value)
                for key, value in self._dict_payload(payload.get("selected_tracker_item_settings")).items()
                if str(key).strip() and isinstance(value, dict)
            },
        )

    def _workflow_preset_payload(self, preset: GuiWorkflowPreset) -> dict[str, Any]:
        settings_payload = self._settings_payload(preset.settings)
        if self.app_settings_path.exists():
            settings_payload = {
                "upload_mode": normalize_gui_upload_mode(preset.settings.upload_mode),
                "excel_header_row": int(preset.settings.excel_header_row or 1),
                "summary_column": str(preset.settings.summary_column or "Summary"),
                "excel_sheet_name": str(preset.settings.excel_sheet_name or "0"),
                "last_file_path": str(preset.settings.last_file_path or ""),
                "password_encrypted": "",
                "save_password": False,
            }
        return {
            "version": APP_SETTINGS_VERSION if self.app_settings_path.exists() else int(preset.version or 1),
            "preset_id": str(preset.preset_id or uuid4().hex),
            "name": str(preset.name or "기본 설정").strip() or "기본 설정",
            "connection_scope": str(preset.connection_scope or "").strip(),
            "project_id": str(preset.project_id or "").strip(),
            "tracker_id": str(preset.tracker_id or "").strip(),
            "is_default": bool(preset.is_default),
            "settings": settings_payload,
            "file_options": self._dict_payload(preset.file_options),
            "root_item_config": self._dict_payload(preset.root_item_config),
            "selected_mapping": {
                str(key): str(value)
                for key, value in dict(preset.selected_mapping or {}).items()
                if str(key).strip() and str(value).strip()
            },
            "selected_mapping_modes": {
                str(key): self._operation_scope_payload(value)
                for key, value in dict(preset.selected_mapping_modes or {}).items()
                if str(key).strip() and isinstance(value, dict)
            },
            "selected_default_values": {
                str(key): str(value)
                for key, value in dict(preset.selected_default_values or {}).items()
                if str(key).strip() and str(value).strip()
            },
            "selected_default_value_modes": {
                str(key): self._operation_scope_payload(value)
                for key, value in dict(preset.selected_default_value_modes or {}).items()
                if str(key).strip() and isinstance(value, dict)
            },
            "selected_tracker_item_settings": {
                str(key): dict(value)
                for key, value in dict(preset.selected_tracker_item_settings or {}).items()
                if str(key).strip() and isinstance(value, dict)
            },
        }

    def _tracker_workflow_preset_payload(
        self,
        preset: GuiWorkflowPreset,
    ) -> dict[str, Any]:
        """Named collection에는 배치 설정과 비밀 없는 scope만 저장한다."""
        file_options = dict(preset.file_options or {})
        return {
            "version": WORKFLOW_PRESET_COLLECTION_VERSION,
            "preset_id": str(preset.preset_id or uuid4().hex),
            "name": str(preset.name or "기본 설정").strip() or "기본 설정",
            "connection_scope": str(preset.connection_scope or "").strip(),
            "project_id": str(preset.project_id or "").strip(),
            "tracker_id": str(preset.tracker_id or "").strip(),
            "is_default": bool(preset.is_default),
            "settings": {
                "upload_mode": normalize_gui_upload_mode(preset.settings.upload_mode),
                "excel_header_row": max(int(preset.settings.excel_header_row or 1), 1),
                "summary_column": str(preset.settings.summary_column or "Summary"),
                "excel_sheet_name": str(preset.settings.excel_sheet_name or "0"),
            },
            "file_options": {
                "sheet_name": str(file_options.get("sheet_name") or "0"),
                "header_row": max(int(file_options.get("header_row") or 1), 1),
                "summary_column": str(file_options.get("summary_column") or "Summary"),
            },
            "root_item_config": self._dict_payload(preset.root_item_config),
            "selected_mapping": {
                str(key): str(value)
                for key, value in dict(preset.selected_mapping or {}).items()
                if str(key).strip() and str(value).strip()
            },
            "selected_mapping_modes": {
                str(key): self._operation_scope_payload(value)
                for key, value in dict(preset.selected_mapping_modes or {}).items()
                if str(key).strip() and isinstance(value, dict)
            },
            "selected_default_values": {
                str(key): str(value)
                for key, value in dict(preset.selected_default_values or {}).items()
                if str(key).strip() and str(value).strip()
            },
            "selected_default_value_modes": {
                str(key): self._operation_scope_payload(value)
                for key, value in dict(preset.selected_default_value_modes or {}).items()
                if str(key).strip() and isinstance(value, dict)
            },
            "selected_tracker_item_settings": {
                str(key): dict(value)
                for key, value in dict(preset.selected_tracker_item_settings or {}).items()
                if str(key).strip() and isinstance(value, dict)
            },
        }

    def save_workflow_preset(self, preset: GuiWorkflowPreset) -> None:
        """기존 단일 전체 설정 파일 계약을 유지한다."""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        payload = self._workflow_preset_payload(preset)
        self._write_json_atomic(self.workflow_preset_path, payload)

    def list_tracker_workflow_presets(
        self,
        *,
        connection_scope: str | None = None,
        project_id: str | int | None = None,
        tracker_id: str | int | None = None,
    ) -> list[GuiWorkflowPreset]:
        payload = self._read_json_object(self.workflow_preset_collection_path)
        raw_presets = payload.get("presets")
        if not isinstance(raw_presets, list):
            return []
        normalized_connection = str(connection_scope or "").strip()
        normalized_project = str(project_id or "").strip()
        normalized_tracker = str(tracker_id or "").strip()
        presets: list[GuiWorkflowPreset] = []
        for raw_preset in raw_presets:
            if not isinstance(raw_preset, dict):
                continue
            preset = self._workflow_preset_from_payload(raw_preset)
            if normalized_connection and preset.connection_scope != normalized_connection:
                continue
            if normalized_project and preset.project_id != normalized_project:
                continue
            if normalized_tracker and preset.tracker_id != normalized_tracker:
                continue
            presets.append(preset)
        return sorted(presets, key=lambda item: (item.name.casefold(), item.preset_id))

    def get_default_tracker_workflow_preset(
        self,
        *,
        connection_scope: str,
        project_id: str | int,
        tracker_id: str | int,
    ) -> GuiWorkflowPreset | None:
        if not str(connection_scope or "").strip():
            return None
        presets = self.list_tracker_workflow_presets(
            connection_scope=connection_scope,
            project_id=project_id,
            tracker_id=tracker_id,
        )
        return next((preset for preset in presets if preset.is_default), None)

    def get_tracker_workflow_preset(self, preset_id: str) -> GuiWorkflowPreset | None:
        normalized_id = str(preset_id or "").strip()
        if not normalized_id:
            return None
        for preset in self.list_tracker_workflow_presets():
            if preset.preset_id == normalized_id:
                return preset
        return None

    def save_tracker_workflow_preset(
        self,
        preset: GuiWorkflowPreset,
    ) -> GuiWorkflowPreset:
        connection_scope = str(preset.connection_scope or "").strip()
        project_id = str(preset.project_id or preset.settings.default_project_id or "").strip()
        tracker_id = str(preset.tracker_id or preset.settings.default_tracker_id or "").strip()
        name = str(preset.name or "").strip()
        if not connection_scope:
            raise ValueError("전체 설정을 저장할 연결 범위를 확인할 수 없습니다.")
        if not project_id or not tracker_id:
            raise ValueError("트래커별 설정을 저장하려면 프로젝트와 트래커를 선택해야 합니다.")
        if not name:
            raise ValueError("저장 설정 이름을 입력해야 합니다.")

        normalized = replace(
            preset,
            preset_id=str(preset.preset_id or uuid4().hex),
            name=name,
            connection_scope=connection_scope,
            project_id=project_id,
            tracker_id=tracker_id,
            settings=replace(
                preset.settings,
                default_project_id=project_id,
                default_tracker_id=tracker_id,
            ),
        )
        presets = self.list_tracker_workflow_presets()
        for existing in presets:
            if (
                existing.preset_id != normalized.preset_id
                and existing.connection_scope == connection_scope
                and existing.project_id == project_id
                and existing.tracker_id == tracker_id
                and existing.name.casefold() == name.casefold()
            ):
                raise ValueError(f"같은 트래커에 '{name}' 이름의 저장 설정이 이미 있습니다.")

        updated: list[GuiWorkflowPreset] = []
        replaced_existing = False
        for existing in presets:
            if existing.preset_id == normalized.preset_id:
                updated.append(normalized)
                replaced_existing = True
            else:
                updated.append(existing)
        if not replaced_existing:
            updated.append(normalized)

        target_presets = [
            item
            for item in updated
            if item.connection_scope == connection_scope
            and item.project_id == project_id
            and item.tracker_id == tracker_id
        ]
        existing_default_id = next(
            (
                item.preset_id
                for item in target_presets
                if item.is_default and item.preset_id != normalized.preset_id
            ),
            "",
        )
        preferred_default_id = (
            normalized.preset_id
            if normalized.is_default or not existing_default_id
            else existing_default_id
        )
        updated = [
            replace(item, is_default=item.preset_id == preferred_default_id)
            if item.connection_scope == connection_scope
            and item.project_id == project_id
            and item.tracker_id == tracker_id
            else item
            for item in updated
        ]
        normalized = next(
            item for item in updated if item.preset_id == normalized.preset_id
        )
        payload = {
            "version": WORKFLOW_PRESET_COLLECTION_VERSION,
            "presets": [
                self._tracker_workflow_preset_payload(item)
                for item in sorted(
                    updated,
                    key=lambda item: (
                        item.connection_scope,
                        item.project_id,
                        item.tracker_id,
                        item.name.casefold(),
                        item.preset_id,
                    ),
                )
            ],
        }
        self._write_json_atomic(self.workflow_preset_collection_path, payload)
        return normalized

    def delete_tracker_workflow_preset(self, preset_id: str) -> bool:
        normalized_id = str(preset_id or "").strip()
        if not normalized_id:
            return False
        presets = self.list_tracker_workflow_presets()
        deleted = next(
            (preset for preset in presets if preset.preset_id == normalized_id),
            None,
        )
        remaining = [preset for preset in presets if preset.preset_id != normalized_id]
        if len(remaining) == len(presets):
            return False
        if deleted is not None and deleted.is_default:
            successor = next(
                (
                    preset
                    for preset in sorted(
                        remaining,
                        key=lambda item: (item.name.casefold(), item.preset_id),
                    )
                    if preset.connection_scope == deleted.connection_scope
                    and preset.project_id == deleted.project_id
                    and preset.tracker_id == deleted.tracker_id
                ),
                None,
            )
            if successor is not None:
                remaining = [
                    replace(preset, is_default=preset.preset_id == successor.preset_id)
                    if preset.connection_scope == deleted.connection_scope
                    and preset.project_id == deleted.project_id
                    and preset.tracker_id == deleted.tracker_id
                    else preset
                    for preset in remaining
                ]
        payload = {
            "version": WORKFLOW_PRESET_COLLECTION_VERSION,
            "presets": [
                self._tracker_workflow_preset_payload(item)
                for item in remaining
            ],
        }
        self._write_json_atomic(self.workflow_preset_collection_path, payload)
        return True

    @staticmethod
    def _dict_payload(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _operation_scope_payload(value: Any) -> OperationScope:
        return as_operation_scope(value)

    def _load_legacy_settings(self) -> GuiSettings:
        if not self.settings_path.exists():
            return GuiSettings()
        payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        return self._settings_from_payload(payload)

    def _settings_payload(self, settings: GuiSettings) -> dict[str, Any]:
        payload = asdict(settings)
        password = payload.pop("password", "")
        if settings.save_password and password:
            payload["password_encrypted"] = self._encrypt_password(password)
        else:
            payload["password_encrypted"] = ""
        return payload

    def _settings_from_payload(self, payload: dict[str, Any]) -> GuiSettings:
        payload = dict(payload or {})
        password = ""
        encrypted_password = payload.pop("password_encrypted", "")
        if payload.get("save_password") and encrypted_password:
            password = self._decrypt_password(encrypted_password)
        payload["theme_name"] = normalize_gui_theme_name(payload.get("theme_name"))
        payload["upload_mode"] = normalize_gui_upload_mode(payload.get("upload_mode"))

        return GuiSettings(
            password=password,
            **{key: value for key, value in payload.items() if key in GuiSettings.__dataclass_fields__},
        )

    def _normalize_app_settings(self, settings: AppSettings) -> AppSettings:
        profiles: list[ConnectionProfile] = []
        seen_ids: set[str] = set()
        for raw_profile in settings.profiles:
            profile_id = str(raw_profile.profile_id or "").strip() or uuid4().hex
            if profile_id in seen_ids:
                profile_id = uuid4().hex
            seen_ids.add(profile_id)
            profiles.append(
                ConnectionProfile(
                    profile_id=profile_id,
                    name=str(raw_profile.name or "").strip() or "이름 없는 연결",
                    base_url=str(raw_profile.base_url or "").strip(),
                    username=str(raw_profile.username or "").strip(),
                    password=str(raw_profile.password or ""),
                    credential_storage=_normalized_credential_storage(
                        raw_profile.credential_storage
                    ),
                    server_wiki_html_enabled=bool(
                        getattr(raw_profile, "server_wiki_html_enabled", False)
                    ),
                    validated_signature=str(raw_profile.validated_signature or ""),
                    validated_at=str(raw_profile.validated_at or ""),
                    credential_error=str(raw_profile.credential_error or ""),
                )
            )
        active_profile_id = str(settings.active_profile_id or "")
        if active_profile_id not in seen_ids:
            active_profile_id = profiles[0].profile_id if profiles else ""
        return AppSettings(
            version=APP_SETTINGS_VERSION,
            active_profile_id=active_profile_id,
            profiles=profiles,
            theme_name=normalize_gui_theme_name(settings.theme_name),
            window_width=max(int(settings.window_width or 1160), 860),
            window_height=max(int(settings.window_height or 780), 620),
            window_is_maximized=bool(settings.window_is_maximized),
            window_is_fullscreen=bool(settings.window_is_fullscreen),
            navigation_collapsed=bool(settings.navigation_collapsed),
            rate_limit_retry_delay_seconds=max(
                float(settings.rate_limit_retry_delay_seconds or 0), 0.0
            ),
            rate_limit_max_retries=max(int(settings.rate_limit_max_retries or 0), 0),
            api_monitor_enabled=bool(settings.api_monitor_enabled),
            api_monitor_slow_threshold_ms=min(
                max(
                    int(
                        settings.api_monitor_slow_threshold_ms
                        or API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
                    ),
                    API_MONITOR_MIN_SLOW_THRESHOLD_MS,
                ),
                API_MONITOR_MAX_SLOW_THRESHOLD_MS,
            ),
            bulk_update_chunk_size=max(
                int(getattr(settings, "bulk_update_chunk_size", 1000) or 1000), 1
            ),
            output_dir=str(settings.output_dir or "").strip() or "output",
            offline_mode=bool(settings.offline_mode),
            offline_schema_path=str(settings.offline_schema_path or "").strip(),
            offline_tracker_configuration_path=str(
                settings.offline_tracker_configuration_path or ""
            ).strip(),
            offline_query_data_path=str(settings.offline_query_data_path or "").strip(),
            test_mode_validated_signature=str(settings.test_mode_validated_signature or ""),
            test_mode_validated_at=str(settings.test_mode_validated_at or ""),
            default_project_id=str(settings.default_project_id or ""),
            default_tracker_id=str(settings.default_tracker_id or ""),
            migrated_from_legacy=bool(settings.migrated_from_legacy),
        )

    def _app_settings_payload(
        self,
        settings: AppSettings,
        previous_payload: dict[str, Any],
    ) -> dict[str, Any]:
        previous_profiles = {
            str(profile.get("profile_id") or ""): profile
            for profile in previous_payload.get("profiles", [])
            if isinstance(profile, dict) and str(profile.get("profile_id") or "")
        }
        profiles_payload: list[dict[str, Any]] = []
        for profile in settings.profiles:
            profile_payload: dict[str, Any] = {
                "profile_id": profile.profile_id,
                "name": profile.name,
                "base_url": profile.base_url,
                "username": profile.username,
                "credential_storage": profile.credential_storage,
                "server_wiki_html_enabled": profile.server_wiki_html_enabled,
                "validated_signature": profile.validated_signature,
                "validated_at": profile.validated_at,
            }
            if profile.credential_storage == CREDENTIAL_STORAGE_LOCAL:
                encrypted = ""
                if profile.password:
                    encrypted = self._encrypt_password(profile.password)
                else:
                    previous = previous_profiles.get(profile.profile_id, {})
                    if previous.get("credential_storage") == CREDENTIAL_STORAGE_LOCAL:
                        encrypted = str(previous.get("password_encrypted") or "")
                profile_payload["password_encrypted"] = encrypted
            profiles_payload.append(profile_payload)
        return {
            "version": APP_SETTINGS_VERSION,
            "active_profile_id": settings.active_profile_id,
            "profiles": profiles_payload,
            "theme_name": settings.theme_name,
            "window_width": settings.window_width,
            "window_height": settings.window_height,
            "window_is_maximized": settings.window_is_maximized,
            "window_is_fullscreen": settings.window_is_fullscreen,
            "navigation_collapsed": settings.navigation_collapsed,
            "rate_limit_retry_delay_seconds": settings.rate_limit_retry_delay_seconds,
            "rate_limit_max_retries": settings.rate_limit_max_retries,
            "api_monitor_enabled": settings.api_monitor_enabled,
            "api_monitor_slow_threshold_ms": settings.api_monitor_slow_threshold_ms,
            "bulk_update_chunk_size": settings.bulk_update_chunk_size,
            "output_dir": settings.output_dir,
            "offline_mode": settings.offline_mode,
            "offline_schema_path": settings.offline_schema_path,
            "offline_tracker_configuration_path": settings.offline_tracker_configuration_path,
            "offline_query_data_path": settings.offline_query_data_path,
            "test_mode_validated_signature": settings.test_mode_validated_signature,
            "test_mode_validated_at": settings.test_mode_validated_at,
            "default_project_id": settings.default_project_id,
            "default_tracker_id": settings.default_tracker_id,
            "migrated_from_legacy": settings.migrated_from_legacy,
        }

    def _app_settings_from_payload(
        self,
        payload: dict[str, Any],
        *,
        load_credentials: bool = True,
    ) -> AppSettings:
        profiles: list[ConnectionProfile] = []
        for raw_profile in payload.get("profiles", []):
            if not isinstance(raw_profile, dict):
                continue
            storage = _normalized_credential_storage(
                raw_profile.get("credential_storage")
            )
            password = ""
            credential_error = ""
            if load_credentials and storage == CREDENTIAL_STORAGE_LOCAL:
                encrypted = str(raw_profile.get("password_encrypted") or "")
                if encrypted:
                    try:
                        password = self._decrypt_password(encrypted)
                    except Exception as exc:
                        credential_error = str(exc) or "로컬 암호화 비밀번호를 복원하지 못했습니다."
            elif load_credentials and storage == CREDENTIAL_STORAGE_OS:
                if self.os_credential_available:
                    try:
                        password = str(
                            self.credential_store.get_password(
                                str(raw_profile.get("profile_id") or "")
                            )
                            or ""
                        )
                    except Exception as exc:
                        credential_error = str(exc)
                else:
                    credential_error = (
                        self.os_credential_availability_error
                        or "OS 자격증명 저장소를 사용할 수 없습니다."
                    )
            profiles.append(
                ConnectionProfile(
                    profile_id=str(raw_profile.get("profile_id") or "") or uuid4().hex,
                    name=str(raw_profile.get("name") or "이름 없는 연결"),
                    base_url=str(raw_profile.get("base_url") or ""),
                    username=str(raw_profile.get("username") or ""),
                    password=password,
                    credential_storage=storage,
                    server_wiki_html_enabled=bool(
                        raw_profile.get("server_wiki_html_enabled", False)
                    ),
                    validated_signature=str(raw_profile.get("validated_signature") or ""),
                    validated_at=str(raw_profile.get("validated_at") or ""),
                    credential_error=credential_error,
                )
            )
        settings = AppSettings(
            version=int(payload.get("version") or APP_SETTINGS_VERSION),
            active_profile_id=str(payload.get("active_profile_id") or ""),
            profiles=profiles,
            theme_name=normalize_gui_theme_name(payload.get("theme_name")),
            window_width=int(payload.get("window_width") or 1160),
            window_height=int(payload.get("window_height") or 780),
            window_is_maximized=bool(payload.get("window_is_maximized", False)),
            window_is_fullscreen=bool(payload.get("window_is_fullscreen", False)),
            navigation_collapsed=bool(payload.get("navigation_collapsed", False)),
            rate_limit_retry_delay_seconds=float(
                payload.get("rate_limit_retry_delay_seconds") or 0
            ),
            rate_limit_max_retries=int(payload.get("rate_limit_max_retries") or 0),
            api_monitor_enabled=bool(payload.get("api_monitor_enabled", False)),
            api_monitor_slow_threshold_ms=int(
                payload.get("api_monitor_slow_threshold_ms")
                or API_MONITOR_DEFAULT_SLOW_THRESHOLD_MS
            ),
            bulk_update_chunk_size=max(
                int(payload.get("bulk_update_chunk_size") or 1000), 1
            ),
            output_dir=str(payload.get("output_dir") or "output"),
            offline_mode=bool(payload.get("offline_mode", False)),
            offline_schema_path=str(payload.get("offline_schema_path") or ""),
            offline_tracker_configuration_path=str(
                payload.get("offline_tracker_configuration_path") or ""
            ),
            offline_query_data_path=str(payload.get("offline_query_data_path") or ""),
            test_mode_validated_signature=str(
                payload.get("test_mode_validated_signature") or ""
            ),
            test_mode_validated_at=str(payload.get("test_mode_validated_at") or ""),
            default_project_id=str(payload.get("default_project_id") or ""),
            default_tracker_id=str(payload.get("default_tracker_id") or ""),
            migrated_from_legacy=bool(payload.get("migrated_from_legacy", False)),
        )
        return self._normalize_app_settings(settings)

    @staticmethod
    def _read_json_object(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return as_mapping(payload)

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)

    def _get_fernet(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise RuntimeError(
                "GUI 암호화 저장에는 cryptography 패키지가 필요합니다."
            ) from exc

        self.root_dir.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
        return Fernet(self.key_path.read_bytes())

    def _encrypt_password(self, password: str) -> str:
        return self._get_fernet().encrypt(password.encode("utf-8")).decode("utf-8")

    def _decrypt_password(self, encrypted_password: str) -> str:
        return self._get_fernet().decrypt(encrypted_password.encode("utf-8")).decode("utf-8")
