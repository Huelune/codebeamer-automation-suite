"""작업 공간 화면의 즐겨찾기 추가·열기·표시 테스트. 즐겨찾기 모델은 test_gui_workspace_favorites.py가 본다."""

from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from src.gui.tracker_favorites_panel import UNAVAILABLE_TEXT
from src.gui.workspace_favorites import TEST_MODE_FAVORITES_KEY
from src.gui.workspace_favorites import FavoriteItem
from src.gui.workspace_favorites import WorkspaceFavorites
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401
from tests.tracker_workspace_fixtures import TrackerWorkspaceTestCase


class TrackerWorkspaceFavoritesPanelTest(TrackerWorkspaceTestCase):
    def test_item_favorites_are_added_from_the_detail_and_opened_from_the_tab(self) -> None:
        page, saved, _holder = self._favorites_page()
        tree = page.hierarchy_panel.item_tree
        tree.setCurrentItem(tree.topLevelItem(0))
        self._app.processEvents()
        star = page.detail_panel.detail_favorite_button
        self.assertTrue(star.isEnabled())
        self.assertEqual(star.text(), "☆")

        star.click()

        key, favorites = saved[-1]
        self.assertEqual(key, TEST_MODE_FAVORITES_KEY)
        self.assertEqual(
            favorites.items[0],
            FavoriteItem(9001001, "Vehicle requirements", "Offline Requirements", "Offline Vehicle Project"),
        )
        self.assertEqual(star.text(), "★")
        table = page.favorites_panel.item_table
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(
            [table.item(0, column).text() for column in range(3)],
            ["Vehicle requirements", "9001001", "Offline Requirements"],
        )

        # 다른 아이템을 보다가 즐겨찾기 탭에서 연다. 한 번 누르면 고르기만 한다.
        page.search_panel.search_table.clearSelection()
        page.detail_panel.reset_detail()
        page.browser_tabs.setCurrentWidget(page.favorites_panel)
        self._app.processEvents()
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=self._favorite_cell(table, 0))
        self.assertIsNone(page.detail_panel.current_detail)
        self.assertTrue(page.favorites_panel.open_button.isEnabled())

        QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=self._favorite_cell(table, 0))
        self._app.processEvents()

        self.assertEqual(page.detail_panel.current_detail.item_id, 9001001)
        self.assertIs(page.browser_tabs.currentWidget(), page.hierarchy_panel)
        self.assertEqual(page.detail_panel.detail_favorite_button.text(), "★")

        page.browser_tabs.setCurrentWidget(page.favorites_panel)
        table.setFocus()
        table.selectRow(0)
        page.detail_panel.reset_detail()
        QTest.keyClick(table, Qt.Key.Key_Return)
        self._app.processEvents()
        self.assertEqual(page.detail_panel.current_detail.item_id, 9001001)

        page.browser_tabs.setCurrentWidget(page.favorites_panel)
        table.selectRow(0)
        page.favorites_panel.remove_button.click()

        self.assertEqual(table.rowCount(), 0)
        self.assertTrue(saved[-1][1].is_empty())
        self.assertEqual(page.detail_panel.detail_favorite_button.text(), "☆")
        self.assertTrue(page.favorites_panel.hint_label.isVisibleTo(page.favorites_panel))

    def test_tracker_favorites_are_pinned_on_top_and_listed_in_the_tab(self) -> None:
        page, saved, _holder = self._favorites_page()
        combo = page.tracker_combo
        button = page.tracker_favorite_button
        self.assertEqual(page._current_tracker.tracker_id, 24680001)
        self.assertTrue(button.isEnabled())

        # 다른 트래커를 고정하면 콤보 맨 위에 ★로 둔다.
        test_cases = combo.findData(24680002)
        combo.setCurrentIndex(test_cases)
        page._on_tracker_activated(test_cases)
        self._app.processEvents()
        button.click()

        self.assertEqual(saved[-1][1].trackers[0].tracker_id, 24680002)
        self.assertEqual(combo.itemData(0), 24680002)
        self.assertTrue(combo.itemText(0).startswith("★ Offline Test Cases"))
        self.assertEqual(combo.currentData(), 24680002)
        self.assertEqual(button.text(), "★")
        table = page.favorites_panel.tracker_table
        self.assertEqual(
            [table.item(0, column).text() for column in range(2)],
            ["Offline Test Cases", "Offline Vehicle Project"],
        )

        # 다른 트래커를 보다가 탭에서 고정 트래커를 연다.
        requirements = combo.findData(24680001)
        combo.setCurrentIndex(requirements)
        page._on_tracker_activated(requirements)
        self._app.processEvents()
        self.assertEqual(button.text(), "☆")
        page.browser_tabs.setCurrentWidget(page.favorites_panel)
        table.selectRow(0)
        page.favorites_panel.open_button.click()
        self._app.processEvents()

        self.assertEqual(page._current_tracker.tracker_id, 24680002)
        self.assertIs(page.browser_tabs.currentWidget(), page.hierarchy_panel)

        button.click()

        self.assertEqual(saved[-1][1].trackers, ())
        self.assertFalse(combo.itemText(combo.findData(24680002)).startswith("★"))
        self.assertEqual(combo.currentData(), 24680002)

    def test_favorites_that_cannot_be_opened_are_marked_and_names_follow_the_item(self) -> None:
        stored = WorkspaceFavorites().with_item(FavoriteItem(99999999, "Removed item")).with_item(
            FavoriteItem(9001001, "Old name", "Old tracker")
        )
        page, saved, _holder = self._favorites_page({TEST_MODE_FAVORITES_KEY: stored.to_payload()})
        panel = page.favorites_panel
        table = panel.item_table
        self.assertEqual(table.item(0, 0).text(), "Old name")

        page.browser_tabs.setCurrentWidget(panel)
        table.selectRow(1)
        panel.open_button.click()
        self._app.processEvents()

        self.assertEqual(table.item(1, 2).text(), UNAVAILABLE_TEXT)
        self.assertEqual(saved, [])

        page.browser_tabs.setCurrentWidget(panel)
        table.selectRow(0)
        panel.open_button.click()
        self._app.processEvents()

        # 열린 아이템의 지금 이름으로 목록을 맞추고, 자리는 그대로 둔다.
        self.assertEqual(table.item(0, 0).text(), "Vehicle requirements")
        self.assertEqual(table.item(0, 2).text(), "Offline Requirements")
        self.assertEqual([item.item_id for item in saved[-1][1].items], [9001001, 99999999])
        self.assertEqual(table.item(1, 2).text(), UNAVAILABLE_TEXT)

    def test_applying_settings_reloads_favorites(self) -> None:
        page, _saved, holder = self._favorites_page()
        self.assertEqual(page.favorites_panel.item_table.rowCount(), 0)
        holder["value"] = {
            TEST_MODE_FAVORITES_KEY: WorkspaceFavorites().with_item(FavoriteItem(9001002, "Brake system")).to_payload()
        }

        page.on_settings_applied()
        self._app.processEvents()

        self.assertEqual(page.favorites_panel.item_table.item(0, 0).text(), "Brake system")


if __name__ == "__main__":
    unittest.main()
