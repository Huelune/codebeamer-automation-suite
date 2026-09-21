from __future__ import annotations

import base64
import os
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog
from PySide6.QtWidgets import QMessageBox

from src.gui.settings_store import GuiSettings
from src.gui.tracker_baseline_compare import BaselineComparisonKind
from src.gui.tracker_baseline_compare import BaselineComparisonSource
from src.gui.tracker_baseline_compare import compare_tracker_items
from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_content_models import AttachmentResource
from src.gui.tracker_content_models import WikiRenderResult
from src.gui.tracker_content_models import WikiResourceReference
from src.gui.tracker_item_context_models import ItemRelationsSnapshot
from src.gui.tracker_item_create_dialog import TrackerItemCreateRequest
from src.gui.tracker_item_detail_dialog import TrackerItemDetailDialog
from src.gui.tracker_item_detail_session import TrackerItemDetailSession
from src.gui.tracker_item_editor import TrackerItemEditorService
from src.gui.tracker_item_editor import TrackerItemFieldChange
from src.gui.tracker_query_models import TrackerFieldValue
from src.gui.tracker_query_models import TrackerItemDetail
from src.gui.tracker_query_models import TrackerItemSummary
from src.gui.tracker_query_service import TrackerQueryService
from src.gui.tracker_workspace import CHILDREN_LOADED_ROLE
from src.gui.tracker_workspace import ITEM_SUMMARY_ROLE
from src.gui.tracker_workspace import TrackerWorkspacePage
from src.gui.wiki_content_view import WikiContentDialog
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "gui-offline-sample"


def _detail(item_id: int, name: str, *, version: int = 1) -> TrackerItemDetail:
    return TrackerItemDetail.from_raw(
        {
            "id": item_id,
            "name": name,
            "description": f"{name} description",
            "descriptionFormat": "PlainText",
            "version": version,
            "tracker": {
                "id": 24680001,
                "name": "Offline Requirements",
                "project": {"id": 246800, "name": "Offline Project"},
            },
        }
    )


class _SignalStub:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, value=None) -> None:
        for callback in tuple(self._callbacks):
            if value is None:
                callback()
            else:
                callback(value)


