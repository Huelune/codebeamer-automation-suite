from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QDialogButtonBox
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtWidgets import QVBoxLayout
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_content_models import WikiRenderResult
from .tracker_query_models import TrackerFieldValue
from .wiki_content_view import WikiContentView
from .wiki_renderer import codebeamer_wiki_to_html
from .wiki_renderer import payload_uses_wiki


_PREFERRED_COLUMN_WIDTH = 220
_MAXIMUM_AUTOFIT_COLUMN_WIDTH = 480


def is_table_field(field: TrackerFieldValue) -> bool:
    type_name = str(field.type_name or "").strip().casefold()
    raw_type = str(field.raw_value.get("type") or "").strip().casefold()
    return "tablefield" in type_name or "tablefield" in raw_type


def _row_payloads(payload: dict[str, Any]) -> list[list[dict[str, Any]]]:
    raw_rows = payload.get("values")
    if not isinstance(raw_rows, list):
        return []
    rows: list[list[dict[str, Any]]] = []
    for raw_row in raw_rows:
        if isinstance(raw_row, list):
            rows.append([cell for cell in raw_row if isinstance(cell, dict)])
            continue
        if isinstance(raw_row, dict) and isinstance(raw_row.get("values"), list):
            rows.append(
                [cell for cell in raw_row["values"] if isinstance(cell, dict)]
            )
    return rows


def _field_id(payload: dict[str, Any]) -> int | None:
    raw_id = payload.get("fieldId")
    if raw_id is None:
        raw_id = payload.get("id")
    if raw_id is None or isinstance(raw_id, bool):
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _column_key(payload: dict[str, Any], fallback_index: int) -> tuple[str, Any]:
    field_id = _field_id(payload)
    if field_id is not None:
        return ("id", field_id)
    name = str(payload.get("name") or "").strip()
    if name:
        return ("name", name.casefold())
    return ("index", fallback_index)


def _column_payloads(
    payload: dict[str, Any],
    rows: list[list[dict[str, Any]]],
) -> list[tuple[tuple[str, Any], dict[str, Any]]]:
    columns: list[tuple[tuple[str, Any], dict[str, Any]]] = []
    seen: set[tuple[str, Any]] = set()
    schema_columns = payload.get("columns")
    candidates: list[list[dict[str, Any]]] = []
    if isinstance(schema_columns, list):
        candidates.append([column for column in schema_columns if isinstance(column, dict)])
    candidates.extend(rows)
    for candidate_row in candidates:
        for index, column in enumerate(candidate_row):
            key = _column_key(column, index)
            if key in seen:
                continue
            seen.add(key)
            columns.append((key, deepcopy(column)))
    return columns


def _plain_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, dict):
        for key in ("value", "name", "summary", "id"):
            if value.get(key) not in (None, ""):
                return _plain_value(value.get(key))
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(
            text for text in (_plain_value(item) for item in value) if text
        )
    return str(value).strip()


def _cell_text(payload: dict[str, Any]) -> str:
    if "value" in payload:
        return _plain_value(payload.get("value"))
    if "values" in payload:
        return _plain_value(payload.get("values"))
    return ""


def table_field_dimensions(field: TrackerFieldValue) -> tuple[int, int]:
    rows = _row_payloads(field.raw_value)
    columns = _column_payloads(field.raw_value, rows)
    return len(rows), len(columns)


def table_field_summary(field: TrackerFieldValue) -> str:
    row_count, column_count = table_field_dimensions(field)
    if row_count or column_count:
        return f"{row_count}행 × {column_count}열"
    return "빈 테이블"


