from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

from scripts.inspect_item_activity_contract import MAX_LINES
from scripts.inspect_item_activity_contract import REPORT_NAME
from scripts.inspect_item_activity_contract import WIDTH
from scripts.inspect_item_activity_contract import failure_text
from scripts.inspect_item_activity_contract import main
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

    def test_malformed_server_address_points_to_the_address_format(self) -> None:
        for exc in (
            requests.exceptions.MissingSchema("secret address"),
            requests.exceptions.InvalidSchema("secret address"),
            requests.exceptions.InvalidURL("secret address"),
        ):
            text = failure_text(exc)
            self.assertEqual(text, "서버 주소 형식 확인 · https:// 포함해 다시 실행")
            self.assertNotIn("secret", text)


class FakeClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.args = (base_url, username, password)

    def get_item_history(self, item_id: int) -> object:
        return HISTORY

    def get_item_comments(self, item_id: int) -> object:
        return COMMENTS

    def get_item_attachments(self, item_id: int) -> object:
        return ATTACHMENTS

    def get_item_relations(self, item_id: int) -> object:
        return RELATIONS


def _http_error(status: int) -> requests.HTTPError:
    error = requests.HTTPError("secret path /items/1")
    error.response = SimpleNamespace(status_code=status)
    return error


class InspectMainTest(unittest.TestCase):
    """main()을 터미널과 서버 없이 돌려 화면에 찍히는 내용만 본다."""

    def run_main(self, inputs: list[object], *, tmp: str, client_cls: type = FakeClient) -> tuple[int, str]:
        output = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=inputs),
            mock.patch("getpass.getpass", return_value="pw"),
            mock.patch("os.system", return_value=0),
            mock.patch("src.codebeamer_client.CodebeamerClient", client_cls),
            mock.patch("tempfile.gettempdir", return_value=tmp),
            contextlib.redirect_stdout(output),
        ):
            status = main()
        return status, output.getvalue()

    def assert_safe_screen(self, text: str) -> None:
        self.assertNotIn("secret", text)
        self.assertNotIn(":\\", text)
        self.assertLessEqual(len(text.splitlines()), MAX_LINES)

    def test_success_prints_summary_and_footer_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, text = self.run_main(["http://example.test", "user", "1"], tmp=tmp)
            report_exists = (Path(tmp) / REPORT_NAME).exists()

        self.assertEqual(status, 0)
        self.assertTrue(report_exists)
        self.assertIn("[변경 이력] 버전 1건 · 변경 2건", text)
        self.assertIn("전체 응답: %TEMP%", text)
        self.assert_safe_screen(text)

    def test_non_ascii_digit_item_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, text = self.run_main(["http://example.test", "user", "²"], tmp=tmp)

        self.assertNotEqual(status, 0)
        self.assertIn("아이템 ID는 숫자여야 합니다", text)
        self.assert_safe_screen(text)

    def test_report_write_failure_keeps_summary_and_prints_fixed_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_folder = str(Path(tmp) / "missing" / "nested")
            status, text = self.run_main(["http://example.test", "user", "1"], tmp=missing_folder)

        self.assertNotEqual(status, 0)
        self.assertIn("[변경 이력] 버전 1건", text)
        self.assertIn("전체 응답 파일 쓰기 실패 · 임시 폴더 쓰기 권한 확인", text)
        self.assertNotIn("전체 응답: %TEMP%", text)
        self.assertNotIn("Traceback", text)
        self.assert_safe_screen(text)

    def test_cancelled_input_prints_cancel_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for cancel in (KeyboardInterrupt(), EOFError()):
                with self.subTest(error=type(cancel).__name__):
                    status, text = self.run_main([cancel], tmp=tmp)

                    self.assertNotEqual(status, 0)
                    self.assertEqual(text.strip(), "입력을 취소했습니다. 다시 실행하세요.")
                    self.assert_safe_screen(text)

    def test_http_failure_for_one_api_shows_status_only(self) -> None:
        class ForbiddenHistoryClient(FakeClient):
            def get_item_history(self, item_id: int) -> object:
                raise _http_error(403)

        with tempfile.TemporaryDirectory() as tmp:
            status, text = self.run_main(
                ["http://example.test", "user", "1"], tmp=tmp, client_cls=ForbiddenHistoryClient
            )

        self.assertEqual(status, 0)
        self.assertIn("[조회 실패]", text)
        self.assertIn("HTTP 403", text)
        self.assertIn("전체 응답: %TEMP%", text)
        self.assert_safe_screen(text)

    def test_unexpected_error_prints_fixed_line_without_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status, text = self.run_main([RuntimeError("secret C:\\Users\\x")], tmp=tmp)

        self.assertNotEqual(status, 0)
        self.assertEqual(text.strip(), "예상하지 못한 오류 · 다시 실행하고, 반복되면 이 화면만 알려 주세요.")
        self.assert_safe_screen(text)


if __name__ == "__main__":
    unittest.main()
