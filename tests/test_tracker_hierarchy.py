from __future__ import annotations

import unittest

from src.gui.tracker_hierarchy import TrackerHierarchyError
from src.gui.tracker_hierarchy import build_tracker_hierarchy
from src.gui.tracker_query_models import TrackerItemSummary
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


def _item(
    item_id: int,
    name: str,
    *,
    parent_id: int | None = None,
    children: tuple[int, ...] = (),
    ordinal: int | None = None,
    tracker_id: int = 20,
) -> TrackerItemSummary:
    raw = {
        "id": item_id,
        "name": name,
        "tracker": {"id": tracker_id},
        "children": [{"id": child_id} for child_id in children],
    }
    if parent_id is not None:
        raw["parent"] = {"id": parent_id}
    if ordinal is not None:
        raw["ordinal"] = ordinal
    return TrackerItemSummary.from_raw(raw, tracker_id=tracker_id)


class TrackerHierarchyTest(unittest.TestCase):
    def test_derives_roots_and_preserves_explicit_child_order(self) -> None:
        root_b = _item(2, "Root B", ordinal=1)
        root_a = _item(1, "Root A", children=(4, 3), ordinal=2)
        child_a = _item(3, "Child A", parent_id=1, ordinal=1)
        child_b = _item(4, "Child B", parent_id=1, ordinal=2)

        snapshot = build_tracker_hierarchy(
            (child_a, root_a, child_b, root_b),
            tracker_id=20,
        )

        self.assertEqual(
            [(node.item.item_id, node.parent_id, node.depth) for node in snapshot.nodes],
            [(2, None, 0), (1, None, 0), (4, 1, 1), (3, 1, 1)],
        )

    def test_rejects_conflicting_parents(self) -> None:
        first = _item(1, "First", children=(3,))
        second = _item(2, "Second", children=(3,))
        child = _item(3, "Child", parent_id=1)

        with self.assertRaisesRegex(TrackerHierarchyError, "두 개의 상위"):
            build_tracker_hierarchy((first, second, child), tracker_id=20)

    def test_rejects_cycle_without_derived_root(self) -> None:
        first = _item(1, "First", parent_id=2)
        second = _item(2, "Second", parent_id=1)

        with self.assertRaisesRegex(TrackerHierarchyError, "순환 계층"):
            build_tracker_hierarchy((first, second), tracker_id=20)

    def test_rejects_missing_and_cross_tracker_references(self) -> None:
        with self.assertRaisesRegex(TrackerHierarchyError, "전체 조회 결과에 없습니다"):
            build_tracker_hierarchy((_item(1, "Child", parent_id=9),), tracker_id=20)

        with self.assertRaisesRegex(TrackerHierarchyError, "다른 트래커"):
            build_tracker_hierarchy((_item(1, "Other", tracker_id=21),), tracker_id=20)


if __name__ == "__main__":
    unittest.main()
