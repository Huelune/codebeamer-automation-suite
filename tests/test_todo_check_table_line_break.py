"""todo.md 3절 스크립트가 서버 주소·ID·칸 값 없이 개수만 한 화면에 찍는지 확인한다.

스크립트와 절을 지울 때 이 테스트도 함께 지운다.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "todo_check_table_line_break.py"
_spec = importlib.util.spec_from_file_location("todo_check_table_line_break", SCRIPT)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

BASE_URL = "https://secret-host.test/secret-context/api"


def table_item(*cells: str) -> dict[str, Any]:
    return {
        "id": 900001,
        "name": "secret item",
        "description": "secret line_x000D_\nsecret next",
        "customFields": [
            {"fieldId": 1000, "name": "secret table", "type": "TextFieldValue", "value": "secret\\\\text"},
            {
                "fieldId": 1001,
                "name": "secret table",
                "type": "TableFieldValue",
                "values": [[{"fieldId": 1002, "name": "secret column", "value": cell} for cell in cells]],
            },
        ],
    }


class HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"{status} for url {BASE_URL}/secret-path")
        self.response = SimpleNamespace(status_code=status)


class FakeClient:
    items: dict[int, dict[str, Any]] = {}

    def __init__(self, base_url: str, username: str, password: str, logger: Any = None) -> None:
        del base_url, username, password, logger

    def get_item(self, item_id: int) -> dict[str, Any]:
        if item_id not in self.items:
            raise HttpError(404)
        return self.items[item_id]


class TodoCheckTableLineBreakTest(unittest.TestCase):
    def run_script(self, *arguments: str) -> str:
        settings = SimpleNamespace(base_url=BASE_URL, username="secret-user", password="secret-password")
        output = io.StringIO()
        with (
            patch("src.gui.settings_store.GuiSettingsStore.load", return_value=settings),
            patch("src.codebeamer_client.CodebeamerClient", FakeClient),
            patch.object(script.os, "system"),
            patch.object(script.sys, "argv", ["script", *arguments]),
            contextlib.redirect_stdout(output),
        ):
            script.main()
        return output.getvalue()

    def assert_safe(self, text: str) -> None:
        self.assertNotIn("secret", text)
        self.assertNotIn("900001", text)
        self.assertNotIn("555", text)
        self.assertLessEqual(len(text.splitlines()), 40)
        self.assertLessEqual(max(len(line) for line in text.splitlines()), 120)

    def test_wiki_break_in_table_cell_is_reported_as_counts_only(self) -> None:
        FakeClient.items = {555001: table_item("secret a\\\\\nsecret b", "secret c", "")}

        text = self.run_script("555001")

        self.assert_safe(text)
        self.assertIn("표 칸 3개(글자 2개): LF 1, CR 0, \\\\ 1, <br> 0, _x000D_ 0", text)
        self.assertIn("설명(있음): LF 1, CR 0, \\\\ 0, <br> 0, _x000D_ 1", text)
        self.assertIn("판정: 표 칸 줄바꿈이 `\\\\`로 저장됨", text)

    def test_plain_line_feed_and_failed_item_are_reported(self) -> None:
        FakeClient.items = {555001: table_item("secret a\nsecret b")}

        text = self.run_script("555001", "555002")

        self.assert_safe(text)
        self.assertIn("[아이템 2] 실패: 조회 실패(HTTP 404)", text)
        self.assertIn("판정: 표 칸에 LF가 그대로 저장됨", text)

    def test_missing_item_id_asks_for_one(self) -> None:
        text = self.run_script()

        self.assert_safe(text)
        self.assertIn("실패: 아이템 ID 없음", text)


if __name__ == "__main__":
    unittest.main()
