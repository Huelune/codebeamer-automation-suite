"""`트래커 작업공간` 화면과 Baseline 패널이 함께 쓰는 작은 표시 helper.

표시용 정렬 셀, 색상 혼합, 단건 ID 조회 결과 컨테이너만 둔다.
화면 조립이나 조회 로직은 담지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


try:
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QTableWidgetItem
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_query_models import TrackerItemContext
from .tracker_query_models import TrackerItemSummary


@dataclass(frozen=True)
class DirectItemResult:
    context: TrackerItemContext
    ancestor_path: tuple[TrackerItemSummary, ...]


class SortableTableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value: Any) -> None:
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortableTableItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


def blend_colors(base: QColor, accent: QColor, ratio: float) -> QColor:
    clamped = max(0.0, min(float(ratio), 1.0))
    inverse = 1.0 - clamped
    return QColor(
        int(base.red() * inverse + accent.red() * clamped),
        int(base.green() * inverse + accent.green() * clamped),
        int(base.blue() * inverse + accent.blue() * clamped),
    )
