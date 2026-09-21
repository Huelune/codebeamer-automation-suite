from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class WikiRenderContext:
    project_id: int
    item_id: int
    item_version: int
    baseline_id: int | None = None
    rendering_context_type: str = "TRACKER_ITEM"


@dataclass(frozen=True)
class WikiResourceReference:
    resource_key: str
    source_url: str
    attachment_id: int | None = None


@dataclass(frozen=True)
class WikiRenderResult:
    html: str
    resources: tuple[WikiResourceReference, ...] = field(default_factory=tuple)
    used_fallback: bool = False
    warning: str = ""


# 인라인으로 그릴 수 있는 이미지 첨부를 가려낼 때 쓴다.
ATTACHMENT_IMAGE_MIME_TYPES = {
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
ATTACHMENT_IMAGE_SUFFIXES = (".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp")


@dataclass(frozen=True)
class AttachmentSummary:
    attachment_id: int
    name: str
    version: int | None = None
    size: int | None = None
    mime_type: str = ""
    modified_at: str = ""
    md5: str = ""
    download_url: str = ""


@dataclass(frozen=True)
class AttachmentResource:
    resource_key: str
    mime_type: str
    data: bytes = field(repr=False)


__all__ = [
    "AttachmentResource",
    "AttachmentSummary",
    "WikiRenderContext",
    "WikiRenderResult",
    "WikiResourceReference",
]
