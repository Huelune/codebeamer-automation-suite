"""작업 공간의 저장·생성·삭제와 일괄 수정 통합 테스트."""

from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from src.gui.settings_store import GuiSettings
from src.gui.tracker_bulk_update import BulkFieldChange
from src.gui.tracker_bulk_update import BulkUpdateRunResult
from src.gui.tracker_bulk_update import BulkUpdateRunStore
from src.gui.tracker_bulk_update import TrackerBulkUpdateService
from src.gui.tracker_bulk_update import bulk_run_server_key
from src.gui.tracker_bulk_update_dialog import BulkUpdateRequest
from src.gui.tracker_bulk_update_dialog import TrackerBulkUpdateDialog
from src.gui.tracker_item_create_dialog import TrackerItemCreateDialog
from src.gui.tracker_item_create_dialog import TrackerItemCreateRequest
from src.gui.tracker_item_editor import TrackerItemEditorService
from src.gui.tracker_item_editor import TrackerItemFieldChange
from src.gui.tracker_item_editor_panel import ConfirmItemDeleteDialog
from src.gui.tracker_query_models import TrackerItemDetail
from src.gui.tracker_query_service import TrackerQueryService
from src.gui.tracker_workspace import TrackerWorkspacePage
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401
from tests.tracker_workspace_fixtures import EditableWorkspaceClient
from tests.tracker_workspace_fixtures import _DeferredTask


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
        self.page.hierarchy_panel.item_tree.setCurrentItem(self.page.hierarchy_panel.item_tree.topLevelItem(0))
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
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItem(0).text(0), "Changed summary")
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItem(0).toolTip(0), "Changed summary")
        update_calls = [call for call in EditableWorkspaceClient.calls if call[0] == "update"]
        self.assertEqual(update_calls[0][2][0]["fieldId"], 3)

        target_index = self.page.detail_panel.editor_panel.status_combo.findData(2)
        self.page.detail_panel.editor_panel.status_combo.setCurrentIndex(target_index)
        self.page.detail_panel.editor_panel.transition_button.click()

        self.assertEqual(self.page.hierarchy_panel.item_tree.columnCount(), 2)
        self.assertEqual(self.page.detail_panel.detail_fields_table.item(3, 1).text(), "Review")

        self.page.detail_panel.editor_panel.delete_button.click()

        self.assertTrue(EditableWorkspaceClient.deleted)
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 0)
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
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItem(0).text(0), "Original summary")
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

    @staticmethod
    def _other_detail() -> TrackerItemDetail:
        return TrackerItemDetail.from_raw(
            {"id": 1009, "name": "Another item", "version": 1, "tracker": {"id": 20, "name": "Requirements"}}
        )

    def test_late_save_result_does_not_replace_another_open_item(self) -> None:
        """저장이 끝나기 전에 다른 아이템을 열었으면 그 화면을 저장한 아이템으로 바꾸지 않는다."""
        from PySide6.QtCore import Qt

        editor = self.page.detail_panel.editor_panel
        summary_row = editor.rows[3]
        editor.field_table.item(summary_row.row, 0).setCheckState(Qt.CheckState.Checked)
        summary_row.widget.setText("Saved late")
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        editor.save_button.click()
        self.page.detail_panel.render_detail(self._other_detail())

        tasks[0].finish()

        self.assertEqual(self.page.detail_panel.detail_title.text(), "Another item")
        # 저장은 끝났으므로 계층의 그 아이템은 새 이름으로 바뀐다.
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItem(0).text(0), "Saved late")
        self.assertEqual(self.activities[-1].operation.value, "tracker_update")

    def test_late_delete_result_does_not_clear_another_open_item(self) -> None:
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.detail_panel.editor_panel.delete_button.click()
        self.page.detail_panel.render_detail(self._other_detail())

        tasks[0].finish()

        self.assertEqual(self.page.detail_panel.detail_title.text(), "Another item")
        self.assertEqual(self.page.hierarchy_panel.item_tree.topLevelItemCount(), 0)

    def test_delete_uses_the_real_dialog_that_needs_the_item_id(self) -> None:
        """삭제 확인 창을 실제 생성자로 띄운다. ID를 입력해야 삭제 버튼이 켜진다."""
        enabled_before_typing = []

        class _TypingDialog(ConfirmItemDeleteDialog):
            def exec(self) -> int:
                enabled_before_typing.append(self.delete_button.isEnabled())
                self.confirm_input.setText(str(self.detail.item_id))
                self.delete_button.click()
                return self.result()

        self.page.detail_panel.delete_confirmer = None
        with patch("src.gui.tracker_detail_panel.ConfirmItemDeleteDialog", _TypingDialog):
            self.page.detail_panel.editor_panel.delete_button.click()

        self.assertEqual(enabled_before_typing, [False])
        self.assertIn(("delete", 1001), EditableWorkspaceClient.calls)

    def test_create_uses_the_real_dialog(self) -> None:
        class _FillingDialog(TrackerItemCreateDialog):
            def exec(self) -> int:
                self.rows[3].widget.setText("Created in dialog")
                self.create_button.click()
                return self.result()

        self.page.create_request_provider = None
        with patch("src.gui.tracker_workspace.TrackerItemCreateDialog", _FillingDialog):
            self.page.create_item_button.click()
            self._app.processEvents()

        create_call = next(call for call in EditableWorkspaceClient.calls if call[0] == "create")
        self.assertEqual(create_call[2], {"name": "Created in dialog"})
        self.assertEqual(self.page.detail_panel.detail_title.text(), "Created in dialog")

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
        root = self.page.hierarchy_panel.item_tree.topLevelItem(0)
        self.assertEqual(root.childCount(), 1)
        self.assertEqual(root.child(0).text(1), "1002")
        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#1002")
        self.assertEqual(self.page.detail_panel.detail_title.text(), "Created child")
        self.assertIn("생성했습니다", self.page.workspace_status_label.text())
        self.assertEqual(self.activities[-1].operation.value, "tracker_create")
        self.assertEqual(self.activities[-1].item_id, 1002)


