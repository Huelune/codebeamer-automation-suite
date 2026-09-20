from __future__ import annotations

import unittest

from src.gui.service_core import OfflineGuiClient
from src.gui.settings_store import GuiSettings
from src.gui.tracker_baseline_compare import BaselineComparisonKind
from src.gui.tracker_baseline_compare import BaselineComparisonSource
from src.gui.tracker_baseline_compare import compare_tracker_items
from src.gui.tracker_query_models import TrackerItemSummary
from src.gui.tracker_query_service import TrackerQueryService
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


def _summary(item_id: int, *, status: str = "Open", rows=None) -> TrackerItemSummary:
    raw = {
        "id": item_id,
        "name": f"Item {item_id}",
        "status": {"id": status, "name": status, "type": "ChoiceOptionReference"},
        "customFields": [
            {
                "fieldId": 10,
                "name": "Table",
                "type": "TableFieldValue",
                "value": rows if rows is not None else [["A", "1"]],
            }
        ],
    }
    return TrackerItemSummary.from_raw(raw, tracker_id=20)


class _ComparisonClient:
    search_calls: list[tuple] = []

    def __init__(self, *args, **kwargs):
        del args, kwargs

    def get_tracker_baselines(self, tracker_id):
        self.tracker_id = tracker_id
        return [{"id": 11, "name": "R1", "createdAt": "2026-01-01T00:00:00Z"}]

    def get_tracker_items_page(self, tracker_id, *, page, page_size):
        del tracker_id, page_size
        refs = [{"id": item_id, "name": f"Item {item_id}"} for item_id in (1, 2, 3)]
        start = (page - 1) * 2
        return {"page": page, "pageSize": 2, "total": len(refs), "itemRefs": refs[start : start + 2]}

    def get_tracker_items(self, tracker_id):
        return self.get_tracker_items_page(tracker_id, page=1, page_size=500)["itemRefs"]

    def get_item(self, item_id, baseline_id=None):
        items = {
            None: {1: _summary(1).raw_reference, 2: _summary(2).raw_reference},
            11: {1: _summary(1, status="Draft").raw_reference, 3: _summary(3).raw_reference},
        }[baseline_id]
        if item_id not in items:
            raise KeyError(item_id)
        return items[item_id]

    def search_items(
        self,
        *,
        query_string,
        baseline_id=None,
        page=1,
        page_size=500,
    ):
        self.__class__.search_calls.append(
            (query_string, baseline_id, page, page_size)
        )
        items = {
            None: [_summary(1).raw_reference, _summary(2).raw_reference],
            11: [
                _summary(1, status="Draft").raw_reference,
                _summary(3).raw_reference,
            ],
        }[baseline_id]
        start = (page - 1) * page_size
        return {
            "page": page,
            "pageSize": page_size,
            "total": len(items),
            "items": items[start : start + page_size],
        }


