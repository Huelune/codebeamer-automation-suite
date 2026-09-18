from __future__ import annotations


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QVBoxLayout
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_item_editor_panel import TrackerItemEditorPanel


class TrackerItemEditorDialog(QDialog):
    """작업 중인 수정 panel을 상태 손실 없이 큰 창에 표시한다."""

    def __init__(
        self,
        panel: TrackerItemEditorPanel,
        *,
        title: str = "트래커 아이템 수정",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.panel: TrackerItemEditorPanel | None = panel

        self.setObjectName("tracker_item_editor_dialog")
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setModal(False)
        self.setMinimumSize(760, 540)
        self.resize(1100, 760)

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(14, 12, 14, 14)
        self.root_layout.setSpacing(8)

        heading = QHBoxLayout()
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("tracker_detail_title")
        heading.addWidget(self.title_label, 1)
        self.fullscreen_button = QPushButton("전체 화면", self)
        self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.toggled.connect(self._set_fullscreen)
        heading.addWidget(self.fullscreen_button)
        self.close_button = QPushButton("작업공간으로 돌아가기", self)
        self.close_button.clicked.connect(self.close)
        heading.addWidget(self.close_button)
        self.root_layout.addLayout(heading)
        self.root_layout.addWidget(panel, 1)

    def take_panel(self) -> TrackerItemEditorPanel | None:
        panel = self.panel
        if panel is not None:
            self.root_layout.removeWidget(panel)
            self.panel = None
        return panel

    def _set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_button.setText("창 모드" if enabled else "전체 화면")
        if enabled:
            self.showFullScreen()
            return
        self.showNormal()


__all__ = ["TrackerItemEditorDialog"]