class TrackerWorkspaceBulkUpdateTest(unittest.TestCase):
    """일괄 수정은 실제 작업 스레드로 돌려 실행 중 상태와 끝난 뒤 정리를 확인한다."""

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
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.run_store = BulkUpdateRunStore(Path(temp_dir.name) / "bulk_runs.json")
        query_service = TrackerQueryService(client_factory=EditableWorkspaceClient)
        self.requests: list[dict] = []
        self.activities = []
        self.alerts: list[tuple[str, str]] = []

        def bulk_request(schema, **kwargs):
            self.requests.append(kwargs)
            summary = next(field for field in schema.fields if field.field_id == 3)
            return BulkUpdateRequest(
                changes=(BulkFieldChange(summary, "Bulk summary"),),
                atomic=True,
                chunk_size=1,
            )

        self.page = TrackerWorkspacePage(
            settings_provider=lambda: self.settings,
            service=query_service,
            editor_service=TrackerItemEditorService(
                client_factory=EditableWorkspaceClient,
                query_service=query_service,
            ),
            bulk_update_service=TrackerBulkUpdateService(client_factory=EditableWorkspaceClient),
            bulk_run_store=self.run_store,
            bulk_request_provider=bulk_request,
            activity_recorder=self.activities.append,
            error_notifier=lambda title, message: self.alerts.append((title, message)),
            synchronous=True,
        )
        self.page.show()
        self.page.activate()
        self._app.processEvents()
        # 가짜 클라이언트에는 Baseline 목록이 없어 활성화 때 알림이 하나 나온다.
        self.alerts.clear()
        self.panel = self.page.search_panel

    def tearDown(self) -> None:
        if EditableWorkspaceClient.bulk_gate is not None:
            EditableWorkspaceClient.bulk_gate.set()
        worker = self.panel._bulk_worker
        if worker is not None:
            worker.wait(5000)
        self._app.processEvents()
        self.page.close()
        self._app.processEvents()

    def _wait_for_bulk_run(self, worker) -> None:
        self.assertTrue(worker.wait(5000))
        # 작업 스레드의 완료 신호는 이벤트 루프로 넘어온다.
        self._app.processEvents()
        self._app.processEvents()

    def _bulk_calls(self) -> list[tuple]:
        return [call for call in EditableWorkspaceClient.calls if call[0] == "bulk"]

    def test_running_bulk_update_cannot_be_closed_or_started_twice(self) -> None:
        gate = threading.Event()
        EditableWorkspaceClient.bulk_gate = gate
        self.panel._prepare_bulk_update((1001,))
        first = self.panel._bulk_worker
        progress = self.panel._bulk_progress_dialog
        self.assertIsNotNone(first)
        self.assertTrue(progress.isVisible())
        # 첫 청크 요청이 서버에 가 있는 동안 닫으려 한다.
        self.assertTrue(EditableWorkspaceClient.bulk_entered.wait(5))

        # Esc나 창 닫기로는 진행 창이 닫히지 않는다. 남은 청크 중단 요청으로만 받는다.
        QTest.keyClick(progress, Qt.Key.Key_Escape)
        progress.close()
        self._app.processEvents()
        self.assertTrue(progress.isVisible())
        self.assertFalse(progress.cancel_button.isEnabled())

        # 끝나기 전에 다시 실행해도 두 번째 작업을 만들지 않는다.
        self.panel._prepare_bulk_update((1001,))
        self.assertIs(self.panel._bulk_worker, first)
        self.assertIn("진행 중", self.page.workspace_status_label.text())
        self.assertEqual(len(self.requests), 1)

        gate.set()
        self._wait_for_bulk_run(first)

        self.assertIsNone(self.panel._bulk_worker)
        self.assertFalse(progress.isVisible())
        self.assertEqual(len(self._bulk_calls()), 1)

    def test_editor_and_bulk_schema_loads_do_not_cancel_each_other(self) -> None:
        """수정 탭과 일괄 수정이 같은 요청 이름을 쓰면 늦게 시작한 쪽이 앞 결과를 버린다."""
        tree = self.page.hierarchy_panel.item_tree
        tree.setCurrentItem(tree.topLevelItem(0))
        self._app.processEvents()
        detail = self.page.detail_panel.current_detail
        editor = self.page.detail_panel.editor_panel
        self.assertNotIn(3, editor.rows)
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]

        self.page.detail_panel._load_editor_schema(detail)
        self.panel._prepare_bulk_update((1001,))
        tasks[0].finish()
        tasks[1].finish()

        self.assertIn(3, editor.rows)
        self.assertEqual(len(self.requests), 1)
        self._wait_for_bulk_run(self.panel._bulk_worker)

    def test_bulk_update_uses_the_real_field_dialog(self) -> None:
        from PySide6.QtWidgets import QPushButton

        class _FillingDialog(TrackerBulkUpdateDialog):
            def exec(self) -> int:
                row = self.rows[3]
                row.include_item.setCheckState(Qt.CheckState.Checked)
                row.input_widget.setText("Bulk from dialog")
                buttons = {button.text(): button for button in self.findChildren(QPushButton)}
                buttons["일괄 수정 실행"].click()
                return self.result()

        self.panel.bulk_request_provider = None
        with patch("src.gui.tracker_search_panel.TrackerBulkUpdateDialog", _FillingDialog):
            self.panel._prepare_bulk_update((1001,))
        self._wait_for_bulk_run(self.panel._bulk_worker)

        bulk_calls = self._bulk_calls()
        self.assertEqual(len(bulk_calls), 1)
        self.assertEqual(bulk_calls[0][1], (1001,))
        self.assertIn("성공 1건", self.page.workspace_status_label.text())

    def test_bulk_run_stopped_by_error_keeps_record_and_reports(self) -> None:
        EditableWorkspaceClient.bulk_error_on_call = 2

        self.panel._prepare_bulk_update((1001, 1002, 1003))
        self._wait_for_bulk_run(self.panel._bulk_worker)

        record = self.run_store.load()[0]
        self.assertEqual(record.successful_item_ids, (1001,))
        self.assertEqual(record.retry_item_ids, (1002, 1003))
        self.assertEqual(self.activities[-1].result.value, "partial")
        self.assertTrue(self.activities[-1].details["stopped_by_error"])
        self.assertEqual(len(self.alerts), 1)
        self.assertIn("중단", self.alerts[0][1])
        self.assertIn("성공 1건", self.page.workspace_status_label.text())
        self.assertIsNone(self.panel._bulk_progress_dialog)

    def test_retry_from_another_server_or_older_record_is_refused(self) -> None:
        def stored(run_id: str, server_key: str) -> None:
            self.run_store.append(
                BulkUpdateRunResult(
                    run_id=run_id,
                    tracker_id=20,
                    target_item_ids=(1001,),
                    field_ids=(3,),
                    clear_field_ids=(),
                    chunks=(),
                    atomic=True,
                    chunk_size=1,
                    unattempted_item_ids=(1001,),
                    server_key=server_key,
                )
            )

        stored("other-account", bulk_run_server_key(replace(self.settings, username="other")))
        stored("older-record", "")
        stored("same-server", bulk_run_server_key(self.settings))

        for run_id in ("other-account", "older-record"):
            with self.subTest(run_id=run_id):
                self.page.open_bulk_retry(run_id)
                self.assertEqual(self.requests, [])
                self.assertIn("재시도할 수 없습니다", self.page.workspace_status_label.text())

        EditableWorkspaceClient.bulk_gate = threading.Event()
        self.page.open_bulk_retry("same-server")
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
