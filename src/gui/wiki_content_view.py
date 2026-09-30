from __future__ import annotations

from typing import Any
from urllib.parse import unquote


try:
    from PySide6.QtCore import QRect
    from PySide6.QtCore import Qt
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtGui import QImage
    from PySide6.QtGui import QPainter
    from PySide6.QtGui import QPalette
    from PySide6.QtGui import QTextCursor
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


ATTACHMENT_SCHEME = "cb-attachment"


class WikiContentView(QTextBrowser):
    """원격 네트워크 로딩 없이 정제된 Wiki HTML과 로컬 이미지만 표시한다."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        # 기본값이면 링크를 누를 때 이 칸이 그 주소로 이동하려다 내용이 통째로 사라진다.
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._open_link)
        # 그림 폭을 맞추는 편집이 되돌리기 기록에 쌓이지 않게 한다.
        self.document().setUndoRedoEnabled(False)
        self._result: WikiRenderResult | None = None
        self._source_html = ""
        # 받은 그림의 원본. 칸 폭이 바뀌면 이 크기를 기준으로 다시 맞춘다.
        self._images: dict[str, QImage] = {}

    def setHtml(self, text: str) -> None:
        self._source_html = str(text or "")
        super().setHtml(self._source_html)
        # 문서 리소스는 HTML을 바꿔도 남으므로 새 문서의 그림 폭만 다시 맞춘다.
        self._fit_images()

    def set_render_result(self, result: WikiRenderResult) -> None:
        self._result = result
        self.setHtml(result.html)

    def text(self) -> str:
        """기존 QLabel 기반 Wiki cell 테스트·호출부와 호환되는 HTML accessor."""
        return self._source_html

    def clear(self) -> None:
        self._images.clear()
        super().clear()

    def _open_link(self, url: QUrl) -> None:
        """웹 주소는 기본 브라우저로 연다. 그 밖의 주소는 이 칸에서 열지 않는다."""
        if url.scheme().casefold() in {"http", "https"}:
            QDesktopServices.openUrl(url)

    def add_attachment_resource(self, resource: AttachmentResource) -> bool:
        url = QUrl(f"{ATTACHMENT_SCHEME}://{resource.resource_key}")
        image = QImage.fromData(resource.data)
        document = self.document()
        if image.isNull():
            # 너무 크거나 깨진 그림은 Qt가 거절한다. 조용히 사라지지 않게 이유를 남긴다.
            document.addResource(
                QTextDocument.ResourceType.ImageResource,
                url,
                self._placeholder_image(url, "크기나 형식 때문에 표시할 수 없습니다"),
            )
            self._relayout()
            return False
        self._images[url.toString()] = image
        document.addResource(QTextDocument.ResourceType.ImageResource, url, image)
        self._fit_images()
        # 이미 배치한 문서에 늦게 도착한 그림은 다시 배치하지 않으면 글자 위에 겹쳐 그려진다.
        self._relayout()
        return True

    def loadResource(self, resource_type: int, name: QUrl | str) -> Any:
        """아직 받지 못했거나 찾지 못한 첨부 그림 자리에 파일 이름을 보여 준다."""
        url = QUrl(name) if isinstance(name, str) else name
        if (
            getattr(resource_type, "value", resource_type)
            == QTextDocument.ResourceType.ImageResource.value
            and url.scheme() == ATTACHMENT_SCHEME
        ):
            return self._placeholder_image(url, "")
        return super().loadResource(resource_type, name)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._images:
            self._fit_images()

    def _relayout(self) -> None:
        document = self.document()
        document.markContentsDirty(0, document.characterCount())
        self.viewport().update()

    def _fit_images(self) -> None:
        """칸보다 넓은 그림은 칸 폭에 맞춰 그린다. 원본 크기는 크게 보기 창에서 본다."""
        if not self._images:
            return
        limit = self._image_width_limit()
        pending = []
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                iterator += 1
                char_format = fragment.charFormat()
                if not char_format.isImageFormat():
                    continue
                image_format = char_format.toImageFormat()
                image = self._images.get(QUrl(image_format.name()).toString())
                if image is None or image.width() <= 0:
                    continue
                width = min(image.width(), limit)
                if abs(image_format.width() - width) >= 0.5:
                    image_format.setWidth(width)
                    image_format.setHeight(image.height() * width / image.width())
                    pending.append((fragment.position(), fragment.length(), image_format))
            block = block.next()
        # 순회 중에 서식을 바꾸면 조각이 쪼개지므로 모아 두었다가 한 번에 바꾼다.
        cursor = QTextCursor(self.document())
        for position, length, image_format in pending:
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(image_format)

    def _image_width_limit(self) -> int:
        margin = int(self.document().documentMargin())
        return max(self.viewport().width() - margin * 2 - 8, 64)

    def _placeholder_image(self, url: QUrl, reason: str) -> QImage:
        name = ""
        if url.host() == "wiki-image":
            parts = [part for part in url.path(QUrl.ComponentFormattingOption.FullyEncoded).split("/") if part]
            name = unquote(parts[0]) if parts else ""
        text = " · ".join(value for value in (f"[이미지] {name}".strip(), reason) if value)
        metrics = QFontMetrics(self.font())
        # 자리 표시가 칸보다 넓으면 가로 스크롤이 생기므로 가운데를 줄인다.
        text = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, self._image_width_limit() - 16)
        width = metrics.horizontalAdvance(text) + 16
        height = metrics.height() + 10
        ratio = max(self.devicePixelRatioF(), 1.0)
        image = QImage(int(width * ratio), int(height * ratio), QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        palette = self.palette()
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawRect(QRect(0, 0, width - 1, height - 1))
        painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
        painter.setFont(self.font())
        painter.drawText(QRect(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return image


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
