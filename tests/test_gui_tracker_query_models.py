from __future__ import annotations

import unittest

from src.gui.tracker_query_models import LoadState
from src.gui.tracker_query_models import PageResult
from src.gui.tracker_query_models import TrackerItemDetail
from src.gui.tracker_query_models import TrackerItemSummary
from src.gui.tracker_query_models import TrackerQuery
from src.gui.tracker_query_models import TrackerQueryCondition
from src.gui.tracker_query_models import TrackerQueryGroup
from src.gui.tracker_query_models import TrackerSearchMode
from src.gui.tracker_query_models import mask_sensitive_payload
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class TrackerQueryModelTest(unittest.TestCase):
    def test_simple_query_always_adds_tracker_scope_and_server_sort(self) -> None:
        query = TrackerQuery(
            tracker_id=42,
            text="Steering",
            status="Open",
            assignee="sample_user_a",
            sort="modifiedAt DESC, item.id ASC",
        )

        cbql = query.build_cbql()

        self.assertTrue(cbql.startswith("tracker.id = 42 AND ("))
        self.assertIn("summary LIKE '%Steering%'", cbql)
        self.assertIn("status = 'Open'", cbql)
        self.assertIn("assignedTo = 'sample_user_a'", cbql)
        self.assertTrue(cbql.endswith("ORDER BY modifiedAt DESC, item.id ASC"))

    def test_numeric_simple_query_matches_id_or_summary_inside_current_tracker(self) -> None:
        query = TrackerQuery(tracker_id=42, text="9001001")

        self.assertEqual(
            query.build_cbql(),
            "tracker.id = 42 AND ((item.id = 9001001 OR summary LIKE '%9001001%')) "
            "ORDER BY item.id ASC",
        )

    def test_condition_groups_use_and_inside_group_and_or_between_groups(self) -> None:
        query = TrackerQuery(
            tracker_id=42,
            mode=TrackerSearchMode.CONDITIONS,
            groups=(
                TrackerQueryGroup(
                    (
                        TrackerQueryCondition("status", "equals", "Open"),
                        TrackerQueryCondition("Priority", "in", ["High", "Critical"]),
                    )
                ),
                TrackerQueryGroup(
                    (TrackerQueryCondition("summary", "contains", "Brake"),)
                ),
            ),
        )

        cbql = query.build_cbql()

        self.assertIn("(status = 'Open' AND Priority IN ('High', 'Critical'))", cbql)
        self.assertIn("OR (summary LIKE '%Brake%')", cbql)
        self.assertTrue(cbql.startswith("tracker.id = 42 AND ("))

    def test_empty_condition_groups_are_not_executed_as_tracker_wide_search(self) -> None:
        query = TrackerQuery(
            tracker_id=42,
            mode=TrackerSearchMode.CONDITIONS,
            groups=(TrackerQueryGroup(),),
        )

        with self.assertRaisesRegex(ValueError, "하나 이상의 완성된 조건"):
            query.build_cbql()

    def test_expert_cbql_keeps_user_order_but_forces_selected_tracker(self) -> None:
        query = TrackerQuery(
            tracker_id=42,
            mode=TrackerSearchMode.CBQL,
            cbql="tracker.id = 77 AND status = 'Open' ORDER BY modifiedAt DESC",
        )

        self.assertEqual(
            query.build_cbql(),
            "tracker.id = 42 AND (tracker.id = 77 AND status = 'Open') "
            "ORDER BY modifiedAt DESC",
        )

    def test_expert_cbql_rejects_multi_statement_and_grouped_projection(self) -> None:
        with self.assertRaisesRegex(ValueError, "한 개의 조건식"):
            TrackerQuery(
                tracker_id=42,
                mode=TrackerSearchMode.CBQL,
                cbql="status = 'Open'; tracker.id = 77",
            ).build_cbql()

        with self.assertRaisesRegex(ValueError, "SELECT 또는 GROUP BY"):
            TrackerQuery(
                tracker_id=42,
                mode=TrackerSearchMode.CBQL,
                cbql="SELECT status WHERE status = 'Open' GROUP BY status",
            ).build_cbql()

    def test_page_result_preserves_server_and_requested_pagination(self) -> None:
        result = PageResult.create(
            ["first", "second"],
            raw_page={"page": 2, "pageSize": 2, "total": 5, "baseline": 100},
            requested_page=2,
            requested_page_size=20,
        )

        self.assertEqual(result.items, ("first", "second"))
        self.assertEqual(result.page, 2)
        self.assertEqual(result.page_size, 2)
        self.assertEqual(result.total, 5)
        self.assertEqual(result.requested_page_size, 20)
        self.assertTrue(result.has_previous)
        self.assertTrue(result.has_next)
        self.assertFalse(result.server_honored_pagination)
        self.assertEqual(result.load_state, LoadState.LOADED)
        self.assertEqual(result.server_metadata["baseline"], 100)

    def test_detail_normalizes_builtin_custom_hierarchy_and_masks_raw_secrets(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1001,
                "name": "Requirement",
                "description": "Details",
                "descriptionFormat": "PlainText",
                "version": 3,
                "tracker": {"id": 200, "name": "Requirements"},
                "status": {"id": 1, "name": "Open"},
                "assignedTo": [{"id": 7, "name": "sample_user"}],
                "parent": {"id": 1000, "name": "Root"},
                "children": [{"id": 1002, "name": "Child"}],
                "customFields": [
                    {
                        "fieldId": 90,
                        "name": "Risk",
                        "type": "TextFieldValue",
                        "value": "High",
                    }
                ],
                "authorization": "Basic hidden-value",
            },
            tracker_payload={
                "id": 200,
                "name": "Requirements",
                "project": {"id": 20, "name": "Vehicle"},
            },
        )

        self.assertEqual(detail.item_id, 1001)
        self.assertEqual(detail.summary.project_id, 20)
        self.assertEqual(detail.summary.status, "Open")
        self.assertEqual(detail.summary.assignees, ("sample_user",))
        self.assertEqual(detail.parent.item_id, 1000)
        self.assertEqual(detail.children[0].item_id, 1002)
        self.assertEqual(detail.custom_fields[0].display_value, "High")
        self.assertEqual(detail.raw_payload["authorization"], "***")
        self.assertNotIn("authorization", detail.normalized_payload())

    def test_item_summary_keeps_unknown_children_distinct_from_known_empty(self) -> None:
        unknown = TrackerItemSummary.from_raw({"id": 1, "name": "Unknown"})
        empty = TrackerItemSummary.from_raw(
            {"id": 2, "name": "Empty", "childCount": 0, "hasChildren": False}
        )

        self.assertIsNone(unknown.child_count)
        self.assertFalse(unknown.has_children)
        self.assertEqual(empty.child_count, 0)

    def test_sensitive_masking_is_recursive_and_does_not_mutate_source(self) -> None:
        source = {
            "nested": [
                {
                    "token": "value",
                    "accessToken": "camel-secret",
                    "name": "safe",
                }
            ]
        }

        masked = mask_sensitive_payload(source)

        self.assertEqual(masked["nested"][0]["token"], "***")
        self.assertEqual(masked["nested"][0]["accessToken"], "***")
        self.assertEqual(masked["nested"][0]["name"], "safe")
        self.assertEqual(source["nested"][0]["token"], "value")


if __name__ == "__main__":
    unittest.main()
