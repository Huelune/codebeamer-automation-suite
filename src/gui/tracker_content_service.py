from __future__ import annotations

import contextlib
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.codebeamer_client import CodebeamerClient

from .payload_values import optional_int
from .service_core import _build_gui_client
from .tracker_content_models import AttachmentResource
from .tracker_content_models import AttachmentSummary
from .tracker_content_models import WikiRenderContext
from .tracker_content_models import WikiRenderResult
from .wiki_renderer import codebeamer_wiki_to_html
from .wiki_renderer import sanitize_server_wiki_html


MAX_INLINE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ITEM_INLINE_IMAGE_BYTES = 50 * 1024 * 1024
_IMAGE_MIME_TYPES = {
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
    "image/webp",
}


def _attachment_payloads(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [value for value in payload if isinstance(value, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("attachments", "attachmentRefs", "items", "references", "content"):
        values = payload.get(key)
        if isinstance(values, list):
            return [value for value in values if isinstance(value, dict)]
    return []


class TrackerContentService:
    """Wiki 렌더링과 첨부 리소스를 tracker query와 분리해 조회한다."""

    def __init__(self, client_factory=CodebeamerClient, logger=None) -> None:
        self.client_factory = client_factory
        self.logger = logger
        self._render_cache: dict[tuple[Any, ...], WikiRenderResult] = {}
        self._attachment_cache: dict[tuple[Any, ...], tuple[AttachmentSummary, ...]] = {}
        self._resource_cache: dict[tuple[Any, ...], AttachmentResource] = {}

    @staticmethod
    def _settings_key(settings) -> tuple[Any, ...]:
        return (
            bool(getattr(settings, "offline_mode", False)),
            bool(getattr(settings, "server_wiki_html_enabled", False)),
            str(getattr(settings, "base_url", "") or "").strip().rstrip("/"),
            str(getattr(settings, "username", "") or "").strip(),
            str(getattr(settings, "offline_query_data_path", "") or "").strip(),
        )

    def clear_cache(self) -> None:
        self._render_cache.clear()
        self._attachment_cache.clear()
        self._resource_cache.clear()

    def clear_item_cache(self, settings, item_id: int) -> None:
        settings_key = self._settings_key(settings)
        normalized_item_id = int(item_id)
        self._render_cache = {
            key: value
            for key, value in self._render_cache.items()
            if not (key[0] == settings_key and key[2] == normalized_item_id)
        }
        self._attachment_cache.pop((settings_key, normalized_item_id), None)
        self._resource_cache.clear()

    def _client(self, settings):
        return _build_gui_client(settings, self.client_factory, self.logger)

    def render_wiki(
        self,
        settings,
        context: WikiRenderContext | None,
        markup: str,
    ) -> WikiRenderResult:
        source = str(markup or "")
        if (
            context is None
            or bool(getattr(settings, "offline_mode", False))
            or not bool(getattr(settings, "server_wiki_html_enabled", False))
        ):
            return WikiRenderResult(
                html=codebeamer_wiki_to_html(source),
                used_fallback=True,
            )
        digest = sha256(source.encode("utf-8")).hexdigest()
        key = (
            self._settings_key(settings),
            context.project_id,
            context.item_id,
            context.item_version,
            context.baseline_id,
            digest,
        )
        cached = self._render_cache.get(key)
        if cached is not None:
            return cached
        try:
            raw_html = self._client(settings).render_wiki_to_html(
                context.project_id,
                context_id=context.item_id,
                context_version=context.item_version,
                markup=source,
                rendering_context_type=context.rendering_context_type,
            )
            sanitized = sanitize_server_wiki_html(
                raw_html,
                base_url=str(getattr(settings, "base_url", "") or ""),
            )
            warning = ""
            resources = sanitized.resources
            if context.baseline_id is not None and resources:
                resources = ()
                warning = "과거 첨부 revision 계약이 확인되지 않아 Baseline 이미지는 자동으로 불러오지 않습니다."
            result = WikiRenderResult(
                html=sanitized.html,
                resources=resources,
                warning=warning,
            )
        except Exception:
            result = WikiRenderResult(
                html=codebeamer_wiki_to_html(source),
                used_fallback=True,
                warning="서버 Wiki 렌더링에 실패해 제한된 로컬 렌더링을 사용합니다.",
            )
        self._render_cache[key] = result
        return result

    def load_attachments(
        self,
        settings,
        item_id: int,
        *,
        raw_payload: dict[str, Any] | None = None,
        baseline_id: int | None = None,
    ) -> tuple[AttachmentSummary, ...]:
        if baseline_id is not None:
            return ()
        key = (self._settings_key(settings), int(item_id))
        cached = self._attachment_cache.get(key)
        if cached is not None:
            return cached
        payloads = _attachment_payloads((raw_payload or {}).get("attachments"))
        if not payloads and not bool(getattr(settings, "offline_mode", False)):
            payloads = _attachment_payloads(
                self._client(settings).get_item_attachments(int(item_id))
            )
        attachments: list[AttachmentSummary] = []
        for payload in payloads:
            attachment_id = optional_int(payload.get("id") or payload.get("attachmentId"))
            if attachment_id is None:
                continue
            attachments.append(
                AttachmentSummary(
                    attachment_id=attachment_id,
                    name=str(payload.get("name") or payload.get("fileName") or f"첨부 {attachment_id}"),
                    version=optional_int(payload.get("version")),
                    size=optional_int(payload.get("size") or payload.get("fileSize")),
                    mime_type=str(payload.get("mimeType") or payload.get("contentType") or ""),
                    modified_at=str(payload.get("modifiedAt") or ""),
                    md5=str(payload.get("md5") or ""),
                    download_url=str(payload.get("downloadUrl") or payload.get("uri") or ""),
                )
            )
        result = tuple(attachments)
        self._attachment_cache[key] = result
        return result

    def download_resource(
        self,
        settings,
        *,
        resource_key: str,
        source_url: str,
        max_bytes: int = MAX_INLINE_IMAGE_BYTES,
        image_only: bool = True,
    ) -> AttachmentResource:
        key = (
            self._settings_key(settings),
            resource_key,
            str(source_url or ""),
            int(max_bytes),
            bool(image_only),
        )
        cached = self._resource_cache.get(key)
        if cached is not None:
            return cached
        mime_type, data = self._client(settings).download_authenticated_resource(
            source_url,
            max_bytes=max_bytes,
        )
        normalized_mime = mime_type.split(";", 1)[0].strip().casefold()
        if image_only and normalized_mime not in _IMAGE_MIME_TYPES:
            raise ValueError("첨부 리소스가 지원되는 이미지 형식이 아닙니다.")
        result = AttachmentResource(resource_key, normalized_mime, data)
        self._resource_cache[key] = result
        return result

    def download_attachment(
        self,
        settings,
        attachment: AttachmentSummary,
        *,
        max_bytes: int,
    ) -> AttachmentResource:
        resource_key = f"attachment-{attachment.attachment_id}"
        key = (
            self._settings_key(settings),
            resource_key,
            attachment.version,
            attachment.md5,
            int(max_bytes),
            False,
        )
        cached = self._resource_cache.get(key)
        if cached is not None:
            return cached
        mime_type, data = self._client(settings).download_attachment_content(
            attachment.attachment_id,
            max_bytes=max_bytes,
        )
        normalized_mime = mime_type.split(";", 1)[0].strip().casefold()
        result = AttachmentResource(resource_key, normalized_mime, data)
        self._resource_cache[key] = result
        return result

    def save_attachment(
        self,
        settings,
        attachment: AttachmentSummary,
        output_path: str,
        *,
        max_bytes: int = 1024 * 1024 * 1024,
    ) -> int:
        """첨부를 대상 폴더의 임시 파일에 쓴 뒤 원자적으로 교체한다."""
        target = Path(str(output_path)).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        resource = self.download_attachment(
            settings,
            attachment,
            max_bytes=max_bytes,
        )
        temporary_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=str(target.parent),
                delete=False,
            ) as handle:
                temporary_path = handle.name
                handle.write(resource.data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
            temporary_path = ""
            return len(resource.data)
        finally:
            if temporary_path:
                with contextlib.suppress(OSError):
                    os.unlink(temporary_path)


__all__ = [
    "MAX_INLINE_IMAGE_BYTES",
    "MAX_ITEM_INLINE_IMAGE_BYTES",
    "TrackerContentService",
]
