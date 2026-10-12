"""GUI 조회 서비스가 작업 스레드끼리 함께 쓰는 캐시.

작업공간은 요청마다 새 작업 스레드를 띄운다. 끝나지 않은 요청은 결과만 버리므로 같은 서비스
캐시를 여러 스레드가 동시에 읽고 쓴다. 메인 스레드는 상세 새로고침 때 그 캐시를 비운다.

- 모든 읽기·쓰기·비우기를 한 락 안에서 한다. 네트워크 호출 중에는 락을 잡지 않는다.
- 비울 때마다 세대 번호를 올린다. 조회를 시작할 때 받은 번호가 다르면 결과를 넣지 않는다.
  그래야 새로고침 전에 시작한 조회가 끝나도 옛 결과가 캐시에 되살아나지 않는다.
- 크기 예산을 주면 가장 오래 쓰지 않은 값부터 밀어낸다.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from collections.abc import Hashable


class ServiceCache[K: Hashable, V]:
    def __init__(
        self,
        *,
        max_total_size: int | None = None,
        size_of: Callable[[V], int] | None = None,
    ) -> None:
        if max_total_size is not None and size_of is None:
            raise ValueError("크기 예산을 쓰려면 size_of 가 필요합니다.")
        self._lock = threading.Lock()
        self._values: OrderedDict[K, V] = OrderedDict()
        self._generation = 0
        self._max_total_size = max_total_size
        self._size_of = size_of
        self._total_size = 0

    def generation(self) -> int:
        """조회를 시작할 때 받아 두었다가 `put` 에 넘긴다."""
        with self._lock:
            return self._generation

    def get(self, key: K) -> V | None:
        with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return value

    def put(self, key: K, value: V, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
            size = self._size(value)
            if self._max_total_size is not None and size > self._max_total_size:
                return
            previous = self._values.pop(key, None)
            if previous is not None:
                self._total_size -= self._size(previous)
            self._values[key] = value
            self._total_size += size
            while self._max_total_size is not None and self._total_size > self._max_total_size:
                _evicted_key, evicted = self._values.popitem(last=False)
                self._total_size -= self._size(evicted)

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._values.clear()
            self._total_size = 0

    def discard_where(self, predicate: Callable[[K], bool]) -> None:
        """조건에 맞는 값을 지운다. 지금 진행 중인 조회의 결과도 받지 않는다."""
        with self._lock:
            self._generation += 1
            for key in [key for key in self._values if predicate(key)]:
                self._total_size -= self._size(self._values.pop(key))

    def total_size(self) -> int:
        with self._lock:
            return self._total_size

    def _size(self, value: V) -> int:
        return self._size_of(value) if self._size_of is not None else 0


__all__ = ["ServiceCache"]
