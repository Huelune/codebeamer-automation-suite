from __future__ import annotations


try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QImage
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QDialog
    from PySide6.QtWidgets import QDialogButtonBox
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QTextBrowser
    from PySide6.QtWidgets import QVBoxLayout
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .tracker_content_models import AttachmentResource
from .tracker_content_models import WikiRenderResult


class WikiContentView(QTextBrowser):
    """원격 네트워크 로딩 없이 정제된 Wiki HTML과 로컬 이미지만 표시한다."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self._result: WikiRenderResult | None = None
        self._source_html = ""

    def setHtml(self, text: str) -> None:
        self._source_html = str(text or "")
        super().setHtml(self._source_html)

    def set_render_result(self, result: WikiRenderResult) -> None:
        self._result = result
        self.setHtml(result.html)

    def text(self) -> str:
        """기존 QLabel 기반 Wiki cell 테스트·호출부와 호환되는 HTML accessor."""
        return self._source_html

    def add_attachment_resource(self, resource: AttachmentResource) -> bool:
        image = QImage.fromData(resource.data)
        if image.isNull():
            return False
        url = QUrl(f"cb-attachment://{resource.resource_key}")
        self.document().addResource(QTextDocument.ResourceType.ImageResource, url, image)
        self.viewport().update()
        return True


class WikiContentDialog(QDialog):
    def __init__(self, title: str, source: str, result: WikiRenderResult, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(str(title or "Wiki 내용"))
        self.setMinimumSize(720, 440)
        self.resize(920, 620)
        layout = QVBoxLayout(self)
        if result.warning:
            warning = QLabel(result.warning, self)
            warning.setWordWrap(True)
            warning.setObjectName("tracker_detail_warning")
            layout.addWidget(warning)
        self.view = WikiContentView(self)
        self.view.set_render_result(result)
        self.view.setProperty("wikiSource", str(source or ""))
        layout.addWidget(self.view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText("닫기")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


__all__ = ["WikiContentDialog", "WikiContentView"]
