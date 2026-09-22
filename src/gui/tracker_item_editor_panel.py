from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import replace
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDoubleValidator
    from PySide6.QtGui import QIntValidator
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtWidgets import QListWidget
    from PySide6.QtWidgets import QListWidgetItem
    from PySide6.QtWidgets import QPlainTextEdit
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    # 런타임에는 순환 import 를 피하려고 메서드 안에서 지연 import 한다.
    from .tracker_table_field_editor_dialog import TrackerTableFieldEditorDialog

from .tracker_item_editor import EditableTrackerField
from .tracker_item_editor import EditableTrackerSchema
from .tracker_item_editor import FieldEditorKind
from .tracker_item_editor import TrackerItemFieldChange
from .tracker_query_models import TrackerItemDetail


_FIELD_CURRENT_VALUE = object()


class TrackerTableFieldInput(QWidget):
    """TableField 중첩값을 전용 행 편집기로 여는 입력 widget."""

    def __init__(
        self,
        field_value: EditableTrackerField,
        parent: QWidget,
        *,
        initial_value: Any = _FIELD_CURRENT_VALUE,
    ) -> None:
        super().__init__(parent)
        self.field_value = field_value
        current = (
            field_value.current_value
            if initial_value is _FIELD_CURRENT_VALUE
            else initial_value
        )
        self._value = deepcopy(current) if isinstance(current, list) else []
        self._dialog: TrackerTableFieldEditorDialog | None = None

        self.setObjectName("tracker_table_field_input")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.summary_label = QLabel("", self)
        self.summary_label.setObjectName("tracker_panel_status")
        layout.addWidget(self.summary_label, 1)
        self.edit_button = QPushButton("테이블 수정", self)
        self.edit_button.clicked.connect(self.open_editor)
        layout.addWidget(self.edit_button)
        self._refresh_summary()

    def value(self) -> list[list[dict[str, Any]]]:
        return deepcopy(self._value)

    def open_editor(self) -> None:
        from .tracker_table_field_editor_dialog import TrackerTableFieldEditorDialog

        dialog_field = replace(
            self.field_value,
            current_value=deepcopy(self._value),
        )
        try:
            dialog = TrackerTableFieldEditorDialog(dialog_field, self)
        except (TypeError, ValueError) as exc:
            message = str(exc) or "TableField 행 구조를 해석할 수 없습니다."
            self.summary_label.setText("편집 불가 · 데이터 형식 확인 필요")
            self.summary_label.setToolTip(message)
            self.edit_button.setToolTip(message)
            return
        self._dialog = dialog
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._value = dialog.value()
                self._refresh_summary()
        finally:
            self._dialog = None

    def _refresh_summary(self) -> None:
        self.summary_label.setText(
            f"{len(self._value)}행 × {len(self.field_value.table_columns)}열"
        )


def tracker_field_boolean_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"true", "1", "yes", "예"}


def tracker_field_reference_ids(value: Any) -> tuple[int, ...]:
    values = value if isinstance(value, (list, tuple)) else (value,)
    normalized: list[int] = []
    for raw_value in values:
        if isinstance(raw_value, dict):
            raw_value = raw_value.get("id")
        try:
            item_id = int(raw_value)
        except (TypeError, ValueError):
            continue
        if item_id not in normalized:
            normalized.append(item_id)
    return tuple(normalized)


def tracker_field_single_reference_id(value: Any) -> int | None:
    values = tracker_field_reference_ids(value)
    return values[0] if values else None


