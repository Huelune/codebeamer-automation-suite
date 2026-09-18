from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.gui.batch_upload import BatchUploadService
from src.gui.upload_context import FailedUploadRetryContext
from src.gui.upload_context import FailedUploadRetryJob
from src.models import PayloadStatus
from src.upload_policy import UPLOAD_MODE_CREATE
from src.upload_policy import UPLOAD_MODE_UPDATE
from src.upload_policy import UPLOAD_MODE_UPSERT
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


class RetryWizardStub:
    def __init__(self, payload_df: pd.DataFrame, *, fail_upload: bool = False) -> None:
        self.state = SimpleNamespace(payload_df=payload_df)
        self.upload_calls: list[set[int]] = []
        self.update_calls: list[set[int]] = []
        self.update_fetch_existing_calls: list[bool] = []
        self.fail_upload = fail_upload

    @staticmethod
    def _success_df(row_ids: set[int], phase: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "_row_id": row_id,
                    "upload_name": f"REQ-{row_id}",
                    "phase": phase,
                    "status": "success",
                }
                for row_id in sorted(row_ids)
            ]
        )

    def upload(self, *, include_row_ids, existing_row_item_ids, existing_parent_item_ids_by_key, **_kwargs):
        row_ids = set(include_row_ids)
        self.upload_calls.append(row_ids)
        created_map = dict(existing_row_item_ids)
        if not self.fail_upload:
            created_map.update({row_id: 2_000 + row_id for row_id in row_ids})
        return {
            "created_map": created_map,
            "parent_item_ids_by_key": dict(existing_parent_item_ids_by_key),
            "success_df": (
                pd.DataFrame()
                if self.fail_upload
                else self._success_df(row_ids, "insert")
            ),
            "failed_df": (
                pd.DataFrame(
                    [
                        {
                            "_row_id": row_id,
                            "upload_name": f"REQ-{row_id}",
                            "phase": "insert",
                            "status": "failed",
                            "error": "temporary",
                        }
                        for row_id in sorted(row_ids)
                    ]
                )
                if self.fail_upload
                else pd.DataFrame()
            ),
            "unresolved_df": pd.DataFrame(),
        }

    def update_items(self, *, include_row_ids, fetch_existing_items, **_kwargs):
        row_ids = set(include_row_ids)
        self.update_calls.append(row_ids)
        self.update_fetch_existing_calls.append(bool(fetch_existing_items))
        return {
            "created_map": {},
            "success_df": self._success_df(row_ids, "update"),
            "failed_df": pd.DataFrame(),
            "unresolved_df": pd.DataFrame(),
        }


class InitialBatchWizardStub:
    def __init__(
        self,
        row_ids: set[int],
        *,
        fail_upload: bool = False,
        fail_save: bool = False,
    ) -> None:
        self.state = SimpleNamespace(
            payload_df=pd.DataFrame(
                [
                    {
                        "_row_id": row_id,
                        "upload_name": f"REQ-{row_id}",
                        "parent_row_id": None,
                        "payload_status": PayloadStatus.READY.value,
                    }
                    for row_id in sorted(row_ids)
                ]
            ),
            upload_mode=UPLOAD_MODE_CREATE,
        )
        self.row_ids = set(row_ids)
        self.fail_upload = fail_upload
        self.fail_save = fail_save
        self.upload_call_count = 0
        self.save_call_count = 0

    def upload(self, **_kwargs):
        self.upload_call_count += 1
        if self.fail_upload:
            failed_row_id = min(self.row_ids)
            return {
                "created_map": {},
                "parent_item_ids_by_key": {},
                "success_df": pd.DataFrame(),
                "failed_df": pd.DataFrame(
                    [
                        {
                            "_row_id": failed_row_id,
                            "upload_name": f"REQ-{failed_row_id}",
                            "phase": "insert",
                            "status": "failed",
                            "error": "temporary",
                        }
                    ]
                ),
                "unresolved_df": pd.DataFrame(),
            }
        return {
            "created_map": {row_id: 3_000 + row_id for row_id in self.row_ids},
            "parent_item_ids_by_key": {},
            "success_df": RetryWizardStub._success_df(self.row_ids, "insert"),
            "failed_df": pd.DataFrame(),
            "unresolved_df": pd.DataFrame(),
        }

    def save_state(self, _output_dir: str) -> None:
        self.save_call_count += 1
        if self.fail_save:
            raise OSError("disk full at /private/path")


class BatchUploadServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = BatchUploadService(
            mapper=Mock(),
            create_wizard=Mock(),
            root_items=Mock(),
            batch_validation=Mock(),
        )

    def test_phase_ready_counts_separate_upsert_create_and_update(self) -> None:
        wizard = SimpleNamespace(
            state=SimpleNamespace(
                upload_mode=UPLOAD_MODE_UPSERT,
                payload_df=pd.DataFrame(
                    [
                        {
                            "payload_status": PayloadStatus.READY.value,
                            "_operation": "create",
                        },
                        {
                            "payload_status": PayloadStatus.READY.value,
                            "_operation": "update",
                        },
                    ]
                ),
            )
        )

        insert_count, update_count = self.service._phase_ready_counts(
            wizard,
            root_item_specs=[Mock()],
        )

        self.assertEqual(insert_count, 2)
        self.assertEqual(update_count, 1)

    def test_batch_output_dir_is_stable_per_file_index(self) -> None:
        output_dir = self.service._batch_output_dir(
            "output",
            "folder/Requirements.xlsx",
            3,
        )

        self.assertTrue(output_dir.endswith("003_Requirements"))

    def test_failed_retry_limits_include_row_ids_for_create_update_and_upsert(self) -> None:
        cases = (
            (UPLOAD_MODE_CREATE, "", {1, 2}, set()),
            (UPLOAD_MODE_UPDATE, "update", set(), {1, 2}),
            (UPLOAD_MODE_UPSERT, "mixed", {1}, {2}),
        )
        for upload_mode, operation_mode, expected_create, expected_update in cases:
            with self.subTest(upload_mode=upload_mode):
                operations = (
                    ["", "", ""]
                    if operation_mode == ""
                    else (
                        ["update", "update", "update"] if operation_mode == "update" else ["create", "create", "update"]
                    )
                )
                payload_df = pd.DataFrame(
                    [
                        {
                            "_row_id": row_id,
                            "payload_status": PayloadStatus.READY.value,
                            "_operation": operations[row_id],
                        }
                        for row_id in range(3)
                    ]
                )
                wizard = RetryWizardStub(payload_df)
                retry_job = FailedUploadRetryJob(
                    file_path="/tmp/sample.xlsx",
                    file_label="sample.xlsx",
                    root_item_specs=[],
                    output_dir="/tmp/output",
                    wizard=wizard,
                    upload_mode=upload_mode,
                    retry_row_ids={1, 2},
                    retry_root_keys=set(),
                    created_row_item_ids={0: 1_000},
                    created_parent_item_ids_by_key={},
                )
                context = FailedUploadRetryContext(
                    jobs=[retry_job],
                    success_df=pd.DataFrame(
                        [
                            {
                                "source_file": "sample.xlsx",
                                "source_file_path": "/tmp/sample.xlsx",
                                "_row_id": 0,
                                "upload_name": "REQ-0",
                                "phase": "insert" if upload_mode != UPLOAD_MODE_UPDATE else "update",
                                "status": "success",
                            }
                        ]
                    ),
                    failed_df=pd.DataFrame(
                        [
                            {
                                "source_file": "sample.xlsx",
                                "source_file_path": "/tmp/sample.xlsx",
                                "_row_id": 1,
                                "upload_name": "REQ-1",
                                "phase": "update" if upload_mode == UPLOAD_MODE_UPDATE else "insert",
                                "status": "failed",
                            }
                        ]
                    ),
                    unresolved_df=pd.DataFrame(
                        [
                            {
                                "source_file": "sample.xlsx",
                                "source_file_path": "/tmp/sample.xlsx",
                                "_row_id": 2,
                                "upload_name": "REQ-2",
                                "phase": "update"
                                if upload_mode in {UPLOAD_MODE_UPDATE, UPLOAD_MODE_UPSERT}
                                else "insert",
                                "status": "unresolved_parent",
                            }
                        ]
                    ),
                    created_map_by_file={"/tmp/sample.xlsx": {0: 1_000}},
                    dry_run=False,
                )

                result = self.service.run_failed_upload_retry(
                    context,
                    continue_on_error=True,
                )

                self.assertEqual(wizard.upload_calls, [expected_create] if expected_create else [])
                self.assertEqual(wizard.update_calls, [expected_update] if expected_update else [])
                attempted_ids = set().union(*wizard.upload_calls, *wizard.update_calls)
                self.assertEqual(attempted_ids, {1, 2})
                self.assertNotIn(0, attempted_ids)
                self.assertEqual(set(result["success_df"]["_row_id"].tolist()), {0, 1, 2})
                self.assertTrue(result["failed_df"].empty)
                self.assertTrue(result["unresolved_df"].empty)
                self.assertIsNone(result["retry_context"])

    def test_upsert_retry_keeps_skipped_update_rows_when_insert_stops_on_error(self) -> None:
        payload_df = pd.DataFrame(
            [
                {
                    "_row_id": 1,
                    "payload_status": PayloadStatus.READY.value,
                    "_operation": "create",
                },
                {
                    "_row_id": 2,
                    "payload_status": PayloadStatus.READY.value,
                    "_operation": "update",
                },
            ]
        )
        wizard = RetryWizardStub(payload_df, fail_upload=True)
        retry_job = FailedUploadRetryJob(
            file_path="/tmp/sample.xlsx",
            file_label="sample.xlsx",
            root_item_specs=[],
            output_dir="/tmp/output",
            wizard=wizard,
            upload_mode=UPLOAD_MODE_UPSERT,
            retry_row_ids={1, 2},
            retry_root_keys=set(),
            created_row_item_ids={},
            created_parent_item_ids_by_key={},
        )
        failed_df = pd.DataFrame(
            [
                {
                    "source_file": "sample.xlsx",
                    "source_file_path": "/tmp/sample.xlsx",
                    "_row_id": row_id,
                    "upload_name": f"REQ-{row_id}",
                    "phase": phase,
                    "status": "failed",
                }
                for row_id, phase in ((1, "insert"), (2, "update"))
            ]
        )
        context = FailedUploadRetryContext(
            jobs=[retry_job],
            success_df=pd.DataFrame(),
            failed_df=failed_df,
            unresolved_df=pd.DataFrame(),
            created_map_by_file={"/tmp/sample.xlsx": {}},
            dry_run=False,
        )

        result = self.service.run_failed_upload_retry(
            context,
            continue_on_error=False,
        )

        self.assertEqual(wizard.upload_calls, [{1}])
        self.assertEqual(wizard.update_calls, [])
        self.assertEqual(result["retry_attempted_count"], 1)
        self.assertEqual(set(result["failed_df"]["_row_id"].tolist()), {1, 2})
        self.assertIsNotNone(result["retry_context"])
        self.assertEqual(result["retry_context"].jobs[0].retry_row_ids, {1, 2})

    def test_retry_fetches_existing_item_when_update_payload_was_not_prepared(self) -> None:
        payload_df = pd.DataFrame(
            [
                {
                    "_row_id": 2,
                    "payload_status": PayloadStatus.READY.value,
                    "_operation": "update",
                }
            ]
        )
        wizard = RetryWizardStub(payload_df)
        retry_job = FailedUploadRetryJob(
            file_path="/tmp/sample.xlsx",
            file_label="sample.xlsx",
            root_item_specs=[],
            output_dir="/tmp/output",
            wizard=wizard,
            upload_mode=UPLOAD_MODE_UPSERT,
            retry_row_ids={2},
            retry_root_keys=set(),
            created_row_item_ids={},
            created_parent_item_ids_by_key={},
            update_payload_prepared=False,
        )
        context = FailedUploadRetryContext(
            jobs=[retry_job],
            success_df=pd.DataFrame(),
            failed_df=pd.DataFrame(),
            unresolved_df=pd.DataFrame(
                [
                    {
                        "source_file": "sample.xlsx",
                        "source_file_path": "/tmp/sample.xlsx",
                        "_row_id": 2,
                        "upload_name": "REQ-2",
                        "phase": "update",
                        "status": "unresolved",
                    }
                ]
            ),
            created_map_by_file={"/tmp/sample.xlsx": {}},
            dry_run=False,
        )

        result = self.service.run_failed_upload_retry(
            context,
            continue_on_error=True,
        )

        self.assertEqual(wizard.update_fetch_existing_calls, [True])
        self.assertIsNone(result["retry_context"])

    def test_retry_cancel_before_next_request_preserves_retry_context(self) -> None:
        payload_df = pd.DataFrame(
            [
                {
                    "_row_id": 1,
                    "payload_status": PayloadStatus.READY.value,
                    "_operation": "create",
                }
            ]
        )
        wizard = RetryWizardStub(payload_df)
        retry_job = FailedUploadRetryJob(
            file_path="/tmp/sample.xlsx",
            file_label="sample.xlsx",
            root_item_specs=[],
            output_dir="/tmp/output",
            wizard=wizard,
            upload_mode=UPLOAD_MODE_CREATE,
            retry_row_ids={1},
            retry_root_keys=set(),
            created_row_item_ids={},
            created_parent_item_ids_by_key={},
        )
        unresolved_df = pd.DataFrame(
            [
                {
                    "source_file": "sample.xlsx",
                    "source_file_path": "/tmp/sample.xlsx",
                    "_row_id": 1,
                    "upload_name": "REQ-1",
                    "phase": "insert",
                    "status": "unresolved",
                }
            ]
        )
        context = FailedUploadRetryContext(
            jobs=[retry_job],
            success_df=pd.DataFrame(),
            failed_df=pd.DataFrame(),
            unresolved_df=unresolved_df,
            created_map_by_file={"/tmp/sample.xlsx": {}},
            dry_run=False,
        )

        result = self.service.run_failed_upload_retry(
            context,
            continue_on_error=True,
            cancel_requested=lambda: True,
        )

        self.assertTrue(result["cancelled"])
        self.assertEqual(result["retry_attempted_count"], 0)
        self.assertEqual(wizard.upload_calls, [])
        self.assertIsNotNone(result["retry_context"])
        self.assertEqual(result["retry_context"].jobs[0].retry_row_ids, {1})

    @staticmethod
    def _batch_mapping_context(file_paths: list[str]):
        return SimpleNamespace(
            file_paths=file_paths,
            selected_mapping={"Summary": "Summary"},
            upload_mode=UPLOAD_MODE_CREATE,
            batch_duplicate_update_item_ids=set(),
        )

    def test_stop_on_error_keeps_later_prepared_file_for_retry(self) -> None:
        first = InitialBatchWizardStub({0}, fail_upload=True)
        second = InitialBatchWizardStub({0})
        wizards = {
            "/tmp/first.xlsx": first,
            "/tmp/second.xlsx": second,
        }
        self.service._prepare_wizard_for_file = Mock(
            side_effect=lambda _settings, _context, *, file_path, **_kwargs: wizards[file_path]
        )
        self.service.root_items.build_root_item_payload_specs.return_value = []

        result = self.service.run_batch_upload(
            SimpleNamespace(offline_mode=False),
            {"sheet_name": "Main", "header_row": 1, "summary_column": "Summary"},
            self._batch_mapping_context(list(wizards)),
            dry_run=False,
            continue_on_error=False,
            output_dir="/tmp/output",
        )

        self.assertEqual(first.upload_call_count, 1)
        self.assertEqual(second.upload_call_count, 0)
        skipped = result["unresolved_df"].loc[
            result["unresolved_df"]["source_file_path"].eq("/tmp/second.xlsx")
        ]
        self.assertEqual(skipped["_row_id"].tolist(), [0])
        self.assertIn("실행하지 않았습니다", skipped.iloc[0]["error"])
        self.assertIsNotNone(result["retry_context"])
        self.assertEqual(
            {job.file_path for job in result["retry_context"].jobs},
            {"/tmp/first.xlsx", "/tmp/second.xlsx"},
        )

    def test_prepare_failure_keeps_later_successfully_prepared_file_for_retry(self) -> None:
        first = InitialBatchWizardStub({0})
        third = InitialBatchWizardStub({0})

        def prepare(_settings, _context, *, file_path, **_kwargs):
            if file_path == "/tmp/second.xlsx":
                raise ValueError("invalid workbook")
            return first if file_path == "/tmp/first.xlsx" else third

        self.service._prepare_wizard_for_file = Mock(side_effect=prepare)
        self.service.root_items.build_root_item_payload_specs.return_value = []
        file_paths = [
            "/tmp/first.xlsx",
            "/tmp/second.xlsx",
            "/tmp/third.xlsx",
        ]

        result = self.service.run_batch_upload(
            SimpleNamespace(offline_mode=False),
            {"sheet_name": "Main", "header_row": 1, "summary_column": "Summary"},
            self._batch_mapping_context(file_paths),
            dry_run=False,
            continue_on_error=False,
            output_dir="/tmp/output",
        )

        self.assertEqual(first.upload_call_count, 1)
        self.assertEqual(third.upload_call_count, 0)
        self.assertEqual(
            result["failed_df"]["source_file_path"].tolist(),
            ["/tmp/second.xlsx"],
        )
        self.assertEqual(
            result["unresolved_df"]["source_file_path"].tolist(),
            ["/tmp/third.xlsx"],
        )
        self.assertIsNotNone(result["retry_context"])
        self.assertEqual(
            [job.file_path for job in result["retry_context"].jobs],
            ["/tmp/third.xlsx"],
        )

    def test_save_state_failure_keeps_server_result_and_safe_warning(self) -> None:
        wizard = InitialBatchWizardStub({0}, fail_save=True)
        self.service._prepare_wizard_for_file = Mock(return_value=wizard)
        self.service.root_items.build_root_item_payload_specs.return_value = []
        events = []

        result = self.service.run_batch_upload(
            SimpleNamespace(offline_mode=False),
            {"sheet_name": "Main", "header_row": 1, "summary_column": "Summary"},
            self._batch_mapping_context(["/tmp/sample.xlsx"]),
            dry_run=False,
            continue_on_error=True,
            output_dir="/tmp/output",
            event_callback=events.append,
        )

        self.assertEqual(wizard.save_call_count, 1)
        self.assertEqual(result["created_map_by_file"]["/tmp/sample.xlsx"], {0: 3000})
        self.assertEqual(result["success_df"]["_row_id"].tolist(), [0])
        self.assertTrue(result["failed_df"].empty)
        self.assertEqual(len(result["state_save_warnings"]), 1)
        self.assertNotIn("/private/path", result["state_save_warnings"][0])
        self.assertTrue(
            any(
                event.get("type") == "log" and "결과와 세션 재시도 정보는 유지" in event.get("message", "")
                for event in events
            )
        )


if __name__ == "__main__":
    unittest.main()
