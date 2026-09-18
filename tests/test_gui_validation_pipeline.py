from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from src.gui.service_core import GuiExcelService
from src.gui.settings_store import GuiSettings
from src.gui.upload_service import GuiUploadPipelineService
from src.models import MappingStatus
from src.models import PayloadStatus
from tests.gui_service_fixtures import FakeClient
from tests.gui_service_fixtures import FakeExcelReader


class GuiValidationPipelineServiceTest(unittest.TestCase):
    def test_build_user_issue_df_keeps_only_user_visible_issues(self) -> None:
        service = GuiUploadPipelineService(client_factory=FakeClient)
        comparison_df = pd.DataFrame([
            {"df_column": "_row_id", "selected_schema_field": "", "status": MappingStatus.UNMAPPED.value},
            {"df_column": "담당자", "selected_schema_field": "", "status": MappingStatus.UNMAPPED.value},
        ])
        option_check_df = pd.DataFrame([
            {"df_column": "담당자", "schema_field": "담당자", "_row_id": 1, "raw_value": "홍길동", "status": "USER_NOT_FOUND"},
            {"df_column": "상태", "schema_field": "Status", "status": "PRECONSTRUCTION_REQUIRED"},
        ])
        payload_df = pd.DataFrame([
            {
                "_row_id": 1,
                "upload_name": "REQ-001",
                "payload_status": PayloadStatus.FAILED.value,
                "payload_error": "payload error",
            },
        ])
        row_context_df = pd.DataFrame([
            {
                "_row_id": 1,
                "_excel_row": 2,
                "upload_name": "REQ-001",
                "담당자": "홍길동",
            }
        ])

        visible_comparison_df = service._gui_visible_comparison_df(comparison_df)
        issue_df = service._build_user_issue_df(
            visible_comparison_df,
            option_check_df,
            payload_df,
            row_context_df=row_context_df,
        )

        self.assertFalse((issue_df["column"] == "_row_id").any())
        self.assertTrue((issue_df["column"] == "담당자").any())
        self.assertTrue(issue_df["message"].str.contains("사용자를 찾지 못했습니다").any())
        self.assertFalse(issue_df["message"].str.contains("내부 변환").any())
        self.assertTrue(issue_df["message"].str.contains("payload error").any())
        self.assertTrue((issue_df["row_label"] == "Excel 2행").any())
        self.assertTrue((issue_df["item_name"] == "REQ-001").any())
        self.assertTrue((issue_df["raw_value"] == "홍길동").any())
        self.assertTrue(issue_df["action"].str.contains("다시 검증").any())

    def test_build_user_issue_df_formats_structured_payload_errors(self) -> None:
        service = GuiUploadPipelineService(client_factory=FakeClient)
        issue_df = service._build_user_issue_df(
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame([
                {
                    "_row_id": 1,
                    "upload_name": "REQ-001",
                    "payload_status": PayloadStatus.FAILED.value,
                    "payload_error": "[LOOKUP_REQUIRED] field='담당자' df_column='담당자' _row_id=1 lookup_target='user'",
                }
            ]),
            row_context_df=pd.DataFrame([
                {
                    "_row_id": 1,
                    "_excel_row": 2,
                    "upload_name": "REQ-001",
                    "담당자": "홍길동",
                }
            ]),
        )

        self.assertEqual(issue_df.iloc[0]["column"], "담당자")
        self.assertEqual(issue_df.iloc[0]["field"], "담당자")
        self.assertIn("필요한 값을 찾지 못해 업로드용 데이터를 만들 수 없습니다.", issue_df.iloc[0]["message"])
        self.assertEqual(issue_df.iloc[0]["row_label"], "Excel 2행")
        self.assertEqual(issue_df.iloc[0]["raw_value"], "홍길동")
        self.assertIn("다시 검증하세요", issue_df.iloc[0]["action"])

    def test_validate_mapping_does_not_block_when_payload_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Main"
            sheet.append(["Summary", "담당자", "비고"])
            sheet.append(["REQ-001", "홍길동", "메모"])
            workbook.save(path)
            workbook.close()

            service = GuiUploadPipelineService(
                client_factory=FakeClient,
                excel_service=GuiExcelService(reader_cls=FakeExcelReader),
                reader_cls=FakeExcelReader,
            )
            settings = GuiSettings(
                base_url="https://example.com/cb",
                username="user",
                password="secret",
                default_project_id="10",
                default_tracker_id="1000",
                excel_header_row=1,
                summary_column="Summary",
                excel_sheet_name="Main",
            )
            mapping_context = service.prepare_mapping_context(
                settings,
                {
                    "file_path": str(path),
                    "sheet_name": "Main",
                    "header_row": 1,
                    "summary_column": "Summary",
                },
            )

            validation_context = service.validate_mapping(
                mapping_context,
                {"Summary": "Summary"},
                {"Status": "Open"},
            )

            self.assertFalse(validation_context.has_blocking_issues)
            self.assertTrue(validation_context.issue_df.empty)
            self.assertEqual(len(validation_context.payload_df.index), 1)
            self.assertEqual(validation_context.summary_stats["total_rows"], 1)
            self.assertEqual(validation_context.summary_stats["ready_rows"], 1)
            self.assertEqual(validation_context.summary_stats["error_rows"], 0)
            self.assertEqual(
                list(mapping_context.wizard.state.payload_df["payload_status"]),
                [PayloadStatus.READY.value],
            )
            self.assertEqual(
                mapping_context.wizard.state.payload_df.iloc[0]["payload_json"]["status"]["name"],
                "Open",
            )
