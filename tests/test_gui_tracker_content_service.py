from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_content_models import WikiRenderContext
from src.gui.tracker_content_service import TrackerContentService
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


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


    def test_saved_attachment_is_not_kept_in_memory(self) -> None:
        """저장은 최대 1GB까지 받는다. 받은 내용을 캐시에 남기지 않고, 다시 저장하면 다시 받는다."""
        attachment = AttachmentSummary(28, "sample.png")
        with TemporaryDirectory() as directory:
            target = Path(directory) / "sample.png"
            self.service.save_attachment(settings(), attachment, str(target))
            self.service.save_attachment(settings(), attachment, str(target))

        downloads = [call for client in FakeContentClient.instances for call in client.download_calls]
        self.assertEqual(len(downloads), 2)
        self.assertEqual(self.service.cached_resource_bytes(), 0)

    def test_image_cache_keeps_recent_images_within_byte_budget(self) -> None:
        service = TrackerContentService(client_factory=FakeContentClient, resource_cache_bytes=25)

        def download(key: str) -> None:
            service.download_resource(settings(), resource_key=key, source_url=f"/cb/attachment/{key}")

        for key in ("a", "b", "c"):  # 10바이트씩, 예산 25바이트
            download(key)
        download("c")
        download("a")

        downloads = [call for client in FakeContentClient.instances for call in client.download_calls]
        # c 는 남아 있어 다시 받지 않고, 가장 오래된 a 는 밀려나 다시 받는다.
        self.assertEqual([url for url, _limit in downloads], [f"/cb/attachment/{key}" for key in "abca"])
        self.assertLessEqual(service.cached_resource_bytes(), 25)

    def test_failed_server_render_is_not_cached(self) -> None:
        """서버 렌더링이 한 번 실패해도 다음에 다시 서버로 그린다. 대체 결과를 계속 쓰지 않는다."""
        attempts: list[int] = []

        class FlakyClient(FakeContentClient):
            def render_wiki_to_html(self, project_id: int, **kwargs) -> str:
                attempts.append(project_id)
                if len(attempts) == 1:
                    raise ConnectionError("temporary")
                return super().render_wiki_to_html(project_id, **kwargs)

        service = TrackerContentService(client_factory=FlakyClient)

        first = service.render_wiki(settings(), self.context, "text")
        second = service.render_wiki(settings(), self.context, "text")

        self.assertTrue(first.used_fallback)
        self.assertFalse(second.used_fallback)
        self.assertIn("서버 표", second.html)
        self.assertEqual(len(attempts), 2)

    def test_cleared_render_cache_is_not_refilled_by_a_late_result(self) -> None:
        """상세 새로고침으로 비운 뒤 늦게 끝난 렌더링이 옛 결과를 다시 넣지 않는다."""
        entered = threading.Event()
        release = threading.Event()

        class SlowClient(FakeContentClient):
            def render_wiki_to_html(self, project_id: int, **kwargs) -> str:
                entered.set()
                release.wait(5)
                return super().render_wiki_to_html(project_id, **kwargs)

        service = TrackerContentService(client_factory=SlowClient)
        worker = threading.Thread(target=lambda: service.render_wiki(settings(), self.context, "text"))
        worker.start()
        self.assertTrue(entered.wait(5))
        service.clear_item_cache(settings(), 1001)
        release.set()
        worker.join(5)
        renders_before = sum(len(client.render_calls) for client in SlowClient.instances)

        service.render_wiki(settings(), self.context, "text")

        renders_after = sum(len(client.render_calls) for client in SlowClient.instances)
        self.assertEqual(renders_after, renders_before + 1)


if __name__ == "__main__":
    unittest.main()
