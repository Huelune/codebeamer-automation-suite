from __future__ import annotations

import atexit
import contextlib
import json
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from src.excel_processor import ExcelHierarchyProcessor
from src.mapping_service import MappingService
from src.models import OptionCheckStatus
from src.models import UserLookupStatus
from src.wizard import CodebeamerUploadWizard


try:
    import xlwings._xlmac as _xlmac

    for cleanup_name in ("cleanup", "clean_up"):
        cleanup_func = getattr(_xlmac, cleanup_name, None)
        if cleanup_func is not None:
            with contextlib.suppress(Exception):
                atexit.unregister(cleanup_func)
except Exception:
    pass


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class CsvFixtureProcessor(ExcelHierarchyProcessor):
    """CSV 파일을 읽어 Excel 원본과 비슷한 DataFrame으로 바꿔주는 테스트용 처리기다."""

    def read_excel(self, file_path: str, sheet_name: str | int = 0, visible: bool = False) -> pd.DataFrame:
        """CSV를 읽고 `_excel_row`, `_summary_indent`가 포함된 raw DataFrame을 만든다."""
        del sheet_name
        del visible

        raw_df = pd.read_csv(file_path, keep_default_na=False).replace({"": None})
        if "들여쓰기" not in raw_df.columns:
            raise ValueError("CSV fixture must include '들여쓰기' column.")

        raw_df["_excel_row"] = range(self.header_row + 1, self.header_row + 1 + len(raw_df))
        raw_df["_summary_indent"] = raw_df["들여쓰기"].fillna(0).astype(int)
        return raw_df.drop(columns=["들여쓰기"])


class OfflineSchemaClient:
    """schema fixture만 제공하고 서버 lookup은 일부러 막는 오프라인 테스트용 client다."""

    def __init__(self, schema: dict[str, Any]) -> None:
        """테스트에서 재사용할 schema fixture를 저장한다."""
        self.schema = schema

    def get_tracker_schema(self, tracker_id: int) -> dict[str, Any]:
        """선택된 tracker ID와 무관하게 준비된 schema fixture를 돌려준다."""
        del tracker_id
        return self.schema

    def get_user(self, user_id: int):
        """오프라인 모드에서는 사용자 디렉터리 조회를 제공하지 않는다."""
        raise RuntimeError(f"offline fixture does not provide user lookup by id: {user_id}")

    def get_user_by_name(self, name: str):
        """오프라인 모드에서는 사용자 이름 조회를 제공하지 않는다."""
        raise RuntimeError(f"offline fixture does not provide user lookup by name: {name}")

    def get_user_groups(self):
        """오프라인 모드에서는 그룹 목록을 제공하지 않는다."""
        raise RuntimeError("offline fixture does not provide user groups")

    def get_tracker_field_permissions(self, tracker_id: int, field_id: int):
        """오프라인 모드에서는 field permission matrix를 제공하지 않는다."""
        raise RuntimeError(f"offline fixture does not provide field permissions: {tracker_id}/{field_id}")


class OfflinePayloadIntegrationTest(unittest.TestCase):
    """서버 없이 schema JSON과 CSV만으로 어디까지 갈 수 있는지 검증한다."""

    def setUp(self) -> None:
        """각 테스트에서 공통으로 쓸 schema fixture, mapper, processor를 준비한다."""
        self.schema = json.loads((FIXTURE_DIR / "offline_schema.json").read_text(encoding="utf-8"))
        self.csv_path = FIXTURE_DIR / "offline_upload.csv"
        self.mapper = MappingService()
        self.processor = CsvFixtureProcessor(summary_col="요약")
        self.client = OfflineSchemaClient(self.schema)

    def _build_wizard(self, selected_mapping: dict[str, str]) -> CodebeamerUploadWizard:
        """fixture 파일을 읽어 schema 비교와 option 처리까지 끝난 wizard를 만든다."""
        wizard = CodebeamerUploadWizard(
            client=self.client,
            processor=self.processor,
            mapper=self.mapper,
        )
        wizard.select_project(101)
        wizard.select_tracker(202)

        schema_df = self.mapper.flatten_schema_fields(self.schema)
        list_cols = self.mapper.get_list_columns_for_mapping(selected_mapping, schema_df)

        wizard.read_excel(file_path=str(self.csv_path), list_cols=list_cols)
        wizard.load_schema_and_compare(selected_mapping)
        wizard.process_option_mapping(selected_mapping)
        return wizard

    def test_offline_fixtures_build_payload_for_supported_fields(self) -> None:
        """지원되는 필드만 매핑하면 서버 없이도 payload preview까지 만들 수 있어야 한다."""
        wizard = self._build_wizard({
            "요약": "Summary",
            "상태": "Status",
            "승인": "Approved",
            "단계": "Phase",
        })

        payload = wizard.preview_payload(0)
        custom_fields = {field["name"]: field for field in payload["customFields"]}

        self.assertEqual(payload["name"], "REQ-001")
        self.assertEqual(payload["status"]["name"], "Open")
        self.assertEqual(custom_fields["Approved"]["type"], "BoolFieldValue")
        self.assertTrue(custom_fields["Approved"]["value"])
        self.assertEqual(
            [value["name"] for value in custom_fields["Phase"]["values"]],
            ["Draft", "Review"],
        )
        self.assertEqual(custom_fields["체크리스트"]["type"], "TableFieldValue")
        self.assertEqual(custom_fields["체크리스트"]["values"][0][0]["name"], "결과")
        self.assertEqual(custom_fields["체크리스트"]["values"][0][0]["value"], "PASS")

    def test_offline_fixtures_report_user_reference_as_lookup_failed(self) -> None:
        """사용자 정보가 없으면 `UserReference`는 검증 단계에서 lookup 실패로 표시돼야 한다."""
        wizard = self._build_wizard({
            "Owner": "Owner",
        })

        statuses = set(wizard.state.option_check_df["status"].dropna().tolist())

        self.assertIn(UserLookupStatus.USER_LOOKUP_FAILED.value, statuses)
        with self.assertRaisesRegex(ValueError, r"\[LOOKUP_REQUIRED\]"):
            wizard.preview_payload(0)

    def test_offline_fixtures_report_generic_reference_as_lookup_required(self) -> None:
        """generic reference는 서버가 없어도 조기 검증에서 lookup 필요 상태를 보여줘야 한다."""
        wizard = self._build_wizard({
            "Related Candidate": "Related Candidate",
        })

        statuses = set(wizard.state.option_check_df["status"].dropna().tolist())

        self.assertIn(OptionCheckStatus.LOOKUP_REQUIRED.value, statuses)
        with self.assertRaisesRegex(ValueError, r"\[LOOKUP_REQUIRED\]"):
            wizard.preview_payload(0)

    def test_offline_fixtures_report_member_field_as_member_lookup_failed(self) -> None:
        """`MemberField`는 member 후보를 구성하지 못하면 곧바로 lookup 실패로 드러나야 한다."""
        wizard = self._build_wizard({
            "시험 담당자": "시험 담당자",
        })

        statuses = set(wizard.state.option_check_df["status"].dropna().tolist())

        self.assertIn(UserLookupStatus.MEMBER_LOOKUP_FAILED.value, statuses)
        with self.assertRaisesRegex(ValueError, r"\[LOOKUP_REQUIRED\]"):
            wizard.preview_payload(0)


if __name__ == "__main__":
    unittest.main()
