"""todo.md 1절 스크립트가 서버 주소·이름·값 없이 한 화면에 결과를 찍는지 확인한다.

스크립트와 절을 지울 때 이 테스트도 함께 지운다.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from src.codebeamer_client import CodebeamerClient


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "todo_check_baseline_wiki_render.py"
_spec = importlib.util.spec_from_file_location("todo_check_baseline_wiki_render", SCRIPT)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

BASE_URL = "https://secret-host.test/secret-context/api"
OLD, NEW = b"secret old image", b"secret new image"
OLD_HASH, NEW_HASH = "a" * 32, "b" * 32
CONTENT = {"555009": OLD, "555001": NEW}


def source(artifact_id: str) -> str:
    return f"/secret-context/displayDocument/secret-diagram.png?task_id=900001&amp;artifact_id={artifact_id}"


class HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"{status} for url {BASE_URL}/secret-path")
        self.response = SimpleNamespace(status_code=status)


class FakeResponse:
    def __init__(self, status: int, text: str, content_type: str = "text/html; charset=UTF-8") -> None:
        self.status = status
        self.text = text
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise HttpError(self.status)


class FakeSession:
    status = 200

    def post(self, url: str, *, json: dict[str, Any], timeout: Any) -> FakeResponse:
        # 서버가 Baseline 버전 값으로 그 시점 첨부를 고른다고 가정한다.
        artifact_id = "555009" if json["contextVersion"] == 3 else "555001"
        return FakeResponse(self.status, f'<p>secret text</p><img alt="secret" src="{source(artifact_id)}">')


class FakeClient:
    session = FakeSession()
    _resource_monitor_path = staticmethod(CodebeamerClient._resource_monitor_path)

    def __init__(self, base_url: str, username: str, password: str, logger: Any = None) -> None:
        self.base_url = base_url
        self.downloaded: list[str] = []

    def _session(self) -> FakeSession:
        return self.session

    def _timeout(self, method: str) -> tuple[float, float]:
        return (1.0, 1.0)

    def get_tracker(self, tracker_id: int) -> dict[str, Any]:
        return {"id": tracker_id, "name": "secret tracker", "project": {"id": 333001}}

    def get_tracker_baselines(self, tracker_id: int) -> list[dict[str, Any]]:
        return [{"id": 777001, "name": "secret baseline"}, {"id": 777002, "name": "secret newer"}]

    def search_items(self, *, baseline_id: int | None = None, **kwargs: Any) -> dict[str, Any]:
        if baseline_id is None:
            return {"items": [
                {"id": 900001, "version": 5, "description": f"secret [!secret-diagram.png#{NEW_HASH}!]"},
                {"id": 900002, "version": 2, "description": "secret no image"},
            ]}
        return {"items": [
            {"id": 900001, "version": 3, "description": f"secret [!secret-diagram.png#{OLD_HASH}!]"},
            {"id": 900002, "version": 2, "description": "secret no image"},
        ]}

    def download_authenticated_resource(self, url: str, *, max_bytes: int) -> tuple[str, bytes]:
        return "image/png", CONTENT[url.rsplit("=", 1)[1]]


def run_script(*arguments: str, status: int = 200) -> str:
    settings = SimpleNamespace(base_url=BASE_URL, username="secret-user", password="secret-password")
    output = io.StringIO()
    with (
        patch("os.system"),
        patch("sys.argv", ["script", *arguments]),
        patch("src.gui.settings_store.GuiSettingsStore.load", return_value=settings),
        patch("src.codebeamer_client.CodebeamerClient", FakeClient),
        patch.object(FakeSession, "status", status),
        contextlib.redirect_stdout(output),
    ):
        script.main()
    return output.getvalue()


def assert_no_internal_values(test: unittest.TestCase, output: str) -> None:
    test.assertNotIn("secret", output)
    for value in ("123456", "777002", "333001", "900001", "555009", "555001", OLD_HASH, NEW_HASH):
        test.assertNotIn(value, output)
    test.assertLessEqual(len(output.splitlines()), 40)
    test.assertTrue(all(len(line) <= 120 for line in output.splitlines()))


class TodoCheckBaselineWikiRenderTest(unittest.TestCase):
    def test_baseline_render_gives_the_old_image(self) -> None:
        output = run_script("123456")

        assert_no_internal_values(self, output)
        self.assertIn("가장 최근 Baseline, 본문 그림 해시가 현재와 다른 아이템 1개 중 1개 확인", output)
        self.assertIn("[wiki2html] 성공 3회 (응답 html 3회)", output)
        self.assertIn("현재 본문 img 1개, Baseline 본문 img 1개, 그중 현재와 다른 주소 1개", output)
        self.assertIn("[주소 모양] /displayDocument/{name} ?artifact_id&task_id 1개", output)
        self.assertIn("같은 주소 0개 / 1개", output)
        self.assertIn("받음 1개, 현재 그림과 내용 다름 1개 (받기 2회)", output)
        self.assertIn("판정: 서버 렌더링으로 Baseline 당시 그림을 받을 수 있음 (Baseline 버전 값이 필요)", output)

    def test_server_without_wiki2html_is_reported(self) -> None:
        output = run_script("123456", "777001", status=404)

        assert_no_internal_values(self, output)
        self.assertIn("지정한 Baseline", output)
        self.assertIn("[wiki2html] 성공 0회, 실패: HTTP 404 2회", output)
        self.assertIn("판정: 이 서버에서 wiki2html을 쓸 수 없음", output)

    def test_source_shape_keeps_only_words(self) -> None:
        client = FakeClient(BASE_URL, "", "")
        data = "data:image/png;base64," + base64.b64encode(OLD).decode()

        self.assertEqual(
            "/v3/attachments/{x}/content ?version",
            script.source_shape(client, "/secret-context/api/v3/attachments/555001/content?version=2"),
        )
        self.assertEqual("data URI", script.source_shape(client, data))
        self.assertEqual(hashlib.md5(OLD).hexdigest(), script.Checker(client, 1).md5_of(data))

    def test_missing_tracker_id_is_explained(self) -> None:
        self.assertIn("실패: 트래커 ID 없음", run_script())


if __name__ == "__main__":
    unittest.main()
