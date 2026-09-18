from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from src.gui.settings_store import GuiSettings
from src.gui.tracker_query_models import TrackerQuery
from src.gui.tracker_query_models import TrackerQueryCondition
from src.gui.tracker_query_models import TrackerQueryErrorKind
from src.gui.tracker_query_models import TrackerQueryGroup
from src.gui.tracker_query_models import TrackerQueryServiceError
from src.gui.tracker_query_models import TrackerSearchMode
from src.gui.tracker_query_service import TrackerQueryService
from src.gui.tracker_query_service import classify_tracker_query_error
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "gui-offline-sample"


class QueryFakeClient:
    calls: list[tuple] = []

    def __init__(self, base_url, username, password, logger=None, **kwargs) -> None:
        del base_url, username, password, logger, kwargs

    @classmethod
    def reset(cls) -> None:
        cls.calls = []

    def get_projects(self):
        self.__class__.calls.append(("projects",))
        return [{"id": 10, "name": "Vehicle"}]

    def get_trackers(self, project_id: int):
        self.__class__.calls.append(("trackers", project_id))
        return [{"id": 20, "name": "Requirements"}]

    def get_tracker(self, tracker_id: int):
        self.__class__.calls.append(("tracker", tracker_id))
        return {
            "id": tracker_id,
            "name": "Requirements",
            "project": {"id": 10, "name": "Vehicle"},
        }

    def get_tracker_schema(self, tracker_id: int):
        self.__class__.calls.append(("schema", tracker_id))
        return {"id": tracker_id, "fields": [{"id": 1, "name": "Summary"}]}

    def get_tracker_children_page(self, tracker_id: int, *, page: int, page_size: int):
        self.__class__.calls.append(("roots", tracker_id, page, page_size))
        return {
            "page": page,
            "pageSize": page_size,
            "total": 2,
            "itemRefs": [
                {"id": 1001, "name": "Root A", "hasChildren": True},
                {"id": 1002, "name": "Root B", "hasChildren": False},
            ],
        }

    def get_item_children_page(self, item_id: int, *, page: int, page_size: int):
        self.__class__.calls.append(("children", item_id, page, page_size))
        return {
            "page": page,
            "pageSize": page_size,
            "total": 1,
            "itemRefs": [{"id": 1010, "name": "Child"}],
        }

    def search_items(
        self,
        *,
        query_string: str,
        baseline_id=None,
        page: int,
        page_size: int,
    ):
        self.__class__.calls.append(
            ("search", query_string, baseline_id, page, page_size)
        )
        tracker_id = int(re.search(r"tracker\.id = (\d+)", query_string).group(1))
        return {
            "page": page,
            "pageSize": page_size,
            "total": 1,
            "items": [
                {
                    "id": 1001,
                    "name": "Steering",
                    "tracker": {"id": tracker_id, "name": "Requirements"},
                    "status": {"id": 1, "name": "Open"},
                }
            ],
        }

    def get_item(self, item_id: int):
        self.__class__.calls.append(("item", item_id))
        return {
            "id": item_id,
            "name": "Steering",
            "description": "Description",
            "descriptionFormat": "PlainText",
            "version": 4,
            "tracker": {"id": 20, "name": "Requirements"},
            "status": {"id": 1, "name": "Open"},
            "assignedTo": [{"id": 7, "name": "sample_user"}],
            "children": [{"id": 1003, "name": "Nested"}],
            "customFields": [
                {
                    "fieldId": 90,
                    "name": "Risk",
                    "type": "TextFieldValue",
                    "value": "High",
                }
            ],
            "password": "must-not-leak",
        }


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _HttpError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code} with unsafe server detail")
        self.response = _Response(status_code)


class ForbiddenFakeClient(QueryFakeClient):
    def get_projects(self):
        raise _HttpError(403)


class LeakingSearchFakeClient(QueryFakeClient):
    def search_items(self, **kwargs):
        payload = super().search_items(**kwargs)
        payload["items"].append(
            {
                "id": 9999,
                "name": "Other tracker item",
                "tracker": {"id": 99, "name": "Other"},
            }
        )
        payload["total"] = 2
        return payload


