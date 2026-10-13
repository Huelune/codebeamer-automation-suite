from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from src.hierarchy_processor import UPLOAD_RECORD_KEY_COLUMN
from src.hierarchy_processor import HierarchyProcessor
from src.mapping_service import MappingService
from src.models import PayloadStatus
from src.models import UploadStatus
from src.wizard import CodebeamerUploadWizard


# 연결 오류 문구에는 서버 이름과 경로가 들어 있다. 화면·기록에 남지 않아야 한다.
SECRET_CONNECTION_ERROR = (
    "HTTPSConnectionPool(host='secret-host.example.invalid', port=443): Max retries exceeded "
    "with url: /cb/api/v3/trackers/2/items (Caused by NewConnectionError('refused'))"
)

class StaticSchemaClient:
    def __init__(self, schema: list[dict[str, Any]]) -> None:
        self.schema = schema
        self.create_item_calls: list[dict[str, Any]] = []

    def get_tracker_schema(self, tracker_id: int):
        del tracker_id
        return self.schema

    def create_item(self, tracker_id: int, payload: dict[str, Any], parent_item_id: int | None = None):
        self.create_item_calls.append({
            "tracker_id": tracker_id,
            "payload": payload,
            "parent_item_id": parent_item_id,
        })
        return {"id": 1000 + len(self.create_item_calls)}


class FailingSchemaClient(StaticSchemaClient):
    def create_item(self, tracker_id: int, payload: dict[str, Any], parent_item_id: int | None = None):
        del tracker_id, payload, parent_item_id

        class UploadError(Exception):
            def __init__(self) -> None:
                self.response = type(
                    "Response",
                    (),
                    {
                        "status_code": 400,
                        "json": staticmethod(lambda: {
                            "message": "Invalid tracker item",
                            "details": {"field": "Status"},
                        }),
                    },
                )()
                super().__init__("upload failed")

        raise UploadError()