class TrackerTableFieldDialog(QDialog):
    """TableField 행·열 구조를 보존하며 Wiki 셀만 rich text로 표시한다."""

    def __init__(
        self,
        field: TrackerFieldValue,
        parent=None,
        *,
        wiki_render_request: Callable[[str, Callable[[WikiRenderResult], None]], None] | None = None,
        wiki_resource_loader: Callable[[WikiRenderResult, WikiContentView], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.field = field
        self.rows = _row_payloads(field.raw_value)
        self.columns = _column_payloads(field.raw_value, self.rows)
        self.wiki_render_request = wiki_render_request
        self.wiki_resource_loader = wiki_resource_loader
        self._wiki_generation = 0
        self._pending_wiki: list[tuple[int, str, WikiContentView]] = []
        self._active_wiki_requests = 0
        self.setWindowTitle(f"{field.name} · 테이블 보기")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setMinimumSize(720, 440)
        self.resize(920, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(f"{field.name} · {table_field_summary(field)}", self)
        title.setObjectName("tracker_detail_section_title")
        header.addWidget(title, 1)
        self.fit_columns_button = QPushButton("열 너비 맞춤", self)
        self.fit_columns_button.setToolTip(
            "내용에 맞게 열 너비를 다시 조정합니다. "
            "열 머리글 경계를 드래그해 직접 조정할 수도 있습니다."
        )
        self.fit_columns_button.clicked.connect(self._fit_columns_to_contents)
        header.addWidget(self.fit_columns_button)
        self.fit_rows_button = QPushButton("행 높이 맞춤", self)
        self.fit_rows_button.setToolTip(
            "내용에 맞게 행 높이를 다시 조정합니다. "
            "행 번호 경계를 드래그해 직접 조정할 수도 있습니다."
        )
        self.fit_rows_button.clicked.connect(self._fit_rows_to_contents)
        header.addWidget(self.fit_rows_button)
        self.fullscreen_button = QPushButton("전체 화면", self)
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.toggled.connect(self._set_fullscreen)
        header.addWidget(self.fullscreen_button)
        self.source_toggle = QPushButton("Wiki 원문", self)
        self.source_toggle.setObjectName("mode_toggle")
        self.source_toggle.setCheckable(True)
        self.source_toggle.toggled.connect(self._populate)
        header.addWidget(self.source_toggle)
        layout.addLayout(header)

        self.table = QTableWidget(self)
        self.table.setObjectName("tracker_table_field_view")
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setWordWrap(True)
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        row_header = self.table.verticalHeader()
        row_header.setVisible(True)
        row_header.setMinimumSectionSize(24)
        row_header.setDefaultSectionSize(36)
        row_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table_header = self.table.horizontalHeader()
        table_header.setMinimumSectionSize(80)
        table_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table_header.setStretchLastSection(False)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText("닫기")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate(False)
        self._fit_columns_to_contents()
        self._fit_rows_to_contents()

    def _cell_for_column(
        self,
        row: list[dict[str, Any]],
        key: tuple[str, Any],
        column_index: int,
    ) -> dict[str, Any] | None:
        for index, cell in enumerate(row):
            if _column_key(cell, index) == key:
                return cell
        if key[0] == "index" and column_index < len(row):
            return row[column_index]
        return None

    def _populate(self, show_source: bool = False) -> None:
        self._wiki_generation += 1
        generation = self._wiki_generation
        self._pending_wiki.clear()
        self._active_wiki_requests = 0
        previous_row_heights = [
            self.table.rowHeight(index) for index in range(self.table.rowCount())
        ]
        self.source_toggle.setText("렌더링 보기" if show_source else "Wiki 원문")
        self.table.clear()
        self.table.setRowCount(len(self.rows))
        self.table.setColumnCount(len(self.columns))
        self.table.setVerticalHeaderLabels(
            [str(index + 1) for index in range(len(self.rows))]
        )
        self.table.setHorizontalHeaderLabels(
            [
                str(column.get("name") or f"열 {index + 1}")
                for index, (_, column) in enumerate(self.columns)
            ]
        )
        for row_index, row in enumerate(self.rows):
            for column_index, (key, column_schema) in enumerate(self.columns):
                cell = self._cell_for_column(row, key, column_index)
                if cell is None:
                    self.table.setItem(row_index, column_index, QTableWidgetItem(""))
                    continue
                text = _cell_text(cell)
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row_index, column_index, item)
                metadata = dict(column_schema)
                metadata.update(cell)
                if show_source or not payload_uses_wiki(metadata):
                    continue
                label = WikiContentView(self.table)
                label.setObjectName("tracker_wiki_cell")
                label.setMinimumHeight(32)
                label.setHtml(codebeamer_wiki_to_html(text))
                item.setText("")
                self.table.setCellWidget(row_index, column_index, label)
                if self.wiki_render_request is not None:
                    self._pending_wiki.append((generation, text, label))
        for row_index, height in enumerate(previous_row_heights[: len(self.rows)]):
            self.table.setRowHeight(row_index, height)
        self._drain_wiki_queue()

    def _drain_wiki_queue(self) -> None:
        while self._active_wiki_requests < 4 and self._pending_wiki:
            generation, text, view = self._pending_wiki.pop(0)
            if generation != self._wiki_generation:
                continue
            self._active_wiki_requests += 1

            def completed(
                result: WikiRenderResult,
                *,
                expected_generation=generation,
                target=view,
            ) -> None:
                self._active_wiki_requests = max(0, self._active_wiki_requests - 1)
                if expected_generation == self._wiki_generation:
                    target.set_render_result(result)
                    if self.wiki_resource_loader is not None:
                        self.wiki_resource_loader(result, target)
                self._drain_wiki_queue()

            if self.wiki_render_request is not None:
                self.wiki_render_request(text, completed)

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
            content_width = self.table.columnWidth(column_index) + 16
            self.table.setColumnWidth(
                column_index,
                min(
                    _MAXIMUM_AUTOFIT_COLUMN_WIDTH,
                    max(preferred_width, content_width),
                ),
            )

    def _fit_rows_to_contents(self, _checked: bool = False) -> None:
        self.table.resizeRowsToContents()

    def _set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_button.setText("창 모드" if enabled else "전체 화면")
        if enabled:
            self.showFullScreen()
            return
        self.showNormal()


__all__ = [
    "TrackerTableFieldDialog",
    "is_table_field",
    "table_field_dimensions",
    "table_field_summary",
]
