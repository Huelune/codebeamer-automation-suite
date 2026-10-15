"""아이템 활동 이력을 시간순으로 보여 주는 트리.

상세 창과 Baseline 비교의 변경 이력 탭이 활동 패널 안에서 함께 쓴다.
필드 변경은 버전 줄 아래에 필드별 이전 값·새 값을 두고, 댓글은 본문, 첨부는 파일명 한 줄로 보인다.
값은 Baseline 비교와 같은 방식으로 글자로 바꾼다.
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


import html
from collections.abc import Sequence

from .item_activity import BaselineMarker
from .item_activity import ItemActivityEntry
from .item_activity import ItemActivityKind
from .item_activity import is_after_baseline
from .tracker_baseline_compare import display_tracker_value


# 긴 설명이나 표 값은 칸에서 줄이고 툴팁으로 전체를 보인다.
MAX_CELL_TEXT = 300
MAX_TOOLTIP_TEXT = 4000


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def plain_tooltip(text: str) -> str:
    """서버 값을 툴팁에 글자 그대로 보인다. Qt는 HTML처럼 보이는 글을 서식으로 해석하므로 막는다."""
    if not text:
        # 빈 글을 <qt></qt>로 감싸면 내용 없는 툴팁 상자가 뜬다.
        return ""
    return "<qt>" + html.escape(str(text)).replace("\n", "<br>") + "</qt>"


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
        entries: Sequence[ItemActivityEntry],
        *,
        current_version: int | None = None,
        baseline: BaselineMarker | None = None,
    ) -> None:
        """최신부터 보인다. `baseline`이 있으면 Baseline 안쪽의 첫 항목 앞에 구분선을 넣는다."""
        self.clear()
        boundary_shown = False
        for entry in entries:
            after_baseline = baseline is not None and is_after_baseline(entry, baseline)
            if baseline is not None and not after_baseline and not boundary_shown:
                version = f" (버전 {baseline.version})" if baseline.version is not None else ""
                boundary = self._add_spanned_row(f"── {baseline.name} 시점{version} ──")
                # 고를 일이 없는 구분선이라 흐리게 둔다.
                boundary.setDisabled(True)
                boundary_shown = True
            text = self._entry_text(entry, current_version)
            row = self._add_spanned_row(f"[Baseline 이후] {text}" if after_baseline else text)
            row.setToolTip(0, plain_tooltip(entry.at))
            font = row.font(0)
            font.setBold(True)
            row.setFont(0, font)
            if entry.kind is ItemActivityKind.FIELD_CHANGE:
                self._add_field_rows(row, entry)
            elif entry.kind is ItemActivityKind.COMMENT:
                self._add_text_row(row, entry.body or "(본문 없음)")
                if entry.attachment_names:
                    self._add_text_row(row, "첨부: " + ", ".join(entry.attachment_names))
        self.expandAll()

    def _add_field_rows(self, row: QTreeWidgetItem, entry: ItemActivityEntry) -> None:
        if not entry.changes:
            self._add_text_row(row, entry.change_summary or "바뀐 필드 정보가 없습니다.")
            return
        for change in entry.changes:
            values = [
                change.field_name,
                display_tracker_value(change.old_value),
                display_tracker_value(change.new_value),
            ]
            child = QTreeWidgetItem([_short(value, MAX_CELL_TEXT) for value in values])
            for column, value in enumerate(values):
                child.setToolTip(column, plain_tooltip(_short(value, MAX_TOOLTIP_TEXT)))
            row.addChild(child)

    @staticmethod
    def _add_text_row(row: QTreeWidgetItem, text: str) -> None:
        child = QTreeWidgetItem([_short(text, MAX_CELL_TEXT)])
        child.setToolTip(0, plain_tooltip(_short(text, MAX_TOOLTIP_TEXT)))
        row.addChild(child)
        child.setFirstColumnSpanned(True)

    def _add_spanned_row(self, text: str) -> QTreeWidgetItem:
        row = QTreeWidgetItem([text])
        self.addTopLevelItem(row)
        row.setFirstColumnSpanned(True)
        return row

    @staticmethod
    def _entry_text(entry: ItemActivityEntry, current_version: int | None) -> str:
        time = history_time_text(entry.at)
        if entry.kind is ItemActivityKind.COMMENT:
            author = f"{entry.by} (수정됨)" if entry.edited and entry.by else entry.by
            parts = ["댓글", time, author]
        elif entry.kind is ItemActivityKind.ATTACHMENT:
            parts = ["첨부", time, entry.title, entry.body]
        else:
            version = f"버전 {entry.version}" if entry.version is not None else "버전 정보 없음"
            if entry.version is not None and entry.version == current_version:
                version += " (현재)"
            parts = [version, time, entry.by, f"필드 {len(entry.changes)}개" if entry.changes else ""]
        return " · ".join(part for part in parts if part)
