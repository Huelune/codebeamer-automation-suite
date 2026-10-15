from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from src.api_monitor import ApiMonitorService
from src.codebeamer_client import CodebeamerClient
from src.diagnostics import DiagnosticService
from src.diagnostics import export_diagnostic_bundle


class FakeResponse:
    def __init__(self, *, headers=None, chunks=(), status_code=200) -> None:
        self.headers = dict(headers or {})
        self._chunks = tuple(chunks)
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = RuntimeError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class AttachmentDownloadTest(unittest.TestCase):
    def client(self, session: FakeSession, monitor=None) -> CodebeamerClient:
        client = CodebeamerClient(
            "https://example.test/cb",
            "sample",
            "placeholder",
            rate_limit_max_retries=0,
            api_monitor=monitor or ApiMonitorService(),
        )
        client._session = lambda: session
        return client

    def test_streamed_download_checks_actual_received_size(self) -> None:
        response = FakeResponse(
            headers={"Content-Type": "image/png"},
            chunks=(b"1234", b"5678"),
        )

        with self.assertRaisesRegex(ValueError, "허용 크기"):
            self.client(FakeSession([response])).download_authenticated_resource(
                "/cb/attachment/28",
                max_bytes=7,
            )

        self.assertTrue(response.closed)

    def test_content_length_is_rejected_before_body_is_collected(self) -> None:
        response = FakeResponse(
            headers={"Content-Type": "image/png", "Content-Length": "100"},
            chunks=(b"small",),
        )

        with self.assertRaisesRegex(ValueError, "허용 크기"):
            self.client(FakeSession([response])).download_authenticated_resource(
                "/cb/attachment/28",
                max_bytes=10,
            )

    def test_external_url_is_rejected_without_request(self) -> None:
        session = FakeSession([])

        with self.assertRaisesRegex(ValueError, "다른 서버"):
            self.client(session).download_authenticated_resource(
                "https://outside.test/attachment/28",
                max_bytes=10,
            )

        self.assertEqual(session.calls, [])

    def test_monitor_path_does_not_store_attachment_query(self) -> None:
        monitor = ApiMonitorService()
        monitor.configure(enabled=True)
        session = FakeSession(
            [FakeResponse(headers={"Content-Type": "image/png"}, chunks=(b"ok",))]
        )

        self.client(session, monitor).download_authenticated_resource(
            "/cb/displayDocument/sample.png?task_id=1001&artifact_id=28",
            max_bytes=10,
        )

        event = monitor.snapshot().events[-1]
        self.assertNotIn("task_id", event.path)
        self.assertNotIn("artifact_id", event.path)

    def test_monitor_hides_server_context_path_and_document_names(self) -> None:
        """다운로드 경로에는 서버 context 경로와 첨부 파일 이름이 들어 있다. API 모니터와 진단 파일에 남기지 않는다."""
        cases = {
            "/secret-context/displayDocument/secret-plan.png?task_id=1001": "/displayDocument/{name}",
            "/secret-context/v3/attachments/4392/content": "/v3/attachments/{id}/content",
            "/secret-context/secret-folder/attachment-view": "/{resource}",
        }
        for source_url, expected in cases.items():
            with self.subTest(source_url=source_url):
                monitor = ApiMonitorService()
                monitor.configure(enabled=True)
                session = FakeSession([FakeResponse(headers={"Content-Type": "image/png"}, chunks=(b"ok",))])
                client = CodebeamerClient(
                    "https://example.test/secret-context",
                    "sample",
                    "placeholder",
                    rate_limit_max_retries=0,
                    api_monitor=monitor,
                )
                client._session = lambda session=session: session

                client.download_authenticated_resource(source_url, max_bytes=10)

                event = monitor.snapshot().events[-1]
                self.assertEqual(event.path, expected)
                self.assertNotIn("secret", f"{event.request_kind} {event.path}")

    def test_diagnostic_bundle_has_no_download_path_names(self) -> None:
        monitor = ApiMonitorService()
        monitor.configure(enabled=True)
        session = FakeSession([FakeResponse(headers={"Content-Type": "image/png"}, chunks=(b"ok",))])
        client = CodebeamerClient(
            "https://example.test/secret-context",
            "sample",
            "placeholder",
            rate_limit_max_retries=0,
            api_monitor=monitor,
        )
        client._session = lambda: session
        client.download_authenticated_resource("/secret-context/displayDocument/secret-plan.png", max_bytes=10)

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "diagnostics.zip"
            export_diagnostic_bundle(
                target,
                diagnostics_snapshot=DiagnosticService().snapshot(),
                api_events=monitor.snapshot().events,
            )
            with zipfile.ZipFile(target) as archive:
                bundle_text = b"\n".join(archive.read(name) for name in archive.namelist()).decode("utf-8")

        self.assertIn("/displayDocument/{name}", bundle_text)
        self.assertNotIn("secret", bundle_text)

    def test_attachment_id_download_uses_v3_content_endpoint(self) -> None:
        session = FakeSession(
            [FakeResponse(headers={"Content-Type": "application/pdf"}, chunks=(b"pdf",))]
        )

        mime_type, content = self.client(session).download_attachment_content(
            4392,
            max_bytes=10,
        )

        self.assertEqual(mime_type, "application/pdf")
        self.assertEqual(content, b"pdf")
        self.assertEqual(session.calls[0][0], "https://example.test/cb/v3/attachments/4392/content")
        # 첨부를 받다가 서버가 멈춰도 무한히 기다리지 않는다.
        self.assertEqual(session.calls[0][1]["timeout"], (10.0, 120.0))


if __name__ == "__main__":
    unittest.main()
