"""GUI 조회 서비스가 작업 스레드끼리 함께 쓰는 캐시.

작업공간은 요청마다 새 작업 스레드를 띄운다. 끝나지 않은 요청은 결과만 버리므로 같은 서비스
캐시를 여러 스레드가 동시에 읽고 쓴다. 메인 스레드는 상세 새로고침 때 그 캐시를 비운다.

- 모든 읽기·쓰기·비우기를 한 락 안에서 한다. 네트워크 호출 중에는 락을 잡지 않는다.
- 비울 때마다 세대 번호를 올린다. 조회를 시작할 때 받은 번호가 다르면 결과를 넣지 않는다.
  그래야 새로고침 전에 시작한 조회가 끝나도 옛 결과가 캐시에 되살아나지 않는다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from collections.abc import Hashable


class ServiceCache[K: Hashable, V]:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[K, V] = {}
        self._generation = 0

    def generation(self) -> int:
        """조회를 시작할 때 받아 두었다가 `put` 에 넘긴다."""
        with self._lock:
            return self._generation

    def get(self, key: K) -> V | None:
        with self._lock:
            return self._values.get(key)

    def put(self, key: K, value: V, generation: int) -> None:
        with self._lock:
            if generation == self._generation:
                self._values[key] = value

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._values.clear()

    def discard_where(self, predicate: Callable[[K], bool]) -> None:
        """조건에 맞는 값을 지운다. 지금 진행 중인 조회의 결과도 받지 않는다."""
        with self._lock:
            self._generation += 1
            for key in [key for key in self._values if predicate(key)]:
                del self._values[key]


__all__ = ["ServiceCache"]
