from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urljoin
from urllib.parse import urlparse

from .tracker_content_models import AttachmentResource
from .tracker_content_models import AttachmentSummary
from .tracker_content_models import WikiImageReference
from .tracker_content_models import WikiLink
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
# 스타일 블록을 열거나 닫는 표시. 어느 쪽인지는 뒤따르는 글자로 정한다.
_STYLE_MARK_RE = re.compile(r"%%|%!")
_SAFE_STYLE_NAMES = {
    "background-color",
    "color",
    "font-size",
    "font-style",
    "font-weight",
    "text-align",
    "text-decoration",
    "vertical-align",
}
# 붙여넣은 표는 배경색을 `background` 축약형으로 적는다.
_STYLE_NAME_ALIASES = {"background": "background-color"}
_SAFE_COLOR_RE = re.compile(
    r"(?:#[0-9a-fA-F]{3,8}|[A-Za-z]{1,24}|rgba?\([0-9.,%\s]+\))\Z"
)
_SAFE_SIZE_RE = re.compile(r"(?:\d+(?:\.\d+)?(?:px|pt|em|rem|%)|small|medium|large)\Z")
_SAFE_WEIGHT_RE = re.compile(r"(?:normal|bold|bolder|lighter|[1-9]00)\Z")
_SAFE_FONT_STYLE_RE = re.compile(r"(?:normal|italic|oblique)\Z")
_SAFE_DECORATION_RE = re.compile(
    r"(?:none|underline|line-through|underline line-through|line-through underline)\Z"
)
_SAFE_TEXT_ALIGN_RE = re.compile(r"(?:left|right|center|justify)\Z")
_SAFE_VERTICAL_ALIGN_RE = re.compile(r"(?:top|middle|bottom|baseline)\Z")
# `~` 뒤의 기호는 Wiki 문법이 아니라 글자 그대로 보여 준다.
_ESCAPED_MARKUP_RE = re.compile(r"~([-_'{}\[\]|%\\*#!^~])")
_LINE_BREAK_RE = re.compile(r"\\\\[ \t]*\n?")
# `[!Primary Architecture.png#a114...!]`처럼 첨부 이름 뒤에 내용 해시가 붙는다.
# 너비 같은 다른 매개변수가 붙은 모양은 확인되지 않아 원문 그대로 둔다.
_WIKI_IMAGE_RE = re.compile(r"(?<!~)\[!([^!\[\]|#\n]+?)(?:#([0-9A-Fa-f]{8,64}))?!\]")
_IMAGE_SLOT_RE = re.compile("\x00(\\d+)\x00")
# `[표시|대상]`, `[대상]`. `[!` 이미지, `[{` plugin, `[[` 이스케이프는 링크가 아니다.
_WIKI_LINK_RE = re.compile(r"(?<![~\[])\[(?![!{\[])([^\[\]\n]+?)\]")
_ITEM_LINK_RE = re.compile(r"(?:CB|ISSUE):(\d+)", re.IGNORECASE)
WIKI_LINK_SCHEME = "cb-link"
_TABLE_PLUGIN_OPEN_RE = re.compile(r"\[\{Table(?=[\s}])")
_PLUGIN_PARAM_RE = re.compile(r"""(\w+)\s*=\s*(?:'([^']*)'|"([^"]*)"|([^\s'"]+))""")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_TABLE_CELL_STYLE = "border: 1px solid #999; padding: 4px"
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
    if name == "text-align" and _SAFE_TEXT_ALIGN_RE.fullmatch(normalized):
        return normalized
    if name == "vertical-align" and _SAFE_VERTICAL_ALIGN_RE.fullmatch(normalized):
        return normalized
    return None


def sanitize_wiki_style(style: str) -> str:
    # 같은 속성이 여러 번 나오면 CSS처럼 뒤의 값을 쓴다.
    declarations: dict[str, str] = {}
    for declaration in str(style or "").split(";"):
        if ":" not in declaration:
            continue
        raw_name, raw_value = declaration.split(":", 1)
        name = raw_name.strip().casefold()
        name = _STYLE_NAME_ALIASES.get(name, name)
        if name not in _SAFE_STYLE_NAMES:
            continue
        value = _safe_style_value(name, raw_value)
        if value is not None:
            declarations[name] = value
    return "; ".join(f"{name}: {value}" for name, value in declarations.items())


def wiki_image_resource_key(name: str, content_hash: str) -> str:
    """본문 이미지 자리의 리소스 이름. 받기 전 자리 표시에 쓰도록 파일 이름을 담는다."""
    return f"wiki-image/{quote(name, safe='')}/{content_hash.casefold()}"


