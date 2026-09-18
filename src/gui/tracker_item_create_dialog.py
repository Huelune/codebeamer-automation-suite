from __future__ import annotations

from dataclasses import dataclass


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QRadioButton
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_item_editor import EditableTrackerField
from .tracker_item_editor import EditableTrackerSchema
from .tracker_item_editor import FieldEditorKind
from .tracker_item_editor import TrackerItemFieldChange
from .tracker_item_editor import build_create_item_payload
from .tracker_item_editor_panel import create_tracker_field_input_widget
from .tracker_item_editor_panel import tracker_field_input_value
from .tracker_query_models import TrackerItemDetail


@dataclass(frozen=True)
class TrackerItemCreateRequest:
    changes: tuple[TrackerItemFieldChange, ...]
    parent_item_id: int | None = None


@dataclass
class _CreateFieldRow:
    row: int
    field: EditableTrackerField
    include_item: QTableWidgetItem
    widget: QWidget | None


class TrackerItemCreateDialog(QDialog):
    """선택 tracker의 schema를 사용해 단건 생성 입력을 받는다."""

    def __init__(
        self,
        schema: EditableTrackerSchema,
        *,
        tracker_name: str,
        selected_detail: TrackerItemDetail | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.schema = schema
        self.tracker_name = str(tracker_name or schema.tracker_id)
        self.selected_detail = (
            selected_detail
            if selected_detail is not None
            and selected_detail.summary.tracker_id == schema.tracker_id
            else None
        )
        self.rows: dict[int, _CreateFieldRow] = {}

        self.setObjectName("tracker_item_create_dialog")
        self.setWindowTitle("새 트래커 아이템")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setModal(True)
        self.resize(760, 620)
        self.setMinimumSize(620, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("새 트래커 아이템", self)
        title.setObjectName("tracker_detail_title")
        title_row.addWidget(title, 1)
        self.fullscreen_button = QPushButton("전체 화면", self)
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.toggled.connect(self._set_fullscreen)
        title_row.addWidget(self.fullscreen_button)
        layout.addLayout(title_row)
        context = QLabel(
            f"생성 위치: {self.tracker_name} ({schema.tracker_id})",
            self,
        )
        context.setObjectName("tracker_detail_breadcrumb")
        layout.addWidget(context)

        self.validation_label = QLabel("", self)
        self.validation_label.setObjectName("tracker_editor_status")
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        layout.addWidget(self.validation_label)

        target_title = QLabel("계층 위치", self)
        target_title.setObjectName("tracker_detail_section_title")
        layout.addWidget(target_title)
        target_row = QHBoxLayout()
        self.root_radio = QRadioButton("최상위 아이템", self)
        self.root_radio.setChecked(True)
        target_row.addWidget(self.root_radio)
        self.child_radio = QRadioButton(self)
        if self.selected_detail is None:
            self.child_radio.setText("선택한 아이템의 하위 (선택된 아이템 없음)")
            self.child_radio.setEnabled(False)
        else:
            self.child_radio.setText(
                "선택한 아이템의 하위 "
                f"(#{self.selected_detail.item_id} {self.selected_detail.summary.name})"
            )
        target_row.addWidget(self.child_radio, 1)
        layout.addLayout(target_row)

        helper = QLabel(
            "* 필수 필드는 항상 포함됩니다. 선택 필드는 '포함'을 체크한 경우에만 전송합니다. "
            "상태는 서버 기본값으로 생성한 뒤 수정 탭에서 별도로 전환합니다.",
            self,
        )
        helper.setObjectName("tracker_panel_status")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        self.field_table = QTableWidget(0, 3, self)
        self.field_table.setObjectName("tracker_create_fields")
        self.field_table.setHorizontalHeaderLabels(["포함", "필드", "입력값"])
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
        self.field_table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.field_table, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("취소", self)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        self.create_button = QPushButton("아이템 생성", self)
        self.create_button.setObjectName("primary_button")
        self.create_button.clicked.connect(self._validate_and_accept)
        button_row.addWidget(self.create_button)
        layout.addLayout(button_row)

        self._populate_fields()

    def _populate_fields(self) -> None:
        candidates = [
            field_value
            for field_value in self.schema.fields
            if not field_value.is_status
            and field_value.tracker_item_field != "status"
        ]
        unsupported_required = [
            field_value.label
            for field_value in candidates
            if field_value.mandatory and not field_value.editable
        ]
        visible_fields = [
            field_value for field_value in candidates if field_value.editable
        ]
        self.rows.clear()
        self.field_table.blockSignals(True)
        self.field_table.setRowCount(len(visible_fields))
        for row, field_value in enumerate(visible_fields):
            include_item = QTableWidgetItem("")
            if field_value.mandatory:
                include_item.setCheckState(Qt.CheckState.Checked)
                include_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            elif field_value.editable:
                include_item.setCheckState(Qt.CheckState.Unchecked)
                include_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
                )
            else:
                include_item.setCheckState(Qt.CheckState.Unchecked)
                include_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.field_table.setItem(row, 0, include_item)

            name_item = QTableWidgetItem(
                f"{field_value.label}{' *' if field_value.mandatory else ''}"
            )
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name_item.setToolTip(
                f"{field_value.type_name or '-'} · fieldId {field_value.field_id}"
            )
            self.field_table.setItem(row, 1, name_item)

            widget = create_tracker_field_input_widget(
                field_value,
                self.field_table,
                initial_value=None,
            )
            if widget is not None:
                widget.setEnabled(field_value.mandatory)
                self.field_table.setCellWidget(row, 2, widget)
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
            self.rows[field_value.field_id] = _CreateFieldRow(
                row=row,
                field=field_value,
                include_item=include_item,
                widget=widget,
            )
        self.field_table.blockSignals(False)

        if unsupported_required:
            self.create_button.setEnabled(False)
            self._show_validation(
                "필수 필드의 입력 형식을 지원하지 않아 생성할 수 없습니다: "
                + ", ".join(unsupported_required)
            )

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        row_value = next(
            (row for row in self.rows.values() if row.row == item.row()),
            None,
        )
        if row_value is not None and row_value.widget is not None:
            row_value.widget.setEnabled(
                item.checkState() == Qt.CheckState.Checked
            )

    def selected_changes(self) -> tuple[TrackerItemFieldChange, ...]:
        changes: list[TrackerItemFieldChange] = []
        for row_value in self.rows.values():
            if (
                row_value.include_item.checkState() != Qt.CheckState.Checked
                or row_value.widget is None
            ):
                continue
            changes.append(
                TrackerItemFieldChange(
                    field=row_value.field,
                    value=tracker_field_input_value(row_value.field, row_value.widget),
                )
            )
        return tuple(changes)

    def selected_parent_item_id(self) -> int | None:
        if self.child_radio.isChecked() and self.selected_detail is not None:
            return self.selected_detail.item_id
        return None

    def request_value(self) -> TrackerItemCreateRequest:
        return TrackerItemCreateRequest(
            changes=self.selected_changes(),
            parent_item_id=self.selected_parent_item_id(),
        )

    def _show_validation(self, message: str) -> None:
        self.validation_label.setText(str(message or ""))
        self.validation_label.setProperty("tone", "error")
        self.validation_label.style().unpolish(self.validation_label)
        self.validation_label.style().polish(self.validation_label)
        self.validation_label.show()

    def _set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_button.setText("창 모드" if enabled else "전체 화면")
        if enabled:
            self.showFullScreen()
            return
        self.showNormal()

    def _validate_and_accept(self) -> None:
        try:
            build_create_item_payload(self.schema, self.selected_changes())
        except (TypeError, ValueError) as exc:
            self._show_validation(str(exc) or "생성 입력값을 확인하세요.")
            return
        self.accept()

    @classmethod
    def request(
        cls,
        schema: EditableTrackerSchema,
        *,
        tracker_name: str,
        selected_detail: TrackerItemDetail | None = None,
        parent=None,
    ) -> TrackerItemCreateRequest | None:
        dialog = cls(
            schema,
            tracker_name=tracker_name,
            selected_detail=selected_detail,
            parent=parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.request_value()


__all__ = [
    "TrackerItemCreateDialog",
    "TrackerItemCreateRequest",
]
