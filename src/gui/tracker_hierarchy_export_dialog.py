from __future__ import annotations


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QDialogButtonBox
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtWidgets import QListWidget
    from PySide6.QtWidgets import QListWidgetItem
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QVBoxLayout
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_hierarchy_export import TrackerHierarchyExportField


class TrackerHierarchyExportFieldDialog(QDialog):
    """트래커 계층 Excel에 추가할 스키마 필드를 선택한다."""

    def __init__(
        self,
        fields: tuple[TrackerHierarchyExportField, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.fields = tuple(fields)
        self.setWindowTitle("트래커 계층 Excel 필드 선택")
        self.setMinimumSize(540, 540)

        layout = QVBoxLayout(self)
        description = QLabel(
            "ID, Summary, 계층 단계, 상위 아이템 ID는 항상 포함됩니다. "
            "TableField를 선택하면 내부 열과 행 순서를 그대로 내보냅니다.",
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("hierarchy_export_field_search")
        self.search_input.setPlaceholderText("필드 이름 검색")
        self.search_input.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_input)

        self.field_list = QListWidget(self)
        self.field_list.setObjectName("hierarchy_export_field_list")
        for field in self.fields:
            suffix = (
                f" · TableField {len(field.table_columns)}열"
                if field.is_table
                else ""
            )
            item = QListWidgetItem(f"{field.label}{suffix}", self.field_list)
            item.setData(Qt.ItemDataRole.UserRole, field.field_key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if field.default_selected
                else Qt.CheckState.Unchecked
            )
        layout.addWidget(self.field_list, 1)

        selection_row = QHBoxLayout()
        self.status_label = QLabel(self)
        self.status_label.setObjectName("hierarchy_export_selection_status")
        selection_row.addWidget(self.status_label, 1)
        select_all = QPushButton("전체 선택", self)
        select_all.clicked.connect(lambda: self._set_all_checks(Qt.CheckState.Checked))
        selection_row.addWidget(select_all)
        clear = QPushButton("전체 해제", self)
        clear.clicked.connect(lambda: self._set_all_checks(Qt.CheckState.Unchecked))
        selection_row.addWidget(clear)
        layout.addLayout(selection_row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("파일 선택")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.field_list.itemChanged.connect(self._update_status)
        self._update_status()

    def selected_field_keys(self) -> tuple[str, ...]:
        selected: list[str] = []
        for index in range(self.field_list.count()):
            item = self.field_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return tuple(selected)

    def _apply_filter(self, text: str) -> None:
        needle = str(text or "").strip().casefold()
        for index in range(self.field_list.count()):
            item = self.field_list.item(index)
            item.setHidden(bool(needle) and needle not in item.text().casefold())

    def _set_all_checks(self, state: Qt.CheckState) -> None:
        self.field_list.blockSignals(True)
        for index in range(self.field_list.count()):
            self.field_list.item(index).setCheckState(state)
        self.field_list.blockSignals(False)
        self._update_status()

    def _update_status(self, *_args) -> None:
        count = len(self.selected_field_keys())
        self.status_label.setText(
            f"추가 필드 {count}개 / 전체 {len(self.fields)}개 · 고정 열 4개"
        )


__all__ = ["TrackerHierarchyExportFieldDialog"]
