"""트래커 작업공간 즐겨찾기(아이템·트래커) 모델.

아이템·트래커 ID는 서버마다 다르므로 설정에는 서버·사용자별로 나눠 저장한다.
테스트 모드 샘플 ID가 실서버 목록에 섞이지 않도록 테스트 모드는 따로 둔다.
이름은 마지막으로 본 값을 남겨 목록에 보여 주고, 다시 열 때 갱신한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from .payload_values import as_mapping


MAX_FAVORITE_ITEMS = 200
MAX_FAVORITE_TRACKERS = 50
TEST_MODE_FAVORITES_KEY = "test-mode"


def favorites_key(settings: Any) -> str:
    """즐겨찾기를 나눠 저장하는 단위. 서버 주소와 사용자, 테스트 모드는 따로."""
    if bool(getattr(settings, "offline_mode", False)):
        return TEST_MODE_FAVORITES_KEY
    base_url = str(getattr(settings, "base_url", "") or "").strip().rstrip("/")
    username = str(getattr(settings, "username", "") or "").strip()
    return f"{base_url}|{username}"


def _positive_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


@dataclass(frozen=True)
class FavoriteItem:
    item_id: int
    name: str = ""
    tracker_name: str = ""
    project_name: str = ""


@dataclass(frozen=True)
class FavoriteTracker:
    tracker_id: int
    project_id: int
    name: str = ""
    project_name: str = ""


@dataclass(frozen=True)
class WorkspaceFavorites:
    """한 서버·사용자의 즐겨찾기. 최근에 추가한 것이 앞이다."""

    items: tuple[FavoriteItem, ...] = ()
    trackers: tuple[FavoriteTracker, ...] = ()

    @classmethod
    def from_payload(cls, value: object) -> WorkspaceFavorites:
        """설정 파일 값을 읽는다. ID가 올바르지 않은 항목과 중복은 버리고 개수를 제한한다."""
        payload = as_mapping(value)
        items: list[FavoriteItem] = []
        seen_items: set[int] = set()
        for raw in payload.get("items") or []:
            entry = as_mapping(raw)
            item_id = _positive_int(entry.get("item_id"))
            if not item_id or item_id in seen_items:
                continue
            seen_items.add(item_id)
            items.append(
                FavoriteItem(
                    item_id=item_id,
                    name=str(entry.get("name") or ""),
                    tracker_name=str(entry.get("tracker_name") or ""),
                    project_name=str(entry.get("project_name") or ""),
                )
            )
        trackers: list[FavoriteTracker] = []
        seen_trackers: set[int] = set()
        for raw in payload.get("trackers") or []:
            entry = as_mapping(raw)
            tracker_id = _positive_int(entry.get("tracker_id"))
            project_id = _positive_int(entry.get("project_id"))
            if not tracker_id or not project_id or tracker_id in seen_trackers:
                continue
            seen_trackers.add(tracker_id)
            trackers.append(
                FavoriteTracker(
                    tracker_id=tracker_id,
                    project_id=project_id,
                    name=str(entry.get("name") or ""),
                    project_name=str(entry.get("project_name") or ""),
                )
            )
        return cls(tuple(items[:MAX_FAVORITE_ITEMS]), tuple(trackers[:MAX_FAVORITE_TRACKERS]))

    def to_payload(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "items": [
                {
                    "item_id": item.item_id,
                    "name": item.name,
                    "tracker_name": item.tracker_name,
                    "project_name": item.project_name,
                }
                for item in self.items
            ],
            "trackers": [
                {
                    "tracker_id": tracker.tracker_id,
                    "project_id": tracker.project_id,
                    "name": tracker.name,
                    "project_name": tracker.project_name,
                }
                for tracker in self.trackers
            ],
        }

    def is_empty(self) -> bool:
        return not self.items and not self.trackers

    def has_item(self, item_id: int) -> bool:
        return any(item.item_id == int(item_id) for item in self.items)

    def has_tracker(self, tracker_id: int) -> bool:
        return any(tracker.tracker_id == int(tracker_id) for tracker in self.trackers)

    def with_item(self, item: FavoriteItem) -> WorkspaceFavorites:
        rest = tuple(value for value in self.items if value.item_id != item.item_id)
        return replace(self, items=(item, *rest)[:MAX_FAVORITE_ITEMS])

    def without_item(self, item_id: int) -> WorkspaceFavorites:
        return replace(self, items=tuple(value for value in self.items if value.item_id != int(item_id)))

    def with_tracker(self, tracker: FavoriteTracker) -> WorkspaceFavorites:
        rest = tuple(value for value in self.trackers if value.tracker_id != tracker.tracker_id)
        return replace(self, trackers=(tracker, *rest)[:MAX_FAVORITE_TRACKERS])

    def without_tracker(self, tracker_id: int) -> WorkspaceFavorites:
        return replace(
            self,
            trackers=tuple(value for value in self.trackers if value.tracker_id != int(tracker_id)),
        )

    def renamed_item(self, item: FavoriteItem) -> WorkspaceFavorites:
        """즐겨찾기한 아이템이면 자리는 그대로 두고 이름만 새 값으로 바꾼다."""
        return replace(
            self,
            items=tuple(item if value.item_id == item.item_id else value for value in self.items),
        )


def normalized_favorites_by_server(value: object) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """설정 파일의 서버별 즐겨찾기를 정리한다. 비어 있는 서버는 남기지 않는다."""
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key, raw in as_mapping(value).items():
        favorites = WorkspaceFavorites.from_payload(raw)
        if str(key) and not favorites.is_empty():
            result[str(key)] = favorites.to_payload()
    return result
