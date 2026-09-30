from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from src.gui.settings_store import GuiSettings
from src.gui.tracker_query_service import TrackerQueryService
from src.gui.tracker_workspace import TrackerWorkspacePage
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "gui-offline-sample"


class RootCountingService(TrackerQueryService):
    """어떤 트래커의 최상위 아이템을 실제로 조회했는지 기록한다."""

    def __init__(self) -> None:
        super().__init__()
        self.root_loads: list[int] = []

    def load_all_top_level_items(self, settings, tracker_id, **kwargs):
        self.root_loads.append(int(tracker_id))
        return super().load_all_top_level_items(settings, tracker_id, **kwargs)


def _write_two_project_query_data(target_dir: Path) -> Path:
    """샘플에 트래커 하나와, 트래커 하나짜리 두 번째 프로젝트를 더한 조회 데이터를 만든다."""
    data = json.loads((SAMPLE_DIR / "offline_tracker_items.json").read_text(encoding="utf-8"))
    data["projects"].append(
        {"id": 246801, "name": "Offline Second Project", "type": "ProjectReference"}
    )
    data["trackers"].extend(
        [
            {
                "id": 24680003,
                "name": "Offline Change Requests",
                "type": "TrackerReference",
                "projectId": 246800,
            },
            {
                "id": 24680101,
                "name": "Offline Second Tracker",
                "type": "TrackerReference",
                "projectId": 246801,
            },
        ]
    )
    path = target_dir / "offline_tracker_items.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TrackerPickerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        self.settings = GuiSettings(
            offline_mode=True,
            offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
            offline_tracker_configuration_path=str(
                SAMPLE_DIR / "offline_tracker_configuration.json"
            ),
            offline_query_data_path=str(_write_two_project_query_data(Path(self._tmp_dir.name))),
        )
        self.saved: list[list[dict[str, int]]] = []
        self.service = RootCountingService()
        self.page = self._open_page()

    def _open_page(self, recent_trackers=(), service=None) -> TrackerWorkspacePage:
        page = TrackerWorkspacePage(
            settings_provider=lambda: self.settings,
            service=service or self.service,
            recent_trackers=recent_trackers,
            recent_trackers_saver=self.saved.append,
            synchronous=True,
        )
        page.show()
        self.addCleanup(page.close)
        self._app.processEvents()
        return page

    def _type_and_enter(self, combo, text: str) -> None:
        line_edit = combo.lineEdit()
        combo.setFocus()
        line_edit.selectAll()
        QTest.keyClicks(line_edit, text)
        QTest.keyClick(line_edit, Qt.Key.Key_Return)
        self._app.processEvents()

    def test_typing_part_of_a_tracker_name_opens_the_first_match(self) -> None:
        self.page.activate()
        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)

        self._type_and_enter(self.page.tracker_combo, "test cases")

        self.assertEqual(self.page.tracker_combo.currentData(), 24680002)
        self.assertEqual(
            self.page.tracker_combo.currentText(),
            self.page.tracker_combo.itemText(self.page.tracker_combo.currentIndex()),
        )
        self.assertEqual(self.service.root_loads[-1], 24680002)
        self.assertEqual(self.saved[-1][0], {"project_id": 246800, "tracker_id": 24680002})

    def test_unmatched_text_is_reported_and_the_selection_is_kept(self) -> None:
        self.page.activate()
        combo = self.page.tracker_combo

        self._type_and_enter(combo, "no such tracker")

        self.assertEqual(combo.currentData(), 24680001)
        self.assertEqual(combo.currentText(), combo.itemText(combo.currentIndex()))
        self.assertIn("일치하는 트래커가 없습니다", self.page.workspace_status_label.text())

        # 고르지 않고 칸을 떠나도 반쯤 친 글자가 남지 않는다. 오프스크린에서는 창이
        # 활성화되지 않아 포커스가 옮겨지지 않으므로 칸을 떠날 때 나오는 신호를 직접 보낸다.
        combo.setFocus()
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), "offl")
        combo.lineEdit().editingFinished.emit()
        self.assertEqual(combo.currentText(), combo.itemText(combo.currentIndex()))

    def test_opened_tracker_is_listed_first_and_restored_on_next_start(self) -> None:
        self.page.activate()
        combo = self.page.tracker_combo

        combo.activated.emit(combo.findData(24680002))

        # 시작할 때 연 트래커와 방금 고른 트래커가 위, 구분선 아래에 나머지가 온다.
        self.assertEqual(
            [combo.itemData(index) for index in range(combo.count())],
            [24680002, 24680001, None, 24680003],
        )
        self.assertEqual(combo.currentData(), 24680002)
        remembered = self.saved[-1]
        self.assertEqual(
            remembered,
            [
                {"project_id": 246800, "tracker_id": 24680002},
                {"project_id": 246800, "tracker_id": 24680001},
            ],
        )

        next_service = RootCountingService()
        next_page = self._open_page(recent_trackers=remembered, service=next_service)
        next_page.activate()

        self.assertEqual(next_page.tracker_combo.currentData(), 24680002)
        self.assertEqual(next_service.root_loads, [24680002])

    def test_recent_trackers_are_saved_only_when_their_order_changes(self) -> None:
        """설정 저장은 자격 증명 저장소까지 다시 쓰므로 같은 목록을 반복 저장하지 않는다."""
        self.page.activate()
        self.assertEqual(len(self.saved), 1)

        self.page.activate(force=True)

        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)
        self.assertEqual(len(self.saved), 1)

    def test_switching_project_does_not_open_its_first_tracker(self) -> None:
        self.page.activate()
        self.service.root_loads.clear()
        project_combo = self.page.project_combo

        project_combo.activated.emit(project_combo.findData(246801))

        self.assertIsNone(self.page._current_tracker)
        self.assertEqual(self.page.tracker_combo.currentIndex(), -1)
        self.assertEqual(self.page.tracker_combo.currentText(), "")
        self.assertEqual(self.page.tracker_combo.count(), 1)
        self.assertEqual(self.service.root_loads, [])
        self.assertIn("조회할 트래커를 고르세요", self.page.workspace_status_label.text())
        self.assertFalse(self.page.required_fields_label.isVisible())

        # 돌아오면 그 프로젝트에서 보던 트래커를 다시 연다.
        project_combo.activated.emit(project_combo.findData(246800))

        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)
        self.assertEqual(self.page._current_tracker.tracker_id, 24680001)

    def test_tracker_id_from_another_project_moves_to_that_project(self) -> None:
        self.page.activate()

        self._type_and_enter(self.page.tracker_combo, "24680101")

        self.assertEqual(self.page.project_combo.currentData(), 246801)
        self.assertEqual(self.page.tracker_combo.currentData(), 24680101)
        self.assertEqual(self.page._current_tracker.tracker_id, 24680101)
        self.assertEqual(self.service.root_loads[-1], 24680101)
        self.assertEqual(self.saved[-1][0], {"project_id": 246801, "tracker_id": 24680101})

    def test_unknown_tracker_id_is_reported_without_changing_the_selection(self) -> None:
        self.page.activate()

        self._type_and_enter(self.page.tracker_combo, "99999999")

        self.assertEqual(self.page.tracker_combo.currentData(), 24680001)
        self.assertIn("트래커 #99999999 열기 실패", self.page.workspace_status_label.text())
        self.assertEqual(self.page.workspace_status_label.property("tone"), "error")

    def test_project_can_be_found_by_part_of_its_name(self) -> None:
        self.page.activate()

        self._type_and_enter(self.page.project_combo, "second")

        self.assertEqual(self.page.project_combo.currentData(), 246801)
        self.assertEqual(self.page.tracker_combo.currentIndex(), -1)


if __name__ == "__main__":
    unittest.main()