def create_tracker_field_input_widget(
    field_value: EditableTrackerField,
    parent: QWidget,
    *,
    initial_value: Any = _FIELD_CURRENT_VALUE,
) -> QWidget | None:
    """수정·생성 화면이 공유하는 schema 유형별 입력 widget을 만든다."""
    kind = field_value.editor_kind
    current = (
        field_value.current_value
        if initial_value is _FIELD_CURRENT_VALUE
        else initial_value
    )
    if not field_value.editable:
        return None
    if kind == FieldEditorKind.TABLE:
        return TrackerTableFieldInput(
            field_value,
            parent,
            initial_value=initial_value,
        )
    if kind == FieldEditorKind.MULTILINE_TEXT:
        text_edit = QPlainTextEdit(parent)
        text_edit.setPlainText(str(current or ""))
        return text_edit
    if kind in {
        FieldEditorKind.TEXT,
        FieldEditorKind.INTEGER,
        FieldEditorKind.DECIMAL,
        FieldEditorKind.DATE,
        FieldEditorKind.DATETIME,
    }:
        line_edit = QLineEdit(parent)
        line_edit.setText("" if current is None else str(current))
        if kind == FieldEditorKind.INTEGER:
            line_edit.setValidator(QIntValidator(line_edit))
        elif kind == FieldEditorKind.DECIMAL:
            line_edit.setValidator(QDoubleValidator(line_edit))
        elif kind == FieldEditorKind.DATE:
            line_edit.setPlaceholderText("YYYY-MM-DD")
        elif kind == FieldEditorKind.DATETIME:
            line_edit.setPlaceholderText("YYYY-MM-DDThh:mm:ss")
        return line_edit
    if kind == FieldEditorKind.BOOLEAN:
        boolean_combo = QComboBox(parent)
        boolean_combo.addItem("예", True)
        boolean_combo.addItem("아니요", False)
        boolean_combo.setCurrentIndex(0 if tracker_field_boolean_value(current) else 1)
        return boolean_combo
    if kind == FieldEditorKind.CHOICE:
        current_ids = set(tracker_field_reference_ids(current))
        if field_value.multiple_values:
            choice_list = QListWidget(parent)
            for option in field_value.options:
                item = QListWidgetItem(option.name)
                item.setData(Qt.ItemDataRole.UserRole, option.option_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if option.option_id in current_ids
                    else Qt.CheckState.Unchecked
                )
                choice_list.addItem(item)
            return choice_list
        choice_combo = QComboBox(parent)
        choice_combo.addItem("(값 비우기)", None)
        for option in field_value.options:
            choice_combo.addItem(option.name, option.option_id)
        current_id = next(iter(current_ids), None)
        index = choice_combo.findData(current_id)
        choice_combo.setCurrentIndex(index if index >= 0 else 0)
        return choice_combo
    if kind == FieldEditorKind.REFERENCE:
        reference_ids = tracker_field_reference_ids(current)
        input_text = "\n".join(str(value) for value in reference_ids)
        if field_value.multiple_values:
            reference_edit = QPlainTextEdit(parent)
            reference_edit.setPlaceholderText("한 줄에 참조 ID 하나")
            reference_edit.setPlainText(input_text)
            return reference_edit
        reference_input = QLineEdit(parent)
        reference_input.setPlaceholderText("참조 ID")
        reference_input.setText(input_text)
        reference_input.setValidator(QIntValidator(1, 2_147_483_647, reference_input))
        return reference_input
    return None


def tracker_field_input_value(
    field_value: EditableTrackerField,
    widget: QWidget,
) -> Any:
    if isinstance(widget, TrackerTableFieldInput):
        return widget.value()
    if isinstance(widget, QPlainTextEdit):
        return widget.toPlainText()
    if isinstance(widget, QLineEdit):
        return widget.text()
    if isinstance(widget, QComboBox):
        return widget.currentData()
    if isinstance(widget, QListWidget):
        return tuple(
            widget.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(widget.count())
            if widget.item(index).checkState() == Qt.CheckState.Checked
        )
    raise TypeError(f"지원하지 않는 편집 widget입니다: {field_value.label}")


@dataclass
class _EditorRow:
    row: int
    field: EditableTrackerField
    widget: QWidget | None


