from __future__ import annotations

import unittest

import pandas as pd

from src.mapping_service import MappingService
from src.models import FieldValueType
from src.models import LookupTargetKind
from src.models import OptionCheckStatus
from src.models import OptionMapKind
from src.models import OptionSourceStatus
from src.models import PayloadTargetKind
from src.models import PreconstructionKind
from src.models import ResolvedFieldKind
from src.models import UserLookupStatus


class MappingServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        """각 테스트마다 새 `MappingService` 인스턴스를 준비한다."""
        self.service = MappingService()

    @staticmethod
    def _field_by_name(schema_df: pd.DataFrame, field_name: str) -> pd.Series:
        """schema 표에서 이름으로 원하는 필드 한 행을 찾는다."""
        matched = schema_df[schema_df["field_name"] == field_name]
        if matched.empty:
            raise AssertionError(f"Field not found in schema_df: {field_name}")
        return matched.iloc[0]

    def test_get_list_columns_for_mapping_returns_only_multiple_value_fields(self) -> None:
        """여러 값을 받는 필드에 연결된 컬럼만 list 컬럼으로 잡히는지 확인한다."""
        schema_df = pd.DataFrame([
            {"field_name": "Summary", "multiple_values": False},
            {"field_name": "Assignees", "multiple_values": True},
            {"field_name": "Categories", "multiple_values": "true"},
            {"field_name": "Priority", "multiple_values": None},
        ])
        selected_mapping = {
            "요약": "Summary",
            "담당자": "Assignees",
            "분류": "Categories",
            "우선순위": "Priority",
        }

        list_columns = self.service.get_list_columns_for_mapping(selected_mapping, schema_df)

        self.assertEqual(list_columns, ["담당자", "분류"])

    def test_get_list_columns_for_mapping_returns_empty_for_empty_mapping(self) -> None:
        """매핑이 비어 있으면 list 컬럼도 비어 있어야 한다."""
        schema_df = pd.DataFrame([
            {"field_name": "Assignees", "multiple_values": True},
        ])

        list_columns = self.service.get_list_columns_for_mapping({}, schema_df)

        self.assertEqual(list_columns, [])

    def test_get_list_columns_for_mapping_includes_table_field_pseudo_columns(self) -> None:
        """`TableField.Column` 형식 컬럼은 멀티라인 병합을 위해 list 컬럼으로 다뤄야 한다."""
        schema_df = pd.DataFrame([
            {"field_name": "Summary", "multiple_values": False, "is_table_field": False},
            {"field_name": "Test Steps", "multiple_values": False, "is_table_field": True},
        ])
        selected_mapping = {
            "요약": "Summary",
            "Test Steps.Action": "Test Steps",
            "Test Steps.Expected result": "Test Steps",
        }

        list_columns = self.service.get_list_columns_for_mapping(selected_mapping, schema_df)

        self.assertEqual(list_columns, ["Test Steps.Action", "Test Steps.Expected result"])

    def test_resolve_tracker_item_reference_value_with_regex_extracts_multiple_matches_from_one_cell(self) -> None:
        """다중 tracker item 필드는 한 셀 안의 여러 정규식 매치도 각각 reference로 변환해야 한다."""
        resolved = self.service.resolve_tracker_item_reference_value_with_regex(
            "REQ-A [REQ:20263671], REQ-B [REQ:20263672]",
            multiple_values=True,
            pattern=r"\[(?:[^:\]]+:)?(\d+)[^\]]*\]|^(\d+)(?:\.0)?$",
        )

        self.assertEqual(
            resolved,
            [
                {"id": 20263671, "type": "TrackerItemReference"},
                {"id": 20263672, "type": "TrackerItemReference"},
            ],
        )

    def test_get_default_value_candidates_returns_single_static_option_fields_only(self) -> None:
        """공통 기본값 후보는 단일 static option 필드만 포함해야 한다."""
        schema_df = self.service.flatten_schema_fields([
            {
                "id": 1,
                "name": "Status",
                "type": "OptionChoiceField",
                "trackerItemField": "status",
                "options": [
                    {"id": 11, "name": "Open"},
                    {"id": 12, "name": "Review"},
                ],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
            {
                "id": 2,
                "name": "Phase",
                "type": "OptionChoiceField",
                "multipleValues": True,
                "options": [{"id": 21, "name": "Draft"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
            {
                "id": 3,
                "name": "Owner",
                "type": "ReferenceField",
                "referenceType": "UserReference",
                "valueModel": "ChoiceFieldValue<UserReference>",
            },
        ])

        candidates = self.service.get_default_value_candidates(schema_df)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["field_name"], "Status")
        self.assertEqual(candidates[0]["options"], ["Open", "Review"])

    def test_flatten_schema_fields_resolves_field_kind_and_preconstruction(self) -> None:
        """서로 다른 schema type이 올바른 내부 분류와 선구성 규칙으로 해석되는지 본다."""
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
                "name": "Phase",
                "type": "OptionChoiceField",
                "options": [{"id": 11, "name": "Draft"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
            {
                "id": 3,
                "name": "Owner",
                "type": "ReferenceField",
                "referenceType": "UserReference",
                "valueModel": "ChoiceFieldValue<UserReference>",
            },
            {
                "id": 4,
                "name": "Related Candidate",
                "type": "ReferenceField",
                "referenceType": "TrackerItemReference",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            },
            {
                "id": 5,
                "name": "Related Missing Type",
                "type": "ReferenceField",
                "multipleValues": False,
            },
            {
                "id": 6,
                "name": "Choice Hint Only",
                "type": "OptionChoiceField",
                "valueModel": "ChoiceFieldValue<AbstractReference>",
            },
            {
                "id": 7,
                "name": "Checklist",
                "type": "TableField",
                "columns": [],
            },
            {
                "id": 8,
                "name": "Approved",
                "type": "BoolField",
                "valueModel": "BoolFieldValue",
            },
            {
                "id": 9,
                "name": "Status",
                "type": "OptionChoiceField",
                "trackerItemField": "status",
                "options": [{"id": 21, "name": "Open"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
            {
                "id": 10,
                "name": "Assigned To",
                "type": "ReferenceField",
                "trackerItemField": "assignedTo",
                "referenceType": "UserReference",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<UserReference>",
            },
            {
                "id": 11,
                "name": "Related Items",
                "type": "TrackerItemChoiceField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            },
            {
                "id": 13,
                "name": "Team",
                "type": "MemberField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<AbstractReference>",
                "memberTypes": ["USER", "ROLE", "GROUP"],
            },
            {
                "id": 12,
                "name": "Subjects",
                "type": "ReferenceField",
                "trackerItemField": "subjects",
                "referenceType": "TrackerItemReference",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            },
        ]

        schema_df = self.service.flatten_schema_fields(schema)

        summary = self._field_by_name(schema_df, "Summary")
        self.assertEqual(summary["resolved_field_kind"], ResolvedFieldKind.SCALAR_TEXT.value)
        self.assertEqual(summary["payload_target_kind"], PayloadTargetKind.BUILTIN_FIELD.value)
        self.assertEqual(summary["preconstruction_kind"], PreconstructionKind.BUILTIN_DIRECT.value)
        self.assertTrue(summary["is_supported"])

        approved = self._field_by_name(schema_df, "Approved")
        self.assertEqual(approved["resolved_field_kind"], ResolvedFieldKind.SCALAR_BOOL.value)
        self.assertEqual(approved["preconstruction_kind"], PreconstructionKind.FIELD_VALUE.value)
        self.assertEqual(approved["preconstruction_detail"], FieldValueType.BOOL.value)

        checklist = self._field_by_name(schema_df, "Checklist")
        self.assertEqual(checklist["resolved_field_kind"], ResolvedFieldKind.TABLE.value)
        self.assertEqual(checklist["preconstruction_kind"], PreconstructionKind.TABLE_FIELD_VALUE.value)
        self.assertEqual(checklist["preconstruction_detail"], FieldValueType.TABLE.value)

        phase = self._field_by_name(schema_df, "Phase")
        self.assertEqual(phase["resolved_field_kind"], ResolvedFieldKind.STATIC_OPTION.value)
        self.assertEqual(phase["payload_target_kind"], PayloadTargetKind.CUSTOM_FIELD.value)
        self.assertEqual(phase["preconstruction_kind"], PreconstructionKind.FIELD_VALUE.value)
        self.assertEqual(phase["requires_lookup"], False)

        owner = self._field_by_name(schema_df, "Owner")
        self.assertEqual(owner["resolved_field_kind"], ResolvedFieldKind.USER_REFERENCE.value)
        self.assertEqual(owner["lookup_target_kind"], LookupTargetKind.USER.value)
        self.assertTrue(owner["requires_lookup"])
        self.assertEqual(owner["preconstruction_kind"], PreconstructionKind.FIELD_VALUE.value)

        related_candidate = self._field_by_name(schema_df, "Related Candidate")
        self.assertEqual(related_candidate["resolved_field_kind"], ResolvedFieldKind.GENERIC_REFERENCE.value)
        self.assertTrue(related_candidate["requires_lookup"])
        self.assertEqual(related_candidate["lookup_target_kind"], LookupTargetKind.REFERENCE.value)
        self.assertEqual(related_candidate["preconstruction_kind"], PreconstructionKind.FIELD_VALUE.value)
        self.assertTrue(related_candidate["is_supported"])

        related_missing_type = self._field_by_name(schema_df, "Related Missing Type")
        self.assertEqual(related_missing_type["resolved_field_kind"], ResolvedFieldKind.GENERIC_REFERENCE.value)
        self.assertFalse(related_missing_type["is_supported"])
        self.assertIn("referenceType", related_missing_type["unsupported_reason"])

        choice_hint = self._field_by_name(schema_df, "Choice Hint Only")
        self.assertEqual(choice_hint["resolved_field_kind"], ResolvedFieldKind.UNSUPPORTED.value)
        self.assertFalse(choice_hint["is_supported"])
        self.assertIn("valueModel", choice_hint["unsupported_reason"])

        status = self._field_by_name(schema_df, "Status")
        self.assertEqual(status["payload_target_kind"], PayloadTargetKind.BUILTIN_FIELD.value)
        self.assertEqual(status["preconstruction_kind"], PreconstructionKind.REFERENCE.value)

        assigned_to = self._field_by_name(schema_df, "Assigned To")
        self.assertEqual(assigned_to["payload_target_kind"], PayloadTargetKind.BUILTIN_FIELD.value)
        self.assertEqual(assigned_to["preconstruction_kind"], PreconstructionKind.REFERENCE_LIST.value)

        related_items = self._field_by_name(schema_df, "Related Items")
        self.assertEqual(related_items["resolved_field_kind"], ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value)
        self.assertFalse(related_items["requires_lookup"])
        self.assertEqual(related_items["preconstruction_kind"], PreconstructionKind.FIELD_VALUE.value)
        self.assertEqual(related_items["preconstruction_detail"], "ChoiceFieldValue<TrackerItemReference>")

        team = self._field_by_name(schema_df, "Team")
        self.assertEqual(team["resolved_field_kind"], ResolvedFieldKind.MEMBER_REFERENCE.value)
        self.assertTrue(team["requires_lookup"])
        self.assertEqual(team["lookup_target_kind"], LookupTargetKind.MEMBER.value)
        self.assertEqual(team["preconstruction_kind"], PreconstructionKind.FIELD_VALUE.value)
        self.assertEqual(team["preconstruction_detail"], "ChoiceFieldValue<AbstractReference>")

        subjects = self._field_by_name(schema_df, "Subjects")
        self.assertEqual(subjects["resolved_field_kind"], ResolvedFieldKind.TRACKER_ITEM_REFERENCE.value)
        self.assertEqual(subjects["payload_target_kind"], PayloadTargetKind.BUILTIN_FIELD.value)
        self.assertEqual(subjects["preconstruction_kind"], PreconstructionKind.REFERENCE_LIST.value)
        self.assertFalse(subjects["requires_lookup"])

    def test_compare_upload_df_with_schema_includes_resolution_columns(self) -> None:
        """비교 결과 표에도 분류와 lookup 정보가 함께 들어가는지 확인한다."""
        schema_df = self.service.flatten_schema_fields([
            {
                "id": 1,
                "name": "Owner",
                "type": "ReferenceField",
                "referenceType": "UserReference",
                "valueModel": "ChoiceFieldValue<UserReference>",
            },
            {
                "id": 2,
                "name": "Team",
                "type": "MemberField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<AbstractReference>",
                "memberTypes": ["USER", "ROLE", "GROUP"],
            },
        ])
        upload_df = pd.DataFrame([{"owner": "Jane Doe", "team": "Developers"}])
        comparison_df = self.service.compare_upload_df_with_schema(
            upload_df=upload_df,
            schema_df=schema_df,
            selected_mapping={"owner": "Owner", "team": "Team"},
        )

        row = comparison_df.iloc[0]
        self.assertEqual(row["resolved_field_kind"], ResolvedFieldKind.USER_REFERENCE.value)
        self.assertTrue(row["is_supported"])
        self.assertTrue(row["requires_lookup"])
        self.assertEqual(row["lookup_target_kind"], LookupTargetKind.USER.value)
        self.assertEqual(row["preconstruction_kind"], PreconstructionKind.FIELD_VALUE.value)
        self.assertEqual(row["payload_target_kind"], PayloadTargetKind.CUSTOM_FIELD.value)

        team = comparison_df[comparison_df["df_column"] == "team"].iloc[0]
        self.assertEqual(team["resolved_field_kind"], ResolvedFieldKind.MEMBER_REFERENCE.value)
        self.assertEqual(team["lookup_target_kind"], LookupTargetKind.MEMBER.value)

    def test_build_option_maps_from_schema_distinguishes_field_resolution_states(self) -> None:
        """옵션 맵이 static option, user lookup, generic reference를 구분하는지 확인한다."""
        schema_df = self.service.flatten_schema_fields([
            {
                "id": 1,
                "name": "Phase",
                "type": "OptionChoiceField",
                "options": [{"id": 11, "name": "Draft"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
            {
                "id": 2,
                "name": "Owner",
                "type": "ReferenceField",
                "referenceType": "UserReference",
                "valueModel": "ChoiceFieldValue<UserReference>",
            },
            {
                "id": 3,
                "name": "Related Candidate",
                "type": "ReferenceField",
                "referenceType": "TrackerItemReference",
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            },
            {
                "id": 4,
                "name": "Choice Hint Only",
                "type": "OptionChoiceField",
                "valueModel": "ChoiceFieldValue<AbstractReference>",
            },
            {
                "id": 5,
                "name": "Related Items",
                "type": "TrackerItemChoiceField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            },
            {
                "id": 6,
                "name": "Team",
                "type": "MemberField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<AbstractReference>",
                "memberTypes": ["USER", "ROLE", "GROUP"],
            },
        ])

        option_maps = self.service.build_option_maps_from_schema(schema_df)

        self.assertEqual(option_maps["Phase"]["kind"], OptionMapKind.STATIC_OPTIONS.value)
        self.assertEqual(option_maps["Phase"]["source_status"], OptionSourceStatus.READY.value)

        self.assertEqual(option_maps["Owner"]["kind"], OptionMapKind.USER_LOOKUP.value)
        self.assertEqual(option_maps["Owner"]["source_status"], OptionSourceStatus.LOOKUP_REQUIRED.value)
        self.assertTrue(option_maps["Owner"]["resolver_available"])

        self.assertEqual(option_maps["Related Candidate"]["kind"], OptionMapKind.REFERENCE_LOOKUP.value)
        self.assertFalse(option_maps["Related Candidate"]["resolver_available"])
        self.assertIn("resolver", option_maps["Related Candidate"]["unsupported_reason"])

        self.assertEqual(option_maps["Related Items"]["kind"], OptionMapKind.TRACKER_ITEM_DIRECT.value)
        self.assertEqual(option_maps["Related Items"]["source_status"], OptionSourceStatus.READY.value)
        self.assertTrue(option_maps["Related Items"]["resolver_available"])

        self.assertEqual(option_maps["Team"]["kind"], OptionMapKind.MEMBER_LOOKUP.value)
        self.assertEqual(option_maps["Team"]["source_status"], OptionSourceStatus.LOOKUP_REQUIRED.value)
        self.assertEqual(option_maps["Team"]["lookup_target_kind"], LookupTargetKind.MEMBER.value)
        self.assertEqual(option_maps["Team"]["member_types"], ["USER", "ROLE", "GROUP"])

        self.assertEqual(option_maps["Choice Hint Only"]["kind"], OptionMapKind.UNSUPPORTED.value)
        self.assertEqual(option_maps["Choice Hint Only"]["source_status"], OptionSourceStatus.UNSUPPORTED.value)

    def test_check_option_alignment_surfaces_early_resolution_risks(self) -> None:
        """조기 검증 단계에서 차단 이슈와 정보성 상태가 모두 드러나는지 확인한다."""
        schema_df = self.service.flatten_schema_fields([
            {
                "id": 1,
                "name": "Phase",
                "type": "OptionChoiceField",
                "options": [{"id": 11, "name": "Draft"}],
                "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            },
            {
                "id": 2,
                "name": "Owner",
                "type": "ReferenceField",
                "referenceType": "UserReference",
                "valueModel": "ChoiceFieldValue<UserReference>",
            },
            {
                "id": 3,
                "name": "Related Candidate",
                "type": "ReferenceField",
                "referenceType": "TrackerItemReference",
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            },
            {
                "id": 4,
                "name": "Choice Hint Only",
                "type": "OptionChoiceField",
                "valueModel": "ChoiceFieldValue<AbstractReference>",
            },
            {
                "id": 5,
                "name": "Related Items",
                "type": "TrackerItemChoiceField",
                "multipleValues": True,
                "valueModel": "ChoiceFieldValue<TrackerItemReference>",
            },
        ])
        option_maps = self.service.build_option_maps_from_schema(schema_df)
        upload_df = pd.DataFrame([
            {
                "_row_id": 1,
                "phase": "Missing",
                "owner": "Jane Doe",
                "related": "REQ-1",
                "choice_hint": "Anything",
                "related_items": ["Item [REQ:20263671]", "broken"],
            }
        ])
        option_mapping = {
            "phase": "Phase",
            "owner": "Owner",
            "related": "Related Candidate",
            "choice_hint": "Choice Hint Only",
            "related_items": "Related Items",
        }

        result = self.service.check_option_alignment(upload_df, option_mapping, option_maps)
        statuses = set(result["status"].tolist())

        self.assertIn(OptionCheckStatus.PRECONSTRUCTION_REQUIRED.value, statuses)
        self.assertIn(OptionCheckStatus.OPTION_NOT_FOUND.value, statuses)
        self.assertIn(OptionCheckStatus.LOOKUP_REQUIRED.value, statuses)
        self.assertIn(OptionCheckStatus.DIRECT_PARSE_FAILED.value, statuses)
        self.assertIn(OptionCheckStatus.FIELD_UNSUPPORTED.value, statuses)
        self.assertIn(UserLookupStatus.USER_LOOKUP_NOT_RUN.value, statuses)


if __name__ == "__main__":
    unittest.main()
