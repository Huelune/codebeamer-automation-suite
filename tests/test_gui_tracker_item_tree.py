from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.styles import GUI_THEME_LABELS
from src.gui.styles import build_gui_stylesheet
from src.gui.tracker_item_tree import TrackerItemTree
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class TrackerItemTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _nested_tree(self):
        from PySide6.QtWidgets import QTreeWidgetItem

        tree = TrackerItemTree()
        tree.resize(420, 240)
        root = QTreeWidgetItem(["Root summary", "1001"])
        child = QTreeWidgetItem(["Child summary", "1002"])
        grandchild = QTreeWidgetItem(["Grandchild summary", "1003"])
        root.addChild(child)
        child.addChild(grandchild)
        tree.addTopLevelItem(root)
        tree.expandAll()
        self.addCleanup(tree.deleteLater)
        return tree, root, child, grandchild

    def test_summary_is_the_indented_first_column_and_id_follows(self) -> None:
        from PySide6.QtWidgets import QHeaderView

        tree, _root, _child, _grandchild = self._nested_tree()
        header = tree.header()

        self.assertEqual(tree.objectName(), "tracker_item_tree")
        self.assertEqual([tree.headerItem().text(column) for column in range(2)], ["요약", "ID"])
        self.assertEqual(header.sectionResizeMode(0), QHeaderView.ResizeMode.Stretch)
        self.assertEqual(header.sectionResizeMode(1), QHeaderView.ResizeMode.ResizeToContents)

    def test_guides_are_drawn_under_each_ancestor_arrow(self) -> None:
        from PySide6.QtGui import QColor

        tree, root, child, grandchild = self._nested_tree()
        tree.guide_color = QColor("#FF0000")
        tree.show()
        self._app.processEvents()
        image = tree.viewport().grab().toImage()
        indent = tree.indentation()

        def is_guide(item, level: int) -> bool:
            # 연결선 칸 가운데를 본다. 화살표가 있는 칸에는 연결선이 없다.
            y = tree.visualItemRect(item).center().y()
            return image.pixelColor(level * indent + indent // 2, y) == QColor("#FF0000")

        self.assertFalse(is_guide(root, 0))
        self.assertTrue(is_guide(child, 0))
        self.assertFalse(is_guide(child, 1))
        self.assertTrue(is_guide(grandchild, 0))
        self.assertTrue(is_guide(grandchild, 1))

    def test_each_theme_sets_its_own_guide_color(self) -> None:
        colors = {}
        for theme in GUI_THEME_LABELS:
            tree = TrackerItemTree()
            self.addCleanup(tree.deleteLater)
            tree.setStyleSheet(build_gui_stylesheet(theme))
            tree.ensurePolished()
            colors[theme] = tree.guide_color.name()

        self.assertEqual(colors, {"kefico": "#c3d1de", "igloo": "#b5d6d9"})


if __name__ == "__main__":
    unittest.main()
