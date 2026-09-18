from __future__ import annotations

import unittest
from dataclasses import dataclass

from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_comment_service import TrackerCommentService
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

    def test_baseline_is_rejected_before_client_call(self) -> None:
        with self.assertRaisesRegex(ValueError, "Baseline"):
            self.service.load_comments(self.settings, 1205, 3, baseline_id=7)
        self.assertEqual(Client.calls, 0)


if __name__ == "__main__":
    unittest.main()
