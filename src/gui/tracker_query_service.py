from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from typing import Any

from src.codebeamer_client import CodebeamerClient

from .payload_values import as_mapping
from .service_core import _build_gui_client
from .tracker_baseline_compare import BaselineComparisonResult
from .tracker_baseline_compare import BaselineComparisonSource
from .tracker_baseline_compare import TrackerBaseline
from .tracker_baseline_compare import compare_tracker_items
from .tracker_hierarchy import TrackerHierarchyError
from .tracker_hierarchy import TrackerHierarchySnapshot
from .tracker_hierarchy import build_tracker_hierarchy
from .tracker_hierarchy_export import TrackerHierarchyExportSnapshot
from .tracker_hierarchy_export import build_tracker_hierarchy_snapshot
from .tracker_query_models import PageResult
from .tracker_query_models import ProjectSummary
from .tracker_query_models import TrackerItemContext
from .tracker_query_models import TrackerItemDetail
from .tracker_query_models import TrackerItemSummary
from .tracker_query_models import TrackerQuery
from .tracker_query_models import TrackerQueryErrorKind
from .tracker_query_models import TrackerQueryServiceError
from .tracker_query_models import TrackerSummary


_ERROR_MESSAGES = {
    TrackerQueryErrorKind.UNAUTHORIZED: "Codebeamer 인증에 실패했습니다. 활성 연결 정보를 확인하세요.",
    TrackerQueryErrorKind.FORBIDDEN: "선택한 데이터에 대한 조회 권한이 없습니다.",
    TrackerQueryErrorKind.NOT_FOUND: "요청한 프로젝트, 트래커 또는 아이템을 찾을 수 없습니다.",
    TrackerQueryErrorKind.RATE_LIMITED: "서버 요청 제한에 도달했습니다. 잠시 후 다시 시도하세요.",
    TrackerQueryErrorKind.INVALID_QUERY: "검색 조건을 실행할 수 없습니다. 조건식과 필드 값을 확인하세요.",
    TrackerQueryErrorKind.NETWORK: "Codebeamer 서버에 연결하지 못했습니다. 네트워크와 주소를 확인하세요.",
    TrackerQueryErrorKind.SERVER: "Codebeamer 서버가 조회 요청을 처리하지 못했습니다.",
    TrackerQueryErrorKind.OFFLINE_DATA_UNAVAILABLE: (
        "테스트 모드의 조회 데이터 snapshot이 없거나 올바르지 않습니다."
    ),
    TrackerQueryErrorKind.UNKNOWN: "조회 중 예상하지 못한 오류가 발생했습니다.",
}


def classify_tracker_query_error(exc: Exception) -> tuple[TrackerQueryErrorKind, int | None]:
    explicit_kind = getattr(exc, "query_error_kind", None)
    if explicit_kind is not None:
        try:
            return TrackerQueryErrorKind(explicit_kind), None
        except Exception:
            pass

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 401:
        return TrackerQueryErrorKind.UNAUTHORIZED, status_code
    if status_code == 403:
        return TrackerQueryErrorKind.FORBIDDEN, status_code
    if status_code == 404:
        return TrackerQueryErrorKind.NOT_FOUND, status_code
    if status_code == 429:
        return TrackerQueryErrorKind.RATE_LIMITED, status_code
    if status_code in {400, 409, 422}:
        return TrackerQueryErrorKind.INVALID_QUERY, status_code
    if isinstance(status_code, int) and status_code >= 500:
        return TrackerQueryErrorKind.SERVER, status_code

    if isinstance(exc, ValueError):
        return TrackerQueryErrorKind.INVALID_QUERY, None
    if isinstance(exc, KeyError):
        return TrackerQueryErrorKind.NOT_FOUND, None
    class_name = type(exc).__name__.lower()
    if "timeout" in class_name or "connection" in class_name:
        return TrackerQueryErrorKind.NETWORK, None
    return TrackerQueryErrorKind.UNKNOWN, status_code


