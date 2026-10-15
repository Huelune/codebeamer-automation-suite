"""트래커 작업 공간 테스트가 함께 쓰는 가짜 객체와 기본 테스트 클래스."""

from __future__ import annotations

import os
import threading
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QBuffer
from PySide6.QtCore import QByteArray
from PySide6.QtCore import QIODevice
from PySide6.QtGui import QColor
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from src.gui.settings_store import GuiSettings
from src.gui.styles import build_gui_stylesheet
from src.gui.tracker_content_models import AttachmentResource
from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_content_models import WikiRenderResult
from src.gui.tracker_content_models import WikiResourceReference
from src.gui.tracker_item_detail_dialog import TrackerItemDetailDialog
from src.gui.tracker_query_models import TrackerItemDetail
from src.gui.tracker_query_service import TrackerQueryService
from src.gui.tracker_workspace import TrackerWorkspacePage
from src.gui.tracker_workspace_support import BASELINE_COMPARISON_ROLE
from src.gui.tracker_workspace_support import tree_items
from src.gui.workspace_favorites import WorkspaceFavorites
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "gui-offline-sample"


def _png_bytes(width: int, height: int) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def _detail(item_id: int, name: str, *, version: int = 1) -> TrackerItemDetail:
    return TrackerItemDetail.from_raw(
        {
            "id": item_id,
            "name": name,
            "description": f"{name} description",
            "descriptionFormat": "PlainText",
            "version": version,
            "tracker": {
                "id": 24680001,
                "name": "Offline Requirements",
                "project": {"id": 246800, "name": "Offline Project"},
            },
        }
    )


class _SignalStub:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        # 조회 결과가 None인 경우도 있으므로 받은 인자를 그대로 넘긴다.
        for callback in tuple(self._callbacks):
            callback(*args)


