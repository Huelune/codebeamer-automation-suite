from __future__ import annotations

import unittest
from types import SimpleNamespace

import requests

from scripts.inspect_item_activity_contract import MAX_LINES
from scripts.inspect_item_activity_contract import WIDTH
from scripts.inspect_item_activity_contract import failure_text
from scripts.inspect_item_activity_contract import summarize_contract


HISTORY = {
    "versions": [
        {
            "itemRevision": {"version": 2, "name": "secret item name"},
            "modifiedAt": "2026-07-20T09:00:00Z",
            "modifiedBy": {"name": "secret-user"},
            "changes": [
                {
                    "type": "TrackerItemChange",
                    "field": {"id": 1, "name": "secret field", "type": "FieldReference"},
                    "name": "secret field",
                    "oldValue": {"value": "secret old", "type": "TextFieldValue"},
                    "newValue": {"value": "secret new", "type": "TextFieldValue"},
                },
                {"type": "secret type with spaces", "name": "secret comment"},
            ],
        }
    ],
    "secret key with spaces": 1,
}
COMMENTS = [{"id": 1, "comment": "secret body", "createdBy": {"name": "secret-user"}, "createdAt": "2026-07-20"}]
ATTACHMENTS = [{"id": 2, "name": "secret-file.txt", "modifiedAt": "2026-07-18", "createdBy": {"name": "secret-user"}}]
RELATIONS = {
    "downstreamReferences": [{"id": "secret-relation", "type": "OutgoingTrackerItemAssociation",
                              "itemRevision": {"name": "secret target"}}],
    "upstreamReferences": [],
}


class InspectItemActivityContractTest(unittest.TestCase):
    def test_report_lists_only_schema_names_and_counts(self) -> None:
        lines = summarize_contract(HISTORY, COMMENTS, ATTACHMENTS, RELATIONS)
        text = "\n".join(lines)

        self.assertNotIn("secret", text)
        self.assertLessEqual(len(lines), MAX_LINES)
        self.assertTrue(all(len(line) <= WIDTH for line in lines))
        self.assertIn("[변경 이력] 버전 1건 · 변경 2건", text)
        self.assertIn("응답 키: versions (기타 1개)", text)
        self.assertIn("변경 type 값: TrackerItemChange (기타 1개)", text)
        self.assertIn("field 없는 변경: 1건", text)
        self.assertIn("[댓글] 1건", text)
        self.assertIn("[첨부] 1건", text)
        self.assertIn("createdAt 0 · createdBy 1 · modifiedAt 1 · modifiedBy 0", text)
        self.assertIn("[관계] 그룹 2개 · 항목 1건", text)
        self.assertIn("관계 type 값: OutgoingTrackerItemAssociation", text)

    def test_missing_responses_are_reported_as_empty(self) -> None:
        lines = summarize_contract(None, None, None, None)

        self.assertIn("[변경 이력] 버전 0건 · 변경 0건", lines)
        self.assertIn("[관계] 그룹 0개 · 항목 0건", lines)

    def test_failures_show_kind_and_action_without_the_message(self) -> None:
        http_error = requests.HTTPError("secret path /items/1")
        http_error.response = SimpleNamespace(status_code=403)
        server_error = requests.HTTPError("secret")
        server_error.response = SimpleNamespace(status_code=500)

        self.assertEqual(failure_text(http_error), "HTTP 403 권한 없음 · 아이템을 볼 수 있는 계정으로 다시 실행")
        self.assertEqual(failure_text(server_error), "HTTP 500 서버 오류 · 잠시 뒤 다시 실행")
        self.assertEqual(
            failure_text(requests.ConnectionError("secret host")), "연결 실패 · 서버 주소와 네트워크 확인"
        )
        self.assertEqual(failure_text(ValueError("secret")), "ValueError · 응답 형식 확인 필요")


if __name__ == "__main__":
    unittest.main()
