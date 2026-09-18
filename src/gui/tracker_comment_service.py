from __future__ import annotations

from typing import Any

from src.codebeamer_client import CodebeamerClient

from .service_core import _build_gui_client
from .tracker_comment_models import ItemCommentsSnapshot
from .tracker_query_models import TrackerQueryErrorKind
from .tracker_query_models import TrackerQueryServiceError
from .tracker_query_service import classify_tracker_query_error


class TrackerCommentService:
    """현재 아이템의 읽기 전용 댓글 목록을 조회하고 정규화한다."""

    def __init__(self, client_factory=CodebeamerClient, logger=None) -> None:
        self.client_factory = client_factory
        self.logger = logger
        self._cache: dict[tuple[Any, ...], ItemCommentsSnapshot] = {}

    @staticmethod
    def _settings_key(settings) -> tuple[Any, ...]:
        return (
            bool(getattr(settings, "offline_mode", False)),
            str(getattr(settings, "base_url", "") or "").strip().rstrip("/"),
            str(getattr(settings, "username", "") or "").strip(),
            str(getattr(settings, "offline_query_data_path", "") or "").strip(),
        )

    def clear_cache(self) -> None:
        self._cache.clear()

    def clear_item_cache(self, settings, item_id: int) -> None:
        prefix = self._settings_key(settings), int(item_id)
        self._cache = {key: value for key, value in self._cache.items() if key[:2] != prefix}

    def load_comments(self, settings, item_id: int, item_version: int | None, *, baseline_id: int | None = None, force: bool = False) -> ItemCommentsSnapshot:
        if baseline_id is not None:
            raise ValueError("Baseline 시점의 댓글 조회는 지원하지 않습니다.")
        key = self._settings_key(settings), int(item_id), item_version
        if not force and key in self._cache:
            return self._cache[key]
        try:
            raw = _build_gui_client(settings, self.client_factory, self.logger).get_item_comments(int(item_id))
        except Exception as exc:
            kind, status_code = classify_tracker_query_error(exc)
            messages = {
                TrackerQueryErrorKind.UNAUTHORIZED: "로그인이 만료되어 댓글을 조회할 수 없습니다.",
                TrackerQueryErrorKind.FORBIDDEN: "댓글을 볼 권한이 없습니다.",
                TrackerQueryErrorKind.NOT_FOUND: "댓글을 찾을 수 없습니다.",
                TrackerQueryErrorKind.RATE_LIMITED: "요청이 많아 댓글 조회가 제한되었습니다.",
            }
            raise TrackerQueryServiceError(kind, messages.get(kind, f"댓글 조회에 실패했습니다: {exc}"), status_code=status_code, operation="load_item_comments") from exc
        if not isinstance(raw, (dict, list)):
            raise TrackerQueryServiceError(TrackerQueryErrorKind.SERVER, "댓글 응답 형식을 해석할 수 없습니다.", operation="load_item_comments")
        result = ItemCommentsSnapshot.from_raw(raw)
        self._cache[key] = result
        return result


__all__ = ["TrackerCommentService"]
