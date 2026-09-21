"""트래커 작업공간의 상세 창을 맡는 controller.

상세 창은 열기, 관계·이력 탭 조회, 앞뒤 탐색, 본문과 댓글 채우기까지
한 덩어리로 움직인다. 작업공간 화면 클래스에서 이 덩어리만 떼어냈다.

조회 로직은 `tracker_query_service` 와 각 service 에 있고 여기는 화면 조립만
한다. 작업공간의 상태와 service 를 그대로 쓰므로 page 를 참조로 받는다.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape
from typing import TYPE_CHECKING

from .tracker_comment_models import ItemComment
from .tracker_comment_models import ItemCommentsSnapshot
from .tracker_content_models import ATTACHMENT_IMAGE_MIME_TYPES
from .tracker_content_models import AttachmentResource
from .tracker_content_models import AttachmentSummary
from .tracker_content_models import WikiRenderResult
from .tracker_content_models import WikiResourceReference
from .tracker_content_service import MAX_INLINE_IMAGE_BYTES
from .tracker_content_service import MAX_ITEM_INLINE_IMAGE_BYTES
from .tracker_item_detail_dialog import TrackerItemDetailDialog
from .tracker_item_detail_session import TrackerItemDetailSession
from .tracker_query_models import TrackerItemDetail
from .wiki_renderer import codebeamer_wiki_to_html
from .wiki_renderer import is_explicit_wiki_type


if TYPE_CHECKING:
    from .tracker_workspace import TrackerWorkspacePage


class DetailDialogController:
    """상세 창의 열기, 탐색, 본문 채우기를 맡는다."""

    def __init__(self, page: TrackerWorkspacePage) -> None:
        self.page = page

    def open_dialog(self, _checked: bool = False) -> None:
        detail = self.page._current_detail
        if detail is None:
            return
        if self.page._description_uses_wiki:
            description_html = (
                self.page._description_render_result.html
                if self.page._description_render_result is not None
                else codebeamer_wiki_to_html(self.page._description_text)
            )
        else:
            description_html = (
                "<p>" + escape(self.page._description_text).replace("\n", "<br>") + "</p>"
            )
        dialog = TrackerItemDetailDialog(
            detail,
            description_html=description_html,
            attachments=self.page._attachments,
            image_resources=tuple(self.page._attachment_preview_resources.values()),
            baseline_id=self.page._detail_baseline_id,
            parent=self.page,
        )
        session = TrackerItemDetailSession(detail.item_id, detail.version)
        dialog.comments_requested.connect(
            lambda force=False: self.load_comments(
                dialog,
                session,
                force=force,
            )
        )
        dialog.comment_attachment_save_requested.connect(self.page._save_attachment)
        dialog.set_navigation_state(can_go_back=False, can_go_forward=False)
        dialog.context_tab_requested.connect(
            lambda kind, force=False: self.load_context(
                dialog, session, kind, force=force
            )
        )
        dialog.related_item_requested.connect(
            lambda item_id: self.navigate(dialog, session, item_id)
        )
        dialog.navigate_back_requested.connect(
            lambda: self.navigate_history(dialog, session, back=True)
        )
        dialog.navigate_forward_requested.connect(
            lambda: self.navigate_history(dialog, session, back=False)
        )
        dialog.finished.connect(lambda _result: session.invalidate())
        dialog.exec()

    def load_context(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        kind: str,
        *,
        force: bool = False,
    ) -> None:
        if dialog.baseline_id is not None or kind not in {"relations", "history"}:
            return
        detail = dialog.detail
        generation = session.generation
        dialog.set_context_loading(kind)
        settings = self.page.settings_provider()

        def current() -> bool:
            return (
                dialog.isVisible()
                and session.generation == generation
                and session.current.item_id == detail.item_id
            )

        def loaded(result) -> None:
            if not current():
                return
            if kind == "relations":
                dialog.set_relations(result)
            else:
                dialog.set_history(result)

        def failed(exc: Exception) -> None:
            if current():
                dialog.set_context_error(kind, str(exc))

        load_context = (
            self.page.context_service.load_relations
            if kind == "relations"
            else self.page.context_service.load_history
        )

        def operation():
            return load_context(
                settings,
                detail.item_id,
                detail.version,
                force=force,
            )

        self.page._submit(f"detail_dialog_{kind}", operation, loaded, failed)

    def navigate(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        item_id: int,
    ) -> None:
        target_item_id = int(item_id)
        if target_item_id == session.current.item_id:
            return

        def commit(detail: TrackerItemDetail) -> None:
            session.navigate(detail.item_id, detail.version)

        self.load_item(
            dialog,
            session,
            target_item_id,
            commit,
        )

    def navigate_history(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        *,
        back: bool,
    ) -> None:
        target = session.peek_back() if back else session.peek_forward()
        if target is None:
            return

        def commit(_detail: TrackerItemDetail) -> None:
            if back:
                session.back()
            else:
                session.forward()

        self.load_item(
            dialog,
            session,
            target.item_id,
            commit,
        )

    def load_item(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        item_id: int,
        commit: Callable[[TrackerItemDetail], None],
    ) -> None:
        source_generation = session.generation
        source_item_id = session.current.item_id
        settings = self.page.settings_provider()
        dialog.set_navigation_state(
            can_go_back=False,
            can_go_forward=False,
        )

        def is_pending() -> bool:
            return (
                dialog.isVisible()
                and session.generation == source_generation
                and session.current.item_id == source_item_id
                and dialog.detail.item_id == source_item_id
            )

        def loaded(detail: TrackerItemDetail) -> None:
            if not is_pending():
                return
            commit(detail)
            generation = session.generation
            description_html = (
                codebeamer_wiki_to_html(detail.description)
                if is_explicit_wiki_type(detail.description_format)
                else "<p>" + escape(detail.description).replace("\n", "<br>") + "</p>"
            )
            dialog.replace_detail(detail, description_html=description_html)
            dialog.set_navigation_state(
                can_go_back=session.can_go_back,
                can_go_forward=session.can_go_forward,
            )
            self.hydrate(dialog, session, detail, generation)

        def failed(exc: Exception) -> None:
            if not is_pending():
                return
            dialog.set_navigation_state(
                can_go_back=session.can_go_back,
                can_go_forward=session.can_go_forward,
            )
            self.page._show_error(exc, prefix="관련 아이템 상세 조회 실패")

        self.page._submit(
            "detail_dialog_item",
            lambda: self.page.service.load_detail(settings, item_id),
            loaded,
            failed,
        )

    def hydrate(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        detail: TrackerItemDetail,
        generation: int,
    ) -> None:
        settings = self.page.settings_provider()

        def current() -> bool:
            return dialog.isVisible() and session.generation == generation and dialog.detail.item_id == detail.item_id

        if is_explicit_wiki_type(detail.description_format):
            self.page._submit(
                "detail_dialog_wiki",
                lambda: self.page.content_service.render_wiki(
                    settings, self.page._wiki_context(detail, None), detail.description
                ),
                lambda result: dialog.set_description_html(result.html) if current() else None,
                lambda _exc: None,
            )

        def attachments_loaded(attachments: tuple[AttachmentSummary, ...]) -> None:
            if not current():
                return
            images = tuple(
                value
                for value in attachments
                if self.page._is_attachment_image(value)
                and (value.size is None or value.size <= MAX_INLINE_IMAGE_BYTES)
            )
            if not images:
                dialog.set_images(attachments, ())
                return

            def resources_loaded(resources: tuple[AttachmentResource, ...]) -> None:
                if current():
                    dialog.set_images(attachments, resources)

            self.page._submit(
                "detail_dialog_images",
                lambda: tuple(
                    self.page.content_service.download_attachment(settings, image, max_bytes=MAX_INLINE_IMAGE_BYTES)
                    for image in images[: max(1, MAX_ITEM_INLINE_IMAGE_BYTES // MAX_INLINE_IMAGE_BYTES)]
                ),
                resources_loaded,
                lambda _exc: dialog.set_images(attachments, ()) if current() else None,
            )

        self.page._submit(
            "detail_dialog_attachments",
            lambda: self.page.content_service.load_attachments(
                settings, detail.item_id, raw_payload=detail.raw_payload
            ),
            attachments_loaded,
            lambda _exc: None,
        )

    def load_comments(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        *,
        force: bool = False,
    ) -> None:
        if dialog.baseline_id is not None:
            return
        detail = dialog.detail
        item_id = detail.item_id
        version = detail.version
        generation = session.generation
        settings = self.page.settings_provider()
        dialog.set_comments_loading()

        def current() -> bool:
            return (
                dialog.isVisible()
                and session.generation == generation
                and session.current.item_id == item_id
                and dialog.detail.item_id == item_id
                and dialog.detail.version == version
            )

        def loaded(snapshot: ItemCommentsSnapshot) -> None:
            if not current():
                return
            dialog.set_comments(snapshot)
            self.hydrate_comments(
                dialog,
                session,
                detail,
                snapshot,
                generation,
            )

        self.page._submit(
            "detail_dialog_comments",
            lambda: self.page.comment_service.load_comments(settings, item_id, version, force=force),
            loaded,
            lambda exc: dialog.set_comments_error(str(exc)) if current() else None,
        )

    def hydrate_comments(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        detail: TrackerItemDetail,
        snapshot: ItemCommentsSnapshot,
        generation: int,
    ) -> None:
        settings = self.page.settings_provider()
        item_id = detail.item_id
        version = detail.version
        loaded_bytes = {"value": 0}
        reserved = {"value": 0}

        def current() -> bool:
            return (
                dialog.isVisible()
                and session.generation == generation
                and session.current.item_id == item_id
                and dialog.detail.item_id == item_id
                and dialog.detail.version == version
            )

        def apply_resource(comment_id: str, resource: AttachmentResource) -> None:
            reserved["value"] = max(0, reserved["value"] - MAX_INLINE_IMAGE_BYTES)
            if not current() or loaded_bytes["value"] + len(resource.data) > MAX_ITEM_INLINE_IMAGE_BYTES:
                return
            if dialog.add_comment_resource(comment_id, resource):
                loaded_bytes["value"] += len(resource.data)

        def reserve() -> bool:
            if loaded_bytes["value"] + reserved["value"] + MAX_INLINE_IMAGE_BYTES > MAX_ITEM_INLINE_IMAGE_BYTES:
                return False
            reserved["value"] += MAX_INLINE_IMAGE_BYTES
            return True

        for comment in snapshot.comments:
            if is_explicit_wiki_type(comment.format_name):
                def rendered(result: WikiRenderResult, *, selected=comment) -> None:
                    if not current():
                        return
                    dialog.set_comment_html(selected.comment_id, result.html)
                    for reference in result.resources:
                        if not reserve():
                            break

                        def inline_loaded(resource: AttachmentResource, *, comment_id=selected.comment_id) -> None:
                            apply_resource(comment_id, resource)

                        def inline_failed(_exc: Exception) -> None:
                            reserved["value"] = max(0, reserved["value"] - MAX_INLINE_IMAGE_BYTES)

                        def download_inline(
                            value: WikiResourceReference = reference,
                        ) -> AttachmentResource:
                            return self.page.content_service.download_resource(
                                settings,
                                resource_key=value.resource_key,
                                source_url=value.source_url,
                            )

                        self.page._submit(
                            f"comment_inline:{selected.comment_id}:{reference.resource_key}",
                            download_inline,
                            inline_loaded,
                            inline_failed,
                        )

                def render_comment(selected: ItemComment = comment) -> WikiRenderResult:
                    return self.page.content_service.render_wiki(
                        settings,
                        self.page._wiki_context(detail, None),
                        selected.body,
                    )

                self.page._submit(
                    f"comment_wiki:{comment.comment_id}",
                    render_comment,
                    rendered,
                    lambda _exc: None,
                )

            for attachment in comment.attachments:
                if not self.page._is_attachment_image(attachment):
                    continue
                if attachment.size is not None and attachment.size > MAX_INLINE_IMAGE_BYTES:
                    continue
                if not reserve():
                    break
                resource_key = f"comment-{comment.comment_id}-attachment-{attachment.attachment_id}"

                def attachment_loaded(
                    resource: AttachmentResource,
                    *,
                    comment_id=comment.comment_id,
                    alias=resource_key,
                ) -> None:
                    normalized_mime = str(resource.mime_type or "").split(";", 1)[0].strip().casefold()
                    if normalized_mime not in ATTACHMENT_IMAGE_MIME_TYPES:
                        reserved["value"] = max(0, reserved["value"] - MAX_INLINE_IMAGE_BYTES)
                        return
                    apply_resource(
                        comment_id,
                        AttachmentResource(alias, resource.mime_type, resource.data),
                    )

                def attachment_failed(_exc: Exception) -> None:
                    reserved["value"] = max(0, reserved["value"] - MAX_INLINE_IMAGE_BYTES)

                def download_comment_attachment(
                    selected: AttachmentSummary = attachment,
                ) -> AttachmentResource:
                    return self.page.content_service.download_attachment(
                        settings,
                        selected,
                        max_bytes=MAX_INLINE_IMAGE_BYTES,
                    )

                self.page._submit(
                    f"comment_attachment:{comment.comment_id}:{attachment.attachment_id}",
                    download_comment_attachment,
                    attachment_loaded,
                    attachment_failed,
                )