def _image_reference(match: re.Match[str]) -> WikiImageReference | None:
    name = match.group(1).strip()
    # 외부 주소 이미지는 받지 않는다. 첨부 이름만 이미지로 바꾼다.
    if not name or "://" in name:
        return None
    content_hash = match.group(2) or ""
    return WikiImageReference(
        name=name,
        content_hash=content_hash,
        resource_key=wiki_image_resource_key(name, content_hash),
    )


def wiki_image_references(markup: Any) -> tuple[WikiImageReference, ...]:
    """원문이 가리키는 첨부 이미지. 같은 이미지는 한 번만 돌려준다."""
    references: dict[str, WikiImageReference] = {}
    for match in _WIKI_IMAGE_RE.finditer(str(markup or "")):
        reference = _image_reference(match)
        if reference is not None:
            references.setdefault(reference.resource_key, reference)
    return tuple(references.values())


def _matching_attachment(
    reference: WikiImageReference,
    attachments: Iterable[AttachmentSummary],
) -> AttachmentSummary | None:
    """이름이 같은 첨부를 찾는다. 붙여넣은 그림은 이름이 겹치므로 해시가 맞는 것을 먼저 고른다."""
    candidates = [value for value in attachments if value.name == reference.name]
    if not candidates:
        wanted = reference.name.casefold()
        candidates = [value for value in attachments if value.name.casefold() == wanted]
    wanted_hash = reference.content_hash.casefold()
    if wanted_hash:
        for candidate in candidates:
            if candidate.md5.casefold() == wanted_hash:
                return candidate
    return candidates[0] if candidates else None


def resolve_wiki_images(
    markup: Any,
    attachments: Iterable[AttachmentSummary],
    resources: Iterable[AttachmentResource],
) -> tuple[AttachmentResource, ...]:
    """원문의 이미지 자리에 넣을 리소스를 이미 받은 첨부 이미지에서 만든다.

    첨부 영역이 `attachment-{id}`로 받아 둔 데이터를 본문 자리 이름으로 다시 붙일 뿐,
    새로 내려받지 않는다. 짝을 찾지 못한 자리는 보기 화면이 파일 이름으로 표시한다.
    """
    attachment_list = list(attachments)
    by_key = {resource.resource_key: resource for resource in resources}
    resolved: list[AttachmentResource] = []
    for reference in wiki_image_references(markup):
        attachment = _matching_attachment(reference, attachment_list)
        if attachment is None:
            continue
        resource = by_key.get(f"attachment-{attachment.attachment_id}")
        if resource is not None:
            resolved.append(
                AttachmentResource(reference.resource_key, resource.mime_type, resource.data)
            )
    return tuple(resolved)


def _render_image(match: re.Match[str]) -> str:
    reference = _image_reference(match)
    if reference is None:
        return escape(match.group(0), quote=False)
    return (
        f'<img src="cb-attachment://{escape(reference.resource_key, quote=True)}" '
        f'alt="{escape(reference.name, quote=True)}">'
    )


def _link_href(target: str) -> str | None:
    """링크 대상을 이 앱이 여는 주소로 바꾼다. 열 수 없는 대상이면 None."""
    if match := _ITEM_LINK_RE.fullmatch(target):
        return f"{WIKI_LINK_SCHEME}:item/{int(match.group(1))}"
    if target[:4].upper() == "CB:/":
        # `CB:/displayDocument/<파일>?task_id=<아이템>&artifact_id=<첨부>`는 아이템 첨부다.
        parsed = urlparse(target[3:])
        artifact_id = parse_qs(parsed.query).get("artifact_id", [""])[0]
        if not artifact_id.isdigit():
            return None
        name = unquote(parsed.path.rsplit("/", 1)[-1])
        return f"{WIKI_LINK_SCHEME}:attachment/{int(artifact_id)}/{quote(name, safe='')}"
    parsed = urlparse(target)
    if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc:
        return target
    return None


def _render_link(match: re.Match[str]) -> str:
    body = match.group(1)
    label, separator, target = body.partition("|")
    if not separator:
        label = target = body
    href = _link_href(target.strip())
    # Wiki 페이지 이름처럼 이 앱이 열 수 없는 대상은 짐작하지 않고 원문으로 둔다.
    if href is None:
        return escape(match.group(0), quote=False)
    return f'<a href="{escape(href, quote=True)}">{escape(label.strip(), quote=False)}</a>'


