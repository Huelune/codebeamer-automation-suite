from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_content_models import WikiRenderContext
from src.gui.tracker_content_service import TrackerContentService


class FakeContentClient:
    instances: list[FakeContentClient] = []

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        self.render_calls: list[dict] = []
        self.download_calls: list[tuple[str, int]] = []
        self.__class__.instances.append(self)

    def render_wiki_to_html(self, project_id: int, **kwargs) -> str:
        self.render_calls.append({"project_id": project_id, **kwargs})
        return (
            '<table><tr><td>서버 표</td></tr></table>'
            '<img src="/cb/attachment/28">'
        )

    def get_item_attachments(self, item_id: int):
        return {
            "attachments": [
                {
                    "id": 28,
                    "name": "sample.png",
                    "version": 2,
                    "size": 12,
                    "mimeType": "image/png",
                    "modifiedAt": "2026-08-13T10:00:00Z",
                    "uri": "/attachment/28",
                }
            ]
        }

    def download_authenticated_resource(self, source_url: str, *, max_bytes: int):
        self.download_calls.append((source_url, max_bytes))
        return "image/png", b"safe-bytes"

    def download_attachment_content(self, attachment_id: int, *, max_bytes: int):
        self.download_calls.append((f"/v3/attachments/{attachment_id}/content", max_bytes))
        return "image/png", b"safe-bytes"


def settings():
    return SimpleNamespace(
        offline_mode=False,
        server_wiki_html_enabled=True,
        base_url="https://example.test/cb",
        username="sample",
        password="placeholder",
        offline_query_data_path="",
        rate_limit_retry_delay_seconds=0,
        rate_limit_max_retries=0,
    )


class TrackerContentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeContentClient.instances.clear()
        self.service = TrackerContentService(client_factory=FakeContentClient)
        self.context = WikiRenderContext(10, 1001, 7)

    def test_render_uses_versioned_context_and_cache(self) -> None:
        first = self.service.render_wiki(settings(), self.context, "|| 이름 || 상태")
        second = self.service.render_wiki(settings(), self.context, "|| 이름 || 상태")

        self.assertEqual(first, second)
        self.assertIn("서버 표", first.html)
        self.assertEqual(len(first.resources), 1)
        self.assertEqual(len(FakeContentClient.instances), 1)
        self.assertEqual(FakeContentClient.instances[0].render_calls[0]["context_version"], 7)

    def test_render_does_not_call_server_when_html_rendering_is_disabled(self) -> None:
        disabled = settings()
        disabled.server_wiki_html_enabled = False

        result = self.service.render_wiki(disabled, self.context, "|| 이름 || 상태")

        self.assertTrue(result.used_fallback)
        self.assertIn("<table", result.html)
        self.assertEqual(FakeContentClient.instances, [])

    def test_baseline_cache_is_separate_and_blocks_unverified_images(self) -> None:
        current = self.service.render_wiki(settings(), self.context, "image")
        historical = self.service.render_wiki(
            settings(),
            WikiRenderContext(10, 1001, 7, baseline_id=44),
            "image",
        )

        self.assertEqual(len(current.resources), 1)
        self.assertEqual(historical.resources, ())
        self.assertIn("Baseline", historical.warning)
        self.assertEqual(len(FakeContentClient.instances), 2)

    def test_attachment_list_is_normalized_and_cached(self) -> None:
        first = self.service.load_attachments(settings(), 1001)
        second = self.service.load_attachments(settings(), 1001)

        self.assertEqual(first, second)
        self.assertEqual(first[0].attachment_id, 28)
        self.assertEqual(first[0].name, "sample.png")
        self.assertEqual(len(FakeContentClient.instances), 1)

    def test_save_attachment_replaces_target_after_complete_download(self) -> None:
        attachment = AttachmentSummary(28, "sample.png")
        with TemporaryDirectory() as directory:
            target = Path(directory) / "sample.png"
            target.write_bytes(b"old")

            size = self.service.save_attachment(settings(), attachment, str(target))

            self.assertEqual(size, len(b"safe-bytes"))
            self.assertEqual(target.read_bytes(), b"safe-bytes")
            self.assertEqual(list(target.parent.glob("*.tmp")), [])
            self.assertEqual(
                FakeContentClient.instances[0].download_calls,
                [("/v3/attachments/28/content", 1024 * 1024 * 1024)],
            )


if __name__ == "__main__":
    unittest.main()
