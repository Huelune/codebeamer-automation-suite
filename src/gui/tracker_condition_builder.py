from __future__ import annotations

from dataclasses import dataclass
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QFrame
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QScrollArea
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_item_editor import EditableTrackerSchema
from .tracker_item_editor import FieldEditorKind
from .tracker_query_models import TrackerQueryCondition
from .tracker_query_models import TrackerQueryGroup


@dataclass(frozen=True)
class TrackerQueryFieldSpec:
    field_id: int
    label: str
    query_name: str
    kind: FieldEditorKind
    options: tuple[str, ...] = ()


_OPERATOR_LABELS = {
    "equals": "같음",
    "not_equals": "같지 않음",
    "contains": "포함",
    "not_contains": "포함하지 않음",
    "gt": "보다 큼",
    "gte": "이상",
    "lt": "보다 작음",
    "lte": "이하",
    "in": "목록 중 하나",
    "not_in": "목록에 없음",
}


def query_field_specs(schema: EditableTrackerSchema) -> tuple[TrackerQueryFieldSpec, ...]:
    specs: list[TrackerQueryFieldSpec] = [
        TrackerQueryFieldSpec(
            field_id=0,
            label="ID",
            query_name="item.id",
            kind=FieldEditorKind.INTEGER,
        )
    ]
    seen_names: set[str] = {"item.id"}
    for field_value in schema.fields:
        if field_value.editor_kind in {FieldEditorKind.TABLE, FieldEditorKind.UNSUPPORTED}:
            tracker_item_field = str(field_value.tracker_item_field or "")
            if tracker_item_field != "id":
                continue
        tracker_item_field = str(field_value.tracker_item_field or "").strip()
        if tracker_item_field == "id" or field_value.name.casefold() == "id":
            query_name = "item.id"
            kind = FieldEditorKind.INTEGER
        elif tracker_item_field == "name":
            query_name = "summary"
            kind = FieldEditorKind.TEXT
        elif tracker_item_field == "status" or field_value.is_status:
            query_name = "status"
            kind = FieldEditorKind.CHOICE
        elif tracker_item_field == "assignedTo":
            query_name = "assignedTo"
            kind = FieldEditorKind.REFERENCE
        else:
            query_name = field_value.name
            kind = field_value.editor_kind
        if not query_name or query_name.casefold() in seen_names:
            continue
        seen_names.add(query_name.casefold())
        specs.append(
            TrackerQueryFieldSpec(
                field_id=field_value.field_id,
                label=field_value.label,
                query_name=query_name,
                kind=kind,
                options=tuple(option.name for option in field_value.options),
            )
        )
    return tuple(specs)


def _operators(spec: TrackerQueryFieldSpec) -> tuple[str, ...]:
    if spec.kind in {FieldEditorKind.TEXT, FieldEditorKind.MULTILINE_TEXT}:
        return ("equals", "not_equals", "contains", "not_contains", "in", "not_in")
    if spec.kind in {
        FieldEditorKind.INTEGER,
        FieldEditorKind.DECIMAL,
        FieldEditorKind.DATE,
        FieldEditorKind.DATETIME,
    }:
        return ("equals", "not_equals", "gt", "gte", "lt", "lte", "in", "not_in")
    return ("equals", "not_equals", "in", "not_in")