def wiki_link_from_url(url: str) -> WikiLink | None:
    """렌더러가 만든 앱 안 링크 주소를 되읽는다. 다른 주소면 None."""
    prefix = f"{WIKI_LINK_SCHEME}:"
    if not url.startswith(prefix):
        return None
    kind, _, rest = url[len(prefix) :].partition("/")
    target_id, _, name = rest.partition("/")
    if kind not in {"item", "attachment"} or not target_id.isdigit():
        return None
    return WikiLink(kind=kind, target_id=int(target_id), name=unquote(name))


def attachment_for_link(
    attachments: Iterable[AttachmentSummary],
    attachment_id: int,
    name: str,
) -> AttachmentSummary:
    """링크가 가리키는 첨부. 현재 아이템 첨부 목록에 있으면 그 정보를 쓴다.

    다른 아이템의 첨부를 가리키는 링크도 첨부 ID로 받을 수 있으므로 목록에 없으면 새로 만든다.
    """
    for attachment in attachments:
        if attachment.attachment_id == attachment_id:
            return attachment
    return AttachmentSummary(attachment_id=attachment_id, name=name or f"첨부 {attachment_id}")


def _render_basic_markup(text: str) -> str:
    source = text.replace("\r\n", "\n").replace("\r", "\n")
    # 이미지·링크 문법은 escape와 강조 치환 전에 자리만 잡아 두었다가 마지막에 되돌린다.
    # 파일 이름 속 `__`나 `&`가 강조·문자 참조로 바뀌지 않는다.
    images: list[str] = []

    def keep(html: str) -> str:
        images.append(html)
        return f"\x00{len(images) - 1}\x00"

    source = _WIKI_IMAGE_RE.sub(lambda match: keep(_render_image(match)), source)
    source = _WIKI_LINK_RE.sub(lambda match: keep(_render_link(match)), source)
    rendered = escape(source, quote=False)
    # 문자 참조로 바꿔 두면 아래 강조 치환에 걸리지 않는다.
    rendered = _ESCAPED_MARKUP_RE.sub(lambda match: f"&#{ord(match.group(1))};", rendered)
    rendered = re.sub(r"__([^_\n]+?)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"''([^'\n]+?)''", r"<em>\1</em>", rendered)
    rendered = re.sub(r"\{\{([^{}\n]+?)\}\}", r"<code>\1</code>", rendered)
    # `\\`는 강제 줄바꿈이다. 바로 뒤 개행과 합쳐 한 번만 바꾼다.
    rendered = _LINE_BREAK_RE.sub("<br>", rendered)
    rendered = rendered.replace("\n", "<br>")
    return _IMAGE_SLOT_RE.sub(lambda match: images[int(match.group(1))], rendered)


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


def _render_styled_text(source: str) -> str:
    """`%%(...)` 스타일 블록과 단순 Wiki table을 HTML로 바꾼다.

    Codebeamer는 붙여넣은 서식을 `%%(바깥)%%(안쪽)글자%!%!`처럼 겹쳐 저장한다. 열린 블록을
    쌓아 두고 `%%`나 `%!`가 나오면 가장 안쪽 블록을 닫는다. 끝까지 닫히지 않은 블록은 끝에서
    닫는다. 이름 스타일 `%%red`는 블록 밖에서만 연다. 블록 안의 `%%`는 닫는 표시로 본다.
    """
    parts: list[str] = []
    # 열린 블록마다 `<span>`을 열었는지. 허용되지 않은 스타일만 있으면 span 없이 글자만 둔다.
    open_spans: list[bool] = []
    position = 0
    search_from = 0
    while (mark := _STYLE_MARK_RE.search(source, search_from)) is not None:
        start = mark.start()
        style_open = _STYLE_OPEN_RE.match(source, start)
        named_open = (
            _NAMED_STYLE_OPEN_RE.match(source, start)
            if style_open is None and not open_spans
            else None
        )
        if style_open is None and named_open is None and not open_spans:
            # 열린 블록이 없으면 `%%`, `%!`는 글자 그대로 둔다.
            search_from = mark.end()
            continue
        text = source[position:start]
        parts.append(_render_basic_markup(text) if open_spans else _render_local_tables(text))
        if style_open is not None:
            style = sanitize_wiki_style(style_open.group("style"))
            position = style_open.end()
        elif named_open is not None:
            name = named_open.group("name").casefold()
            style = (
                f"color: {name}"
                if name in _NAMED_COLOR_STYLES and name not in _THEME_FOREGROUND_COLORS
                else ""
            )
            position = named_open.end()
        else:
            if open_spans.pop():
                parts.append("</span>")
            position = search_from = mark.end()
            continue
        open_spans.append(bool(style))
        if style:
            parts.append(f'<span style="{style}">')
        search_from = position
    rest = source[position:]
    parts.append(_render_basic_markup(rest) if open_spans else _render_local_tables(rest))
    parts.extend("</span>" for opened in reversed(open_spans) if opened)
    return "".join(parts)


@dataclass
class _TableCell:
    content: str = ""
    header: bool = False
    style: str = ""
    # `<`는 왼쪽 셀, `^`는 위 셀과 합친다.
    merge: str = ""
    # 이 셀이 차지하는 (행, 열) 칸. 병합 계산 중에 채운다.
    positions: list[tuple[int, int]] = field(default_factory=list)


def _plugin_end(source: str, start: int) -> int | None:
    """`[{`로 연 plugin과 짝이 맞는 `}]` 바로 뒤 위치를 찾는다."""
    depth = 0
    index = start
    while index < len(source) - 1:
        pair = source[index : index + 2]
        if pair == "[{":
            depth += 1
            index += 2
        elif pair == "}]":
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    return None


def _balanced_paren_end(text: str) -> int | None:
    """`(`로 시작하는 text에서 짝이 맞는 `)` 위치를 찾는다. `rgb(...)`처럼 괄호가 겹친다."""
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_row_line(line: str) -> list[str]:
    """한 줄에 적은 행을 셀 조각으로 나눈다. 조각은 `|` 또는 `||`로 시작한다.

    `[이름|주소]` 링크 안의 `|`와 `~|`는 셀 구분자가 아니다.
    """
    source = line.strip()
    starts: list[int] = []
    depth = 0
    index = 0
    while index < len(source):
        char = source[index]
        if char == "~":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(depth - 1, 0)
        elif char == "|" and depth == 0:
            starts.append(index)
            if source.startswith("||", index):
                index += 1
        index += 1
    pieces = [
        source[begin:end]
        for begin, end in zip(starts, [*starts[1:], len(source)], strict=True)
    ]
    # 줄 끝의 `|`는 마지막 셀을 닫을 뿐이다.
    if len(pieces) > 1 and pieces[-1] in {"|", "||"}:
        pieces.pop()
    return pieces


def _parse_cell(piece: str) -> _TableCell:
    header = piece.startswith("||")
    body = piece[2:] if header else piece[1:]
    marker = body.lstrip()
    if marker[:1] in {"<", "^"}:
        return _TableCell(header=header, merge=marker[0])
    if marker.startswith("("):
        end = _balanced_paren_end(marker)
        # `(참고) 내용`처럼 CSS가 아닌 괄호는 내용으로 둔다.
        if end is not None and ":" in marker[1:end]:
            return _TableCell(content=marker[end + 1 :], header=header, style=marker[1:end])
    return _TableCell(content=body, header=header)


def _table_rows(body: str) -> list[list[_TableCell]]:
    """Table plugin 본문을 행과 셀로 나눈다.

    한 줄에 셀이 여럿이면 줄마다 한 행이다. 첫 줄에 셀이 하나뿐이면 빈 줄까지를
    한 행으로 보고 `|`로 시작하는 줄마다 새 셀을 연다. `|`로 시작하지 않는 줄은
    바로 앞 셀 내용이 이어지는 것이다.
    """
    rows: list[list[_TableCell]] = []
    for group in _BLANK_LINE_RE.split(body):
        if not group.strip():
            continue
        text = group.strip("\n")
        lines = text.split("\n")
        if not lines[0].lstrip().startswith("|"):
            # 셀 밖 글자도 버리지 않는다. 앞 셀에 잇거나 한 칸짜리 행으로 둔다.
            if rows:
                rows[-1][-1].content += "\n" + text
            else:
                rows.append([_TableCell(content=text)])
            continue
        single_line_rows = len(_split_row_line(lines[0])) > 1
        row: list[_TableCell] = []
        for line in lines:
            if not line.lstrip().startswith("|"):
                row[-1].content += "\n" + line
            elif single_line_rows:
                if row:
                    rows.append(row)
                row = [_parse_cell(piece) for piece in _split_row_line(line)]
            else:
                row.append(_parse_cell(line.lstrip()))
        rows.append(row)
    return rows


def _resolve_merges(rows: list[list[_TableCell]]) -> list[list[_TableCell]]:
    """각 칸을 실제로 차지하는 셀을 돌려준다. 병합 표시는 원래 셀을 가리킨다."""
    owners: list[list[_TableCell]] = []
    for row_index, row in enumerate(rows):
        owner_row: list[_TableCell] = []
        for col_index, cell in enumerate(row):
            owner = cell
            if cell.merge == "<" and col_index > 0:
                owner = owner_row[col_index - 1]
            elif cell.merge == "^" and row_index > 0 and col_index < len(owners[-1]):
                owner = owners[-1][col_index]
            owner.positions.append((row_index, col_index))
            owner_row.append(owner)
        owners.append(owner_row)
    return owners


def _plugin_params(header: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for match in _PLUGIN_PARAM_RE.finditer(header):
        value = next(group for group in match.groups()[1:] if group is not None)
        params[match.group(1).casefold()] = value
    return params


def _render_table_plugin(inner: str) -> str:
    """`[{Table ...}]` 안쪽을 HTML 표로 바꾼다.

    셀마다 다른 테두리와 px 폭은 따르지 않는다. 좁은 상세 영역에서도 읽히도록
    균일한 격자와 내용 기준 폭을 쓰고, 배경색과 정렬만 남긴다.
    """
    lines = inner.split("\n")
    header_end = 0
    while (
        header_end < len(lines)
        and lines[header_end].strip()
        and not lines[header_end].lstrip().startswith("|")
    ):
        header_end += 1
    params = _plugin_params(" ".join(lines[:header_end]))
    rows = _table_rows("\n".join(lines[header_end:]))
    owners = _resolve_merges(rows)
    try:
        first_row_number = int(params.get("rownumber", "0"))
    except ValueError:
        first_row_number = 0

    rows_html: list[str] = []
    for row_index, row in enumerate(rows):
        cells_html: list[str] = []
        for col_index, cell in enumerate(row):
            if owners[row_index][col_index] is not cell:
                continue
            if cell.header:
                styles = [params.get("headerstyle", ""), cell.style]
            else:
                row_style = params.get("evenrowstyle" if row_index % 2 == 0 else "oddrowstyle", "")
                styles = [params.get("datastyle", ""), cell.style, row_style]
            style = sanitize_wiki_style(";".join(styles))
            style_attr = f"{_TABLE_CELL_STYLE}; {style}" if style else _TABLE_CELL_STYLE
            last_row = max(position[0] for position in cell.positions)
            last_col = max(position[1] for position in cell.positions)
            span_attrs = ""
            if last_col > col_index:
                span_attrs += f' colspan="{last_col - col_index + 1}"'
            if last_row > row_index:
                span_attrs += f' rowspan="{last_row - row_index + 1}"'
            content = cell.content.strip()
            if content == "#":
                content = str(first_row_number + row_index)
            tag = "th" if cell.header else "td"
            cells_html.append(
                f'<{tag} style="{style_attr}"{span_attrs}>'
                f"{codebeamer_wiki_to_html(content)}</{tag}>"
            )
        rows_html.append(f"<tr>{''.join(cells_html)}</tr>")
    table_style = sanitize_wiki_style(params.get("style", ""))
    table_style_attr = "border-collapse: collapse; margin: 4px 0"
    if table_style:
        table_style_attr += f"; {table_style}"
    return f'<table style="{table_style_attr}">{"".join(rows_html)}</table>'


def codebeamer_wiki_to_html(value: Any) -> str:
    """안전한 Codebeamer Wiki 문법 일부를 Qt rich text용 HTML로 바꾼다.

    Table plugin 블록은 셀 안에 스타일 블록이 들어 있으므로 먼저 떼어 낸다.
    짝이 맞지 않는 블록은 원문 그대로 둔다.
    """
    source = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    parts: list[str] = []
    position = 0
    while (opening := _TABLE_PLUGIN_OPEN_RE.search(source, position)) is not None:
        end = _plugin_end(source, opening.start())
        if end is None:
            break
        before = source[position : opening.start()]
        # 표는 블록이라 바로 앞뒤 개행까지 `<br>`로 바꾸면 빈 줄이 하나 더 생긴다.
        parts.append(_render_styled_text(before.removesuffix("\n")))
        parts.append(_render_table_plugin(source[opening.end() : end - 2]))
        position = end + 1 if source.startswith("\n", end) else end
    parts.append(_render_styled_text(source[position:]))
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
    "attachment_for_link",
    "codebeamer_wiki_to_html",
    "is_explicit_wiki_type",
    "payload_uses_wiki",
    "resolve_wiki_images",
    "sanitize_server_wiki_html",
    "sanitize_wiki_style",
    "wiki_image_references",
    "wiki_image_resource_key",
    "wiki_link_from_url",
]
