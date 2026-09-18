from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

from .tracker_content_models import WikiResourceReference


_WIKI_TYPE_NAMES = {
    "wiki",
    "wikitext",
    "wikitextfield",
    "wikitextfieldvalue",
}
_STYLE_OPEN_RE = re.compile(
    r"%%\((?P<style>(?:[^()]|\([^()]*\)){1,1000})\)"
)
_NAMED_STYLE_OPEN_RE = re.compile(r"%%(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*")
_SAFE_STYLE_NAMES = {
    "background-color",
    "color",
    "font-size",
    "font-style",
    "font-weight",
    "text-decoration",
}
_SAFE_COLOR_RE = re.compile(
    r"(?:#[0-9a-fA-F]{3,8}|[A-Za-z]{1,24}|rgba?\([0-9.,%\s]+\))\Z"
)
_SAFE_SIZE_RE = re.compile(r"(?:\d+(?:\.\d+)?(?:px|pt|em|rem|%)|small|medium|large)\Z")
_SAFE_WEIGHT_RE = re.compile(r"(?:normal|bold|bolder|lighter|[1-9]00)\Z")
_SAFE_FONT_STYLE_RE = re.compile(r"(?:normal|italic|oblique)\Z")
_SAFE_DECORATION_RE = re.compile(
    r"(?:none|underline|line-through|underline line-through|line-through underline)\Z"
)
_THEME_FOREGROUND_COLORS = {
    "black",
    "white",
    "#000",
    "#000000",
    "#fff",
    "#ffffff",
}
_NAMED_COLOR_STYLES = {
    "black",
    "blue",
    "cyan",
    "gray",
    "green",
    "magenta",
    "orange",
    "pink",
    "red",
    "white",
    "yellow",
}


