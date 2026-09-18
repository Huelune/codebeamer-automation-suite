from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from .tracker_content_models import AttachmentSummary


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _person(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("displayName") or value.get("name") or value.get("email") or value.get("id"))
    return _text(value)


@dataclass(frozen=True)
class ItemComment:
    comment_id: str
    author: str = ""
    created_at: str = ""
    modified_at: str = ""
    reply_to_id: str = ""
    format_name: str = ""
    body: str = ""
    attachments: tuple[AttachmentSummary, ...] = field(default_factory=tuple)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ItemComment:
        raw_id = raw.get("id") or raw.get("commentId")
        attachments: list[AttachmentSummary] = []
        raw_attachments = raw.get("attachments")
        if isinstance(raw_attachments, dict):
            raw_attachments = raw_attachments.get("attachments") or raw_attachments.get("items") or []
        if isinstance(raw_attachments, list):
            for value in raw_attachments:
                if not isinstance(value, dict):
                    continue
                attachment_id = _optional_int(value.get("id") or value.get("attachmentId"))
                if attachment_id is None:
                    continue
                attachments.append(
                    AttachmentSummary(
                        attachment_id=attachment_id,
                        name=_text(value.get("name") or value.get("fileName")) or f"첨부 {attachment_id}",
                        version=_optional_int(value.get("version")),
                        size=_optional_int(value.get("size") or value.get("fileSize")),
                        mime_type=_text(value.get("mimeType") or value.get("contentType")),
                        modified_at=_text(value.get("modifiedAt")),
                        md5=_text(value.get("md5")),
                    )
                )
        reply_to = raw.get("replyTo") or raw.get("parent") or raw.get("replyToId")
        if isinstance(reply_to, dict):
            reply_to = reply_to.get("id") or reply_to.get("commentId")
        return cls(
            comment_id=_text(raw_id),
            author=_person(raw.get("createdBy") or raw.get("author")),
            created_at=_text(raw.get("createdAt")),
            modified_at=_text(raw.get("modifiedAt")),
            reply_to_id=_text(reply_to),
            format_name=_text(raw.get("commentFormat") or raw.get("format") or raw.get("markupFormat")),
            body=_text(raw.get("comment") or raw.get("body") or raw.get("markup") or raw.get("text")),
            attachments=tuple(attachments),
        )


@dataclass(frozen=True)
class ItemCommentsSnapshot:
    comments: tuple[ItemComment, ...] = field(default_factory=tuple)

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | list[Any]) -> ItemCommentsSnapshot:
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, dict):
            candidates = next(
                (raw.get(key) for key in ("comments", "items", "content") if isinstance(raw.get(key), list)), []
            )
        else:
            candidates = []
        comments = [ItemComment.from_raw(value) for value in candidates if isinstance(value, dict)]
        comments.sort(key=lambda value: (value.created_at, value.comment_id))
        by_id = {comment.comment_id: comment for comment in comments if comment.comment_id}
        children: dict[str, list[ItemComment]] = {}
        roots: list[ItemComment] = []
        for comment in comments:
            if comment.reply_to_id and comment.reply_to_id in by_id:
                children.setdefault(comment.reply_to_id, []).append(comment)
            else:
                roots.append(comment)
        ordered: list[ItemComment] = []
        visited: set[str] = set()

        def append_thread(comment: ItemComment) -> None:
            identity = comment.comment_id
            if identity and identity in visited:
                return
            if identity:
                visited.add(identity)
            ordered.append(comment)
            for reply in children.get(identity, ()):
                append_thread(reply)

        for root in roots:
            append_thread(root)
        for comment in comments:
            append_thread(comment)
        return cls(tuple(ordered))


__all__ = ["ItemComment", "ItemCommentsSnapshot"]
