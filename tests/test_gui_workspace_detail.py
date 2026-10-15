"""작업 공간의 상세 패널·상세 창·첨부·이미지 테스트."""

from __future__ import annotations

import base64
import unittest
from dataclasses import replace
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtCore import QUrl
from shiboken6 import isValid

from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_content_models import AttachmentResource
from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_content_models import WikiRenderResult
from src.gui.tracker_content_models import WikiResourceReference
from src.gui.tracker_detail_panel import ATTACHMENT_VISIBLE_ROWS
from src.gui.tracker_item_context_models import ItemRelationsSnapshot
from src.gui.tracker_item_detail_dialog import TrackerItemDetailDialog
from src.gui.tracker_item_detail_session import TrackerItemDetailSession
from src.gui.tracker_query_models import TrackerFieldValue
from src.gui.tracker_query_models import TrackerItemDetail
from src.gui.wiki_content_view import WikiContentDialog
from src.gui.wiki_renderer import wiki_image_resource_key
from src.gui.workspace_favorites import TEST_MODE_FAVORITES_KEY
from src.gui.workspace_favorites import FavoriteItem
from src.gui.workspace_favorites import WorkspaceFavorites
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401
from tests.tracker_workspace_fixtures import TrackerWorkspaceTestCase
from tests.tracker_workspace_fixtures import _DeferredTask
from tests.tracker_workspace_fixtures import _detail
from tests.tracker_workspace_fixtures import _png_bytes