class _DeferredTask:
    def __init__(self, operation) -> None:
        self.operation = operation
        self.completed = _SignalStub()
        self.failed = _SignalStub()
        self.finished = _SignalStub()
        self.started = False
        self.deleted = False

    def start(self) -> None:
        self.started = True

    def finish(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            self.failed.emit(exc)
        else:
            self.completed.emit(result)
        finally:
            self.finished.emit()

    def emit_failure(self, exc: Exception) -> None:
        self.failed.emit(exc)
        self.finished.emit()

    def deleteLater(self) -> None:
        self.deleted = True


class CountingTrackerQueryService(TrackerQueryService):
    def __init__(self) -> None:
        super().__init__()
        self.child_load_count = 0
        self.baseline_compare_count = 0
        self.baseline_load_count = 0
        self.baseline_hierarchy_count = 0

    def load_all_child_items(self, *args, **kwargs):
        self.child_load_count += 1
        return super().load_all_child_items(*args, **kwargs)

    def compare_item_at_sources(self, *args, **kwargs):
        self.baseline_compare_count += 1
        return super().compare_item_at_sources(*args, **kwargs)

    def compare_tracker_at_sources(self, *args, **kwargs):
        self.baseline_compare_count += 1
        return super().compare_tracker_at_sources(*args, **kwargs)

    def load_tracker_baselines(self, *args, **kwargs):
        self.baseline_load_count += 1
        return super().load_tracker_baselines(*args, **kwargs)

    def load_baseline_hierarchy_snapshot(self, *args, **kwargs):
        self.baseline_hierarchy_count += 1
        return super().load_baseline_hierarchy_snapshot(*args, **kwargs)


EDITOR_SCHEMA = {
    "id": 20,
    "fields": [
        {
            "id": 3,
            "name": "Summary",
            "type": "TextField",
            "valueModel": "TextFieldValue",
            "trackerItemField": "name",
            "mandatory": True,
        },
        {
            "id": 7,
            "name": "Status",
            "type": "OptionChoiceField",
            "valueModel": "ChoiceFieldValue<ChoiceOptionReference>",
            "trackerItemField": "status",
            "options": [
                {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
                {"id": 2, "name": "Review", "type": "ChoiceOptionReference"},
            ],
        },
    ],
}


class EditableWorkspaceClient:
    item = {}
    created_item = None
    calls: list[tuple] = []
    deleted = False
    # 일괄 수정 요청을 이 신호가 올 때까지 붙잡아 둔다. 실행 중인 상태를 만들 때 쓴다.
    bulk_gate: threading.Event | None = None
    # 일괄 수정 요청이 클라이언트에 도착하면 켜진다.
    bulk_entered = threading.Event()
    # 이 번호(1부터)의 일괄 수정 요청은 응답 없이 연결 오류로 끝난다.
    bulk_error_on_call: int | None = None

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    @classmethod
    def reset(cls) -> None:
        cls.item = {
            "id": 1001,
            "name": "Original summary",
            "description": "Editable detail",
            "descriptionFormat": "PlainText",
            "version": 1,
            "tracker": {"id": 20, "name": "Requirements"},
            "status": {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
            "assignedTo": [],
            "children": [],
            "customFields": [],
        }
        cls.calls = []
        cls.deleted = False
        cls.created_item = None
        cls.bulk_gate = None
        cls.bulk_entered = threading.Event()
        cls.bulk_error_on_call = None

    def get_projects(self):
        return [{"id": 10, "name": "Vehicle"}]

    def get_trackers(self, project_id: int):
        return [{"id": 20, "name": "Requirements", "projectId": project_id}]

    def get_tracker(self, tracker_id: int):
        return {
            "id": tracker_id,
            "name": "Requirements",
            "project": {"id": 10, "name": "Vehicle"},
        }

    def get_tracker_schema(self, tracker_id: int):
        del tracker_id
        return deepcopy(EDITOR_SCHEMA)

    def get_tracker_children_page(self, tracker_id: int, *, page: int, page_size: int):
        del tracker_id
        if self.__class__.deleted:
            items = []
        else:
            item = self.__class__.item
            items = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "status": deepcopy(item["status"]),
                    "version": item["version"],
                    "hasChildren": False,
                }
            ]
        return {
            "page": page,
            "pageSize": page_size,
            "total": len(items),
            "itemRefs": items,
        }

    def get_item(self, item_id: int):
        self.__class__.calls.append(("get", item_id))
        if (
            self.__class__.created_item is not None
            and item_id == self.__class__.created_item["id"]
        ):
            return deepcopy(self.__class__.created_item)
        if self.__class__.deleted:
            raise KeyError(item_id)
        return deepcopy(self.__class__.item)

    def create_item(
        self,
        tracker_id: int,
        payload: dict,
        parent_item_id: int | None = None,
    ):
        self.__class__.calls.append(
            ("create", tracker_id, deepcopy(payload), parent_item_id)
        )
        created_item = {
            "id": 1002,
            "name": payload["name"],
            "description": payload.get("description", ""),
            "descriptionFormat": "PlainText",
            "version": 1,
            "tracker": {"id": tracker_id, "name": "Requirements"},
            "status": {"id": 1, "name": "Open", "type": "ChoiceOptionReference"},
            "assignedTo": [],
            "children": [],
            "customFields": deepcopy(payload.get("customFields", [])),
        }
        if parent_item_id is not None:
            created_item["parent"] = {
                "id": parent_item_id,
                "name": self.__class__.item["name"],
            }
        self.__class__.created_item = created_item
        return {"id": 1002}

    def update_item_fields(self, item_id: int, field_values: list[dict]):
        self.__class__.calls.append(("update", item_id, deepcopy(field_values)))
        for field_value in field_values:
            if field_value["fieldId"] == 3:
                self.__class__.item["name"] = field_value["value"]
            elif field_value["fieldId"] == 7:
                self.__class__.item["status"] = deepcopy(field_value["values"][0])
        self.__class__.item["version"] += 1
        return deepcopy(self.__class__.item)

    def delete_item(self, item_id: int):
        self.__class__.calls.append(("delete", item_id))
        self.__class__.deleted = True
        return {}

    def bulk_update_item_fields(self, operations, *, atomic=True):
        calls = self.__class__.calls
        calls.append(("bulk", tuple(operation["itemId"] for operation in operations), atomic))
        self.__class__.bulk_entered.set()
        if self.__class__.bulk_gate is not None:
            self.__class__.bulk_gate.wait(5)
        if sum(1 for call in calls if call[0] == "bulk") == self.__class__.bulk_error_on_call:
            raise ConnectionError("connection reset")
        return {"successfulOperationsCount": len(operations)}


class TrackerWorkspaceTestCase(unittest.TestCase):
    """오프라인 샘플로 작업 공간 페이지를 띄운다. 패널별 테스트 파일이 상속한다."""

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.settings = GuiSettings(
            offline_mode=True,
            offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
            offline_query_data_path=str(SAMPLE_DIR / "offline_tracker_items.json"),
        )
        self.service = CountingTrackerQueryService()
        self.baseline_compare_confirmations = []

        def confirm_baseline_compare(reference, comparison) -> bool:
            self.baseline_compare_confirmations.append((reference, comparison))
            return True

        self.page = TrackerWorkspacePage(
            settings_provider=lambda: self.settings,
            service=self.service,
            baseline_compare_confirmer=confirm_baseline_compare,
            synchronous=True,
        )
        self.page.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.page.close()
        self._app.processEvents()

    def _minimum_widths_with_baseline_names(self, repeat: int) -> tuple[int, int, int]:
        """Baseline 이름을 `repeat`배로 늘린 새 작업공간의 최소 너비.

        조회 탭, Baseline 탭, 테마를 바꾼 뒤의 계층 출처 콤보 순서다.
        """
        service = CountingTrackerQueryService()
        original = service.load_tracker_baselines

        def long_named_baselines(*args, **kwargs):
            return tuple(
                replace(baseline, name=baseline.name * repeat)
                for baseline in original(*args, **kwargs)
            )

        service.load_tracker_baselines = long_named_baselines  # type: ignore[method-assign]
        page = TrackerWorkspacePage(settings_provider=lambda: self.settings, service=service, synchronous=True)
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        # 앱처럼 테마를 입혀야 콤보가 처음 보일 때 폭을 다시 잰다.
        page.setStyleSheet(build_gui_stylesheet("kefico"))
        # 처음 보이기 전에 Baseline 목록을 채운다. 내용 길이로 폭을 잡는 정책이면 여기서 넓어진다.
        page.activate()
        page.show()
        self._app.processEvents()
        browse_width = page.minimumSizeHint().width()
        page.workspace_mode_tabs.setCurrentIndex(page.baseline_mode_index)
        self._app.processEvents()
        self.assertGreater(page.baseline_workspace.baseline_comparison_panel.after_combo.count(), 2)
        self.assertGreater(page.hierarchy_panel.hierarchy_source_combo.count(), 1)
        baseline_width = page.minimumSizeHint().width()
        # 테마를 바꾸면 콤보가 폭을 다시 잰다. 이미 채운 계층 출처 콤보도 이름 길이를 따르지 않아야 한다.
        page.setStyleSheet(build_gui_stylesheet("igloo"))
        self._app.processEvents()
        return (
            browse_width,
            baseline_width,
            page.hierarchy_panel.hierarchy_source_combo.minimumSizeHint().width(),
        )

    @staticmethod
    def _accepting_export_dialog(dialog_cls, selected_keys: tuple[str, ...]):
        """exec만 막은 진짜 필드 선택 창. 호출부가 넘긴 실제 인자로 생성자가 불린다."""

        class _AcceptingDialog(dialog_cls):
            def exec(self) -> int:
                return QDialog.DialogCode.Accepted

            def selected_field_keys(self) -> tuple[str, ...]:
                return selected_keys

        return _AcceptingDialog

    def _select_comparison_row(self, item_id: int) -> None:
        table = self.page.baseline_workspace.baseline_result_table
        for row in range(table.rowCount()):
            comparison = table.item(row, 1).data(BASELINE_COMPARISON_ROLE)
            if comparison is not None and comparison.item_id == item_id:
                table.selectRow(row)
                self._app.processEvents()
                return
        self.fail(f"#{item_id}이 비교 결과에 없습니다.")

    def _favorites_page(self, stored: dict | None = None) -> tuple[TrackerWorkspacePage, list, dict]:
        """즐겨찾기를 읽고 저장하는 작업공간. 저장 호출과 설정 파일 대신 쓰는 dict를 돌려준다."""
        holder = {"value": dict(stored or {})}
        saved: list[tuple[str, WorkspaceFavorites]] = []
        page = TrackerWorkspacePage(
            settings_provider=lambda: self.settings,
            service=self.service,
            favorites_loader=lambda: holder["value"],
            favorites_saver=lambda key, favorites: saved.append((key, favorites)),
            synchronous=True,
        )
        self.addCleanup(page.deleteLater)
        self.addCleanup(page.close)
        page.resize(1280, 860)
        page.show()
        page.activate()
        self._app.processEvents()
        return page, saved, holder

    @staticmethod
    def _favorite_cell(table, row: int, column: int = 0):
        return table.visualItemRect(table.item(row, column)).center()

    def _open_real_detail_dialog(self) -> TrackerItemDetailDialog:
        """exec 만 막고 진짜 상세 창을 연다. 조회 결과가 반영되도록 화면에 띄워 둔다."""
        opened: list[TrackerItemDetailDialog] = []

        class _NonModalDialog(TrackerItemDetailDialog):
            def exec(self) -> int:
                opened.append(self)
                return 0

        with patch(
            "src.gui.tracker_detail_dialog.TrackerItemDetailDialog", _NonModalDialog
        ):
            self.page.detail_dialog.open_dialog()
        self.assertEqual(len(opened), 1)
        dialog = opened[0]
        self.addCleanup(lambda: isValid(dialog) and dialog.close())
        dialog.show()
        self._app.processEvents()
        return dialog

    @staticmethod
    def _dialog_tree_item(dialog: TrackerItemDetailDialog, item_id: int):
        return next(
            item
            for item in tree_items(dialog.item_tree)
            if item.text(1) == str(item_id)
        )

    def _show_baseline_hierarchy(self, baseline_id: int = 24681001) -> None:
        hierarchy = self.page.hierarchy_panel
        hierarchy.hierarchy_source_combo.setCurrentIndex(hierarchy.hierarchy_source_combo.findData(baseline_id))
        hierarchy.reload_roots_button.click()
        self._app.processEvents()
        self.assertEqual(hierarchy.selected_baseline_id(), baseline_id)
        self.assertEqual(hierarchy.item_tree.topLevelItemCount(), 1)

    def _image_test_detail(self, item_id: int) -> TrackerItemDetail:
        self.settings.offline_mode = False
        self.settings.base_url = "https://example.test/cb"
        self.settings.username = "sample"
        self.settings.password = "placeholder"
        detail = TrackerItemDetail.from_raw(
            {
                "id": item_id,
                "name": "Image detail",
                "version": 1,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
            }
        )
        self.page.detail_panel.render_detail(detail)
        return detail

    def _deferred_tasks(self) -> list[_DeferredTask]:
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        return tasks

    @staticmethod
    def _finish_all(tasks: list[_DeferredTask]) -> None:
        index = 0
        while index < len(tasks):
            tasks[index].finish()
            index += 1

    def _record_image_downloads(self) -> list[str]:
        requested: list[str] = []
        content = self.page.content_service

        def download_resource(*_args, **kwargs):
            requested.append(kwargs["resource_key"])
            return AttachmentResource(kwargs["resource_key"], "image/png", _png_bytes(2, 2))

        def download_attachment(_settings, attachment, *, max_bytes):
            del max_bytes
            key = f"attachment-{attachment.attachment_id}"
            requested.append(key)
            return AttachmentResource(key, "image/png", _png_bytes(2, 2))

        content.download_resource = download_resource
        content.download_attachment = download_attachment
        return requested

    @staticmethod
    def _image_attachments(count: int) -> tuple[AttachmentSummary, ...]:
        return tuple(
            AttachmentSummary(500 + index, f"preview-{index}.png", mime_type="image/png", size=100)
            for index in range(count)
        )

    @staticmethod
    def _server_images(count: int) -> WikiRenderResult:
        return WikiRenderResult(
            html="<p>images</p>",
            resources=tuple(
                WikiResourceReference(f"image-{index}", f"https://example.test/cb/attachment/{index}")
                for index in range(count)
            ),
        )

    def _wiki_image_detail(self, item_id: int) -> TrackerItemDetail:
        """서버 Wiki 렌더링을 쓰는 상세. 패널에는 첨부를 아직 받지 않은 상태로 둔다."""
        self._image_test_detail(item_id)
        self.settings.server_wiki_html_enabled = True
        detail = TrackerItemDetail.from_raw(
            {
                "id": item_id,
                "name": "Dialog image detail",
                "version": 1,
                "description": "!image!",
                "descriptionFormat": "Wiki",
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
            }
        )
        self.page.detail_panel.render_detail(detail)
        return detail

    def _select_steering_results(self):
        panel = self.page.search_panel
        panel.search_text_input.setText("Steering")
        panel._run_search()
        panel._select_current_search_page()
        self.assertEqual(panel.selected_count(), 2)
        return panel

    def _search_row_texts(self) -> list[tuple[str, ...]]:
        table = self.page.search_panel.search_table
        return [
            tuple(table.item(row, column).text() for column in range(1, table.columnCount()))
            for row in range(table.rowCount())
        ]
