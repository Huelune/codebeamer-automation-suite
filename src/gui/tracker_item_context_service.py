from __future__ import annotations

from typing import Any

from src.codebeamer_client import CodebeamerClient

from .service_core import _build_gui_client
from .tracker_item_context_models import ItemHistorySnapshot
from .tracker_item_context_models import ItemRelationsSnapshot
from .tracker_query_models import TrackerQueryErrorKind
from .tracker_query_models import TrackerQueryServiceError
from .tracker_query_service import classify_tracker_query_error


class TrackerItemContextService:
    """현재 아이템의 관계·이력 조회를 상세 및 콘텐츠 서비스와 분리한다."""

    def __init__(self, client_factory=CodebeamerClient, logger=None) -> None:
        self.client_factory = client_factory
        self.logger = logger
        self._relations_cache: dict[tuple[Any, ...], ItemRelationsSnapshot] = {}
        self._history_cache: dict[tuple[Any, ...], ItemHistorySnapshot] = {}

    @staticmethod
    def _settings_key(settings) -> tuple[Any, ...]:
        return (
            bool(getattr(settings, "offline_mode", False)),
            str(getattr(settings, "base_url", "") or "").strip().rstrip("/"),
            str(getattr(settings, "username", "") or "").strip(),
            str(getattr(settings, "offline_query_data_path", "") or "").strip(),
        )

    def _key(self, settings, item_id: int, item_version: int | None) -> tuple[Any, ...]:
        return self._settings_key(settings), int(item_id), item_version

    def _client(self, settings):
        return _build_gui_client(settings, self.client_factory, self.logger)

    def clear_cache(self) -> None:
        self._relations_cache.clear()
        self._history_cache.clear()

    def clear_item_cache(self, settings, item_id: int) -> None:
        prefix = self._settings_key(settings), int(item_id)
        self._relations_cache = {key: value for key, value in self._relations_cache.items() if key[:2] != prefix}
        self._history_cache = {key: value for key, value in self._history_cache.items() if key[:2] != prefix}

    @staticmethod
    def _error(operation: str, exc: Exception) -> TrackerQueryServiceError:
        kind, status_code = classify_tracker_query_error(exc)
        messages = {
            TrackerQueryErrorKind.UNAUTHORIZED: "로그인이 만료되어 아이템 문맥을 조회할 수 없습니다.",
            TrackerQueryErrorKind.FORBIDDEN: "아이템 문맥을 볼 권한이 없습니다.",
            TrackerQueryErrorKind.NOT_FOUND: "아이템 문맥을 찾을 수 없습니다.",
            TrackerQueryErrorKind.RATE_LIMITED: "요청이 많아 아이템 문맥 조회가 제한되었습니다.",
        }
        return TrackerQueryServiceError(kind, messages.get(kind, f"아이템 문맥 조회에 실패했습니다: {exc}"), status_code=status_code, operation=operation)

    def load_relations(self, settings, item_id: int, item_version: int | None, *, baseline_id: int | None = None, force: bool = False) -> ItemRelationsSnapshot:
        if baseline_id is not None:
            raise ValueError("Baseline 시점의 관계 조회는 지원하지 않습니다.")
        key = self._key(settings, item_id, item_version)
        if not force and key in self._relations_cache:
            return self._relations_cache[key]
        try:
            raw = self._client(settings).get_item_relations(int(item_id))
        except Exception as exc:
            raise self._error("load_item_relations", exc) from exc
        if not isinstance(raw, dict):
            raise TrackerQueryServiceError(TrackerQueryErrorKind.SERVER, "아이템 관계 응답 형식을 해석할 수 없습니다.", operation="load_item_relations")
        result = ItemRelationsSnapshot.from_raw(raw)
        self._relations_cache[key] = result
        return result

    def load_history(self, settings, item_id: int, item_version: int | None, *, baseline_id: int | None = None, force: bool = False) -> ItemHistorySnapshot:
        if baseline_id is not None:
            raise ValueError("Baseline 시점의 변경 이력 조회는 지원하지 않습니다.")
        key = self._key(settings, item_id, item_version)
        if not force and key in self._history_cache:
            return self._history_cache[key]
        try:
            raw = self._client(settings).get_item_history(int(item_id))
        except Exception as exc:
            raise self._error("load_item_history", exc) from exc
        if not isinstance(raw, (dict, list)):
            raise TrackerQueryServiceError(TrackerQueryErrorKind.SERVER, "아이템 이력 응답 형식을 해석할 수 없습니다.", operation="load_item_history")
        result = ItemHistorySnapshot.from_raw(raw, current_version=item_version)
        self._history_cache[key] = result
        return result


__all__ = ["TrackerItemContextService"]
