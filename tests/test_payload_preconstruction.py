from __future__ import annotations

import unittest

import pandas as pd

from src.mapping_service import MappingService
from src.models import ColorFieldValue
from src.models import CountryFieldValue
from src.models import DateFieldValue
from src.models import DecimalFieldValue
from src.models import DurationFieldValue
from src.models import IntegerFieldValue
from src.models import LanguageFieldValue
from src.models import PayloadTargetKind
from src.models import PreconstructionKind
from src.models import ReferenceType
from src.models import TrackerItemBase
from src.models import UrlFieldValue
from src.models import UserInfo
from src.models import WikiTextFieldValue
from src.wizard import CodebeamerUploadWizard


class TrackerItemPreconstructionTest(unittest.TestCase):
    def test_create_field_value_uses_official_single_value_models(self) -> None:
        """공식 문서에서 확인된 단일 값 FieldValue 구현체를 우선 사용해야 한다."""
        item = TrackerItemBase()
        cases = [
            (
                {"field_id": 1, "field_name": "Due Date", "field_type": "DateField"},
                "2026-04-14",
                DateFieldValue,
            ),
            (
                {"field_id": 11, "field_name": "Color", "field_type": "ColorField"},
                "#ffffff",
                ColorFieldValue,
            ),
            (
                {"field_id": 12, "field_name": "Country", "field_type": "CountryField"},
                "KR",
                CountryFieldValue,
            ),
            (
                {"field_id": 2, "field_name": "Score", "field_type": "DecimalField"},
                "1.5",
                DecimalFieldValue,
            ),
            (
                {"field_id": 3, "field_name": "Spent", "field_type": "DurationField"},
                "30",
                DurationFieldValue,
            ),
            (
                {"field_id": 4, "field_name": "Size", "field_type": "IntegerField"},
                "5",
                IntegerFieldValue,
            ),
            (
                {"field_id": 13, "field_name": "Language", "field_type": "LanguageField"},
                "ko",
                LanguageFieldValue,
            ),
            (
                {"field_id": 5, "field_name": "Link", "field_type": "UrlField"},
                "https://example.com",
                UrlFieldValue,
            ),
            (
                {"field_id": 6, "field_name": "Notes", "field_type": "WikiTextField"},
                "Some wiki text",
                WikiTextFieldValue,
            ),
        ]

        for field_info, raw_value, expected_type in cases:
            with self.subTest(field_type=field_info["field_type"]):
                field_info["preconstruction_kind"] = PreconstructionKind.FIELD_VALUE.value
                value = item._create_field_value(field_info, raw_value)
                self.assertIsInstance(value, expected_type)

    def test_set_field_value_sets_builtin_direct_scalar(self) -> None:
        """builtin direct 필드는 값이 바로 기본 속성에 들어가야 한다."""
        item = TrackerItemBase()

        item.set_field_value(
            "name",
            "REQ-001",
            {
                "field_name": "Summary",
                "field_type": "TextField",
                "is_supported": True,
                "payload_target_kind": PayloadTargetKind.BUILTIN_FIELD.value,
                "preconstruction_kind": PreconstructionKind.BUILTIN_DIRECT.value,
            },
        )

        self.assertEqual(item.name, "REQ-001")

    def test_set_field_value_preserves_original_float_for_builtin_text(self) -> None:
        """builtin 문자열 필드는 입력된 float 표현을 임의로 바꾸지 않아야 한다."""
        item = TrackerItemBase()

        item.set_field_value(
            "name",
            12.0,
            {
                "field_name": "Summary",
                "field_type": "TextField",
                "is_supported": True,
                "payload_target_kind": PayloadTargetKind.BUILTIN_FIELD.value,
                "preconstruction_kind": PreconstructionKind.BUILTIN_DIRECT.value,
            },
        )

        self.assertEqual(item.name, "12.0")

    def test_set_field_value_builds_custom_field_value(self) -> None:
        """custom field는 알맞은 FieldValue 객체로 감싸져야 한다."""
        item = TrackerItemBase()

        item.set_field_value(
            "Approved",
            True,
            {
                "field_id": 7,
                "field_name": "Approved",
                "field_type": "BoolField",
                "value_model": "BoolFieldValue",
                "is_supported": True,
                "payload_target_kind": PayloadTargetKind.CUSTOM_FIELD.value,
                "preconstruction_kind": PreconstructionKind.FIELD_VALUE.value,
            },
        )

        payload = item.create_new_item_payload()
        self.assertEqual(len(payload["customFields"]), 1)
        self.assertEqual(payload["customFields"][0]["type"], "BoolFieldValue")
        self.assertTrue(payload["customFields"][0]["value"])

    def test_set_field_value_builds_builtin_reference_list(self) -> None:
        """builtin 다중 reference 필드는 reference 목록으로 저장돼야 한다."""
        item = TrackerItemBase()

        item.set_field_value(
            "assignedTo",
            [{"id": 10, "name": "Jane Doe", "type": "UserReference"}],
            {
                "field_name": "Assigned To",
                "field_type": "ReferenceField",
                "reference_type": ReferenceType.USER.value,
                "multiple_values": True,
                "is_supported": True,
                "payload_target_kind": PayloadTargetKind.BUILTIN_FIELD.value,
                "preconstruction_kind": PreconstructionKind.REFERENCE_LIST.value,
            },
        )

        payload = item.create_new_item_payload()
        self.assertEqual(payload["assignedTo"][0]["id"], 10)
        self.assertEqual(payload["assignedTo"][0]["type"], ReferenceType.USER.value)

    def test_set_field_value_parses_tracker_item_reference_from_bracket_text(self) -> None:
        """TrackerItemReference는 `[]` 안 첫 번째 정수를 파싱해 만들어야 한다."""
        item = TrackerItemBase()

        item.set_field_value(
            "subjects",
            ["Candidate [REQ:20263671] extra text", "[20263672] another"],
            {
                "field_name": "Subjects",
                "field_type": "TrackerItemChoiceField",
                "reference_type": ReferenceType.TRACKER_ITEM.value,
                "multiple_values": True,
                "is_supported": True,
                "payload_target_kind": PayloadTargetKind.BUILTIN_FIELD.value,
                "preconstruction_kind": PreconstructionKind.REFERENCE_LIST.value,
            },
        )

        payload = item.create_new_item_payload()
        self.assertEqual([value["id"] for value in payload["subjects"]], [20263671, 20263672])
        self.assertEqual(
            [value["type"] for value in payload["subjects"]],
            [ReferenceType.TRACKER_ITEM.value, ReferenceType.TRACKER_ITEM.value],
        )

    def test_set_field_value_rejects_unsupported_field(self) -> None:
        """지원하지 않는 필드는 payload 생성 전에 바로 거부해야 한다."""
        item = TrackerItemBase()

        with self.assertRaisesRegex(ValueError, "unsupported"):
            item.set_field_value(
                "mysteryField",
                "value",
                {
                    "field_name": "Mystery",
                    "field_type": "OptionChoiceField",
                    "is_supported": False,
                    "unsupported_reason": "schema가 불명확합니다.",
                    "payload_target_kind": PayloadTargetKind.CUSTOM_FIELD.value,
                    "preconstruction_kind": PreconstructionKind.NONE.value,
                },
            )


class WizardPayloadResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        """payload preview 테스트에 쓸 wizard를 준비한다."""
        self.mapper = MappingService()
        self.wizard = CodebeamerUploadWizard(
            client=None,
            processor=None,
            mapper=self.mapper,
        )

    def test_preview_payload_fails_early_for_generic_reference_without_resolver(self) -> None:
        """resolver가 없는 generic reference는 preview 단계에서 즉시 실패해야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 3,
                "name": "Related Candidate",
                "type": "ReferenceField",
                "referenceType": "TrackerItemReference",
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            }
        ])
        self.wizard.state.selected_mapping = {"related": "Related Candidate"}
        self.wizard.state.selected_option_mapping = {"related": "Related Candidate"}
        self.wizard.state.option_maps = self.mapper.build_option_maps_from_schema(self.wizard.state.schema_df)
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "related": "REQ-2"}
        ])

        with self.assertRaisesRegex(ValueError, r"\[LOOKUP_REQUIRED\]"):
            self.wizard.preview_payload(1)

    def test_preview_payload_fails_early_for_unsupported_field(self) -> None:
        """미지원 필드는 preview 단계에서 즉시 `FIELD_UNSUPPORTED`를 내야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 4,
                "name": "Choice Hint Only",
                "type": "OptionChoiceField",
                "valueModel": "ChoiceFieldValue<AbstractReference>",
            }
        ])
        self.wizard.state.selected_mapping = {"choice_hint": "Choice Hint Only"}
        self.wizard.state.selected_option_mapping = {"choice_hint": "Choice Hint Only"}
        self.wizard.state.option_maps = self.mapper.build_option_maps_from_schema(self.wizard.state.schema_df)
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "choice_hint": "Anything"}
        ])

        with self.assertRaisesRegex(ValueError, r"\[FIELD_UNSUPPORTED\]"):
            self.wizard.preview_payload(1)

    def test_preview_payload_builds_member_field_from_user_role_group_names(self) -> None:
        """MemberField는 USER/ROLE/GROUP 이름을 각각 해당 reference로 변환해야 한다."""

        class NotFoundError(Exception):
            def __init__(self) -> None:
                self.response = type("Response", (), {"status_code": 404})()
                super().__init__("not found")

        class FakeUserClient:
            def get_user_by_name(self, name: str) -> UserInfo:
                if name == "Kim QA":
                    return UserInfo(id=101, name=name)
                raise NotFoundError()

            def get_user(self, user_id: int) -> UserInfo:
                return UserInfo(id=user_id, name=f"User {user_id}")

            def get_user_groups(self):
                return [
                    {"id": 301, "name": "QA Group", "type": "GroupReference"},
                ]

            def get_tracker_field_permissions(self, tracker_id: int, field_id: int):
                return [
                    {
                        "status": {"id": 0, "name": "Unset", "type": "ChoiceOptionReference"},
                        "permissions": [
                            {
                                "role": {"id": 201, "name": "Developer", "type": "RoleReference"},
                            }
                        ],
                    }
                ]

        wizard = CodebeamerUploadWizard(
            client=FakeUserClient(),
            processor=None,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(1)
        wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 9,
                "name": "시험 담당자",
                "type": "MemberField",
                "valueModel": "ChoiceFieldValue",
                "multipleValues": True,
                "memberTypes": ["USER", "ROLE", "GROUP"],
            }
        ])
        wizard.state.selected_mapping = {"members": "시험 담당자"}
        wizard.state.selected_option_mapping = {"members": "시험 담당자"}
        wizard.state.option_maps = self.mapper.build_option_maps_from_schema(wizard.state.schema_df)
        wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "members": ["Kim QA", "Developer", "QA Group"]}
        ])
        wizard.state.converted_upload_df = wizard._resolve_member_reference_fields(
            wizard.state.upload_df,
            wizard.state.selected_option_mapping,
            wizard.state.option_maps,
        )

        payload = wizard.preview_payload(1)
        custom_field = payload["customFields"][0]

        self.assertEqual(custom_field["name"], "시험 담당자")
        self.assertEqual(custom_field["type"], "ChoiceFieldValue")
        self.assertEqual([value["name"] for value in custom_field["values"]], ["Kim QA", "Developer", "QA Group"])
        self.assertEqual(
            [value["type"] for value in custom_field["values"]],
            ["UserReference", "RoleReference", "GroupReference"],
        )

    def test_preview_payload_builds_table_field_value_from_column_field_values(self) -> None:
        """TableField는 일반 custom field처럼 중복 생성하지 말고 셀별 FieldValue로 묶어야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 1000000,
                "name": "Test Steps",
                "type": "TableField",
                "valueModel": "TableFieldValue",
                "columns": [
                    {
                        "id": 1000001,
                        "name": "Action",
                        "type": "WikiTextField",
                        "valueModel": "WikiTextFieldValue",
                    },
                    {
                        "id": 1000002,
                        "name": "Expected result",
                        "type": "WikiTextField",
                        "valueModel": "WikiTextFieldValue",
                    },
                    {
                        "id": 1000003,
                        "name": "Critical?",
                        "type": "BoolField",
                        "valueModel": "BoolFieldValue",
                    },
                ],
            }
        ])
        self.wizard.state.selected_mapping = {
            "Test Steps.Action": "Test Steps",
            "Test Steps.Expected result": "Test Steps",
            "Test Steps.Critical?": "Test Steps",
        }
        self.wizard.state.table_field_mapping = {
            "Test Steps.Action": {
                "table_field_name": "Test Steps",
                "column_name": "Action",
                "column_info": {
                    "id": 1000001,
                    "name": "Action",
                    "type": "WikiTextField",
                    "valueModel": "WikiTextFieldValue",
                },
            },
            "Test Steps.Expected result": {
                "table_field_name": "Test Steps",
                "column_name": "Expected result",
                "column_info": {
                    "id": 1000002,
                    "name": "Expected result",
                    "type": "WikiTextField",
                    "valueModel": "WikiTextFieldValue",
                },
            },
            "Test Steps.Critical?": {
                "table_field_name": "Test Steps",
                "column_name": "Critical?",
                "column_info": {
                    "id": 1000003,
                    "name": "Critical?",
                    "type": "BoolField",
                    "valueModel": "BoolFieldValue",
                },
            },
        }
        self.wizard.state.upload_df = pd.DataFrame([
            {
                "_row_id": 1,
                "upload_name": "REQ-1",
                "Test Steps.Action": ["ACU_RetFlag := 1", "BMS_Timeout := 0"],
                "Test Steps.Expected result": ["Result A", "Result B"],
                "Test Steps.Critical?": [False, True],
            }
        ])

        payload = self.wizard.preview_payload(1)

        self.assertEqual(len(payload["customFields"]), 1)
        custom_field = payload["customFields"][0]
        self.assertEqual(custom_field["name"], "Test Steps")
        self.assertEqual(custom_field["type"], "TableFieldValue")
        self.assertEqual(len(custom_field["values"]), 2)
        self.assertEqual(
            [value["type"] for value in custom_field["values"][0]],
            ["WikiTextFieldValue", "WikiTextFieldValue", "BoolFieldValue"],
        )
        self.assertEqual(custom_field["values"][0][0]["value"], "ACU_RetFlag := 1")
        self.assertFalse(custom_field["values"][0][2]["value"])
        self.assertTrue(custom_field["values"][1][2]["value"])

    def test_preview_payload_applies_default_status_when_row_value_is_missing(self) -> None:
        """행 값이 없으면 선택한 공통 기본값으로 Status를 채워야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
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
                "options": [{"id": 11, "name": "Open"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
        ])
        self.wizard.state.selected_mapping = {"summary": "Summary"}
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "summary": "REQ-1"}
        ])
        self.wizard.process_option_mapping(
            self.wizard.state.selected_mapping,
            selected_default_values={"Status": "Open"},
        )

        payload = self.wizard.preview_payload(1)

        self.assertEqual(payload["name"], "REQ-1")
        self.assertEqual(payload["status"]["name"], "Open")

    def test_preview_payload_prefers_row_value_over_default_status(self) -> None:
        """행 값이 있으면 공통 기본값보다 행 값을 우선해야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
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
                "options": [{"id": 11, "name": "Open"}, {"id": 12, "name": "Review"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
        ])
        self.wizard.state.selected_mapping = {"summary": "Summary", "status": "Status"}
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "summary": "REQ-1", "status": "Review"}
        ])
        self.wizard.process_option_mapping(
            self.wizard.state.selected_mapping,
            selected_default_values={"Status": "Open"},
        )

        payload = self.wizard.preview_payload(1)

        self.assertEqual(payload["name"], "REQ-1")
        self.assertEqual(payload["status"]["name"], "Review")

    def test_preview_payload_applies_default_text_field_when_row_value_is_missing(self) -> None:
        """행 값이 없으면 선택한 공통 기본값으로 텍스트 custom field를 채워야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 2,
                "name": "담당자",
                "type": "TextField",
                "valueModel": "TextFieldValue",
            },
        ])
        self.wizard.state.selected_mapping = {"summary": "Summary"}
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "summary": "REQ-1"}
        ])
        self.wizard.process_option_mapping(
            self.wizard.state.selected_mapping,
            selected_default_values={"담당자": "홍길동"},
        )

        payload = self.wizard.preview_payload(1)

        self.assertEqual(payload["name"], "REQ-1")
        self.assertEqual(payload["customFields"][0]["name"], "담당자")
        self.assertEqual(payload["customFields"][0]["value"], "홍길동")

    def test_preview_payload_applies_default_user_reference_field_when_row_value_is_missing(self) -> None:
        """행 값이 없으면 선택한 공통 기본값으로 UserReference custom field를 채워야 한다."""

        class FakeUserClient:
            def get_user_by_name(self, name: str) -> UserInfo:
                if name == "Jane Doe":
                    return UserInfo(id=101, name=name)
                raise ValueError("user not found")

            def get_user(self, user_id: int) -> UserInfo:
                return UserInfo(id=user_id, name="Jane Doe")

        wizard = CodebeamerUploadWizard(
            client=FakeUserClient(),
            processor=None,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(1)
        wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 2,
                "name": "담당 사용자",
                "type": "ReferenceField",
                "referenceType": "UserReference",
                "valueModel": "ChoiceFieldValue<UserReference>",
            },
        ])
        wizard.state.selected_mapping = {"summary": "Summary"}
        wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "summary": "REQ-1"}
        ])
        wizard.process_option_mapping(
            wizard.state.selected_mapping,
            selected_default_values={"담당 사용자": "Jane Doe"},
        )

        payload = wizard.preview_payload(1)

        self.assertEqual(payload["name"], "REQ-1")
        self.assertEqual(payload["customFields"][0]["name"], "담당 사용자")
        self.assertEqual(payload["customFields"][0]["type"], "ChoiceFieldValue")
        self.assertEqual(payload["customFields"][0]["values"][0]["id"], 101)
        self.assertEqual(payload["customFields"][0]["values"][0]["type"], "UserReference")

    def test_preview_payload_applies_default_member_field_when_row_value_is_missing(self) -> None:
        """행 값이 없으면 선택한 공통 기본값으로 MemberField custom field를 채워야 한다."""

        class NotFoundError(Exception):
            def __init__(self) -> None:
                self.response = type("Response", (), {"status_code": 404})()
                super().__init__("not found")

        class FakeMemberClient:
            def get_user_by_name(self, name: str) -> UserInfo:
                raise NotFoundError()

            def get_user(self, user_id: int) -> UserInfo:
                return UserInfo(id=user_id, name=f"User {user_id}")

            def get_user_groups(self):
                return [
                    {"id": 301, "name": "QA Group", "type": "GroupReference"},
                ]

            def get_tracker_field_permissions(self, tracker_id: int, field_id: int):
                return [
                    {
                        "status": {"id": 0, "name": "Unset", "type": "ChoiceOptionReference"},
                        "permissions": [
                            {
                                "role": {"id": 201, "name": "Developer", "type": "RoleReference"},
                            }
                        ],
                    }
                ]

        wizard = CodebeamerUploadWizard(
            client=FakeMemberClient(),
            processor=None,
            mapper=self.mapper,
        )
        wizard.select_project(1)
        wizard.select_tracker(1)
        wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 9,
                "name": "시험 담당자",
                "type": "MemberField",
                "valueModel": "ChoiceFieldValue",
                "multipleValues": False,
                "memberTypes": ["USER", "ROLE", "GROUP"],
            },
        ])
        wizard.state.selected_mapping = {"summary": "Summary"}
        wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "summary": "REQ-1"}
        ])
        wizard.process_option_mapping(
            wizard.state.selected_mapping,
            selected_default_values={"시험 담당자": "Developer"},
        )

        payload = wizard.preview_payload(1)

        self.assertEqual(payload["name"], "REQ-1")
        self.assertEqual(payload["customFields"][0]["name"], "시험 담당자")
        self.assertEqual(payload["customFields"][0]["type"], "ChoiceFieldValue")
        self.assertEqual(payload["customFields"][0]["values"][0]["id"], 201)
        self.assertEqual(payload["customFields"][0]["values"][0]["type"], "RoleReference")

    def test_preview_payload_applies_default_multi_tracker_item_field_when_row_value_is_missing(self) -> None:
        """다중 TrackerItemChoiceField도 행 값이 없으면 기본값 1건을 사용해야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 15,
                "name": "연관 요구사항",
                "type": "TrackerItemChoiceField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            }
        ])
        self.wizard.state.selected_mapping = {}
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1"}
        ])
        self.wizard.process_option_mapping(
            self.wizard.state.selected_mapping,
            selected_default_values={"연관 요구사항": "Candidate [REQ:20263672] extra"},
        )

        payload = self.wizard.preview_payload(1)
        custom_field = payload["customFields"][0]

        self.assertEqual(custom_field["name"], "연관 요구사항")
        self.assertEqual(custom_field["type"], "ChoiceFieldValue")
        self.assertEqual([value["id"] for value in custom_field["values"]], [20263672])
        self.assertEqual([value["type"] for value in custom_field["values"]], ["TrackerItemReference"])

    def test_build_root_item_payload_wraps_single_fixed_value_for_multi_choice_field(self) -> None:
        """상단 데이터의 다중 선택형 필드는 단일 입력도 한 건짜리 목록으로 직렬화해야 한다."""
        self.wizard.select_project(1)
        self.wizard.select_tracker(1)
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 1,
                "name": "Summary",
                "type": "TextField",
                "trackerItemField": "name",
                "valueModel": "TextFieldValue",
            },
            {
                "id": 2,
                "name": "태그",
                "type": "OptionChoiceField",
                "multipleValues": True,
                "options": [{"id": 11, "name": "Open"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
        ])
        self.wizard.state.option_maps = self.mapper.build_option_maps_from_schema(self.wizard.state.schema_df)

        payload = self.wizard._build_root_item_payload(
            "ROOT-REQ",
            root_field_values={"태그": "Open"},
        )

        self.assertEqual(payload["name"], "ROOT-REQ")
        self.assertEqual(payload["customFields"][0]["name"], "태그")
        self.assertEqual(payload["customFields"][0]["type"], "ChoiceFieldValue")
        self.assertEqual(len(payload["customFields"][0]["values"]), 1)
        self.assertEqual(payload["customFields"][0]["values"][0]["id"], 11)
        self.assertEqual(payload["customFields"][0]["values"][0]["name"], "Open")

    def test_process_option_mapping_reports_invalid_default_status_value(self) -> None:
        """잘못된 기본값은 option 검증 단계에서 바로 드러나야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
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
                "options": [{"id": 11, "name": "Open"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
        ])
        self.wizard.state.selected_mapping = {"summary": "Summary"}
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "summary": "REQ-1"}
        ])

        _, option_check_df = self.wizard.process_option_mapping(
            self.wizard.state.selected_mapping,
            selected_default_values={"Status": "Missing"},
        )

        self.assertEqual(option_check_df.iloc[0]["df_column"], "(기본값)")
        self.assertEqual(option_check_df.iloc[0]["schema_field"], "Status")
        self.assertEqual(option_check_df.iloc[0]["status"], "OPTION_NOT_FOUND")

    def test_process_option_mapping_skips_update_only_option_validation_for_upsert_create_rows(self) -> None:
        """upsert에서는 수정 전용 옵션 필드가 생성 행에서 검증되지 않아야 한다."""
        self.wizard.state.upload_mode = "upsert"
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
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
                "options": [{"id": 11, "name": "Open"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
        ])
        self.wizard.state.selected_mapping = {
            "summary": "Summary",
            "status": "Status",
        }
        self.wizard.state.upload_df = pd.DataFrame([
            {"_row_id": 1, "upload_name": "REQ-1", "summary": "REQ-1", "status": "Missing"},
            {"_row_id": 2, "upload_name": "REQ-2", "id": 101, "summary": "REQ-2", "status": "Open"},
        ])

        _, option_check_df = self.wizard.process_option_mapping(
            self.wizard.state.selected_mapping,
            selected_mapping_modes={
                "status": {"create": False, "update": True},
            },
        )

        self.assertNotIn("OPTION_NOT_FOUND", option_check_df["status"].tolist())
        self.assertEqual(option_check_df["_row_id"].dropna().tolist(), [])
        converted = self.wizard.state.converted_upload_df
        self.assertIsNotNone(converted)
        self.assertEqual(converted.iloc[0]["status"], "Missing")
        self.assertIsNone(converted.iloc[0]["status__resolved"])
        self.assertEqual(converted.iloc[1]["status__resolved"]["name"], "Open")

    def test_preview_payload_builds_tracker_item_choice_field_from_bracket_text(self) -> None:
        """TrackerItemChoiceField는 입력 문자열에서 item id를 직접 파싱해야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 15,
                "name": "연관 요구사항",
                "type": "TrackerItemChoiceField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            }
        ])
        self.wizard.state.selected_mapping = {"related_items": "연관 요구사항"}
        self.wizard.state.selected_option_mapping = {"related_items": "연관 요구사항"}
        self.wizard.state.option_maps = self.mapper.build_option_maps_from_schema(self.wizard.state.schema_df)
        self.wizard.state.upload_df = pd.DataFrame([
            {
                "_row_id": 1,
                "upload_name": "REQ-1",
                "related_items": ["Candidate [REQ:20263671] extra", "20263672"],
            }
        ])
        self.wizard.state.converted_upload_df = self.mapper.apply_option_resolution(
            self.wizard.state.upload_df,
            self.wizard.state.selected_option_mapping,
            self.wizard.state.option_maps,
        )

        payload = self.wizard.preview_payload(1)
        custom_field = payload["customFields"][0]

        self.assertEqual(custom_field["name"], "연관 요구사항")
        self.assertEqual(custom_field["type"], "ChoiceFieldValue")
        self.assertEqual([value["id"] for value in custom_field["values"]], [20263671, 20263672])
        self.assertEqual(
            [value["type"] for value in custom_field["values"]],
            ["TrackerItemReference", "TrackerItemReference"],
        )

    def test_preview_payload_builds_tracker_item_choice_field_from_multiline_bracket_text(self) -> None:
        """다중 TrackerItemChoiceField는 한 셀의 여러 줄 텍스트도 각각 reference로 풀어야 한다."""
        self.wizard.state.schema_df = self.mapper.flatten_schema_fields([
            {
                "id": 15,
                "name": "연관 요구사항",
                "type": "TrackerItemChoiceField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            }
        ])
        self.wizard.state.selected_mapping = {"related_items": "연관 요구사항"}
        self.wizard.state.selected_option_mapping = {"related_items": "연관 요구사항"}
        self.wizard.state.option_maps = self.mapper.build_option_maps_from_schema(self.wizard.state.schema_df)
        self.wizard.state.upload_df = pd.DataFrame([
            {
                "_row_id": 1,
                "upload_name": "REQ-1",
                "related_items": "Candidate [REQ:20263671]\nCandidate [REQ:20263672]",
            }
        ])
        self.wizard.state.converted_upload_df = self.mapper.apply_option_resolution(
            self.wizard.state.upload_df,
            self.wizard.state.selected_option_mapping,
            self.wizard.state.option_maps,
        )

        payload = self.wizard.preview_payload(1)
        custom_field = payload["customFields"][0]

        self.assertEqual(custom_field["name"], "연관 요구사항")
        self.assertEqual([value["id"] for value in custom_field["values"]], [20263671, 20263672])


if __name__ == "__main__":
    unittest.main()
