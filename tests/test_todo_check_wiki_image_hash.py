"""todo.md 1절 스크립트가 서버 주소·이름·값 없이 한 화면에 결과를 찍는지 확인한다.

스크립트와 절을 지울 때 이 테스트도 함께 지운다.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "todo_check_wiki_image_hash.py"
_spec = importlib.util.spec_from_file_location("todo_check_wiki_image_hash", SCRIPT)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

BASE_URL = "https://secret-host.test/secret-context"
OLD, NEW, OTHER = b"secret old image", b"secret new image", b"secret other image"


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def description(data: bytes) -> str:
    return f"secret text [!secret-diagram.png#{md5(data).upper()}!]"


class FakeClient:
    def __init__(self, base_url: str, username: str, password: str, logger: Any = None) -> None:
        self.base_url = base_url

    def search_items(self, *, baseline_id: int | None = None, **kwargs: Any) -> dict[str, Any]:
        if baseline_id is None:
            return {"items": [
                {"id": 900001, "description": description(NEW)},
                {"id": 900002, "description": "secret no image"},
                {"id": 900003, "description": "[!secret-missing.png#0123456789abcdef0123456789abcdef!]"},
            ]}
        return {"items": [{"id": 900001, "description": description(OLD)}]}

    def get_tracker_baselines(self, tracker_id: int) -> list[dict[str, Any]]:
        return [{"id": 777001, "name": "secret baseline"}, {"id": 777002, "name": "secret newer"}]

    def get_item_attachments(self, item_id: int) -> list[dict[str, Any]]:
        if item_id != 900001:
            return []
        return [{"id": 555001, "name": "secret-diagram.png", "version": 3}]

    def _get(self, path: str, params: Any = None) -> dict[str, Any]:
        return {"page": 1, "revisions": [{"version": 1}, {"version": 2}, {"version": 3}]}

    def download_authenticated_resource(self, url: str, *, max_bytes: int) -> tuple[str, bytes]:
        version = url.rsplit("=", 1)[1] if "version=" in url else "3"
        return "image/png", {"1": OLD, "2": OTHER, "3": NEW}[version]


def run_script(*arguments: str) -> str:
    settings = SimpleNamespace(base_url=BASE_URL, username="secret-user", password="secret-password")
    output = io.StringIO()
    with (
        patch("os.system"),
        patch("sys.argv", ["script", *arguments]),
        patch("src.gui.settings_store.GuiSettingsStore.load", return_value=settings),
        patch("src.codebeamer_client.CodebeamerClient", FakeClient),
        contextlib.redirect_stdout(output),
    ):
        script.main()
    return output.getvalue()


class TodoCheckWikiImageHashTest(unittest.TestCase):
    def test_reports_hash_matches_without_internal_values(self) -> None:
        output = run_script("123456")

        self.assertNotIn("secret", output)
        for value in ("123456", "777002", "900001", "555001", md5(NEW)[:8], md5(OLD)[:8]):
            self.assertNotIn(value, output)
        self.assertLessEqual(len(output.splitlines()), 40)
        self.assertIn("아이템 3개 중 본문 그림 있는 아이템 2개, 해시 붙은 그림 자리 2개", output)
        self.assertIn("같은 이름 첨부 없음 1개, 이름 겹침 0개, 내용 md5 = 해시 1개, 다름 0개", output)
        self.assertIn("판정: 본문 해시는 첨부 내용의 md5", output)
        self.assertIn("가장 최근 Baseline, 현재와 해시가 다른 그림 자리 1개 (아이템 1개)", output)
        self.assertIn("이력에서 찾음: 최신 버전 0개, 이전 버전 1개", output)
        self.assertIn("판정: Baseline 그림을 이전 버전에서 찾을 수 있음", output)
        self.assertIn("[요청] 이력 조회 1회, 내용 받기 4회", output)

    def test_missing_tracker_id_is_explained(self) -> None:
        self.assertIn("실패: 트래커 ID 없음", run_script())


if __name__ == "__main__":
    unittest.main()