class TrackerConditionRow(QFrame):
    remove_requested = Signal(object)
    changed = Signal()

    def __init__(self, fields: tuple[TrackerQueryFieldSpec, ...], parent=None) -> None:
        super().__init__(parent)
        self.fields = fields
        self.setObjectName("tracker_condition_row")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        self.field_combo = QComboBox(self)
        self.field_combo.setObjectName("tracker_condition_field")
        for value in fields:
            self.field_combo.addItem(value.label, value)
        layout.addWidget(self.field_combo, 2)
        self.operator_combo = QComboBox(self)
        self.operator_combo.setObjectName("tracker_condition_operator")
        layout.addWidget(self.operator_combo, 1)
        self.value_input = QLineEdit(self)
        self.value_input.setObjectName("tracker_condition_value")
        layout.addWidget(self.value_input, 3)
        self.remove_button = QPushButton("조건 삭제", self)
        self.remove_button.clicked.connect(
            lambda _checked=False: self.remove_requested.emit(self)
        )
        layout.addWidget(self.remove_button)
        self.field_combo.currentIndexChanged.connect(self._field_changed)
        self.operator_combo.currentIndexChanged.connect(self._operator_changed)
        self.value_input.textChanged.connect(lambda _text: self.changed.emit())
        self._field_changed()

    def field_spec(self) -> TrackerQueryFieldSpec | None:
        value = self.field_combo.currentData()
        return value if isinstance(value, TrackerQueryFieldSpec) else None

    def _field_changed(self, *args) -> None:
        del args
        spec = self.field_spec()
        self.operator_combo.blockSignals(True)
        self.operator_combo.clear()
        if spec is not None:
            for operator in _operators(spec):
                self.operator_combo.addItem(_OPERATOR_LABELS[operator], operator)
        self.operator_combo.blockSignals(False)
        self._operator_changed()
        self.changed.emit()

    def _operator_changed(self, *args) -> None:
        del args
        spec = self.field_spec()
        operator = str(self.operator_combo.currentData() or "")
        if operator in {"in", "not_in"}:
            self.value_input.setPlaceholderText("값을 세미콜론(;)으로 구분")
        elif spec is not None and spec.options:
            self.value_input.setPlaceholderText("가능 값: " + ", ".join(spec.options[:6]))
        elif spec is not None and spec.kind == FieldEditorKind.BOOLEAN:
            self.value_input.setPlaceholderText("예 또는 아니요")
        else:
            self.value_input.setPlaceholderText("검색 값")
        self.changed.emit()

    def condition(self) -> TrackerQueryCondition:
        spec = self.field_spec()
        if spec is None:
            raise ValueError("검색 조건 필드를 선택하세요.")
        operator = str(self.operator_combo.currentData() or "")
        raw_value = self.value_input.text().strip()
        if operator in {"in", "not_in"}:
            values = [value.strip() for value in raw_value.split(";") if value.strip()]
            value: Any = [_typed_value(spec, raw) for raw in values]
        else:
            value = _typed_value(spec, raw_value)
        return TrackerQueryCondition(
            spec.query_name,
            operator,
            value,
            field_type=spec.kind.value,
        )


def _typed_value(spec: TrackerQueryFieldSpec, value: str) -> Any:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if spec.kind == FieldEditorKind.INTEGER:
        return int(normalized)
    if spec.kind == FieldEditorKind.DECIMAL:
        return float(normalized)
    if spec.kind == FieldEditorKind.BOOLEAN:
        lowered = normalized.casefold()
        if lowered not in {"true", "false", "1", "0", "예", "아니요"}:
            raise ValueError("참·거짓 검색값은 예 또는 아니요여야 합니다.")
        return lowered in {"true", "1", "예"}
    return normalized