class PaginatedSearchClient(QueryFakeClient):
    def search_items(self, *, query_string, baseline_id=None, page, page_size):
        del baseline_id
        tracker_id = int(re.search(r"tracker\.id = (\d+)", query_string).group(1))
        start = (page - 1) * page_size
        ids = list(range(1, 1202))[start : start + page_size]
        return {
            "page": page,
            "pageSize": page_size,
            "total": 1201,
            "items": [
                {
                    "id": item_id,
                    "name": f"Item {item_id}",
                    "tracker": {"id": tracker_id},
                }
                for item_id in ids
            ],
        }


class TrackerMetadataFailureFakeClient(QueryFakeClient):
    def get_tracker(self, tracker_id: int):
        raise _HttpError(403)


class TrackerQueryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        QueryFakeClient.reset()
        self.settings = GuiSettings(
            base_url="https://example.test/cb",
            username="sample",
            password="placeholder",
        )
        self.service = TrackerQueryService(client_factory=QueryFakeClient)

    def test_context_lists_are_normalized_without_exposing_server_dicts(self) -> None:
        projects = self.service.load_projects(self.settings)
        trackers = self.service.load_trackers(
            self.settings,
            projects[0].project_id,
            project_name=projects[0].name,
        )

        self.assertEqual(projects[0].project_id, 10)
        self.assertEqual(trackers[0].tracker_id, 20)
        self.assertEqual(trackers[0].project_id, 10)
        self.assertEqual(trackers[0].project_name, "Vehicle")

    def test_hierarchy_uses_root_and_direct_child_endpoints_with_server_metadata(self) -> None:
        roots = self.service.load_top_level_items(
            self.settings,
            20,
            tracker_name="Requirements",
            project_id=10,
            page=2,
            page_size=25,
        )
        children = self.service.load_child_items(
            self.settings,
            1001,
            tracker_id=20,
            page=1,
            page_size=10,
        )

        self.assertIn(("roots", 20, 2, 25), QueryFakeClient.calls)
        self.assertIn(("children", 1001, 1, 10), QueryFakeClient.calls)
        self.assertEqual(roots.page, 2)
        self.assertEqual(roots.total, 2)
        self.assertTrue(roots.items[0].has_children)
        self.assertEqual(children.items[0].parent_id, 1001)
        self.assertEqual(children.items[0].tracker_id, 20)

    def test_tracker_schema_accepts_v3_field_array_response(self) -> None:
        class ArraySchemaClient(QueryFakeClient):
            def get_tracker_schema(self, tracker_id: int):
                self.__class__.calls.append(("schema", tracker_id))
                return [
                    {
                        "id": 3,
                        "name": "Summary",
                        "type": "TextField",
                        "valueModel": "TextFieldValue",
                        "trackerItemField": "name",
                    }
                ]

        ArraySchemaClient.reset()
        service = TrackerQueryService(client_factory=ArraySchemaClient)

        schema = service.load_tracker_schema(self.settings, 20)

        self.assertEqual(schema["id"], 20)
        self.assertEqual(schema["fields"][0]["name"], "Summary")
        self.assertIn(("schema", 20), ArraySchemaClient.calls)

    def test_hierarchy_all_loaders_collect_every_server_page(self) -> None:
        class PagedHierarchyClient(QueryFakeClient):
            roots = [
                {"id": item_id, "name": f"Root {item_id}"}
                for item_id in range(1001, 1006)
            ]
            children = [
                {"id": item_id, "name": f"Child {item_id}"}
                for item_id in range(2001, 2005)
            ]

            @staticmethod
            def _page(items, page: int, page_size: int):
                start = (page - 1) * page_size
                return {
                    "page": page,
                    "pageSize": page_size,
                    "total": len(items),
                    "itemRefs": items[start : start + page_size],
                }

            def get_tracker_children_page(
                self,
                tracker_id: int,
                *,
                page: int,
                page_size: int,
            ):
                self.__class__.calls.append(("roots", tracker_id, page, page_size))
                return self._page(self.roots, page, page_size)

            def get_item_children_page(
                self,
                item_id: int,
                *,
                page: int,
                page_size: int,
            ):
                self.__class__.calls.append(("children", item_id, page, page_size))
                return self._page(self.children, page, page_size)

        PagedHierarchyClient.reset()
        service = TrackerQueryService(client_factory=PagedHierarchyClient)

        roots = service.load_all_top_level_items(self.settings, 20, page_size=2)
        children = service.load_all_child_items(
            self.settings,
            1001,
            tracker_id=20,
            page_size=2,
        )

        self.assertEqual([item.item_id for item in roots], [1001, 1002, 1003, 1004, 1005])
        self.assertEqual([item.item_id for item in children], [2001, 2002, 2003, 2004])
        self.assertEqual(
            [call[2] for call in PagedHierarchyClient.calls if call[0] == "roots"],
            [1, 2, 3],
        )
        self.assertEqual(
            [call[2] for call in PagedHierarchyClient.calls if call[0] == "children"],
            [1, 2],
        )

    def test_hierarchy_export_snapshot_uses_bulk_query_and_roots_without_item_calls(self) -> None:
        class BulkHierarchyClient(QueryFakeClient):
            def get_tracker_children_page(self, tracker_id: int, *, page: int, page_size: int):
                self.__class__.calls.append(("roots", tracker_id, page, page_size))
                return {
                    "page": page,
                    "pageSize": page_size,
                    "total": 1,
                    "itemRefs": [{"id": 1, "name": "Root", "hasChildren": True}],
                }

            def search_items(self, *, query_string, baseline_id=None, page, page_size):
                del baseline_id
                self.__class__.calls.append(("search", query_string, page, page_size))
                return {
                    "page": page,
                    "pageSize": page_size,
                    "total": 2,
                    "items": [
                        {
                            "id": 1,
                            "name": "Root",
                            "tracker": {"id": 20},
                            "children": [{"id": 2, "name": "Child"}],
                        },
                        {
                            "id": 2,
                            "name": "Child",
                            "tracker": {"id": 20},
                            "parent": {"id": 1, "name": "Root"},
                            "children": [],
                        },
                    ],
                }

            def get_item(self, item_id: int):
                raise AssertionError(f"unexpected item call: {item_id}")

            def get_item_children_page(self, item_id: int, *, page: int, page_size: int):
                raise AssertionError(f"unexpected child call: {item_id}, {page}, {page_size}")

        BulkHierarchyClient.reset()
        service = TrackerQueryService(client_factory=BulkHierarchyClient)

        snapshot = service.load_tracker_hierarchy_export_snapshot(
            self.settings,
            20,
            tracker_name="Requirements",
        )

        self.assertEqual([node.item.item_id for node in snapshot.nodes], [1, 2])
        self.assertEqual([node.depth for node in snapshot.nodes], [0, 1])
        self.assertTrue(any(call[0] == "search" for call in BulkHierarchyClient.calls))
        self.assertTrue(any(call[0] == "roots" for call in BulkHierarchyClient.calls))

    def test_baseline_hierarchy_and_detail_keep_the_selected_baseline(self) -> None:
        class BaselineHierarchyClient(QueryFakeClient):
            def search_items(self, *, query_string, baseline_id=None, page, page_size):
                self.__class__.calls.append(
                    ("baseline_search", query_string, baseline_id, page, page_size)
                )
                return {
                    "page": page,
                    "pageSize": page_size,
                    "total": 3,
                    "items": [
                        {
                            "id": 1,
                            "name": "Baseline root",
                            "tracker": {"id": 20},
                            "ordinal": 1,
                            "children": [{"id": 2}, {"id": 3}],
                        },
                        {
                            "id": 2,
                            "name": "Second",
                            "tracker": {"id": 20},
                            "parent": {"id": 1},
                            "ordinal": 2,
                            "children": [],
                        },
                        {
                            "id": 3,
                            "name": "First",
                            "tracker": {"id": 20},
                            "parent": {"id": 1},
                            "ordinal": 1,
                            "children": [],
                        },
                    ],
                }

            def get_item(self, item_id: int, baseline_id=None):
                self.__class__.calls.append(("baseline_item", item_id, baseline_id))
                return {
                    "id": item_id,
                    "name": "Baseline detail",
                    "tracker": {"id": 20, "name": "Requirements"},
                    "children": [],
                    "customFields": [],
                }

            def get_tracker_children_page(self, tracker_id: int, *, page: int, page_size: int):
                raise AssertionError("current root API must not be used")

            def get_item_children_page(self, item_id: int, *, page: int, page_size: int):
                raise AssertionError("current child API must not be used")

        BaselineHierarchyClient.reset()
        service = TrackerQueryService(client_factory=BaselineHierarchyClient)

        snapshot = service.load_baseline_hierarchy_snapshot(
            self.settings,
            20,
            11,
        )
        detail = service.load_detail(self.settings, 2, baseline_id=11)

        self.assertEqual([node.item.item_id for node in snapshot.nodes], [1, 2, 3])
        search_call = next(
            call for call in BaselineHierarchyClient.calls if call[0] == "baseline_search"
        )
        self.assertEqual(search_call[2], 11)
        self.assertIn("tracker.id = 20", search_call[1])
        self.assertEqual(detail.summary.name, "Baseline detail")
        self.assertIn(("baseline_item", 2, 11), BaselineHierarchyClient.calls)

    def test_search_passes_only_scoped_cbql_and_preserves_it_as_metadata(self) -> None:
        result = self.service.search(
            self.settings,
            TrackerQuery(tracker_id=20, text="Steering", page=3, page_size=30),
        )

        search_call = next(call for call in QueryFakeClient.calls if call[0] == "search")
        self.assertIn("tracker.id = 20", search_call[1])
        self.assertIn("summary LIKE '%Steering%'", search_call[1])
        self.assertEqual(search_call[3:], (3, 30))
        self.assertEqual(result.items[0].tracker_id, 20)
        self.assertEqual(result.server_metadata["scopedCbql"], search_call[1])

    def test_detail_enriches_project_context_and_masks_raw_credentials(self) -> None:
        detail = self.service.load_detail(self.settings, 1001)

        self.assertEqual(detail.summary.project_id, 10)
        self.assertEqual(detail.summary.project_name, "Vehicle")
        self.assertEqual(detail.custom_fields[0].display_value, "High")
        self.assertEqual(detail.raw_payload["password"], "***")
        self.assertNotIn("must-not-leak", str(detail.raw_payload))

    def test_tracker_metadata_is_reused_for_multiple_item_details(self) -> None:
        self.service.load_detail(self.settings, 1001)
        self.service.load_detail(self.settings, 1002)

        tracker_calls = [call for call in QueryFakeClient.calls if call[0] == "tracker"]
        self.assertEqual(tracker_calls, [("tracker", 20)])

    def test_tracker_list_seeds_detail_metadata_cache(self) -> None:
        self.service.load_trackers(self.settings, 10, project_name="Vehicle")
        detail = self.service.load_detail(self.settings, 1001)

        self.assertEqual(detail.summary.project_name, "Vehicle")
        self.assertNotIn(("tracker", 20), QueryFakeClient.calls)

    def test_tracker_schema_is_cached_and_returned_as_an_isolated_copy(self) -> None:
        first = self.service.load_tracker_schema(self.settings, 20)
        first["fields"][0]["name"] = "Changed locally"
        second = self.service.load_tracker_schema(self.settings, 20)

        self.assertEqual(second["fields"][0]["name"], "Summary")
        self.assertEqual(
            [call for call in QueryFakeClient.calls if call[0] == "schema"],
            [("schema", 20)],
        )

        self.service.clear_cache()
        self.service.load_tracker_schema(self.settings, 20)
        self.assertEqual(
            [call for call in QueryFakeClient.calls if call[0] == "schema"],
            [("schema", 20), ("schema", 20)],
        )

    def test_direct_item_context_contains_target_project_and_tracker(self) -> None:
        context = self.service.resolve_item_context(self.settings, 1001)

        self.assertEqual(context.item.item_id, 1001)
        self.assertEqual(context.project_id, 10)
        self.assertEqual(context.tracker_id, 20)
        self.assertEqual(context.tracker_name, "Requirements")

    def test_detail_remains_available_when_project_metadata_lookup_fails(self) -> None:
        service = TrackerQueryService(client_factory=TrackerMetadataFailureFakeClient)

        detail = service.load_detail(self.settings, 1001)

        self.assertEqual(detail.item_id, 1001)
        self.assertIsNone(detail.summary.project_id)
        self.assertEqual(len(detail.warnings), 1)
        self.assertIn("아이템 상세만 표시", detail.warnings[0])

    def test_http_errors_are_classified_without_returning_server_message(self) -> None:
        service = TrackerQueryService(client_factory=ForbiddenFakeClient)

        with self.assertRaises(TrackerQueryServiceError) as raised:
            service.load_projects(self.settings)

        self.assertEqual(raised.exception.kind, TrackerQueryErrorKind.FORBIDDEN)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertNotIn("unsafe server detail", str(raised.exception))

    def test_expected_http_statuses_have_distinct_error_kinds(self) -> None:
        expected = {
            400: TrackerQueryErrorKind.INVALID_QUERY,
            401: TrackerQueryErrorKind.UNAUTHORIZED,
            403: TrackerQueryErrorKind.FORBIDDEN,
            404: TrackerQueryErrorKind.NOT_FOUND,
            429: TrackerQueryErrorKind.RATE_LIMITED,
            503: TrackerQueryErrorKind.SERVER,
        }

        for status_code, expected_kind in expected.items():
            with self.subTest(status_code=status_code):
                kind, actual_status = classify_tracker_query_error(_HttpError(status_code))
                self.assertEqual(kind, expected_kind)
                self.assertEqual(actual_status, status_code)

    def test_search_rejects_server_results_outside_selected_tracker(self) -> None:
        service = TrackerQueryService(client_factory=LeakingSearchFakeClient)

        with self.assertRaises(TrackerQueryServiceError) as raised:
            service.search(self.settings, TrackerQuery(tracker_id=20))

        self.assertEqual(raised.exception.kind, TrackerQueryErrorKind.SERVER)
        self.assertIn("현재 트래커 범위", str(raised.exception))

    def test_incomplete_condition_query_is_classified_before_server_call(self) -> None:
        query = TrackerQuery(
            tracker_id=20,
            mode=TrackerSearchMode.CONDITIONS,
            groups=(TrackerQueryGroup(),),
        )

        with self.assertRaises(TrackerQueryServiceError) as raised:
            self.service.search(self.settings, query)

        self.assertEqual(raised.exception.kind, TrackerQueryErrorKind.INVALID_QUERY)
        self.assertFalse(any(call[0] == "search" for call in QueryFakeClient.calls))


class OfflineTrackerQueryServiceIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = GuiSettings(
            offline_mode=True,
            offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
            offline_tracker_configuration_path=str(
                SAMPLE_DIR / "offline_tracker_configuration.json"
            ),
            offline_query_data_path=str(SAMPLE_DIR / "offline_tracker_items.json"),
        )
        self.service = TrackerQueryService()

    def test_fixture_exposes_two_trackers_and_lazy_hierarchy(self) -> None:
        projects = self.service.load_projects(self.settings)
        trackers = self.service.load_trackers(
            self.settings,
            projects[0].project_id,
            project_name=projects[0].name,
        )
        roots = self.service.load_top_level_items(
            self.settings,
            24680001,
            page_size=100,
        )
        children = self.service.load_child_items(
            self.settings,
            9001001,
            tracker_id=24680001,
        )
        nested = self.service.load_child_items(
            self.settings,
            9001003,
            tracker_id=24680001,
        )

        self.assertEqual([tracker.tracker_id for tracker in trackers], [24680001, 24680002])
        self.assertEqual([item.item_id for item in roots.items], [9001001, 9001010])
        self.assertEqual([item.item_id for item in children.items], [9001002, 9001003])
        self.assertEqual([item.item_id for item in nested.items], [9001004])

    def test_fixture_search_never_leaks_items_from_the_other_tracker(self) -> None:
        requirement_results = self.service.search(
            self.settings,
            TrackerQuery(tracker_id=24680001, text="Steering"),
        )
        test_results = self.service.search(
            self.settings,
            TrackerQuery(tracker_id=24680002, text="Steering"),
        )

        self.assertEqual(
            [item.item_id for item in requirement_results.items],
            [9001003, 9001004],
        )
        self.assertEqual(
            [item.item_id for item in test_results.items],
            [9101002],
        )
        self.assertTrue(
            all(item.tracker_id == 24680001 for item in requirement_results.items)
        )
        self.assertTrue(all(item.tracker_id == 24680002 for item in test_results.items))

    def test_fixture_evaluates_and_or_condition_groups_against_custom_fields(self) -> None:
        result = self.service.search(
            self.settings,
            TrackerQuery(
                tracker_id=24680001,
                mode=TrackerSearchMode.CONDITIONS,
                groups=(
                    TrackerQueryGroup(
                        (TrackerQueryCondition("status", "equals", "Approved"),)
                    ),
                    TrackerQueryGroup(
                        (TrackerQueryCondition("Risk Level", "equals", "High"),)
                    ),
                ),
            ),
        )

        self.assertEqual([item.item_id for item in result.items], [9001003, 9001004])

    def test_fixture_applies_multiple_server_sort_terms(self) -> None:
        result = self.service.search(
            self.settings,
            TrackerQuery(
                tracker_id=24680001,
                sort="status ASC, item.id DESC",
            ),
        )

        self.assertEqual(
            [item.item_id for item in result.items],
            [9001004, 9001003, 9001001, 9001010, 9001002],
        )

    def test_fixture_rejects_cbql_outside_supported_offline_subset(self) -> None:
        query = TrackerQuery(
            tracker_id=24680001,
            mode=TrackerSearchMode.CBQL,
            cbql="exists(tracker.id = 24680002)",
        )

        with self.assertRaises(TrackerQueryServiceError) as raised:
            self.service.search(self.settings, query)

        self.assertEqual(raised.exception.kind, TrackerQueryErrorKind.INVALID_QUERY)

    def test_fixture_pagination_and_detail_context_match_snapshot(self) -> None:
        first_page = self.service.load_top_level_items(
            self.settings,
            24680001,
            page=1,
            page_size=1,
        )
        second_page = self.service.load_top_level_items(
            self.settings,
            24680001,
            page=2,
            page_size=1,
        )
        context = self.service.resolve_item_context(self.settings, 9001003)
        ancestor_path = self.service.load_ancestor_path(self.settings, 9001004)

        self.assertEqual([item.item_id for item in first_page.items], [9001001])
        self.assertEqual([item.item_id for item in second_page.items], [9001010])
        self.assertEqual(first_page.total, 2)
        self.assertTrue(first_page.has_next)
        self.assertEqual(context.project_id, 246800)
        self.assertEqual(context.tracker_id, 24680001)
        self.assertEqual(context.item.custom_fields[0].display_value, "High")
        self.assertEqual(
            [item.item_id for item in ancestor_path],
            [9001001, 9001003, 9001004],
        )

    def test_offline_query_without_item_snapshot_is_reported_explicitly(self) -> None:
        settings = GuiSettings(
            offline_mode=True,
            offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
        )

        with self.assertRaises(TrackerQueryServiceError) as raised:
            self.service.load_top_level_items(settings, 24680001)

        self.assertEqual(
            raised.exception.kind,
            TrackerQueryErrorKind.OFFLINE_DATA_UNAVAILABLE,
        )

    def test_invalid_offline_query_snapshot_is_reported_without_raw_parser_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            invalid_path = Path(tmp_dir) / "invalid-query.json"
            invalid_path.write_text("[]", encoding="utf-8")
            settings = GuiSettings(
                offline_mode=True,
                offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
                offline_query_data_path=str(invalid_path),
            )

            with self.assertRaises(TrackerQueryServiceError) as raised:
                self.service.load_projects(settings)

        self.assertEqual(
            raised.exception.kind,
            TrackerQueryErrorKind.OFFLINE_DATA_UNAVAILABLE,
        )
        self.assertNotIn("JSON", str(raised.exception))

    def test_load_all_search_items_collects_every_server_page_without_cap(self) -> None:
        service = TrackerQueryService(client_factory=PaginatedSearchClient)
        settings = GuiSettings(
            base_url="https://example.test/cb",
            username="sample",
            password="placeholder",
        )

        items = service.load_all_search_items(
            settings,
            TrackerQuery(tracker_id=20, text="Item"),
        )

        self.assertEqual(len(items), 1201)
        self.assertEqual(items[0].item_id, 1)
        self.assertEqual(items[-1].item_id, 1201)

    def test_full_comparison_rejects_reference_only_query_response(self) -> None:
        class ReferenceOnlyClient(QueryFakeClient):
            def search_items(self, **kwargs):
                payload = super().search_items(**kwargs)
                payload["itemRefs"] = payload.pop("items")
                return payload

        service = TrackerQueryService(client_factory=ReferenceOnlyClient)
        settings = GuiSettings(
            base_url="https://example.test/cb",
            username="sample",
            password="placeholder",
        )

        with self.assertRaises(TrackerQueryServiceError) as raised:
            service.load_all_search_items(
                settings,
                TrackerQuery(tracker_id=20),
                require_full_items=True,
            )

        self.assertEqual(raised.exception.kind, TrackerQueryErrorKind.SERVER)
        self.assertIn("items", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
