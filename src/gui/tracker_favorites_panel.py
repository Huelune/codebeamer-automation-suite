"""트래커 작업공간의 즐겨찾기 탭을 맡는 자식 위젯.

고정한 트래커와 즐겨찾기 아이템을 보여 준다. 열면 다른 프로젝트·트래커로 옮겨 가고
계층 탭이 그 아이템 경로로 바뀌므로, 한 번 누르면 고르기만 하고 더블클릭이나 Enter로 연다.

작업공간과는 두 방향으로만 이어진다.

- 작업공간 -> panel: `show_favorites`
- panel -> 작업공간: `FavoritesPanelHost` 의 콜백
"""

from __future__ import annotations

from dataclasses import dataclass


try:
    from PySide6.QtCore import QModelIndex
    from PySide6.QtCore import QPersistentModelIndex
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QSplitter
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc


from collections.abc import Callable
from collections.abc import Collection

from .workspace_favorites import WorkspaceFavorites


FAVORITE_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 1
UNAVAILABLE_TEXT = "열 수 없음"


@dataclass(frozen=True)
class FavoritesPanelHost:
    """즐겨찾기 탭이 작업공간에 되돌려주는 일."""

    open_item: Callable[[int], None]
    open_tracker: Callable[[int], None]
    remove_item: Callable[[int], None]
    remove_tracker: Callable[[int], None]


def _table(parent: QWidget, headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers), parent)
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for column in range(1, len(headers)):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    return table


class TrackerFavoritesPanel(QWidget):
    """고정 트래커와 즐겨찾기 아이템 목록."""

    def __init__(self, parent: QWidget | None, *, host: FavoritesPanelHost) -> None:
        super().__init__(parent)
        self._host = host
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.hint_label = QLabel(
            "상세 머리의 ☆로 아이템을, 트래커 옆 ☆로 트래커를 추가합니다. 더블클릭이나 Enter로 엽니다.",
            self,
        )
        self.hint_label.setObjectName("tracker_panel_status")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        tracker_section = QWidget(splitter)
        tracker_layout = QVBoxLayout(tracker_section)
        tracker_layout.setContentsMargins(0, 0, 0, 0)
        tracker_label = QLabel("트래커", tracker_section)
        tracker_label.setObjectName("tracker_detail_section_title")
        tracker_layout.addWidget(tracker_label)
        self.tracker_table = _table(tracker_section, ["트래커", "프로젝트"])
        tracker_layout.addWidget(self.tracker_table, 1)
        item_section = QWidget(splitter)
        item_layout = QVBoxLayout(item_section)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_label = QLabel("아이템", item_section)
        item_label.setObjectName("tracker_detail_section_title")
        item_layout.addWidget(item_label)
        self.item_table = _table(item_section, ["요약", "ID", "트래커"])
        item_layout.addWidget(self.item_table, 1)
        splitter.addWidget(tracker_section)
        splitter.addWidget(item_section)
        # 아이템이 더 많으므로 아이템 목록에 높이를 더 준다.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_button = QPushButton("열기", self)
        self.open_button.clicked.connect(self._open_selected)
        buttons.addWidget(self.open_button)
        self.remove_button = QPushButton("즐겨찾기 해제", self)
        self.remove_button.clicked.connect(self._remove_selected)
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)

        # 버튼은 마지막으로 고른 목록에 적용한다.
        self._active_table = self.item_table
        for table in (self.tracker_table, self.item_table):
            table.activated.connect(lambda index, source=table: self._open_row(source, index))
            table.itemSelectionChanged.connect(lambda source=table: self._on_selection_changed(source))
        self._update_buttons()

    def show_favorites(
        self,
        favorites: WorkspaceFavorites,
        *,
        unavailable_item_ids: Collection[int] = (),
    ) -> None:
        """즐겨찾기를 다시 그린다. 고른 항목은 그대로 둔다."""
        selected = {table: self._selected_id(table) for table in (self.tracker_table, self.item_table)}
        self._fill(
            self.tracker_table,
            [
                (tracker.tracker_id, [tracker.name or f"트래커 #{tracker.tracker_id}", tracker.project_name])
                for tracker in favorites.trackers
            ],
        )
        self._fill(
            self.item_table,
            [
                (
                    item.item_id,
                    [
                        item.name or f"아이템 #{item.item_id}",
                        str(item.item_id),
                        UNAVAILABLE_TEXT if item.item_id in unavailable_item_ids else item.tracker_name,
                    ],
                )
                for item in favorites.items
            ],
        )
        for table, favorite_id in selected.items():
            self._select_id(table, favorite_id)
        self._update_buttons()

    @staticmethod
    def _fill(table: QTableWidget, rows: list[tuple[int, list[str]]]) -> None:
        table.blockSignals(True)
        table.setRowCount(len(rows))
        for row, (favorite_id, values) in enumerate(rows):
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                cell.setData(FAVORITE_ID_ROLE, favorite_id)
                table.setItem(row, column, cell)
        table.blockSignals(False)

    @staticmethod
    def _row_id(table: QTableWidget, row: int) -> int | None:
        cell = table.item(row, 0)
        value = cell.data(FAVORITE_ID_ROLE) if cell is not None else None
        return int(value) if isinstance(value, int) else None

    def _selected_id(self, table: QTableWidget) -> int | None:
        rows = {index.row() for index in table.selectedIndexes()}
        return self._row_id(table, min(rows)) if rows else None

    def _select_id(self, table: QTableWidget, favorite_id: int | None) -> None:
        table.blockSignals(True)
        table.clearSelection()
        for row in range(table.rowCount()):
            if favorite_id is not None and self._row_id(table, row) == favorite_id:
                table.selectRow(row)
        table.blockSignals(False)

    def _on_selection_changed(self, table: QTableWidget) -> None:
        if self._selected_id(table) is not None:
            self._active_table = table
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_selection = self._selected_id(self._active_table) is not None
        self.open_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)
        empty = not self.tracker_table.rowCount() and not self.item_table.rowCount()
        self.hint_label.setVisible(empty)

    def _open_row(self, table: QTableWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        favorite_id = self._row_id(table, index.row())
        if favorite_id is not None:
            self._open(table, favorite_id)

    def _open(self, table: QTableWidget, favorite_id: int) -> None:
        if table is self.tracker_table:
            self._host.open_tracker(favorite_id)
        else:
            self._host.open_item(favorite_id)

    def _open_selected(self, _checked: bool = False) -> None:
        favorite_id = self._selected_id(self._active_table)
        if favorite_id is not None:
            self._open(self._active_table, favorite_id)

    def _remove_selected(self, _checked: bool = False) -> None:
        favorite_id = self._selected_id(self._active_table)
        if favorite_id is None:
            return
        if self._active_table is self.tracker_table:
            self._host.remove_tracker(favorite_id)
        else:
            self._host.remove_item(favorite_id)
