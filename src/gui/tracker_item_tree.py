"""트래커 아이템 계층 트리.

작업공간 계층 탭, Baseline 탭, 상세 창의 계층이 같은 트리를 쓴다.
들여쓰기는 첫 칸에만 적용되므로 요약을 첫 칸에, ID를 둘째 칸에 둔다.
상위 아이템마다 세로 연결선을 그어 깊은 계층에서도 같은 부모 아래 항목을 따라갈 수 있게 한다.
"""

from __future__ import annotations


try:
    from PySide6.QtCore import Property
    from PySide6.QtCore import QModelIndex
    from PySide6.QtCore import QPersistentModelIndex
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor
    from PySide6.QtGui import QPainter
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QTreeWidget
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc


class TrackerItemTree(QTreeWidget):
    """요약(첫 칸)·ID(둘째 칸) 계층 트리. 연결선 색은 테마의 `qproperty-guide_color`로 정한다."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._guide_color = self.palette().color(QPalette.ColorRole.Mid)
        self.setObjectName("tracker_item_tree")
        self.setColumnCount(2)
        self.setHeaderLabels(["요약", "ID"])
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setUniformRowHeights(True)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

    def _get_guide_color(self) -> QColor:
        return self._guide_color

    def _set_guide_color(self, color: QColor) -> None:
        self._guide_color = QColor(color)
        self.viewport().update()

    guide_color = Property(QColor, _get_guide_color, _set_guide_color)

    def drawBranches(
        self,
        painter: QPainter,
        rect: QRect,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """펼침 화살표 칸 앞의 상위 단계마다 세로선을 긋는다.

        선은 상위 아이템의 화살표 바로 아래에 오므로 그 아이템의 하위가 끝나는 곳까지 이어진다.
        """
        super().drawBranches(painter, rect, index)
        depth = 0
        parent = index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        if depth == 0:
            return
        indent = self.indentation()
        painter.save()
        painter.setPen(self._guide_color)
        for level in range(depth):
            x = rect.left() + level * indent + indent // 2
            painter.drawLine(x, rect.top(), x, rect.bottom())
        painter.restore()
