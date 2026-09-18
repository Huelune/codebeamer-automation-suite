
from __future__ import annotations

from typing import Any

from src.mapping_service import MappingService
from src.upload_policy import UPLOAD_MODE_CREATE as GUI_UPLOAD_MODE_CREATE
from src.upload_policy import UPLOAD_MODE_UPDATE as GUI_UPLOAD_MODE_UPDATE
from src.upload_policy import UPLOAD_MODE_UPSERT as GUI_UPLOAD_MODE_UPSERT


USER_HIDDEN_TABLE_COLUMNS = {
    "_row_id",
    "parent_row_id",
    "depth",
    "_summary_indent",
    "_start_excel_row",
    "_end_excel_row",
    "_excel_row",
    "payload_json",
    "payload_status",
    "payload_error",
    "error_response_json",
    "source_file_path",
}

PAGE_MARGIN = 4
PAGE_SPACING = 6
SECTION_SPACING = 6
CARD_HORIZONTAL_MARGIN = 8
CARD_VERTICAL_MARGIN = 6
FORM_HORIZONTAL_SPACING = 8
FORM_VERTICAL_SPACING = 4
DEFAULT_FORM_FIELD_MIN_WIDTH = 210
FORM_PANEL_MAX_WIDTH = 760
WIDE_FORM_PANEL_MAX_WIDTH = 860
PREVIEW_TABLE_MIN_HEIGHT = 180
PRIMARY_TABLE_MIN_HEIGHT = 240
SECONDARY_TABLE_MIN_HEIGHT = 220
DETAIL_PANE_MIN_HEIGHT = 110
UPLOAD_DETAIL_TABS_MIN_HEIGHT = 220
ACTIVITY_TABLE_MIN_HEIGHT = 160


def _is_hidden_user_table_column(column_name: object) -> bool:
    text = str(column_name or "").strip()
    if not text:
        return False
    if text in USER_HIDDEN_TABLE_COLUMNS:
        return True
    if text.startswith("_"):
        return True
    return "__" in text


def _settings_mode_toggle_text(is_offline: bool) -> str:
    return "테스트"


def _settings_upload_mode_choices() -> list[tuple[str, str]]:
    return [
        (GUI_UPLOAD_MODE_CREATE, "신규 생성"),
        (GUI_UPLOAD_MODE_UPDATE, "기존 수정"),
        (GUI_UPLOAD_MODE_UPSERT, "혼합 처리"),
    ]


def _settings_mode_description(is_offline: bool) -> str:
    if bool(is_offline):
        return "테스트 모드에서는 저장된 schema/config snapshot으로만 검증합니다."
    return "기본 모드에서는 Codebeamer 서버 연결과 로그인 정보를 사용합니다."


def _project_selection_status_text(is_offline: bool) -> str:
    if bool(is_offline):
        return "테스트 모드에서는 schema snapshot 기준 가상 프로젝트/트래커를 자동으로 불러옵니다."
    return "프로젝트 불러오기를 실행하면 프로젝트 목록을 조회합니다."


def _project_selection_refresh_button_text(is_offline: bool) -> str:
    return "스냅샷 불러오기" if bool(is_offline) else "프로젝트 불러오기"


def _project_selection_source_signature(settings: Any) -> tuple[str, str, str, str, str]:
    return (
        "offline" if bool(getattr(settings, "offline_mode", False)) else "online",
        str(getattr(settings, "offline_schema_path", "") or "").strip(),
        str(getattr(settings, "offline_tracker_configuration_path", "") or "").strip(),
        str(getattr(settings, "base_url", "") or "").strip(),
        str(getattr(settings, "username", "") or "").strip(),
    )


def _tracker_item_sample_values(upload_preview_df: Any, column_name: str, limit: int = 3) -> list[Any]:
    if upload_preview_df is None or not hasattr(upload_preview_df, "columns"):
        return []
    normalized_column = str(column_name).strip()
    if normalized_column not in upload_preview_df.columns:
        return []

    samples: list[Any] = []
    seen_keys: set[str] = set()
    for raw_value in upload_preview_df[normalized_column].tolist():
        if raw_value is None:
            continue
        if isinstance(raw_value, str) and not raw_value.strip():
            continue
        if isinstance(raw_value, list):
            flattened = [str(item).strip() for item in raw_value if item is not None and str(item).strip()]
            if not flattened:
                continue
            sample_key = repr(flattened)
        else:
            sample_key = str(raw_value).strip()
            if not sample_key:
                continue
        if sample_key in seen_keys:
            continue
        seen_keys.add(sample_key)
        samples.append(raw_value)
        if len(samples) >= max(int(limit), 1):
            break
    return samples


def _format_tracker_item_example_value(raw_value: Any) -> str:
    if isinstance(raw_value, list):
        parts = [str(item).strip() for item in raw_value if item is not None and str(item).strip()]
        if not parts:
            return "(빈 값)"
        return ", ".join(parts[:3]) + (" ..." if len(parts) > 3 else "")
    text = str(raw_value or "").strip()
    return text or "(빈 값)"


def _format_tracker_item_example_resolution(resolved_value: Any) -> str:
    if isinstance(resolved_value, list):
        ids = [str(item.get("id")) for item in resolved_value if isinstance(item, dict) and item.get("id") is not None]
        return ", ".join(ids) if ids else "(해석 실패)"
    if isinstance(resolved_value, dict) and resolved_value.get("id") is not None:
        return str(resolved_value["id"])
    return "(해석 실패)"


