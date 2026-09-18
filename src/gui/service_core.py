from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from src.codebeamer_client import CodebeamerClient
from src.excel_reader import ExcelReader

from .offline_query import build_offline_cbql_predicate
from .payload_values import as_mapping


@dataclass
class FileSignature:
    path: str
    size: int
    modified_ns: int

    @classmethod
    def capture(cls, file_path: str) -> FileSignature:
        path = Path(str(file_path)).expanduser()
        stat = path.stat()
        return cls(
            path=str(file_path),
            size=int(stat.st_size),
            modified_ns=int(stat.st_mtime_ns),
        )

    def matches_current_file(self) -> bool:
        try:
            current = self.capture(self.path)
        except OSError:
            return False
        return self.size == current.size and self.modified_ns == current.modified_ns


@dataclass
class WorkbookMetadata:
    file_path: str
    sheet_names: list[str]
    signature: FileSignature


@dataclass
class SheetPreviewData:
    file_path: str
    sheet_name: str
    header_row: int
    summary_column: str
    headers: list[str]
    rows: list[list[str]]
    suggested_summary: str
    signature: FileSignature


@dataclass
class PreviewData:
    file_path: str
    sheet_name: str
    header_row: int
    summary_column: str
    sheet_names: list[str]
    headers: list[str]
    rows: list[list[str]]
    suggested_summary: str
    raw_df: pd.DataFrame
    raw_df_by_file: dict[str, pd.DataFrame] = field(default_factory=dict)
    file_signatures: dict[str, FileSignature] = field(default_factory=dict)
    cache_hit: bool = False

    def files_are_current(self) -> bool:
        return all(signature.matches_current_file() for signature in self.file_signatures.values())


def gui_display_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, list):
        return ", ".join(part for part in (gui_display_text(item) for item in value) if part)
    if isinstance(value, dict):
        if value.get("name") is not None:
            return str(value.get("name")).strip()
        return str(value).strip()
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


DEFAULT_OFFLINE_PROJECT_ID = 1
DEFAULT_OFFLINE_TRACKER_ID = 1
DEFAULT_OFFLINE_PROJECT_NAME = "Offline Project"
DEFAULT_OFFLINE_TRACKER_NAME = "Offline Tracker"


def _normalize_offline_id(value: Any, default_value: int) -> int:
    try:
        normalized = int(value)
    except Exception:
        return default_value
    return normalized if normalized > 0 else default_value


def _load_json_snapshot(path_value: Any, *, label: str) -> Any:
    path_text = str(path_value or "").strip()
    if not path_text:
        raise ValueError(f"{label} 경로가 비어 있습니다.")

    snapshot_path = Path(path_text).expanduser()
    if not snapshot_path.is_file():
        raise ValueError(f"{label} 파일을 찾을 수 없습니다: {snapshot_path}")

    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{label} JSON을 읽을 수 없습니다: {exc}") from exc


class OfflineQueryDataUnavailable(RuntimeError):
    query_error_kind = "offline_data_unavailable"


def _offline_page(
    items: list[dict[str, Any]],
    *,
    page: int,
    page_size: int,
    item_key: str,
) -> dict[str, Any]:
    normalized_page = max(int(page), 1)
    normalized_page_size = min(max(int(page_size), 1), 500)
    start = (normalized_page - 1) * normalized_page_size
    end = start + normalized_page_size
    return {
        "page": normalized_page,
        "pageSize": normalized_page_size,
        "total": len(items),
        item_key: deepcopy(items[start:end]),
    }


