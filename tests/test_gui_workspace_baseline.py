"""작업 공간의 Baseline 계층·비교·내보내기 테스트."""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity_export import ItemActivityExportSummary
from src.gui.tracker_baseline_compare import BaselineComparisonKind
from src.gui.tracker_baseline_compare import BaselineComparisonSource
from src.gui.tracker_baseline_compare import compare_tracker_items
from src.gui.tracker_baseline_export_dialog import BaselineExportFieldDialog
from src.gui.tracker_hierarchy_export_dialog import TrackerHierarchyExportFieldDialog
from src.gui.tracker_query_models import TrackerItemSummary
from src.gui.tracker_workspace import CHILDREN_LOADED_ROLE
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401
from tests.tracker_workspace_fixtures import TrackerWorkspaceTestCase
from tests.tracker_workspace_fixtures import _DeferredTask


class TrackerWorkspaceBaselineTest(TrackerWorkspaceTestCase):
    def test_long_baseline_names_do_not_widen_the_workspace(self) -> None:
        """Baseline 이름이 길어도 창을 줄일 수 있다. 콤보는 남는 폭만 채운다."""
        short_widths = self._minimum_widths_with_baseline_names(1)

        self.assertEqual(self._minimum_widths_with_baseline_names(8), short_widths)

    def test_saved_baseline_hierarchy_opens_at_once_and_reload_fetches_again(self) -> None:
        """저장본이 있는 Baseline은 고르기만 해도 열리고, 다시 불러오기만 저장본을 무시한다."""
        load_snapshot = self.service.load_baseline_hierarchy_snapshot
        refresh_flags: list[object] = []

        def recording_load(settings, tracker_id, baseline_id, **kwargs):
            refresh_flags.append(kwargs.get("refresh"))
            return load_snapshot(settings, tracker_id, baseline_id, **kwargs)

        self.service.load_baseline_hierarchy_snapshot = recording_load
        self.service.load_saved_baseline_hierarchy = lambda settings, tracker_id, baseline_id: replace(
            load_snapshot(settings, tracker_id, baseline_id),
            saved_at="2026-09-30T05:00:00+00:00",
        )
        self.page.activate()
        panel = self.page.hierarchy_panel

        panel.hierarchy_source_combo.setCurrentIndex(panel.hierarchy_source_combo.findData(24681001))
        self._app.processEvents()

        self.assertEqual(panel.item_tree.topLevelItemCount(), 1)
        self.assertIn("저장본 2026-09-30", panel.tree_status_label.text())
        self.assertIn("저장본", self.page.workspace_status_label.text())
        self.assertEqual(panel.reload_roots_button.text(), "Baseline 계층 다시 불러오기")
        self.assertEqual(refresh_flags, [])

        panel.reload_roots_button.click()
        self._app.processEvents()

        self.assertEqual(refresh_flags, [True])
        self.assertNotIn("저장본", panel.tree_status_label.text())

    def test_baseline_source_loads_full_read_only_hierarchy_and_detail(self) -> None:
        self.page.activate()

        self.assertEqual(self.page.hierarchy_panel.hierarchy_source_combo.count(), 2)
        baseline_id = 24681001
        self.page.hierarchy_panel.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_panel.hierarchy_source_combo.findData(baseline_id)
        )
        self._app.processEvents()

        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 0)
        self.assertIn("Baseline 계층 조회", self.page.hierarchy_panel.reload_roots_button.text())
        self.assertFalse(self.page.hierarchy_panel.hierarchy_export_button.isEnabled())
        self.assertFalse(self.page.detail_panel.detail_tabs.isTabEnabled(self.page.detail_panel.editor_tab_index))
        self.page._create_item()
        self.assertIn("Baseline 조회 중", self.page.workspace_status_label.text())

        child_loads_before = self.service.child_load_count
        self.page.hierarchy_panel.reload_roots_button.click()
        self._app.processEvents()

        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 1)
        self.assertTrue(self.page.hierarchy_panel.hierarchy_export_button.isEnabled())
        root = self.page.hierarchy_panel.item_tree.topLevelItem(0)
        self.assertEqual(root.text(0), "Vehicle requirements baseline")
        self.assertEqual(root.toolTip(0), "Vehicle requirements baseline")
        self.assertEqual(root.text(1), "9001001")
        self.assertEqual(root.childCount(), 2)
        self.assertTrue(root.data(0, CHILDREN_LOADED_ROLE))
        self.page.hierarchy_panel.load_children(root)
        self.assertEqual(self.service.child_load_count, child_loads_before)

        child = root.child(0)
        self.page.hierarchy_panel.item_tree.setCurrentItem(child)
        self._app.processEvents()

        self.assertEqual(self.page.detail_panel._detail_baseline_id, baseline_id)
        self.assertEqual(self.page.detail_panel.detail_title.text(), "Brake system baseline · Baseline")
        self.assertIn("읽기 전용", self.page.detail_panel.detail_warning.text())
        self.assertFalse(self.page.detail_panel.detail_tabs.isTabEnabled(self.page.detail_panel.editor_tab_index))

        self.page.hierarchy_panel.hierarchy_source_combo.setCurrentIndex(0)
        self._app.processEvents()

        self.assertIsNone(self.page.detail_panel._detail_baseline_id)
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 2)
        self.assertTrue(self.page.hierarchy_panel.hierarchy_export_button.isEnabled())

        self.page.hierarchy_panel.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_panel.hierarchy_source_combo.findData(baseline_id)
        )
        self._app.processEvents()
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 1)
        self.assertEqual(self.service.baseline_hierarchy_count, 1)

    def test_stale_baseline_hierarchy_does_not_replace_current_tree(self) -> None:
        self.page.activate()
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]

        baseline_id = 24681001
        self.page.hierarchy_panel.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_panel.hierarchy_source_combo.findData(baseline_id)
        )
        self.page.hierarchy_panel.reload_roots_button.click()
        # 출처를 고를 때 저장본을 먼저 찾고, 조회 버튼으로 전체를 받는다.
        self.assertEqual(len(tasks), 2)

        self.page.hierarchy_panel.hierarchy_source_combo.setCurrentIndex(0)
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 2)

        for task in tasks:
            task.finish()
        self._app.processEvents()

        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 2)
        self.assertNotIn(
            (24680001, baseline_id),
            self.page.hierarchy_panel._baseline_hierarchy_cache,
        )

    def test_baseline_hierarchy_export_reuses_loaded_snapshot(self) -> None:
        self.page.activate()
        baseline_id = 24681001
        self.page.hierarchy_panel.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_panel.hierarchy_source_combo.findData(baseline_id)
        )
        self.page.hierarchy_panel.reload_roots_button.click()
        self._app.processEvents()
        loaded_snapshot = self.page.hierarchy_panel._baseline_hierarchy_cache[
            (24680001, baseline_id)
        ]
        export_snapshot = object()
        summary = SimpleNamespace(
            item_count=3,
            selected_field_count=1,
            data_row_count=3,
            long_value_count=0,
            long_value_part_count=0,
        )

        accepting_dialog = self._accepting_export_dialog(TrackerHierarchyExportFieldDialog, ("status",))
        with (
            patch(
                "src.gui.tracker_hierarchy_panel.TrackerHierarchyExportFieldDialog",
                accepting_dialog,
            ),
            patch(
                "src.gui.tracker_hierarchy_panel.QFileDialog.getSaveFileName",
                return_value=("baseline-hierarchy.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ) as file_dialog,
            patch(
                "src.gui.tracker_hierarchy_panel.build_tracker_hierarchy_export_snapshot",
                return_value=export_snapshot,
            ) as build_mock,
            patch.object(
                self.service,
                "load_tracker_hierarchy_export_snapshot",
            ) as current_snapshot_mock,
            patch(
                "src.gui.tracker_hierarchy_panel.export_tracker_hierarchy_xlsx",
                return_value=summary,
            ) as export_mock,
        ):

            self.page.hierarchy_panel.hierarchy_export_button.click()

        current_snapshot_mock.assert_not_called()
        self.assertEqual(self.service.baseline_hierarchy_count, 1)
        build_mock.assert_called_once()
        self.assertIs(build_mock.call_args.args[0], loaded_snapshot)
        file_dialog.assert_called_once()
        self.assertEqual(
            file_dialog.call_args.args[2],
            "tracker_hierarchy_24680001_baseline_24681001.xlsx",
        )
        export_mock.assert_called_once_with(
            export_snapshot,
            "baseline-hierarchy.xlsx",
            tracker_name="Offline Requirements (ID 24680001)",
            project_name="Offline Vehicle Project",
            selected_field_keys=("status",),
            baseline_id=baseline_id,
            baseline_name=self.page.hierarchy_panel.hierarchy_source_combo.currentText(),
        )
        self.assertIn("아이템 3개", self.page.hierarchy_panel.tree_status_label.text())

    def test_baseline_compare_uses_separate_workspace_and_does_not_eagerly_fetch_details(self) -> None:
        self.page.activate()

        self.assertEqual(self.page.workspace_mode_tabs.count(), 2)
        self.assertEqual(self.page.workspace_mode_tabs.tabText(1), "Baseline 비교")
        self.page.workspace_mode_tabs.setCurrentIndex(self.page.baseline_mode_index)
        self._app.processEvents()

        self.assertEqual(self.page.baseline_workspace.baseline_item_tree.topLevelItemCount(), 2)
        self.assertEqual(self.service.baseline_compare_count, 0)
        self.assertEqual(self.service.baseline_load_count, 1)

    def test_baseline_comparison_directly_shows_all_fields_without_result_filter(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        comparison = TrackerItemSummary.from_raw(
            {
                "id": 9001001,
                "name": "Earlier summary",
                "version": 1,
                "unknownMetadata": {"flag": True},
                "customFields": [],
            }
        )
        reference = TrackerItemSummary.from_raw(
            {
                "id": 9001001,
                "name": "Current summary",
                "version": 2,
                "unknownMetadata": {"flag": True},
                "customFields": [],
            }
        )
        result = compare_tracker_items(
            (comparison,),
            (reference,),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )

        panel.set_result(result)

        self.assertFalse(hasattr(panel, "kind_filter"))
        self.assertFalse(hasattr(panel, "table"))
        self.assertEqual(panel.detail.columnCount(), 4)
        labels = {
            panel.detail.item(row, 0).text()
            for row in range(panel.detail.rowCount())
        }
        self.assertIn("ID", labels)
        self.assertIn("요약", labels)
        self.assertIn("버전", labels)
        self.assertIn("unknownMetadata", labels)
        self.assertIn("전체 필드 4개", panel.status_label.text())
        self.assertTrue(panel.detail.isSortingEnabled())
        self.assertEqual(panel.detail.horizontalHeader().sortIndicatorSection(), 3)
        self.assertEqual(panel.detail.item(0, 3).text(), "● 변경")

        changed_row = next(
            row
            for row in range(panel.detail.rowCount())
            if panel.detail.item(row, 0).text() == "요약"
        )
        same_row = next(
            row
            for row in range(panel.detail.rowCount())
            if panel.detail.item(row, 0).text() == "ID"
        )
        self.assertNotEqual(
            panel.detail.item(changed_row, 0).background().style(),
            Qt.BrushStyle.NoBrush,
        )
        self.assertEqual(
            panel.detail.item(same_row, 0).background().style(),
            Qt.BrushStyle.NoBrush,
        )
        self.assertEqual(panel.detail.item(same_row, 3).text(), "✓ 동일")
        self.assertTrue(panel.detail.item(changed_row, 3).font().bold())

        panel.detail.sortItems(0, Qt.SortOrder.DescendingOrder)
        sorted_labels = [
            panel.detail.item(row, 0).text()
            for row in range(panel.detail.rowCount())
        ]
        self.assertEqual(
            sorted_labels,
            sorted(sorted_labels, key=str.casefold, reverse=True),
        )

    def test_baseline_sources_require_explicit_confirmation_and_selection_reuses_cache(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        comparison = TrackerItemSummary.from_raw(
            {"id": 9001001, "name": "Earlier", "status": {"id": 1, "name": "Draft"}}
        )
        reference = TrackerItemSummary.from_raw(
            {"id": 9001001, "name": "Current", "status": {"id": 2, "name": "Open"}}
        )
        result = compare_tracker_items(
            (comparison,),
            (reference,),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        calls = []

        def compare_all(*args, **kwargs):
            calls.append((args, kwargs))
            return result

        self.service.compare_tracker_at_sources = compare_all
        panel.after_combo.addItem("R1", 11)
        panel.after_combo.setCurrentIndex(panel.after_combo.count() - 1)
        self._app.processEvents()

        self.assertEqual(len(calls), 0)
        self.assertEqual(len(self.baseline_compare_confirmations), 0)
        self.assertIsNone(self.page.baseline_workspace._baseline_comparison_result)
        self.assertIn("전체 비교 실행", panel.status_label.text())

        panel.run_button.click()
        self._app.processEvents()

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.baseline_compare_confirmations), 1)
        self.assertIs(self.page.baseline_workspace._baseline_comparison_result, result)
        self.assertEqual(self.page.baseline_workspace.baseline_result_table.rowCount(), 1)
        self.assertTrue(panel.export_button.isEnabled())
        self.assertEqual(panel.run_button.text(), "전체 비교 다시 불러오기")

        self.page.baseline_workspace.baseline_result_table.selectRow(0)
        self._app.processEvents()

        self.assertEqual(self.page.baseline_workspace._baseline_selected_item_id, 9001001)
        self.assertGreater(panel.detail.rowCount(), 0)
        self.assertEqual(len(calls), 1)

    def _open_comparison_history(self, item_id: int = 9001001):
        """현재 상태와 샘플 Baseline을 전체 비교하고 아이템을 골라 변경 이력 탭을 연다."""
        self.page.activate()
        self.page.workspace_mode_tabs.setCurrentIndex(self.page.baseline_mode_index)
        self._app.processEvents()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        panel.after_combo.setCurrentIndex(panel.after_combo.findData(24681001))
        panel.run_button.click()
        self._app.processEvents()
        self._select_comparison_row(item_id)
        return panel

    def test_comparison_history_lists_changes_comments_and_attachments_between_the_two_points(self) -> None:
        """비교 결과에서 고른 아이템의 두 시점 사이 이력을 탭을 열 때만 유형별로 조회해 시간순으로 보인다."""
        requested: list[tuple[str, int, int | None]] = []
        load_history = self.page.context_service.load_history
        load_comments = self.page.comment_service.load_comments
        load_attachments = self.page.content_service.load_attachments

        def recording_history(settings, item_id, item_version, **kwargs):
            requested.append(("history", item_id, item_version))
            return load_history(settings, item_id, item_version, **kwargs)

        def recording_comments(settings, item_id, item_version, **kwargs):
            requested.append(("comments", item_id, item_version))
            return load_comments(settings, item_id, item_version, **kwargs)

        def recording_attachments(settings, item_id, **kwargs):
            requested.append(("attachments", item_id, None))
            return load_attachments(settings, item_id, **kwargs)

        self.page.context_service.load_history = recording_history  # type: ignore[method-assign]
        self.page.comment_service.load_comments = recording_comments  # type: ignore[method-assign]
        self.page.content_service.load_attachments = recording_attachments  # type: ignore[method-assign]
        panel = self._open_comparison_history()
        activity = panel.activity_panel

        # 필드 비교만 볼 때는 이력을 묻지 않는다.
        self.assertEqual(requested, [])
        self.assertEqual(activity.status_label.text(), "#9001001 · 탭을 열면 변경 이력을 조회합니다.")
        self.assertEqual(activity.baseline_combo.currentText(), "비교 시점 사이")

        panel.detail_tabs.setCurrentWidget(panel.history_tab)
        self._app.processEvents()

        self.assertEqual(
            requested,
            [("history", 9001001, 3), ("comments", 9001001, 3), ("attachments", 9001001, None)],
        )
        # 필드 변경은 버전 1 → 3 사이, 댓글·첨부는 Baseline 생성 시각(07-15) 뒤만 남는다.
        self.assertEqual(
            activity.status_label.text(),
            "#9001001 · 비교 시점 사이 · 버전 2건 · 필드 변경 3건 · 바뀐 필드 3개 · 댓글 2건 · 첨부 1건",
        )
        view = activity.history_view
        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            [
                "댓글 · 2026-07-20 10:00 · Sample User B",
                "댓글 · 2026-07-20 09:10 · Sample User A",
                "버전 3 · 2026-07-20 09:00 · Sample User A · 필드 1개",
                "버전 2 · 2026-07-19 08:00 · Sample User B · 필드 2개",
                "첨부 · 2026-07-18 11:00 · anonymous-spec.txt · 2,048 bytes · text/plain",
            ],
        )
        risk = view.topLevelItem(2).child(0)
        self.assertEqual([risk.text(column) for column in range(3)], ["Risk Level", "-", "Medium"])
        table = activity.summary_table
        self.assertEqual(
            {table.item(row, 0).text() for row in range(table.rowCount())},
            {"Risk Level", "Summary", "Description"},
        )

        # 탭을 연 채 다른 아이템을 고르면 그 아이템을 묻는다.
        self._select_comparison_row(9001003)

        self.assertEqual(
            requested[-3:],
            [("history", 9001003, 4), ("comments", 9001003, 4), ("attachments", 9001003, None)],
        )
        self.assertTrue(activity.status_label.text().startswith("#9001003 · 비교 시점 사이 · 버전 3건"))
        self.assertTrue(activity.status_label.text().endswith("댓글 0건 · 첨부 0건"))

        # 앞 아이템의 늦은 응답은 지금 고른 아이템 이력을 덮지 않는다.
        panel.set_activity(9001001, ItemActivityKind.FIELD_CHANGE, load_history(self.settings, 9001001, 3))
        self.assertTrue(activity.status_label.text().startswith("#9001003"))

        # 구간을 전체로 바꾸면 다시 묻지 않고 거르기만 한다.
        request_count = len(requested)
        activity.select_scope("")
        self.assertEqual(len(requested), request_count)
        self.assertTrue(activity.status_label.text().startswith("#9001003 · 전체"))

    def test_comparison_history_export_saves_the_visible_range_in_background(self) -> None:
        panel = self._open_comparison_history()
        panel.detail_tabs.setCurrentWidget(panel.history_tab)
        self._app.processEvents()
        activity = panel.activity_panel
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(_DeferredTask(operation)) or tasks[-1]
        summary = ItemActivityExportSummary(entry_count=5, row_count=6, long_value_count=0)

        with (
            patch(
                "src.gui.item_activity_panel.QFileDialog.getSaveFileName",
                return_value=("history.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch("src.gui.item_activity_panel.export_item_activity_xlsx", return_value=summary) as export_mock,
        ):
            activity.export_button.click()

            self.assertEqual(len(tasks), 1)
            export_mock.assert_not_called()
            self.assertFalse(activity.export_button.isEnabled())
            self.assertIn("Excel 파일을 만드는 중입니다.", activity.status_label.text())

            tasks[0].finish()

        request = export_mock.call_args.args[0]
        tracker = self.page._current_tracker
        self.assertEqual(request.tracker_name, f"{tracker.name} (ID {tracker.tracker_id})")
        # 파일만 봐도 어느 두 시점인지 알 수 있어야 한다. 이름은 화면의 두 칸 글자 그대로다.
        reference_label, comparison_label = panel.source_labels()
        self.assertEqual(request.scope_label, f"비교 시점 사이 ({reference_label} → {comparison_label})")
        self.assertIn("Baseline", comparison_label)
        self.assertEqual(request.kind_labels, ("필드 변경", "댓글", "첨부"))
        self.assertEqual(len(request.entries), 5)
        self.assertTrue(activity.export_button.isEnabled())
        self.assertTrue(activity.status_label.text().endswith("Excel 내보내기 완료 · 항목 5건 · 행 6개"))

    def _request_comparison_attachments(self, reference_id: int | None, comparison_id: int | None) -> list[object]:
        """비교 결과의 두 시점을 바꿔 첨부를 요청하고, 첨부 조회에 넘어간 raw_payload 를 모아 돌려준다."""
        self._open_comparison_history()
        workspace = self.page.baseline_workspace
        result = workspace._baseline_comparison_result
        comparison = next(item for item in result.items if item.item_id == 9001001)
        comparison = replace(
            comparison,
            after=replace(comparison.after, raw_reference={"marker": "reference-side"}),
            before=replace(comparison.before, raw_reference={"marker": "comparison-side"}),
        )
        workspace._baseline_comparison_result = replace(
            result,
            after_source=BaselineComparisonSource(reference_id),
            before_source=BaselineComparisonSource(comparison_id),
        )
        payloads: list[object] = []
        self.page.content_service.load_attachments = (  # type: ignore[method-assign]
            lambda _settings, _item_id, **kwargs: payloads.append(kwargs.get("raw_payload")) or ()
        )
        workspace._load_comparison_activity(comparison, ItemActivityKind.ATTACHMENT, False)
        return payloads

    def test_comparison_attachments_never_cache_a_baseline_time_payload_as_current(self) -> None:
        """두 시점이 모두 Baseline 이면 그 시점 응답을 현재 첨부로 캐시하지 않도록 raw 를 넘기지 않는다."""
        self.assertEqual(self._request_comparison_attachments(24681001, 24681002), [None])

    def test_comparison_attachments_reuse_only_the_current_state_payload(self) -> None:
        self.assertEqual(self._request_comparison_attachments(None, 24681001), [{"marker": "reference-side"}])
        self.assertEqual(self._request_comparison_attachments(24681001, None), [{"marker": "comparison-side"}])

    def test_baseline_confirmation_cancel_does_not_call_full_compare(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        calls = []
        self.service.compare_tracker_at_sources = lambda *args, **kwargs: calls.append(
            (args, kwargs)
        )
        self.page.baseline_compare_confirmer = None
        panel.after_combo.addItem("R1", 11)
        panel.after_combo.setCurrentIndex(panel.after_combo.count() - 1)

        with patch(
            "src.gui.tracker_baseline_workspace.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Cancel,
        ) as warning:
            panel.run_button.click()
            self._app.processEvents()

        warning.assert_called_once()
        self.assertEqual(calls, [])
        self.assertIsNone(self.page.baseline_workspace._baseline_comparison_result)
        self.assertTrue(panel.run_button.isEnabled())
        self.assertEqual(panel.run_button.text(), "전체 비교 실행")

    def test_failed_same_source_reload_preserves_cached_baseline_result(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        result = compare_tracker_items(
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Earlier"}),),
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Current"}),),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        self.service.compare_tracker_at_sources = lambda *args, **kwargs: result
        panel.after_combo.addItem("R1", 11)
        panel.after_combo.setCurrentIndex(panel.after_combo.count() - 1)
        panel.run_button.click()
        self._app.processEvents()
        cached_key = self.page.baseline_workspace._baseline_comparison_cache_key
        detail_rows = panel.detail.rowCount()

        def fail_reload(*_args, **_kwargs):
            raise RuntimeError("reload failed")

        self.service.compare_tracker_at_sources = fail_reload
        panel.run_button.click()
        self._app.processEvents()

        self.assertIs(self.page.baseline_workspace._baseline_comparison_result, result)
        self.assertEqual(self.page.baseline_workspace._baseline_comparison_cache_key, cached_key)
        self.assertIs(panel._result, result)
        self.assertEqual(panel.detail.rowCount(), detail_rows)
        self.assertTrue(panel.export_button.isEnabled())
        self.assertEqual(panel.run_button.text(), "전체 비교 다시 불러오기")
        self.assertIn("reload failed", panel.status_label.text())
        self.assertEqual(len(self.baseline_compare_confirmations), 2)

    def test_stale_baseline_compare_failure_does_not_overwrite_new_sources(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        tasks = []
        alerts = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.error_notifier = lambda title, message: alerts.append((title, message))
        panel.after_combo.addItem("R1", 11)
        panel.after_combo.setCurrentIndex(panel.after_combo.count() - 1)

        panel.run_button.click()

        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0].started)
        self.assertIsNotNone(self.page.baseline_workspace._baseline_comparison_loading_key)

        panel.after_combo.setCurrentIndex(panel.after_combo.findData(None))
        expected_status = panel.status_label.text()
        tasks[0].emit_failure(RuntimeError("stale failure"))

        self.assertEqual(panel.status_label.text(), expected_status)
        self.assertIn("서로 다른", panel.status_label.text())
        self.assertEqual(alerts, [])
        self.assertIsNone(self.page.baseline_workspace._baseline_comparison_loading_key)

    def test_baseline_export_runs_in_background_and_restores_success_ui(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        result = compare_tracker_items(
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Earlier"}),),
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Current"}),),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        cache_key = (self.page._current_tracker.tracker_id, 11, None)
        self.page.baseline_workspace._baseline_comparison_result = result
        self.page.baseline_workspace._baseline_comparison_cache_key = cache_key
        panel.set_result(result)
        tasks = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        summary = SimpleNamespace(
            item_count=1,
            selected_field_count=1,
            data_row_count=1,
            long_value_count=0,
            long_value_part_count=0,
        )

        accepting_dialog = self._accepting_export_dialog(BaselineExportFieldDialog, ("name",))
        with (
            patch("src.gui.tracker_baseline_workspace.BaselineExportFieldDialog", accepting_dialog),
            patch(
                "src.gui.tracker_baseline_workspace.QFileDialog.getSaveFileName",
                return_value=("baseline.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch(
                "src.gui.tracker_baseline_workspace.export_baseline_comparison_xlsx",
                return_value=summary,
            ) as export_mock,
        ):

            self.page.baseline_workspace._export_baseline_comparison()

            self.assertEqual(len(tasks), 1)
            self.assertTrue(tasks[0].started)
            export_mock.assert_not_called()
            self.assertTrue(self.page.baseline_workspace._baseline_export_in_progress)
            self.assertFalse(panel.export_button.isEnabled())
            self.assertIn("생성하는 중", panel.status_label.text())

            self.page.baseline_workspace._export_baseline_comparison()
            self.assertEqual(len(tasks), 1)

            tasks[0].finish()

        export_mock.assert_called_once()
        self.assertFalse(self.page.baseline_workspace._baseline_export_in_progress)
        self.assertTrue(panel.export_button.isEnabled())
        self.assertIn("Excel 내보내기 완료", panel.status_label.text())
        self.assertTrue(tasks[0].deleted)

    def test_baseline_export_failure_restores_cached_result_actions(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        result = compare_tracker_items(
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Earlier"}),),
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Current"}),),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        self.page.baseline_workspace._baseline_comparison_result = result
        self.page.baseline_workspace._baseline_comparison_cache_key = (
            self.page._current_tracker.tracker_id,
            11,
            None,
        )
        panel.set_result(result)
        tasks = []
        alerts = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.error_notifier = lambda title, message: alerts.append((title, message))

        accepting_dialog = self._accepting_export_dialog(BaselineExportFieldDialog, ("name",))
        with (
            patch("src.gui.tracker_baseline_workspace.BaselineExportFieldDialog", accepting_dialog),
            patch(
                "src.gui.tracker_baseline_workspace.QFileDialog.getSaveFileName",
                return_value=("baseline.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch(
                "src.gui.tracker_baseline_workspace.export_baseline_comparison_xlsx",
                side_effect=RuntimeError("save failed"),
            ),
        ):

            self.page.baseline_workspace._export_baseline_comparison()
            tasks[0].finish()

        self.assertFalse(self.page.baseline_workspace._baseline_export_in_progress)
        self.assertTrue(panel.export_button.isEnabled())
        self.assertIn("save failed", panel.status_label.text())
        self.assertEqual(len(alerts), 1)
        self.assertIn("Baseline Excel 내보내기 실패", alerts[0][0])

    def test_new_and_deleted_items_do_not_show_fields_as_changed(self) -> None:
        self.page.activate()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        result = compare_tracker_items(
            (TrackerItemSummary.from_raw({"id": 9001002, "name": "Deleted"}),),
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "New"}),),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )

        panel.set_result(result, selected_item_id=9001001)

        self.assertIn("신규 아이템", panel.status_label.text())
        self.assertNotIn("변경 필드", panel.status_label.text())
        self.assertTrue(
            all(
                panel.detail.item(row, 3).text() == "＋ 신규"
                for row in range(panel.detail.rowCount())
            )
        )

        panel.select_item(9001002)

        self.assertIn("삭제 아이템", panel.status_label.text())
        self.assertNotIn("변경 필드", panel.status_label.text())
        self.assertTrue(
            all(
                panel.detail.item(row, 3).text() == "－ 삭제"
                for row in range(panel.detail.rowCount())
            )
        )

        self.page.baseline_workspace._baseline_comparison_result = result
        self.page.baseline_workspace._render_baseline_comparison_results()
        result_rows = {
            self.page.baseline_workspace.baseline_result_table.item(row, 1).text(): row
            for row in range(self.page.baseline_workspace.baseline_result_table.rowCount())
        }
        new_row = result_rows["9001001"]
        deleted_row = result_rows["9001002"]
        self.assertIn(
            "신규", self.page.baseline_workspace.baseline_result_table.item(new_row, 0).text()
        )
        self.assertEqual(
            self.page.baseline_workspace.baseline_result_table.item(new_row, 3).text(), "—"
        )
        self.assertEqual(
            self.page.baseline_workspace.baseline_result_table.item(deleted_row, 3).text(), "—"
        )

    def test_baseline_field_filter_ands_with_kind_and_search_without_server_calls(self) -> None:
        self.page.activate()
        result = compare_tracker_items(
            (
                TrackerItemSummary.from_raw(
                    {"id": 9001001, "name": "Earlier", "description": "old"}
                ),
                TrackerItemSummary.from_raw(
                    {"id": 9001003, "name": "Removed", "description": "gone"}
                ),
            ),
            (
                TrackerItemSummary.from_raw(
                    {"id": 9001001, "name": "Current", "description": "new"}
                ),
                TrackerItemSummary.from_raw(
                    {"id": 9001002, "name": "Added", "description": "fresh"}
                ),
            ),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        self.page.baseline_workspace._baseline_comparison_result = result
        self.page.baseline_workspace._populate_baseline_field_filter(result)
        self.page.baseline_workspace.baseline_comparison_panel.set_result(result, selected_item_id=9001001)
        detail_row_count = self.page.baseline_workspace.baseline_comparison_panel.detail.rowCount()
        compare_calls = self.service.baseline_compare_count

        self.page.baseline_workspace.baseline_field_filter.setCurrentIndex(
            self.page.baseline_workspace.baseline_field_filter.findData("description")
        )
        self.assertEqual(self.page.baseline_workspace.baseline_result_table.rowCount(), 3)
        self.assertEqual(
            self.page.baseline_workspace.baseline_comparison_panel.detail.rowCount(), detail_row_count
        )

        self.page.baseline_workspace.baseline_result_filter.setCurrentIndex(
            self.page.baseline_workspace.baseline_result_filter.findData(
                BaselineComparisonKind.ADDED.value
            )
        )
        self.assertEqual(self.page.baseline_workspace.baseline_result_table.rowCount(), 1)
        self.assertEqual(self.page.baseline_workspace.baseline_result_table.item(0, 1).text(), "9001002")

        self.page.baseline_workspace.baseline_result_search.setText("no match")
        self.assertEqual(self.page.baseline_workspace.baseline_result_table.rowCount(), 0)
        self.page.baseline_workspace.baseline_result_search.setText("Added")
        self.assertEqual(self.page.baseline_workspace.baseline_result_table.rowCount(), 1)
        self.assertEqual(self.service.baseline_compare_count, compare_calls)

        self.page.baseline_workspace._render_baseline_comparison_results()
        self.assertEqual(self.page.baseline_workspace.baseline_field_filter.currentData(), "description")

        self.page.baseline_workspace._on_baseline_sources_changed()
        self.assertEqual(self.page.baseline_workspace.baseline_result_filter.currentData(), "")
        self.assertEqual(self.page.baseline_workspace.baseline_field_filter.currentData(), "")
        self.assertEqual(self.page.baseline_workspace.baseline_result_search.text(), "")

    def test_baseline_export_uses_only_current_filtered_items(self) -> None:
        self.page.activate()
        result = compare_tracker_items(
            (
                TrackerItemSummary.from_raw({"id": 1, "name": "Before one"}),
                TrackerItemSummary.from_raw({"id": 2, "name": "Before two"}),
            ),
            (
                TrackerItemSummary.from_raw({"id": 1, "name": "After one"}),
                TrackerItemSummary.from_raw({"id": 2, "name": "After two"}),
            ),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        self.page.baseline_workspace._baseline_comparison_result = result
        self.page.baseline_workspace._baseline_comparison_cache_key = (
            self.page._current_tracker.tracker_id,
            11,
            None,
        )
        self.page.baseline_workspace._populate_baseline_field_filter(result)
        self.page.baseline_workspace.baseline_result_search.setText("After one")
        summary = SimpleNamespace(
            item_count=1,
            selected_field_count=1,
            data_row_count=1,
            long_value_count=0,
            long_value_part_count=0,
        )

        accepting_dialog = self._accepting_export_dialog(BaselineExportFieldDialog, ("name",))
        with (
            patch("src.gui.tracker_baseline_workspace.BaselineExportFieldDialog", accepting_dialog),
            patch(
                "src.gui.tracker_baseline_workspace.QFileDialog.getSaveFileName",
                return_value=("baseline.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch(
                "src.gui.tracker_baseline_workspace.export_baseline_comparison_xlsx",
                return_value=summary,
            ) as export_mock,
        ):
            self.page.baseline_workspace._export_baseline_comparison()

        exported_result = export_mock.call_args.args[0]
        self.assertEqual([item.item_id for item in exported_result.items], [1])

    def test_baseline_state_survives_tab_navigation_until_explicit_reload(self) -> None:
        self.page.activate()
        self.page.workspace_mode_tabs.setCurrentIndex(self.page.baseline_mode_index)
        self._app.processEvents()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        panel.after_combo.addItem("R1", 11)
        panel.after_combo.setCurrentIndex(panel.after_combo.count() - 1)
        self.page.baseline_workspace._baseline_selected_item_id = 9001001
        root = self.page.baseline_workspace.baseline_item_tree.topLevelItem(0)
        self.page.baseline_workspace.baseline_item_tree.blockSignals(True)
        self.page.baseline_workspace.baseline_item_tree.setCurrentItem(root)
        self.page.baseline_workspace.baseline_item_tree.blockSignals(False)
        result = compare_tracker_items(
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Earlier"}),),
            (TrackerItemSummary.from_raw({"id": 9001001, "name": "Current"}),),
            before_source=BaselineComparisonSource(11),
            after_source=BaselineComparisonSource(None),
        )
        panel.set_result(result)
        detail_rows = panel.detail.rowCount()

        self.page.workspace_mode_tabs.setCurrentIndex(0)
        self.page.workspace_mode_tabs.setCurrentIndex(self.page.baseline_mode_index)
        self._app.processEvents()

        self.assertEqual(self.service.baseline_load_count, 1)
        self.assertEqual(panel.after_combo.currentData(), 11)
        self.assertEqual(self.page.baseline_workspace._baseline_selected_item_id, 9001001)
        self.assertIs(self.page.baseline_workspace.baseline_item_tree.currentItem(), root)
        self.assertEqual(panel.detail.rowCount(), detail_rows)

        self.page.baseline_workspace.baseline_reload_button.click()
        self._app.processEvents()

        self.assertEqual(self.service.baseline_load_count, 2)
        self.assertIsNone(self.page.baseline_workspace._baseline_selected_item_id)
        self.assertEqual(panel.after_combo.currentData(), "")
        self.assertEqual(panel.detail.rowCount(), 0)

    def test_late_baseline_tab_children_after_tree_reload_are_ignored(self) -> None:
        """하위 조회가 끝나기 전에 Baseline 탭 트리를 다시 그려도 지워진 항목을 건드리지 않는다."""
        self.page.activate()
        self.page.workspace_mode_tabs.setCurrentIndex(self.page.baseline_mode_index)
        self._app.processEvents()
        workspace = self.page.baseline_workspace
        roots = self.page.hierarchy_panel.root_cache()[24680001]
        alerts: list[str] = []
        self.page.error_notifier = lambda _title, message: alerts.append(message)
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]

        workspace.baseline_item_tree.topLevelItem(0).setExpanded(True)
        workspace.render_roots(())
        tasks[0].finish()

        self.page.hierarchy_panel.child_cache().clear()
        workspace.render_roots(roots)
        workspace.baseline_item_tree.topLevelItem(0).setExpanded(True)
        workspace.render_roots(())
        tasks[1].emit_failure(RuntimeError("late failure"))

        self.assertEqual(len(tasks), 2)
        self.assertEqual(alerts, [])

    def test_direct_open_from_baseline_source_shows_current_state(self) -> None:
        """ID 바로 열기는 현재 상태를 연다. 조회 기준이 Baseline으로 남아 있으면 쓰기가 막힌다."""
        self.page.activate()
        panel = self.page.hierarchy_panel
        panel.hierarchy_source_combo.setCurrentIndex(panel.hierarchy_source_combo.findData(24681001))
        self._app.processEvents()
        self.assertEqual(panel.selected_baseline_id(), 24681001)
        self.page.direct_id_input.setText("9001002")

        self.page._open_direct_item()

        self.assertIsNone(panel.selected_baseline_id())
        self.assertFalse(self.page._is_historical_read_only())
        self.assertEqual(panel.reload_roots_button.text(), "현재 계층 다시 불러오기")
        # Baseline 목록은 남겨 다시 고를 수 있다.
        self.assertGreater(panel.hierarchy_source_combo.findData(24681001), 0)


if __name__ == "__main__":
    unittest.main()
