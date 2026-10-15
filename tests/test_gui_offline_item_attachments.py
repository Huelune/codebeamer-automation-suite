from __future__ import annotations

import unittest
from pathlib import Path

from src.gui.settings_store import GuiSettings
from src.gui.tracker_content_service import TrackerContentService


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "gui-offline-sample"


class OfflineItemAttachmentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = GuiSettings(
            offline_mode=True,
            offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
            offline_query_data_path=str(SAMPLE_DIR / "offline_tracker_items.json"),
        )

    def test_sample_attachments_are_listed_in_test_mode(self) -> None:
        attachments = TrackerContentService().load_attachments(self.settings, 9001001)

        self.assertEqual(
            [(value.attachment_id, value.name, value.size, value.modified_at) for value in attachments],
            [
                (53001, "anonymous-spec.txt", 2048, "2026-07-18T11:00:00Z"),
                (53002, "anonymous-draft.txt", 512, "2026-07-10T08:00:00Z"),
            ],
        )

    def test_items_without_sample_attachments_have_none(self) -> None:
        self.assertEqual(TrackerContentService().load_attachments(self.settings, 9001002), ())
        # 테스트 데이터가 모르는 아이템도 오류 없이 빈 목록이다.
        self.assertEqual(TrackerContentService().load_attachments(self.settings, 123), ())

    def test_baseline_attachments_are_still_not_listed(self) -> None:
        self.assertEqual(TrackerContentService().load_attachments(self.settings, 9001001, baseline_id=24681001), ())

    def test_test_mode_without_sample_data_does_not_ask(self) -> None:
        settings = GuiSettings(offline_mode=True)

        self.assertEqual(TrackerContentService().load_attachments(settings, 9001001), ())


if __name__ == "__main__":
    unittest.main()