class OfflineGuiClient:
    """로컬 schema/config/query snapshot으로 GUI 테스트 모드를 지원한다."""

    def __init__(
        self,
        *,
        schema: dict[str, Any],
        schema_path: str,
        tracker_configuration: Any = None,
        query_data: dict[str, Any] | None = None,
        query_data_path: str = "",
        project_id: int = DEFAULT_OFFLINE_PROJECT_ID,
        tracker_id: int = DEFAULT_OFFLINE_TRACKER_ID,
    ) -> None:
        """필요한 의존성과 상태를 초기화한다."""
        self.schema = dict(schema or {})
        self.schema_path = str(schema_path)
        self.tracker_configuration = tracker_configuration
        if query_data is not None and not isinstance(query_data, dict):
            raise ValueError("테스트 조회 데이터 snapshot은 JSON 객체여야 합니다.")
        self.query_data = deepcopy(query_data) if isinstance(query_data, dict) else None
        self.query_data_path = str(query_data_path or "")
        self.project_id = int(project_id)
        self.tracker_id = int(tracker_id)
        self.project_name = DEFAULT_OFFLINE_PROJECT_NAME
        self.tracker_name = (
            str(self.schema.get("name") or "").strip()
            or Path(self.schema_path).stem
            or DEFAULT_OFFLINE_TRACKER_NAME
        )
        self._offline_projects: dict[int, dict[str, Any]] = {}
        self._offline_trackers: dict[int, dict[str, Any]] = {}
        self._offline_items: dict[int, dict[str, Any]] = {}
        self._offline_children: dict[int | None, list[int]] = {}
        self._offline_relations: dict[str, Any] = {}
        self._offline_history: dict[str, Any] = {}
        self._offline_comments: dict[str, Any] = {}
        if self.query_data is not None:
            self._load_query_data(self.query_data)

    @classmethod
    def from_settings(cls, settings) -> OfflineGuiClient:
        schema_path = str(getattr(settings, "offline_schema_path", "") or "").strip()
        schema = _load_json_snapshot(schema_path, label="테스트 schema")
        tracker_configuration = None
        configuration_path = str(
            getattr(settings, "offline_tracker_configuration_path", "") or ""
        ).strip()
        if configuration_path:
            tracker_configuration = _load_json_snapshot(
                configuration_path,
                label="테스트 tracker configuration",
            )
        query_data = None
        query_data_path = str(
            getattr(settings, "offline_query_data_path", "") or ""
        ).strip()
        if query_data_path:
            try:
                query_data = _load_json_snapshot(
                    query_data_path,
                    label="테스트 조회 데이터",
                )
            except Exception as exc:
                raise OfflineQueryDataUnavailable(
                    "테스트 조회 데이터 Snapshot을 읽을 수 없습니다."
                ) from exc
        try:
            return cls(
                schema=schema,
                schema_path=schema_path,
                tracker_configuration=tracker_configuration,
                query_data=query_data,
                query_data_path=query_data_path,
                project_id=_normalize_offline_id(
                    getattr(settings, "default_project_id", ""),
                    DEFAULT_OFFLINE_PROJECT_ID,
                ),
                tracker_id=_normalize_offline_id(
                    getattr(settings, "default_tracker_id", ""),
                    DEFAULT_OFFLINE_TRACKER_ID,
                ),
            )
        except OfflineQueryDataUnavailable:
            raise
        except ValueError as exc:
            if query_data_path:
                raise OfflineQueryDataUnavailable(
                    "테스트 조회 데이터 Snapshot 형식이 올바르지 않습니다."
                ) from exc
            raise

    def _load_query_data(self, payload: dict[str, Any]) -> None:
        if int(payload.get("version") or 0) != 1:
            raise ValueError("테스트 조회 데이터 version은 1이어야 합니다.")
        projects = payload.get("projects")
        trackers = payload.get("trackers")
        items = payload.get("items")
        if not isinstance(projects, list) or not isinstance(trackers, list) or not isinstance(items, list):
            raise ValueError("테스트 조회 데이터에는 projects, trackers, items 목록이 필요합니다.")
        if not projects or not trackers:
            raise ValueError("테스트 조회 데이터에는 프로젝트와 트래커가 하나 이상 필요합니다.")

        for raw_project in projects:
            if not isinstance(raw_project, dict):
                raise ValueError("테스트 조회 데이터의 프로젝트 형식이 올바르지 않습니다.")
            project_id = int(raw_project.get("id") or 0)
            if project_id <= 0 or project_id in self._offline_projects:
                raise ValueError("테스트 조회 데이터의 프로젝트 ID가 없거나 중복됩니다.")
            self._offline_projects[project_id] = deepcopy(raw_project)

        for raw_tracker in trackers:
            if not isinstance(raw_tracker, dict):
                raise ValueError("테스트 조회 데이터의 트래커 형식이 올바르지 않습니다.")
            tracker_id = int(raw_tracker.get("id") or 0)
            project = as_mapping(raw_tracker.get("project"))
            project_id = int(raw_tracker.get("projectId") or project.get("id") or 0)
            if tracker_id <= 0 or tracker_id in self._offline_trackers:
                raise ValueError("테스트 조회 데이터의 트래커 ID가 없거나 중복됩니다.")
            if project_id not in self._offline_projects:
                raise ValueError("테스트 조회 데이터의 트래커가 알 수 없는 프로젝트를 참조합니다.")
            normalized_tracker = deepcopy(raw_tracker)
            normalized_tracker["projectId"] = project_id
            normalized_tracker["project"] = {
                "id": project_id,
                "name": self._offline_projects[project_id].get("name", str(project_id)),
                "type": "ProjectReference",
            }
            self._offline_trackers[tracker_id] = normalized_tracker

        parent_ids: dict[int, int | None] = {}
        for raw_item in items:
            if not isinstance(raw_item, dict):
                raise ValueError("테스트 조회 데이터의 아이템 형식이 올바르지 않습니다.")
            item_id = int(raw_item.get("id") or 0)
            tracker = as_mapping(raw_item.get("tracker"))
            tracker_id = int(raw_item.get("trackerId") or tracker.get("id") or 0)
            parent = as_mapping(raw_item.get("parent"))
            parent_id_value = raw_item.get("parentId") or parent.get("id")
            parent_id = int(parent_id_value) if parent_id_value not in (None, "") else None
            if item_id <= 0 or item_id in self._offline_items:
                raise ValueError("테스트 조회 데이터의 아이템 ID가 없거나 중복됩니다.")
            if tracker_id not in self._offline_trackers:
                raise ValueError("테스트 조회 데이터의 아이템이 알 수 없는 트래커를 참조합니다.")
            normalized_item = deepcopy(raw_item)
            normalized_item["trackerId"] = tracker_id
            normalized_item["parentId"] = parent_id
            self._offline_items[item_id] = normalized_item
            parent_ids[item_id] = parent_id

        for item_id, parent_id in parent_ids.items():
            if parent_id is not None:
                parent = self._offline_items.get(parent_id)
                if parent is None:
                    raise ValueError("테스트 조회 데이터의 parent 아이템을 찾을 수 없습니다.")
                if int(parent.get("trackerId") or 0) != int(
                    self._offline_items[item_id].get("trackerId") or 0
                ):
                    raise ValueError("테스트 조회 데이터의 parent는 같은 트래커에 있어야 합니다.")
            self._offline_children.setdefault(parent_id, []).append(item_id)

        relations = payload.get("relationsByItemId", {})
        history = payload.get("historyByItemId", {})
        if not isinstance(relations, dict) or not isinstance(history, dict):
            raise ValueError("테스트 관계·이력 데이터는 아이템 ID별 객체여야 합니다.")
        self._offline_relations = deepcopy(relations)
        self._offline_history = deepcopy(history)
        comments = payload.get("commentsByItemId", {})
        if not isinstance(comments, dict):
            raise ValueError("테스트 댓글 데이터는 아이템 ID별 객체여야 합니다.")
        self._offline_comments = deepcopy(comments)

        if self._offline_projects and self.project_id not in self._offline_projects:
            self.project_id = next(iter(self._offline_projects))
        if self._offline_trackers and self.tracker_id not in self._offline_trackers:
            self.tracker_id = next(iter(self._offline_trackers))
        if self.tracker_id in self._offline_trackers:
            self.tracker_name = str(
                self._offline_trackers[self.tracker_id].get("name") or self.tracker_name
            )
        if self.project_id in self._offline_projects:
            self.project_name = str(
                self._offline_projects[self.project_id].get("name") or self.project_name
            )

    def _require_query_data(self) -> None:
        if self.query_data is None:
            raise OfflineQueryDataUnavailable(
                "테스트 조회 데이터 Snapshot이 설정되지 않았습니다."
            )

    def _item_reference(self, item_id: int) -> dict[str, Any]:
        item = self._offline_items[int(item_id)]
        child_ids = self._offline_children.get(int(item_id), [])
        tracker_id = int(item.get("trackerId") or 0)
        tracker = self._offline_trackers[tracker_id]
        reference: dict[str, Any] = {
            "id": int(item_id),
            "name": str(item.get("name") or item.get("summary") or item_id),
            "type": "TrackerItemReference",
            "tracker": {
                "id": tracker_id,
                "name": str(tracker.get("name") or tracker_id),
                "type": "TrackerReference",
            },
            "status": deepcopy(item.get("status")),
            "assignedTo": deepcopy(item.get("assignedTo") or []),
            "modifiedAt": str(item.get("modifiedAt") or ""),
            "version": item.get("version"),
            "hasChildren": bool(child_ids),
            "childCount": len(child_ids),
        }
        parent_id = item.get("parentId")
        if parent_id is not None:
            parent = self._offline_items[int(parent_id)]
            reference["parent"] = {
                "id": int(parent_id),
                "name": str(parent.get("name") or parent_id),
                "type": "TrackerItemReference",
            }
        return reference

    def _item_payload(self, item_id: int) -> dict[str, Any]:
        item = deepcopy(self._offline_items[int(item_id)])
        tracker_id = int(item.pop("trackerId"))
        parent_id = item.pop("parentId", None)
        tracker = self._offline_trackers[tracker_id]
        project_id = int(tracker.get("projectId") or 0)
        item["tracker"] = {
            "id": tracker_id,
            "name": str(tracker.get("name") or tracker_id),
            "type": "TrackerReference",
            "project": {
                "id": project_id,
                "name": str(self._offline_projects[project_id].get("name") or project_id),
                "type": "ProjectReference",
            },
        }
        if parent_id is not None:
            item["parent"] = self._item_reference(int(parent_id))
        else:
            item.pop("parent", None)
        child_ids = self._offline_children.get(int(item_id), [])
        item["children"] = [self._item_reference(child_id) for child_id in child_ids]
        item["hasChildren"] = bool(child_ids)
        item["childCount"] = len(child_ids)
        return item

    def _baseline_item_payload(self, item: dict[str, Any], tracker_id: int) -> dict[str, Any]:
        payload = deepcopy(item)
        tracker = self._offline_trackers[int(tracker_id)]
        project_id = int(tracker.get("projectId") or 0)
        payload["tracker"] = {
            "id": int(tracker_id),
            "name": str(tracker.get("name") or tracker_id),
            "type": "TrackerReference",
            "project": {
                "id": project_id,
                "name": str(self._offline_projects[project_id].get("name") or project_id),
                "type": "ProjectReference",
            },
        }
        payload.setdefault("customFields", [])
        payload.setdefault("assignedTo", [])
        return payload

    def get_projects(self) -> list[dict[str, Any]]:
        """`get_projects` 값을 반환한다."""
        if self.query_data is not None:
            return [deepcopy(project) for project in self._offline_projects.values()]
        return [{"id": self.project_id, "name": self.project_name}]

    def get_trackers(self, project_id: int) -> list[dict[str, Any]]:
        """`get_trackers` 값을 반환한다."""
        if self.query_data is not None:
            return [
                deepcopy(tracker)
                for tracker in self._offline_trackers.values()
                if int(tracker.get("projectId") or 0) == int(project_id)
            ]
        del project_id
        return [{"id": self.tracker_id, "name": self.tracker_name}]

    def get_tracker(self, tracker_id: int) -> dict[str, Any]:
        if self.query_data is None:
            return {
                "id": self.tracker_id,
                "name": self.tracker_name,
                "project": {
                    "id": self.project_id,
                    "name": self.project_name,
                    "type": "ProjectReference",
                },
            }
        tracker = self._offline_trackers.get(int(tracker_id))
        if tracker is None:
            raise KeyError(f"offline tracker not found: {tracker_id}")
        return deepcopy(tracker)

    def get_tracker_baselines(self, tracker_id: int) -> list[dict[str, Any]]:
        self._require_query_data()
        if int(tracker_id) not in self._offline_trackers:
            raise KeyError(f"offline tracker not found: {tracker_id}")
        baselines = self.query_data.get("baselines", []) if self.query_data else []
        if not isinstance(baselines, list):
            return []
        result: list[dict[str, Any]] = []
        for item in baselines:
            if not isinstance(item, dict) or int(item.get("trackerId") or tracker_id) != int(tracker_id):
                continue
            reference = deepcopy(item)
            reference.pop("items", None)
            result.append(reference)
        return result

    def get_tracker_schema(self, tracker_id: int) -> dict[str, Any]:
        """`get_tracker_schema` 값을 반환한다."""
        if self.query_data is not None:
            tracker = self._offline_trackers.get(int(tracker_id))
            if tracker is None:
                raise KeyError(f"offline tracker not found: {tracker_id}")
            tracker_schema = tracker.get("schema")
            if isinstance(tracker_schema, dict):
                return deepcopy(tracker_schema)
            schema = deepcopy(self.schema)
            schema["id"] = int(tracker_id)
            schema["name"] = str(tracker.get("name") or schema.get("name") or tracker_id)
            return schema
        del tracker_id
        return deepcopy(self.schema)

    def get_tracker_configuration(self, tracker_id: int) -> Any:
        """`get_tracker_configuration` 값을 반환한다."""
        del tracker_id
        if self.tracker_configuration is None:
            raise RuntimeError("offline tracker configuration snapshot is not configured")
        return self.tracker_configuration

    def get_tracker_items_page(
        self,
        tracker_id: int,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        self._require_query_data()
        if int(tracker_id) not in self._offline_trackers:
            raise KeyError(f"offline tracker not found: {tracker_id}")
        references = [
            self._item_reference(item_id)
            for item_id, item in self._offline_items.items()
            if int(item.get("trackerId") or 0) == int(tracker_id)
        ]
        return _offline_page(
            references,
            page=page,
            page_size=page_size,
            item_key="itemRefs",
        )

    def get_tracker_items(self, tracker_id: int) -> list[dict[str, Any]]:
        return self.get_tracker_items_page(tracker_id)["itemRefs"]

    def get_tracker_children_page(
        self,
        tracker_id: int,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        self._require_query_data()
        if int(tracker_id) not in self._offline_trackers:
            raise KeyError(f"offline tracker not found: {tracker_id}")
        references = [
            self._item_reference(item_id)
            for item_id in self._offline_children.get(None, [])
            if int(self._offline_items[item_id].get("trackerId") or 0) == int(tracker_id)
        ]
        return _offline_page(
            references,
            page=page,
            page_size=page_size,
            item_key="itemRefs",
        )

    def get_tracker_children(self, tracker_id: int) -> list[dict[str, Any]]:
        return self.get_tracker_children_page(tracker_id)["itemRefs"]

    def get_item_children_page(
        self,
        item_id: int,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        self._require_query_data()
        if int(item_id) not in self._offline_items:
            raise KeyError(f"offline item not found: {item_id}")
        references = [
            self._item_reference(child_id)
            for child_id in self._offline_children.get(int(item_id), [])
        ]
        return _offline_page(
            references,
            page=page,
            page_size=page_size,
            item_key="itemRefs",
        )

    def get_item_children(self, item_id: int) -> list[dict[str, Any]]:
        return self.get_item_children_page(item_id)["itemRefs"]

    def create_item(
        self, tracker_id: int, payload: dict[str, Any], parent_item_id: int | None = None
    ) -> dict[str, Any]:
        del tracker_id, payload, parent_item_id
        raise RuntimeError("테스트 모드에서는 실제 업로드를 실행할 수 없습니다. Dry Run만 사용해야 합니다.")

    def update_item(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        del item_id, payload
        raise RuntimeError("테스트 모드에서는 업데이트를 실행할 수 없습니다. Dry Run만 사용해야 합니다.")

    def update_item_fields(
        self,
        item_id: int,
        field_values: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del item_id, field_values
        raise RuntimeError("테스트 모드에서는 필드 수정을 실행할 수 없습니다.")

    def delete_item(self, item_id: int) -> dict[str, Any]:
        del item_id
        raise RuntimeError("테스트 모드에서는 아이템 삭제를 실행할 수 없습니다.")

    def get_item(self, item_id: int, baseline_id: int | None = None) -> dict[str, Any]:
        """`get_item` 값을 반환한다."""
        self._require_query_data()
        if baseline_id is not None:
            baselines = self.query_data.get("baselines", []) if self.query_data else []
            baseline = next(
                (
                    entry
                    for entry in baselines
                    if isinstance(entry, dict) and int(entry.get("id") or 0) == int(baseline_id)
                ),
                None,
            )
            if baseline is None or not isinstance(baseline.get("items"), list):
                raise KeyError(f"offline baseline not found: {baseline_id}")
            item = next(
                (
                    entry
                    for entry in baseline["items"]
                    if isinstance(entry, dict) and int(entry.get("id") or 0) == int(item_id)
                ),
                None,
            )
            if item is None:
                raise KeyError(f"offline baseline item not found: {item_id}")
            tracker_id = int(item.get("trackerId") or self.tracker_id)
            return self._baseline_item_payload(item, tracker_id)
        if int(item_id) not in self._offline_items:
            raise KeyError(f"offline item not found: {item_id}")
        return self._item_payload(int(item_id))

    def get_item_relations(self, item_id: int) -> dict[str, Any]:
        self._require_query_data()
        normalized = int(item_id)
        if normalized not in self._offline_items:
            raise KeyError(f"offline item not found: {item_id}")
        payload = self._offline_relations.get(str(normalized), {})
        if not isinstance(payload, dict):
            raise ValueError("테스트 관계 데이터 형식이 올바르지 않습니다.")
        return deepcopy(payload)

    def get_item_history(self, item_id: int) -> dict[str, Any]:
        self._require_query_data()
        normalized = int(item_id)
        if normalized not in self._offline_items:
            raise KeyError(f"offline item not found: {item_id}")
        payload = self._offline_history.get(str(normalized), {"versions": []})
        if not isinstance(payload, dict):
            raise ValueError("테스트 이력 데이터 형식이 올바르지 않습니다.")
        return deepcopy(payload)

    def get_item_comments(self, item_id: int) -> list[dict[str, Any]]:
        self._require_query_data()
        normalized = int(item_id)
        if normalized not in self._offline_items:
            raise KeyError(f"offline item not found: {item_id}")
        payload = self._offline_comments.get(str(normalized), [])
        if isinstance(payload, dict):
            payload = payload.get("comments") or payload.get("items") or []
        if not isinstance(payload, list):
            raise ValueError("테스트 댓글 데이터 형식이 올바르지 않습니다.")
        return deepcopy([value for value in payload if isinstance(value, dict)])

    def search_items(
        self,
        *,
        query_string: str,
        baseline_id: int | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        self._require_query_data()
        tracker_match = re.search(
            r"\btracker\.id\s*=\s*(\d+)",
            str(query_string or ""),
            re.IGNORECASE,
        )
        if tracker_match is None:
            raise ValueError("테스트 조회는 tracker.id 범위가 반드시 필요합니다.")
        tracker_id = int(tracker_match.group(1))
        if tracker_id not in self._offline_trackers:
            return _offline_page([], page=page, page_size=page_size, item_key="items")

        condition_expression = re.sub(
            r"\s+ORDER\s+BY\s+.+$",
            "",
            str(query_string or "").strip(),
            flags=re.IGNORECASE,
        )
        predicate = build_offline_cbql_predicate(condition_expression)
        if baseline_id is None:
            source_items = [self._item_payload(item_id) for item_id in self._offline_items]
        else:
            baselines = self.query_data.get("baselines", []) if self.query_data else []
            baseline = next(
                (
                    item for item in baselines
                    if isinstance(item, dict)
                    and int(item.get("id") or 0) == int(baseline_id)
                    and int(item.get("trackerId") or tracker_id) == tracker_id
                ),
                None,
            )
            if baseline is None:
                raise KeyError(f"offline baseline not found: {baseline_id}")
            raw_items = baseline.get("items")
            if not isinstance(raw_items, list):
                raise OfflineQueryDataUnavailable("테스트 baseline snapshot에 items 목록이 없습니다.")
            source_items = [
                self._baseline_item_payload(item, tracker_id)
                for item in raw_items if isinstance(item, dict)
            ]

        matches: list[dict[str, Any]] = []
        for item_payload in source_items:
            if predicate(item_payload):
                matches.append(item_payload)

        order_match = re.search(r"\bORDER\s+BY\s+(.+)$", query_string, re.IGNORECASE)
        if order_match is not None:
            order_terms: list[tuple[str, bool]] = []
            for raw_term in order_match.group(1).split(","):
                term_match = re.fullmatch(
                    r"\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(ASC|DESC)?\s*",
                    raw_term,
                    re.IGNORECASE,
                )
                if term_match is None:
                    raise ValueError(f"테스트 모드 정렬식을 해석할 수 없습니다: {raw_term}")
                order_terms.append(
                    (
                        term_match.group(1).lower(),
                        (term_match.group(2) or "ASC").upper() == "DESC",
                    )
                )

            def _sort_value(item: dict[str, Any], field_name: str):
                if field_name in {"item.id", "id"}:
                    return int(item.get("id") or 0)
                if field_name in {"summary", "name"}:
                    return str(item.get("name") or "").casefold()
                if field_name == "modifiedat":
                    return str(item.get("modifiedAt") or "")
                if field_name == "status":
                    status = item.get("status")
                    return str(status.get("name") or "").casefold() if isinstance(
                        status, dict
                    ) else str(status or "").casefold()
                return str(item.get(field_name) or "").casefold()

            for field_name, reverse in reversed(order_terms):
                matches.sort(
                    key=lambda item, selected_field=field_name: _sort_value(
                        item,
                        selected_field,
                    ),
                    reverse=reverse,
                )

        return _offline_page(
            matches,
            page=page,
            page_size=page_size,
            item_key="items",
        )

    def get_user(self, user_id: int):
        """`get_user` 값을 반환한다."""
        raise RuntimeError(f"offline snapshot does not provide user lookup by id: {user_id}")

    def get_user_by_name(self, name: str):
        """`get_user_by_name` 값을 반환한다."""
        raise RuntimeError(f"offline snapshot does not provide user lookup by name: {name}")

    def get_user_groups(self):
        """`get_user_groups` 값을 반환한다."""
        raise RuntimeError("offline snapshot does not provide user groups")

    def get_tracker_field_permissions(self, tracker_id: int, field_id: int):
        """`get_tracker_field_permissions` 값을 반환한다."""
        raise RuntimeError(
            f"offline snapshot does not provide field permissions: {tracker_id}/{field_id}"
        )

    def search_tracker_items_by_name(self, *, tracker_id: int, name: str, **kwargs):
        page = int(kwargs.get("page") or 1)
        page_size = int(kwargs.get("page_size") or 100)
        escaped = str(name or "").replace("'", "''")
        payload = self.search_items(
            query_string=(
                f"tracker.id = {int(tracker_id)} AND summary LIKE '%{escaped}%' "
                "ORDER BY item.id ASC"
            ),
            page=page,
            page_size=page_size,
        )
        return [self._item_reference(int(item["id"])) for item in payload["items"]]


def _build_gui_client(settings, client_factory, logger=None):
    if bool(getattr(settings, "offline_mode", False)):
        return OfflineGuiClient.from_settings(settings)
    return client_factory(
        settings.base_url,
        settings.username,
        settings.password,
        logger,
        rate_limit_retry_delay_seconds=settings.rate_limit_retry_delay_seconds,
        rate_limit_max_retries=settings.rate_limit_max_retries,
    )


class GuiCodebeamerService:
    """GUI 에서 사용하는 최소 Codebeamer 조회 기능을 제공한다."""

    def __init__(self, client_factory=CodebeamerClient, logger=None) -> None:
        """필요한 의존성과 상태를 초기화한다."""
        self.client_factory = client_factory
        self.logger = logger

    def _build_client(self, settings):
        return _build_gui_client(settings, self.client_factory, self.logger)

    @staticmethod
    def _normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized.append({
                "id": item.get("id"),
                "name": item.get("name") or item.get("key") or str(item.get("id", "")),
            })
        return normalized

    def test_connection_and_load_projects(self, settings) -> list[dict[str, Any]]:
        projects = self._build_client(settings).get_projects()
        return self._normalize_items(projects)

    def load_trackers(self, settings, project_id: int) -> list[dict[str, Any]]:
        """`load_trackers` 데이터를 불러온다."""
        trackers = self._build_client(settings).get_trackers(project_id)
        return self._normalize_items(trackers)


class GuiExcelService:
    """GUI 파일 선택 화면에서 사용하는 Excel 메타데이터와 미리보기를 제공한다."""

    def __init__(self, logger=None, *, reader_cls=ExcelReader) -> None:
        """필요한 의존성과 상태를 초기화한다."""
        self.logger = logger
        self.reader_cls = reader_cls
        self._full_data_cache: dict[tuple[Any, ...], PreviewData] = {}
        self._raw_data_cache: dict[tuple[Any, ...], pd.DataFrame] = {}

    @staticmethod
    def _normalize_headers(values: list[Any]) -> list[str]:
        headers: list[str] = []
        for index, value in enumerate(values):
            if value is None:
                headers.append(f"Unnamed_{index}")
            else:
                headers.append(str(value).strip())
        return headers

    @staticmethod
    def _suggest_summary(headers: list[str]) -> str:
        for header in headers:
            if header.lower() == "summary":
                return header
        for header in headers:
            if header == "요약":
                return header
        return headers[0] if headers else "Summary"

    @staticmethod
    def _normalized_file_paths(file_path: str, file_paths: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for candidate in [file_path, *(file_paths or [])]:
            text = str(candidate or "").strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @staticmethod
    def _capture_signatures(file_paths: list[str]) -> dict[str, FileSignature]:
        return {
            file_path: FileSignature.capture(file_path)
            for file_path in file_paths
        }

    @staticmethod
    def _cache_key(
        signatures: dict[str, FileSignature],
        *,
        sheet_name: str,
        header_row: int,
        summary_column: str,
    ) -> tuple[Any, ...]:
        signature_key = tuple(
            (
                file_path,
                int(signature.size),
                int(signature.modified_ns),
            )
            for file_path, signature in signatures.items()
        )
        return (
            signature_key,
            str(sheet_name),
            int(header_row),
            str(summary_column),
        )

    @staticmethod
    def _raw_cache_key(
        signature: FileSignature,
        *,
        sheet_name: str,
        header_row: int,
        summary_column: str,
    ) -> tuple[Any, ...]:
        return (
            signature.path,
            int(signature.size),
            int(signature.modified_ns),
            str(sheet_name),
            int(header_row),
            str(summary_column),
        )

    @staticmethod
    def _assert_signatures_unchanged(signatures: dict[str, FileSignature]) -> None:
        changed = [
            Path(file_path).name
            for file_path, signature in signatures.items()
            if not signature.matches_current_file()
        ]
        if changed:
            raise ValueError(
                "데이터를 읽는 동안 파일이 변경되었습니다: " + ", ".join(changed)
            )

    def load_metadata(self, file_path: str) -> WorkbookMetadata:
        """대표 파일의 시트 목록만 읽는다."""
        normalized_path = str(file_path or "").strip()
        if not normalized_path:
            raise ValueError("Excel 파일을 먼저 선택해야 합니다.")
        signature = FileSignature.capture(normalized_path)
        reader = self.reader_cls(header_row=1, summary_col="Summary", logger=self.logger)
        sheet_names = reader.list_sheet_names(normalized_path)
        if not sheet_names:
            raise ValueError("시트가 없는 Excel 파일입니다.")
        if not signature.matches_current_file():
            raise ValueError("시트 정보를 읽는 동안 파일이 변경되었습니다.")
        return WorkbookMetadata(
            file_path=normalized_path,
            sheet_names=list(sheet_names),
            signature=signature,
        )

    def load_sheet_preview(
        self,
        file_path: str,
        *,
        sheet_name: str,
        header_row: int = 1,
        summary_column: str | None = None,
        max_preview_rows: int = 10,
    ) -> SheetPreviewData:
        """선택한 시트의 헤더와 제한된 행만 읽는다."""
        if header_row < 1:
            raise ValueError("header_row 는 1 이상이어야 합니다.")
        normalized_path = str(file_path or "").strip()
        if not normalized_path:
            raise ValueError("Excel 파일을 먼저 선택해야 합니다.")
        normalized_sheet = str(sheet_name or "").strip()
        if not normalized_sheet:
            raise ValueError("미리볼 시트를 선택해야 합니다.")

        signature = FileSignature.capture(normalized_path)
        reader = self.reader_cls(
            header_row=int(header_row),
            summary_col="Summary",
            logger=self.logger,
        )
        preview_reader = getattr(reader, "read_preview_rows", None)
        if callable(preview_reader):
            headers, raw_rows = preview_reader(
                normalized_path,
                normalized_sheet,
                max_rows=max_preview_rows,
            )
        else:  # 기존 custom reader 호환
            headers = reader.read_headers(normalized_path, normalized_sheet)
            fallback_summary = self._suggest_summary(headers)
            reader.summary_col = fallback_summary
            raw_df = reader.read_excel(normalized_path, sheet_name=normalized_sheet)
            raw_rows = raw_df[headers].head(max_preview_rows).values.tolist()
        headers = self._normalize_headers(list(headers))
        suggested_summary = self._suggest_summary(headers)
        target_summary = str(summary_column or "").strip() or suggested_summary
        if target_summary not in headers:
            target_summary = suggested_summary
        if not signature.matches_current_file():
            raise ValueError("미리보기를 읽는 동안 파일이 변경되었습니다.")
        return SheetPreviewData(
            file_path=normalized_path,
            sheet_name=normalized_sheet,
            header_row=int(header_row),
            summary_column=target_summary,
            headers=headers,
            rows=[
                [gui_display_text(value) for value in row]
                for row in raw_rows
            ],
            suggested_summary=suggested_summary,
            signature=signature,
        )

    def load_full_data(
        self,
        file_path: str,
        *,
        file_paths: list[str] | None = None,
        sheet_name: str,
        header_row: int = 1,
        summary_column: str,
        sheet_preview: SheetPreviewData | None = None,
        max_preview_rows: int = 10,
    ) -> PreviewData:
        """명시적 호출에서만 선택된 모든 파일의 전체 데이터를 읽고 cache한다."""
        if header_row < 1:
            raise ValueError("header_row 는 1 이상이어야 합니다.")
        normalized_paths = self._normalized_file_paths(file_path, file_paths)
        if not normalized_paths:
            raise ValueError("Excel 파일을 먼저 선택해야 합니다.")
        normalized_sheet = str(sheet_name or "").strip()
        normalized_summary = str(summary_column or "").strip()
        if not normalized_sheet:
            raise ValueError("전체 데이터를 읽을 시트를 선택해야 합니다.")
        if not normalized_summary:
            raise ValueError("Summary 컬럼을 선택해야 합니다.")

        signatures = self._capture_signatures(normalized_paths)
        cache_key = self._cache_key(
            signatures,
            sheet_name=normalized_sheet,
            header_row=header_row,
            summary_column=normalized_summary,
        )
        cached = self._full_data_cache.get(cache_key)
        if cached is not None and cached.files_are_current():
            return replace(cached, cache_hit=True)

        reader = self.reader_cls(
            header_row=int(header_row),
            summary_col=normalized_summary,
            logger=self.logger,
        )
        raw_df_by_file: dict[str, pd.DataFrame] = {}
        active_raw_cache_keys: set[tuple[Any, ...]] = set()
        expected_headers: list[str] | None = None
        for current_path in normalized_paths:
            raw_cache_key = self._raw_cache_key(
                signatures[current_path],
                sheet_name=normalized_sheet,
                header_row=header_row,
                summary_column=normalized_summary,
            )
            active_raw_cache_keys.add(raw_cache_key)
            raw_df = self._raw_data_cache.get(raw_cache_key)
            if raw_df is None:
                raw_df = reader.read_excel(
                    file_path=current_path,
                    sheet_name=normalized_sheet,
                )
                self._raw_data_cache[raw_cache_key] = raw_df
            visible_headers = [
                str(column)
                for column in raw_df.columns
                if not str(column).startswith("_")
            ]
            if expected_headers is None:
                expected_headers = visible_headers
            elif visible_headers != expected_headers:
                raise ValueError(
                    f"{Path(current_path).name} 파일의 헤더가 기준 파일과 다릅니다."
                )
            raw_df_by_file[current_path] = raw_df
        self._assert_signatures_unchanged(signatures)
        active_source_keys = {key[:-1] for key in active_raw_cache_keys}
        self._raw_data_cache = {
            key: value
            for key, value in self._raw_data_cache.items()
            if key[:-1] in active_source_keys
        }

        representative_path = normalized_paths[0]
        raw_df = raw_df_by_file[representative_path]
        headers = list(expected_headers or [])
        if normalized_summary not in headers:
            raise ValueError(f"'{normalized_summary}' 컬럼을 찾을 수 없습니다.")
        suggested_summary = self._suggest_summary(headers)
        if (
            sheet_preview is not None
            and sheet_preview.file_path == representative_path
            and sheet_preview.sheet_name == normalized_sheet
            and int(sheet_preview.header_row) == int(header_row)
            and sheet_preview.signature == signatures[representative_path]
        ):
            preview_rows = [list(row) for row in sheet_preview.rows]
        else:
            visible_df = raw_df[headers].head(max_preview_rows)
            preview_rows = [
                [gui_display_text(value) for value in row.tolist()]
                for _, row in visible_df.iterrows()
            ]

        result = PreviewData(
            file_path=representative_path,
            sheet_name=normalized_sheet,
            header_row=int(header_row),
            summary_column=normalized_summary,
            sheet_names=[],
            headers=headers,
            rows=preview_rows,
            suggested_summary=suggested_summary,
            raw_df=raw_df,
            raw_df_by_file=raw_df_by_file,
            file_signatures=signatures,
            cache_hit=False,
        )
        self._full_data_cache[cache_key] = result
        while len(self._full_data_cache) > 8:
            oldest_key = next(iter(self._full_data_cache))
            self._full_data_cache.pop(oldest_key, None)
        return result

    def load_preview(
        self,
        file_path: str,
        *,
        file_paths: list[str] | None = None,
        sheet_name: str | None = None,
        header_row: int = 1,
        summary_column: str | None = None,
        max_preview_rows: int = 10,
    ) -> PreviewData:
        """기존 호출 호환: 메타데이터와 전체 데이터를 한 번에 불러온다."""
        if header_row < 1:
            raise ValueError("header_row 는 1 이상이어야 합니다.")

        header_reader = self.reader_cls(header_row=header_row, summary_col="Summary", logger=self.logger)
        sheet_names = header_reader.list_sheet_names(file_path)
        if not sheet_names:
            raise ValueError("시트가 없는 Excel 파일입니다.")

        target_sheet_name = sheet_name or sheet_names[0]
        if target_sheet_name not in sheet_names:
            target_sheet_name = sheet_names[0]

        headers = header_reader.read_headers(file_path, target_sheet_name)
        suggested_summary = self._suggest_summary(headers)
        target_summary = str(summary_column or "").strip() or suggested_summary
        if target_summary not in headers:
            target_summary = suggested_summary
        result = self.load_full_data(
            file_path,
            file_paths=file_paths,
            sheet_name=str(target_sheet_name),
            header_row=header_row,
            summary_column=target_summary,
            max_preview_rows=max_preview_rows,
        )
        result.sheet_names = list(sheet_names)
        return result