class TrackerItemEditorPanel(QWidget):
    """Schema field별 입력 widget과 명시적 쓰기 동작을 제공한다."""

    def __init__(
        self,
        *,
        save_requested: Callable[[tuple[TrackerItemFieldChange, ...]], None],
        transition_requested: Callable[[EditableTrackerField, int], None],
        delete_requested: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tracker_item_editor_panel")
        self.save_requested = save_requested
        self.transition_requested = transition_requested
        self.delete_requested = delete_requested
        self.detail: TrackerItemDetail | None = None
        self.schema: EditableTrackerSchema | None = None
        self.write_enabled = False
        self.rows: dict[int, _EditorRow] = {}
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(7)

        self.editor_status = QLabel("수정 탭을 열면 tracker schema를 불러옵니다.")
        self.editor_status.setObjectName("tracker_editor_status")
        self.editor_status.setWordWrap(True)
        layout.addWidget(self.editor_status)

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_title = QLabel("상태 필드 변경")
        status_title.setObjectName("tracker_detail_section_title")
        status_row.addWidget(status_title)
        self.current_status_label = QLabel("-")
        self.current_status_label.setObjectName("tracker_current_status")
        status_row.addWidget(self.current_status_label)
        status_row.addStretch(1)
        self.status_combo = QComboBox(self)
        self.status_combo.setObjectName("tracker_status_transition_combo")
        self.status_combo.setMinimumWidth(145)
        self.status_combo.currentIndexChanged.connect(self._update_action_state)
        status_row.addWidget(self.status_combo)
        self.transition_button = QPushButton("상태 필드 변경", self)
        self.transition_button.setObjectName("primary_button")
        self.transition_button.clicked.connect(self._request_transition)
        status_row.addWidget(self.transition_button)
        layout.addLayout(status_row)

        self.editor_helper = QLabel(
            "수정할 필드만 체크하세요. 현재 값과 새 값을 같은 표에서 확인한 뒤 한 번에 저장합니다."
        )
        self.editor_helper.setObjectName("tracker_panel_status")
        self.editor_helper.setWordWrap(True)
        layout.addWidget(self.editor_helper)

        self.field_table = QTableWidget(0, 4, self)
        self.field_table.setObjectName("tracker_editor_fields")
        self.field_table.setHorizontalHeaderLabels(
            ["수정", "필드", "현재 값", "새 값"]
        )
        self.field_table.setAlternatingRowColors(True)
        self.field_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.field_table.verticalHeader().setVisible(False)
        self.field_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.field_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.field_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.field_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.field_table.itemChanged.connect(self._on_item_changed)
        self.field_table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self.field_table, 1)

        action_row = QHBoxLayout()
        self.delete_button = QPushButton("아이템 삭제", self)
        self.delete_button.setObjectName("danger_button")
        self.delete_button.clicked.connect(self.delete_requested)
        action_row.addWidget(self.delete_button)
        action_row.addStretch(1)
        self.reset_button = QPushButton("변경 취소", self)
        self.reset_button.clicked.connect(self.reset_values)
        action_row.addWidget(self.reset_button)
        self.save_button = QPushButton("선택한 필드 저장", self)
        self.save_button.setObjectName("primary_button")
        self.save_button.clicked.connect(self._request_save)
        action_row.addWidget(self.save_button)
        layout.addLayout(action_row)
        self.clear()

    def clear(self) -> None:
        self.detail = None
        self.schema = None
        self.write_enabled = False
        self.rows.clear()
        self.field_table.blockSignals(True)
        self.field_table.setRowCount(0)
        self.field_table.blockSignals(False)
        self.status_combo.clear()
        self.current_status_label.setText("-")
        self.editor_status.setText("아이템을 선택한 뒤 수정 탭을 여세요.")
        self._update_action_state()

    def set_loading(self, message: str) -> None:
        self.editor_status.setText(message)
        self.editor_status.setProperty("tone", "loading")
        self._refresh_status_style()
        self.set_busy(True)

    def set_error(self, message: str) -> None:
        self.editor_status.setText(message)
        self.editor_status.setProperty("tone", "error")
        self._refresh_status_style()
        self.set_busy(False)

    def set_context(
        self,
        detail: TrackerItemDetail,
        schema: EditableTrackerSchema,
        *,
        write_enabled: bool,
    ) -> None:
        self.detail = detail
        self.schema = schema
        self.write_enabled = bool(write_enabled)
        self._busy = False
        if self.write_enabled:
            self.editor_status.setText(
                "서버 version을 다시 확인한 뒤 선택한 필드만 부분 업데이트합니다."
            )
            tone = "info"
        else:
            self.editor_status.setText(
                "테스트 모드에서는 입력 구조만 확인할 수 있으며 수정·상태 필드 변경·삭제는 실행되지 않습니다."
            )
            tone = "warning"
        self.editor_status.setProperty("tone", tone)
        self._refresh_status_style()
        self._populate_status(schema.status_field)
        self._populate_fields(schema)
        self._update_action_state()

    def _refresh_status_style(self) -> None:
        self.editor_status.style().unpolish(self.editor_status)
        self.editor_status.style().polish(self.editor_status)

    def _populate_status(self, status_field: EditableTrackerField | None) -> None:
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        if status_field is None:
            self.current_status_label.setText(
                self.detail.summary.status if self.detail is not None else "-"
            )
            self.status_combo.addItem("상태 schema 없음", None)
            self.status_combo.blockSignals(False)
            return
        current_id = self._single_reference_id(status_field.current_value)
        current_name = status_field.current_display_value or (
            self.detail.summary.status if self.detail is not None else "-"
        )
        self.current_status_label.setText(current_name or "-")
        for option in status_field.options:
            self.status_combo.addItem(option.name, option.option_id)
        selected_index = self.status_combo.findData(current_id)
        self.status_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.status_combo.blockSignals(False)

    def _populate_fields(self, schema: EditableTrackerSchema) -> None:
        candidates = [
            field_value for field_value in schema.fields if not field_value.is_status
        ]
        visible_fields = [
            field_value for field_value in candidates if field_value.editable
        ]
        hidden_count = len(candidates) - len(visible_fields)
        helper_text = (
            "수정할 필드만 체크하세요. 현재 값과 새 값을 같은 표에서 "
            "확인한 뒤 한 번에 저장합니다."
        )
        if hidden_count:
            helper_text += f" 수정할 수 없는 필드 {hidden_count}개는 숨겼습니다."
        self.editor_helper.setText(helper_text)
        self.rows.clear()
        self.field_table.blockSignals(True)
        self.field_table.setRowCount(len(visible_fields))
        for row, field_value in enumerate(visible_fields):
            check_item = QTableWidgetItem("")
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                if self.write_enabled
                else Qt.ItemFlag.NoItemFlags
            )
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.field_table.setItem(row, 0, check_item)

            name_item = QTableWidgetItem(
                f"{field_value.label}{' *' if field_value.mandatory else ''}"
            )
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name_item.setToolTip(
                f"{field_value.type_name or '-'} · fieldId {field_value.field_id}"
            )
            self.field_table.setItem(row, 1, name_item)

            current_item = QTableWidgetItem(field_value.current_display_value or "-")
            current_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            current_item.setToolTip(field_value.current_display_value)
            self.field_table.setItem(row, 2, current_item)

            editor_widget = self._create_editor_widget(field_value)
            if editor_widget is not None:
                editor_widget.setEnabled(
                    field_value.editor_kind == FieldEditorKind.TABLE
                    and not self.write_enabled
                )
                self.field_table.setCellWidget(row, 3, editor_widget)
                if field_value.editor_kind in {
                    FieldEditorKind.MULTILINE_TEXT,
                    FieldEditorKind.REFERENCE,
                } and (
                    field_value.multiple_values
                    or field_value.editor_kind == FieldEditorKind.MULTILINE_TEXT
                ):
                    self.field_table.setRowHeight(row, 72)
                elif (
                    field_value.editor_kind == FieldEditorKind.CHOICE
                    and field_value.multiple_values
                ):
                    self.field_table.setRowHeight(row, 82)
            self.rows[field_value.field_id] = _EditorRow(
                row=row,
                field=field_value,
                widget=editor_widget,
            )
        self.field_table.blockSignals(False)

    def _create_editor_widget(self, field_value: EditableTrackerField) -> QWidget | None:
        return create_tracker_field_input_widget(field_value, self.field_table)

    @staticmethod
    def _boolean_value(value: Any) -> bool:
        return tracker_field_boolean_value(value)

    @staticmethod
    def _reference_ids(value: Any) -> tuple[int, ...]:
        return tracker_field_reference_ids(value)

    @classmethod
    def _single_reference_id(cls, value: Any) -> int | None:
        return tracker_field_single_reference_id(value)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """행을 클릭하면 그 행의 `수정` 을 켜고 입력으로 포커스를 옮긴다.

        켜야 입력이 열린다는 것을 모르면 값 칸이 고장 난 것처럼 보인다.
        비활성 widget 은 마우스 이벤트를 삼키지 않아 이 신호가 그대로 온다.
        `수정` 열은 Qt 가 직접 토글하므로 건드리지 않는다.
        """
        if column == 0:
            return
        check_item = self.field_table.item(row, 0)
        if check_item is None:
            return
        if not (check_item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return
        if check_item.checkState() != Qt.CheckState.Checked:
            check_item.setCheckState(Qt.CheckState.Checked)
        widget = self.field_table.cellWidget(row, 3)
        if widget is not None and widget.isEnabled():
            widget.setFocus()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        row_value = next((row for row in self.rows.values() if row.row == item.row()), None)
        if row_value is not None and row_value.widget is not None:
            row_value.widget.setEnabled(
                not self._busy
                and (
                    (
                        self.write_enabled
                        and item.checkState() == Qt.CheckState.Checked
                    )
                    or (
                        not self.write_enabled
                        and row_value.field.editor_kind == FieldEditorKind.TABLE
                    )
                )
            )
        self._update_action_state()

    def selected_changes(self) -> tuple[TrackerItemFieldChange, ...]:
        changes: list[TrackerItemFieldChange] = []
        for row_value in self.rows.values():
            check_item = self.field_table.item(row_value.row, 0)
            if (
                check_item is None
                or check_item.checkState() != Qt.CheckState.Checked
                or row_value.widget is None
            ):
                continue
            changes.append(
                TrackerItemFieldChange(
                    field=row_value.field,
                    value=self._widget_value(row_value.field, row_value.widget),
                )
            )
        return tuple(changes)

    @staticmethod
    def _widget_value(field_value: EditableTrackerField, widget: QWidget) -> Any:
        return tracker_field_input_value(field_value, widget)

    def reset_values(self) -> None:
        if self.detail is None or self.schema is None:
            return
        self.set_context(
            self.detail,
            self.schema,
            write_enabled=self.write_enabled,
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        for row_value in self.rows.values():
            check_item = self.field_table.item(row_value.row, 0)
            if check_item is not None:
                flags = Qt.ItemFlag.NoItemFlags
                if self.write_enabled and not self._busy:
                    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                check_item.setFlags(flags)
            if row_value.widget is not None:
                row_value.widget.setEnabled(
                    not self._busy
                    and (
                        (
                            self.write_enabled
                            and check_item is not None
                            and check_item.checkState() == Qt.CheckState.Checked
                        )
                        or (
                            not self.write_enabled
                            and row_value.field.editor_kind == FieldEditorKind.TABLE
                        )
                    )
                )
        self._update_action_state()

    def _update_action_state(self, *args) -> None:
        del args
        has_context = self.detail is not None and self.schema is not None
        has_changes = bool(self.selected_changes()) if has_context else False
        self.save_button.setEnabled(
            has_context and self.write_enabled and not self._busy and has_changes
        )
        self.reset_button.setEnabled(has_context and not self._busy)
        self.delete_button.setEnabled(has_context and self.write_enabled and not self._busy)
        status_field = self.schema.status_field if self.schema is not None else None
        target_status_id = self.status_combo.currentData()
        current_status_id = (
            self._single_reference_id(status_field.current_value)
            if status_field is not None
            else None
        )
        self.transition_button.setEnabled(
            has_context
            and self.write_enabled
            and not self._busy
            and status_field is not None
            and target_status_id is not None
            and int(target_status_id) != current_status_id
        )
        self.status_combo.setEnabled(
            has_context
            and self.write_enabled
            and not self._busy
            and status_field is not None
        )

    def _request_save(self) -> None:
        changes = self.selected_changes()
        if changes:
            self.save_requested(changes)

    def _request_transition(self) -> None:
        if self.schema is None or self.schema.status_field is None:
            return
        option_id = self.status_combo.currentData()
        if option_id is None:
            return
        self.transition_requested(self.schema.status_field, int(option_id))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.editor_helper.setVisible(self.height() >= 390)


class ConfirmItemDeleteDialog(QDialog):
    """삭제 대상을 사용자가 ID로 다시 확인하는 비가역 동작 다이얼로그."""

    def __init__(self, detail: TrackerItemDetail, parent=None) -> None:
        super().__init__(parent)
        self.detail = detail
        self.setObjectName("tracker_delete_dialog")
        self.setWindowTitle("트래커 아이템 삭제")
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QLabel(f"#{detail.item_id} {detail.summary.name}")
        title.setObjectName("alert_title")
        layout.addWidget(title)
        child_notice = (
            f"직접 하위 아이템 {len(detail.children)}개가 연결되어 있습니다. "
            if detail.children
            else ""
        )
        message = QLabel(
            child_notice
            + "삭제는 되돌릴 수 없습니다. 계속하려면 아래에 아이템 ID를 입력하세요."
        )
        message.setWordWrap(True)
        message.setObjectName("alert_message")
        layout.addWidget(message)
        self.confirm_input = QLineEdit(self)
        self.confirm_input.setPlaceholderText(str(detail.item_id))
        self.confirm_input.setAccessibleName("삭제 확인 아이템 ID")
        layout.addWidget(self.confirm_input)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소", self)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        self.delete_button = QPushButton("영구 삭제", self)
        self.delete_button.setObjectName("danger_button")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.accept)
        button_row.addWidget(self.delete_button)
        layout.addLayout(button_row)
        self.confirm_input.textChanged.connect(self._update_delete_enabled)

    def _update_delete_enabled(self, text: str) -> None:
        self.delete_button.setEnabled(text.strip() == str(self.detail.item_id))

    @classmethod
    def confirm(cls, detail: TrackerItemDetail, parent=None) -> bool:
        dialog = cls(detail, parent)
        return dialog.exec() == QDialog.DialogCode.Accepted


__all__ = [
    "ConfirmItemDeleteDialog",
    "TrackerItemEditorPanel",
    "TrackerTableFieldInput",
    "create_tracker_field_input_widget",
    "tracker_field_input_value",
]
