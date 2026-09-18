from __future__ import annotations

import os
import unittest
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.api_monitor import API_MONITOR
from src.diagnostics import DIAGNOSTICS
from src.diagnostics import DiagnosticSource
from src.gui.worker import BackgroundTask
from src.gui.worker import UploadWorker


class _UploadPipeline:
    def run_batch_upload(self, *_args, **_kwargs):
        handle = API_MONITOR.start_request(
            request_kind="create_item",
            method="POST",
            path="/v3/trackers/1/items",
        )
        API_MONITOR.finish_request(handle, status_code=200, outcome="success")
        return {"success_df": None, "failed_df": None, "unresolved_df": None}


class _CancelAfterServerSuccessPipeline:
    def __init__(self) -> None:
        self.cancel = lambda: None

    def run_batch_upload(self, *_args, **kwargs):
        self.cancel()
        kwargs["event_callback"](
            {
                "type": "row_success",
                "phase": "insert",
                "row_id": 1,
                "upload_name": "REQ-001",
                "item_id": 1001,
            }
        )
        return {
            "created_map_by_file": {"sample.xlsx": {1: 1001}},
            "success_df": None,
            "failed_df": None,
            "unresolved_df": None,
        }


class WorkerDiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        DIAGNOSTICS.clear()
        API_MONITOR.reset(enabled=True, slow_threshold_ms=1_000)

    def tearDown(self) -> None:
        DIAGNOSTICS.clear()
        API_MONITOR.reset(enabled=False, slow_threshold_ms=1_000)

    def test_background_task_correlates_api_events_with_diagnostic_operation(self) -> None:
        def load_excel_preview():
            handle = API_MONITOR.start_request(
                request_kind="read_workbook",
                method="GET",
                path="/local/workbook",
            )
            API_MONITOR.finish_request(handle, status_code=200, outcome="success")
            return "ok"

        task = BackgroundTask(load_excel_preview)
        task.start()
        task.wait()

        events = DIAGNOSTICS.snapshot().events
        api_events = API_MONITOR.snapshot().events
        self.assertEqual(len(events), 2)
        self.assertEqual({event.source for event in events}, {DiagnosticSource.EXCEL})
        self.assertEqual(len({event.operation_id for event in events}), 1)
        self.assertEqual(api_events[0].operation_id, events[0].operation_id)

    def test_upload_worker_correlates_upload_api_events(self) -> None:
        task = UploadWorker(
            _UploadPipeline(),
            settings=SimpleNamespace(),
            file_state={},
            mapping_context=SimpleNamespace(),
            dry_run=False,
            continue_on_error=True,
            output_dir=".",
        )
        task.start()
        task.wait()

        events = DIAGNOSTICS.snapshot().events
        api_events = API_MONITOR.snapshot().events
        self.assertEqual(len(events), 2)
        self.assertEqual({event.source for event in events}, {DiagnosticSource.UPLOAD})
        self.assertEqual(api_events[0].operation_id, events[0].operation_id)

    def test_cancel_after_server_success_preserves_checkpoint_result(self) -> None:
        pipeline = _CancelAfterServerSuccessPipeline()
        task = UploadWorker(
            pipeline,
            settings=SimpleNamespace(),
            file_state={},
            mapping_context=SimpleNamespace(),
            dry_run=False,
            continue_on_error=True,
            output_dir=".",
        )
        finished = []
        failed = []
        task.upload_finished.connect(finished.append)
        task.upload_failed.connect(failed.append)
        pipeline.cancel = task.request_cancel

        task.start()
        task.wait()
        self._app.processEvents()

        self.assertEqual(failed, [])
        self.assertEqual(len(finished), 1)
        self.assertTrue(finished[0]["cancelled"])
        self.assertEqual(
            finished[0]["created_map_by_file"]["sample.xlsx"],
            {1: 1001},
        )
        self.assertEqual(
            DIAGNOSTICS.snapshot().events[-1].details["outcome"],
            "cancelled",
        )

    def test_cancel_releases_paused_worker(self) -> None:
        task = UploadWorker(
            _UploadPipeline(),
            settings=SimpleNamespace(),
            file_state={},
            mapping_context=SimpleNamespace(),
            dry_run=False,
            continue_on_error=True,
            output_dir=".",
        )

        task.request_pause()
        task.request_cancel()

        self.assertFalse(task._pause_requested)
        self.assertTrue(task._cancel_requested)


if __name__ == "__main__":
    unittest.main()
