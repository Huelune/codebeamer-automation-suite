from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QCheckBox
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QProgressBar
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QSpinBox
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_bulk_update import BulkFieldChange
from .tracker_bulk_update import build_bulk_field_values
from .tracker_item_editor import EditableTrackerField
from .tracker_item_editor import EditableTrackerSchema
from .tracker_item_editor import FieldEditorKind
from .tracker_item_editor_panel import create_tracker_field_input_widget
from .tracker_item_editor_panel import tracker_field_input_value


@dataclass(frozen=True)
class BulkUpdateRequest:
    changes: tuple[BulkFieldChange, ...]
    atomic: bool
    chunk_size: int


@dataclass
class _BulkFieldRow:
    field: EditableTrackerField
    include_item: QTableWidgetItem
    action_combo: QComboBox
    input_widget: QWidget


class TrackerBulkUpdateDialog(QDialog):
    def __init__(
        self,
        schema: EditableTrackerSchema,
        *,
        tracker_name: str,
        target_count: int,
        initial_chunk_size: int = 1000,
        initial_field_ids: tuple[int, ...] = (),
        initial_clear_field_ids: tuple[int, ...] = (),
        initial_atomic: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.schema = schema
        self.rows: dict[int, _BulkFieldRow] = {}
        self._request: BulkUpdateRequest | None = None
        self.setObjectName("tracker_bulk_update_dialog")
        self.setWindowTitle("선택 아이템 일괄 수정")
        self.setModal(True)
        self.resize(900, 650)

        layout = QVBoxLayout(self)
        title = QLabel(
            f"{tracker_name} · {int(target_count):,}개 아이템 일괄 수정",
            self,
        )
        title.setObjectName("tracker_detail_title")
        layout.addWidget(title)
        helper = QLabel(
            "체크한 필드만 모든 대상에 같은 값으로 반영합니다. 다중값과 TableField는 기존 값을 대체하며, "
            "값 비우기는 별도 동작으로 선택해야 합니다.",
            self,
        )
        helper.setWordWrap(True)
        helper.setObjectName("tracker_panel_status")
        layout.addWidget(helper)

        self.field_table = QTableWidget(0, 4, self)
        self.field_table.setHorizontalHeaderLabels(["수정", "필드", "동작", "입력값"])
        self.field_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.field_table.verticalHeader().setVisible(False)
        self.field_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.field_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.field_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.field_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.field_table.itemChanged.connect(self._update_row_states)
        layout.addWidget(self.field_table, 1)

        option_row = QHBoxLayout()
        self.atomic_checkbox = QCheckBox("청크 내 원자적 처리", self)
        self.atomic_checkbox.setChecked(bool(initial_atomic))
        self.atomic_checkbox.setToolTip(
            "켜면 한 청크에서 한 건이라도 실패할 때 그 청크 전체가 롤백됩니다."
        )
        option_row.addWidget(self.atomic_checkbox)
        option_row.addStretch(1)
        option_row.addWidget(QLabel("청크 크기", self))
        self.chunk_size_input = QSpinBox(self)
        self.chunk_size_input.setRange(1, 2_147_483_647)
        self.chunk_size_input.setValue(max(int(initial_chunk_size), 1))
        self.chunk_size_input.setToolTip("한 API 요청에 포함할 아이템 수입니다.")
        option_row.addWidget(self.chunk_size_input)
        layout.addLayout(option_row)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("tracker_detail_warning")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("취소", self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        apply_button = QPushButton("일괄 수정 실행", self)
        apply_button.setObjectName("primary_button")
        apply_button.clicked.connect(self._validate_and_accept)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)
        self._populate_fields(set(initial_field_ids), set(initial_clear_field_ids))

    def _populate_fields(self, initial_ids: set[int], clear_ids: set[int]) -> None:
        candidates = [
            field for field in self.schema.fields
            if field.editable or field.is_status
        ]
        self.field_table.blockSignals(True)
        self.field_table.setRowCount(len(candidates))
        for row, field in enumerate(candidates):
            include = QTableWidgetItem("")
            include.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            include.setCheckState(
                Qt.CheckState.Checked if field.field_id in initial_ids else Qt.CheckState.Unchecked
            )
            self.field_table.setItem(row, 0, include)
            label = QTableWidgetItem(field.label)
            label.setFlags(Qt.ItemFlag.ItemIsEnabled)
            label.setToolTip(f"{field.type_name or '-'} · fieldId {field.field_id}")
            self.field_table.setItem(row, 1, label)

            action = QComboBox(self.field_table)
            action.addItem("값 설정", False)
            if not field.mandatory and not field.is_status:
                action.addItem("값 비우기", True)
            if field.field_id in clear_ids:
                clear_index = action.findData(True)
                if clear_index >= 0:
                    action.setCurrentIndex(clear_index)
            action.currentIndexChanged.connect(self._update_row_states)
            self.field_table.setCellWidget(row, 2, action)

            input_field = (
                replace(field, editor_kind=FieldEditorKind.CHOICE)
                if field.is_status
                else field
            )
            widget = create_tracker_field_input_widget(
                input_field, self.field_table, initial_value=None
            )
            if widget is None:
                continue
            self.field_table.setCellWidget(row, 3, widget)
            if field.editor_kind in {
                FieldEditorKind.MULTILINE_TEXT,
                FieldEditorKind.TABLE,
            } or field.multiple_values:
                self.field_table.setRowHeight(row, 86)
            self.rows[field.field_id] = _BulkFieldRow(field, include, action, widget)
        self.field_table.blockSignals(False)
        self._update_row_states()

    def _update_row_states(self, *args) -> None:
        del args
        for row in self.rows.values():
            included = row.include_item.checkState() == Qt.CheckState.Checked
            clearing = bool(row.action_combo.currentData())
            row.action_combo.setEnabled(included)
            row.input_widget.setEnabled(included and not clearing)

    def _build_request(self) -> BulkUpdateRequest:
        changes: list[BulkFieldChange] = []
        for row in self.rows.values():
            if row.include_item.checkState() != Qt.CheckState.Checked:
                continue
            clear = bool(row.action_combo.currentData())
            value = None if clear else tracker_field_input_value(row.field, row.input_widget)
            changes.append(BulkFieldChange(row.field, value=value, clear=clear))
        build_bulk_field_values(self.schema, changes)
        return BulkUpdateRequest(
            changes=tuple(changes),
            atomic=self.atomic_checkbox.isChecked(),
            chunk_size=self.chunk_size_input.value(),
        )

    def _validate_and_accept(self) -> None:
        try:
            self._request = self._build_request()
        except Exception as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.accept()

    @classmethod
    def request(cls, schema: EditableTrackerSchema, **kwargs) -> BulkUpdateRequest | None:
        dialog = cls(schema, **kwargs)
        return dialog._request if dialog.exec() == QDialog.DialogCode.Accepted else None


class BulkUpdateProgressDialog(QDialog):
    def __init__(self, total: int, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("일괄 수정 진행")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.status_label = QLabel("일괄 수정 요청을 준비하는 중입니다.", self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, max(int(total), 1))
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("남은 청크 중단", self)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def update_event(self, event: dict) -> None:
        completed = int(event.get("completed") or 0)
        total = int(event.get("total") or self.progress.maximum())
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(completed)
        self.status_label.setText(
            f"{completed:,}/{total:,} 처리 · 현재 청크 성공 {int(event.get('successful') or 0):,} · "
            f"직접 실패 {int(event.get('failed') or 0):,} · 롤백 {int(event.get('rolled_back') or 0):,}"
        )


__all__ = [
    "BulkUpdateProgressDialog",
    "BulkUpdateRequest",
    "TrackerBulkUpdateDialog",
]
