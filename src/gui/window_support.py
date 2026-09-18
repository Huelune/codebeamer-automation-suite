from __future__ import annotations

import time
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import datetime
from typing import Any

from .settings_store import GuiSettings
from .settings_store import GuiWorkflowPreset
from .upload_context import MappingContext
from .upload_context import ValidationContext


def _require_qt():
    try:
        from PySide6.QtCore import QEventLoop
        from PySide6.QtCore import QSize
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWidgets import QComboBox
        from PySide6.QtWidgets import QDialog
        from PySide6.QtWidgets import QFrame
        from PySide6.QtWidgets import QHBoxLayout
        from PySide6.QtWidgets import QInputDialog
        from PySide6.QtWidgets import QLabel
        from PySide6.QtWidgets import QMainWindow
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtWidgets import QPlainTextEdit
        from PySide6.QtWidgets import QProgressBar
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtWidgets import QScrollArea
        from PySide6.QtWidgets import QStackedWidget
        from PySide6.QtWidgets import QStatusBar
        from PySide6.QtWidgets import QVBoxLayout
        from PySide6.QtWidgets import QWidget
    except ImportError as exc:
        raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

    return {
        "QApplication": QApplication,
        "QDialog": QDialog,
        "QComboBox": QComboBox,
        "QEventLoop": QEventLoop,
        "QFrame": QFrame,
        "QHBoxLayout": QHBoxLayout,
        "QInputDialog": QInputDialog,
        "QLabel": QLabel,
        "QMainWindow": QMainWindow,
        "QMessageBox": QMessageBox,
        "QPlainTextEdit": QPlainTextEdit,
        "QProgressBar": QProgressBar,
        "QPushButton": QPushButton,
        "QScrollArea": QScrollArea,
        "QSize": QSize,
        "QStackedWidget": QStackedWidget,
        "QStatusBar": QStatusBar,
        "Qt": Qt,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }


@dataclass
class GuiSessionState:
    settings: GuiSettings
    file_state: dict[str, object]
    projects: list[dict[str, object]]
    trackers: list[dict[str, object]]
    workflow_preset: GuiWorkflowPreset | None
    mapping_context: MappingContext | None
    validation_context: ValidationContext | None
    upload_result: dict[str, Any] | None


@dataclass
class UploadProgressState:
    success_count: int = 0
    failed_count: int = 0
    retry_count: int = 0
    total_count: int = 0
    phase_totals: dict[str, int] = field(
        default_factory=lambda: {"insert": 0, "update": 0}
    )
    phase_counts: dict[str, int] = field(
        default_factory=lambda: {
            "insert_success": 0,
            "insert_failed": 0,
            "update_success": 0,
            "update_failed": 0,
        }
    )
    current_phase: str = ""
    current: int = 0
    total: int = 0
    event_started_at: dict[str, float] = field(default_factory=dict)
    batch_started_at: float | None = None


def _format_duration_text(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 1:
        return f"{seconds:.2f}초"
    if seconds < 60:
        return f"{seconds:.1f}초"
    minutes = int(seconds // 60)
    remainder = seconds - (minutes * 60)
    return f"{minutes}분 {remainder:.1f}초"


def _format_clock_text(timestamp: float | None = None) -> str:
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _estimate_upload_remaining_seconds(
    elapsed_seconds: float | None,
    completed_count: int,
    total_count: int,
) -> float | None:
    if elapsed_seconds is None or elapsed_seconds < 0:
        return None

    normalized_total = max(int(total_count), 0)
    normalized_completed = max(int(completed_count), 0)
    if normalized_total <= 0 or normalized_completed <= 0:
        return None
    if normalized_completed >= normalized_total:
        return 0.0

    average_seconds = elapsed_seconds / normalized_completed
    remaining_count = normalized_total - normalized_completed
    return max(average_seconds * remaining_count, 0.0)


def _format_upload_progress_text(completed_count: int, total_count: int) -> str:
    normalized_total = max(int(total_count), 0)
    normalized_completed = max(int(completed_count), 0)
    if normalized_total <= 0:
        return "진행률 0.0% (0 / 0)"

    clamped_completed = min(normalized_completed, normalized_total)
    percent = (clamped_completed / normalized_total) * 100
    return f"진행률 {percent:.1f}% ({clamped_completed} / {normalized_total})"


def _format_upload_eta_text(
    *,
    now_timestamp: float,
    elapsed_seconds: float | None,
    completed_count: int,
    total_count: int,
) -> str:
    remaining_seconds = _estimate_upload_remaining_seconds(
        elapsed_seconds,
        completed_count,
        total_count,
    )
    if remaining_seconds is None:
        return "예상 종료: -"
    if remaining_seconds <= 0:
        return f"예상 종료: 완료됨 ({_format_clock_text(now_timestamp)})"

    finish_timestamp = now_timestamp + remaining_seconds
    return (
        f"예상 종료: {_format_clock_text(finish_timestamp)} "
        f"(남은 약 {_format_duration_text(remaining_seconds)})"
    )


def _clamp_window_dimension(value: object, *, fallback: int, minimum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(normalized, minimum)


def _window_size_from_settings(settings: GuiSettings) -> tuple[int, int]:
    return (
        _clamp_window_dimension(
            getattr(settings, "window_width", 1160),
            fallback=1160,
            minimum=860,
        ),
        _clamp_window_dimension(
            getattr(settings, "window_height", 780),
            fallback=780,
            minimum=620,
        ),
    )


def _merge_window_preferences(current_settings: GuiSettings, incoming_settings: GuiSettings) -> GuiSettings:
    width, height = _window_size_from_settings(current_settings)
    return replace(
        incoming_settings,
        window_width=width,
        window_height=height,
        window_is_maximized=bool(getattr(current_settings, "window_is_maximized", False)),
        window_is_fullscreen=bool(getattr(current_settings, "window_is_fullscreen", False)),
        navigation_collapsed=bool(
            getattr(current_settings, "navigation_collapsed", False)
        ),
    )


def _merge_root_item_page_configs(
    base_config: dict[str, object] | None,
    *,
    structure_config: dict[str, object] | None = None,
    field_config: dict[str, object] | None = None,
) -> dict[str, object]:
    merged = dict(base_config or {})
    if structure_config:
        merged.update(dict(structure_config))
    if field_config:
        merged["field_assignments"] = dict(field_config.get("field_assignments") or {})
        merged["field_sources"] = dict(field_config.get("field_sources") or {})
    return merged
