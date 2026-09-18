from __future__ import annotations

import base64
import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_content_models import AttachmentResource
from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_item_context_models import ItemRelationsSnapshot
from src.gui.tracker_item_detail_dialog import TrackerItemDetailDialog
from src.gui.tracker_query_models import TrackerItemDetail
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class TrackerItemDetailDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def detail(self) -> TrackerItemDetail:
        return TrackerItemDetail.from_raw(
            {
                "id": 1205,
                "name": "Large detail",
                "description": "설명",
                "version": 4,
                "status": {"id": 1, "name": "Open"},
                "tracker": {
                    "id": 24680001,
                    "name": "Requirements",
                    "project": {"id": 246800, "name": "Sample Project"},
                },
                "customFields": [
                    {"fieldId": 1000, "name": "Risk", "type": "TextFieldValue", "value": "Low"}
                ],
            }
        )

    def test_dialog_shows_full_detail_and_zoomable_image(self) -> None:
        dialog = TrackerItemDetailDialog(
            self.detail(),
            description_html="<p>설명</p>",
            attachments=(AttachmentSummary(28, "sample.png", mime_type="image/png"),),
            image_resources=(AttachmentResource("attachment-28", "image/png", PNG),),
        )
        dialog.show()
        self.app.processEvents()

        self.assertIn("#1205", dialog.windowTitle())
        self.assertEqual(dialog.image_combo.count(), 1)
        self.assertIn("확대", dialog.image_status.text())
        dialog.image_view.actual_size()
        self.assertAlmostEqual(dialog.image_view.transform().m11(), 1.0)
        dialog.image_view.zoom_in()
        self.assertAlmostEqual(dialog.image_view.transform().m11(), 1.25)
        dialog.image_view.zoom_out()
        self.assertAlmostEqual(dialog.image_view.transform().m11(), 1.0)
        dialog.close()

    def test_dialog_disables_image_controls_without_loaded_resource(self) -> None:
        dialog = TrackerItemDetailDialog(
            self.detail(),
            description_html="<p>설명</p>",
            attachments=(AttachmentSummary(29, "sample.pdf", mime_type="application/pdf"),),
        )

        self.assertEqual(dialog.image_combo.count(), 0)
        self.assertFalse(dialog.image_combo.isEnabled())
        self.assertIn("없습니다", dialog.image_status.text())

    def test_context_tabs_are_lazy_and_related_item_is_opened_in_dialog(self) -> None:
        dialog = TrackerItemDetailDialog(self.detail(), description_html="<p>설명</p>")
        requested = []
        opened = []
        dialog.context_tab_requested.connect(lambda kind, force: requested.append((kind, force)))
        dialog.related_item_requested.connect(opened.append)
        dialog.show()
        dialog.tabs.setCurrentWidget(dialog.relations_tab)
        self.app.processEvents()

        self.assertEqual(requested, [("relations", False)])
        dialog.set_relations(
            ItemRelationsSnapshot.from_raw(
                {
                    "downstreamReferences": [
                        {"id": "r1", "itemRevision": {"id": 1206, "name": "Child"}}
                    ]
                }
            )
        )
        dialog._open_selected_relation(dialog.relations_table.model().index(0, 1))
        self.assertEqual(opened, [1206])
        dialog.close()

    def test_baseline_context_tabs_never_request_current_context(self) -> None:
        dialog = TrackerItemDetailDialog(self.detail(), description_html="", baseline_id=7)
        requested = []
        dialog.context_tab_requested.connect(lambda kind, force: requested.append((kind, force)))
        dialog.show()
        dialog.tabs.setCurrentWidget(dialog.relations_tab)
        dialog.tabs.setCurrentWidget(dialog.history_tab)
        self.app.processEvents()

        self.assertEqual(requested, [])
        self.assertIn("현재 상태를 대신 조회하지 않습니다", dialog.history_status.text())
        dialog.close()

    def test_comments_tab_loads_lazily_and_renders_reply_attachment(self) -> None:
        dialog = TrackerItemDetailDialog(self.detail(), description_html="<p>설명</p>")
        requested = []
        saved = []
        dialog.comments_requested.connect(requested.append)
        dialog.comment_attachment_save_requested.connect(saved.append)
        dialog.show()
        dialog.tabs.setCurrentWidget(dialog.comments_tab)
        self.app.processEvents()

        self.assertEqual(requested, [False])
        snapshot = ItemCommentsSnapshot.from_raw(
            [
                {"id": 1, "createdAt": "2026-01-01", "commentFormat": "Wiki", "comment": "|| A || B ||"},
                {
                    "id": 2,
                    "replyTo": {"id": 1},
                    "createdAt": "2026-01-02",
                    "comment": "reply",
                    "attachments": [{"id": 29, "name": "sample.pdf", "mimeType": "application/pdf"}],
                },
            ]
        )
        dialog.set_comments(snapshot)
        self.assertEqual(set(dialog.comment_views), {"1", "2"})
        self.assertEqual(dialog.comments_layout.count(), 3)
        buttons = dialog.comments_container.findChildren(type(dialog.comments_retry))
        save_button = next(button for button in buttons if button.text() == "저장")
        save_button.click()
        self.assertEqual(saved[0].attachment_id, 29)
        dialog.close()

    def test_baseline_comments_tab_never_requests_current_comments(self) -> None:
        dialog = TrackerItemDetailDialog(self.detail(), description_html="", baseline_id=7)
        requested = []
        dialog.comments_requested.connect(requested.append)
        dialog.show()
        dialog.tabs.setCurrentWidget(dialog.comments_tab)
        self.app.processEvents()

        self.assertEqual(requested, [])
        self.assertIn("현재 댓글을 대신 조회하지 않습니다", dialog.comments_status.text())
        dialog.close()

    def test_replacing_detail_resets_context_and_comments_for_lazy_reload(self) -> None:
        dialog = TrackerItemDetailDialog(self.detail(), description_html="<p>설명</p>")
        dialog.set_comments(ItemCommentsSnapshot.from_raw([{"id": 1, "comment": "old"}]))

        dialog.replace_detail(self.detail(), description_html="<p>교체</p>")

        self.assertEqual(dialog.relations_table.rowCount(), 0)
        self.assertEqual(dialog.history_table.rowCount(), 0)
        self.assertEqual(dialog.comment_views, {})
        self.assertEqual(dialog._comments_state, "idle")
        self.assertIn("탭을 열면", dialog.comments_status.text())
        dialog.close()


if __name__ == "__main__":
    unittest.main()
