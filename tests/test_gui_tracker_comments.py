from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass

from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_comment_service import TrackerCommentService
from src.gui.tracker_query_models import TrackerQueryServiceError
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


@dataclass


class Settings:
    offline_mode: bool = False
    base_url: str = "https://example.test/cb"
    username: str = "sample"
    password: str = "placeholder"
    offline_query_data_path: str = ""
    rate_limit_retry_delay_seconds: float = 0.0
    rate_limit_max_retries: int = 0


class Client:
    calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def get_item_comments(self, item_id: int):
        self.__class__.calls += 1
        return [
            {
                "id": "3",
                "createdBy": {"displayName": "Other User"},
                "createdAt": "2026-01-01T12:00:00Z",
                "comment": "Other thread",
            },
            {
                "id": "2",
                "replyTo": {"id": "1"},
                "createdBy": {"displayName": "Reply User"},
                "createdAt": "2026-01-02T00:00:00Z",
                "commentFormat": "PlainText",
                "comment": "Reply",
                "attachments": [{"id": 28, "name": "evidence.png", "mimeType": "image/png"}],
            },
            {
                "id": 1,
                "createdBy": {"name": "Author"},
                "createdAt": "2026-01-01T00:00:00Z",
                "commentFormat": "Wiki",
                "comment": "|| Key || Value ||",
            },
        ]


class _ServerError(Exception):
    """서버 500. 예외 문구에 서버 주소가 들어 있다."""

    def __init__(self) -> None:
        self.response = type("Response", (), {"status_code": 500})()
        super().__init__("500 Server Error: Internal for url: https://secret-host.example.invalid/cb/api/v3/items/1")


class TrackerCommentModelsTest(unittest.TestCase):
    def test_comments_are_normalized_and_sorted_with_reply_and_attachments(self) -> None:
        snapshot = ItemCommentsSnapshot.from_raw(Client().get_item_comments(1205))

        self.assertEqual([comment.comment_id for comment in snapshot.comments], ["1", "2", "3"])
        reply = snapshot.comments[1]
        self.assertEqual(reply.reply_to_id, "1")
        self.assertEqual(reply.author, "Reply User")
        self.assertEqual(reply.attachments[0].attachment_id, 28)


class TrackerCommentServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        Client.calls = 0
        self.settings = Settings()
        self.service = TrackerCommentService(client_factory=Client)

    def test_comments_are_cached_by_item_version(self) -> None:
        first = self.service.load_comments(self.settings, 1205, 3)
        second = self.service.load_comments(self.settings, 1205, 3)

        self.assertIs(first, second)
        self.assertEqual(Client.calls, 1)
        self.service.load_comments(self.settings, 1205, 4)
        self.assertEqual(Client.calls, 2)

    def test_force_and_cache_invalidation(self) -> None:
        self.service.load_comments(self.settings, 1205, 3)
        self.service.load_comments(self.settings, 1205, 3, force=True)
        self.service.clear_item_cache(self.settings, 1205)
        self.service.load_comments(self.settings, 1205, 3)
        self.assertEqual(Client.calls, 3)

    def test_cleared_cache_is_not_refilled_by_a_late_result(self) -> None:
        """상세 새로고침으로 비운 뒤 늦게 끝난 조회가 옛 댓글을 다시 넣지 않는다."""
        entered = threading.Event()
        release = threading.Event()

        class SlowClient(Client):
            def get_item_comments(self, item_id: int):
                entered.set()
                release.wait(5)
                return super().get_item_comments(item_id)

        SlowClient.calls = 0
        service = TrackerCommentService(client_factory=SlowClient)
        worker = threading.Thread(target=lambda: service.load_comments(Settings(), 1001, 3))
        worker.start()
        self.assertTrue(entered.wait(5))
        service.clear_item_cache(Settings(), 1001)
        release.set()
        worker.join(5)

        service.load_comments(Settings(), 1001, 3)

        self.assertEqual(SlowClient.calls, 2)

    def test_baseline_is_rejected_before_client_call(self) -> None:
        with self.assertRaisesRegex(ValueError, "Baseline"):
            self.service.load_comments(self.settings, 1205, 3, baseline_id=7)
        self.assertEqual(Client.calls, 0)

    def test_server_error_message_shows_status_without_address(self) -> None:
        class FailingClient(Client):
            def get_item_comments(self, item_id: int):
                raise _ServerError()

        service = TrackerCommentService(client_factory=FailingClient)

        with self.assertRaises(TrackerQueryServiceError) as caught:
            service.load_comments(Settings(), 1001, 3)

        message = str(caught.exception)
        self.assertNotIn("secret-host", message)
        self.assertNotIn("/cb/api", message)
        self.assertIn("500", message)


if __name__ == "__main__":
    unittest.main()
