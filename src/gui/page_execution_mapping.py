from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget as QtWidget

from src.models import TrackerItemResolutionMode
from src.upload_policy import DEFAULT_TRACKER_ITEM_ID_REGEX
from src.upload_policy import UPLOAD_MODE_CREATE as GUI_UPLOAD_MODE_CREATE
from src.upload_policy import UPLOAD_MODE_UPDATE as GUI_UPLOAD_MODE_UPDATE
from src.upload_policy import default_operation_scope
from src.upload_policy import normalize_all_or_none_operation_scope
from src.upload_policy import normalize_operation_scope
from src.upload_policy import normalize_upload_mode as normalize_gui_upload_mode

from .page_common import PRIMARY_TABLE_MIN_HEIGHT
from .page_common import SECONDARY_TABLE_MIN_HEIGHT
from .page_common import WIDE_FORM_PANEL_MAX_WIDTH
from .page_common import _build_tracker_item_regex_preview_text
from .page_common import _configure_constrained_panel
from .page_common import _configure_data_table
from .page_common import _configure_inline_layout
from .page_common import _configure_page_layout
from .page_common import _configure_table_columns
from .page_common import _require_qt
from .page_common import _tracker_item_sample_values


def _initialize_mapping_page(page, on_validate_requested, on_error=None):
    qt = _require_qt()
    Qt = qt["Qt"]
    QColor = qt["QColor"]
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QPushButton = qt["QPushButton"]
    QTableWidget = qt["QTableWidget"]
    QTableWidgetItem = qt["QTableWidgetItem"]
    QCheckBox = qt["QCheckBox"]
    QComboBox = qt["QComboBox"]
    QLineEdit = qt["QLineEdit"]
    QTabWidget = qt["QTabWidget"]

    layout = QVBoxLayout(page)
    _configure_page_layout(layout)
    info_label = QLabel("")
    info_label.setObjectName("section_label")
    _configure_constrained_panel(info_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(info_label)

    mapping_tabs = QTabWidget()
    mapping_tabs.setDocumentMode(True)

    mapping_tab = QWidget()
    mapping_tab_layout = QVBoxLayout(mapping_tab)
    _configure_inline_layout(mapping_tab_layout)
    table = QTableWidget(0, 7)
    table.setHorizontalHeaderLabels(["생성", "수정", "Excel 컬럼", "Codebeamer 필드", "타입", "다중값", "지원 여부"])
    table.setAlternatingRowColors(True)
    _configure_data_table(table, minimum_height=PRIMARY_TABLE_MIN_HEIGHT)
    _configure_table_columns(table, [70, 70, 220, 220, 170, 90, 90])
    page.mapping_table = table
    mapping_tab_layout.addWidget(table, 1)
    mapping_tabs.addTab(mapping_tab, "컬럼 매핑")

    defaults_tab = QWidget()
    defaults_tab_layout = QVBoxLayout(defaults_tab)
    _configure_inline_layout(defaults_tab_layout)
    default_label = QLabel("공통 기본값")
    default_label.setObjectName("section_label")
    defaults_tab_layout.addWidget(default_label)

    default_help_label = QLabel("행 값이 있으면 행 값이 우선하고, 비어 있으면 아래 기본값을 사용합니다.")
    default_help_label.setWordWrap(True)
    _configure_constrained_panel(default_help_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    defaults_tab_layout.addWidget(default_help_label)

    default_table = QTableWidget(0, 5)
    default_table.setHorizontalHeaderLabels(["적용", "Codebeamer 필드", "타입", "기본값", "필수"])
    default_table.setAlternatingRowColors(True)
    _configure_data_table(default_table, minimum_height=SECONDARY_TABLE_MIN_HEIGHT)
    _configure_table_columns(default_table, [70, 220, 170, 240, 90])
    page.default_table = default_table
    defaults_tab_layout.addWidget(default_table, 1)
    mapping_tabs.addTab(defaults_tab, "기본값")

    tracker_tab = QWidget()
    tracker_tab_layout = QVBoxLayout(tracker_tab)
    _configure_inline_layout(tracker_tab_layout)
    tracker_item_label = QLabel("Tracker Item 처리")
    tracker_item_label.setObjectName("section_label")
    tracker_tab_layout.addWidget(tracker_item_label)

    tracker_item_help_label = QLabel(
        "TrackerItemChoiceField 는 입력값에서 ID를 추출해 사용합니다. 이름이나 summary 조회는 현재 사용할 수 없습니다."
    )
    tracker_item_help_label.setWordWrap(True)
    _configure_constrained_panel(tracker_item_help_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    tracker_tab_layout.addWidget(tracker_item_help_label)

    tracker_item_table = QTableWidget(0, 5)
    tracker_item_table.setHorizontalHeaderLabels(
        ["Excel 컬럼", "Codebeamer 필드", "처리 방식", "ID 추출 정규식", "예시"]
    )
    tracker_item_table.setAlternatingRowColors(True)
    _configure_data_table(tracker_item_table, minimum_height=SECONDARY_TABLE_MIN_HEIGHT)
    _configure_table_columns(tracker_item_table, [220, 220, 180, 300, 360])
    page.tracker_item_table = tracker_item_table
    tracker_tab_layout.addWidget(tracker_item_table, 1)
    mapping_tabs.addTab(tracker_tab, "Tracker Item")

    page.mapping_tabs = mapping_tabs
    layout.addWidget(mapping_tabs, 1)

    status_label = QLabel("")
    status_label.setObjectName("status_label")
    _configure_constrained_panel(status_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(status_label)

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    previous_button = QPushButton("이전")
    validate_button = QPushButton("검증 실행")
    next_button = QPushButton("다음")
    validate_button.setObjectName("primary_button")
    next_button.setObjectName("primary_button")
    next_button.setEnabled(False)
    buttons.addWidget(previous_button)
    buttons.addWidget(validate_button)
    buttons.addStretch(1)
    buttons.addWidget(next_button)
    layout.addLayout(buttons)

    page._mapping_validated = False
    page._schema_rows_by_name = {}
    page._tracker_item_settings = {}
    page._upload_preview_df = None

    def _mark_dirty() -> None:
        """`mark_dirty` 상태를 표시한다."""
        page._mapping_validated = False
        next_button.setEnabled(False)

    def _tracker_item_candidates(mapping: dict[str, str]) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for df_column, schema_field in mapping.items():
            schema_row = page._schema_rows_by_name.get(schema_field, {})
            if str(schema_row.get("field_type") or "").strip() != "TrackerItemChoiceField":
                continue
            candidates.append({
                "df_column": df_column,
                "schema_field": schema_field,
            })
        return candidates

    def _tracker_item_example_text(df_column: str, schema_field: str, regex_pattern: str) -> str:
        schema_row = page._schema_rows_by_name.get(schema_field, {})
        sample_values = _tracker_item_sample_values(page._upload_preview_df, df_column)
        return _build_tracker_item_regex_preview_text(
            sample_values,
            pattern=regex_pattern,
            multiple_values=bool(schema_row.get("multiple_values", False)),
        )

    def _refresh_tracker_item_example(row_index: int, df_column: str, schema_field: str, regex_edit) -> None:
        """`refresh_tracker_item_example` 표시를 새로 고친다."""
        example_item = tracker_item_table.item(row_index, 4)
        if example_item is None:
            example_item = QTableWidgetItem("")
            tracker_item_table.setItem(row_index, 4, example_item)
        example_item.setText(
            _tracker_item_example_text(df_column, schema_field, regex_edit.text().strip())
        )

    def _populate_tracker_item_table(
        mapping: dict[str, str], tracker_item_settings: dict[str, dict[str, object]]
    ) -> None:
        page._tracker_item_settings = {
            str(schema_field): dict(setting)
            for schema_field, setting in (tracker_item_settings or {}).items()
            if str(schema_field).strip() and isinstance(setting, dict)
        }
        candidates = _tracker_item_candidates(mapping)
        tracker_item_table.setRowCount(len(candidates))

        for row_index, candidate in enumerate(candidates):
            df_column = str(candidate.get("df_column") or "")
            schema_field = str(candidate.get("schema_field") or "")
            selected_setting = page._tracker_item_settings.get(schema_field, {})
            selected_regex = str(selected_setting.get("regex_pattern") or DEFAULT_TRACKER_ITEM_ID_REGEX).strip()

            column_item = QTableWidgetItem(df_column)
            column_item.setData(Qt.ItemDataRole.UserRole, {"schema_field": schema_field})
            tracker_item_table.setItem(row_index, 0, column_item)
            tracker_item_table.setItem(row_index, 1, QTableWidgetItem(schema_field))

            tracker_item_table.setItem(row_index, 2, QTableWidgetItem("ID 추출 (고정)"))
            regex_edit = QLineEdit(selected_regex)
            tracker_item_table.setCellWidget(row_index, 3, regex_edit)
            tracker_item_table.setItem(row_index, 4, QTableWidgetItem(""))
            _refresh_tracker_item_example(row_index, df_column, schema_field, regex_edit)
            def _on_regex_changed(
                _text: str,
                row: int = row_index,
                column: str = df_column,
                field: str = schema_field,
                edit: Any = regex_edit,
            ) -> None:
                _refresh_tracker_item_example(row, column, field, edit)
                _mark_dirty()

            regex_edit.textChanged.connect(_on_regex_changed)

        _configure_table_columns(tracker_item_table, [220, 220, 180, 300, 360])
        if candidates:
            tracker_item_help_label.setText(
                "TrackerItemChoiceField 는 입력값에서 ID를 추출해 사용합니다. "
                "이름이나 summary 조회는 현재 사용할 수 없습니다."
            )
        else:
            tracker_item_help_label.setText("현재 매핑에는 별도 Tracker Item 처리 설정이 필요한 필드가 없습니다.")

    def _configure_default_value_widget(combo, candidate, selected_default: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.setEditable(False)
        combo.addItem("")

        options = list(getattr(candidate, "options", []) or [])
        for option_name in options:
            combo.addItem(str(option_name))

        if bool(getattr(candidate, "allows_custom_value", False)):
            combo.setEditable(True)
            if combo.lineEdit() is not None:
                combo.lineEdit().setPlaceholderText("직접 입력")
            combo.setCurrentText(selected_default)
        else:
            target_index = combo.findText(selected_default)
            combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        combo.blockSignals(False)

    def _bind_default_value_commit(combo) -> None:
        line_edit = combo.lineEdit()
        if line_edit is None:
            return
        if bool(line_edit.property("_codex_default_dirty_bound")):
            return
        line_edit.setProperty("_codex_default_dirty_bound", True)
        line_edit.editingFinished.connect(_mark_dirty)

    def _blend_colors(base_color, accent_color, ratio: float):
        """`blend_colors` 값을 섞어 계산한다."""
        clamped_ratio = max(0.0, min(float(ratio), 1.0))
        inverse_ratio = 1.0 - clamped_ratio
        return QColor(
            int(base_color.red() * inverse_ratio + accent_color.red() * clamped_ratio),
            int(base_color.green() * inverse_ratio + accent_color.green() * clamped_ratio),
            int(base_color.blue() * inverse_ratio + accent_color.blue() * clamped_ratio),
        )

    def _mapping_row_palette() -> dict[str, object]:
        palette = table.palette()
        base_color = palette.base().color()
        alternate_color = palette.alternateBase().color()
        highlight_color = palette.highlight().color()
        return {
            "row_background": _blend_colors(alternate_color, highlight_color, 0.18),
            "combo_background": _blend_colors(base_color, highlight_color, 0.20),
            "combo_border": _blend_colors(base_color, highlight_color, 0.48),
        }

    def _mapping_row_active(row_index: int) -> bool:
        create_widget = table.cellWidget(row_index, 0)
        update_widget = table.cellWidget(row_index, 1)
        combo = table.cellWidget(row_index, 3)
        if create_widget is None or update_widget is None or combo is None:
            return False
        if not (bool(create_widget.isChecked()) or bool(update_widget.isChecked())):
            return False
        return bool(combo.currentText().strip())

    def _apply_mapping_row_highlight(row_index: int) -> None:
        """`apply_mapping_row_highlight` 변경을 적용한다."""
        colors = _mapping_row_palette()
        is_active = _mapping_row_active(row_index)
        for column_index in (2, 4, 5, 6):
            item = table.item(row_index, column_index)
            if item is None:
                continue
            item.setData(
                Qt.ItemDataRole.BackgroundRole,
                colors["row_background"] if is_active else None,
            )
        column_item = table.item(row_index, 2)
        if column_item is not None:
            font = column_item.font()
            font.setBold(is_active)
            column_item.setFont(font)

        combo = table.cellWidget(row_index, 3)
        if combo is not None:
            if is_active:
                combo.setStyleSheet(
                    "QComboBox {"
                    f" background-color: {colors['combo_background'].name()};"
                    f" border: 1px solid {colors['combo_border'].name()};"
                    " font-weight: 600;"
                    "}"
                )
            else:
                combo.setStyleSheet("")

    def _refresh_mapping_row(row_index: int) -> None:
        """`refresh_mapping_row` 표시를 새로 고친다."""
        _apply_mapping_row_highlight(row_index)
        _populate_tracker_item_table(get_selected_mapping(), get_selected_tracker_item_settings())
        _mark_dirty()

    def _normalize_default_value_scope(raw_scope: dict[str, object] | None, *, upload_mode: str) -> dict[str, bool]:
        return normalize_all_or_none_operation_scope(raw_scope, upload_mode=upload_mode)

    def _sync_mapping_scope_checkboxes(create_widget, update_widget, *, upload_mode: str) -> None:
        """`sync_mapping_scope_checkboxes` 상태를 동기화한다."""
        normalized_mode = normalize_gui_upload_mode(upload_mode)
        if normalized_mode == GUI_UPLOAD_MODE_CREATE:
            create_widget.setEnabled(True)
            update_widget.setChecked(False)
            update_widget.setEnabled(False)
            return
        if normalized_mode == GUI_UPLOAD_MODE_UPDATE:
            create_widget.setChecked(False)
            create_widget.setEnabled(False)
            update_widget.setEnabled(True)
            return
        create_widget.setEnabled(True)
        update_widget.setEnabled(True)

    def load_context(
        upload_mode: str,
        upload_columns: list[str],
        schema_df,
        selected_mapping: dict[str, str],
        selected_mapping_modes: dict[str, dict[str, bool]],
        default_value_candidates: list,
        selected_default_values: dict[str, str],
        selected_default_value_modes: dict[str, dict[str, bool]],
        selected_tracker_item_settings: dict[str, dict[str, object]],
        upload_preview_df=None,
    ) -> None:
        """`load_context` 데이터를 불러온다."""
        page._mapping_validated = False
        next_button.setEnabled(False)
        page._upload_preview_df = upload_preview_df
        normalized_upload_mode = normalize_gui_upload_mode(upload_mode)
        page._mapping_upload_mode = normalized_upload_mode
        page._schema_rows_by_name = {
            str(row["field_name"]): row
            for _, row in schema_df.iterrows()
            if row.get("field_name")
        }
        schema_field_names = sorted(page._schema_rows_by_name.keys())
        table.setRowCount(len(upload_columns))
        for row_index, column_name in enumerate(upload_columns):
            create_widget = QCheckBox()
            update_widget = QCheckBox()
            is_selected = column_name in selected_mapping
            scope = (
                normalize_operation_scope(
                    (selected_mapping_modes or {}).get(column_name),
                    upload_mode=normalized_upload_mode,
                )
                if is_selected
                else {"create": False, "update": False}
            )
            create_widget.setChecked(bool(scope.get("create", False)))
            update_widget.setChecked(bool(scope.get("update", False)))
            _sync_mapping_scope_checkboxes(
                create_widget,
                update_widget,
                upload_mode=normalized_upload_mode,
            )
            table.setCellWidget(row_index, 0, create_widget)
            table.setCellWidget(row_index, 1, update_widget)
            table.setItem(row_index, 2, QTableWidgetItem(column_name))

            combo = QComboBox()
            combo.addItem("")
            combo.addItems(schema_field_names)
            if column_name in selected_mapping and combo.findText(selected_mapping[column_name]) >= 0:
                combo.setCurrentText(selected_mapping[column_name])
            table.setCellWidget(row_index, 3, combo)

            schema_field = selected_mapping.get(column_name)
            schema_row = page._schema_rows_by_name.get(schema_field, {})
            table.setItem(row_index, 4, QTableWidgetItem(str(schema_row.get("field_type") or "")))
            table.setItem(row_index, 5, QTableWidgetItem(str(bool(schema_row.get("multiple_values", False)))))
            table.setItem(row_index, 6, QTableWidgetItem("yes" if schema_row.get("is_supported", True) else "no"))

            def _on_combo_changed(_text, row=row_index):
                selected_name = table.cellWidget(row, 3).currentText().strip()
                schema = page._schema_rows_by_name.get(selected_name, {})
                table.setItem(row, 4, QTableWidgetItem(str(schema.get("field_type") or "")))
                table.setItem(row, 5, QTableWidgetItem(str(bool(schema.get("multiple_values", False)))))
                table.setItem(row, 6, QTableWidgetItem("yes" if schema.get("is_supported", True) else "no"))
                _refresh_mapping_row(row)

            combo.currentTextChanged.connect(_on_combo_changed)
            create_widget.toggled.connect(lambda _checked, row=row_index: _refresh_mapping_row(row))
            update_widget.toggled.connect(lambda _checked, row=row_index: _refresh_mapping_row(row))
            _apply_mapping_row_highlight(row_index)

        default_table.setRowCount(len(default_value_candidates))
        for row_index, candidate in enumerate(default_value_candidates):
            schema_field = str(getattr(candidate, "schema_field", ""))
            create_widget = QCheckBox()
            default_scope = _normalize_default_value_scope(
                (selected_default_value_modes or {}).get(schema_field),
                upload_mode=normalized_upload_mode,
            )
            create_widget.setChecked(bool(default_scope.get("create", False) or default_scope.get("update", False)))
            create_widget.setEnabled(True)
            default_table.setCellWidget(row_index, 0, create_widget)
            default_table.setItem(row_index, 1, QTableWidgetItem(schema_field))
            default_table.setItem(row_index, 2, QTableWidgetItem(str(getattr(candidate, "field_type", ""))))

            combo = QComboBox()
            selected_default = str(selected_default_values.get(schema_field, "") or "")
            _configure_default_value_widget(combo, candidate, selected_default)
            _bind_default_value_commit(combo)
            combo.currentTextChanged.connect(
                lambda _text, widget=combo: None if bool(widget.isEditable()) else _mark_dirty()
            )
            default_table.setCellWidget(row_index, 3, combo)

            default_table.setItem(
                row_index,
                4,
                QTableWidgetItem("yes" if bool(getattr(candidate, "mandatory", False)) else "no"),
            )
            create_widget.toggled.connect(lambda _checked: _mark_dirty())

        _configure_table_columns(table, [70, 70, 220, 220, 170, 90, 90])
        _configure_table_columns(default_table, [70, 220, 170, 240, 90])
        _populate_tracker_item_table(get_selected_mapping(), selected_tracker_item_settings)
        info_label.setText(
            f"매핑 대상 컬럼 {len(upload_columns)}개. id, parent 는 제외되며 "
            "생성/수정 체크를 모두 끄면 해당 컬럼은 무시됩니다."
        )
        if default_value_candidates:
            default_help_label.setText(
                "행 값이 있으면 행 값이 우선하고, 비어 있으면 아래 기본값을 현재 처리 모드에 맞게 적용합니다."
            )
        else:
            default_help_label.setText("선택 가능한 공통 기본값 필드가 없습니다.")
        status_label.setText("")

    def get_selected_mapping() -> dict[str, str]:
        """`get_selected_mapping` 값을 반환한다."""
        mapping: dict[str, str] = {}
        for row_index in range(table.rowCount()):
            create_widget = table.cellWidget(row_index, 0)
            update_widget = table.cellWidget(row_index, 1)
            combo = table.cellWidget(row_index, 3)
            if create_widget is None or update_widget is None or combo is None:
                continue
            if not (bool(create_widget.isChecked()) or bool(update_widget.isChecked())):
                continue
            schema_field = combo.currentText().strip()
            if not schema_field:
                continue
            column_name_item = table.item(row_index, 2)
            if column_name_item is None:
                continue
            mapping[column_name_item.text()] = schema_field
        return mapping

    def get_selected_mapping_modes() -> dict[str, dict[str, bool]]:
        """`get_selected_mapping_modes` 값을 반환한다."""
        mapping_modes: dict[str, dict[str, bool]] = {}
        for row_index in range(table.rowCount()):
            create_widget = table.cellWidget(row_index, 0)
            update_widget = table.cellWidget(row_index, 1)
            column_name_item = table.item(row_index, 2)
            combo = table.cellWidget(row_index, 3)
            if (
                create_widget is None
                or update_widget is None
                or column_name_item is None
                or combo is None
            ):
                continue
            if not combo.currentText().strip():
                continue
            if not (bool(create_widget.isChecked()) or bool(update_widget.isChecked())):
                continue
            mapping_modes[column_name_item.text()] = {
                "create": bool(create_widget.isChecked()),
                "update": bool(update_widget.isChecked()),
            }
        return mapping_modes

    def get_selected_default_values() -> dict[str, str]:
        """`get_selected_default_values` 값을 반환한다."""
        default_values: dict[str, str] = {}
        for row_index in range(default_table.rowCount()):
            field_item = default_table.item(row_index, 1)
            combo = default_table.cellWidget(row_index, 3)
            if field_item is None or combo is None:
                continue
            selected_value = combo.currentText().strip()
            if not selected_value:
                continue
            default_values[field_item.text()] = selected_value
        return default_values

    def get_selected_default_value_modes() -> dict[str, dict[str, bool]]:
        """`get_selected_default_value_modes` 값을 반환한다."""
        default_value_modes: dict[str, dict[str, bool]] = {}
        for row_index in range(default_table.rowCount()):
            field_item = default_table.item(row_index, 1)
            create_widget = default_table.cellWidget(row_index, 0)
            combo = default_table.cellWidget(row_index, 3)
            if field_item is None or create_widget is None or combo is None:
                continue
            if not combo.currentText().strip():
                continue
            if not bool(create_widget.isChecked()):
                default_value_modes[field_item.text()] = {"create": False, "update": False}
                continue
            upload_mode_scope = default_operation_scope(
                getattr(page, "_mapping_upload_mode", GUI_UPLOAD_MODE_CREATE)
            )
            default_value_modes[field_item.text()] = {
                "create": bool(upload_mode_scope.get("create", False)),
                "update": bool(upload_mode_scope.get("update", False)),
            }
        return default_value_modes

    def get_selected_tracker_item_settings() -> dict[str, dict[str, object]]:
        """`get_selected_tracker_item_settings` 값을 반환한다."""
        settings: dict[str, dict[str, object]] = {}
        for row_index in range(tracker_item_table.rowCount()):
            source_item = tracker_item_table.item(row_index, 0)
            regex_edit = tracker_item_table.cellWidget(row_index, 3)
            if source_item is None or regex_edit is None:
                continue
            metadata = source_item.data(Qt.ItemDataRole.UserRole) or {}
            schema_field = str(metadata.get("schema_field") or "").strip()
            if not schema_field:
                continue
            settings[schema_field] = {
                "mode": TrackerItemResolutionMode.REGEX.value,
                "regex_pattern": regex_edit.text().strip(),
            }
        return settings

    def _validate() -> None:
        mapping = get_selected_mapping()
        if not mapping:
            status_label.setText("최소 1개 이상의 컬럼을 매핑해야 합니다.")
            return
        mapping_modes = get_selected_mapping_modes()
        selected_default_values = get_selected_default_values()
        selected_default_value_modes = get_selected_default_value_modes()
        try:
            on_validate_requested(
                mapping,
                mapping_modes,
                selected_default_values,
                selected_default_value_modes,
                get_selected_tracker_item_settings(),
            )
        except Exception as exc:
            message = f"검증 실패: {exc}"
            status_label.setText(message)
            if callable(on_error):
                on_error("검증 실패", message)
            page._mapping_validated = False
            next_button.setEnabled(False)
            return
        status_label.setText("검증이 완료되었습니다.")
        page._mapping_validated = True
        next_button.setEnabled(True)

    previous_button.clicked.connect(lambda: page.request_previous())
    validate_button.clicked.connect(_validate)
    next_button.clicked.connect(lambda: page.request_next())

    page.load_context = load_context
    page.get_selected_mapping = get_selected_mapping
    page.get_selected_mapping_modes = get_selected_mapping_modes
    page.get_selected_default_values = get_selected_default_values
    page.get_selected_default_value_modes = get_selected_default_value_modes
    page.get_selected_tracker_item_settings = get_selected_tracker_item_settings
    return page


class MappingPage(QtWidget):
    """Excel 컬럼과 Codebeamer 필드 매핑 상태를 소유하는 페이지."""

    def __init__(self, on_validate_requested, on_error=None) -> None:
        super().__init__()
        _initialize_mapping_page(self, on_validate_requested, on_error)


def create_mapping_page(on_validate_requested, on_error=None):
    """기존 factory 호출 계약으로 `MappingPage`를 생성한다."""
    return MappingPage(on_validate_requested, on_error)
