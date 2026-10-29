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

import requests


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "todo_check_attachment_history.py"
_spec = importlib.util.spec_from_file_location("todo_check_attachment_history", SCRIPT)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

BASE_URL = "https://secret-host.test/secret-context"
OLD, NEW = b"secret old image", b"secret new image"


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class FakeClient:
    versions: dict[int, bytes] = {1: OLD, 2: NEW}
    fail_content = False

    def __init__(self, base_url: str, username: str, password: str, logger: Any = None) -> None:
        self.base_url = base_url

    def get_tracker_baselines(self, tracker_id: int) -> list[dict[str, Any]]:
        return [{"id": 777001, "name": "secret baseline", "createdAt": "2026-01-02T03:04:05.678"}]

    def search_items(self, **kwargs: Any) -> dict[str, Any]:
        return {"items": [{"id": 900001, "name": "secret item"}, {"id": 900002, "name": "secret other"}]}

    def get_item_attachments(self, item_id: int) -> list[dict[str, Any]]:
        if item_id == 900001:
            return []
        return [{"id": 555001, "name": "secret-diagram.png", "md5": md5(NEW), "version": 2}]

    def _get(self, path: str) -> dict[str, Any]:
        return {
            "page": 1,
            "attachments": [
                {
                    "id": 555001,
                    "name": "secret-diagram.png",
                    "version": version,
                    "md5": md5(data),
                    "modifiedAt": f"2026-0{version}-01T00:00:00.000",
                }
                for version, data in self.versions.items()
            ],
        }

    def download_authenticated_resource(self, url: str, *, max_bytes: int) -> tuple[str, bytes]:
        if self.fail_content:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(f"404 for {url}", response=response)
        return "image/png", self.versions[int(url.rsplit("=", 1)[1])]


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


class TodoCheckAttachmentHistoryTest(unittest.TestCase):
    def test_reports_history_shape_without_internal_values(self) -> None:
        output = run_script("123456")

        self.assertNotIn("secret", output)
        for value in ("123456", "777001", "900002", "555001", "2026"):
            self.assertNotIn(value, output)
        self.assertLessEqual(len(output.splitlines()), 40)
        self.assertIn("항목 키: createdAt, id, name", output)
        self.assertIn("시각 키: createdAt(9999-99-99T99:99:99.999)", output)
        self.assertIn("아이템 2개 중 첨부 있는 아이템 1개, 이력 조회 1회, 버전 2개 이상 첨부 1개", output)
        self.assertIn("최상위: 객체(attachments, page)", output)
        self.assertIn("항목 키: id, md5, modifiedAt, name, version", output)
        self.assertIn("버전 2개, version 값 서로 다름: 예, id 모두 같음: 예, md5 서로 다름: 예", output)
        self.assertIn("두 버전 내용 다름: 예", output)
        self.assertIn("받은 내용의 md5 = 이력의 md5: 예 (2개 비교)", output)

    def test_content_failure_shows_status_only(self) -> None:
        with patch.object(FakeClient, "fail_content", True):
            output = run_script("123456", "900002")

        self.assertNotIn("secret", output)
        self.assertIn("첫 버전: HTTP 404", output)
        self.assertIn("마지막 버전: HTTP 404", output)

    def test_missing_tracker_id_is_explained(self) -> None:
        self.assertIn("실패: 트래커 ID 없음", run_script())


if __name__ == "__main__":
    unittest.main()