class TrackerQueryService:
    """트래커 조회 응답을 UI 독립 모델로 정규화한다."""

    def __init__(self, client_factory=CodebeamerClient, logger=None) -> None:
        self.client_factory = client_factory
        self.logger = logger
        self._tracker_cache: dict[tuple[tuple[Any, ...], int], dict[str, Any]] = {}
        self._schema_cache: dict[tuple[tuple[Any, ...], int], dict[str, Any]] = {}

    @staticmethod
    def _settings_cache_key(settings) -> tuple[Any, ...]:
        return (
            bool(getattr(settings, "offline_mode", False)),
            str(getattr(settings, "base_url", "") or "").strip().rstrip("/"),
            str(getattr(settings, "username", "") or "").strip(),
            str(getattr(settings, "offline_schema_path", "") or "").strip(),
            str(getattr(settings, "offline_query_data_path", "") or "").strip(),
        )

    def clear_cache(self) -> None:
        """연결 설정이나 서버 데이터를 새로 불러올 때 세션 캐시를 비운다."""
        self._tracker_cache.clear()
        self._schema_cache.clear()

    def _cache_key(self, settings, tracker_id: int) -> tuple[tuple[Any, ...], int]:
        return self._settings_cache_key(settings), int(tracker_id)

    def _build_client(self, settings):
        return _build_gui_client(settings, self.client_factory, self.logger)

    def _client(self, settings, operation: str):
        return self._run(operation, lambda: self._build_client(settings))

    @staticmethod
    def _run(operation: str, callback: Callable[[], Any]) -> Any:
        try:
            return callback()
        except TrackerQueryServiceError:
            raise
        except Exception as exc:
            kind, status_code = classify_tracker_query_error(exc)
            raise TrackerQueryServiceError(
                kind,
                _ERROR_MESSAGES[kind],
                status_code=status_code,
                operation=operation,
            ) from exc

    @staticmethod
    def _extract_list(payload: Any, *keys: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _page_payload(
        client: Any,
        *,
        page_method: str,
        list_method: str,
        entity_id: int,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        page_callback = getattr(client, page_method, None)
        if callable(page_callback):
            payload = page_callback(entity_id, page=page, page_size=page_size)
            if isinstance(payload, dict):
                return payload
            if isinstance(payload, list):
                return {
                    "page": page,
                    "pageSize": len(payload),
                    "total": len(payload),
                    "itemRefs": payload,
                }
        list_callback = getattr(client, list_method)
        items = list_callback(entity_id)
        normalized = items if isinstance(items, list) else []
        return {
            "page": 1,
            "pageSize": len(normalized),
            "total": len(normalized),
            "itemRefs": normalized,
        }

    def _load_all_item_summaries(
        self,
        client: Any,
        *,
        operation: str,
        page_method: str,
        list_method: str,
        entity_id: int,
        page_size: int,
        normalize: Callable[[dict[str, Any]], TrackerItemSummary],
    ) -> tuple[TrackerItemSummary, ...]:
        normalized_page_size = min(max(int(page_size), 1), 500)

        def collect() -> tuple[TrackerItemSummary, ...]:
            collected: list[TrackerItemSummary] = []
            seen_ids: set[int] = set()
            page = 1
            while True:
                payload = self._page_payload(
                    client,
                    page_method=page_method,
                    list_method=list_method,
                    entity_id=int(entity_id),
                    page=page,
                    page_size=normalized_page_size,
                )
                raw_items = self._extract_list(payload, "itemRefs", "items")
                added = 0
                for raw_item in raw_items:
                    summary = normalize(raw_item)
                    if summary.item_id in seen_ids:
                        continue
                    seen_ids.add(summary.item_id)
                    collected.append(summary)
                    added += 1

                raw_total = payload.get("total")
                try:
                    total = int(raw_total) if raw_total is not None else None
                except (TypeError, ValueError):
                    total = None

                if total is not None and len(collected) >= max(total, 0):
                    break
                if not raw_items:
                    if total is not None and len(collected) < total:
                        raise TrackerQueryServiceError(
                            TrackerQueryErrorKind.SERVER,
                            "서버가 계층의 전체 아이템 목록을 반환하지 못했습니다.",
                            operation=operation,
                        )
                    break
                if added == 0:
                    if total is not None and len(collected) < total:
                        raise TrackerQueryServiceError(
                            TrackerQueryErrorKind.SERVER,
                            "서버가 계층 조회의 다음 페이지를 적용하지 않았습니다.",
                            operation=operation,
                        )
                    break
                if total is None and len(raw_items) < normalized_page_size:
                    break
                page += 1

            return tuple(collected)

        return self._run(operation, collect)

    def load_projects(self, settings) -> tuple[ProjectSummary, ...]:
        client = self._client(settings, "load_projects")
        payload = self._run("load_projects", client.get_projects)
        return tuple(
            ProjectSummary.from_raw(item)
            for item in self._extract_list(payload, "projects", "items", "references")
        )

    def load_trackers(
        self,
        settings,
        project_id: int,
        *,
        project_name: str = "",
    ) -> tuple[TrackerSummary, ...]:
        project_id = int(project_id)
        client = self._client(settings, "load_trackers")
        payload = self._run(
            "load_trackers",
            lambda: client.get_trackers(project_id),
        )
        trackers: list[TrackerSummary] = []
        for item in self._extract_list(payload, "trackers", "items", "references"):
            tracker = TrackerSummary.from_raw(
                item,
                project_id=project_id,
                project_name=project_name,
            )
            trackers.append(tracker)
            tracker_payload = dict(item)
            tracker_payload.setdefault("id", tracker.tracker_id)
            tracker_payload.setdefault("name", tracker.name)
            if not isinstance(tracker_payload.get("project"), dict):
                tracker_payload["project"] = {
                    "id": project_id,
                    "name": project_name,
                }
            self._tracker_cache[
                self._cache_key(settings, tracker.tracker_id)
            ] = tracker_payload
        return tuple(trackers)

    def load_tracker_schema(self, settings, tracker_id: int) -> dict[str, Any]:
        normalized_tracker_id = int(tracker_id)
        cache_key = self._cache_key(settings, normalized_tracker_id)
        cached = self._schema_cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)
        client = self._client(settings, "load_tracker_schema")
        payload = self._run(
            "load_tracker_schema",
            lambda: client.get_tracker_schema(normalized_tracker_id),
        )
        if isinstance(payload, list):
            normalized = {
                "id": normalized_tracker_id,
                "fields": [dict(field) for field in payload if isinstance(field, dict)],
            }
        elif isinstance(payload, dict):
            normalized = dict(payload)
            if not isinstance(normalized.get("fields"), list):
                fields = self._extract_list(normalized, "items", "references")
                if fields:
                    normalized["fields"] = fields
            normalized.setdefault("id", normalized_tracker_id)
        else:
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.SERVER,
                "트래커 schema 응답 형식을 해석할 수 없습니다.",
                operation="load_tracker_schema",
            )
        self._schema_cache[cache_key] = deepcopy(normalized)
        return deepcopy(normalized)

    def load_top_level_items(
        self,
        settings,
        tracker_id: int,
        *,
        tracker_name: str = "",
        project_id: int | None = None,
        project_name: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> PageResult[TrackerItemSummary]:
        client = self._client(settings, "load_top_level_items")
        payload = self._run(
            "load_top_level_items",
            lambda: self._page_payload(
                client,
                page_method="get_tracker_children_page",
                list_method="get_tracker_children",
                entity_id=int(tracker_id),
                page=page,
                page_size=page_size,
            ),
        )
        items = (
            TrackerItemSummary.from_raw(
                item,
                tracker_id=int(tracker_id),
                tracker_name=tracker_name,
                project_id=project_id,
                project_name=project_name,
            )
            for item in self._extract_list(payload, "itemRefs", "items")
        )
        return PageResult.create(
            items,
            raw_page=payload,
            requested_page=page,
            requested_page_size=page_size,
        )

    def load_all_top_level_items(
        self,
        settings,
        tracker_id: int,
        *,
        tracker_name: str = "",
        project_id: int | None = None,
        project_name: str = "",
        page_size: int = 500,
    ) -> tuple[TrackerItemSummary, ...]:
        normalized_tracker_id = int(tracker_id)
        client = self._client(settings, "load_all_top_level_items")
        return self._load_all_item_summaries(
            client,
            operation="load_all_top_level_items",
            page_method="get_tracker_children_page",
            list_method="get_tracker_children",
            entity_id=normalized_tracker_id,
            page_size=page_size,
            normalize=lambda item: TrackerItemSummary.from_raw(
                item,
                tracker_id=normalized_tracker_id,
                tracker_name=tracker_name,
                project_id=project_id,
                project_name=project_name,
            ),
        )

    def load_child_items(
        self,
        settings,
        item_id: int,
        *,
        tracker_id: int | None = None,
        tracker_name: str = "",
        project_id: int | None = None,
        project_name: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> PageResult[TrackerItemSummary]:
        client = self._client(settings, "load_child_items")
        payload = self._run(
            "load_child_items",
            lambda: self._page_payload(
                client,
                page_method="get_item_children_page",
                list_method="get_item_children",
                entity_id=int(item_id),
                page=page,
                page_size=page_size,
            ),
        )
        raw_items = self._extract_list(payload, "itemRefs", "items")
        items: list[TrackerItemSummary] = []
        for raw_item in raw_items:
            normalized = dict(raw_item)
            normalized.setdefault("parent", {"id": int(item_id)})
            items.append(
                TrackerItemSummary.from_raw(
                    normalized,
                    tracker_id=tracker_id,
                    tracker_name=tracker_name,
                    project_id=project_id,
                    project_name=project_name,
                )
            )
        return PageResult.create(
            items,
            raw_page=payload,
            requested_page=page,
            requested_page_size=page_size,
        )

    def load_all_child_items(
        self,
        settings,
        item_id: int,
        *,
        tracker_id: int | None = None,
        tracker_name: str = "",
        project_id: int | None = None,
        project_name: str = "",
        page_size: int = 500,
    ) -> tuple[TrackerItemSummary, ...]:
        normalized_item_id = int(item_id)
        client = self._client(settings, "load_all_child_items")

        def normalize(raw_item: dict[str, Any]) -> TrackerItemSummary:
            normalized = dict(raw_item)
            normalized.setdefault("parent", {"id": normalized_item_id})
            return TrackerItemSummary.from_raw(
                normalized,
                tracker_id=tracker_id,
                tracker_name=tracker_name,
                project_id=project_id,
                project_name=project_name,
            )

        return self._load_all_item_summaries(
            client,
            operation="load_all_child_items",
            page_method="get_item_children_page",
            list_method="get_item_children",
            entity_id=normalized_item_id,
            page_size=page_size,
            normalize=normalize,
        )

    def load_tracker_hierarchy_export_snapshot(
        self,
        settings,
        tracker_id: int,
        *,
        tracker_name: str = "",
        project_id: int | None = None,
        project_name: str = "",
        page_size: int = 500,
    ) -> TrackerHierarchyExportSnapshot:
        """단건 조회 없이 트래커 전체 item과 최상위 목록으로 계층 snapshot을 만든다."""
        normalized_tracker_id = int(tracker_id)
        items = self.load_all_search_items(
            settings,
            TrackerQuery(
                tracker_id=normalized_tracker_id,
                page=1,
                page_size=page_size,
                sort="item.id ASC",
            ),
            page_size=page_size,
            require_full_items=True,
        )
        roots = self.load_all_top_level_items(
            settings,
            normalized_tracker_id,
            tracker_name=tracker_name,
            project_id=project_id,
            project_name=project_name,
            page_size=page_size,
        )
        schema = self.load_tracker_schema(settings, normalized_tracker_id)
        return build_tracker_hierarchy_snapshot(
            items,
            roots,
            schema,
            tracker_id=normalized_tracker_id,
        )

    def load_baseline_hierarchy_snapshot(
        self,
        settings,
        tracker_id: int,
        baseline_id: int,
        *,
        page_size: int = 500,
    ) -> TrackerHierarchySnapshot:
        """현재 계층 API를 섞지 않고 Baseline 전체 item으로 계층을 만든다."""
        normalized_tracker_id = int(tracker_id)
        normalized_baseline_id = int(baseline_id)
        items = self.load_all_search_items(
            settings,
            TrackerQuery(
                tracker_id=normalized_tracker_id,
                page=1,
                page_size=page_size,
                sort="item.id ASC",
                baseline_id=normalized_baseline_id,
            ),
            page_size=page_size,
            require_full_items=True,
        )
        try:
            return build_tracker_hierarchy(items, tracker_id=normalized_tracker_id)
        except TrackerHierarchyError as exc:
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.SERVER,
                str(exc),
                operation="load_baseline_hierarchy",
            ) from exc

    def search(
        self,
        settings,
        query: TrackerQuery,
        *,
        require_full_items: bool = False,
    ) -> PageResult[TrackerItemSummary]:
        scoped_cbql = self._run("build_query", query.build_cbql)
        client = self._client(settings, "search_items")
        payload = self._run(
            "search_items",
            lambda: client.search_items(
                query_string=scoped_cbql,
                baseline_id=query.baseline_id,
                page=query.page,
                page_size=query.page_size,
            ),
        )
        if require_full_items and not (
            isinstance(payload, dict) and isinstance(payload.get("items"), list)
        ):
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.SERVER,
                "이 작업에는 전체 필드가 포함된 items query 응답이 필요합니다.",
                operation="search_items",
            )
        raw_items = self._extract_list(payload, "items", "itemRefs")
        normalized_items: list[TrackerItemSummary] = []
        for item in raw_items:
            normalized = TrackerItemSummary.from_raw(item, tracker_id=query.tracker_id)
            if normalized.tracker_id != query.tracker_id:
                raise TrackerQueryServiceError(
                    TrackerQueryErrorKind.SERVER,
                    "검색 응답에 현재 트래커 범위를 벗어난 아이템이 포함되었습니다.",
                    operation="search_items",
                )
            normalized_items.append(normalized)
        result = PageResult.create(
            normalized_items,
            raw_page=payload,
            requested_page=query.page,
            requested_page_size=query.page_size,
        )
        metadata = dict(result.server_metadata)
        metadata["scopedCbql"] = scoped_cbql
        return replace(result, server_metadata=metadata)

    def load_tracker_baselines(self, settings, tracker_id: int) -> tuple[TrackerBaseline, ...]:
        client = self._client(settings, "load_tracker_baselines")
        payload = self._run(
            "load_tracker_baselines",
            lambda: client.get_tracker_baselines(int(tracker_id)),
        )
        raw_baselines = self._extract_baselines(payload)
        baselines: list[TrackerBaseline] = []
        for raw in raw_baselines:
            try:
                baselines.append(TrackerBaseline.from_raw(raw))
            except ValueError:
                continue
        return tuple(sorted(baselines, key=lambda baseline: (baseline.created_at, baseline.baseline_id), reverse=True))

    @classmethod
    def _extract_baselines(cls, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in (
            "references",
            "baselines",
            "trackerBaselines",
            "baselineList",
            "items",
            "results",
            "content",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        data = payload.get("data")
        if isinstance(data, (dict, list)):
            return cls._extract_baselines(data)
        return [payload] if payload.get("id") is not None else []

    def load_all_search_items(
        self,
        settings,
        query: TrackerQuery,
        *,
        page_size: int = 500,
        require_full_items: bool = False,
    ) -> tuple[TrackerItemSummary, ...]:
        """검색 조건에 맞는 전체 ID를 서버 페이지 단위로 빠짐없이 수집한다."""
        normalized_page_size = min(max(int(page_size), 1), 500)
        collected: list[TrackerItemSummary] = []
        seen_ids: set[int] = set()
        page = 1
        while True:
            result = self.search(
                settings,
                replace(query, page=page, page_size=normalized_page_size),
                require_full_items=require_full_items,
            )
            added = 0
            for summary in result.items:
                if summary.item_id in seen_ids:
                    continue
                seen_ids.add(summary.item_id)
                collected.append(summary)
                added += 1
            if len(collected) >= result.total:
                break
            if not result.items or added == 0:
                raise TrackerQueryServiceError(
                    TrackerQueryErrorKind.SERVER,
                    "서버가 검색 결과의 다음 페이지를 적용하지 않았습니다.",
                    operation="load_all_search_items",
                )
            page += 1
        return tuple(collected)

    def compare_tracker_at_sources(
        self,
        settings,
        tracker_id: int,
        *,
        reference_source: BaselineComparisonSource,
        comparison_source: BaselineComparisonSource,
        page_size: int = 500,
    ) -> BaselineComparisonResult:
        """두 기준의 트래커 전체 아이템을 query로 조회해 한 번에 비교한다."""
        if reference_source == comparison_source:
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.INVALID_QUERY,
                "서로 다른 두 비교 기준을 선택하세요.",
                operation="compare_tracker_at_sources",
            )
        normalized_tracker_id = int(tracker_id)

        def load_source(
            source: BaselineComparisonSource,
        ) -> tuple[TrackerItemSummary, ...]:
            return self.load_all_search_items(
                settings,
                TrackerQuery(
                    tracker_id=normalized_tracker_id,
                    page=1,
                    page_size=page_size,
                    sort="item.id ASC",
                    baseline_id=source.baseline_id,
                ),
                page_size=page_size,
                require_full_items=True,
            )

        reference = load_source(reference_source)
        comparison = load_source(comparison_source)
        try:
            tracker_schema = self.load_tracker_schema(settings, normalized_tracker_id)
        except TrackerQueryServiceError:
            tracker_schema = None
        # 내부 before/after는 비교 대상에서 기준으로 이동한 변화 방향을 나타낸다.
        return compare_tracker_items(
            comparison,
            reference,
            before_source=comparison_source,
            after_source=reference_source,
            tracker_schema=tracker_schema,
        )

    def compare_item_at_sources(
        self,
        settings,
        item_id: int,
        tracker_id: int,
        *,
        reference_source: BaselineComparisonSource,
        comparison_source: BaselineComparisonSource,
    ) -> BaselineComparisonResult:
        if reference_source == comparison_source:
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.INVALID_QUERY,
                "서로 다른 두 비교 기준을 선택하세요.",
                operation="compare_item_at_sources",
            )
        normalized_item_id = int(item_id)
        normalized_tracker_id = int(tracker_id)
        client = self._client(settings, "compare_item_at_sources")

        def load_source(source: BaselineComparisonSource) -> tuple[TrackerItemSummary, ...]:
            try:
                raw = client.get_item(normalized_item_id, baseline_id=source.baseline_id)
            except Exception as exc:
                kind, _status_code = classify_tracker_query_error(exc)
                if kind == TrackerQueryErrorKind.NOT_FOUND:
                    return ()
                raise
            if not isinstance(raw, dict):
                return ()
            return (TrackerItemSummary.from_raw(raw, tracker_id=normalized_tracker_id),)

        reference = self._run(
            "compare_item_at_sources", lambda: load_source(reference_source)
        )
        comparison = self._run(
            "compare_item_at_sources", lambda: load_source(comparison_source)
        )
        try:
            tracker_schema = self.load_tracker_schema(settings, normalized_tracker_id)
        except TrackerQueryServiceError:
            tracker_schema = None
        # 신규/삭제는 비교 대상에서 기준으로 이동했을 때의 변화로 판정한다.
        return compare_tracker_items(
            comparison,
            reference,
            before_source=comparison_source,
            after_source=reference_source,
            tracker_schema=tracker_schema,
        )

    def load_detail(
        self,
        settings,
        item_id: int,
        *,
        baseline_id: int | None = None,
    ) -> TrackerItemDetail:
        client = self._client(settings, "load_item_detail")
        normalized_baseline_id = (
            None if baseline_id is None else int(baseline_id)
        )
        raw_item = self._run(
            "load_item_detail",
            lambda: (
                client.get_item(int(item_id))
                if normalized_baseline_id is None
                else client.get_item(
                    int(item_id), baseline_id=normalized_baseline_id
                )
            ),
        )
        if not isinstance(raw_item, dict):
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.SERVER,
                "아이템 상세 응답 형식을 해석할 수 없습니다.",
                operation="load_item_detail",
            )

        tracker = as_mapping(raw_item.get("tracker"))
        tracker_payload: dict[str, Any] = dict(tracker)
        tracker_id = tracker.get("id")
        get_tracker = getattr(client, "get_tracker", None)
        warnings: tuple[str, ...] = ()
        if tracker_id is not None and callable(get_tracker):
            cache_key = self._cache_key(settings, int(tracker_id))
            candidate = self._tracker_cache.get(cache_key)
            if candidate is None:
                try:
                    candidate = get_tracker(int(tracker_id))
                except Exception:
                    candidate = None
                    warnings = (
                        "소속 프로젝트 메타데이터를 불러오지 못해 아이템 상세만 표시합니다.",
                    )
                if isinstance(candidate, dict):
                    self._tracker_cache[cache_key] = dict(candidate)
            if isinstance(candidate, dict):
                tracker_payload = candidate
        detail = TrackerItemDetail.from_raw(raw_item, tracker_payload=tracker_payload)
        return replace(detail, warnings=warnings)

    def resolve_item_context(self, settings, item_id: int) -> TrackerItemContext:
        client = self._client(settings, "resolve_item_context")
        raw_item = self._run(
            "resolve_item_context",
            lambda: client.get_item(int(item_id)),
        )
        if not isinstance(raw_item, dict):
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.SERVER,
                "아이템 상세 응답 형식을 해석할 수 없습니다.",
                operation="resolve_item_context",
            )
        tracker_reference = (
            as_mapping(raw_item.get("tracker"))
        )
        tracker_id = tracker_reference.get("id")
        if tracker_id is None:
            raise TrackerQueryServiceError(
                TrackerQueryErrorKind.SERVER,
                "아이템 응답에서 소속 트래커를 확인할 수 없습니다.",
                operation="resolve_item_context",
            )
        cache_key = self._cache_key(settings, int(tracker_id))
        tracker_payload = self._tracker_cache.get(cache_key)
        if tracker_payload is None:
            tracker_payload = self._run(
                "resolve_item_tracker",
                lambda: client.get_tracker(int(tracker_id)),
            )
            if isinstance(tracker_payload, dict):
                self._tracker_cache[cache_key] = dict(tracker_payload)
        if not isinstance(tracker_payload, dict):
            tracker_payload = dict(tracker_reference)
        detail = TrackerItemDetail.from_raw(raw_item, tracker_payload=tracker_payload)
        return TrackerItemContext(
            item=detail,
            tracker_id=int(tracker_id),
            tracker_name=str(tracker_payload.get("name") or tracker_reference.get("name") or ""),
            project_id=detail.summary.project_id,
            project_name=detail.summary.project_name,
        )

    def load_ancestor_path(
        self,
        settings,
        item_id: int,
        *,
        max_depth: int = 100,
    ) -> tuple[TrackerItemSummary, ...]:
        """parent 참조를 따라 루트부터 대상 아이템까지의 경로를 구성한다."""
        if int(max_depth) <= 0:
            raise ValueError("조상 경로 최대 깊이는 양의 정수여야 합니다.")
        client = self._client(settings, "load_ancestor_path")
        current_id: int | None = int(item_id)
        expected_tracker_id: int | None = None
        visited: set[int] = set()
        reversed_path: list[TrackerItemSummary] = []

        while current_id is not None:
            if current_id in visited:
                raise TrackerQueryServiceError(
                    TrackerQueryErrorKind.SERVER,
                    "아이템 계층에 순환 parent 참조가 있어 경로를 구성할 수 없습니다.",
                    operation="load_ancestor_path",
                )
            if len(visited) >= int(max_depth):
                raise TrackerQueryServiceError(
                    TrackerQueryErrorKind.SERVER,
                    "아이템 계층이 허용된 최대 깊이를 초과했습니다.",
                    operation="load_ancestor_path",
                )
            visited.add(current_id)
            raw_item = self._run(
                "load_ancestor_path",
                lambda selected_id=current_id: client.get_item(selected_id),
            )
            if not isinstance(raw_item, dict):
                raise TrackerQueryServiceError(
                    TrackerQueryErrorKind.SERVER,
                    "아이템 계층 응답 형식을 해석할 수 없습니다.",
                    operation="load_ancestor_path",
                )
            summary = TrackerItemSummary.from_raw(raw_item)
            if expected_tracker_id is None:
                expected_tracker_id = summary.tracker_id
            elif (
                summary.tracker_id is not None
                and expected_tracker_id is not None
                and summary.tracker_id != expected_tracker_id
            ):
                raise TrackerQueryServiceError(
                    TrackerQueryErrorKind.SERVER,
                    "아이템 parent 경로가 다른 트래커로 연결되어 있습니다.",
                    operation="load_ancestor_path",
                )
            reversed_path.append(summary)
            current_id = summary.parent_id

        return tuple(reversed(reversed_path))


__all__ = [
    "TrackerQueryService",
    "classify_tracker_query_error",
]
