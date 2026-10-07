"""아이템 버전 이력을 버전별 필드 변경까지 보여 주는 트리.

상세 창의 변경 이력 탭과 Baseline 비교의 변경 이력 탭이 함께 쓴다.
버전 줄 아래에 필드별 이전 값·새 값을 두고, 값은 Baseline 비교와 같은 방식으로 글자로 바꾼다.
"""

from __future__ import annotations


try:
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QTreeWidget
    from PySide6.QtWidgets import QTreeWidgetItem
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc


from collections.abc import Sequence

from .tracker_baseline_compare import display_tracker_value
from .tracker_item_context_models import ItemHistoryEntry


# 긴 설명이나 표 값은 칸에서 줄이고 툴팁으로 전체를 보인다.
MAX_CELL_TEXT = 300
MAX_TOOLTIP_TEXT = 4000


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def history_time_text(value: str) -> str:
    """`2026-07-20T10:45:36.456` 같은 시각을 분까지 줄인다. 다른 모양은 그대로 둔다."""
    text = str(value or "").strip()
    if len(text) >= 16 and text[10] == "T":
        return text[:16].replace("T", " ")
    return text


class ItemChangeHistoryView(QTreeWidget):
    """버전별 필드 변경 이력."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("item_change_history")
        self.setColumnCount(3)
        self.setHeaderLabels(["변경", "이전 값", "새 값"])
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setWordWrap(True)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(0, 220)

    def show_entries(
        self,
        entries: Sequence[ItemHistoryEntry],
        *,
        current_version: int | None = None,
        baseline: tuple[int, str] | None = None,
    ) -> None:
        """최신 버전부터 보인다. `baseline`(버전, 이름)이 있으면 그 버전 앞에 구분선을 넣는다."""
        self.clear()
        boundary_shown = False
        for entry in entries:
            after_baseline = (
                baseline is not None and entry.version is not None and entry.version > baseline[0]
            )
            if baseline is not None and not after_baseline and not boundary_shown:
                boundary = self._add_spanned_row(f"── {baseline[1]} 시점 (버전 {baseline[0]}) ──")
                # 고를 일이 없는 구분선이라 흐리게 둔다.
                boundary.setDisabled(True)
                boundary_shown = True
            version_row = self._add_spanned_row(self._version_text(entry, current_version, after_baseline))
            version_row.setToolTip(0, entry.modified_at)
            font = version_row.font(0)
            font.setBold(True)
            version_row.setFont(0, font)
            if not entry.changes:
                child = QTreeWidgetItem([entry.change_summary or "바뀐 필드 정보가 없습니다."])
                version_row.addChild(child)
                child.setFirstColumnSpanned(True)
            for change in entry.changes:
                values = [
                    change.field_name,
                    display_tracker_value(change.old_value),
                    display_tracker_value(change.new_value),
                ]
                child = QTreeWidgetItem([_short(value, MAX_CELL_TEXT) for value in values])
                for column, value in enumerate(values):
                    child.setToolTip(column, _short(value, MAX_TOOLTIP_TEXT))
                version_row.addChild(child)
        self.expandAll()

    def _add_spanned_row(self, text: str) -> QTreeWidgetItem:
        row = QTreeWidgetItem([text])
        self.addTopLevelItem(row)
        row.setFirstColumnSpanned(True)
        return row

    @staticmethod
    def _version_text(entry: ItemHistoryEntry, current_version: int | None, after_baseline: bool) -> str:
        version = f"버전 {entry.version}" if entry.version is not None else "버전 정보 없음"
        if entry.version is not None and entry.version == current_version:
            version += " (현재)"
        parts = [version, history_time_text(entry.modified_at), entry.modified_by]
        if entry.changes:
            parts.append(f"필드 {len(entry.changes)}개")
        text = " · ".join(part for part in parts if part)
        return f"[Baseline 이후] {text}" if after_baseline else text