def _normalize_tracker_item_regex_preview_error(exc: Exception) -> str:
    message = str(exc).strip()
    lowered = message.lower()
    if "regex pattern is empty" in lowered:
        return "정규식 비어 있음"
    if "did not match value" in lowered:
        return "불일치"
    if "did not produce numeric id" in lowered:
        return "숫자 ID 아님"
    if "produced empty match" in lowered:
        return "빈 결과"
    return message or "해석 실패"


def _build_tracker_item_regex_preview_text(
    sample_values: list[Any],
    *,
    pattern: str,
    multiple_values: bool,
) -> str:
    regex_pattern = str(pattern or "").strip()
    if not regex_pattern:
        return "정규식 없음"
    if not sample_values:
        return "샘플 값 없음"

    examples: list[str] = []
    for raw_value in sample_values[:3]:
        source_text = _format_tracker_item_example_value(raw_value)
        try:
            resolved_value = MappingService.resolve_tracker_item_reference_value_with_regex(
                raw_value,
                multiple_values=multiple_values,
                pattern=regex_pattern,
            )
            result_text = _format_tracker_item_example_resolution(resolved_value)
        except Exception as exc:
            result_text = _normalize_tracker_item_regex_preview_error(exc)
        examples.append(f"{source_text} -> {result_text}")
    return " | ".join(examples)

def _require_qt():
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QCheckBox
        from PySide6.QtWidgets import QComboBox
        from PySide6.QtWidgets import QDoubleSpinBox
        from PySide6.QtWidgets import QFileDialog
        from PySide6.QtWidgets import QFormLayout
        from PySide6.QtWidgets import QFrame
        from PySide6.QtWidgets import QHBoxLayout
        from PySide6.QtWidgets import QHeaderView
        from PySide6.QtWidgets import QLabel
        from PySide6.QtWidgets import QLineEdit
        from PySide6.QtWidgets import QPlainTextEdit
        from PySide6.QtWidgets import QProgressBar
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtWidgets import QSizePolicy
        from PySide6.QtWidgets import QSpinBox
        from PySide6.QtWidgets import QTableWidget
        from PySide6.QtWidgets import QTableWidgetItem
        from PySide6.QtWidgets import QTabWidget
        from PySide6.QtWidgets import QToolButton
        from PySide6.QtWidgets import QVBoxLayout
        from PySide6.QtWidgets import QWidget
    except ImportError as exc:
        raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

    return {
        "Qt": Qt,
        "QColor": QColor,
        "QCheckBox": QCheckBox,
        "QComboBox": QComboBox,
        "QDoubleSpinBox": QDoubleSpinBox,
        "QFileDialog": QFileDialog,
        "QFrame": QFrame,
        "QFormLayout": QFormLayout,
        "QHBoxLayout": QHBoxLayout,
        "QHeaderView": QHeaderView,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QPlainTextEdit": QPlainTextEdit,
        "QProgressBar": QProgressBar,
        "QPushButton": QPushButton,
        "QSizePolicy": QSizePolicy,
        "QSpinBox": QSpinBox,
        "QTabWidget": QTabWidget,
        "QTableWidget": QTableWidget,
        "QTableWidgetItem": QTableWidgetItem,
        "QToolButton": QToolButton,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }


def _configure_table_columns(table, minimum_widths: list[int]) -> None:
    qt = _require_qt()
    QHeaderView = qt["QHeaderView"]
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(80)
    for column_index in range(table.columnCount()):
        header.setSectionResizeMode(column_index, QHeaderView.ResizeToContents)
    table.resizeColumnsToContents()
    for column_index, minimum_width in enumerate(minimum_widths):
        if column_index >= table.columnCount():
            break
        if table.columnWidth(column_index) < minimum_width:
            table.setColumnWidth(column_index, minimum_width)
    if table.columnCount() > 0:
        header.setSectionResizeMode(table.columnCount() - 1, QHeaderView.Stretch)


def _configure_page_layout(layout, *, top_align: bool = False) -> None:
    qt = _require_qt()
    Qt = qt["Qt"]
    layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    layout.setSpacing(PAGE_SPACING)
    if top_align:
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)


def _configure_card_layout(layout) -> None:
    layout.setContentsMargins(
        CARD_HORIZONTAL_MARGIN,
        CARD_VERTICAL_MARGIN,
        CARD_HORIZONTAL_MARGIN,
        CARD_VERTICAL_MARGIN,
    )
    layout.setSpacing(SECTION_SPACING)


def _configure_inline_layout(layout, *, spacing: int = SECTION_SPACING) -> None:
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)


def _configure_form_layout(form) -> None:
    qt = _require_qt()
    Qt = qt["Qt"]
    QFormLayout = qt["QFormLayout"]

    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setFormAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    )
    form.setLabelAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    form.setHorizontalSpacing(FORM_HORIZONTAL_SPACING)
    form.setVerticalSpacing(FORM_VERTICAL_SPACING)


def _configure_form_field(widget, *, minimum_width: int = DEFAULT_FORM_FIELD_MIN_WIDTH) -> None:
    qt = _require_qt()
    QSizePolicy = qt["QSizePolicy"]
    widget.setMinimumWidth(minimum_width)
    widget.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Fixed,
    )


def _configure_constrained_panel(widget, *, max_width: int = FORM_PANEL_MAX_WIDTH) -> None:
    qt = _require_qt()
    QSizePolicy = qt["QSizePolicy"]
    widget.setMaximumWidth(16777215)
    widget.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Maximum,
    )


def _configure_data_table(widget, *, minimum_height: int) -> None:
    qt = _require_qt()
    QSizePolicy = qt["QSizePolicy"]
    widget.setMinimumHeight(minimum_height)
    widget.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Expanding,
    )