class TrackerConditionGroup(QFrame):
    remove_requested = Signal(object)
    changed = Signal()

    def __init__(
        self,
        fields: tuple[TrackerQueryFieldSpec, ...],
        *,
        index: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.fields = fields
        self.rows: list[TrackerConditionRow] = []
        self.setObjectName("tracker_condition_group")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(5)
        header = QHBoxLayout()
        self.title_label = QLabel("", self)
        self.title_label.setObjectName("tracker_detail_section_title")
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.add_row_button = QPushButton("함께 만족할 조건 추가", self)
        self.add_row_button.clicked.connect(lambda _checked=False: self.add_row())
        header.addWidget(self.add_row_button)
        self.remove_button = QPushButton("조건 묶음 삭제", self)
        self.remove_button.clicked.connect(
            lambda _checked=False: self.remove_requested.emit(self)
        )
        header.addWidget(self.remove_button)
        layout.addLayout(header)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(4)
        layout.addLayout(self.rows_layout)
        self.set_index(index)
        self.add_row()

    def set_index(self, index: int) -> None:
        self.title_label.setText(
            f"조건 묶음 {int(index) + 1} · 아래 조건을 모두 만족"
        )

    def add_row(self) -> TrackerConditionRow:
        row = TrackerConditionRow(self.fields, self)
        row.remove_requested.connect(self.remove_row)
        row.changed.connect(self.changed.emit)
        self.rows.append(row)
        self.rows_layout.addWidget(row)
        self._update_remove_state()
        self.changed.emit()
        return row

    def remove_row(self, row: TrackerConditionRow) -> None:
        if row not in self.rows or len(self.rows) <= 1:
            return
        self.rows.remove(row)
        row.deleteLater()
        self._update_remove_state()
        self.changed.emit()

    def _update_remove_state(self) -> None:
        for row in self.rows:
            row.remove_button.setEnabled(len(self.rows) > 1)

    def value(self) -> TrackerQueryGroup:
        return TrackerQueryGroup(row.condition() for row in self.rows)


class TrackerConditionBuilder(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.fields: tuple[TrackerQueryFieldSpec, ...] = ()
        self.groups: list[TrackerConditionGroup] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        toolbar = QHBoxLayout()
        self.helper_label = QLabel(
            "한 묶음 안의 조건은 모두 만족해야 합니다. 묶음이 여러 개면 그중 하나만 만족해도 검색됩니다.",
            self,
        )
        self.helper_label.setObjectName("tracker_panel_status")
        self.helper_label.setWordWrap(True)
        toolbar.addWidget(self.helper_label, 1)
        self.add_group_button = QPushButton("다른 조건 묶음 추가", self)
        self.add_group_button.clicked.connect(lambda _checked=False: self.add_group())
        toolbar.addWidget(self.add_group_button)
        self.clear_button = QPushButton("조건 초기화", self)
        self.clear_button.clicked.connect(lambda _checked=False: self.reset())
        toolbar.addWidget(self.clear_button)
        layout.addLayout(toolbar)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        self.groups_host = QWidget(scroll)
        self.groups_layout = QVBoxLayout(self.groups_host)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.setSpacing(6)
        self.groups_layout.addStretch(1)
        scroll.setWidget(self.groups_host)
        layout.addWidget(scroll, 1)
        self.setEnabled(False)

    def set_schema(self, schema: EditableTrackerSchema) -> None:
        self.fields = query_field_specs(schema)
        self.reset()
        self.setEnabled(bool(self.fields))

    def clear_schema(self) -> None:
        self.fields = ()
        self.reset()
        self.setEnabled(False)

    def add_group(self) -> TrackerConditionGroup | None:
        if not self.fields:
            return None
        group = TrackerConditionGroup(self.fields, index=len(self.groups), parent=self.groups_host)
        group.remove_requested.connect(self.remove_group)
        group.changed.connect(self.changed.emit)
        self.groups.append(group)
        self.groups_layout.insertWidget(self.groups_layout.count() - 1, group)
        self._refresh_groups()
        self.changed.emit()
        return group

    def remove_group(self, group: TrackerConditionGroup) -> None:
        if group not in self.groups or len(self.groups) <= 1:
            return
        self.groups.remove(group)
        group.deleteLater()
        self._refresh_groups()
        self.changed.emit()

    def reset(self) -> None:
        for group in self.groups:
            group.deleteLater()
        self.groups = []
        if self.fields:
            self.add_group()
        self._refresh_groups()
        self.changed.emit()

    def _refresh_groups(self) -> None:
        for index, group in enumerate(self.groups):
            group.set_index(index)
            group.remove_button.setEnabled(len(self.groups) > 1)

    def values(self) -> tuple[TrackerQueryGroup, ...]:
        return tuple(group.value() for group in self.groups)

    def summary_text(self) -> str:
        group_count = len(self.groups)
        condition_count = sum(len(group.rows) for group in self.groups)
        if not self.fields:
            return "상세 검색에 사용할 필드 정보를 불러오지 않았습니다."
        return f"조건 묶음 {group_count}개 · 입력 조건 {condition_count}개"


class TrackerConditionDialog(QDialog):
    """상세 검색 조건을 넓은 별도 창에서 편집한다."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("tracker_condition_dialog")
        self.setWindowTitle("상세 검색 조건 설정")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setModal(False)
        self.setMinimumSize(860, 600)
        self.resize(1180, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("상세 검색 조건 설정", self)
        title.setObjectName("tracker_detail_title")
        heading.addWidget(title, 1)
        self.fullscreen_button = QPushButton("전체 화면", self)
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.toggled.connect(self._set_fullscreen)
        heading.addWidget(self.fullscreen_button)
        self.close_button = QPushButton("설정 완료", self)
        self.close_button.setObjectName("primary_button")
        self.close_button.clicked.connect(self.close)
        heading.addWidget(self.close_button)
        layout.addLayout(heading)

        self.guide_label = QLabel(
            "필드와 비교 방식을 선택하고 검색값을 입력하세요. 작성한 조건은 설정 완료 후에도 유지됩니다.",
            self,
        )
        self.guide_label.setObjectName("tracker_panel_status")
        self.guide_label.setWordWrap(True)
        layout.addWidget(self.guide_label)

        self.builder = TrackerConditionBuilder(self)
        layout.addWidget(self.builder, 1)

        self.summary_label = QLabel("", self)
        self.summary_label.setObjectName("tracker_panel_status")
        layout.addWidget(self.summary_label)
        self.builder.changed.connect(self.refresh_summary)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        self.summary_label.setText(self.builder.summary_text())

    def show_editor(self) -> None:
        self.refresh_summary()
        self.show()
        self.raise_()
        self.activateWindow()

    def _set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_button.setText("창 모드" if enabled else "전체 화면")
        if enabled:
            self.showFullScreen()
            return
        self.showNormal()


__all__ = [
    "TrackerConditionBuilder",
    "TrackerConditionDialog",
    "TrackerConditionGroup",
    "TrackerConditionRow",
    "TrackerQueryFieldSpec",
    "query_field_specs",
]
