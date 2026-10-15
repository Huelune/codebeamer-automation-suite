from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.item_activity import BaselineMarker
from src.gui.item_activity import ItemActivityEntry
from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity import parse_server_time
from src.gui.item_change_history_view import MAX_CELL_TEXT
from src.gui.item_change_history_view import ItemChangeHistoryView
from src.gui.item_change_history_view import history_time_text
from src.gui.tracker_item_context_models import ItemFieldChange
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


FIELD = ItemActivityKind.FIELD_CHANGE


class ItemChangeHistoryViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _view(self) -> ItemChangeHistoryView:
        view = ItemChangeHistoryView()
        self.addCleanup(view.deleteLater)
        return view

    def test_versions_list_field_changes_with_long_values_shortened(self) -> None:
        long_text = "긴 설명 " * 200
        view = self._view()

        view.show_entries(
            (
                ItemActivityEntry(
                    FIELD,
                    at="2026-07-20T10:45:36.456",
                    by="Sample User A",
                    version=2,
                    changes=(
                        ItemFieldChange("Description", "짧은 설명", long_text),
                        ItemFieldChange(
                            "Owners",
                            None,
                            [{"id": 7001, "name": "Sample User A", "type": "UserReference"}],
                        ),
                    ),
                ),
                ItemActivityEntry(
                    FIELD, at="2026-07-19T08:00:00Z", by="Sample User B", version=1, change_summary="Created"
                ),
            ),
            current_version=2,
        )

        first = view.topLevelItem(0)
        self.assertEqual(first.text(0), "버전 2 (현재) · 2026-07-20 10:45 · Sample User A · 필드 2개")
        self.assertTrue(first.isExpanded())
        description = first.child(0)
        self.assertEqual(description.text(1), "짧은 설명")
        self.assertEqual(len(description.text(2)), MAX_CELL_TEXT)
        self.assertTrue(description.text(2).endswith("…"))
        self.assertGreater(len(description.toolTip(2)), MAX_CELL_TEXT)
        owners = first.child(1)
        self.assertEqual(owners.text(1), "-")
        self.assertIn("Sample User A", owners.text(2))
        second = view.topLevelItem(1)
        self.assertEqual(second.text(0), "버전 1 · 2026-07-19 08:00 · Sample User B")
        self.assertEqual(second.child(0).text(0), "Created")

    def test_comment_and_attachment_rows(self) -> None:
        view = self._view()

        view.show_entries(
            (
                ItemActivityEntry(
                    ItemActivityKind.COMMENT,
                    at="2026-07-20T09:10:00Z",
                    by="Sample User B",
                    title="댓글 #51001",
                    body="Review note",
                    edited=True,
                    attachment_names=("anonymous-evidence.txt",),
                ),
                ItemActivityEntry(
                    ItemActivityKind.ATTACHMENT,
                    at="2026-07-18T11:00:00Z",
                    title="anonymous-spec.txt",
                    body="2,048 bytes · text/plain",
                ),
            )
        )

        comment = view.topLevelItem(0)
        self.assertEqual(comment.text(0), "댓글 · 2026-07-20 09:10 · Sample User B (수정됨)")
        self.assertEqual(
            [comment.child(index).text(0) for index in range(comment.childCount())],
            ["Review note", "첨부: anonymous-evidence.txt"],
        )
        attachment = view.topLevelItem(1)
        self.assertEqual(
            attachment.text(0), "첨부 · 2026-07-18 11:00 · anonymous-spec.txt · 2,048 bytes · text/plain"
        )
        self.assertEqual(attachment.childCount(), 0)

    def test_baseline_boundary_is_placed_before_the_first_entry_inside_the_baseline(self) -> None:
        view = self._view()
        marker = BaselineMarker("Baseline #7", version=2, created_at=parse_server_time("2026-07-19T00:00:00Z"))
        entries = [
            ItemActivityEntry(FIELD, version=3),
            ItemActivityEntry(ItemActivityKind.COMMENT, at="2026-07-20T00:00:00Z", by="Sample User A"),
            ItemActivityEntry(FIELD, version=2),
            ItemActivityEntry(FIELD, version=1),
        ]

        view.show_entries(entries, baseline=marker)

        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            [
                "[Baseline 이후] 버전 3",
                "[Baseline 이후] 댓글 · 2026-07-20 00:00 · Sample User A",
                "── Baseline #7 시점 (버전 2) ──",
                "버전 2",
                "버전 1",
            ],
        )

        view.show_entries([ItemActivityEntry(FIELD, version=5)], baseline=marker)
        # Baseline 안쪽 이력이 없으면 구분선도 두지 않는다.
        self.assertEqual(view.topLevelItemCount(), 1)

    def test_tooltips_show_server_values_as_plain_text(self) -> None:
        view = self._view()

        view.show_entries(
            (
                ItemActivityEntry(
                    FIELD, version=2, changes=(ItemFieldChange("Note", "<b>old</b>", "<img src=x>"),)
                ),
                ItemActivityEntry(ItemActivityKind.COMMENT, at="2026-07-20T09:10:00Z", body="<i>hi</i>\nnext"),
            )
        )

        field_row = view.topLevelItem(0).child(0)
        self.assertEqual(field_row.toolTip(1), "<qt>&lt;b&gt;old&lt;/b&gt;</qt>")
        self.assertEqual(field_row.toolTip(2), "<qt>&lt;img src=x&gt;</qt>")
        comment_body = view.topLevelItem(1).child(0)
        self.assertEqual(comment_body.toolTip(0), "<qt>&lt;i&gt;hi&lt;/i&gt;<br>next</qt>")

    def test_time_text_keeps_unknown_shapes(self) -> None:
        self.assertEqual(history_time_text("2026-07-20T10:45:36.456"), "2026-07-20 10:45")
        self.assertEqual(history_time_text("2026-07-20T10:45:36Z"), "2026-07-20 10:45")
        self.assertEqual(history_time_text("yesterday"), "yesterday")
        self.assertEqual(history_time_text(""), "")


if __name__ == "__main__":
    unittest.main()
