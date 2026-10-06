from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.item_change_history_view import MAX_CELL_TEXT
from src.gui.item_change_history_view import ItemChangeHistoryView
from src.gui.item_change_history_view import history_time_text
from src.gui.tracker_item_context_models import ItemFieldChange
from src.gui.tracker_item_context_models import ItemHistoryEntry
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


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
                ItemHistoryEntry(
                    2,
                    "2026-07-20T10:45:36.456",
                    "Sample User A",
                    changes=(
                        ItemFieldChange("Description", "짧은 설명", long_text),
                        ItemFieldChange(
                            "Owners",
                            None,
                            [{"id": 7001, "name": "Sample User A", "type": "UserReference"}],
                        ),
                    ),
                ),
                ItemHistoryEntry(1, "2026-07-19T08:00:00Z", "Sample User B", change_summary="Created"),
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
        # 바뀐 필드 정보가 없는 버전은 변경 요약을 보인다.
        second = view.topLevelItem(1)
        self.assertEqual(second.text(0), "버전 1 · 2026-07-19 08:00 · Sample User B")
        self.assertEqual(second.child(0).text(0), "Created")

    def test_baseline_boundary_is_placed_before_the_baseline_version(self) -> None:
        view = self._view()
        entries = [ItemHistoryEntry(version) for version in (3, 2, 1)]

        view.show_entries(entries, baseline=(2, "Baseline #7"))

        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            [
                "[Baseline 이후] 버전 3",
                "── Baseline #7 시점 (버전 2) ──",
                "버전 2",
                "버전 1",
            ],
        )

        view.show_entries([ItemHistoryEntry(5)], baseline=(2, "Baseline #7"))
        # Baseline 버전 이전 이력이 없으면 구분선도 두지 않는다.
        self.assertEqual(view.topLevelItemCount(), 1)

    def test_time_text_keeps_unknown_shapes(self) -> None:
        self.assertEqual(history_time_text("2026-07-20T10:45:36.456"), "2026-07-20 10:45")
        self.assertEqual(history_time_text("2026-07-20T10:45:36Z"), "2026-07-20 10:45")
        self.assertEqual(history_time_text("yesterday"), "yesterday")
        self.assertEqual(history_time_text(""), "")


if __name__ == "__main__":
    unittest.main()
