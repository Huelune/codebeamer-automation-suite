from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QPointF
from PySide6.QtCore import QRectF
from PySide6.QtCore import QSize
from PySide6.QtCore import Qt
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtGui import QPainter
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtWidgets import QVBoxLayout
from PySide6.QtWidgets import QWidget


class LoadingSpinner(QWidget):
    """애니메이션 프레임 이미지 없이 그리는 회전형 로딩 표시다."""

    def __init__(self, parent=None, *, line_count: int = 12) -> None:
        super().__init__(parent)
        self.setObjectName("loading_spinner")
        self.setAccessibleName("작업 진행 중")
        self._line_count = max(int(line_count), 8)
        self._rotation_step = 0
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)
        self.setFixedSize(42, 42)

    def sizeHint(self) -> QSize:
        return QSize(42, 42)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._rotation_step = (self._rotation_step + 1) % self._line_count
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(QPointF(self.width() / 2.0, self.height() / 2.0))

        radius = min(self.width(), self.height()) * 0.32
        segment_length = min(self.width(), self.height()) * 0.16
        line_width = max(2.0, min(self.width(), self.height()) * 0.075)
        base_color = self.palette().highlight().color()
        if not base_color.isValid():
            base_color = QColor("#00A7D6")

        for index in range(self._line_count):
            distance = (index - self._rotation_step) % self._line_count
            opacity = max(0.16, 1.0 - (distance / self._line_count))
            color = QColor(base_color)
            color.setAlphaF(opacity)
            pen = QPen(color, line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(0.0, -radius),
                QPointF(0.0, -(radius + segment_length)),
            )
            painter.rotate(360.0 / self._line_count)


class LoadingOverlay(QWidget):
    """활성 작업이 끝날 때까지 부모 영역의 입력을 차단하는 로딩 오버레이다."""

    def __init__(self, parent: QWidget, *, title: str = "작업 중") -> None:
        super().__init__(parent)
        self.setObjectName("busy_overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.WaitCursor)
        self._requests: OrderedDict[int, str] = OrderedDict()
        self._next_token = 0
        self._previous_focus: QWidget | None = None

        overlay_layout = QVBoxLayout(self)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame(self)
        card.setObjectName("busy_card")
        card.setMinimumWidth(340)
        card.setMaximumWidth(480)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        card_layout.setSpacing(10)

        spinner_row = QHBoxLayout()
        spinner_row.addStretch(1)
        self.spinner = LoadingSpinner(card)
        spinner_row.addWidget(self.spinner)
        spinner_row.addStretch(1)

        self.title_label = QLabel(title, card)
        self.title_label.setObjectName("busy_title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label = QLabel("잠시만 기다려 주세요.", card)
        self.message_label.setObjectName("busy_message")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumWidth(260)
        self.message_label.setMaximumWidth(420)

        card_layout.addLayout(spinner_row)
        card_layout.addWidget(self.title_label)
        card_layout.addWidget(
            self.message_label,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        overlay_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self.hide()

    @property
    def active_count(self) -> int:
        return len(self._requests)

    @property
    def is_active(self) -> bool:
        return bool(self._requests)

    def start(self, message: str = "") -> int:
        self._next_token += 1
        token = self._next_token
        normalized_message = str(message or "잠시만 기다려 주세요.").strip()
        self._requests[token] = normalized_message
        self.message_label.setText(normalized_message)
        if self.active_count == 1:
            self._previous_focus = QApplication.focusWidget()
        self.sync_geometry()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        return token

    def finish(self, token: int | None) -> None:
        if token is None:
            return
        self._requests.pop(int(token), None)
        if self._requests:
            self.message_label.setText(next(reversed(self._requests.values())))
            self.raise_()
            return
        self.hide()
        previous_focus = self._previous_focus
        self._previous_focus = None
        if previous_focus is not None and previous_focus.isVisible():
            previous_focus.setFocus(Qt.FocusReason.OtherFocusReason)

    def clear(self) -> None:
        self._requests.clear()
        self._previous_focus = None
        self.hide()

    def sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(QRectF(parent.rect()).toRect())
        self.raise_()

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        event.accept()

    def wheelEvent(self, event) -> None:
        event.accept()

    def keyPressEvent(self, event) -> None:
        event.accept()

    def keyReleaseEvent(self, event) -> None:
        event.accept()


__all__ = ["LoadingOverlay", "LoadingSpinner"]
