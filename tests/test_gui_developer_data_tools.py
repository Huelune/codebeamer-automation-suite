from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from src.gui.developer_data_tools import build_read_only_query_preview
from src.gui.developer_data_tools import cache_entry_stats
from src.gui.developer_data_tools import clear_context_caches
from src.gui.developer_data_tools import diff_schema_frames
from src.gui.developer_data_tools import inspect_payload_row
from src.gui.tracker_query_models import TrackerQuery
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class DeveloperDataToolsTest(unittest.TestCase):
    def test_payload_inspection_masks_sensitive_values(self) -> None:
        payload_df = pd.DataFrame(
            [
                {
                    "_row_id": 7,
                    "payload_status": "READY",
                    "_operation": "create",
                    "payload_json": '{"name":"REQ-001","token":"secret","nested":{"password":"pw"}}',
                }
            ]
        )

        result = inspect_payload_row(payload_df, "7")

        self.assertEqual(result.row_id, "7")
        self.assertEqual(result.payload["token"], "***")
        self.assertEqual(result.payload["nested"]["password"], "***")
        self.assertNotIn("secret", result.pretty_json)

    def test_payload_inspection_sanitizes_error_text(self) -> None:
        payload_df = pd.DataFrame(
            [
                {
                    "_row_id": 7,
                    "payload": {"name": "sample"},
                    "payload_error": (
                        "authorization=Bearer secret-value "
                        "https://server.example/api/items/42"
                    ),
                }
            ]
        )

        result = inspect_payload_row(payload_df, 7)

        self.assertNotIn("secret-value", result.error)
        self.assertNotIn("server.example", result.error)
        self.assertIn("***", result.error)
        self.assertIn("<URL>", result.error)

    def test_payload_inspection_rejects_unknown_row(self) -> None:
        payload_df = pd.DataFrame([{"_row_id": 1, "payload_json": "{}"}])
        with self.assertRaisesRegex(ValueError, "찾을 수 없습니다"):
            inspect_payload_row(payload_df, 2)

    def test_payload_inspection_uses_file_and_row_as_compound_identity(self) -> None:
        payload_df = pd.DataFrame(
            [
                {
                    "source_file": "first.xlsx",
                    "source_file_path": "/safe/first.xlsx",
                    "_row_id": 1,
                    "payload": {"name": "first"},
                },
                {
                    "source_file": "second.xlsx",
                    "source_file_path": "/safe/second.xlsx",
                    "_row_id": 1,
                    "payload": {"name": "second"},
                },
            ]
        )

        with self.assertRaisesRegex(ValueError, "파일과 행"):
            inspect_payload_row(payload_df, 1)

        result = inspect_payload_row(
            payload_df,
            1,
            source_file_path="/safe/second.xlsx",
        )

        self.assertEqual(result.payload["name"], "second")

    def test_schema_diff_reports_added_removed_and_changed(self) -> None:
        before = pd.DataFrame(
            [
                {"field_id": 1, "field_name": "Summary", "field_type": "TextField", "mandatory": True},
                {"field_id": 2, "field_name": "Old", "field_type": "TextField"},
            ]
        )
        after = pd.DataFrame(
            [
                {"field_id": 1, "field_name": "Summary", "field_type": "TextField", "mandatory": False},
                {"field_id": 3, "field_name": "New", "field_type": "BoolField"},
            ]
        )

        differences = diff_schema_frames(before, after)

        self.assertEqual([difference.change for difference in differences], ["변경", "삭제", "추가"])
        self.assertEqual(differences[0].changed_properties, ("mandatory",))

    def test_schema_diff_treats_missing_dataframe_values_as_equal(self) -> None:
        before = pd.DataFrame([{"field_id": 1, "field_name": "Summary", "field_label": float("nan")}])
        after = before.copy(deep=True)

        self.assertEqual(diff_schema_frames(before, after), ())

    def test_schema_diff_reports_conditional_requirement_and_support_metadata(self) -> None:
        before = pd.DataFrame(
            [
                {
                    "field_id": 1,
                    "field_name": "Owner",
                    "mandatory": False,
                    "mandatory_mode": "conditional",
                    "mandatory_statuses": [10],
                    "mandatory_status_names": ["Open"],
                    "value_model": "MemberReferenceFieldValue",
                    "member_types": ["USER"],
                }
            ]
        )
        after = before.copy(deep=True)
        after.at[0, "mandatory_statuses"] = [20]
        after.at[0, "mandatory_status_names"] = ["Closed"]
        after.at[0, "member_types"] = ["USER", "GROUP"]

        differences = diff_schema_frames(before, after)

        self.assertEqual(len(differences), 1)
        self.assertEqual(
            differences[0].changed_properties,
            ("mandatory_statuses", "mandatory_status_names", "member_types"),
        )

    def test_cache_stats_never_exposes_keys_or_values_and_clear_is_scoped(self) -> None:
        context = SimpleNamespace(
            tracker_item_lookup_cache={("secret", "value"): (1, None, None)},
            user_lookup_cache={"secret-user": "private"},
            member_lookup_cache={},
            group_lookup_cache={"group": [1]},
            tracker_role_cache={},
            existing_item_cache={1: {"name": "private"}},
        )

        stats = cache_entry_stats(context)
        removed = clear_context_caches(context, ["user_lookup", "existing_item"])

        self.assertEqual(sum(stat.entry_count for stat in stats), 4)
        self.assertEqual(removed, 2)
        self.assertEqual(context.user_lookup_cache, {})
        self.assertEqual(context.existing_item_cache, {})
        self.assertTrue(context.tracker_item_lookup_cache)
        self.assertNotIn("secret", repr(stats))

    def test_cache_clear_rejects_unknown_cache(self) -> None:
        with self.assertRaisesRegex(ValueError, "지원하지 않는"):
            clear_context_caches(SimpleNamespace(), ["everything"])

    def test_read_only_query_preview_is_fixed_to_query_api(self) -> None:
        preview = build_read_only_query_preview(TrackerQuery(tracker_id=17, baseline_id=23))

        self.assertEqual(preview["method"], "GET")
        self.assertEqual(preview["path"], "/v3/items/query")
        self.assertTrue(preview["read_only"])
        self.assertEqual(preview["baseline_id"], 23)
        self.assertIn("tracker.id = 17", preview["cbql"])
        self.assertEqual(preview["query_params"]["baselineId"], 23)
        self.assertEqual(preview["query_params"]["pageSize"], 100)


if __name__ == "__main__":
    unittest.main()
