from __future__ import annotations

import sys
import threading
import time
import unittest

from src.gui.service_cache import ServiceCache


class ServiceCacheTest(unittest.TestCase):
    def test_value_from_before_a_clear_is_not_stored(self) -> None:
        """비운 뒤 늦게 끝난 조회가 옛 결과를 다시 넣지 않는다."""
        cache: ServiceCache[str, str] = ServiceCache()
        generation = cache.generation()
        cache.clear()

        cache.put("key", "old", generation)

        self.assertIsNone(cache.get("key"))
        cache.put("key", "new", cache.generation())
        self.assertEqual(cache.get("key"), "new")

    def test_discard_matching_keys_also_rejects_late_values(self) -> None:
        cache: ServiceCache[tuple[int, int], str] = ServiceCache()
        cache.put((1, 1), "item-1", cache.generation())
        cache.put((2, 1), "item-2", cache.generation())
        generation = cache.generation()

        cache.discard_where(lambda key: key[0] == 1)
        cache.put((1, 2), "late", generation)

        self.assertIsNone(cache.get((1, 1)))
        self.assertIsNone(cache.get((1, 2)))
        self.assertEqual(cache.get((2, 1)), "item-2")

    def test_concurrent_reads_writes_and_clears_do_not_raise(self) -> None:
        """작업 스레드가 넣는 동안 다른 스레드가 비우거나 골라 지워도 예외가 나지 않는다."""
        cache: ServiceCache[tuple[int, int], int] = ServiceCache()
        errors: list[BaseException] = []
        stop = time.monotonic() + 0.3

        def writer(offset: int) -> None:
            try:
                index = 0
                while time.monotonic() < stop:
                    cache.put((offset, index), index, cache.generation())
                    cache.get((offset, index - 1))
                    index += 1
            except BaseException as exc:  # pragma: no cover - 실패 시 원인을 보존한다.
                errors.append(exc)

        def clearer() -> None:
            try:
                while time.monotonic() < stop:
                    cache.discard_where(lambda key: key[1] % 3 == 0)
                    cache.clear()
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        previous = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            threads = [threading.Thread(target=writer, args=(offset,)) for offset in range(3)]
            threads.append(threading.Thread(target=clearer))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            sys.setswitchinterval(previous)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