class TrackerBaselineComparisonTest(unittest.TestCase):
    def test_offline_client_uses_baseline_snapshot(self):
        query_data = {
            "version": 1,
            "projects": [{"id": 1, "name": "Project"}],
            "trackers": [{"id": 20, "name": "Tracker", "projectId": 1}],
            "items": [{"id": 1, "name": "Current", "trackerId": 20, "customFields": []}],
            "baselines": [{
                "id": 11,
                "name": "R1",
                "trackerId": 20,
                "items": [{"id": 1, "name": "Baseline", "customFields": []}],
            }],
        }
        client = OfflineGuiClient(schema={}, schema_path="sample.json", query_data=query_data)
        self.assertEqual(client.get_tracker_baselines(20)[0]["id"], 11)
        result = client.search_items(
            query_string="tracker.id = 20 ORDER BY item.id ASC",
            baseline_id=11,
        )
        self.assertEqual(result["items"][0]["name"], "Baseline")

    def test_table_field_row_order_is_a_change(self):
        result = compare_tracker_items(
            (_summary(1, rows=[["A", "1"], ["B", "2"]]),),
            (_summary(1, rows=[["B", "2"], ["A", "1"]]),),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        self.assertEqual(result.items[0].kind, BaselineComparisonKind.CHANGED)
        table_field = next(
            field for field in result.items[0].fields if field.field_key == "custom:10"
        )
        self.assertEqual(table_field.label, "Table")
        self.assertTrue(table_field.is_changed)

    def test_comparison_classifies_added_removed_and_changed(self):
        result = compare_tracker_items(
            (_summary(1, status="Draft"), _summary(2)),
            (_summary(1), _summary(3)),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        self.assertEqual([item.kind for item in result.items], [
            BaselineComparisonKind.CHANGED,
            BaselineComparisonKind.REMOVED,
            BaselineComparisonKind.ADDED,
        ])

    def test_service_lists_baselines_and_compares_only_selected_item(self):
        settings = GuiSettings(base_url="https://example.invalid", username="sample", password="sample")
        service = TrackerQueryService(client_factory=_ComparisonClient)
        baselines = service.load_tracker_baselines(settings, 20)
        self.assertEqual([(baseline.baseline_id, baseline.name) for baseline in baselines], [(11, "R1")])
        result = service.compare_item_at_sources(
            settings,
            1,
            20,
            reference_source=BaselineComparisonSource(None),
            comparison_source=BaselineComparisonSource(11),
        )
        self.assertEqual(result.count(BaselineComparisonKind.CHANGED), 1)
        status_field = next(
            field for field in result.items[0].fields if field.field_key == "status"
        )
        self.assertEqual(status_field.before, {"id": "Draft", "name": "Draft", "type": "ChoiceOptionReference"})
        self.assertEqual(status_field.after, {"id": "Open", "name": "Open", "type": "ChoiceOptionReference"})
        self.assertTrue(status_field.is_changed)

    def test_service_compares_entire_tracker_with_query_sources(self):
        _ComparisonClient.search_calls = []
        settings = GuiSettings(base_url="https://example.invalid", username="sample", password="sample")
        service = TrackerQueryService(client_factory=_ComparisonClient)

        result = service.compare_tracker_at_sources(
            settings,
            20,
            reference_source=BaselineComparisonSource(None),
            comparison_source=BaselineComparisonSource(11),
        )

        self.assertEqual(
            [item.kind for item in result.items],
            [
                BaselineComparisonKind.CHANGED,
                BaselineComparisonKind.ADDED,
                BaselineComparisonKind.REMOVED,
            ],
        )
        self.assertEqual(
            [(call[1], call[2], call[3]) for call in _ComparisonClient.search_calls],
            [(None, 1, 500), (11, 1, 500)],
        )

    def test_reference_only_item_is_classified_as_added(self):
        settings = GuiSettings(base_url="https://example.invalid", username="sample", password="sample")
        service = TrackerQueryService(client_factory=_ComparisonClient)

        result = service.compare_item_at_sources(
            settings,
            2,
            20,
            reference_source=BaselineComparisonSource(None),
            comparison_source=BaselineComparisonSource(11),
        )

        self.assertEqual(result.items[0].kind, BaselineComparisonKind.ADDED)
        self.assertTrue(result.items[0].fields)
        self.assertTrue(all(field.is_changed for field in result.items[0].fields))

    def test_comparison_only_item_is_classified_as_removed(self):
        settings = GuiSettings(base_url="https://example.invalid", username="sample", password="sample")
        service = TrackerQueryService(client_factory=_ComparisonClient)

        result = service.compare_item_at_sources(
            settings,
            3,
            20,
            reference_source=BaselineComparisonSource(None),
            comparison_source=BaselineComparisonSource(11),
        )

        self.assertEqual(result.items[0].kind, BaselineComparisonKind.REMOVED)
        self.assertTrue(result.items[0].fields)
        self.assertTrue(all(field.is_changed for field in result.items[0].fields))

    def test_schema_resolves_custom_field_name_type_and_table_columns(self):
        before = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item",
                "customFields": [
                    {
                        "fieldId": 1000,
                        "name": "응답 이름",
                        "value": [[{"fieldId": 1001, "value": "이전"}]],
                    }
                ],
            }
        )
        after = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item",
                "customFields": [
                    {
                        "fieldId": 1000,
                        "name": "응답 이름",
                        "value": [[{"fieldId": 1001, "value": "현재"}]],
                    }
                ],
            }
        )
        schema = {
            "fields": [
                {
                    "id": 1000,
                    "name": "검토 결과",
                    "type": "TableField",
                    "valueModel": "TableFieldValue",
                    "columns": [{"id": 1001, "name": "판정"}],
                }
            ]
        }

        result = compare_tracker_items(
            (before,),
            (after,),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
            tracker_schema=schema,
        )
        field = next(
            field for field in result.items[0].fields if field.field_key == "custom:1000"
        )

        self.assertEqual(field.label, "검토 결과")
        self.assertNotIn("custom:1000", field.label)
        self.assertTrue(field.is_table)
        self.assertEqual([column.label for column in field.table_columns], ["판정"])

    def test_custom_field_name_falls_back_without_schema_or_response_name(self):
        result = compare_tracker_items(
            (),
            (
                TrackerItemSummary.from_raw(
                    {
                        "id": 1,
                        "name": "Item",
                        "customFields": [{"fieldId": 1000, "value": "값"}],
                    }
                ),
            ),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
            tracker_schema={"fields": []},
        )
        field = next(
            field for field in result.items[0].fields if field.field_key == "custom:1000"
        )

        self.assertEqual(field.label, "사용자 정의 필드 #1000")

    def test_removed_custom_field_uses_response_name_without_exposing_internal_key(self):
        result = compare_tracker_items(
            (
                TrackerItemSummary.from_raw(
                    {
                        "id": 1,
                        "name": "Item",
                        "customFields": [
                            {"fieldId": 1000, "name": "검토 결과", "value": "값"}
                        ],
                    }
                ),
            ),
            (),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        field = next(
            field for field in result.items[0].fields if field.field_key == "custom:1000"
        )

        self.assertEqual(field.label, "검토 결과")
        self.assertNotIn("custom:1000", field.label)

    def test_comparison_includes_unchanged_and_unknown_response_fields(self):
        before = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item 1",
                "version": 1,
                "modifiedAt": "2026-01-01T00:00:00Z",
                "unknownMetadata": {"flag": True},
                "customFields": [],
            },
            tracker_id=20,
        )
        after = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item 1",
                "version": 2,
                "modifiedAt": "2026-01-02T00:00:00Z",
                "unknownMetadata": {"flag": True},
                "customFields": [],
            },
            tracker_id=20,
        )

        result = compare_tracker_items(
            (before,),
            (after,),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )

        fields = {field.field_key: field for field in result.items[0].fields}
        self.assertEqual(
            set(fields),
            {"id", "name", "version", "modifiedAt", "unknownMetadata"},
        )
        self.assertFalse(fields["id"].is_changed)
        self.assertFalse(fields["name"].is_changed)
        self.assertFalse(fields["unknownMetadata"].is_changed)
        self.assertTrue(fields["version"].is_changed)
        self.assertTrue(fields["modifiedAt"].is_changed)
        self.assertEqual(fields["unknownMetadata"].after_text(), "flag: 예")
        self.assertNotIn("{", fields["unknownMetadata"].after_text())

    def test_comparison_values_are_formatted_for_general_users(self):
        before = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item 1",
                "descriptionFormat": "PlainText",
                "tracker": {"id": 20, "name": "Requirements", "type": "TrackerReference"},
                "assignedTo": [
                    {"id": 7, "name": "Sample User", "type": "UserReference"}
                ],
                "customFields": [
                    {
                        "fieldId": 10,
                        "name": "검증 표",
                        "type": "TableFieldValue",
                        "value": [["조건 A", True], ["조건 B", False]],
                    }
                ],
            }
        )
        after = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item 1",
                "descriptionFormat": "PlainText",
                "tracker": {"id": 20, "name": "Requirements", "type": "TrackerReference"},
                "assignedTo": [
                    {"id": 7, "name": "Sample User", "type": "UserReference"}
                ],
                "customFields": [
                    {
                        "fieldId": 10,
                        "name": "검증 표",
                        "type": "TableFieldValue",
                        "value": [["조건 A", True], ["조건 B", True]],
                    }
                ],
            }
        )

        result = compare_tracker_items(
            (before,),
            (after,),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )

        fields = {field.field_key: field for field in result.items[0].fields}
        self.assertEqual(fields["descriptionFormat"].after_text(), "일반 텍스트")
        self.assertEqual(fields["tracker"].after_text(), "Requirements (ID 20)")
        self.assertEqual(fields["assignedTo"].after_text(), "• Sample User (ID 7)")
        self.assertEqual(
            fields["custom:10"].after_text(),
            "행 1: 열 1=조건 A | 열 2=예\n행 2: 열 1=조건 B | 열 2=예",
        )
        self.assertNotIn("TrackerReference", fields["tracker"].after_text())
        self.assertNotIn("{", fields["assignedTo"].after_text())

    def test_reference_display_name_does_not_create_false_change(self):
        before = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item 1",
                "tracker": {"id": 20, "name": "Old tracker name"},
            },
            tracker_id=20,
        )
        after = TrackerItemSummary.from_raw(
            {
                "id": 1,
                "name": "Item 1",
                "tracker": {"id": 20, "name": "New tracker name"},
            },
            tracker_id=20,
        )

        result = compare_tracker_items(
            (before,),
            (after,),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )

        tracker_field = next(
            field for field in result.items[0].fields if field.field_key == "tracker"
        )
        self.assertEqual(result.items[0].kind, BaselineComparisonKind.UNCHANGED)
        self.assertFalse(tracker_field.is_changed)
        self.assertIn("Old tracker name", tracker_field.before_text())
        self.assertIn("New tracker name", tracker_field.after_text())

    def test_baseline_list_accepts_tracker_baselines_container(self):
        items = TrackerQueryService._extract_baselines(
            {"data": {"trackerBaselines": [{"id": 11, "name": "R1"}]}}
        )
        self.assertEqual(items, [{"id": 11, "name": "R1"}])

    def test_baseline_list_accepts_paged_references_container(self):
        items = TrackerQueryService._extract_baselines(
            {
                "page": 1,
                "pageSize": 100,
                "total": 1,
                "references": [{"id": 11, "name": "R1", "type": "BaselineReference"}],
            }
        )
        self.assertEqual(items[0]["id"], 11)


if __name__ == "__main__":
    unittest.main()
