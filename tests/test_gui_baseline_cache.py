from __future__ import annotations

import gzip
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src.gui.baseline_cache import BaselineCacheKey
from src.gui.baseline_cache import BaselineItemCache
from src.gui.baseline_cache import describe_saved_at


def _key(baseline_id: int = 11, *, username: str = "sample_user") -> BaselineCacheKey:
    return BaselineCacheKey(
        base_url="https://example.test/cb/api",
        username=username,
        tracker_id=20,
        baseline_id=baseline_id,
        query="tracker.id = 20 | item.id ASC",
    )


class BaselineItemCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "baseline_cache"
        self.cache = BaselineItemCache(self.root)

    def test_saved_items_are_read_back_with_their_saved_time(self) -> None:
        items = [{"id": 1, "name": "첫 아이템", "tracker": {"id": 20}}]

        self.cache.save(_key(), items)
        entry = self.cache.load(_key())

        self.assertIsNotNone(entry)
        self.assertEqual(entry.items, items)
        self.assertTrue(entry.saved_at)
        # 압축해서 저장한다.
        files = list(self.root.glob("*.json.gz"))
        self.assertEqual(len(files), 1)
        with gzip.open(files[0], "rt", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["items"], items)

    def test_other_users_and_baselines_do_not_share_saved_items(self) -> None:
        self.cache.save(_key(), [{"id": 1}])

        self.assertIsNone(self.cache.load(_key(baseline_id=12)))
        self.assertIsNone(self.cache.load(_key(username="other_user")))

    def test_a_file_saved_under_another_key_is_not_trusted(self) -> None:
        """파일 이름이 겹치더라도 안에 적힌 조건이 다르면 쓰지 않는다."""
        self.cache.save(_key(), [{"id": 1}])
        path = next(self.root.glob("*.json.gz"))
        payload = {"version": 1, "key": _key(baseline_id=99).fields(), "items": [{"id": 2}]}
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            json.dump(payload, handle)

        self.assertIsNone(self.cache.load(_key()))

    def test_broken_files_are_removed_so_they_can_be_downloaded_again(self) -> None:
        self.cache.save(_key(), [{"id": 1}])
        path = next(self.root.glob("*.json.gz"))
        path.write_bytes(b"not gzip")

        self.assertIsNone(self.cache.load(_key()))
        self.assertFalse(path.exists())

    def test_oldest_unused_files_are_removed_above_the_size_limit(self) -> None:
        big_items = [{"id": index, "name": os.urandom(400).hex()} for index in range(40)]
        self.cache.save(_key(1), big_items)
        one_file = self.cache.total_bytes()
        self.cache = BaselineItemCache(self.root, max_bytes=one_file * 2 + 100)
        self.cache.save(_key(2), big_items)
        # 1번을 다시 읽어 2번보다 최근에 쓴 것으로 만든다.
        time.sleep(0.05)
        self.assertIsNotNone(self.cache.load(_key(1)))

        self.cache.save(_key(3), big_items)

        self.assertIsNotNone(self.cache.load(_key(1)))
        self.assertIsNone(self.cache.load(_key(2)))
        self.assertIsNotNone(self.cache.load(_key(3)))

    def test_clear_removes_every_saved_file(self) -> None:
        self.cache.save(_key(1), [{"id": 1}])
        self.cache.save(_key(2), [{"id": 2}])

        self.assertEqual(self.cache.clear(), 2)
        self.assertEqual(self.cache.total_bytes(), 0)
        self.assertIsNone(self.cache.load(_key(1)))

    def test_saving_into_an_unwritable_place_does_not_raise(self) -> None:
        blocked = Path(self._tmp.name) / "blocked"
        blocked.write_text("파일이라 폴더를 만들 수 없다", encoding="utf-8")

        BaselineItemCache(blocked).save(_key(), [{"id": 1}])

    def test_saved_time_is_shown_in_local_time(self) -> None:
        self.assertRegex(describe_saved_at("2026-09-30T05:00:00+00:00"), r"^2026-09-30 \d\d:00$")
        self.assertEqual(describe_saved_at("unknown"), "unknown")


if __name__ == "__main__":
    unittest.main()