class UpsertSchemaClient(StaticSchemaClient):
    def __init__(self, schema: list[dict[str, Any]]) -> None:
        super().__init__(schema)
        self.get_item_calls: list[int] = []
        self.update_item_calls: list[tuple[int, dict[str, Any]]] = []
        # 여기 없는 item 은 테스트가 고르는 트래커(2) 소속이다.
        self.item_tracker_ids: dict[int, int] = {}

    def get_item(self, item_id: int) -> dict[str, Any]:
        self.get_item_calls.append(int(item_id))
        return {
            "id": int(item_id),
            "name": f"기존-{item_id}",
            "tracker": {"id": self.item_tracker_ids.get(int(item_id), 2), "type": "TrackerReference"},
            "customFields": [],
        }

    def update_item(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self.update_item_calls.append((int(item_id), dict(payload)))
        return {"id": int(item_id)}


class FailingCreateUpsertClient(UpsertSchemaClient):
    def create_item(
        self,
        tracker_id: int,
        payload: dict[str, Any],
        parent_item_id: int | None = None,
    ):
        del tracker_id, payload, parent_item_id
        raise RuntimeError("create failed")


class UnreachableCreateClient(UpsertSchemaClient):
    """생성 요청이 서버에 닿지 않는다. 예외 문구에 서버 이름과 경로가 들어 있다."""

    def create_item(
        self,
        tracker_id: int,
        payload: dict[str, Any],
        parent_item_id: int | None = None,
    ):
        del tracker_id, payload, parent_item_id
        raise ConnectionError(SECRET_CONNECTION_ERROR)


class CancelAfterCreateUpsertClient(UpsertSchemaClient):
    def __init__(self, schema: list[dict[str, Any]]) -> None:
        super().__init__(schema)
        self.cancelled = False

    def create_item(
        self,
        tracker_id: int,
        payload: dict[str, Any],
        parent_item_id: int | None = None,
    ):
        result = super().create_item(tracker_id, payload, parent_item_id)
        self.cancelled = True
        return result


class CountingWizard(CodebeamerUploadWizard):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.payload_build_calls = 0

    def _build_row_payload(self, row: pd.Series, row_id: int, *, operation: str = "create") -> dict[str, Any]:
        self.payload_build_calls += 1
        return super()._build_row_payload(row, row_id, operation=operation)


class HierarchyProcessorSplitTest(unittest.TestCase):
    def test_processor_builds_hierarchy_from_raw_dataframe(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        raw_df = pd.DataFrame([
            {"요약": "Parent", "담당": "11", "_excel_row": 2, "_summary_indent": 0},
            {"요약": None, "담당": "12", "_excel_row": 3, "_summary_indent": 0},
            {"요약": "Child", "담당": "13", "_excel_row": 4, "_summary_indent": 1},
        ])

        merged_df = processor.merge_multiline_records(raw_df, list_cols=["담당"])
        hierarchy_df = processor.add_hierarchy_by_indent(merged_df)
        upload_df = processor.build_upload_df(hierarchy_df, list_cols=["담당"])

        self.assertEqual(list(merged_df["요약"]), ["Parent", "Child"])
        self.assertEqual(merged_df.iloc[0]["담당"], ["11", "12"])
        self.assertTrue(pd.isna(hierarchy_df.iloc[0]["parent_row_id"]))
        self.assertEqual(int(hierarchy_df.iloc[1]["parent_row_id"]), 0)
        self.assertEqual(list(upload_df["upload_name"]), ["Parent", "Child"])

    def test_row_with_a_different_id_starts_a_new_record_without_summary(self) -> None:
        """수정용 파일은 id가 레코드 경계다. Summary가 비어도 앞 아이템에 합치지 않는다."""
        processor = HierarchyProcessor(summary_col="요약")
        raw_df = pd.DataFrame([
            {"id": 101, "요약": "REQ-101", "비고": "a", "_excel_row": 2, "_summary_indent": 0},
            {"id": 102, "요약": None, "비고": "b", "_excel_row": 3, "_summary_indent": 0},
            {"id": None, "요약": None, "비고": "c", "_excel_row": 4, "_summary_indent": 0},
            {"id": 102, "요약": None, "비고": "d", "_excel_row": 5, "_summary_indent": 0},
        ], dtype=object)

        merged_df = processor.merge_multiline_records(raw_df, list_cols=["비고"])

        self.assertEqual(merged_df["id"].tolist(), [101, 102])
        self.assertEqual(merged_df["요약"].tolist(), ["REQ-101", None])
        # id가 비었거나 같은 행은 그 아이템의 이어지는 행이다.
        self.assertEqual(merged_df.iloc[1]["비고"], ["b", "c", "d"])

    def test_rows_before_the_first_summary_are_kept_for_validation(self) -> None:
        """첫 Summary 앞의 행을 조용히 버리지 않는다. 검증에서 이름이나 id가 없다고 알린다."""
        processor = HierarchyProcessor(summary_col="요약")
        raw_df = pd.DataFrame([
            {"요약": None, "비고": "orphan", "_excel_row": 2, "_summary_indent": 0},
            {"요약": "REQ-1", "비고": "kept", "_excel_row": 3, "_summary_indent": 0},
        ], dtype=object)

        merged_df = processor.merge_multiline_records(raw_df, list_cols=[])

        self.assertEqual(merged_df["비고"].tolist(), ["orphan", "kept"])
        self.assertEqual(merged_df["요약"].tolist(), [None, "REQ-1"])

    def test_processor_keeps_integer_like_values_without_decimal_suffix_after_merge(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        raw_df = pd.DataFrame([
            {"요약": "REQ-001", "코드": 12, "_excel_row": 2, "_summary_indent": 0},
            {"요약": "REQ-002", "코드": None, "_excel_row": 3, "_summary_indent": 0},
        ], dtype=object)

        merged_df = processor.merge_multiline_records(raw_df, list_cols=[])
        hierarchy_df = processor.add_hierarchy_by_indent(merged_df)
        upload_df = processor.build_upload_df(hierarchy_df, list_cols=[])

        self.assertEqual(merged_df["코드"].tolist(), [12, None])
        self.assertIsInstance(merged_df.iloc[0]["코드"], int)
        self.assertEqual(upload_df["코드"].tolist(), [12, None])
        self.assertIsInstance(upload_df.iloc[0]["코드"], int)

    def test_record_key_groups_repeated_rows_and_preserves_table_cell_alignment(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        raw_df = pd.DataFrame(
            [
                {
                    UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                    "요약": "Requirement 1",
                    "Priority": "High",
                    "Steps.Action": "Open",
                    "Steps.Expected": None,
                    "_excel_row": 2,
                    "_summary_indent": 0,
                },
                {
                    UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                    "요약": "Requirement 1",
                    "Priority": "High",
                    "Steps.Action": None,
                    "Steps.Expected": "Opened",
                    "_excel_row": 3,
                    "_summary_indent": 0,
                },
                {
                    UPLOAD_RECORD_KEY_COLUMN: "REQ-2",
                    "요약": "Requirement 2",
                    "Priority": "Low",
                    "Steps.Action": "Close",
                    "Steps.Expected": "Closed",
                    "_excel_row": 4,
                    "_summary_indent": 0,
                },
            ],
            dtype=object,
        )

        merged = processor.merge_multiline_records(
            raw_df,
            list_cols=["Steps.Action", "Steps.Expected"],
        )

        self.assertEqual(merged["요약"].tolist(), ["Requirement 1", "Requirement 2"])
        self.assertEqual(merged["_upload_record_key"].tolist(), ["REQ-1", "REQ-2"])
        self.assertEqual(merged.iloc[0]["Steps.Action"], ["Open", None])
        self.assertEqual(merged.iloc[0]["Steps.Expected"], [None, "Opened"])
        self.assertEqual(merged.iloc[0]["Priority"], "High")

    def test_record_key_rejects_conflicting_scalar_fields(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        raw_df = pd.DataFrame(
            [
                {
                    UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                    "요약": "Requirement",
                    "Priority": "High",
                    "_excel_row": 2,
                    "_summary_indent": 0,
                },
                {
                    UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                    "요약": "Requirement",
                    "Priority": "Low",
                    "_excel_row": 3,
                    "_summary_indent": 0,
                },
            ],
            dtype=object,
        )

        with self.assertRaisesRegex(ValueError, "일반 필드 'Priority' 값이 행마다 다릅니다"):
            processor.merge_multiline_records(raw_df, list_cols=[])

        blank_then_value = pd.DataFrame(
            [
                {
                    UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                    "요약": "Requirement",
                    "Priority": None,
                    "_excel_row": 2,
                    "_summary_indent": 0,
                },
                {
                    UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                    "요약": "Requirement",
                    "Priority": "High",
                    "_excel_row": 3,
                    "_summary_indent": 0,
                },
            ],
            dtype=object,
        )
        with self.assertRaisesRegex(ValueError, "일반 필드 'Priority' 값이 행마다 다릅니다"):
            processor.merge_multiline_records(blank_then_value, list_cols=[])

    def test_record_key_requires_nonblank_contiguous_values(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        missing = pd.DataFrame(
            [
                {UPLOAD_RECORD_KEY_COLUMN: "REQ-1", "요약": "One", "_excel_row": 2, "_summary_indent": 0},
                {UPLOAD_RECORD_KEY_COLUMN: None, "요약": "Two", "_excel_row": 3, "_summary_indent": 0},
            ],
            dtype=object,
        )
        with self.assertRaisesRegex(ValueError, "값이 비어 있습니다"):
            processor.merge_multiline_records(missing, list_cols=[])

        noncontiguous = pd.DataFrame(
            [
                {UPLOAD_RECORD_KEY_COLUMN: "REQ-1", "요약": "One", "_excel_row": 2, "_summary_indent": 0},
                {UPLOAD_RECORD_KEY_COLUMN: "REQ-2", "요약": "Two", "_excel_row": 3, "_summary_indent": 0},
                {UPLOAD_RECORD_KEY_COLUMN: "REQ-1", "요약": "One", "_excel_row": 4, "_summary_indent": 0},
            ],
            dtype=object,
        )
        with self.assertRaisesRegex(ValueError, "연속해서 배치"):
            processor.merge_multiline_records(noncontiguous, list_cols=[])

    def test_record_key_rows_become_aligned_table_field_payload_rows(self) -> None:
        schema = [
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 1000,
                "name": "Steps",
                "type": "TableField",
                "valueModel": "TableFieldValue",
                "columns": [
                    {
                        "id": 1001,
                        "name": "Action",
                        "type": "WikiTextField",
                        "valueModel": "WikiTextFieldValue",
                    },
                    {
                        "id": 1002,
                        "name": "Expected",
                        "type": "WikiTextField",
                        "valueModel": "WikiTextFieldValue",
                    },
                ],
            },
        ]
        wizard = CodebeamerUploadWizard(
            client=StaticSchemaClient(schema),
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=MappingService(),
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.load_raw_dataframe(
            pd.DataFrame(
                [
                    {
                        UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                        "요약": "Requirement",
                        "Steps.Action": "Open",
                        "Steps.Expected": None,
                        "_excel_row": 2,
                        "_summary_indent": 0,
                    },
                    {
                        UPLOAD_RECORD_KEY_COLUMN: "REQ-1",
                        "요약": "Requirement",
                        "Steps.Action": None,
                        "Steps.Expected": "Opened",
                        "_excel_row": 3,
                        "_summary_indent": 0,
                    },
                ],
                dtype=object,
            ),
            list_cols=["Steps.Action", "Steps.Expected"],
        )
        selected_mapping = {
            "요약": "Summary",
            "Steps.Action": "Steps",
            "Steps.Expected": "Steps",
        }
        wizard.load_schema_and_compare(selected_mapping)
        wizard.process_option_mapping(selected_mapping)

        payload = wizard.preview_payload(0)

        self.assertEqual(payload["name"], "Requirement")
        self.assertEqual(len(payload["customFields"]), 1)
        table_rows = payload["customFields"][0]["values"]
        self.assertEqual(len(table_rows), 2)
        self.assertEqual(table_rows[0][0]["name"], "Action")
        self.assertEqual(table_rows[0][0]["value"], "Open")
        self.assertEqual(table_rows[1][0]["name"], "Expected")
        self.assertEqual(table_rows[1][0]["value"], "Opened")


class PayloadCacheWizardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = [
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            }
        ]
        self.client = StaticSchemaClient(self.schema)
        self.processor = HierarchyProcessor(summary_col="요약")
        self.mapper = MappingService()

    def _build_wizard(self) -> CountingWizard:
        wizard = CountingWizard(
            client=self.client,
            processor=self.processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "REQ-001", "_excel_row": 2, "_summary_indent": 0},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})
        return wizard

    def test_preview_and_upload_reuse_same_payload_cache(self) -> None:
        wizard = self._build_wizard()

        preview_payload = wizard.preview_payload(0)
        self.assertEqual(preview_payload["name"], "REQ-001")
        self.assertEqual(wizard.payload_build_calls, 1)

        upload_result = wizard.upload(dry_run=False)

        self.assertEqual(wizard.payload_build_calls, 1)
        self.assertEqual(len(self.client.create_item_calls), 1)
        self.assertEqual(self.client.create_item_calls[0]["payload"], preview_payload)
        self.assertEqual(upload_result["success_df"].iloc[0]["status"], UploadStatus.SUCCESS.value)

    def test_build_payloads_and_save_state_persist_payload_cache(self) -> None:
        wizard = self._build_wizard()

        payload_df = wizard.build_payloads()

        self.assertEqual(list(payload_df["payload_status"]), [PayloadStatus.READY.value])
        self.assertIn("payload_json", payload_df.columns)

        with tempfile.TemporaryDirectory() as tmp_dir:
            wizard.save_state(tmp_dir)

            payload_csv = Path(tmp_dir) / "payload_df.csv"
            payload_jsonl = Path(tmp_dir) / "payload_preview.jsonl"

            self.assertTrue(payload_csv.exists())
            self.assertTrue(payload_jsonl.exists())

            payload_df_saved = pd.read_csv(payload_csv)
            self.assertEqual(payload_df_saved.iloc[0]["payload_status"], PayloadStatus.READY.value)

            first_line = payload_jsonl.read_text(encoding="utf-8").strip().splitlines()[0]
            saved_payload = json.loads(first_line)
            self.assertEqual(saved_payload["payload_status"], PayloadStatus.READY.value)
            self.assertEqual(saved_payload["payload_json"]["name"], "REQ-001")

    def test_preview_payload_keeps_integer_like_text_values_without_decimal_suffix(self) -> None:
        schema = [
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 2,
                "name": "코드",
                "type": "TextField",
                "valueModel": "TextFieldValue",
            },
        ]
        client = StaticSchemaClient(schema)
        wizard = CountingWizard(
            client=client,
            processor=self.processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "REQ-001", "코드": 12, "_excel_row": 2, "_summary_indent": 0},
            {"요약": "REQ-002", "코드": None, "_excel_row": 3, "_summary_indent": 0},
        ], dtype=object)
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary", "코드": "코드"})
        wizard.process_option_mapping({"요약": "Summary", "코드": "코드"})

        preview_payload = wizard.preview_payload(0)

        self.assertEqual(wizard.state.upload_df.iloc[0]["코드"], 12)
        self.assertEqual(preview_payload["customFields"][0]["value"], "12")

    def test_upload_creates_file_root_before_existing_hierarchy(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        wizard = CountingWizard(
            client=self.client,
            processor=processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "Parent", "_excel_row": 2, "_summary_indent": 0},
            {"요약": "Child", "_excel_row": 3, "_summary_indent": 1},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})
        upload_result = wizard.upload(dry_run=False, root_item_name="sample")

        self.assertEqual(list(wizard.state.upload_df["upload_name"]), ["Parent", "Child"])
        self.assertEqual(
            [call["payload"]["name"] for call in self.client.create_item_calls],
            ["sample", "Parent", "Child"],
        )
        self.assertEqual(
            [call["parent_item_id"] for call in self.client.create_item_calls],
            [None, 1001, 1002],
        )
        self.assertEqual(len(upload_result["success_df"]), 3)

    def test_upload_root_field_values_can_override_root_name(self) -> None:
        wizard = self._build_wizard()

        upload_result = wizard.upload(
            dry_run=False,
            root_item_name="sample",
            root_field_values={"Summary": "ROOT-CUSTOM"},
        )

        self.assertEqual(self.client.create_item_calls[0]["payload"]["name"], "ROOT-CUSTOM")
        self.assertEqual(upload_result["success_df"].iloc[0]["upload_name"], "sample")

    def test_upsert_can_create_child_under_existing_parent_id_anchor(self) -> None:
        client = UpsertSchemaClient(self.schema)
        wizard = CountingWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = "upsert"
        raw_df = pd.DataFrame([
            {"id": 101, "요약": "Parent", "_excel_row": 2, "_summary_indent": 0},
            {"id": None, "요약": "Child", "_excel_row": 3, "_summary_indent": 1},
        ], dtype=object)
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        payload_df = wizard.build_payloads(fetch_existing_items=False)

        self.assertEqual(payload_df["_operation"].tolist(), ["update", "create"])
        self.assertEqual(payload_df["payload_status"].tolist(), [PayloadStatus.READY.value, PayloadStatus.READY.value])

        upload_result = wizard.upsert_items(dry_run=False)

        self.assertEqual(client.get_item_calls, [101])
        self.assertEqual(client.update_item_calls[0][0], 101)
        self.assertEqual(client.create_item_calls[0]["payload"]["name"], "Child")
        self.assertEqual(client.create_item_calls[0]["parent_item_id"], 101)
        self.assertEqual(len(upload_result["success_df"]), 2)

    def test_upsert_allows_new_hierarchy_without_existing_parent_id_anchor(self) -> None:
        wizard = CountingWizard(
            client=self.client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = "upsert"
        raw_df = pd.DataFrame([
            {"id": None, "요약": "Parent", "_excel_row": 2, "_summary_indent": 0},
            {"id": None, "요약": "Child", "_excel_row": 3, "_summary_indent": 1},
        ], dtype=object)
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        payload_df = wizard.build_payloads(fetch_existing_items=False)

        self.assertEqual(payload_df["_operation"].tolist(), ["create", "create"])
        self.assertEqual(payload_df["payload_status"].tolist(), [PayloadStatus.READY.value, PayloadStatus.READY.value])

        upload_result = wizard.upsert_items(dry_run=False)

        self.assertEqual(
            [call["payload"]["name"] for call in self.client.create_item_calls],
            ["Parent", "Child"],
        )
        self.assertEqual(
            [call["parent_item_id"] for call in self.client.create_item_calls],
            [None, 1001],
        )
        self.assertEqual(len(upload_result["success_df"]), 2)

    def test_failure_reason_hides_server_address(self) -> None:
        """결과 표·로그·실패 보고서에 남는 실패 사유에 서버 주소가 들어가지 않는다."""
        wizard = CountingWizard(
            client=UnreachableCreateClient(self.schema),
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.load_raw_dataframe(
            pd.DataFrame([{"요약": "REQ-1", "_excel_row": 2, "_summary_indent": 0}]),
            list_cols=[],
        )
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        result = wizard.upload(dry_run=False)

        error = str(result["failed_df"].iloc[0]["error"])
        self.assertNotIn("secret-host", error)
        self.assertNotIn("/cb/api", error)
        self.assertIn("Max retries exceeded", error)

    def test_create_stop_on_error_counts_failed_row_only_as_failed(self) -> None:
        """오류 시 중단하면 실패 행은 실패로만, 실행하지 않은 행은 미해결로 남긴다."""
        client = FailingCreateUpsertClient(self.schema)
        wizard = CountingWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "REQ-1", "_excel_row": 2, "_summary_indent": 0},
            {"요약": "REQ-2", "_excel_row": 3, "_summary_indent": 0},
            {"요약": "REQ-3", "_excel_row": 4, "_summary_indent": 0},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        result = wizard.upload(dry_run=False, continue_on_error=False)

        self.assertEqual(result["failed_df"]["_row_id"].tolist(), [0])
        unresolved = result["unresolved_df"]
        self.assertEqual(unresolved["_row_id"].tolist(), [1, 2])
        # 단계별 집계와 결과 화면이 쓰는 열을 채운다.
        self.assertEqual(set(unresolved["phase"]), set(result["failed_df"]["phase"]))
        self.assertTrue(unresolved["error"].str.contains("중단").all())

    def test_upsert_insert_stop_keeps_unattempted_update_for_retry(self) -> None:
        client = FailingCreateUpsertClient(self.schema)
        wizard = CountingWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = "upsert"
        raw_df = pd.DataFrame(
            [
                {
                    "id": None,
                    "요약": "Create Row",
                    "_excel_row": 2,
                    "_summary_indent": 0,
                },
                {
                    "id": 101,
                    "요약": "Update Row",
                    "_excel_row": 3,
                    "_summary_indent": 0,
                },
            ],
            dtype=object,
        )
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        result = wizard.upsert_items(
            dry_run=False,
            continue_on_error=False,
        )

        skipped_update = result["unresolved_df"].loc[
            result["unresolved_df"]["phase"].eq("update")
        ]
        self.assertEqual(skipped_update["_row_id"].tolist(), [1])
        self.assertIn("아직 수정 요청을 실행하지 않았습니다", skipped_update.iloc[0]["error"])
        self.assertFalse(result["update_payload_prepared"])
        self.assertEqual(client.get_item_calls, [])
        self.assertEqual(client.update_item_calls, [])

    def test_upsert_cancel_after_insert_does_not_prepare_updates(self) -> None:
        client = CancelAfterCreateUpsertClient(self.schema)
        wizard = CountingWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = "upsert"
        raw_df = pd.DataFrame(
            [
                {
                    "id": None,
                    "요약": "Create Row",
                    "_excel_row": 2,
                    "_summary_indent": 0,
                },
                {
                    "id": 101,
                    "요약": "Update Row",
                    "_excel_row": 3,
                    "_summary_indent": 0,
                },
            ],
            dtype=object,
        )
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        result = wizard.upsert_items(
            dry_run=False,
            continue_on_error=True,
            cancel_requested=lambda: client.cancelled,
        )

        skipped_update = result["unresolved_df"].loc[
            result["unresolved_df"]["phase"].eq("update")
        ]
        self.assertEqual(skipped_update["_row_id"].tolist(), [1])
        self.assertIn("사용자 중단 요청", skipped_update.iloc[0]["error"])
        self.assertFalse(result["update_payload_prepared"])
        self.assertEqual(client.get_item_calls, [])
        self.assertEqual(client.update_item_calls, [])

    TABLE_SCHEMA = [
        {
            "id": 1,
            "name": "Summary",
            "type": "TextField",
            "trackerItemField": "name",
            "valueModel": "TextFieldValue",
        },
        {
            "id": 1000,
            "name": "Steps",
            "type": "TableField",
            "valueModel": "TableFieldValue",
            "columns": [
                {"id": 1001, "name": "Action", "type": "WikiTextField", "valueModel": "WikiTextFieldValue"},
                {"id": 1002, "name": "Expected", "type": "WikiTextField", "valueModel": "WikiTextFieldValue"},
            ],
        },
    ]

    def _table_wizard(
        self,
        client,
        selected_mapping: dict[str, str],
        *,
        upload_mode: str = "update",
        selected_mapping_modes=None,
    ) -> CodebeamerUploadWizard:
        wizard = CodebeamerUploadWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=MappingService(),
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = upload_mode
        wizard.load_raw_dataframe(
            pd.DataFrame(
                [
                    {
                        "id": 101,
                        "요약": "REQ-101",
                        "Steps.Action": "a1",
                        "Steps.Expected": "e1",
                        "_excel_row": 2,
                        "_summary_indent": 0,
                    }
                ],
                dtype=object,
            ),
            list_cols=[column for column in selected_mapping if column.startswith("Steps.")],
        )
        wizard.load_schema_and_compare(selected_mapping)
        wizard.process_option_mapping(selected_mapping, selected_mapping_modes=selected_mapping_modes)
        return wizard

    @staticmethod
    def _sent_table(client) -> list:
        payload = client.update_item_calls[0][1]
        return [field for field in payload.get("customFields", []) if field.get("fieldId") == 1000]

    def test_unmapped_table_columns_are_not_sent_on_update(self) -> None:
        """매핑에서 뺀 표 열을 보내면 기존 표가 잘린다. 매핑하지 않은 표는 그대로 둔다."""
        client = UpsertSchemaClient(self.TABLE_SCHEMA)
        wizard = self._table_wizard(client, {"요약": "Summary"})

        wizard.update_items(dry_run=False)

        self.assertEqual(self._sent_table(client), [])

    def test_table_columns_outside_update_scope_are_not_sent(self) -> None:
        client = UpsertSchemaClient(self.TABLE_SCHEMA)
        selected_mapping = {"요약": "Summary", "Steps.Action": "Steps", "Steps.Expected": "Steps"}
        wizard = self._table_wizard(
            client,
            selected_mapping,
            upload_mode="upsert",
            selected_mapping_modes={
                "요약": {"create": True, "update": True},
                "Steps.Action": {"create": True, "update": False},
                "Steps.Expected": {"create": True, "update": False},
            },
        )

        wizard.upsert_items(dry_run=False)

        self.assertEqual(self._sent_table(client), [])

    def test_update_with_only_some_table_columns_is_blocked(self) -> None:
        """수정은 표 전체를 바꾸므로 일부 열만 보내면 나머지 열이 비워질 수 있다."""
        client = UpsertSchemaClient(self.TABLE_SCHEMA)
        wizard = self._table_wizard(client, {"요약": "Summary", "Steps.Action": "Steps"})

        payload_df = wizard.build_payloads(fetch_existing_items=False)

        self.assertEqual(payload_df["payload_status"].tolist(), [PayloadStatus.FAILED.value])
        self.assertIn("TABLE_FIELD_PARTIAL_UPDATE", str(payload_df.iloc[0]["payload_error"]))
        self.assertIn("Expected", str(payload_df.iloc[0]["payload_error"]))

    def test_update_with_all_table_columns_replaces_the_table(self) -> None:
        client = UpsertSchemaClient(self.TABLE_SCHEMA)
        selected_mapping = {"요약": "Summary", "Steps.Action": "Steps", "Steps.Expected": "Steps"}
        wizard = self._table_wizard(client, selected_mapping)

        wizard.update_items(dry_run=False)

        table = self._sent_table(client)
        self.assertEqual(len(table), 1)
        self.assertEqual(
            [[cell["value"] for cell in row] for row in table[0]["values"]],
            [["a1", "e1"]],
        )

    NOTE_SCHEMA = [
        {
            "id": 1,
            "name": "Summary",
            "type": "TextField",
            "trackerItemField": "name",
            "valueModel": "TextFieldValue",
        },
        {"id": 3, "name": "비고", "type": "TextField", "valueModel": "TextFieldValue"},
    ]

    def _note_wizard(self, client, rows: list[dict], *, upload_mode: str) -> CodebeamerUploadWizard:
        wizard = CodebeamerUploadWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=MappingService(),
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = upload_mode
        wizard.load_raw_dataframe(pd.DataFrame(rows, dtype=object), list_cols=[])
        mapping = {"요약": "Summary", "비고": "비고"}
        wizard.load_schema_and_compare(mapping)
        wizard.process_option_mapping(mapping)
        return wizard

    def test_update_row_without_summary_goes_to_its_own_item_and_keeps_its_name(self) -> None:
        client = UpsertSchemaClient(self.NOTE_SCHEMA)
        wizard = self._note_wizard(
            client,
            [
                {"id": 101, "요약": "REQ-101", "비고": "v1", "_excel_row": 2, "_summary_indent": 0},
                {"id": 102, "요약": None, "비고": "v2", "_excel_row": 3, "_summary_indent": 0},
            ],
            upload_mode="update",
        )

        wizard.update_items(dry_run=False)

        payloads = dict(client.update_item_calls)
        self.assertEqual(sorted(payloads), [101, 102])
        notes = {
            item_id: next(field["value"] for field in payload["customFields"] if field["fieldId"] == 3)
            for item_id, payload in payloads.items()
        }
        self.assertEqual(notes, {101: "v1", 102: "v2"})
        # Summary를 비운 행은 이름을 바꾸지 않는다.
        self.assertEqual(payloads[102]["name"], "기존-102")

    def test_new_item_without_summary_is_blocked(self) -> None:
        client = UpsertSchemaClient(self.NOTE_SCHEMA)
        wizard = self._note_wizard(
            client,
            [
                {"요약": None, "비고": "orphan", "_excel_row": 2, "_summary_indent": 0},
                {"요약": "REQ-1", "비고": "kept", "_excel_row": 3, "_summary_indent": 0},
            ],
            upload_mode="create",
        )

        payload_df = wizard.build_payloads(fetch_existing_items=False)

        self.assertEqual(
            payload_df["payload_status"].tolist(),
            [PayloadStatus.FAILED.value, PayloadStatus.READY.value],
        )
        self.assertIn("ITEM_NAME_MISSING", str(payload_df.iloc[0]["payload_error"]))

    def test_update_skips_item_that_belongs_to_another_tracker(self) -> None:
        """다른 트래커에서 내보낸 id 열로 그 트래커 아이템을 덮어쓰지 않는다."""
        client = UpsertSchemaClient(self.schema)
        client.item_tracker_ids = {101: 99}
        wizard = CountingWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = "update"
        raw_df = pd.DataFrame([
            {"id": 101, "요약": "Other tracker", "_excel_row": 2, "_summary_indent": 0},
            {"id": 102, "요약": "Same tracker", "_excel_row": 3, "_summary_indent": 0},
        ], dtype=object)
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        result = wizard.update_items(dry_run=False)

        self.assertEqual([call[0] for call in client.update_item_calls], [102])
        failed = result["failed_df"]
        self.assertEqual(failed["_row_id"].tolist(), [0])
        self.assertIn("UPDATE_ITEM_TRACKER_MISMATCH", str(failed.iloc[0]["error"]))

    def test_upsert_blocks_update_row_with_new_ancestor(self) -> None:
        client = UpsertSchemaClient(self.schema)
        wizard = CountingWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = "upsert"
        raw_df = pd.DataFrame([
            {"id": None, "요약": "Parent", "_excel_row": 2, "_summary_indent": 0},
            {"id": 101, "요약": "Child", "_excel_row": 3, "_summary_indent": 1},
        ], dtype=object)
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        payload_df = wizard.build_payloads(fetch_existing_items=False)

        self.assertEqual(payload_df["_operation"].tolist(), ["create", "update"])
        self.assertEqual(payload_df["payload_status"].tolist(), [PayloadStatus.READY.value, PayloadStatus.FAILED.value])
        self.assertIn("UPSERT_UPDATE_WITH_NEW_ANCESTOR", str(payload_df.iloc[1]["payload_error"]))

    def test_upsert_can_split_create_and_update_field_usage(self) -> None:
        schema = [
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 2,
                "name": "설명",
                "type": "TextField",
                "trackerItemField": "description",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 3,
                "name": "비고",
                "type": "TextField",
                "valueModel": "TextFieldValue",
            },
        ]
        client = UpsertSchemaClient(schema)
        wizard = CountingWizard(
            client=client,
            processor=HierarchyProcessor(summary_col="요약"),
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        wizard.state.upload_mode = "upsert"
        raw_df = pd.DataFrame(
            [
                {
                    "id": None,
                    "요약": "Create Row",
                    "생성설명": "생성 설명",
                    "수정비고": "생성 비고",
                    "_excel_row": 2,
                    "_summary_indent": 0,
                },
                {
                    "id": 101,
                    "요약": "Update Row",
                    "생성설명": "수정 설명",
                    "수정비고": "수정 비고",
                    "_excel_row": 3,
                    "_summary_indent": 0,
                },
            ],
            dtype=object,
        )
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({
            "요약": "Summary",
            "생성설명": "설명",
            "수정비고": "비고",
        })
        wizard.process_option_mapping(
            {
                "요약": "Summary",
                "생성설명": "설명",
                "수정비고": "비고",
            },
            selected_mapping_modes={
                "요약": {"create": True, "update": True},
                "생성설명": {"create": True, "update": False},
                "수정비고": {"create": False, "update": True},
            },
        )

        upload_result = wizard.upsert_items(dry_run=False)

        self.assertEqual(client.create_item_calls[0]["payload"]["name"], "Create Row")
        self.assertEqual(client.create_item_calls[0]["payload"]["description"], "생성 설명")
        self.assertNotIn("customFields", client.create_item_calls[0]["payload"])
        self.assertEqual(client.update_item_calls[0][0], 101)
        self.assertEqual(client.update_item_calls[0][1]["name"], "Update Row")
        self.assertEqual(client.update_item_calls[0][1].get("description"), None)
        self.assertEqual(
            client.update_item_calls[0][1]["customFields"],
            [{"fieldId": 3, "name": "비고", "type": "TextFieldValue", "value": "수정 비고"}],
        )
        self.assertEqual(len(upload_result["success_df"]), 2)

    def test_upload_root_field_values_can_apply_static_option_field(self) -> None:
        schema = [
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 2,
                "name": "Status",
                "type": "OptionChoiceField",
                "trackerItemField": "status",
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
                "options": [
                    {"id": 201, "name": "Open", "type": "ChoiceOptionReference"},
                    {"id": 202, "name": "Review", "type": "ChoiceOptionReference"},
                ],
            },
        ]
        client = StaticSchemaClient(schema)
        wizard = CountingWizard(
            client=client,
            processor=self.processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "REQ-001", "_excel_row": 2, "_summary_indent": 0},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        wizard.upload(
            dry_run=False,
            root_item_name="sample",
            root_field_values={"Status": "Open"},
        )

        self.assertEqual(client.create_item_calls[0]["payload"]["status"]["name"], "Open")

    def test_upload_can_create_multiple_top_level_parent_specs_before_rows(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        wizard = CountingWizard(
            client=self.client,
            processor=processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "Parent A", "_excel_row": 2, "_summary_indent": 0},
            {"요약": "Child A", "_excel_row": 3, "_summary_indent": 1},
            {"요약": "Parent B", "_excel_row": 4, "_summary_indent": 0},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        upload_result = wizard.upload(
            dry_run=False,
            top_level_parent_specs=[
                {"key": "ems", "name": "EMS", "field_values": {}, "row_ids": [0]},
                {"key": "vcu", "name": "VCU", "field_values": {}, "row_ids": [2]},
            ],
        )

        self.assertEqual(
            [call["payload"]["name"] for call in self.client.create_item_calls],
            ["EMS", "VCU", "Parent A", "Child A", "Parent B"],
        )
        self.assertEqual(
            [call["parent_item_id"] for call in self.client.create_item_calls],
            [None, None, 1001, 1003, 1002],
        )
        self.assertEqual(len(upload_result["success_df"]), 5)

    def test_upload_retry_reuses_successful_top_level_parent_without_duplicate_creation(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        wizard = CountingWizard(
            client=self.client,
            processor=processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "Parent A", "_excel_row": 2, "_summary_indent": 0},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})
        parent_specs = [
            {"key": "ems", "name": "EMS", "field_values": {}, "row_ids": [0]},
        ]

        first_result = wizard.upload(
            dry_run=False,
            top_level_parent_specs=parent_specs,
            include_row_ids=set(),
        )
        parent_id = first_result["parent_item_ids_by_key"]["ems"]
        self.client.create_item_calls.clear()

        retry_result = wizard.upload(
            dry_run=False,
            top_level_parent_specs=parent_specs,
            include_row_ids={0},
            existing_parent_item_ids_by_key={"ems": parent_id},
        )

        self.assertEqual(len(self.client.create_item_calls), 1)
        self.assertEqual(self.client.create_item_calls[0]["payload"]["name"], "Parent A")
        self.assertEqual(self.client.create_item_calls[0]["parent_item_id"], parent_id)
        self.assertEqual(retry_result["parent_item_ids_by_key"], {"ems": parent_id})

    def test_upload_can_create_nested_top_level_parent_specs_before_rows(self) -> None:
        processor = HierarchyProcessor(summary_col="요약")
        wizard = CountingWizard(
            client=self.client,
            processor=processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "Parent A", "_excel_row": 2, "_summary_indent": 0},
            {"요약": "Child A", "_excel_row": 3, "_summary_indent": 1},
            {"요약": "Parent B", "_excel_row": 4, "_summary_indent": 0},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        upload_result = wizard.upload(
            dry_run=False,
            top_level_parent_specs=[
                {"key": "file-root", "name": "ABC_REQ-001", "field_values": {}, "row_ids": []},
                {
                    "key": "ems",
                    "name": "EMS",
                    "field_values": {},
                    "row_ids": [0],
                    "parent_key": "file-root",
                },
                {
                    "key": "vcu",
                    "name": "VCU",
                    "field_values": {},
                    "row_ids": [2],
                    "parent_key": "file-root",
                },
            ],
        )

        self.assertEqual(
            [call["payload"]["name"] for call in self.client.create_item_calls],
            ["ABC_REQ-001", "EMS", "VCU", "Parent A", "Child A", "Parent B"],
        )
        self.assertEqual(
            [call["parent_item_id"] for call in self.client.create_item_calls],
            [None, 1001, 1001, 1002, 1004, 1003],
        )
        self.assertEqual(len(upload_result["success_df"]), 6)

    def test_upload_failure_persists_response_json(self) -> None:
        wizard = CountingWizard(
            client=FailingSchemaClient(self.schema),
            processor=self.processor,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(2)
        raw_df = pd.DataFrame([
            {"요약": "REQ-001", "_excel_row": 2, "_summary_indent": 0},
        ])
        wizard.load_raw_dataframe(raw_df, list_cols=[])
        wizard.load_schema_and_compare({"요약": "Summary"})
        wizard.process_option_mapping({"요약": "Summary"})

        upload_result = wizard.upload(dry_run=False, continue_on_error=True)

        failed_df = upload_result["failed_df"]
        self.assertEqual(failed_df.iloc[0]["error_status_code"], 400)
        self.assertEqual(
            failed_df.iloc[0]["error_response_json"],
            {"message": "Invalid tracker item", "details": {"field": "Status"}},
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            wizard.save_state(tmp_dir)

            failed_csv = Path(tmp_dir) / "failed_df.csv"
            failed_jsonl = Path(tmp_dir) / "failed_responses.jsonl"

            self.assertTrue(failed_csv.exists())
            self.assertTrue(failed_jsonl.exists())

            failed_df_saved = pd.read_csv(failed_csv)
            self.assertEqual(int(failed_df_saved.iloc[0]["error_status_code"]), 400)
            self.assertIn("Invalid tracker item", failed_df_saved.iloc[0]["error_response_json"])

            first_line = failed_jsonl.read_text(encoding="utf-8").strip().splitlines()[0]
            saved_failure = json.loads(first_line)
            self.assertEqual(saved_failure["error_status_code"], 400)
            self.assertEqual(saved_failure["error_response_json"]["message"], "Invalid tracker item")


if __name__ == "__main__":
    unittest.main()
