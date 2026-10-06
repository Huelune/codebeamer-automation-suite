from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.gui.workspace_favorites import MAX_FAVORITE_ITEMS
from src.gui.workspace_favorites import TEST_MODE_FAVORITES_KEY
from src.gui.workspace_favorites import FavoriteItem
from src.gui.workspace_favorites import FavoriteTracker
from src.gui.workspace_favorites import WorkspaceFavorites
from src.gui.workspace_favorites import favorites_key
from src.gui.workspace_favorites import normalized_favorites_by_server


class WorkspaceFavoritesTest(unittest.TestCase):
    def test_key_separates_servers_users_and_test_mode(self) -> None:
        def settings(**values):
            return SimpleNamespace(**{"offline_mode": False, "base_url": "", "username": "", **values})

        self.assertEqual(
            favorites_key(settings(base_url=" https://example.test/cb/ ", username=" sample ")),
            "https://example.test/cb|sample",
        )
        self.assertNotEqual(
            favorites_key(settings(base_url="https://example.test/cb", username="sample")),
            favorites_key(settings(base_url="https://example.test/cb", username="other")),
        )
        self.assertEqual(
            favorites_key(settings(offline_mode=True, base_url="https://example.test/cb")),
            TEST_MODE_FAVORITES_KEY,
        )

    def test_payload_keeps_valid_unique_entries_in_order(self) -> None:
        favorites = WorkspaceFavorites.from_payload(
            {
                "items": [
                    {"item_id": 9001002, "name": "Brake", "tracker_name": "Requirements"},
                    {"item_id": "bad"},
                    {"item_id": 9001002, "name": "Duplicate"},
                    {"item_id": 9001001},
                    "not a mapping",
                ],
                "trackers": [
                    {"tracker_id": 24680001, "project_id": 246800, "name": "Requirements"},
                    {"tracker_id": 24680002},
                ],
            }
        )

        self.assertEqual([item.item_id for item in favorites.items], [9001002, 9001001])
        self.assertEqual(favorites.items[0].name, "Brake")
        self.assertEqual([tracker.tracker_id for tracker in favorites.trackers], [24680001])
        self.assertEqual(WorkspaceFavorites.from_payload(favorites.to_payload()), favorites)
        self.assertEqual(WorkspaceFavorites.from_payload(None), WorkspaceFavorites())

    def test_added_items_go_first_and_names_update_in_place(self) -> None:
        favorites = (
            WorkspaceFavorites()
            .with_item(FavoriteItem(1, "First"))
            .with_item(FavoriteItem(2, "Second"))
            .with_tracker(FavoriteTracker(20, 10, "Tracker"))
        )

        self.assertEqual([item.item_id for item in favorites.items], [2, 1])
        # 다시 추가하면 앞으로 옮기고, 이름만 바꾸면 자리를 그대로 둔다.
        self.assertEqual([item.item_id for item in favorites.with_item(FavoriteItem(1)).items], [1, 2])
        renamed = favorites.renamed_item(FavoriteItem(1, "Renamed", "Requirements"))
        self.assertEqual([item.name for item in renamed.items], ["Second", "Renamed"])
        self.assertEqual(favorites.renamed_item(FavoriteItem(3, "Unknown")), favorites)
        self.assertFalse(favorites.without_item(2).has_item(2))
        self.assertTrue(favorites.without_tracker(20).trackers == ())
        self.assertTrue(WorkspaceFavorites().is_empty())

    def test_item_count_is_capped(self) -> None:
        favorites = WorkspaceFavorites()
        for item_id in range(1, MAX_FAVORITE_ITEMS + 3):
            favorites = favorites.with_item(FavoriteItem(item_id))

        self.assertEqual(len(favorites.items), MAX_FAVORITE_ITEMS)
        self.assertEqual(favorites.items[0].item_id, MAX_FAVORITE_ITEMS + 2)
        self.assertFalse(favorites.has_item(1))

    def test_servers_without_favorites_are_dropped(self) -> None:
        self.assertEqual(
            normalized_favorites_by_server(
                {
                    "https://example.test/cb|sample": {"items": [{"item_id": 1}]},
                    "https://example.test/cb|empty": {"items": []},
                    "": {"items": [{"item_id": 2}]},
                    "broken": "not a mapping",
                }
            ),
            {
                "https://example.test/cb|sample": {
                    "items": [{"item_id": 1, "name": "", "tracker_name": "", "project_name": ""}],
                    "trackers": [],
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