class TrackerWorkspaceDetailTest(TrackerWorkspaceTestCase):
    def test_tree_selection_loads_read_only_detail_and_masked_raw_json(self) -> None:
        self.page.activate()
        root = self.page.hierarchy_panel.item_tree.topLevelItem(0)
        self.page.hierarchy_panel.item_tree.setCurrentItem(root)
        self._app.processEvents()

        self.assertEqual(self.page.detail_panel.detail_title.text(), "Vehicle requirements")
        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#9001001")
        self.assertTrue(self.page.detail_panel.detail_refresh_button.isEnabled())
        self.assertIn("Top-level sample requirement", self.page.detail_panel.detail_description.toPlainText())
        self.assertGreaterEqual(self.page.detail_panel.detail_fields_table.rowCount(), 10)
        self.assertIn('"Risk Level"', self.page.detail_panel.detail_raw_json.toPlainText())

    def test_detail_id_button_copies_numeric_id_only(self) -> None:
        self.page.activate()
        root = self.page.hierarchy_panel.item_tree.topLevelItem(0)
        self.page.hierarchy_panel.item_tree.setCurrentItem(root)
        self._app.processEvents()
        clipboard = self._app.clipboard()
        clipboard.clear()

        self.page.detail_panel.detail_id_badge.click()
        self._app.processEvents()

        self.assertEqual(self.page.detail_panel.detail_id_badge.text(), "#9001001")
        self.assertEqual(clipboard.text(), "9001001")
        self.assertNotIn("#", clipboard.text())
        self.assertIn("9001001", self.page.workspace_status_label.text())
        self.assertIn("복사", self.page.workspace_status_label.text())

    def test_wiki_rendering_requires_explicit_format_or_field_type(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1200,
                "name": "Wiki detail",
                "description": "%%(color:red)__설명__%%",
                "descriptionFormat": "Wiki",
                "tracker": {"id": 24680001, "name": "Offline Requirements"},
                "customFields": [
                    {
                        "fieldId": 101,
                        "name": "Wiki field",
                        "type": "WikiTextFieldValue",
                        "value": "%%(color:blue)Wiki 값%%",
                    },
                    {
                        "fieldId": 102,
                        "name": "Plain field",
                        "type": "TextFieldValue",
                        "value": "%%(color:blue)원문 유지%%",
                    },
                    {
                        "fieldId": 103,
                        "name": "Steps",
                        "type": "TableFieldValue",
                        "values": [
                            [
                                {
                                    "fieldId": 104,
                                    "name": "Action",
                                    "type": "WikiTextFieldValue",
                                    "value": "%%red 실행%%",
                                }
                            ]
                        ],
                    },
                ],
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertTrue(self.page.detail_panel.description_source_toggle.isVisible())
        self.assertEqual(self.page.detail_panel.detail_description.toPlainText(), "설명")
        self.assertIsNotNone(self.page.detail_panel.detail_fields_table.cellWidget(9, 1))
        self.assertIsNone(self.page.detail_panel.detail_fields_table.cellWidget(10, 1))
        self.assertEqual(
            self.page.detail_panel.detail_fields_table.item(10, 1).text(),
            "%%(color:blue)원문 유지%%",
        )
        self.assertIsNotNone(self.page.detail_panel.detail_fields_table.cellWidget(11, 1))

        self.page.detail_panel.description_source_toggle.setChecked(True)
        self.assertEqual(
            self.page.detail_panel.detail_description.toPlainText(),
            "%%(color:red)__설명__%%",
        )

    def test_plain_description_keeps_wiki_like_text_unchanged(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1201,
                "name": "Plain detail",
                "description": "%%(color:red)원문%%",
                "descriptionFormat": "PlainText",
                "tracker": {"id": 24680001, "name": "Offline Requirements"},
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertFalse(self.page.detail_panel.description_source_toggle.isVisible())
        self.assertEqual(
            self.page.detail_panel.detail_description.toPlainText(),
            "%%(color:red)원문%%",
        )

    def test_current_detail_lists_embedded_attachment_metadata(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1202,
                "name": "Attachment detail",
                "version": 3,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
                "attachments": [
                    {
                        "id": 28,
                        "name": "sample.png",
                        "size": 2048,
                        "mimeType": "image/png",
                        "modifiedAt": "2026-08-13T10:00:00Z",
                        "uri": "/attachment/28",
                    }
                ],
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertEqual(self.page.detail_panel.attachment_table.rowCount(), 1)
        self.assertEqual(self.page.detail_panel.attachment_table.item(0, 0).text(), "sample.png")
        self.assertEqual(self.page.detail_panel.attachment_table.item(0, 1).text(), "2.0 KB")
        self.assertIsNotNone(self.page.detail_panel.attachment_table.cellWidget(0, 3))

    def test_description_and_fields_have_their_own_tabs(self) -> None:
        """설명과 필드 표는 각자 탭을 갖고, 설명 칸은 창 크기를 따라 탭 높이를 채운다."""
        self.page.activate()
        panel = self.page.detail_panel
        panel.load_detail(9001001)
        self.page.resize(1280, 860)
        self._app.processEvents()
        normal_height = panel.detail_description.height()

        self.page.resize(1920, 1080)
        self._app.processEvents()

        self.assertGreater(panel.detail_description.height(), normal_height)
        tabs = panel.detail_tabs
        self.assertEqual(tabs.tabText(0), "설명")
        self.assertEqual(tabs.tabText(1), "필드")
        self.assertTrue(tabs.widget(0).isAncestorOf(panel.detail_description))
        self.assertFalse(tabs.widget(0).isAncestorOf(panel.detail_fields_table))
        self.assertTrue(tabs.widget(1).isAncestorOf(panel.detail_fields_table))
        # 필드 표가 빠진 만큼 설명 칸이 탭 높이의 대부분을 쓴다.
        self.assertGreater(panel.detail_description.height(), tabs.widget(0).height() * 0.6)

    def test_attachment_table_is_hidden_when_empty_and_fits_its_rows(self) -> None:
        """첨부 표가 빈 채로 자리를 차지하지 않고, 행이 많으면 몇 행까지만 보인다."""
        panel = self.page.detail_panel

        def render_with_attachments(count: int) -> int:
            panel.render_detail(
                TrackerItemDetail.from_raw(
                    {
                        "id": 1300 + count,
                        "name": "Attachment layout",
                        "version": 1,
                        "tracker": {
                            "id": 24680001,
                            "name": "Offline Requirements",
                            "project": {"id": 246800, "name": "Offline Project"},
                        },
                        "attachments": [
                            {"id": 700 + index, "name": f"sample-{index}.txt", "size": 10}
                            for index in range(count)
                        ],
                    }
                )
            )
            self._app.processEvents()
            return panel.attachment_table.height()

        render_with_attachments(0)
        self.assertFalse(panel.attachment_table.isVisible())
        self.assertEqual(panel.attachment_status_label.text(), "첨부 파일이 없습니다.")

        one_row_height = render_with_attachments(1)
        self.assertTrue(panel.attachment_table.isVisible())
        capped_height = render_with_attachments(ATTACHMENT_VISIBLE_ROWS)
        self.assertGreater(capped_height, one_row_height)
        self.assertEqual(render_with_attachments(ATTACHMENT_VISIBLE_ROWS + 3), capped_height)

        panel.reset_detail()
        self.assertFalse(panel.attachment_table.isVisible())

    def test_current_detail_automatically_renders_image_attachment_in_memory(self) -> None:
        self.settings.offline_mode = False
        self.settings.base_url = "https://example.test/cb"
        self.settings.username = "sample"
        self.settings.password = "placeholder"
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        calls = []
        self.page.content_service.download_attachment = (
            lambda _settings, attachment, *, max_bytes: calls.append(
                (attachment.attachment_id, max_bytes)
            )
            or AttachmentResource(
                f"attachment-{attachment.attachment_id}",
                "image/png",
                png,
            )
        )
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1205,
                "name": "Image preview",
                "version": 1,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
                "attachments": [
                    {
                        "id": 28,
                        "name": "sample.png",
                        "size": len(png),
                        "mimeType": "image/png",
                    },
                    {
                        "id": 29,
                        "name": "sample.pdf",
                        "size": 100,
                        "mimeType": "application/pdf",
                    },
                ],
            }
        )

        self.page.detail_panel.render_detail(detail)

        self.assertTrue(self.page.detail_panel.attachment_preview.isVisible())
        self.assertIn("cb-attachment://attachment-28", self.page.detail_panel.attachment_preview.text())
        self.assertTrue(self.page.detail_panel.attachment_preview_button.isVisible())
        self.assertTrue(self.page.detail_panel.attachment_preview_button.isEnabled())
        self.assertEqual(calls, [(28, 10 * 1024 * 1024)])
        self.assertEqual(self.page.detail_panel._inline_image_bytes, len(png))

        with patch("src.gui.tracker_detail_panel.WikiContentDialog") as dialog_class:
            self.page.detail_panel._open_attachment_preview()

        dialog_class.assert_called_once()
        dialog_class.return_value.resize.assert_called_once_with(1100, 760)
        dialog_class.return_value.view.add_attachment_resource.assert_called_once()
        dialog_class.return_value.exec.assert_called_once()
        self.assertEqual(calls, [(28, 10 * 1024 * 1024)])

        with patch("src.gui.tracker_detail_dialog.TrackerItemDetailDialog") as detail_dialog:
            self.page.detail_dialog.open_dialog()

        detail_dialog.assert_called_once()
        detail_kwargs = detail_dialog.call_args.kwargs
        self.assertEqual(detail_kwargs["attachments"], self.page.detail_panel._attachments)
        self.assertEqual(len(detail_kwargs["image_resources"]), 1)
        detail_dialog.return_value.exec.assert_called_once()

    def test_attachment_preview_skips_images_already_in_the_description(self) -> None:
        """본문에 나온 그림은 첨부 영역에 다시 보이지 않는다. 원문 보기와 크게 보기는 전부 보인다."""
        self.settings.offline_mode = False
        self.settings.base_url = "https://example.test/cb"
        self.settings.username = "sample"
        self.settings.password = "placeholder"
        self.page.content_service.download_attachment = (
            lambda _settings, attachment, *, max_bytes: AttachmentResource(
                f"attachment-{attachment.attachment_id}", "image/png", _png_bytes(4, 4)
            )
        )

        def detail(description: str) -> TrackerItemDetail:
            return TrackerItemDetail.from_raw(
                {
                    "id": 1212,
                    "name": "Wiki images",
                    "version": 1,
                    "description": description,
                    "descriptionFormat": "Wiki",
                    "tracker": {
                        "id": 24680001,
                        "name": "Offline Requirements",
                        "project": {"id": 246800, "name": "Offline Project"},
                    },
                    "attachments": [
                        {"id": 51, "name": "diagram.png", "mimeType": "image/png"},
                        {"id": 52, "name": "extra.png", "mimeType": "image/png"},
                    ],
                }
            )

        panel = self.page.detail_panel
        panel.render_detail(detail("[!diagram.png!]"))
        self._app.processEvents()

        self.assertTrue(panel.attachment_preview.isVisible())
        self.assertNotIn("attachment-51", panel.attachment_preview.text())
        self.assertIn("attachment-52", panel.attachment_preview.text())
        self.assertEqual(len(panel.detail_description._images), 1)

        # 원문 보기에는 본문 그림이 없으므로 첨부 영역에 모두 보인다.
        panel.description_source_toggle.setChecked(True)
        self.assertIn("attachment-51", panel.attachment_preview.text())
        self.assertIn("attachment-52", panel.attachment_preview.text())
        panel.description_source_toggle.setChecked(False)
        self.assertNotIn("attachment-51", panel.attachment_preview.text())

        with patch("src.gui.tracker_detail_panel.WikiContentDialog") as dialog_class:
            panel._open_attachment_preview()
        enlarged = dialog_class.call_args.args[2].html
        self.assertIn("attachment-51", enlarged)
        self.assertIn("attachment-52", enlarged)

        # 그림이 모두 본문에 있으면 첨부 영역은 숨기고 크게 보기 버튼만 남긴다.
        panel.render_detail(detail("[!diagram.png!] [!extra.png!]"))
        self._app.processEvents()

        self.assertFalse(panel.attachment_preview.isVisible())
        self.assertTrue(panel.attachment_preview_button.isVisible())
        self.assertTrue(panel.attachment_preview_button.isEnabled())

    def test_wiki_description_shows_attachment_images_in_place(self) -> None:
        """wiki2html 없이도 `[!파일명#해시!]` 자리에 첨부 이미지가 보인다."""
        self.settings.offline_mode = False
        self.settings.base_url = "https://example.test/cb"
        self.settings.username = "sample"
        self.settings.password = "placeholder"
        images = {41: _png_bytes(4, 4), 42: _png_bytes(6, 3), 43: b"too large to decode"}
        self.page.content_service.download_attachment = (
            lambda _settings, attachment, *, max_bytes: AttachmentResource(
                f"attachment-{attachment.attachment_id}",
                "image/png",
                images[attachment.attachment_id],
            )
        )

        def detail(item_id: int, description: str, attachments: list[dict]) -> TrackerItemDetail:
            return TrackerItemDetail.from_raw(
                {
                    "id": item_id,
                    "name": "Wiki images",
                    "version": 1,
                    "description": description,
                    "descriptionFormat": "Wiki",
                    "tracker": {
                        "id": 24680001,
                        "name": "Offline Requirements",
                        "project": {"id": 246800, "name": "Offline Project"},
                    },
                    "attachments": attachments,
                }
            )

        panel = self.page.detail_panel
        panel.render_detail(
            detail(
                1210,
                "[!image.png#bbbb1111bbbb1111!]\n[!broken.png!]",
                [
                    {"id": 41, "name": "image.png", "mimeType": "image/png", "md5": "aaaa0000aaaa0000"},
                    {"id": 42, "name": "image.png", "mimeType": "image/png", "md5": "bbbb1111bbbb1111"},
                    {"id": 43, "name": "broken.png", "mimeType": "image/png"},
                ],
            )
        )
        self._app.processEvents()

        chosen = panel.detail_description._images.get(
            QUrl("cb-attachment://" + wiki_image_resource_key("image.png", "bbbb1111bbbb1111")).toString()
        )
        self.assertIsNotNone(chosen)
        self.assertEqual((chosen.width(), chosen.height()), (6, 3))
        self.assertIn(
            wiki_image_resource_key("image.png", "bbbb1111bbbb1111"),
            [resource.resource_key for resource in panel.preview_resources],
        )
        # 그리지 못한 그림은 본문 자리에 이유가 나오도록 넘긴다.
        self.assertIn("attachment-43", panel._failed_preview_resources)
        self.assertEqual(len(panel.detail_description._images), 1)

        # 해시 없는 같은 이름이라도 앞 아이템의 그림이 남지 않는다.
        panel.render_detail(detail(1211, "[!image.png!]", []))
        self._app.processEvents()

        self.assertEqual(panel.detail_description._images, {})

    def test_detail_dialog_is_built_with_the_real_class(self) -> None:
        """상세 창을 진짜 클래스로 만들어 본다.

        다른 테스트는 TrackerItemDetailDialog 를 통째로 patch 하므로 생성자가
        한 번도 불리지 않는다. 그래서 parent 처럼 생성자에서만 드러나는 잘못된
        인자를 잡지 못한다. 여기서는 exec 만 막고 실제로 만든다.
        """
        self.page.activate()
        self.page.hierarchy_panel.item_tree.setCurrentItem(self.page.hierarchy_panel.item_tree.topLevelItem(0))
        self._app.processEvents()
        detail = self.page.detail_panel._current_detail
        self.assertIsNotNone(detail)

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
        try:
            dialog = opened[0]
            self.assertIn(str(detail.item_id), dialog.windowTitle())
            self.assertIs(dialog.parent(), self.page)
            # 설명과 필드 표는 각자 탭에서 창 높이를 쓴다.
            self.assertEqual(dialog.tabs.tabText(0), "설명")
            self.assertEqual(dialog.tabs.tabText(1), "필드")
            self.assertTrue(dialog.tabs.widget(0).isAncestorOf(dialog.description_view))
            self.assertTrue(dialog.tabs.widget(1).isAncestorOf(dialog.fields_table))
            self.assertGreater(dialog.fields_table.rowCount(), 0)
        finally:
            # 진짜 창이라 닫아 둔다. 파괴는 부모인 page 가 맡는다.
            opened[0].close()
            self._app.processEvents()

    def test_baseline_detail_star_shows_state_but_cannot_change_it(self) -> None:
        stored = WorkspaceFavorites().with_item(FavoriteItem(9001001, "Vehicle requirements"))
        page, saved, _holder = self._favorites_page({TEST_MODE_FAVORITES_KEY: stored.to_payload()})
        hierarchy = page.hierarchy_panel
        hierarchy.hierarchy_source_combo.setCurrentIndex(hierarchy.hierarchy_source_combo.findData(24681001))
        hierarchy.reload_roots_button.click()
        self._app.processEvents()
        hierarchy.item_tree.setCurrentItem(hierarchy.item_tree.topLevelItem(0))
        self._app.processEvents()
        star = page.detail_panel.detail_favorite_button

        self.assertEqual(page.detail_panel.baseline_id, 24681001)
        self.assertEqual(star.text(), "★")
        self.assertFalse(star.isEnabled())
        self.assertIn("Baseline", star.toolTip())
        # Baseline 이름으로 즐겨찾기 이름을 바꾸지 않는다.
        self.assertEqual(saved, [])

    def test_detail_dialog_lists_the_tracker_tree_and_opens_selected_items(self) -> None:
        """새 창 옆의 계층 트리로 아이템을 옮겨 다니고, 앞뒤 기록과 선택이 함께 움직인다."""
        self.page.activate()
        workspace_tree = self.page.hierarchy_panel.item_tree
        root = workspace_tree.topLevelItem(0)
        workspace_tree.setCurrentItem(root)
        root.setExpanded(True)
        self._app.processEvents()

        dialog = self._open_real_detail_dialog()

        self.assertTrue(dialog.tree_pane.isVisible())
        self.assertIn("Offline Requirements", dialog.tree_label.text())
        self.assertEqual(dialog.item_tree.topLevelItemCount(), workspace_tree.topLevelItemCount())
        self.assertTrue(dialog.item_tree.topLevelItem(0).isExpanded())
        self.assertEqual(dialog.item_tree.currentItem().text(1), "9001001")

        dialog.item_tree.setCurrentItem(self._dialog_tree_item(dialog, 9001002))
        self._app.processEvents()

        self.assertEqual(dialog.detail.item_id, 9001002)
        self.assertTrue(dialog.back_button.isEnabled())

        dialog.back_button.click()
        self._app.processEvents()

        self.assertEqual(dialog.detail.item_id, 9001001)
        self.assertEqual(dialog.item_tree.currentItem().text(1), "9001001")

        # 아직 받지 않은 하위는 펼칠 때 작업공간과 같은 조회로 불러온다.
        steering = self._dialog_tree_item(dialog, 9001003)
        steering.setExpanded(True)
        self._app.processEvents()

        self.assertEqual(steering.childCount(), 1)
        self.assertEqual(steering.child(0).text(1), "9001004")

    def test_children_arriving_after_the_dialog_closes_are_only_cached(self) -> None:
        """새 창이 파괴된 뒤 하위 조회가 끝나도 사라진 트리 항목은 건드리지 않고 캐시만 남긴다."""
        self.page.activate()
        workspace_tree = self.page.hierarchy_panel.item_tree
        workspace_tree.setCurrentItem(workspace_tree.topLevelItem(0))
        self._app.processEvents()
        dialog = self._open_real_detail_dialog()
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]

        dialog.item_tree.topLevelItem(0).setExpanded(True)
        self.assertEqual(len(tasks), 1)
        dialog.close()
        dialog.deleteLater()
        self._app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        tasks[0].finish()

        self.assertEqual(len(self.page.hierarchy_panel.child_cache()[9001001]), 2)

    def test_closed_detail_dialog_is_destroyed_and_late_results_are_ignored(self) -> None:
        """닫은 상세 창은 작업공간 아래에 남지 않고, 그 뒤 도착한 조회 결과는 창을 건드리지 않는다."""
        self.page.activate()
        workspace_tree = self.page.hierarchy_panel.item_tree
        workspace_tree.setCurrentItem(workspace_tree.topLevelItem(0))
        workspace_tree.topLevelItem(0).setExpanded(True)
        self._app.processEvents()
        dialog = self._open_real_detail_dialog()
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        dialog.item_tree.setCurrentItem(self._dialog_tree_item(dialog, 9001002))
        self.assertEqual(len(tasks), 1)

        dialog.close()
        self._app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.assertFalse(isValid(dialog))
        self.assertEqual(self.page.findChildren(TrackerItemDetailDialog), [])
        tasks[0].finish()

    def test_closed_wiki_field_dialog_is_destroyed_and_late_images_are_ignored(self) -> None:
        self.settings.offline_mode = False
        self.settings.base_url = "https://example.test/cb"
        self.settings.username = "sample"
        self.settings.password = "placeholder"
        panel = self.page.detail_panel
        panel.render_detail(
            TrackerItemDetail.from_raw(
                {
                    "id": 1230,
                    "name": "Wiki field",
                    "version": 1,
                    "tracker": {
                        "id": 24680001,
                        "name": "Offline Requirements",
                        "project": {"id": 246800, "name": "Offline Project"},
                    },
                }
            )
        )
        panel.content_service.render_wiki = lambda *_args: WikiRenderResult(
            html='<img src="cb-attachment://late-image">',
            resources=(WikiResourceReference("late-image", "https://example.test/cb/attachment/9"),),
        )
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        panel.content_service.download_resource = lambda *_args, **_kwargs: AttachmentResource(
            "late-image", "image/png", _png_bytes(2, 2)
        )
        opened: list[WikiContentDialog] = []

        class _NonModalWikiDialog(WikiContentDialog):
            def exec(self) -> int:
                opened.append(self)
                return 0

        field = TrackerFieldValue(
            field_id=77, name="Notes", type_name="WikiTextFieldValue", display_value="[!x.png!]"
        )
        with patch("src.gui.tracker_detail_panel.WikiContentDialog", _NonModalWikiDialog):
            panel._open_wiki_field(field)
            tasks.pop(0).finish()
        self.assertEqual(len(opened), 1)
        self._app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.assertFalse(isValid(opened[0]))
        # 창이 사라진 뒤 이미지 받기가 끝나도 오류 없이 넘어간다.
        tasks.pop(0).finish()

    def test_detail_dialog_has_no_tree_from_another_point_in_time(self) -> None:
        """상세와 작업공간 트리의 시점이 다르면 트리를 두지 않는다. 트리로 옮기면 두 시점이 섞인다."""
        self.page.activate()
        workspace_tree = self.page.hierarchy_panel.item_tree
        workspace_tree.setCurrentItem(workspace_tree.topLevelItem(0))
        self._app.processEvents()
        panel = self.page.detail_panel
        # 현재 상태 트리 옆의 Baseline 상세
        panel.render_detail(panel.current_detail, baseline_id=24681001)

        dialog = self._open_real_detail_dialog()

        self.assertFalse(dialog.tree_pane.isVisible())
        self.assertEqual(dialog.item_tree.topLevelItemCount(), 0)
        dialog.close()

        # Baseline 트리 옆의 현재 상태 상세
        self._show_baseline_hierarchy()
        workspace_tree.setCurrentItem(workspace_tree.topLevelItem(0))
        self._app.processEvents()
        panel.render_detail(panel.current_detail, baseline_id=None)

        dialog = self._open_real_detail_dialog()

        self.assertFalse(dialog.tree_pane.isVisible())
        self.assertEqual(dialog.item_tree.topLevelItemCount(), 0)

    def test_baseline_detail_from_received_items_says_so_and_refresh_asks_the_server(self) -> None:
        """받아 둔 Baseline 목록에서 꺼낸 상세는 그렇다고 알리고, 상세 새로고침만 서버에서 새로 받는다."""
        load_detail = self.service.load_detail
        refresh_flags: list[bool] = []

        def listed_load_detail(settings, item_id, *, baseline_id=None, refresh=False):
            refresh_flags.append(refresh)
            detail = load_detail(settings, item_id, baseline_id=baseline_id, refresh=refresh)
            return detail if refresh else replace(detail, baseline_list_received_at="2026-09-30T05:00:00+00:00")

        self.service.load_detail = listed_load_detail  # type: ignore[method-assign]
        self.page.activate()
        self._show_baseline_hierarchy()
        workspace_tree = self.page.hierarchy_panel.item_tree
        workspace_tree.setCurrentItem(workspace_tree.topLevelItem(0))
        self._app.processEvents()
        panel = self.page.detail_panel

        self.assertEqual(refresh_flags, [False])
        self.assertIn("읽기 전용 · Baseline #24681001", panel.detail_warning.text())
        self.assertIn("받아 둔 Baseline 목록(2026-09-30", panel.detail_warning.text())
        # 안내가 가리키는 버튼이 실제로 있는 버튼이어야 한다.
        self.assertIn(f"'{panel.detail_refresh_button.text()}' 버튼", panel.detail_warning.text())

        panel.detail_refresh_button.click()
        self._app.processEvents()

        self.assertEqual(refresh_flags, [False, True])
        self.assertEqual(panel.baseline_id, 24681001)
        self.assertNotIn("받아 둔 Baseline 목록", panel.detail_warning.text())

    def test_baseline_detail_dialog_history_marks_changes_after_the_baseline(self) -> None:
        """Baseline 상세 창도 변경 이력을 조회하고, 그 Baseline 버전 뒤의 변경을 나눠 보인다."""
        self.page.activate()
        self._show_baseline_hierarchy()
        workspace_tree = self.page.hierarchy_panel.item_tree
        workspace_tree.setCurrentItem(workspace_tree.topLevelItem(0))
        self._app.processEvents()
        dialog = self._open_real_detail_dialog()

        dialog.tabs.setCurrentWidget(dialog.history_tab)
        self._app.processEvents()

        self.assertEqual(dialog.detail.version, 1)
        activity = dialog.activity_panel
        self.assertEqual(dialog.detail.version, 1)
        self.assertEqual(activity.baseline_combo.currentData(), 24681001)
        self.assertEqual(
            activity.status_label.text(),
            "#9001001 · Offline Requirements Baseline 이후 · 버전 2건 · 필드 변경 3건 · 바뀐 필드 3개"
            " · 댓글 2건 · 첨부 1건 · 댓글·첨부는 현재 목록이며 Baseline 시점 내용이 아닙니다",
        )
        view = activity.history_view
        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            [
                "[Baseline 이후] 댓글 · 2026-07-20 10:00 · Sample User B",
                "[Baseline 이후] 댓글 · 2026-07-20 09:10 · Sample User A",
                "[Baseline 이후] 버전 3 · 2026-07-20 09:00 · Sample User A · 필드 1개",
                "[Baseline 이후] 버전 2 · 2026-07-19 08:00 · Sample User B · 필드 2개",
                "[Baseline 이후] 첨부 · 2026-07-18 11:00 · anonymous-spec.txt · 2,048 bytes · text/plain",
            ],
        )
        self.assertIn("관계 조회를 지원하지 않습니다", dialog.relations_status.text())

    def test_detail_dialog_export_records_the_items_own_tracker(self) -> None:
        """상세 창에서 다른 트래커의 아이템으로 옮겨 간 뒤에도 기록은 그 아이템의 트래커와 프로젝트를 가리킨다."""
        self.page.activate()
        page_tracker = self.page._current_tracker
        other = TrackerItemDetail.from_raw(
            {
                "id": 9009001,
                "name": "Other tracker item",
                "version": 1,
                "tracker": {
                    "id": 24689999,
                    "name": "Other Tracker",
                    "project": {"id": 246899, "name": "Other Project"},
                },
            }
        )
        dialog = TrackerItemDetailDialog(other, description_html="<p>x</p>")
        self.addCleanup(dialog.close)
        request = object()

        with patch("src.gui.tracker_detail_dialog.run_activity_export") as export:
            self.page.detail_dialog.export_activity(dialog, request)  # type: ignore[arg-type]

        self.assertNotEqual(page_tracker.tracker_id, 24689999)
        kwargs = export.call_args.kwargs
        self.assertEqual(
            (kwargs["tracker_id"], kwargs["tracker_name"], kwargs["project_id"], kwargs["project_name"]),
            (24689999, "Other Tracker", 246899, "Other Project"),
        )

    def test_detail_dialog_export_falls_back_to_the_workspace_tracker(self) -> None:
        """아이템 응답에 트래커가 없으면 작업공간에서 고른 트래커로 적는다."""
        self.page.activate()
        tracker = self.page._current_tracker
        bare = TrackerItemDetail.from_raw({"id": 9009002, "name": "Bare item", "version": 1})
        dialog = TrackerItemDetailDialog(bare, description_html="<p>x</p>")
        self.addCleanup(dialog.close)

        with patch("src.gui.tracker_detail_dialog.run_activity_export") as export:
            self.page.detail_dialog.export_activity(dialog, object())  # type: ignore[arg-type]

        kwargs = export.call_args.kwargs
        self.assertEqual((kwargs["tracker_id"], kwargs["tracker_name"]), (tracker.tracker_id, tracker.name))

    def test_baseline_detail_dialog_lists_the_baseline_tree_and_stays_at_that_baseline(self) -> None:
        """Baseline 상세 창도 그 Baseline 계층을 옆에 두고, 트리로 옮겨도 같은 Baseline 시점을 연다."""
        load_detail = self.service.load_detail
        requested_baselines: list[int | None] = []

        def recording_load_detail(settings, item_id, *, baseline_id=None, refresh=False):
            requested_baselines.append(baseline_id)
            return load_detail(settings, item_id, baseline_id=baseline_id, refresh=refresh)

        self.service.load_detail = recording_load_detail  # type: ignore[method-assign]
        attachment_requests: list[int] = []
        self.page.content_service.load_attachments = (  # type: ignore[method-assign]
            lambda _settings, item_id, **_kwargs: attachment_requests.append(item_id) or ()
        )
        self.page.activate()
        self._show_baseline_hierarchy()
        workspace_tree = self.page.hierarchy_panel.item_tree
        root = workspace_tree.topLevelItem(0)
        workspace_tree.setCurrentItem(root.child(0))
        self._app.processEvents()
        self.assertEqual(self.page.detail_panel.baseline_id, 24681001)

        dialog = self._open_real_detail_dialog()

        self.assertTrue(dialog.tree_pane.isVisible())
        self.assertIn("Offline Requirements Baseline", dialog.tree_label.text())
        # Baseline 이름이 붙어 길어진 제목이 트리 칸을 처음 폭(300px)보다 넓히지 않는다.
        self.assertLessEqual(dialog.tree_pane.minimumSizeHint().width(), 300)
        self.assertEqual(dialog.item_tree.currentItem().text(1), "9001002")
        requested_baselines.clear()

        dialog.item_tree.setCurrentItem(self._dialog_tree_item(dialog, 9001003))
        self._app.processEvents()

        self.assertEqual(requested_baselines, [24681001])
        self.assertEqual(dialog.detail.item_id, 9001003)
        self.assertEqual(dialog.detail.summary.name, "Steering system baseline")
        self.assertIn("Baseline #24681001", dialog.heading.text())
        self.assertIn("과거 시점", dialog.relations_status.text())
        self.assertIn("과거 시점", dialog.comments_status.text())
        self.assertEqual(attachment_requests, [])

        dialog.back_button.click()
        self._app.processEvents()

        self.assertEqual(dialog.detail.item_id, 9001002)
        self.assertEqual(requested_baselines, [24681001, 24681001])
        self.assertEqual(dialog.item_tree.currentItem().text(1), "9001002")

    def test_wiki_field_dialog_is_built_with_the_real_class(self) -> None:
        """Wiki 필드 창도 진짜 클래스로 만들어 본다.

        [[test_detail_dialog_is_built_with_the_real_class]] 와 같은 이유다.
        이 창들은 지금까지 patch 로만 확인해서 생성자 인자가 검증된 적이 없다.
        """
        self.page.activate()
        self.page.hierarchy_panel.item_tree.setCurrentItem(self.page.hierarchy_panel.item_tree.topLevelItem(0))
        self._app.processEvents()
        field = TrackerFieldValue(
            field_id=101,
            name="Risk Level",
            type_name="WikiTextFieldValue",
            display_value="본문",
        )
        opened: list[WikiContentDialog] = []

        class _NonModalDialog(WikiContentDialog):
            def exec(self) -> int:
                opened.append(self)
                return 0

        with patch("src.gui.tracker_detail_panel.WikiContentDialog", _NonModalDialog):
            self.page.detail_panel._open_wiki_field(field)

        self.assertEqual(len(opened), 1)
        try:
            self.assertIs(opened[0].parent(), self.page.detail_panel)
        finally:
            opened[0].close()
            self._app.processEvents()

    def test_popped_out_editor_window_is_built_with_the_real_class(self) -> None:
        """수정 창 분리도 진짜 클래스로 만들어 본다."""
        self.page.activate()
        self.page.hierarchy_panel.item_tree.setCurrentItem(self.page.hierarchy_panel.item_tree.topLevelItem(0))
        self._app.processEvents()

        self.page.detail_panel._show_editor_in_window()
        self._app.processEvents()

        dialog = self.page.detail_panel._editor_dialog
        self.assertIsNotNone(dialog)
        try:
            self.assertIs(dialog.parent(), self.page.detail_panel)
        finally:
            self.page.detail_panel._restore_editor_panel()
            self._app.processEvents()

    def test_related_detail_failure_keeps_dialog_session_and_context_usable(self) -> None:
        detail = _detail(1205, "Current", version=3)
        dialog = TrackerItemDetailDialog(detail, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(1204, 2)
        session.navigate(detail.item_id, detail.version)
        dialog.set_navigation_state(
            can_go_back=session.can_go_back,
            can_go_forward=session.can_go_forward,
        )
        tasks: list[_DeferredTask] = []
        alerts = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.error_notifier = lambda title, message: alerts.append((title, message))

        self.page.detail_dialog.navigate(dialog, session, 1206)

        self.assertEqual(session.current.item_id, 1205)
        self.assertEqual(dialog.detail.item_id, 1205)
        self.assertFalse(dialog.back_button.isEnabled())
        tasks[0].emit_failure(ValueError("not found"))

        self.assertEqual(session.current.item_id, 1205)
        self.assertEqual(dialog.detail.item_id, 1205)
        self.assertTrue(dialog.back_button.isEnabled())
        self.assertFalse(dialog.forward_button.isEnabled())
        self.assertEqual(
            alerts,
            [
                (
                    "관련 아이템 상세 조회 실패",
                    "관련 아이템 상세 조회 실패: not found",
                )
            ],
        )
        self.assertIn("탭을 열면", dialog.relations_status.text())

        self.page.synchronous = True
        self.page.context_service.load_relations = lambda *_args, **_kwargs: (
            ItemRelationsSnapshot.from_raw(
                {
                    "downstreamReferences": [
                        {"itemRevision": {"id": 1207, "name": "Related"}}
                    ]
                }
            )
        )
        self.page.detail_dialog.load_context(dialog, session, "relations")
        self.assertEqual(dialog.relations_table.rowCount(), 1)
        dialog.close()

    def test_history_navigation_failure_does_not_commit_peeked_target(self) -> None:
        detail = _detail(1205, "Current", version=3)
        dialog = TrackerItemDetailDialog(detail, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(1204, 2)
        session.navigate(detail.item_id, detail.version)
        dialog.set_navigation_state(
            can_go_back=session.can_go_back,
            can_go_forward=session.can_go_forward,
        )
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]

        self.page.detail_dialog.navigate_history(dialog, session, back=True)
        tasks[0].emit_failure(ValueError("not found"))

        self.assertEqual(session.current.item_id, 1205)
        self.assertEqual(dialog.detail.item_id, 1205)
        self.assertTrue(session.can_go_back)
        self.assertFalse(session.can_go_forward)
        dialog.close()

    def test_related_detail_success_commits_session_after_loading(self) -> None:
        current = _detail(1205, "Current", version=3)
        target = _detail(1206, "Target", version=4)
        dialog = TrackerItemDetailDialog(current, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(current.item_id, current.version)
        self.page.service.load_detail = lambda *_args, **_kwargs: target

        with patch.object(self.page.detail_dialog, "hydrate") as hydrate:
            self.page.detail_dialog.navigate(dialog, session, target.item_id)

        self.assertEqual(session.current.item_id, target.item_id)
        self.assertEqual(dialog.detail.item_id, target.item_id)
        self.assertTrue(session.can_go_back)
        self.assertTrue(dialog.back_button.isEnabled())
        hydrate.assert_called_once()
        dialog.close()

    def test_comment_response_from_previous_generation_is_discarded_after_aba_navigation(self) -> None:
        current = _detail(1205, "Current", version=3)
        other = _detail(1206, "Other", version=1)
        dialog = TrackerItemDetailDialog(current, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(current.item_id, current.version)
        snapshot = ItemCommentsSnapshot.from_raw([{"id": 1, "comment": "old"}])
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.comment_service.load_comments = lambda *_args, **_kwargs: snapshot

        self.page.detail_dialog.load_comments(dialog, session)
        session.navigate(other.item_id, other.version)
        dialog.replace_detail(other, description_html="<p>Other</p>")
        session.back()
        dialog.replace_detail(current, description_html="<p>Current</p>")
        tasks[0].finish()

        self.assertEqual(dialog.comment_views, {})
        self.assertEqual(dialog._comments_state, "idle")

        self.page.detail_dialog.load_comments(dialog, session)
        tasks[1].finish()
        self.assertEqual(set(dialog.comment_views), {"1"})
        dialog.close()

    def test_comment_image_from_previous_generation_is_discarded(self) -> None:
        current = _detail(1205, "Current", version=3)
        other = _detail(1206, "Other", version=1)
        dialog = TrackerItemDetailDialog(current, description_html="<p>Current</p>")
        dialog.show()
        session = TrackerItemDetailSession(current.item_id, current.version)
        snapshot = ItemCommentsSnapshot.from_raw(
            [
                {
                    "id": 1,
                    "comment": "image",
                    "attachments": [
                        {
                            "id": 28,
                            "name": "evidence.png",
                            "mimeType": "image/png",
                        }
                    ],
                }
            ]
        )
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.comment_service.load_comments = lambda *_args, **_kwargs: snapshot
        self.page.content_service.download_attachment = (
            lambda *_args, **_kwargs: AttachmentResource(
                "attachment-28",
                "image/png",
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                ),
            )
        )

        self.page.detail_dialog.load_comments(dialog, session)
        tasks[0].finish()
        self.assertEqual(len(tasks), 2)

        session.navigate(other.item_id, other.version)
        dialog.replace_detail(other, description_html="<p>Other</p>")
        session.back()
        dialog.replace_detail(current, description_html="<p>Current</p>")
        with patch.object(dialog, "add_comment_resource", wraps=dialog.add_comment_resource) as add_resource:
            tasks[1].finish()

        add_resource.assert_not_called()
        self.assertEqual(dialog.comment_views, {})
        dialog.close()

    def test_baseline_detail_does_not_mix_current_attachment_metadata(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1203,
                "name": "Historical detail",
                "version": 2,
                "tracker": {
                    "id": 24680001,
                    "name": "Offline Requirements",
                    "project": {"id": 246800, "name": "Offline Project"},
                },
                "attachments": [{"id": 28, "name": "latest.png"}],
            }
        )

        self.page.detail_panel.render_detail(detail, baseline_id=24681001)

        self.assertEqual(self.page.detail_panel.attachment_table.rowCount(), 0)
        self.assertIn("Baseline", self.page.detail_panel.attachment_status_label.text())
        self.assertFalse(self.page.detail_panel.attachment_reload_button.isEnabled())

    def test_inline_image_budget_limits_scheduled_downloads_to_five_images(self) -> None:
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1204,
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
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        self.page.content_service.download_resource = lambda *args, **kwargs: AttachmentResource(
            kwargs["resource_key"],
            "image/png",
            b"not-executed",
        )
        result = WikiRenderResult(
            html="<p>images</p>",
            resources=tuple(
                WikiResourceReference(f"image-{index}", f"https://example.test/cb/attachment/{index}")
                for index in range(6)
            ),
        )

        self.page.detail_panel._load_inline_resources(result, self.page.detail_panel.detail_description, detail, None)

        self.assertEqual(len(tasks), 5)
        self.assertEqual(len(self.page.detail_panel._inline_resource_reservations), 5)

    def test_inline_images_beyond_five_load_as_earlier_ones_finish(self) -> None:
        """동시에는 5개만 받고, 끝나는 대로 나머지를 받는다. 6번째부터 빈 칸으로 남지 않는다."""
        detail = self._image_test_detail(1301)
        panel = self.page.detail_panel
        requested = self._record_image_downloads()
        tasks = self._deferred_tasks()

        panel._load_inline_resources(self._server_images(8), panel.detail_description, detail, None)
        self.assertEqual(len(tasks), 5)
        self._finish_all(tasks)

        self.assertEqual(sorted(requested), sorted(f"image-{index}" for index in range(8)))

    def test_attachment_previews_beyond_five_are_all_loaded(self) -> None:
        detail = self._image_test_detail(1302)
        panel = self.page.detail_panel
        requested = self._record_image_downloads()
        tasks = self._deferred_tasks()

        panel._load_attachment_previews(self._image_attachments(7), detail)
        self._finish_all(tasks)

        self.assertEqual(len(requested), 7)
        self.assertEqual(len(panel._attachment_preview_resources), 7)

    def test_description_images_load_even_when_attachment_previews_came_first(self) -> None:
        """먼저 온 첨부 미리보기가 자리를 다 써도 설명 이미지를 끝내 받는다."""
        detail = self._image_test_detail(1303)
        panel = self.page.detail_panel
        requested = self._record_image_downloads()
        tasks = self._deferred_tasks()

        panel._load_attachment_previews(self._image_attachments(6), detail)
        panel._load_inline_resources(self._server_images(3), panel.detail_description, detail, None)
        self._finish_all(tasks)

        self.assertTrue({"image-0", "image-1", "image-2"} <= set(requested))
        self.assertEqual(len(panel._attachment_preview_resources), 6)

    def test_reopening_wiki_field_dialog_does_not_use_up_the_image_budget(self) -> None:
        """닫은 Wiki 필드 창의 이미지 바이트를 돌려받는다. 다시 열 때마다 쌓여 결국 아무 그림도 못 받던 문제."""
        self._image_test_detail(1304)
        panel = self.page.detail_panel
        self._record_image_downloads()
        panel.content_service.render_wiki = lambda *_args: WikiRenderResult(
            html='<img src="cb-attachment://image-0">',
            resources=(WikiResourceReference("image-0", "https://example.test/cb/attachment/0"),),
        )

        class _NonModalWikiDialog(WikiContentDialog):
            def exec(self) -> int:
                return 0

        field = TrackerFieldValue(field_id=78, name="Notes", type_name="WikiTextFieldValue", display_value="x")
        with patch("src.gui.tracker_detail_panel.WikiContentDialog", _NonModalWikiDialog):
            for _ in range(3):
                panel._open_wiki_field(field)
                self._app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.assertEqual(panel._inline_image_bytes, 0)

    def test_detail_dialog_shows_server_rendered_description_images(self) -> None:
        """서버가 렌더링한 설명의 그림을 상세 창에도 받아 넣는다."""
        self._wiki_image_detail(1311)
        self._record_image_downloads()
        self.page.content_service.render_wiki = lambda *_args: WikiRenderResult(
            html='<img src="cb-attachment://image-0"><img src="cb-attachment://image-1">',
            resources=tuple(
                WikiResourceReference(f"image-{index}", f"https://example.test/cb/attachment/{index}")
                for index in range(2)
            ),
        )
        self.page.content_service.load_attachments = lambda *_args, **_kwargs: ()

        dialog = self._open_real_detail_dialog()

        self.assertEqual(
            {key for key in dialog.description_view._images if "image-" in key},
            {"cb-attachment://image-0", "cb-attachment://image-1"},
        )

    def test_detail_dialog_loads_attachments_the_panel_has_not_received_yet(self) -> None:
        """창을 연 뒤에 끝나는 첨부도 창에 들어온다. 열 때 패널 상태만 복사하면 비어 있다."""
        self._wiki_image_detail(1312)
        self._record_image_downloads()
        attachments = self._image_attachments(3)
        self.page.content_service.load_attachments = lambda *_args, **_kwargs: attachments
        self.assertEqual(self.page.detail_panel.attachments, ())

        dialog = self._open_real_detail_dialog()

        self.assertEqual(dialog.image_combo.count(), 3)

    def test_detail_dialog_keeps_other_images_when_one_fails_and_shows_more_than_five(self) -> None:
        self._wiki_image_detail(1313)
        requested = self._record_image_downloads()
        attachments = self._image_attachments(7)
        self.page.content_service.load_attachments = lambda *_args, **_kwargs: attachments
        succeed = self.page.content_service.download_attachment

        def flaky_download(settings, attachment, *, max_bytes):
            if attachment.attachment_id == 502:
                raise ConnectionError("temporary")
            return succeed(settings, attachment, max_bytes=max_bytes)

        self.page.content_service.download_attachment = flaky_download

        dialog = self._open_real_detail_dialog()

        self.assertEqual(dialog.image_combo.count(), 6)
        self.assertEqual(len(requested), 6)

    def test_detail_dialog_comment_images_beyond_five_are_all_loaded(self) -> None:
        self._wiki_image_detail(1314)
        requested = self._record_image_downloads()
        self.page.content_service.load_attachments = lambda *_args, **_kwargs: ()
        self.page.comment_service.load_comments = lambda *_args, **_kwargs: ItemCommentsSnapshot.from_raw(
            [
                {
                    "id": 1,
                    "comment": "images",
                    "attachments": [
                        {"id": 600 + index, "name": f"comment-{index}.png", "mimeType": "image/png", "size": 100}
                        for index in range(7)
                    ],
                }
            ]
        )
        dialog = self._open_real_detail_dialog()
        tasks = self._deferred_tasks()

        dialog.tabs.setCurrentWidget(dialog.comments_tab)
        self._app.processEvents()
        self._finish_all(tasks)

        self.assertEqual(len([key for key in requested if key.startswith("attachment-6")]), 7)
        self.assertEqual(len(dialog.comment_views["1"]._images), 7)

    def test_scheduled_inline_downloads_keep_their_own_resource(self) -> None:
        """예약된 다운로드가 각자의 참조를 들고 있는지 확인한다.

        콜백이 반복문 변수를 늦게 바인딩하면 5개가 모두 마지막 이미지를 내려받는다.
        화면에는 이미지가 그려지므로 눈으로는 알아채기 어렵다.
        """
        detail = TrackerItemDetail.from_raw(
            {
                "id": 1205,
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
        tasks: list[_DeferredTask] = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(
            _DeferredTask(operation)
        ) or tasks[-1]
        requested_keys: list[str] = []

        def record_download(*_args, **kwargs) -> AttachmentResource:
            requested_keys.append(kwargs["resource_key"])
            return AttachmentResource(kwargs["resource_key"], "image/png", b"payload")

        self.page.content_service.download_resource = record_download
        result = WikiRenderResult(
            html="<p>images</p>",
            resources=tuple(
                WikiResourceReference(f"image-{index}", f"https://example.test/cb/attachment/{index}")
                for index in range(3)
            ),
        )

        self.page.detail_panel._load_inline_resources(result, self.page.detail_panel.detail_description, detail, None)
        for task in tasks:
            task.operation()

        self.assertEqual(requested_keys, ["image-0", "image-1", "image-2"])

    def test_description_links_open_items_and_save_attachments(self) -> None:
        """설명 속 아이템 링크는 ID 바로 열기처럼 열고, 첨부 링크는 저장 흐름으로 넘긴다."""
        self.page.activate()
        panel = self.page.detail_panel
        panel.load_detail(9001001)
        panel._attachments = (AttachmentSummary(31, "계획서.docx", size=2048),)

        with patch.object(panel, "save_attachment") as save_attachment:
            panel.detail_description.anchorClicked.emit(QUrl("cb-link:attachment/31/계획서.docx"))
        save_attachment.assert_called_once_with(AttachmentSummary(31, "계획서.docx", size=2048))

        panel.detail_description.anchorClicked.emit(QUrl("cb-link:item/9101002"))

        self.assertEqual(panel.detail_id_badge.text(), "#9101002")
        self.assertEqual(self.page.tracker_combo.currentData(), 24680002)


if __name__ == "__main__":
    unittest.main()
