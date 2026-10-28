"""todo.md 1절 스크립트가 서버 주소·계정 없이 한 화면에 결과를 찍는지 확인한다.

스크립트와 절을 지울 때 이 테스트도 함께 지운다.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "todo_check_baseline_attachments.py"
_spec = importlib.util.spec_from_file_location("todo_check_baseline_attachments", SCRIPT)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

BASE_URL = "https://secret-host.test/secret-context"
SPEC = {
    "openapi": "3.0.1",
    "paths": {
        "/v3/items/{itemId}": {
            "get": {"parameters": [{"name": "itemId"}, {"name": "baselineId"}]},
        },
        "/v3/items/{itemId}/attachments": {
            "parameters": [{"$ref": "#/components/parameters/ItemId"}],
            "get": {"parameters": [{"name": "page"}, {"name": "pageSize"}]},
            "post": {"parameters": [{"name": "secretWriteOnly"}]},
        },
        "/v3/attachments/{attachmentId}/content": {
            "get": {"parameters": [{"name": "attachmentId"}, {"name": "version"}]},
        },
        "/v3/trackers/{trackerId}": {"get": {"parameters": [{"name": "secretUnrelated"}]}},
    },
    "components": {
        "parameters": {"ItemId": {"name": "itemId", "in": "path"}},
        "schemas": {
            "AttachmentReference": {"properties": {"id": {}, "version": {}}},
            "Attachment": {"allOf": [{"$ref": "#/components/schemas/AttachmentReference"}]},
        },
    },
}


class FakeResponse:
    def __init__(self, status_code: int, payload: object = None, text: str = "") -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str, timeout: object = None) -> FakeResponse:
        self.requested.append(url)
        return self.responses.get(url, FakeResponse(404))


def run_script(session: FakeSession) -> str:
    settings = SimpleNamespace(base_url=BASE_URL, username="secret-user", password="secret-password")
    output = io.StringIO()
    with (
        patch("os.system"),
        patch("src.gui.settings_store.GuiSettingsStore.load", return_value=settings),
        patch("src.codebeamer_client.CodebeamerClient._session", return_value=session),
        contextlib.redirect_stdout(output),
    ):
        script.main()
    return output.getvalue()


class TodoCheckBaselineAttachmentsTest(unittest.TestCase):
    def test_reports_attachment_parameters_without_internal_values(self) -> None:
        page = FakeResponse(200, text='<script>url: "/secret-context/v3/swagger/secret-spec.json"</script>')
        session = FakeSession({
            f"{BASE_URL}/v3/swagger/editor.spr": page,
            "https://secret-host.test/secret-context/v3/swagger/secret-spec.json": FakeResponse(200, SPEC),
            "https://other.test/x.json": FakeResponse(200, SPEC),
        })

        output = run_script(session)

        self.assertNotIn("secret", output)
        self.assertLessEqual(len(output.splitlines()), 40)
        self.assertIn("GET /v3/items/{itemId}  [itemId, *baselineId]", output)
        self.assertIn("GET /v3/items/{itemId}/attachments  [itemId, page, pageSize]", output)
        self.assertIn("GET /v3/attachments/{attachmentId}/content  [attachmentId, *version]", output)
        self.assertIn("AttachmentReference: version", output)
        self.assertIn("Attachment: version", output)

    def test_missing_spec_reports_kinds_only(self) -> None:
        output = run_script(FakeSession({}))

        self.assertNotIn("secret", output)
        self.assertIn("실패: Swagger 명세를 찾지 못함", output)
        self.assertIn("HTTP 404", output)

    def test_spec_on_another_server_is_not_requested(self) -> None:
        page = FakeResponse(200, text='"https://other.test/x.json"')
        session = FakeSession({f"{BASE_URL}/v3/swagger/editor.spr": page})

        run_script(session)

        self.assertTrue(all(url.startswith(BASE_URL) for url in session.requested))


if __name__ == "__main__":
    unittest.main()