def _normalized_type_name(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if "<" in text:
        text = text.split("<", 1)[0].strip()
    return text.replace("_", "").replace("-", "")


def is_explicit_wiki_type(value: Any) -> bool:
    """메타데이터가 Wiki 형식을 명시한 경우만 참을 반환한다."""
    return _normalized_type_name(value) in _WIKI_TYPE_NAMES


def payload_uses_wiki(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(
        is_explicit_wiki_type(payload.get(key))
        for key in ("type", "valueModel", "format", "descriptionFormat")
    )


def _safe_style_value(name: str, value: str) -> str | None:
    normalized = value.strip().casefold()
    blocked_tokens = ("url(", "expression", "javascript")
    if not normalized or any(token in normalized for token in blocked_tokens):
        return None
    if name in {"color", "background-color"}:
        if not _SAFE_COLOR_RE.fullmatch(normalized):
            return None
        if name == "color" and normalized in _THEME_FOREGROUND_COLORS:
            return None
        return normalized
    if name == "font-size" and _SAFE_SIZE_RE.fullmatch(normalized):
        return normalized
    if name == "font-weight" and _SAFE_WEIGHT_RE.fullmatch(normalized):
        return normalized
    if name == "font-style" and _SAFE_FONT_STYLE_RE.fullmatch(normalized):
        return normalized
    if name == "text-decoration" and _SAFE_DECORATION_RE.fullmatch(normalized):
        return normalized
    return None


def sanitize_wiki_style(style: str) -> str:
    declarations: list[str] = []
    for declaration in str(style or "").split(";"):
        if ":" not in declaration:
            continue
        raw_name, raw_value = declaration.split(":", 1)
        name = raw_name.strip().casefold()
        if name not in _SAFE_STYLE_NAMES:
            continue
        value = _safe_style_value(name, raw_value)
        if value is not None:
            declarations.append(f"{name}: {value}")
    return "; ".join(declarations)


def _render_basic_markup(text: str) -> str:
    rendered = escape(text, quote=False)
    rendered = re.sub(r"__([^_\n]+?)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"''([^'\n]+?)''", r"<em>\1</em>", rendered)
    rendered = re.sub(r"\{\{([^{}\n]+?)\}\}", r"<code>\1</code>", rendered)
    return rendered.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _table_cells(line: str, marker: str) -> list[str]:
    source = line.strip()
    if not source.startswith(marker):
        return []
    return [part.strip() for part in source[len(marker) :].split(marker)]


def _render_local_tables(source: str) -> str:
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rendered: list[str] = []
    plain: list[str] = []

    def flush_plain() -> None:
        if plain:
            rendered.append(_render_basic_markup("\n".join(plain)))
            plain.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if not (line.strip().startswith("||") or line.strip().startswith("|")):
            plain.append(line)
            index += 1
            continue
        table_rows: list[tuple[bool, list[str]]] = []
        while index < len(lines):
            candidate = lines[index].strip()
            if candidate.startswith("||"):
                cells = _table_cells(candidate, "||")
                table_rows.append((True, cells))
            elif candidate.startswith("|"):
                cells = _table_cells(candidate, "|")
                table_rows.append((False, cells))
            else:
                break
            index += 1
        if not table_rows or any(not cells for _header, cells in table_rows):
            plain.extend(lines[index - len(table_rows) : index])
            continue
        flush_plain()
        rows_html: list[str] = []
        for header, cells in table_rows:
            tag = "th" if header else "td"
            cells_html = "".join(
                f'<{tag} style="border: 1px solid #999; padding: 4px">'
                f"{_render_basic_markup(cell)}</{tag}>"
                for cell in cells
            )
            rows_html.append(f"<tr>{cells_html}</tr>")
        rendered.append(
            '<table style="border-collapse: collapse; margin: 4px 0">'
            + "".join(rows_html)
            + "</table>"
        )
    flush_plain()
    return "".join(rendered)


def _closing_index(source: str, start: int) -> tuple[int, int] | None:
    candidates = [
        (index, len(token))
        for token in ("%%", "%!")
        if (index := source.find(token, start)) >= 0
    ]
    return min(candidates) if candidates else None


def codebeamer_wiki_to_html(value: Any) -> str:
    """안전한 Codebeamer Wiki 스타일 일부를 Qt rich text용 HTML로 바꾼다."""
    source = str(value or "")
    parts: list[str] = []
    position = 0
    while position < len(source):
        style_match = _STYLE_OPEN_RE.search(source, position)
        named_match = _NAMED_STYLE_OPEN_RE.search(source, position)
        matches = [match for match in (style_match, named_match) if match is not None]
        if not matches:
            parts.append(_render_local_tables(source[position:]))
            break
        opening = min(matches, key=lambda match: match.start())
        parts.append(_render_local_tables(source[position : opening.start()]))
        closing = _closing_index(source, opening.end())
        if closing is None:
            parts.append(_render_basic_markup(source[opening.start() :]))
            break
        closing_position, closing_length = closing
        content = _render_basic_markup(source[opening.end() : closing_position])
        if opening.re is _STYLE_OPEN_RE:
            style = sanitize_wiki_style(opening.group("style"))
        else:
            name = opening.group("name").casefold()
            style = f"color: {name}" if name in _NAMED_COLOR_STYLES else ""
            if name in _THEME_FOREGROUND_COLORS:
                style = ""
        parts.append(f'<span style="{style}">{content}</span>' if style else content)
        position = closing_position + closing_length
    return "".join(parts)


@dataclass(frozen=True)
class SanitizedWikiHtml:
    html: str
    resources: tuple[WikiResourceReference, ...]


_ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "span",
    "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "u", "ul",
}
_VOID_TAGS = {"br", "hr", "img"}
_DROP_CONTENT_TAGS = {"embed", "form", "iframe", "object", "script", "style"}
_SAFE_URL_SCHEMES = {"", "http", "https"}


class _WikiHtmlSanitizer(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.base_origin = urlparse(self.base_url)
        self.parts: list[str] = []
        self.resources: list[WikiResourceReference] = []
        self._drop_depth = 0

    def _safe_url(self, value: str) -> str | None:
        parsed = urlparse(value.strip())
        if parsed.scheme.casefold() not in _SAFE_URL_SCHEMES:
            return None
        return value.strip()

    def _image_reference(self, value: str) -> WikiResourceReference | None:
        safe = self._safe_url(value)
        if not safe or not self.base_url:
            return None
        absolute = urljoin(f"{self.base_url}/", safe)
        parsed = urlparse(absolute)
        if (parsed.scheme.casefold(), parsed.netloc.casefold()) != (
            self.base_origin.scheme.casefold(),
            self.base_origin.netloc.casefold(),
        ):
            return None
        path_and_query = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        lowered = path_and_query.casefold()
        if "attachment" not in lowered and "displaydocument" not in lowered:
            return None
        key = sha256(absolute.encode("utf-8")).hexdigest()[:24]
        attachment_match = re.search(r"(?:artifact_id=|/attachment/)(\d+)", lowered)
        return WikiResourceReference(
            resource_key=key,
            source_url=absolute,
            attachment_id=(int(attachment_match.group(1)) if attachment_match else None),
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in _DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth or normalized_tag not in _ALLOWED_TAGS:
            return
        safe_attrs: list[tuple[str, str]] = []
        if normalized_tag == "img":
            source = next((value or "" for name, value in attrs if name.casefold() == "src"), "")
            reference = self._image_reference(source)
            if reference is None:
                self.parts.append('<span class="blocked-image">[외부 또는 확인되지 않은 이미지 차단]</span>')
                return
            self.resources.append(reference)
            safe_attrs.append(("src", f"cb-attachment://{reference.resource_key}"))
        for raw_name, raw_value in attrs:
            name = raw_name.casefold()
            value = str(raw_value or "")
            if name.startswith("on") or name in {"src", "srcset"}:
                continue
            if name == "href" and normalized_tag == "a":
                safe_url = self._safe_url(value)
                if safe_url is not None:
                    safe_attrs.append(("href", safe_url))
                continue
            if name == "style":
                style = sanitize_wiki_style(value)
                if style:
                    safe_attrs.append(("style", style))
                continue
            if name in {"alt", "title"} or (
                normalized_tag in {"td", "th"}
                and name in {"colspan", "rowspan"}
                and value.isdigit()
            ):
                safe_attrs.append((name, value))
        attrs_html = "".join(
            f' {name}="{escape(value, quote=True)}"' for name, value in safe_attrs
        )
        self.parts.append(f"<{normalized_tag}{attrs_html}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in _DROP_CONTENT_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth or normalized_tag not in _ALLOWED_TAGS or normalized_tag in _VOID_TAGS:
            return
        self.parts.append(f"</{normalized_tag}>")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.parts.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self._drop_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._drop_depth:
            self.parts.append(f"&#{name};")


def sanitize_server_wiki_html(value: Any, *, base_url: str) -> SanitizedWikiHtml:
    parser = _WikiHtmlSanitizer(base_url)
    parser.feed(str(value or ""))
    parser.close()
    unique_resources = tuple(
        {reference.resource_key: reference for reference in parser.resources}.values()
    )
    return SanitizedWikiHtml("".join(parser.parts), unique_resources)


__all__ = [
    "codebeamer_wiki_to_html",
    "is_explicit_wiki_type",
    "payload_uses_wiki",
    "sanitize_server_wiki_html",
    "sanitize_wiki_style",
]
