from __future__ import annotations

import os
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer
from PySide6.QtCore import QByteArray
from PySide6.QtCore import QIODevice
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtGui import QImage
from PySide6.QtGui import QTextDocument

from src.gui.tracker_content_models import AttachmentResource
from src.gui.wiki_content_view import WikiContentView
from src.gui.wiki_renderer import codebeamer_wiki_to_html
from src.gui.wiki_renderer import wiki_image_resource_key
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


IMAGE_NAME = "Primary Architecture.png"
IMAGE_HASH = "a114e08877977d75cfac6aade92755cb"


def png_bytes(width: int, height: int) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


class WikiContentViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.view = WikiContentView()
        self.view.resize(520, 420)
        self.view.show()
        self.addCleanup(self.view.close)
        self._app.processEvents()
        self.key = wiki_image_resource_key(IMAGE_NAME, IMAGE_HASH)
        self.view.setHtml(
            codebeamer_wiki_to_html(f"before\n[!{IMAGE_NAME}#{IMAGE_HASH}!]\nafter")
        )
        self._app.processEvents()

    def _resource(self, key: str) -> object:
        return self.view.document().resource(
            QTextDocument.ResourceType.ImageResource,
            QUrl(f"cb-attachment://{key}"),
        )

    def test_image_arriving_after_layout_is_laid_out_in_place(self) -> None:
        """늦게 도착한 그림을 다시 배치하지 않으면 글자 위에 겹쳐 그려진다."""
        height_before = self.view.document().size().height()

        added = self.view.add_attachment_resource(
            AttachmentResource(self.key, "image/png", png_bytes(300, 200))
        )
        self._app.processEvents()

        self.assertTrue(added)
        self.assertGreaterEqual(self.view.document().size().height(), height_before + 150)

    def test_wide_image_fits_the_view_and_follows_resizing(self) -> None:
        self.view.add_attachment_resource(
            AttachmentResource(self.key, "image/png", png_bytes(1600, 400))
        )
        self._app.processEvents()
        self.assertLessEqual(
            self.view.document().size().width(),
            self.view.viewport().width() + 1,
        )
        narrow_height = self.view.document().size().height()

        self.view.resize(900, 420)
        self._app.processEvents()

        self.assertGreater(self.view.document().size().height(), narrow_height)
        self.assertLessEqual(
            self.view.document().size().width(),
            self.view.viewport().width() + 1,
        )

    def test_image_survives_rerendering_the_same_html(self) -> None:
        """원문 보기에서 렌더링 보기로 돌아와도 받은 그림을 다시 받지 않는다."""
        self.view.add_attachment_resource(
            AttachmentResource(self.key, "image/png", png_bytes(300, 200))
        )
        self._app.processEvents()
        laid_out = self.view.document().size().height()

        rendered = self.view.text()
        self.view.setPlainText("source")
        self.view.setHtml(rendered)
        self._app.processEvents()

        self.assertGreaterEqual(self.view.document().size().height(), laid_out - 40)

    def test_missing_and_undecodable_images_get_a_visible_placeholder(self) -> None:
        """받기 전이나 못 찾은 그림은 파일 이름, 그리지 못한 그림은 이유까지 보여 준다."""
        waiting = self._resource(self.key)
        self.assertIsInstance(waiting, QImage)
        self.assertFalse(waiting.isNull())

        added = self.view.add_attachment_resource(
            AttachmentResource(self.key, "image/png", b"not an image")
        )

        self.assertFalse(added)
        rejected = self._resource(self.key)
        self.assertIsInstance(rejected, QImage)
        self.assertFalse(rejected.isNull())
        self.assertGreater(rejected.width(), waiting.width())

    def test_clicking_a_link_keeps_the_content_and_opens_web_links_in_the_browser(self) -> None:
        """링크를 누르면 칸이 그 주소로 이동하며 내용이 사라지던 문제를 막는다."""
        self.view.setHtml('<p>본문 <a href="https://example.test/doc">링크</a> 끝</p>')

        with patch("src.gui.wiki_content_view.QDesktopServices.openUrl") as open_url:
            self.view.anchorClicked.emit(QUrl("https://example.test/doc"))
            self.view.anchorClicked.emit(QUrl("/cb/issue/1234"))
        self._app.processEvents()

        self.assertEqual(self.view.toPlainText(), "본문 링크 끝")
        open_url.assert_called_once_with(QUrl("https://example.test/doc"))

    def test_codebeamer_links_are_handed_to_the_screen_and_explained_on_hover(self) -> None:
        activated: list[tuple[str, int, str]] = []
        self.view.codebeamer_link_activated.connect(
            lambda kind, target_id, name: activated.append((kind, target_id, name))
        )

        with patch("src.gui.wiki_content_view.QDesktopServices.openUrl") as open_url:
            self.view.anchorClicked.emit(QUrl("cb-link:item/1234"))
            self.view.anchorClicked.emit(QUrl("cb-link:attachment/111111/AA_BB 계획.docx"))

        self.assertEqual(
            activated,
            [("item", 1234, ""), ("attachment", 111111, "AA_BB 계획.docx")],
        )
        open_url.assert_not_called()
        self.view.highlighted.emit(QUrl("cb-link:item/1234"))
        self.assertEqual(self.view.toolTip(), "아이템 #1234 열기")
        self.view.highlighted.emit(QUrl("cb-link:attachment/111111/AA_BB 계획.docx"))
        self.assertEqual(self.view.toolTip(), "첨부 저장 · AA_BB 계획.docx")
        self.view.highlighted.emit(QUrl())
        self.assertEqual(self.view.toolTip(), "")

    def test_clear_drops_downloaded_images(self) -> None:
        self.view.add_attachment_resource(
            AttachmentResource(self.key, "image/png", png_bytes(10, 10))
        )

        self.view.clear()

        self.assertEqual(self.view._images, {})


if __name__ == "__main__":
    unittest.main()
