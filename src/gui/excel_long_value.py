"""Excel 내보내기에서 긴 값을 자르고 미리보기를 만드는 공용 helper.

계층 내보내기와 Baseline 내보내기는 `긴 값 전체보기` 시트의 열 구성이 다르다.
Baseline 은 기준·비교 2단 구조라 값 열이 둘이고 계층은 하나다. 시트 조립은
각 모듈에 두고, 값 단위 계산만 여기로 모은다.
"""

from __future__ import annotations

from typing import Any

from .excel_export_style import excel_text_units
from .excel_export_style import normalize_excel_text


# 셀 하나에 남길 수 있는 한도. Excel 한도보다 낮게 잡아 여유를 둔다.
LONG_VALUE_CELL_TEXT = 30000
LONG_VALUE_CELL_LINE_FEEDS = 200

# 원래 자리에 남기는 미리보기 한도.
LONG_VALUE_PREVIEW_TEXT = 180
LONG_VALUE_PREVIEW_LINE_FEEDS = 3

LONG_VALUE_SHEET_TITLE = "긴 값 전체보기"


def exceeds_text_limits(
    value: str,
    *,
    max_text_units: int,
    max_line_feeds: int,
) -> bool:
    """값이 셀 한도를 넘는지 본다."""
    return excel_text_units(value) > max_text_units or value.count("\n") > max_line_feeds


def requires_long_value_sheet(value: str) -> bool:
    """값을 별도 시트로 빼야 하는지 본다."""
    return exceeds_text_limits(
        value,
        max_text_units=LONG_VALUE_CELL_TEXT,
        max_line_feeds=LONG_VALUE_CELL_LINE_FEEDS,
    )


def split_excel_text(
    value: str,
    *,
    max_text_units: int,
    max_line_feeds: int,
) -> tuple[str, ...]:
    """값을 셀 한도 안에 들어가는 조각으로 자른다.

    줄바꿈에서 자르는 쪽이 읽기 좋으므로 줄바꿈, 그다음 공백 순으로 찾는다.
    조각이 너무 짧아지지 않도록 한도의 절반 이후에 있는 경계만 쓴다.
    """
    normalized = normalize_excel_text(value)
    if not normalized:
        return ("",)
    parts: list[str] = []
    start = 0
    while start < len(normalized):
        units = 0
        line_feeds = 0
        cursor = start
        last_newline = -1
        last_whitespace = -1
        while cursor < len(normalized):
            character = normalized[cursor]
            character_units = 2 if ord(character) > 0xFFFF else 1
            character_line_feeds = 1 if character == "\n" else 0
            if (
                units + character_units > max_text_units
                or line_feeds + character_line_feeds > max_line_feeds
            ):
                break
            units += character_units
            line_feeds += character_line_feeds
            if character == "\n":
                last_newline = cursor
            elif character.isspace():
                last_whitespace = cursor
            cursor += 1

        if cursor >= len(normalized):
            end = len(normalized)
        else:
            minimum_preferred = start + max((cursor - start) // 2, 1)
            if last_newline >= minimum_preferred:
                end = last_newline + 1
            elif last_whitespace >= minimum_preferred:
                end = last_whitespace + 1
            else:
                end = cursor
        if end <= start:
            # 한 글자도 담기지 않으면 무한 반복이 된다.
            end = start + 1
        parts.append(normalized[start:end])
        start = end
    return tuple(parts)


def split_long_value(value: str) -> tuple[str, ...]:
    """긴 값을 시트에 넣을 조각으로 자른다."""
    return split_excel_text(
        value,
        max_text_units=LONG_VALUE_CELL_TEXT,
        max_line_feeds=LONG_VALUE_CELL_LINE_FEEDS,
    )


def cell_preview(
    value: Any,
    *,
    max_text_units: int,
    max_line_feeds: int,
    suffix: str,
) -> str:
    """한도를 넘는 값만 앞부분과 안내 문구로 줄인다."""
    normalized = normalize_excel_text(value)
    if not exceeds_text_limits(
        normalized,
        max_text_units=max_text_units,
        max_line_feeds=max_line_feeds,
    ):
        return normalized
    normalized_suffix = normalize_excel_text(suffix)
    text_budget = max(max_text_units - excel_text_units(normalized_suffix), 1)
    line_feed_budget = max(max_line_feeds - normalized_suffix.count("\n"), 0)
    prefix = split_excel_text(
        normalized,
        max_text_units=text_budget,
        max_line_feeds=line_feed_budget,
    )[0]
    return f"{prefix}{normalized_suffix}"


def long_value_preview(value: str) -> str:
    """원래 자리에 남길 미리보기를 만든다."""
    return cell_preview(
        value,
        max_text_units=LONG_VALUE_PREVIEW_TEXT,
        max_line_feeds=LONG_VALUE_PREVIEW_LINE_FEEDS,
        suffix=f"\n\n[전체 내용은 '{LONG_VALUE_SHEET_TITLE}' 시트에서 확인]",
    )
