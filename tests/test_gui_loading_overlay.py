from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QWidget

from src.gui.loading_overlay import LoadingOverlay


class LoadingOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.parent = QWidget()
        self.parent.resize(720, 480)
        self.button = QPushButton("다른 작업", self.parent)
        self.overlay = LoadingOverlay(self.parent)
        self.parent.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.parent.close()
        self._app.processEvents()

    def test_start_covers_parent_and_runs_spinner(self) -> None:
        token = self.overlay.start("프로젝트를 불러오는 중입니다.")
        self._app.processEvents()

        self.assertTrue(self.overlay.isVisible())
        self.assertEqual(self.overlay.geometry(), self.parent.rect())
        self.assertEqual(self.overlay.active_count, 1)
        self.assertEqual(
            self.overlay.message_label.text(),
            "프로젝트를 불러오는 중입니다.",
        )
        self.assertTrue(self.overlay.spinner._timer.isActive())
        self.assertIs(self._app.widgetAt(self.button.mapToGlobal(self.button.rect().center())), self.overlay)

        self.overlay.finish(token)
        self._app.processEvents()

        self.assertFalse(self.overlay.isVisible())
        self.assertFalse(self.overlay.spinner._timer.isActive())

    def test_nested_tasks_keep_overlay_until_last_token_finishes(self) -> None:
        first = self.overlay.start("프로젝트를 불러오는 중입니다.")
        second = self.overlay.start("트래커를 불러오는 중입니다.")

        self.assertEqual(self.overlay.active_count, 2)
        self.assertEqual(
            self.overlay.message_label.text(),
            "트래커를 불러오는 중입니다.",
        )

        self.overlay.finish(second)
        self.assertTrue(self.overlay.isVisible())
        self.assertEqual(self.overlay.active_count, 1)
        self.assertEqual(
            self.overlay.message_label.text(),
            "프로젝트를 불러오는 중입니다.",
        )

        self.overlay.finish(first)
        self.assertFalse(self.overlay.isVisible())
        self.assertEqual(self.overlay.active_count, 0)

    def test_sync_geometry_follows_parent_resize(self) -> None:
        token = self.overlay.start()
        self.parent.resize(960, 640)
        self.overlay.sync_geometry()

        self.assertEqual(self.overlay.size(), self.parent.size())

        self.overlay.finish(token)


if __name__ == "__main__":
    unittest.main()
