from __future__ import annotations

from copy import deepcopy
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QCheckBox
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QDialogButtonBox
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtWidgets import QListWidget
    from PySide6.QtWidgets import QPlainTextEdit
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtWidgets import QTextBrowser
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_item_editor import EditableTrackerField
from .tracker_item_editor import FieldEditorKind
from .tracker_item_editor import TrackerItemFieldChange
from .tracker_item_editor import build_field_value
from .tracker_item_editor_panel import create_tracker_field_input_widget
from .tracker_item_editor_panel import tracker_field_input_value
from .wiki_renderer import codebeamer_wiki_to_html
from .wiki_renderer import is_explicit_wiki_type


_PREFERRED_COLUMN_WIDTH = 220
_MAXIMUM_AUTOFIT_COLUMN_WIDTH = 480
_MAXIMUM_AUTOFIT_ROW_HEIGHT = 140


def _normalized_rows(value: Any) -> list[list[dict[str, Any]]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("TableField 값이 행 목록 형식이 아닙니다.")
    rows: list[list[dict[str, Any]]] = []
    for row_index, raw_row in enumerate(value, start=1):
        if isinstance(raw_row, dict):
            raw_row = (
                raw_row.get("values")
                if "values" in raw_row
                else raw_row.get("fieldValues")
            )
        if not isinstance(raw_row, list):
            raise ValueError(f"TableField {row_index}행 구조를 해석할 수 없습니다.")
        if not all(isinstance(cell, dict) for cell in raw_row):
            raise ValueError(f"TableField {row_index}행 셀 구조를 해석할 수 없습니다.")
        rows.append(deepcopy(raw_row))
    return rows


def _cell_field_id(cell: dict[str, Any]) -> int | None:
    raw_id = cell.get("fieldId")
    if raw_id is None:
        raw_id = cell.get("id")
    if raw_id is None or isinstance(raw_id, bool):
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _cell_for_column(
    row: list[dict[str, Any]],
    column: EditableTrackerField,
) -> dict[str, Any] | None:
    return next(
        (cell for cell in row if _cell_field_id(cell) == column.field_id),
        None,
    )


def _cell_value(cell: dict[str, Any] | None) -> Any:
    if not isinstance(cell, dict):
        return None
    if "values" in cell:
        return deepcopy(cell.get("values"))
    return deepcopy(cell.get("value"))


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, dict):
        for key in ("name", "value", "id"):
            if value.get(key) not in (None, ""):
                return _display_value(value.get(key))
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(
            text for text in (_display_value(item) for item in value) if text
        )
    return str(value)


def _is_referred_row(row: list[dict[str, Any]]) -> bool:
    return any(
        "referredteststep" in str(cell.get("type") or "").casefold()
        for cell in row
    )


def _is_wiki_column(column: EditableTrackerField) -> bool:
    return is_explicit_wiki_type(column.type_name) or is_explicit_wiki_type(
        column.value_model
    )