class _DeferredTask:
    def __init__(self, operation) -> None:
        self.operation = operation
        self.completed = _SignalStub()
        self.failed = _SignalStub()
        self.finished = _SignalStub()
        self.started = False
        self.deleted = False

    def start(self) -> None:
        self.started = True

    def finish(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            self.failed.emit(exc)
        else:
            self.completed.emit(result)
        finally:
            self.finished.emit()

    def emit_failure(self, exc: Exception) -> None:
        self.failed.emit(exc)
        self.finished.emit()

    def deleteLater(self) -> None:
        self.deleted = True


class CountingTrackerQueryService(TrackerQueryService):
    def __init__(self) -> None:
        super().__init__()
        self.child_load_count = 0
        self.baseline_compare_count = 0
        self.baseline_load_count = 0
        self.baseline_hierarchy_count = 0

    def load_all_child_items(self, *args, **kwargs):
        self.child_load_count += 1
        return super().load_all_child_items(*args, **kwargs)

    def compare_item_at_sources(self, *args, **kwargs):
        self.baseline_compare_count += 1
        return super().compare_item_at_sources(*args, **kwargs)

    def compare_tracker_at_sources(self, *args, **kwargs):
        self.baseline_compare_count += 1
        return super().compare_tracker_at_sources(*args, **kwargs)

    def load_tracker_baselines(self, *args, **kwargs):
        self.baseline_load_count += 1
        return super().load_tracker_baselines(*args, **kwargs)

    def load_baseline_hierarchy_snapshot(self, *args, **kwargs):
        self.baseline_hierarchy_count += 1
        return super().load_baseline_hierarchy_snapshot(*args, **kwargs)


EDITOR_SCHEMA = {
    "id": 20,
    "fields": [
        {
            "id": 3,
            "name": "Summary",
            "type": "TextField",
            "valueModel": "TextFieldValue",
            "trackerItemField": "name",
            "mandatory": True,
        },
        {
            "id": 7,
            "name": "Status",
            "type": "OptionChoiceField",
            "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            "trackerItemField": "status",
            "options": [
                {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
                {"id": 2, "name": "Review", "type": "ChoiceOptionReference"},
            ],
        },
    ],
}


class EditableWorkspaceClient:
    item = {}
    created_item = None
    calls: list[tuple] = []
    deleted = False

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    @classmethod
    def reset(cls) -> None:
        cls.item = {
            "id": 1001,
            "name": "Original summary",
            "description": "Editable detail",
            "descriptionFormat": "PlainText",
            "version": 1,
            "tracker": {"id": 20, "name": "Requirements"},
            "status": {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
            "assignedTo": [],
            "children": [],
            "customFields": [],
        }
        cls.calls = []
        cls.deleted = False
        cls.created_item = None

    def get_projects(self):
        return [{"id": 10, "name": "Vehicle"}]

    def get_trackers(self, project_id: int):
        return [{"id": 20, "name": "Requirements", "projectId": project_id}]

    def get_tracker(self, tracker_id: int):
        return {
            "id": tracker_id,
            "name": "Requirements",
            "project": {"id": 10, "name": "Vehicle"},
        }

    def get_tracker_schema(self, tracker_id: int):
        del tracker_id
        return deepcopy(EDITOR_SCHEMA)

    def get_tracker_children_page(self, tracker_id: int, *, page: int, page_size: int):
        del tracker_id
        if self.__class__.deleted:
            items = []
        else:
            item = self.__class__.item
            items = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "status": deepcopy(item["status"]),
                    "version": item["version"],
                    "hasChildren": False,
                }
            ]
        return {
            "page": page,
            "pageSize": page_size,
            "total": len(items),
            "itemRefs": items,
        }

    def get_item(self, item_id: int):
        self.__class__.calls.append(("get", item_id))
        if (
            self.__class__.created_item is not None
            and item_id == self.__class__.created_item["id"]
        ):
            return deepcopy(self.__class__.created_item)
        if self.__class__.deleted:
            raise KeyError(item_id)
        return deepcopy(self.__class__.item)

    def create_item(
        self,
        tracker_id: int,
        payload: dict,
        parent_item_id: int | None = None,
    ):
        self.__class__.calls.append(
            ("create", tracker_id, deepcopy(payload), parent_item_id)
        )
        created_item = {
            "id": 1002,
            "name": payload["name"],
            "description": payload.get("description", ""),
            "descriptionFormat": "PlainText",
            "version": 1,
            "tracker": {"id": tracker_id, "name": "Requirements"},
            "status": {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
            "assignedTo": [],
            "children": [],
            "customFields": deepcopy(payload.get("customFields", [])),
        }
        if parent_item_id is not None:
            created_item["parent"] = {
                "id": parent_item_id,
                "name": self.__class__.item["name"],
            }
        self.__class__.created_item = created_item
        return {"id": 1002}

    def update_item_fields(self, item_id: int, field_values: list[dict]):
        self.__class__.calls.append(("update", item_id, deepcopy(field_values)))
        for field_value in field_values:
            if field_value["fieldId"] == 3:
                self.__class__.item["name"] = field_value["value"]
            elif field_value["fieldId"] == 7:
                self.__class__.item["status"] = deepcopy(field_value["values"][0])
        self.__class__.item["version"] += 1
        return deepcopy(self.__class__.item)

    def delete_item(self, item_id: int):
        self.__class__.calls.append(("delete", item_id))
        self.__class__.deleted = True
        return {}


class TrackerWorkspacePageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.settings = GuiSettings(
            offline_mode=True,
            offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
            offline_tracker_configuration_path=str(
                SAMPLE_DIR / "offline_tracker_configuration.json"
            ),
            offline_query_data_path=str(SAMPLE_DIR / "offline_tracker_items.json"),
        )
        self.service = CountingTrackerQueryService()
        self.baseline_compare_confirmations = []

        def confirm_baseline_compare(reference, comparison) -> bool:
            self.baseline_compare_confirmations.append((reference, comparison))
            return True

        self.page = TrackerWorkspacePage(
            settings_provider=lambda: self.settings,
            service=self.service,
            baseline_compare_confirmer=confirm_baseline_compare,
            synchronous=True,
        )
        self.page.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self._app.processEvents()

    def test_activation_loads_project_tracker_and_top_level_items(self) -> None:
        self.page.activate()

        self.assertEqual(self.page.project_combo.count(), 1)
        self.assertEqual(self.page.project_combo.currentData(), 246800)
        self.assertEqual(self.page.tracker_combo.count(), 2)
        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)
        self.assertEqual(self.page.item_tree.topLevelItemCount(), 2)
        self.assertEqual(self.page.item_tree.columnCount(), 2)
        self.assertEqual(self.page.item_tree.headerItem().text(0), "ID")
        self.assertEqual(self.page.item_tree.headerItem().text(1), "요약")
        self.assertEqual(self.page.item_tree.topLevelItem(0).text(0), "9001001")
        self.assertIn("전체 표시", self.page.tree_status_label.text())
        self.assertIn("Offline Requirements", self.page.search_scope_label.text())
        self.assertTrue(self.page.search_button.isEnabled())
        self.assertFalse(self.page.create_item_button.isEnabled())

    def test_baseline_source_loads_full_read_only_hierarchy_and_detail(self) -> None:
        self.page.activate()

        self.assertEqual(self.page.hierarchy_source_combo.count(), 2)
        baseline_id = 24681001
        self.page.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_source_combo.findData(baseline_id)
        )
        self._app.processEvents()

        self.assertEqual(self.page.item_tree.topLevelItemCount(), 0)
        self.assertIn("Baseline 계층 조회", self.page.reload_roots_button.text())
        self.assertFalse(self.page.hierarchy_export_button.isEnabled())
        self.assertFalse(self.page.detail_panel.detail_tabs.isTabEnabled(self.page.detail_panel.editor_tab_index))
        self.page._create_item()
        self.assertIn("Baseline 조회 중", self.page.workspace_status_label.text())

        child_loads_before = self.service.child_load_count
        self.page.reload_roots_button.click()
        self._app.processEvents()

        self.assertEqual(self.page.item_tree.topLevelItemCount(), 1)
        self.assertTrue(self.page.hierarchy_export_button.isEnabled())
        root = self.page.item_tree.topLevelItem(0)
        self.assertEqual(root.text(0), "9001001")
        self.assertEqual(root.text(1), "Vehicle requirements baseline")
        self.assertEqual(root.childCount(), 2)
        self.assertTrue(root.data(0, CHILDREN_LOADED_ROLE))
        self.page._on_tree_item_expanded(root)
        self.assertEqual(self.service.child_load_count, child_loads_before)

        child = root.child(0)
        self.page.item_tree.setCurrentItem(child)
        self._app.processEvents()

        self.assertEqual(self.page.detail_panel._detail_baseline_id, baseline_id)
        self.assertEqual(self.page.detail_panel.detail_title.text(), "Brake system baseline · Baseline")
        self.assertIn("읽기 전용", self.page.detail_panel.detail_warning.text())
        self.assertFalse(self.page.detail_panel.detail_tabs.isTabEnabled(self.page.detail_panel.editor_tab_index))

        self.page.hierarchy_source_combo.setCurrentIndex(0)
        self._app.processEvents()

        self.assertIsNone(self.page.detail_panel._detail_baseline_id)
        self.assertEqual(self.page.item_tree.topLevelItemCount(), 2)
        self.assertTrue(self.page.hierarchy_export_button.isEnabled())

        self.page.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_source_combo.findData(baseline_id)
        )
        self._app.processEvents()
        self.assertEqual(self.page.item_tree.topLevelItemCount(), 1)
        self.assertEqual(self.service.baseline_hierarchy_count, 1)

    def test_stale_baseline_hierarchy_does_not_replace_current_tree(self) -> None:
        self.page.activate()
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]

        baseline_id = 24681001
        self.page.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_source_combo.findData(baseline_id)
        )
        self.page.reload_roots_button.click()
        self.assertEqual(len(tasks), 1)

        self.page.hierarchy_source_combo.setCurrentIndex(0)
        self.assertEqual(self.page.item_tree.topLevelItemCount(), 2)

        tasks[0].finish()
        self._app.processEvents()

        self.assertEqual(self.page.item_tree.topLevelItemCount(), 2)
        self.assertNotIn(
            (24680001, baseline_id),
            self.page._baseline_hierarchy_cache,
        )

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

        with (
            patch(
                "src.gui.tracker_workspace.TrackerHierarchyExportFieldDialog"
            ) as dialog_cls,
            patch(
                "src.gui.tracker_workspace.QFileDialog.getSaveFileName",
                return_value=("hierarchy.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch.object(
                self.service,
                "load_tracker_hierarchy_export_snapshot",
                return_value=snapshot,
            ) as snapshot_mock,
            patch(
                "src.gui.tracker_workspace.export_tracker_hierarchy_xlsx",
                return_value=summary,
            ) as export_mock,
        ):
            dialog_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_cls.return_value.selected_field_keys.return_value = (
                "status",
                "custom:101",
            )

            self.page.hierarchy_export_button.click()

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
        self.assertFalse(self.page._hierarchy_export_in_progress)
        self.assertTrue(self.page.hierarchy_export_button.isEnabled())
        self.assertIn("아이템 5개", self.page.tree_status_label.text())

    def test_baseline_hierarchy_export_reuses_loaded_snapshot(self) -> None:
        self.page.activate()
        baseline_id = 24681001
        self.page.hierarchy_source_combo.setCurrentIndex(
            self.page.hierarchy_source_combo.findData(baseline_id)
        )
        self.page.reload_roots_button.click()
        self._app.processEvents()
        loaded_snapshot = self.page._baseline_hierarchy_cache[
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

        with (
            patch(
                "src.gui.tracker_workspace.TrackerHierarchyExportFieldDialog"
            ) as dialog_cls,
            patch(
                "src.gui.tracker_workspace.QFileDialog.getSaveFileName",
                return_value=("baseline-hierarchy.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ) as file_dialog,
            patch(
                "src.gui.tracker_workspace.build_tracker_hierarchy_export_snapshot",
                return_value=export_snapshot,
            ) as build_mock,
            patch.object(
                self.service,
                "load_tracker_hierarchy_export_snapshot",
            ) as current_snapshot_mock,
            patch(
                "src.gui.tracker_workspace.export_tracker_hierarchy_xlsx",
                return_value=summary,
            ) as export_mock,
        ):
            dialog_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_cls.return_value.selected_field_keys.return_value = ("status",)

            self.page.hierarchy_export_button.click()

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
            baseline_name=self.page.hierarchy_source_combo.currentText(),
        )
        self.assertIn("아이템 3개", self.page.tree_status_label.text())

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

        with (
            patch(
                "src.gui.tracker_baseline_workspace.baseline_export_fields",
                return_value=(object(),),
            ),
            patch("src.gui.tracker_baseline_workspace.BaselineExportFieldDialog") as dialog_cls,
            patch(
                "src.gui.tracker_workspace.QFileDialog.getSaveFileName",
                return_value=("baseline.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch(
                "src.gui.tracker_baseline_workspace.export_baseline_comparison_xlsx",
                return_value=summary,
            ) as export_mock,
        ):
            dialog_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_cls.return_value.selected_field_keys.return_value = ("name",)

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

        with (
            patch(
                "src.gui.tracker_baseline_workspace.baseline_export_fields",
                return_value=(object(),),
            ),
            patch("src.gui.tracker_baseline_workspace.BaselineExportFieldDialog") as dialog_cls,
            patch(
                "src.gui.tracker_workspace.QFileDialog.getSaveFileName",
                return_value=("baseline.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch(
                "src.gui.tracker_baseline_workspace.export_baseline_comparison_xlsx",
                side_effect=RuntimeError("save failed"),
            ),
        ):
            dialog_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_cls.return_value.selected_field_keys.return_value = ("name",)

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

        with (
            patch("src.gui.tracker_baseline_workspace.BaselineExportFieldDialog") as dialog_cls,
            patch(
                "src.gui.tracker_workspace.QFileDialog.getSaveFileName",
                return_value=("baseline.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch(
                "src.gui.tracker_baseline_workspace.export_baseline_comparison_xlsx",
                return_value=summary,
            ) as export_mock,
        ):
            dialog_cls.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog_cls.return_value.selected_field_keys.return_value = ("name",)
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

    def test_unknown_child_metadata_keeps_tree_item_expandable(self) -> None:
        unknown = TrackerItemSummary.from_raw({"id": 1, "name": "Unknown"})
        known_empty = TrackerItemSummary.from_raw(
            {"id": 2, "name": "Empty", "hasChildren": False}
        )

        unknown_item = self.page._tree_item(unknown)
        empty_item = self.page._tree_item(known_empty)

        self.assertFalse(bool(unknown_item.data(0, CHILDREN_LOADED_ROLE)))
        self.assertEqual(unknown_item.childCount(), 1)
        self.assertTrue(bool(empty_item.data(0, CHILDREN_LOADED_ROLE)))
        self.assertEqual(empty_item.childCount(), 0)

    def test_expanding_node_loads_direct_children_once_and_reuses_cache(self) -> None:
        self.page.activate()
        root = self.page.item_tree.topLevelItem(0)

        self.page._on_tree_item_expanded(root)

        self.assertEqual(self.service.child_load_count, 1)
        self.assertEqual(root.childCount(), 2)
        self.assertEqual(root.child(0).text(0), "9001002")
        self.assertEqual(root.child(1).text(0), "9001003")

        self.page._on_tree_item_expanded(root)

        self.assertEqual(self.service.child_load_count, 1)
        steering = root.child(1)
        self.page._on_tree_item_expanded(steering)
        self.assertEqual(self.service.child_load_count, 2)
        self.assertEqual(steering.child(0).text(0), "9001004")

    def test_tree_selection_loads_read_only_detail_and_masked_raw_json(self) -> None:
        self.page.activate()
        root = self.page.item_tree.topLevelItem(0)
        self.page.item_tree.setCurrentItem(root)
        self._app.processEvents()

        self.assertEqual(self.page.detail_panel.detail_title.text(), "Vehicle requirements")
        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#9001001")
        self.assertTrue(self.page.detail_panel.detail_refresh_button.isEnabled())
        self.assertIn("Top-level sample requirement", self.page.detail_panel.detail_description.toPlainText())
        self.assertGreaterEqual(self.page.detail_panel.detail_fields_table.rowCount(), 10)
        self.assertIn('"Risk Level"', self.page.detail_panel.detail_raw_json.toPlainText())

    def test_detail_id_button_copies_numeric_id_only(self) -> None:
        self.page.activate()
        root = self.page.item_tree.topLevelItem(0)
        self.page.item_tree.setCurrentItem(root)
        self._app.processEvents()
        clipboard = self._app.clipboard()
        clipboard.clear()

        self.page.detail_panel.detail_id_badge.click()
        self._app.processEvents()

        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#9001001")
        self.assertEqual(clipboard.text(), "9001001")
        self.assertNotIn("#", clipboard.text())
        self.assertIn("9001001", self.page.workspace_status_label.text())
        self.assertIn("복사", self.page.workspace_status_label.text())

    def test_wiki_rendering_requires_explicit_format_or_field_type(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1200,
                "name": "Wiki detail",
                "description": "%%(color:red)__설명__%%",
                "descriptionFormat": "Wiki",
                "tracker": {"id": 24680001, "name": "Offline Requirements"},
                "customFields": [
                    {
                        "fieldId": 101,
                        "name": "Wiki field",
                        "type": "WikiTextFieldValue",
                        "value": "%%(color:blue)Wiki 값%%",
                    },
                    {
                        "fieldId": 102,
                        "name": "Plain field",
                        "type": "TextFieldValue",
                        "value": "%%(color:blue)원문 유지%%",
                    },
                    {
                        "fieldId": 103,
                        "name": "Steps",
                        "type": "TableFieldValue",
                        "values": [
                            [
                                {
                                    "fieldId": 104,
                                    "name": "Action",
                                    "type": "WikiTextFieldValue",
                                    "value": "%%red 실행%%",
                                }
                            ]
                        ],
                    },
                ],
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertTrue(self.page.detail_panel.description_source_toggle.isVisible())
        self.assertEqual(self.page.detail_panel.detail_description.toPlainText(), "설명")
        self.assertIsNotNone(self.page.detail_panel.detail_fields_table.cellWidget(9, 1))
        self.assertIsNone(self.page.detail_panel.detail_fields_table.cellWidget(10, 1))
        self.assertEqual(
            self.page.detail_panel.detail_fields_table.item(10, 1).text(),
            "%%(color:blue)원문 유지%%",
        )
        self.assertIsNotNone(self.page.detail_panel.detail_fields_table.cellWidget(11, 1))

        self.page.detail_panel.description_source_toggle.setChecked(True)
        self.assertEqual(
            self.page.detail_panel.detail_description.toPlainText(),
            "%%(color:red)__설명__%%",
        )

    def test_plain_description_keeps_wiki_like_text_unchanged(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1201,
                "name": "Plain detail",
                "description": "%%(color:red)원문%%",
                "descriptionFormat": "PlainText",
                "tracker": {"id": 24680001, "name": "Offline Requirements"},
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertFalse(self.page.detail_panel.description_source_toggle.isVisible())
        self.assertEqual(
            self.page.detail_panel.detail_description.toPlainText(),
            "%%(color:red)원문%%",
        )

    def test_current_detail_lists_embedded_attachment_metadata(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1202,
                "name": "Attachment detail",
                "version": 3,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
                "attachments": [
                    {
                        "id": 28,
                        "name": "sample.png",
                        "size": 2048,
                        "mimeType": "image/png",
                        "modifiedAt": "2026-08-13T10:00:00Z",
                        "uri": "/attachment/28",
                    }
                ],
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertEqual(self.page.detail_panel.attachment_table.rowCount(), 1)
        self.assertEqual(self.page.detail_panel.attachment_table.item(0, 0).text(), "sample.png")
        self.assertEqual(self.page.detail_panel.attachment_table.item(0, 1).text(), "2.0 KB")
        self.assertIsNotNone(self.page.detail_panel.attachment_table.cellWidget(0, 3))

    def test_current_detail_automatically_renders_image_attachment_in_memory(self) -> None:
        self.settings.offline_mode = False
        self.settings.base_url = "https://example.test/cb"
        self.settings.username = "sample"
        self.settings.password = "placeholder"
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        calls = []
        self.page.content_service.download_attachment = (
            lambda _settings, attachment, *, max_bytes: calls.append(
                (attachment.attachment_id, max_bytes)
            )
            or AttachmentResource(
                f"attachment-{attachment.attachment_id}",
                "image/png",
                png,
            )
        )
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1205,
                "name": "Image preview",
                "version": 1,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
                "attachments": [
                    {
                        "id": 28,
                        "name": "sample.png",
                        "size": len(png),
                        "mimeType": "image/png",
                    },
                    {
                        "id": 29,
                        "name": "sample.pdf",
                        "size": 100,
                        "mimeType": "application/pdf",
                    },
                ],
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertTrue(self.page.detail_panel.attachment_preview.isVisible())
        self.assertIn("cb-attachment://attachment-28", self.page.detail_panel.attachment_preview.text())
        self.assertTrue(self.page.detail_panel.attachment_preview_button.isVisible())
        self.assertTrue(self.page.detail_panel.attachment_preview_button.isEnabled())
        self.assertEqual(calls, [(28, 10 * 1024 * 1024)])
        self.assertEqual(self.page.detail_panel._inline_image_bytes, len(png))

        with patch("src.gui.tracker_detail_panel.WikiContentDialog") as dialog_class:
            self.page.detail_panel._open_attachment_preview()

        dialog_class.assert_called_once()
        dialog_class.return_value.resize.assert_called_once_with(1100, 760)
        dialog_class.return_value.view.add_attachment_resource.assert_called_once()
        dialog_class.return_value.exec.assert_called_once()
        self.assertEqual(calls, [(28, 10 * 1024 * 1024)])

        with patch("src.gui.tracker_detail_dialog.TrackerItemDetailDialog") as detail_dialog:
            self.page.detail_dialog.open_dialog()

        detail_dialog.assert_called_once()
        detail_kwargs = detail_dialog.call_args.kwargs
        self.assertEqual(detail_kwargs["attachments"], self.page.detail_panel._attachments)
        self.assertEqual(len(detail_kwargs["image_resources"]), 1)
        detail_dialog.return_value.exec.assert_called_once()

    def test_detail_dialog_is_built_with_the_real_class(self) -> None:
        """상세 창을 진짜 클래스로 만들어 본다.

        다른 테스트는 TrackerItemDetailDialog 를 통째로 patch 하므로 생성자가
        한 번도 불리지 않는다. 그래서 parent 처럼 생성자에서만 드러나는 잘못된
        인자를 잡지 못한다. 여기서는 exec 만 막고 실제로 만든다.
        """
        self.page.activate()
        self.page.item_tree.setCurrentItem(self.page.item_tree.topLevelItem(0))
        self._app.processEvents()
        detail = self.page.detail_panel._current_detail
        self.assertIsNotNone(detail)

        opened: list[TrackerItemDetailDialog] = []

        class _NonModalDialog(TrackerItemDetailDialog):
            def exec(self) -> int:
                opened.append(self)
                return 0

        with patch(
            "src.gui.tracker_detail_dialog.TrackerItemDetailDialog", _NonModalDialog
        ):
            self.page.detail_dialog.open_dialog()

        self.assertEqual(len(opened), 1)
        try:
            self.assertIn(str(detail.item_id), opened[0].windowTitle())
            self.assertIs(opened[0].parent(), self.page)
        finally:
            # 진짜 창이라 닫아 둔다. 파괴는 부모인 page 가 맡는다.
            opened[0].close()
            self._app.processEvents()

    def test_wiki_field_dialog_is_built_with_the_real_class(self) -> None:
        """Wiki 필드 창도 진짜 클래스로 만들어 본다.

        [[test_detail_dialog_is_built_with_the_real_class]] 와 같은 이유다.
        이 창들은 지금까지 patch 로만 확인해서 생성자 인자가 검증된 적이 없다.
        """
        self.page.activate()
        self.page.item_tree.setCurrentItem(self.page.item_tree.topLevelItem(0))
        self._app.processEvents()
        field = TrackerFieldValue(
            field_id=101,
            name="Risk Level",
            type_name="WikiTextFieldValue",
            display_value="본문",
        )
        opened: list[WikiContentDialog] = []

        class _NonModalDialog(WikiContentDialog):
            def exec(self) -> int:
                opened.append(self)
                return 0

        with patch("src.gui.tracker_detail_panel.WikiContentDialog", _NonModalDialog):
            self.page.detail_panel._open_wiki_field(field)

        self.assertEqual(len(opened), 1)
        try:
            self.assertIs(opened[0].parent(), self.page.detail_panel)
        finally:
            opened[0].close()
            self._app.processEvents()

    def test_popped_out_editor_window_is_built_with_the_real_class(self) -> None:
        """수정 창 분리도 진짜 클래스로 만들어 본다."""
        self.page.activate()
        self.page.item_tree.setCurrentItem(self.page.item_tree.topLevelItem(0))
        self._app.processEvents()

        self.page.detail_panel._show_editor_in_window()
        self._app.processEvents()

        dialog = self.page.detail_panel._editor_dialog
        self.assertIsNotNone(dialog)
        try:
            self.assertIs(dialog.parent(), self.page.detail_panel)
        finally:
            self.page.detail_panel._restore_editor_panel()
            self._app.processEvents()

    def test_related_detail_failure_keeps_dialog_session_and_context_usable(self) -> None:
        detail = _detail(1205, "Current", version=3)
        dialog = TrackerItemDetailDialog(detail, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(1204, 2)
        session.navigate(detail.item_id, detail.version)
        dialog.set_navigation_state(
            can_go_back=session.can_go_back,
            can_go_forward=session.can_go_forward,
        )
        tasks: list[_DeferredTask] = []
        alerts = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.error_notifier = lambda title, message: alerts.append((title, message))

        self.page.detail_dialog.navigate(dialog, session, 1206)

        self.assertEqual(session.current.item_id, 1205)
        self.assertEqual(dialog.detail.item_id, 1205)
        self.assertFalse(dialog.back_button.isEnabled())
        tasks[0].emit_failure(ValueError("not found"))

        self.assertEqual(session.current.item_id, 1205)
        self.assertEqual(dialog.detail.item_id, 1205)
        self.assertTrue(dialog.back_button.isEnabled())
        self.assertFalse(dialog.forward_button.isEnabled())
        self.assertEqual(
            alerts,
            [
                (
                    "관련 아이템 상세 조회 실패",
                    "관련 아이템 상세 조회 실패: not found",
                )
            ],
        )
        self.assertIn("탭을 열면", dialog.relations_status.text())

        self.page.synchronous = True
        self.page.context_service.load_relations = lambda *_args, **_kwargs: (
            ItemRelationsSnapshot.from_raw(
                {
                    "downstreamReferences": [
                        {"itemRevision": {"id": 1207, "name": "Related"}}
                    ]
                }
            )
        )
        self.page.detail_dialog.load_context(dialog, session, "relations")
        self.assertEqual(dialog.relations_table.rowCount(), 1)
        dialog.close()

    def test_history_navigation_failure_does_not_commit_peeked_target(self) -> None:
        detail = _detail(1205, "Current", version=3)
        dialog = TrackerItemDetailDialog(detail, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(1204, 2)
        session.navigate(detail.item_id, detail.version)
        dialog.set_navigation_state(
            can_go_back=session.can_go_back,
            can_go_forward=session.can_go_forward,
        )
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]

        self.page.detail_dialog.navigate_history(dialog, session, back=True)
        tasks[0].emit_failure(ValueError("not found"))

        self.assertEqual(session.current.item_id, 1205)
        self.assertEqual(dialog.detail.item_id, 1205)
        self.assertTrue(session.can_go_back)
        self.assertFalse(session.can_go_forward)
        dialog.close()

    def test_related_detail_success_commits_session_after_loading(self) -> None:
        current = _detail(1205, "Current", version=3)
        target = _detail(1206, "Target", version=4)
        dialog = TrackerItemDetailDialog(current, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(current.item_id, current.version)
        self.page.service.load_detail = lambda *_args, **_kwargs: target

        with patch.object(self.page.detail_dialog, "hydrate") as hydrate:
            self.page.detail_dialog.navigate(dialog, session, target.item_id)

        self.assertEqual(session.current.item_id, target.item_id)
        self.assertEqual(dialog.detail.item_id, target.item_id)
        self.assertTrue(session.can_go_back)
        self.assertTrue(dialog.back_button.isEnabled())
        hydrate.assert_called_once()
        dialog.close()

    def test_comment_response_from_previous_generation_is_discarded_after_aba_navigation(self) -> None:
        current = _detail(1205, "Current", version=3)
        other = _detail(1206, "Other", version=1)
        dialog = TrackerItemDetailDialog(current, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(current.item_id, current.version)
        snapshot = ItemCommentsSnapshot.from_raw([{"id": 1, "comment": "old"}])
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.comment_service.load_comments = lambda *_args, **_kwargs: snapshot

        self.page.detail_dialog.load_comments(dialog, session)
        session.navigate(other.item_id, other.version)
        dialog.replace_detail(other, description_html="<p>Other</p>")
        session.back()
        dialog.replace_detail(current, description_html="<p>Current</p>")
        tasks[0].finish()

        self.assertEqual(dialog.comment_views, {})
        self.assertEqual(dialog._comments_state, "idle")

        self.page.detail_dialog.load_comments(dialog, session)
        tasks[1].finish()
        self.assertEqual(set(dialog.comment_views), {"1"})
        dialog.close()

    def test_comment_image_from_previous_generation_is_discarded(self) -> None:
        current = _detail(1205, "Current", version=3)
        other = _detail(1206, "Other", version=1)
        dialog = TrackerItemDetailDialog(current, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(current.item_id, current.version)
        snapshot = ItemCommentsSnapshot.from_raw(
            [
                {
                    "id": 1,
                    "comment": "image",
                    "attachments": [
                        {
                            "id": 28,
                            "name": "evidence.png",
                            "mimeType": "image/png",
                        }
                    ],
                }
            ]
        )
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.comment_service.load_comments = lambda *_args, **_kwargs: snapshot
        self.page.content_service.download_attachment = (
            lambda *_args, **_kwargs: AttachmentResource(
                "attachment-28",
                "image/png",
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                ),
            )
        )

        self.page.detail_dialog.load_comments(dialog, session)
        tasks[0].finish()
        self.assertEqual(len(tasks), 2)

        session.navigate(other.item_id, other.version)
        dialog.replace_detail(other, description_html="<p>Other</p>")
        session.back()
        dialog.replace_detail(current, description_html="<p>Current</p>")
        with patch.object(dialog, "add_comment_resource", wraps=dialog.add_comment_resource) as add_resource:
            tasks[1].finish()

        add_resource.assert_not_called()
        self.assertEqual(dialog.comment_views, {})
        dialog.close()

    def test_baseline_detail_does_not_mix_current_attachment_metadata(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1203,
                "name": "Historical detail",
                "version": 2,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
                "attachments": [{"id": 28, "name": "latest.png"}],
            }
        )

        self.page.detail_panel.render_detail(detail, baseline_id=24681001)

        self.assertEqual(self.page.detail_panel.attachment_table.rowCount(), 0)
        self.assertIn("Baseline", self.page.detail_panel.attachment_status_label.text())
        self.assertFalse(self.page.detail_panel.attachment_reload_button.isEnabled())

    def test_inline_image_budget_limits_scheduled_downloads_to_five_images(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1204,
                "name": "Image detail",
                "version": 1,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
            }
        )
        self.page.detail_panel.render_detail(detail)
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.content_service.download_resource = lambda *args, **kwargs: AttachmentResource(
            kwargs["resource_key"],
            "image/png",
            b"not-executed",
        )
        result = WikiRenderResult(
            html="<p>images</p>",
            resources=tuple(
                WikiResourceReference(f"image-{index}", f"https://example.test/cb/attachment/{index}")
                for index in range(6)
            ),
        )

        self.page.detail_panel._load_inline_resources(result, self.page.detail_panel.detail_description, detail, None)

        self.assertEqual(len(tasks), 5)
        self.assertEqual(len(self.page.detail_panel._inline_resource_reservations), 5)

    def test_scheduled_inline_downloads_keep_their_own_resource(self) -> None:
        """예약된 다운로드가 각자의 참조를 들고 있는지 확인한다.

        콜백이 반복문 변수를 늦게 바인딩하면 5개가 모두 마지막 이미지를 내려받는다.
        화면에는 이미지가 그려지므로 눈으로는 알아채기 어렵다.
        """
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1205,
                "name": "Image detail",
                "version": 1,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
            }
        )
        self.page.detail_panel.render_detail(detail)
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        requested_keys: list[str] = []

        def record_download(*_args, **kwargs) -> AttachmentResource:
            requested_keys.append(kwargs["resource_key"])
            return AttachmentResource(kwargs["resource_key"], "image/png", b"payload")

        self.page.content_service.download_resource = record_download
        result = WikiRenderResult(
            html="<p>images</p>",
            resources=tuple(
                WikiResourceReference(f"image-{index}", f"https://example.test/cb/attachment/{index}")
                for index in range(3)
            ),
        )

        self.page.detail_panel._load_inline_resources(result, self.page.detail_panel.detail_description, detail, None)
        for task in tasks:
            task.operation()

        self.assertEqual(requested_keys, ["image-0", "image-1", "image-2"])

    def test_test_mode_editor_loads_schema_but_disables_write_actions(self) -> None:
        self.page.activate()
        self.page.item_tree.setCurrentItem(self.page.item_tree.topLevelItem(0))
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
        self.page.search_text_input.setText("Steering")

        self.page._run_search()

        requirement_ids = {
            int(self.page.search_table.item(row, 1).text())
            for row in range(self.page.search_table.rowCount())
        }
        self.assertEqual(requirement_ids, {9001003, 9001004})

        self.page._on_tracker_activated(1)
        self.page.search_text_input.setText("Steering")
        self.page._run_search()

        test_case_ids = {
            int(self.page.search_table.item(row, 1).text())
            for row in range(self.page.search_table.rowCount())
        }
        self.assertEqual(test_case_ids, {9101002})
        self.assertNotIn(9001003, test_case_ids)
        self.assertIn("Offline Test Cases", self.page.search_scope_label.text())

    def test_search_result_selection_supports_page_and_all_query_modes(self) -> None:
        from PySide6.QtCore import Qt

        self.page.activate()
        self.page.search_text_input.setText("Steering")
        self.page._run_search()

        self.page._select_current_search_page()
        self.assertEqual(self.page._selected_search_ids, {9001003, 9001004})
        self.assertEqual(self.page._selected_search_count(), 2)

        self.page._select_all_search_results()
        self.assertTrue(self.page._all_search_selected)
        self.assertEqual(self.page._selected_search_count(), 2)
        first_checkbox = self.page.search_table.item(0, 0)
        first_checkbox.setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(self.page._selected_search_count(), 1)
        self.assertEqual(len(self.page._excluded_search_ids), 1)

    def test_condition_search_mode_loads_schema_and_builds_condition_query(self) -> None:
        self.page.activate()
        self.page.browser_tabs.setCurrentIndex(1)
        mode_index = self.page.search_mode_combo.findData("conditions")
        self.page.search_mode_combo.setCurrentIndex(mode_index)
        self.assertTrue(self.page.condition_search_host.isVisible())
        self.assertFalse(self.page.condition_dialog.isVisible())
        self.assertEqual(self.page.search_button.text(), "상세 조건으로 검색")
        self.assertIn("조건 묶음 1개", self.page.condition_summary_label.text())

        self.page.condition_open_button.click()
        self._app.processEvents()
        self.assertTrue(self.page.condition_dialog.isVisible())
        self.assertGreaterEqual(self.page.condition_dialog.width(), 860)
        self.assertGreaterEqual(self.page.condition_dialog.height(), 600)

        group = self.page.condition_builder.groups[0]
        row = group.rows[0]
        summary_index = row.field_combo.findText("Summary")
        row.field_combo.setCurrentIndex(summary_index)
        contains_index = row.operator_combo.findData("contains")
        row.operator_combo.setCurrentIndex(contains_index)
        row.value_input.setText("Steering")
        self.page.condition_dialog.close_button.click()
        self._app.processEvents()
        self.assertFalse(self.page.condition_dialog.isVisible())
        self.assertEqual(
            self.page.condition_builder.groups[0].rows[0].value_input.text(),
            "Steering",
        )

        self.page._run_search()

        self.assertIsNotNone(self.page._last_search_query)
        self.assertEqual(self.page._last_search_query.mode.value, "conditions")
        self.assertEqual(self.page.search_table.rowCount(), 2)

        self.page.search_mode_combo.setCurrentIndex(0)
        self._app.processEvents()
        self.assertFalse(self.page.condition_dialog.isVisible())
        self.assertEqual(self.page.search_button.text(), "현재 트래커 검색")

    def test_direct_id_open_resolves_other_tracker_and_builds_ancestor_path(self) -> None:
        self.page.activate()
        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)
        self.page.direct_id_input.setText("9101002")

        self.page._open_direct_item()

        self.assertEqual(self.page.tracker_combo.currentData(), 24680002)
        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#9101002")
        self.assertEqual(self.page.detail_panel.detail_title.text(), "Steering response test")
        self.assertEqual(self.page.item_tree.topLevelItemCount(), 1)
        root = self.page.item_tree.topLevelItem(0)
        self.assertEqual(root.text(0), "9101001")
        self.assertEqual(root.childCount(), 1)
        self.assertEqual(root.child(0).text(0), "9101002")
        self.assertIn("ID 직접 접근 경로", self.page.tree_status_label.text())

    def test_search_requires_filter_instead_of_loading_entire_tracker(self) -> None:
        self.page.activate()

        self.page._run_search()

        self.assertEqual(self.page.search_table.rowCount(), 0)
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
            self.assertEqual(len(starts), 4)
            self.assertEqual(finishes, [3, 4, 2, 1])
            self.assertIn("프로젝트", starts[0])
            self.assertIn("트래커", starts[1])
            self.assertIn("최상위 아이템", starts[2])
            self.assertIn("baseline 목록", starts[3])
        finally:
            page.close()

    def test_tree_items_store_normalized_models_not_server_dicts(self) -> None:
        self.page.activate()
        value = self.page.item_tree.topLevelItem(0).data(0, ITEM_SUMMARY_ROLE)

        self.assertEqual(value.item_id, 9001001)
        self.assertEqual(value.tracker_id, 24680001)
        self.assertFalse(isinstance(value, dict))


class TrackerWorkspaceWriteIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        EditableWorkspaceClient.reset()
        self.settings = GuiSettings(
            base_url="https://example.test/cb",
            username="sample",
            password="placeholder",
        )
        query_service = TrackerQueryService(client_factory=EditableWorkspaceClient)
        editor_service = TrackerItemEditorService(
            client_factory=EditableWorkspaceClient,
            query_service=query_service,
        )
        self.activities = []
        self.page = TrackerWorkspacePage(
            settings_provider=lambda: self.settings,
            service=query_service,
            editor_service=editor_service,
            delete_confirmer=lambda detail: detail.item_id == 1001,
            activity_recorder=self.activities.append,
            synchronous=True,
        )
        self.page.show()
        self.page.activate()
        self.page.item_tree.setCurrentItem(self.page.item_tree.topLevelItem(0))
        self._app.processEvents()
        self.page.detail_panel.detail_tabs.setCurrentIndex(self.page.detail_panel.editor_tab_index)
        self._app.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self._app.processEvents()

    def test_field_update_status_field_change_and_delete_refresh_visible_state(self) -> None:
        from PySide6.QtCore import Qt

        summary_row = self.page.detail_panel.editor_panel.rows[3]
        self.page.detail_panel.editor_panel.field_table.item(summary_row.row, 0).setCheckState(
            Qt.CheckState.Checked
        )
        summary_row.widget.setText("Changed summary")
        self.page.detail_panel.editor_panel.save_button.click()

        self.assertEqual(self.page.detail_panel.detail_title.text(), "Changed summary")
        self.assertEqual(self.page.item_tree.topLevelItem(0).text(1), "Changed summary")
        update_calls = [call for call in EditableWorkspaceClient.calls if call[0] == "update"]
        self.assertEqual(update_calls[0][2][0]["fieldId"], 3)

        target_index = self.page.detail_panel.editor_panel.status_combo.findData(2)
        self.page.detail_panel.editor_panel.status_combo.setCurrentIndex(target_index)
        self.page.detail_panel.editor_panel.transition_button.click()

        self.assertEqual(self.page.item_tree.columnCount(), 2)
        self.assertEqual(self.page.detail_panel.detail_fields_table.item(3, 1).text(), "Review")

        self.page.detail_panel.editor_panel.delete_button.click()

        self.assertTrue(EditableWorkspaceClient.deleted)
        self.assertEqual(self.page.item_tree.topLevelItemCount(), 0)
        self.assertEqual(self.page.detail_panel.detail_title.text(), "아이템 상세")
        self.assertIn(("delete", 1001), EditableWorkspaceClient.calls)
        self.assertEqual(
            [record.operation.value for record in self.activities],
            ["tracker_update", "status_transition", "tracker_delete"],
        )

    def test_version_conflict_keeps_editor_and_visible_item_unchanged(self) -> None:
        from PySide6.QtCore import Qt

        summary_row = self.page.detail_panel.editor_panel.rows[3]
        self.page.detail_panel.editor_panel.field_table.item(summary_row.row, 0).setCheckState(
            Qt.CheckState.Checked
        )
        summary_row.widget.setText("Should not save")
        EditableWorkspaceClient.item["version"] = 9

        self.page.detail_panel.editor_panel.save_button.click()

        self.assertEqual(self.page.detail_panel.detail_title.text(), "Original summary")
        self.assertEqual(self.page.item_tree.topLevelItem(0).text(1), "Original summary")
        self.assertIn("다른 사용자가", self.page.workspace_status_label.text())
        self.assertFalse(
            any(call[0] == "update" for call in EditableWorkspaceClient.calls)
        )
        self.assertEqual(self.activities[-1].operation.value, "tracker_update")
        self.assertEqual(self.activities[-1].result.value, "failed")

    def test_editor_moves_to_large_window_without_losing_input_state(self) -> None:
        from PySide6.QtCore import Qt

        summary_row = self.page.detail_panel.editor_panel.rows[3]
        check_item = self.page.detail_panel.editor_panel.field_table.item(summary_row.row, 0)
        check_item.setCheckState(Qt.CheckState.Checked)
        summary_row.widget.setText("Unsaved detached value")

        self.page.detail_panel.popout_editor_button.click()
        self._app.processEvents()

        dialog = self.page.detail_panel._editor_dialog
        self.assertIsNotNone(dialog)
        self.assertIs(self.page.detail_panel.editor_panel.parent(), dialog)
        self.assertTrue(self.page.detail_panel.editor_placeholder.isVisible())
        self.assertEqual(summary_row.widget.text(), "Unsaved detached value")
        self.assertEqual(check_item.checkState(), Qt.CheckState.Checked)

        dialog.fullscreen_button.setChecked(True)
        self._app.processEvents()
        self.assertTrue(dialog.isFullScreen())
        dialog.fullscreen_button.setChecked(False)
        dialog.close()
        self._app.processEvents()

        self.assertIsNone(self.page.detail_panel._editor_dialog)
        self.assertIs(self.page.detail_panel.editor_panel.parent(), self.page.detail_panel.editor_host)
        self.assertFalse(self.page.detail_panel.editor_placeholder.isVisible())
        self.assertEqual(summary_row.widget.text(), "Unsaved detached value")
        self.assertEqual(check_item.checkState(), Qt.CheckState.Checked)

    def test_single_create_adds_selected_child_and_opens_created_detail(self) -> None:
        def create_request(schema, tracker, selected_detail):
            self.assertEqual(tracker.tracker_id, 20)
            self.assertEqual(selected_detail.item_id, 1001)
            summary = next(field for field in schema.fields if field.name == "Summary")
            return TrackerItemCreateRequest(
                changes=(TrackerItemFieldChange(summary, "Created child"),),
                parent_item_id=selected_detail.item_id,
            )

        self.page.create_request_provider = create_request
        self.page.create_item_button.click()
        self._app.processEvents()

        create_call = next(
            call for call in EditableWorkspaceClient.calls if call[0] == "create"
        )
        self.assertEqual(create_call[1], 20)
        self.assertEqual(create_call[2], {"name": "Created child"})
        self.assertEqual(create_call[3], 1001)
        root = self.page.item_tree.topLevelItem(0)
        self.assertEqual(root.childCount(), 1)
        self.assertEqual(root.child(0).text(0), "1002")
        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#1002")
        self.assertEqual(self.page.detail_panel.detail_title.text(), "Created child")
        self.assertIn("생성했습니다", self.page.workspace_status_label.text())
        self.assertEqual(self.activities[-1].operation.value, "tracker_create")
        self.assertEqual(self.activities[-1].item_id, 1002)


if __name__ == "__main__":
    unittest.main()
