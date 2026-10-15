"""작업 공간의 계층·검색·트래커 선택과 공통 동작 테스트."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.gui.settings_store import GuiSettings
from src.gui.tracker_hierarchy_export_dialog import TrackerHierarchyExportFieldDialog
from src.gui.tracker_query_models import TrackerItemSummary
from src.gui.tracker_workspace import CHILDREN_LOADED_ROLE
from src.gui.tracker_workspace import ITEM_SUMMARY_ROLE
from src.gui.tracker_workspace import TrackerWorkspacePage
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401
from tests.tracker_workspace_fixtures import CountingTrackerQueryService
from tests.tracker_workspace_fixtures import TrackerWorkspaceTestCase
from tests.tracker_workspace_fixtures import _detail


class TrackerWorkspacePageTest(TrackerWorkspaceTestCase):
    def test_selecting_a_tracker_shows_its_required_create_fields(self) -> None:
        """생성 대화상자를 열기 전에 무엇을 채워야 하는지 보여 준다."""
        self.page.activate()

        label = self.page.required_fields_label
        self.assertTrue(label.isVisible())
        self.assertIn("Summary", label.text())
        self.assertIn("필수 필드", label.text())

    def test_required_fields_are_cleared_when_no_tracker_is_selected(self) -> None:
        self.page.activate()
        self.page._clear_required_fields()

        self.assertFalse(self.page.required_fields_label.isVisible())
        self.assertEqual(self.page.required_fields_label.text(), "")

    def test_activation_loads_project_tracker_and_top_level_items(self) -> None:
        self.page.activate()

        self.assertEqual(self.page.project_combo.count(), 1)
        self.assertEqual(self.page.project_combo.currentData(), 246800)
        # 연 트래커는 최근 항목으로 맨 위에 오고, 구분선 아래에 나머지가 온다.
        self.assertEqual(
            [
                self.page.tracker_combo.itemData(index)
                for index in range(self.page.tracker_combo.count())
            ],
            [24680001, None, 24680002],
        )
        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 2)
        self.assertEqual(self.page.hierarchy_panel.item_tree.columnCount(), 2)
        self.assertEqual(self.page.hierarchy_panel.item_tree.headerItem().text(0), "요약")
        self.assertEqual(self.page.hierarchy_panel.item_tree.headerItem().text(1), "ID")
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItem(0).text(1), "9001001")
        self.assertIn("전체 표시", self.page.hierarchy_panel.tree_status_label.text())
        self.assertIn("Offline Requirements", self.page.search_panel.search_scope_label.text())
        self.assertTrue(self.page.search_panel.search_button.isEnabled())
        self.assertFalse(self.page.create_item_button.isEnabled())

    def test_hierarchy_export_selects_fields_and_uses_bulk_snapshot_service(self) -> None:
        self.page.activate()
        snapshot = object()
        summary = SimpleNamespace(
            item_count=5,
            selected_field_count=2,
            data_row_count=7,
            long_value_count=0,
            long_value_part_count=0,
        )

        accepting_dialog = self._accepting_export_dialog(TrackerHierarchyExportFieldDialog, ("status", "custom:101"))
        with (
            patch(
                "src.gui.tracker_hierarchy_panel.TrackerHierarchyExportFieldDialog",
                accepting_dialog,
            ),
            patch(
                "src.gui.tracker_hierarchy_panel.QFileDialog.getSaveFileName",
                return_value=("hierarchy.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch.object(
                self.service,
                "load_tracker_hierarchy_export_snapshot",
                return_value=snapshot,
            ) as snapshot_mock,
            patch(
                "src.gui.tracker_hierarchy_panel.export_tracker_hierarchy_xlsx",
                return_value=summary,
            ) as export_mock,
        ):

            self.page.hierarchy_panel.hierarchy_export_button.click()

        snapshot_mock.assert_called_once()
        export_mock.assert_called_once_with(
            snapshot,
            "hierarchy.xlsx",
            tracker_name="Offline Requirements (ID 24680001)",
            project_name="Offline Vehicle Project",
            selected_field_keys=("status", "custom:101"),
            baseline_id=None,
            baseline_name="",
        )
        self.assertFalse(self.page.hierarchy_panel._hierarchy_export_in_progress)
        self.assertTrue(self.page.hierarchy_panel.hierarchy_export_button.isEnabled())
        self.assertIn("아이템 5개", self.page.hierarchy_panel.tree_status_label.text())

    def test_unknown_child_metadata_keeps_tree_item_expandable(self) -> None:
        unknown = TrackerItemSummary.from_raw({"id": 1, "name": "Unknown"})
        known_empty = TrackerItemSummary.from_raw(
            {"id": 2, "name": "Empty", "hasChildren": False}
        )

        unknown_item = self.page.hierarchy_panel.tree_item(unknown)
        empty_item = self.page.hierarchy_panel.tree_item(known_empty)

        self.assertFalse(bool(unknown_item.data(0, CHILDREN_LOADED_ROLE)))
        self.assertEqual(unknown_item.childCount(), 1)
        self.assertTrue(bool(empty_item.data(0, CHILDREN_LOADED_ROLE)))
        self.assertEqual(empty_item.childCount(), 0)

    def test_expanding_node_loads_direct_children_once_and_reuses_cache(self) -> None:
        self.page.activate()
        root = self.page.hierarchy_panel.item_tree.topLevelItem(0)

        self.page.hierarchy_panel.load_children(root)

        self.assertEqual(self.service.child_load_count, 1)
        self.assertEqual(root.childCount(), 2)
        self.assertEqual(root.child(0).text(1), "9001002")
        self.assertEqual(root.child(1).text(1), "9001003")

        self.page.hierarchy_panel.load_children(root)

        self.assertEqual(self.service.child_load_count, 1)
        steering = root.child(1)
        self.page.hierarchy_panel.load_children(steering)
        self.assertEqual(self.service.child_load_count, 2)
        self.assertEqual(steering.child(0).text(1), "9001004")

    def test_test_mode_editor_loads_schema_but_disables_write_actions(self) -> None:
        self.page.activate()
        self.page.hierarchy_panel.item_tree.setCurrentItem(self.page.hierarchy_panel.item_tree.topLevelItem(0))
        self.page.detail_panel.detail_tabs.setCurrentIndex(self.page.detail_panel.editor_tab_index)
        self._app.processEvents()

        self.assertGreater(self.page.detail_panel.editor_panel.field_table.rowCount(), 0)
        self.assertFalse(self.page.detail_panel.editor_panel.save_button.isEnabled())
        self.assertFalse(self.page.detail_panel.editor_panel.transition_button.isEnabled())
        self.assertFalse(self.page.detail_panel.editor_panel.delete_button.isEnabled())
        self.assertIn("테스트 모드", self.page.detail_panel.editor_panel.editor_status.text())

    def test_tracker_search_is_scoped_to_selected_tracker(self) -> None:
        self.page.activate()
        self.page.browser_tabs.setCurrentIndex(1)
        self.page.search_panel.search_text_input.setText("Steering")

        self.page.search_panel._run_search()

        requirement_ids = {
            int(self.page.search_panel.search_table.item(row, 1).text())
            for row in range(self.page.search_panel.search_table.rowCount())
        }
        self.assertEqual(requirement_ids, {9001003, 9001004})

        self.page._on_tracker_activated(self.page.tracker_combo.findData(24680002))
        self.page.search_panel.search_text_input.setText("Steering")
        self.page.search_panel._run_search()

        test_case_ids = {
            int(self.page.search_panel.search_table.item(row, 1).text())
            for row in range(self.page.search_panel.search_table.rowCount())
        }
        self.assertEqual(test_case_ids, {9101002})
        self.assertNotIn(9001003, test_case_ids)
        self.assertIn("Offline Test Cases", self.page.search_panel.search_scope_label.text())

    def test_search_result_selection_supports_page_and_all_query_modes(self) -> None:
        from PySide6.QtCore import Qt

        self.page.activate()
        self.page.search_panel.search_text_input.setText("Steering")
        self.page.search_panel._run_search()

        self.page.search_panel._select_current_search_page()
        self.assertEqual(self.page.search_panel._selected_search_ids, {9001003, 9001004})
        self.assertEqual(self.page.search_panel.selected_count(), 2)

        self.page.search_panel._select_all_search_results()
        self.assertTrue(self.page.search_panel._all_search_selected)
        self.assertEqual(self.page.search_panel.selected_count(), 2)
        first_checkbox = self.page.search_panel.search_table.item(0, 0)
        first_checkbox.setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(self.page.search_panel.selected_count(), 1)
        self.assertEqual(len(self.page.search_panel._excluded_search_ids), 1)

    def test_search_without_server_total_shows_count_as_lower_bound_and_allows_next_page(self) -> None:
        """total이 없는 응답에서 받은 개수를 전체처럼 보이면 다음 페이지로 갈 수 없다."""
        from src.gui.tracker_query_models import PageResult

        panel = self.page.search_panel
        self.page.activate()
        summaries = [
            TrackerItemSummary.from_raw({"id": 9001003 + index, "name": f"Item {index}"}, tracker_id=24680001)
            for index in range(2)
        ]

        panel._render_search_results(
            PageResult.create(summaries, raw_page={"page": 1, "pageSize": 2}, requested_page=1, requested_page_size=2)
        )

        self.assertIn("2개 이상", panel.search_scope_label.text())
        self.assertTrue(panel.search_next_button.isEnabled())

    def test_direct_open_to_other_tracker_clears_search_results_and_selection(self) -> None:
        """다른 트래커로 옮기면 이전 트래커의 검색 선택으로 일괄 수정하지 않게 비운다."""
        self.page.activate()
        panel = self._select_steering_results()
        self.page.direct_id_input.setText("9101002")

        self.page._open_direct_item()

        self.assertEqual(self.page.tracker_combo.currentData(), 24680002)
        self.assertEqual(panel.search_table.rowCount(), 0)
        self.assertEqual(panel.selected_count(), 0)
        self.assertFalse(panel.bulk_update_button.isEnabled())

    def test_opening_tracker_by_id_clears_search_results_and_selection(self) -> None:
        """트래커 ID나 즐겨찾기로 프로젝트를 옮겨 열 때도 검색 결과를 비운다."""
        self.page.activate()
        panel = self._select_steering_results()

        self.page._open_tracker_by_id(24680002)

        self.assertEqual(self.page.tracker_combo.currentData(), 24680002)
        self.assertEqual(panel.search_table.rowCount(), 0)
        self.assertEqual(panel.selected_count(), 0)

    def test_bulk_update_refuses_selection_from_another_tracker(self) -> None:
        """검색 결과를 비우지 못한 경로가 생겨도 다른 트래커 아이템을 일괄 수정하지 않는다."""
        self.page.activate()
        panel = self._select_steering_results()
        self.page._current_tracker = next(
            tracker for tracker in self.page._trackers if tracker.tracker_id == 24680002
        )

        panel._start_bulk_update()

        self.assertIn("다른 트래커", self.page.workspace_status_label.text())
        self.assertEqual(self.page.workspace_status_label.property("tone"), "warning")
        self.assertEqual(panel.selected_count(), 0)
        self.assertEqual(panel.search_table.rowCount(), 0)

    def test_search_rows_follow_saved_and_deleted_items(self) -> None:
        self.page.activate()
        self._select_steering_results()
        self.assertEqual({row[0] for row in self._search_row_texts()}, {"9001003", "9001004"})

        self.page._refresh_visible_item(_detail(9001003, "Renamed steering"))
        self.page._remove_visible_item(9001004)

        rows = self._search_row_texts()
        self.assertEqual([row[:2] for row in rows], [("9001003", "Renamed steering")])

    def test_refresh_reloads_hierarchy_instead_of_cached_children(self) -> None:
        """새로고침은 서버에서 다시 받는다. 펼쳐 둔 하위 목록 캐시를 그대로 쓰지 않는다."""
        self.page.activate()
        self.page.hierarchy_panel.item_tree.topLevelItem(0).setExpanded(True)
        self._app.processEvents()
        loads = self.service.child_load_count

        self.page.refresh_context_button.click()
        self._app.processEvents()
        self.page.hierarchy_panel.item_tree.topLevelItem(0).setExpanded(True)
        self._app.processEvents()

        self.assertEqual(self.service.child_load_count, loads + 1)

    def test_direct_open_to_other_tracker_refreshes_required_fields(self) -> None:
        self.page.activate()
        self.page.required_fields_label.setText("이전 트래커 필드")
        self.page.direct_id_input.setText("9101002")

        self.page._open_direct_item()

        self.assertEqual(self.page.tracker_combo.currentData(), 24680002)
        self.assertNotEqual(self.page.required_fields_label.text(), "이전 트래커 필드")

    def test_condition_search_mode_loads_schema_and_builds_condition_query(self) -> None:
        self.page.activate()
        self.page.browser_tabs.setCurrentIndex(1)
        mode_index = self.page.search_panel.search_mode_combo.findData("conditions")
        self.page.search_panel.search_mode_combo.setCurrentIndex(mode_index)
        self.assertTrue(self.page.search_panel.condition_search_host.isVisible())
        self.assertFalse(self.page.search_panel.condition_dialog.isVisible())
        self.assertEqual(self.page.search_panel.search_button.text(), "상세 조건으로 검색")
        self.assertIn("조건 묶음 1개", self.page.search_panel.condition_summary_label.text())

        self.page.search_panel.condition_open_button.click()
        self._app.processEvents()
        self.assertTrue(self.page.search_panel.condition_dialog.isVisible())
        self.assertGreaterEqual(self.page.search_panel.condition_dialog.width(), 860)
        self.assertGreaterEqual(self.page.search_panel.condition_dialog.height(), 600)

        group = self.page.search_panel.condition_builder.groups[0]
        row = group.rows[0]
        summary_index = row.field_combo.findText("Summary")
        row.field_combo.setCurrentIndex(summary_index)
        contains_index = row.operator_combo.findData("contains")
        row.operator_combo.setCurrentIndex(contains_index)
        row.value_input.setText("Steering")
        self.page.search_panel.condition_dialog.close_button.click()
        self._app.processEvents()
        self.assertFalse(self.page.search_panel.condition_dialog.isVisible())
        self.assertEqual(
            self.page.search_panel.condition_builder.groups[0].rows[0].value_input.text(),
            "Steering",
        )

        self.page.search_panel._run_search()

        self.assertIsNotNone(self.page.search_panel._last_search_query)
        self.assertEqual(self.page.search_panel._last_search_query.mode.value, "conditions")
        self.assertEqual(self.page.search_panel.search_table.rowCount(), 2)

        self.page.search_panel.search_mode_combo.setCurrentIndex(0)
        self._app.processEvents()
        self.assertFalse(self.page.search_panel.condition_dialog.isVisible())
        self.assertEqual(self.page.search_panel.search_button.text(), "현재 트래커 검색")

    def test_direct_id_open_resolves_other_tracker_and_builds_ancestor_path(self) -> None:
        self.page.activate()
        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)
        self.page.direct_id_input.setText("9101002")

        self.page._open_direct_item()

        self.assertEqual(self.page.tracker_combo.currentData(), 24680002)
        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#9101002")
        self.assertEqual(self.page.detail_panel.detail_title.text(), "Steering response test")
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 1)
        root = self.page.hierarchy_panel.item_tree.topLevelItem(0)
        self.assertEqual(root.text(1), "9101001")
        self.assertEqual(root.childCount(), 1)
        self.assertEqual(root.child(0).text(1), "9101002")
        self.assertIn("ID 직접 접근 경로", self.page.hierarchy_panel.tree_status_label.text())

    def test_search_requires_filter_instead_of_loading_entire_tracker(self) -> None:
        self.page.activate()

        self.page.search_panel._run_search()

        self.assertEqual(self.page.search_panel.search_table.rowCount(), 0)
        self.assertIn("하나 이상", self.page.workspace_status_label.text())
        self.assertEqual(self.page.workspace_status_label.property("tone"), "warning")

    def test_unconfigured_workspace_guides_user_to_settings(self) -> None:
        page = TrackerWorkspacePage(
            settings_provider=GuiSettings,
            service=self.service,
            synchronous=True,
        )
        try:
            page.activate()

            self.assertFalse(page.direct_open_button.isEnabled())
            self.assertFalse(page.refresh_context_button.isEnabled())
            self.assertIn("활성 연결", page.workspace_status_label.text())
            self.assertEqual(page.workspace_status_label.property("tone"), "warning")
        finally:
            page.close()

    def test_workspace_error_updates_status_and_calls_user_notifier(self) -> None:
        alerts = []
        self.page.error_notifier = lambda title, message: alerts.append((title, message))

        self.page._show_error(ValueError("잘못된 조건"), prefix="검색 실패")

        self.assertEqual(
            alerts,
            [("검색 실패", "검색 실패: 잘못된 조건")],
        )
        self.assertEqual(self.page.workspace_status_label.property("tone"), "error")
        self.assertIn("잘못된 조건", self.page.workspace_status_label.text())

    def test_background_task_start_failure_uses_failure_callback(self) -> None:
        class SignalStub:
            def connect(self, callback) -> None:
                self.callback = callback

        class FailingTask:
            def __init__(self) -> None:
                self.completed = SignalStub()
                self.failed = SignalStub()
                self.finished = SignalStub()
                self.deleted = False

            def start(self) -> None:
                raise RuntimeError("thread start failed")

            def deleteLater(self) -> None:
                self.deleted = True

        task = FailingTask()
        failures = []
        self.page.synchronous = False
        self.page.task_factory = lambda *_args, **_kwargs: task

        self.page._submit("direct", lambda: None, lambda _result: None, failures.append)

        self.assertEqual(str(failures[0]), "thread start failed")
        self.assertTrue(task.deleted)
        self.assertFalse(self.page._tasks)

    def test_request_tokens_reject_stale_results(self) -> None:
        first = self.page._next_token("detail")
        second = self.page._next_token("detail")

        self.assertFalse(self.page._is_current_token("detail", first))
        self.assertTrue(self.page._is_current_token("detail", second))

    def test_api_requests_report_balanced_global_busy_tokens(self) -> None:
        events: list[tuple[str, object]] = []

        def started(message: str) -> int:
            token = len([event for event in events if event[0] == "start"]) + 1
            events.append(("start", message))
            return token

        page = TrackerWorkspacePage(
            settings_provider=lambda: self.settings,
            service=CountingTrackerQueryService(),
            busy_started=started,
            busy_finished=lambda token: events.append(("finish", token)),
            synchronous=True,
        )
        try:
            page.activate()

            starts = [value for kind, value in events if kind == "start"]
            finishes = [value for kind, value in events if kind == "finish"]
            self.assertEqual(len(starts), 5)
            self.assertEqual(finishes, [3, 4, 5, 2, 1])
            self.assertIn("프로젝트", starts[0])
            self.assertIn("트래커", starts[1])
            self.assertIn("필수 필드", starts[2])
            self.assertIn("최상위 아이템", starts[3])
            self.assertIn("baseline 목록", starts[4])
        finally:
            page.close()

    def test_tree_items_store_normalized_models_not_server_dicts(self) -> None:
        self.page.activate()
        value = self.page.hierarchy_panel.item_tree.topLevelItem(0).data(0, ITEM_SUMMARY_ROLE)

        self.assertEqual(value.item_id, 9001001)
        self.assertEqual(value.tracker_id, 24680001)
        self.assertFalse(isinstance(value, dict))


if __name__ == "__main__":
    unittest.main()
