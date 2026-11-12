"""todo.md 3절: 표 필드 칸의 줄바꿈을 서버가 어떤 모양으로 저장하는지 확인한다.

읽기 전용이다. 칸 값은 찍지 않고 줄바꿈 표시의 개수만 센다. 결과를 받으면 이 파일, 테스트, 절을 함께 지운다.
"""

import collections
import os
import sys
import warnings
from pathlib import Path
from typing import Any


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MAX_ITEMS = 5
# 줄바꿈이 저장될 수 있는 모양. 이름은 화면에 찍고, 값은 칸 안에 있는지만 본다.
MARKERS = (
    ("LF", "\n"),
    ("CR", "\r"),
    ("\\\\", "\\\\"),
    ("<br>", "<br"),
    ("_x000D_", "_x000d_"),
)


def failure(exc: Exception) -> str:
    # 원문에는 주소가 들어 있을 수 있어 종류와 상태 코드만 찍는다.
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def count_markers(texts: list[str]) -> collections.Counter[str]:
    counts = collections.Counter[str]()
    for text in texts:
        lowered = text.casefold()
        counts["text"] += 1
        for name, marker in MARKERS:
            if marker in lowered:
                counts[name] += 1
    return counts


def table_cell_texts(item: dict[str, Any]) -> tuple[int, list[str]]:
    """표 필드의 모든 칸 수와 글자 값이 있는 칸의 값."""
    cell_count = 0
    texts: list[str] = []
    for field in item.get("customFields") or []:
        if not isinstance(field, dict) or field.get("type") != "TableFieldValue":
            continue
        for row in field.get("values") or []:
            for cell in row if isinstance(row, list) else []:
                cell_count += 1
                value = cell.get("value") if isinstance(cell, dict) else None
                if isinstance(value, str) and value:
                    texts.append(value)
    return cell_count, texts


def marker_text(counts: collections.Counter[str]) -> str:
    return ", ".join(f"{name} {counts[name]}" for name, _ in MARKERS)


def main() -> None:
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 3절: 표 칸 줄바꿈의 저장 모양 확인 (읽기 전용, 칸마다 줄바꿈 표시가 있는지만 셈)")
    from src.codebeamer_client import CodebeamerClient
    from src.gui.settings_store import GuiSettingsStore

    settings = GuiSettingsStore().load()
    if not settings.base_url or not settings.password:
        print("실패: 저장된 연결 정보 없음 -> GUI에서 연결 테스트를 통과시킨 뒤 다시 실행")
        return
    arguments = [value.strip() for value in sys.argv[1 : 1 + MAX_ITEMS]]
    if not arguments or not all(value.isdigit() for value in arguments):
        print("실패: 아이템 ID 없음 -> 명령 뒤에 아이템 ID 숫자를 공백으로 띄워 붙여 다시 실행")
        return
    client = CodebeamerClient(settings.base_url, settings.username, settings.password, None)

    table_total = collections.Counter[str]()
    for index, raw_id in enumerate(arguments, start=1):
        try:
            item = client.get_item(int(raw_id))
        except Exception as exc:
            print(f"[아이템 {index}] 실패: 조회 실패({failure(exc)}) -> 사내망/VPN과 아이템 ID 확인")
            continue
        cell_count, texts = table_cell_texts(item if isinstance(item, dict) else {})
        table_counts = count_markers(texts)
        table_total.update(table_counts)
        description = item.get("description") if isinstance(item, dict) else None
        description_counts = count_markers([description] if isinstance(description, str) and description else [])
        print(
            f"[아이템 {index}] 표 칸 {cell_count}개(글자 {table_counts['text']}개): {marker_text(table_counts)}"
        )
        print(f"           설명({'있음' if description_counts['text'] else '없음'}): {marker_text(description_counts)}")

    if not table_total["text"]:
        print("판단 불가: 글자가 든 표 칸이 없음 -> 표에 글자를 넣은 아이템 ID로 다시 실행")
    elif table_total["\\\\"]:
        print("판정: 표 칸 줄바꿈이 `\\\\`로 저장됨 -> 업로드도 표 칸의 줄바꿈을 `\\\\`로 바꿔 보내면 됨")
    elif table_total["<br>"]:
        print("판정: 표 칸 줄바꿈이 <br>로 저장됨 -> 업로드도 표 칸의 줄바꿈을 <br>로 바꿔 보내면 됨")
    elif table_total["LF"]:
        print("판정: 표 칸에 LF가 그대로 저장됨 -> 저장은 되고 화면 표시만 다름. 웹에서 넣은 줄바꿈도 LF인지 확인")
    else:
        print("판정: 표 칸에 줄바꿈 표시가 없음 -> 웹에서 표 칸에 줄바꿈을 넣고 저장한 아이템으로 다시 실행")


if __name__ == "__main__":
    main()