class TrackerTableFieldEditorDialog(QDialog):
    """TableField 행 구조와 숨김 셀을 보존하며 편집한다."""

    def __init__(self, field: EditableTrackerField, parent=None) -> None:
        super().__init__(parent)
        if field.editor_kind != FieldEditorKind.TABLE:
            raise ValueError("TableField 편집 필드가 아닙니다.")
        self.field = field
        self.columns = tuple(field.table_columns)
        self.original_rows = _normalized_rows(field.current_value)
        self.rows = deepcopy(self.original_rows)
        self.cell_widgets: dict[tuple[int, int], QWidget] = {}

        self.setObjectName("tracker_table_field_editor_dialog")
        self.setWindowTitle(f"{field.label} · TableField 수정")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setMinimumSize(820, 540)
        self.resize(1100, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(9)

        header = QHBoxLayout()
        self.title_label = QLabel("", self)
        self.title_label.setObjectName("tracker_detail_title")
        header.addWidget(self.title_label, 1)
        self.fit_columns_button = QPushButton("열 너비 맞춤", self)
        self.fit_columns_button.clicked.connect(self._fit_columns_to_contents)
        header.addWidget(self.fit_columns_button)
        self.fit_rows_button = QPushButton("행 높이 맞춤", self)
        self.fit_rows_button.clicked.connect(self._fit_rows_to_contents)
        header.addWidget(self.fit_rows_button)
        self.fullscreen_button = QPushButton("전체 화면", self)
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.toggled.connect(self._set_fullscreen)
        header.addWidget(self.fullscreen_button)
        layout.addLayout(header)

        helper = QLabel(
            "편집 가능한 열만 변경됩니다. 숨김 ID와 지원하지 않는 셀은 "
            "원본 payload에 그대로 보존됩니다."
        )
        helper.setObjectName("tracker_panel_status")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        row_actions = QHBoxLayout()
        self.add_row_button = QPushButton("행 추가", self)
        self.add_row_button.clicked.connect(self._add_row)
        row_actions.addWidget(self.add_row_button)
        self.duplicate_row_button = QPushButton("행 복제", self)
        self.duplicate_row_button.clicked.connect(self._duplicate_row)
        row_actions.addWidget(self.duplicate_row_button)
        self.delete_row_button = QPushButton("행 삭제", self)
        self.delete_row_button.setObjectName("danger_button")
        self.delete_row_button.clicked.connect(self._delete_row)
        row_actions.addWidget(self.delete_row_button)
        self.move_up_button = QPushButton("위로", self)
        self.move_up_button.clicked.connect(lambda: self._move_row(-1))
        row_actions.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("아래로", self)
        self.move_down_button.clicked.connect(lambda: self._move_row(1))
        row_actions.addWidget(self.move_down_button)
        row_actions.addStretch(1)
        self.row_status_label = QLabel("", self)
        self.row_status_label.setObjectName("tracker_panel_status")
        row_actions.addWidget(self.row_status_label)
        layout.addLayout(row_actions)

        self.table = QTableWidget(self)
        self.table.setObjectName("tracker_table_field_editor")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setMinimumSectionSize(80)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setMinimumSectionSize(28)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        self.preview_title = QLabel("Wiki 미리보기", self)
        self.preview_title.setObjectName("tracker_detail_section_title")
        self.preview_title.hide()
        layout.addWidget(self.preview_title)
        self.wiki_preview = QTextBrowser(self)
        self.wiki_preview.setObjectName("tracker_table_wiki_preview")
        self.wiki_preview.setMaximumHeight(130)
        self.wiki_preview.hide()
        layout.addWidget(self.wiki_preview)

        self.clear_confirmation = QCheckBox(
            "기존 행 전체 삭제를 확인합니다.",
            self,
        )
        self.clear_confirmation.toggled.connect(self._update_action_state)
        self.clear_confirmation.hide()
        layout.addWidget(self.clear_confirmation)

        self.validation_label = QLabel("", self)
        self.validation_label.setObjectName("tracker_editor_status")
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        layout.addWidget(self.validation_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.apply_button.setText("편집 내용 적용")
        self.apply_button.setObjectName("primary_button")
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("취소")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_table()
        self._fit_columns_to_contents()
        self._fit_rows_to_contents()
        self._update_action_state()

    def value(self) -> list[list[dict[str, Any]]]:
        if not self._sync_rows_from_widgets():
            raise ValueError(
                self.validation_label.text() or "TableField 값을 확인하세요."
            )
        return deepcopy(self.rows)

    def _show_validation(self, message: str) -> None:
        self.validation_label.setText(str(message or "TableField 값을 확인하세요."))
        self.validation_label.setProperty("tone", "error")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)
        self.validation_label.show()

    def _clear_validation(self) -> None:
        self.validation_label.clear()
        self.validation_label.hide()

    def _populate_table(
        self,
        selected_row: int | None = None,
        *,
        initialize_missing_row: int | None = None,
    ) -> None:
        previous_heights = [
            self.table.rowHeight(index) for index in range(self.table.rowCount())
        ]
        self.cell_widgets.clear()
        self.table.clear()
        self.table.setRowCount(len(self.rows))
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([column.label for column in self.columns])
        self.table.setVerticalHeaderLabels(
            [
                f"{index + 1} 🔒" if _is_referred_row(row) else str(index + 1)
                for index, row in enumerate(self.rows)
            ]
        )
        for row_index, row in enumerate(self.rows):
            locked = _is_referred_row(row)
            for column_index, column in enumerate(self.columns):
                cell = _cell_for_column(row, column)
                current_value = _cell_value(cell)
                if locked or not column.editable:
                    item = QTableWidgetItem(_display_value(current_value))
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    item.setToolTip(
                        "참조 행은 읽기 전용입니다."
                        if locked
                        else column.unsupported_reason
                    )
                    self.table.setItem(row_index, column_index, item)
                    continue
                widget = create_tracker_field_input_widget(
                    column,
                    self.table,
                    initial_value=current_value,
                )
                if widget is None:
                    item = QTableWidgetItem(column.unsupported_reason or "읽기 전용")
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.table.setItem(row_index, column_index, item)
                    continue
                self.table.setCellWidget(row_index, column_index, widget)
                self.cell_widgets[(row_index, column.field_id)] = widget
                widget.setProperty(
                    "tracker_cell_dirty",
                    cell is None and row_index == initialize_missing_row,
                )
                self._connect_widget_dirty_signal(widget)
                if _is_wiki_column(column) and isinstance(widget, (QPlainTextEdit, QLineEdit)):
                    widget.textChanged.connect(self._refresh_wiki_preview)
        for row_index, height in enumerate(previous_heights[: len(self.rows)]):
            self.table.setRowHeight(row_index, height)
        if self.rows:
            target = (
                0
                if selected_row is None
                else max(0, min(selected_row, len(self.rows) - 1))
            )
            self.table.selectRow(target)
        self._refresh_summary()
        self._update_clear_confirmation()
        self._update_action_state()

    @staticmethod
    def _mark_widget_dirty(widget: QWidget) -> None:
        widget.setProperty("tracker_cell_dirty", True)

    def _connect_widget_dirty_signal(self, widget: QWidget) -> None:
        def mark_dirty(*args) -> None:
            del args
            self._mark_widget_dirty(widget)

        if isinstance(widget, (QLineEdit, QPlainTextEdit)):
            widget.textChanged.connect(mark_dirty)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(mark_dirty)
        elif isinstance(widget, QListWidget):
            widget.itemChanged.connect(mark_dirty)

    def _sync_rows_from_widgets(self) -> bool:
        try:
            for row_index, row in enumerate(self.rows):
                if _is_referred_row(row):
                    continue
                for column in self.columns:
                    widget = self.cell_widgets.get((row_index, column.field_id))
                    if widget is None or not column.editable:
                        continue
                    if not bool(widget.property("tracker_cell_dirty")):
                        continue
                    raw_value = tracker_field_input_value(column, widget)
                    cell_payload = build_field_value(
                        TrackerItemFieldChange(field=column, value=raw_value)
                    )
                    existing = _cell_for_column(row, column)
                    if existing is None:
                        row.append(cell_payload)
                    else:
                        if "value" in cell_payload:
                            existing.pop("values", None)
                        if "values" in cell_payload:
                            existing.pop("value", None)
                        existing.update(cell_payload)
                    widget.setProperty("tracker_cell_dirty", False)
        except (TypeError, ValueError) as exc:
            self._show_validation(str(exc) or "TableField 셀 값을 확인하세요.")
            return False
        self._clear_validation()
        return True

    def _selected_row(self) -> int:
        return self.table.currentRow()

    def _add_row(self) -> None:
        if not self._sync_rows_from_widgets():
            return
        self.rows.append([])
        new_row_index = len(self.rows) - 1
        self._populate_table(
            new_row_index,
            initialize_missing_row=new_row_index,
        )

    def _duplicate_row(self) -> None:
        row_index = self._selected_row()
        if row_index < 0 or not self._sync_rows_from_widgets():
            return
        source = self.rows[row_index]
        if _is_referred_row(source):
            self._show_validation("참조된 행은 복제할 수 없습니다.")
            return
        duplicated = [
            deepcopy(cell)
            for column in self.columns
            if column.editable
            for cell in [_cell_for_column(source, column)]
            if cell is not None
        ]
        self.rows.insert(row_index + 1, duplicated)
        self._populate_table(row_index + 1)

    def _delete_row(self) -> None:
        row_index = self._selected_row()
        if row_index < 0 or not self._sync_rows_from_widgets():
            return
        if _is_referred_row(self.rows[row_index]):
            self._show_validation("참조된 행은 삭제할 수 없습니다.")
            return
        self.rows.pop(row_index)
        self._populate_table(min(row_index, len(self.rows) - 1))

    def _move_row(self, offset: int) -> None:
        row_index = self._selected_row()
        target_index = row_index + int(offset)
        if (
            row_index < 0
            or target_index < 0
            or target_index >= len(self.rows)
            or not self._sync_rows_from_widgets()
        ):
            return
        if _is_referred_row(self.rows[row_index]) or _is_referred_row(
            self.rows[target_index]
        ):
            self._show_validation("참조된 행의 순서는 변경할 수 없습니다.")
            return
        self.rows[row_index], self.rows[target_index] = (
            self.rows[target_index],
            self.rows[row_index],
        )
        self._populate_table(target_index)

    def _on_selection_changed(self) -> None:
        self._update_action_state()
        self._refresh_wiki_preview()

    def _refresh_wiki_preview(self, *args) -> None:
        del args
        row_index = self.table.currentRow()
        column_index = self.table.currentColumn()
        if (
            row_index < 0
            or row_index >= len(self.rows)
            or column_index < 0
            or column_index >= len(self.columns)
        ):
            self.preview_title.hide()
            self.wiki_preview.hide()
            return
        column = self.columns[column_index]
        if not _is_wiki_column(column):
            self.preview_title.hide()
            self.wiki_preview.hide()
            return
        widget = self.cell_widgets.get((row_index, column.field_id))
        if widget is not None:
            value = tracker_field_input_value(column, widget)
        else:
            value = _cell_value(_cell_for_column(self.rows[row_index], column))
        self.wiki_preview.setHtml(codebeamer_wiki_to_html(value))
        self.preview_title.show()
        self.wiki_preview.show()

    def _refresh_summary(self) -> None:
        self.title_label.setText(
            f"{self.field.label} · {len(self.rows)}행 × {len(self.columns)}열"
        )
        locked_count = sum(1 for row in self.rows if _is_referred_row(row))
        status = f"전체 {len(self.rows)}행"
        if locked_count:
            status += f" · 참조 잠금 {locked_count}행"
        self.row_status_label.setText(status)

    def _update_clear_confirmation(self) -> None:
        requires_confirmation = bool(self.original_rows) and not self.rows
        self.clear_confirmation.setVisible(requires_confirmation)
        if not requires_confirmation:
            self.clear_confirmation.setChecked(False)

    def _update_action_state(self, *args) -> None:
        del args
        row_index = self._selected_row()
        has_row = 0 <= row_index < len(self.rows)
        locked = has_row and _is_referred_row(self.rows[row_index])
        self.duplicate_row_button.setEnabled(has_row and not locked)
        self.delete_row_button.setEnabled(has_row and not locked)
        self.move_up_button.setEnabled(
            has_row
            and not locked
            and row_index > 0
            and not _is_referred_row(self.rows[row_index - 1])
        )
        self.move_down_button.setEnabled(
            has_row
            and not locked
            and row_index < len(self.rows) - 1
            and not _is_referred_row(self.rows[row_index + 1])
        )
        requires_confirmation = bool(self.original_rows) and not self.rows
        self.apply_button.setEnabled(
            not requires_confirmation or self.clear_confirmation.isChecked()
        )

    def _fit_columns_to_contents(self, _checked: bool = False) -> None:
        column_count = self.table.columnCount()
        if column_count <= 0:
            return
        self.table.resizeColumnsToContents()
        available_width = max(0, self.width() - 64)
        visible_column_count = min(column_count, 3)
        preferred_width = max(
            _PREFERRED_COLUMN_WIDTH,
            available_width // visible_column_count,
        )
        preferred_width = min(_MAXIMUM_AUTOFIT_COLUMN_WIDTH, preferred_width)
        for column_index in range(column_count):
            self.table.setColumnWidth(
                column_index,
                min(
                    _MAXIMUM_AUTOFIT_COLUMN_WIDTH,
                    max(preferred_width, self.table.columnWidth(column_index) + 16),
                ),
            )

    def _fit_rows_to_contents(self, _checked: bool = False) -> None:
        self.table.resizeRowsToContents()
        for row_index in range(self.table.rowCount()):
            self.table.setRowHeight(
                row_index,
                min(
                    _MAXIMUM_AUTOFIT_ROW_HEIGHT,
                    max(44, self.table.rowHeight(row_index)),
                ),
            )

    def _set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_button.setText("창 모드" if enabled else "전체 화면")
        if enabled:
            self.showFullScreen()
            return
        self.showNormal()

    def _validate_and_accept(self) -> None:
        if not self._sync_rows_from_widgets():
            return
        if (
            self.original_rows
            and not self.rows
            and not self.clear_confirmation.isChecked()
        ):
            self._show_validation("기존 행 전체 삭제를 확인하세요.")
            return
        try:
            build_field_value(TrackerItemFieldChange(self.field, self.rows))
        except (TypeError, ValueError) as exc:
            self._show_validation(str(exc) or "TableField 값을 확인하세요.")
            return
        self.accept()


__all__ = ["TrackerTableFieldEditorDialog"]
