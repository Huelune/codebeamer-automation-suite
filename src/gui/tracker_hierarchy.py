from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .tracker_query_models import TrackerItemSummary


class TrackerHierarchyError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrackerHierarchyNode:
    item: TrackerItemSummary
    parent_id: int | None
    depth: int


@dataclass(frozen=True)
class TrackerHierarchySnapshot:
    tracker_id: int
    nodes: tuple[TrackerHierarchyNode, ...]


def build_tracker_hierarchy(
    items: Iterable[TrackerItemSummary],
    *,
    tracker_id: int,
    root_ids: Iterable[int] | None = None,
) -> TrackerHierarchySnapshot:
    """전체 item의 parent/children/ordinal로 검증된 계층 순서를 만든다."""
    normalized_tracker_id = int(tracker_id)
    item_by_id: dict[int, TrackerItemSummary] = {}
    for item in items:
        if item.item_id in item_by_id:
            raise TrackerHierarchyError(
                f"전체 조회 결과에 아이템 #{item.item_id}가 중복되었습니다."
            )
        if item.tracker_id is not None and int(item.tracker_id) != normalized_tracker_id:
            raise TrackerHierarchyError(
                f"전체 조회 결과에 다른 트래커의 아이템 #{item.item_id}가 포함되었습니다."
            )
        item_by_id[item.item_id] = item

    supplied_roots = root_ids is not None
    ordered_root_ids: list[int] = []
    if supplied_roots:
        for raw_root_id in root_ids or ():
            root_id = int(raw_root_id)
            if root_id not in item_by_id:
                raise TrackerHierarchyError(
                    f"최상위 아이템 #{root_id}가 전체 조회 결과에 없습니다."
                )
            if root_id not in ordered_root_ids:
                ordered_root_ids.append(root_id)
        if item_by_id and not ordered_root_ids:
            raise TrackerHierarchyError(
                "전체 조회 결과는 있지만 최상위 아이템을 확인할 수 없습니다."
            )

    parent_by_id: dict[int, int | None] = dict.fromkeys(ordered_root_ids)
    explicit_child_order: dict[int, list[int]] = {}

    def assign_parent(child_id: int, parent_id: int, *, source: str) -> None:
        if child_id not in item_by_id:
            raise TrackerHierarchyError(
                f"{source}가 현재 트래커에 없는 아이템 #{child_id}를 참조합니다."
            )
        if parent_id not in item_by_id:
            raise TrackerHierarchyError(
                f"아이템 #{child_id}의 상위 아이템 #{parent_id}가 전체 조회 결과에 없습니다."
            )
        if supplied_roots and child_id in ordered_root_ids:
            raise TrackerHierarchyError(
                f"최상위 아이템 #{child_id}에 상위 아이템 #{parent_id} 참조가 함께 있습니다."
            )
        existing = parent_by_id.get(child_id)
        if existing is not None and existing != parent_id:
            raise TrackerHierarchyError(
                f"아이템 #{child_id}가 두 개의 상위 아이템 #{existing}, #{parent_id}를 참조합니다."
            )
        parent_by_id[child_id] = parent_id

    for item in item_by_id.values():
        raw_children = item.raw_reference.get("children")
        if not isinstance(raw_children, list):
            continue
        ordered: list[int] = []
        for raw_child in raw_children:
            child_id = _reference_id(raw_child)
            if child_id is None or child_id in ordered:
                continue
            assign_parent(
                child_id,
                item.item_id,
                source=f"아이템 #{item.item_id}의 children",
            )
            ordered.append(child_id)
        explicit_child_order[item.item_id] = ordered

    for item in item_by_id.values():
        raw_parent = item.raw_reference.get("parent")
        parent_id = item.parent_id or _reference_id(raw_parent)
        if parent_id is None:
            parent_id = _optional_positive_int(item.raw_reference.get("parentId"))
        if parent_id is not None:
            assign_parent(item.item_id, parent_id, source=f"아이템 #{item.item_id}의 parent")

    if supplied_roots:
        unresolved = sorted(item_id for item_id in item_by_id if item_id not in parent_by_id)
        if unresolved:
            preview = ", ".join(f"#{item_id}" for item_id in unresolved[:8])
            suffix = " 외" if len(unresolved) > 8 else ""
            raise TrackerHierarchyError(
                f"상위 관계를 확인할 수 없는 아이템이 있습니다: {preview}{suffix}. "
                "전체 query 응답의 parent/children 정보를 확인하세요."
            )
    else:
        ordered_root_ids = sorted(
            (item_id for item_id in item_by_id if item_id not in parent_by_id),
            key=lambda item_id: _sibling_sort_key(item_by_id[item_id]),
        )
        for root_id in ordered_root_ids:
            parent_by_id[root_id] = None

    for start_id in item_by_id:
        chain: set[int] = set()
        current_id: int | None = start_id
        while current_id is not None:
            if current_id in chain:
                raise TrackerHierarchyError(
                    f"아이템 #{current_id}에서 순환 계층을 발견했습니다."
                )
            chain.add(current_id)
            current_id = parent_by_id[current_id]

    if item_by_id and not ordered_root_ids:
        raise TrackerHierarchyError("전체 조회 결과에서 최상위 아이템을 확인할 수 없습니다.")

    children_by_parent: dict[int, list[int]] = {item_id: [] for item_id in item_by_id}
    for child_id, parent_id in parent_by_id.items():
        if parent_id is not None:
            children_by_parent[parent_id].append(child_id)
    for parent_id, child_ids in children_by_parent.items():
        explicit = explicit_child_order.get(parent_id, [])
        explicit_set = set(explicit)
        ordered = [child_id for child_id in explicit if child_id in child_ids]
        remaining = [child_id for child_id in child_ids if child_id not in explicit_set]
        remaining.sort(key=lambda item_id: _sibling_sort_key(item_by_id[item_id]))
        children_by_parent[parent_id] = [*ordered, *remaining]

    nodes: list[TrackerHierarchyNode] = []
    visited: set[int] = set()

    def visit(item_id: int, depth: int) -> None:
        if item_id in visited:
            raise TrackerHierarchyError(f"아이템 #{item_id}가 계층에 두 번 연결되었습니다.")
        visited.add(item_id)
        nodes.append(TrackerHierarchyNode(item_by_id[item_id], parent_by_id[item_id], depth))
        for child_id in children_by_parent[item_id]:
            visit(child_id, depth + 1)

    for root_id in ordered_root_ids:
        visit(root_id, 0)
    if len(visited) != len(item_by_id):
        missing = sorted(set(item_by_id) - visited)
        preview = ", ".join(f"#{item_id}" for item_id in missing[:8])
        raise TrackerHierarchyError(
            f"최상위 계층에서 도달할 수 없는 아이템이 있습니다: {preview}."
        )
    return TrackerHierarchySnapshot(normalized_tracker_id, tuple(nodes))


def _reference_id(value: Any) -> int | None:
    if isinstance(value, dict):
        return _optional_positive_int(value.get("id"))
    return _optional_positive_int(value)


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _sibling_sort_key(item: TrackerItemSummary) -> tuple[bool, int, int]:
    ordinal = _optional_nonnegative_int(item.raw_reference.get("ordinal"))
    return (ordinal is None, ordinal or 0, item.item_id)


def _optional_nonnegative_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


__all__ = [
    "TrackerHierarchyError",
    "TrackerHierarchyNode",
    "TrackerHierarchySnapshot",
    "build_tracker_hierarchy",
]
