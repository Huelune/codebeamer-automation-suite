from __future__ import annotations

from collections.abc import Sequence


def choose_one(prompt: str, items: Sequence[str], default_index: int | None = None) -> int:
    """목록에서 하나를 고르게 하고 선택한 위치를 돌려준다."""
    if not items:
        raise ValueError("선택 가능한 항목이 없습니다.")

    while True:
        print(f"\n{prompt}")
        for idx, item in enumerate(items, start=1):
            default_mark = " [default]" if default_index == idx - 1 else ""
            print(f"  {idx}. {item}{default_mark}")

        raw = input("> 번호 선택" + (" (Enter=default)" if default_index is not None else "") + ": ").strip()
        if raw == "" and default_index is not None:
            return default_index
        if raw.isdigit():
            selected = int(raw) - 1
            if 0 <= selected < len(items):
                return selected
        print("잘못된 입력입니다. 다시 선택해 주세요.")


def confirm(prompt: str, default: bool = True) -> bool:
    """예/아니오 질문을 보여주고 불린 값으로 돌려준다."""
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"{prompt} {suffix}: ").strip().lower()
    if raw == "":
        return default
    return raw in {"y", "yes"}
