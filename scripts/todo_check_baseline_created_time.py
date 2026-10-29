"""todo.md 1절: Baseline을 만든 시각을 서버에서 얻을 수 있는지 확인한다.

읽기 전용이다. 결과를 받으면 이 파일, 테스트, 절을 함께 지운다.
"""

import os
import re
import sys
import textwrap
import warnings
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGE_SIZE = 500
MAX_KEYS = 30
# API 필드 이름 모양만 찍는다. 다른 모양의 키는 개수로만 센다.
_KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,40}")


def failure(exc: Exception) -> str:
    # 원문에는 주소가 들어 있을 수 있어 종류와 상태 코드만 찍는다.
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def kind(value: Any) -> str:
    if parse_time(value) is not None:
        return "시각"
    if value is None:
        return "null"
    return {bool: "bool", int: "int", float: "float", str: "str", dict: "dict", list: "list"}.get(
        type(value), "기타"
    )


def describe_keys(entry: dict[str, Any]) -> str:
    named = [key for key in entry if isinstance(key, str) and _KEY_RE.fullmatch(key)]
    text = ", ".join(f"{key}({kind(entry[key])})" for key in named[:MAX_KEYS])
    hidden = len(entry) - min(len(named), MAX_KEYS)
    return f"키 {len(entry)}개: {text}" + (f" 외 {hidden}개" if hidden else "")


def time_keys(entry: dict[str, Any]) -> dict[str, datetime]:
    keys = {key: parse_time(value) for key, value in entry.items() if isinstance(key, str) and _KEY_RE.fullmatch(key)}
    return {key: value for key, value in keys.items() if value is not None}


def entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [value for value in payload if isinstance(value, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("baselines", "items", "references"):
        if isinstance(payload.get(key), list):
            return entries(payload[key])
    return []


def print_wrapped(text: str) -> None:
    print(textwrap.fill(text, width=118, subsequent_indent="    "))


def main() -> None:
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 1절: Baseline 만든 시각 확인 (읽기 전용)")
    from src.codebeamer_client import CodebeamerClient
    from src.gui.settings_store import GuiSettingsStore

    settings = GuiSettingsStore().load()
    if not settings.base_url or not settings.password:
        print("실패: 저장된 연결 정보 없음 -> GUI에서 연결 테스트를 통과시킨 뒤 다시 실행")
        return
    arguments = [value.strip() for value in sys.argv[1:3]]
    if not arguments or not all(value.isdigit() for value in arguments):
        print("실패: 트래커 ID 없음 -> 명령 뒤에 트래커 ID 숫자를 붙여 다시 실행")
        return
    tracker_id = int(arguments[0])
    client = CodebeamerClient(settings.base_url, settings.username, settings.password, None)

    try:
        baseline_ids = [int(value["id"]) for value in client.get_tracker_baselines(tracker_id) if "id" in value]
    except Exception as exc:
        print(f"실패: Baseline 목록 조회 실패({failure(exc)}) -> 사내망/VPN과 트래커 ID 확인")
        return
    baseline_id = int(arguments[1]) if len(arguments) > 1 else (max(baseline_ids) if baseline_ids else None)
    if baseline_id is None:
        print("판단 불가: Baseline 없음 -> Baseline이 있는 트래커로 다시 실행")
        return
    print(f"[대상] {'지정한' if len(arguments) > 1 else '가장 최근'} Baseline (트래커 Baseline {len(baseline_ids)}개)")

    candidates: dict[str, datetime] = {}
    try:
        single = client._get(f"/v3/baselines/{baseline_id}")
    except Exception as exc:
        print(f"[Baseline 단건] 실패: {failure(exc)}")
    else:
        if isinstance(single, dict):
            print_wrapped(f"[Baseline 단건] {describe_keys(single)}")
            candidates.update({f"단건 {key}": value for key, value in time_keys(single).items()})
        else:
            print("[Baseline 단건] 응답이 객체가 아님")

    try:
        project = client.get_tracker(tracker_id).get("project") or {}
        listed = client._get(
            f"/v3/projects/{int(project['id'])}/baselines", params={"page": 1, "pageSize": PAGE_SIZE}
        )
    except Exception as exc:
        print(f"[프로젝트 Baseline 목록] 실패: {failure(exc)}")
    else:
        found = [value for value in entries(listed) if str(value.get("id")) == str(baseline_id)]
        if found:
            print_wrapped(f"[프로젝트 Baseline 목록] {describe_keys(found[0])}")
            candidates.update({f"목록 {key}": value for key, value in time_keys(found[0]).items()})
        else:
            print(f"[프로젝트 Baseline 목록] 항목 {len(entries(listed))}개 중 이 Baseline 없음")

    if not candidates:
        print("판정: 만든 시각 없음 -> 버전이 하나인 첨부만 Baseline 본문에 보여 주는 방식으로 진행")
        return

    # 만든 시각이라면 Baseline에 담긴 아이템은 모두 그 전에 수정됐어야 한다.
    try:
        payload = client.search_items(
            query_string=f"tracker.id = {tracker_id}", baseline_id=baseline_id, page=1, page_size=PAGE_SIZE
        )
    except Exception as exc:
        print(f"실패: Baseline 아이템 조회 실패({failure(exc)}) -> 사내망/VPN과 Baseline ID 확인")
        return
    items = payload.get("items", []) if isinstance(payload, dict) else []
    modified = [time for item in items if isinstance(item, dict) if (time := parse_time(item.get("modifiedAt")))]
    print(f"[검증] Baseline 아이템 {len(items)}개 중 수정 시각 있는 것 {len(modified)}개")
    usable = []
    for name, value in candidates.items():
        later = sum(time > value for time in modified)
        gap = (value - max(modified)).total_seconds() / 60 if modified else None
        gap_text = "비교할 수정 시각 없음" if gap is None else f"가장 늦은 수정보다 {gap:.0f}분 뒤"
        print(f"  {name}: 이 시각보다 늦게 수정된 아이템 {later}개, {gap_text}")
        if modified and not later:
            usable.append(name)
    if usable:
        print("판정: 만든 시각으로 쓸 수 있는 값 있음 -> 첨부 버전을 수정 시각으로 고를 수 있음")
    elif modified:
        print("판정: 시각 값이 Baseline 아이템 수정보다 앞섬 ->만든 시각이 아님, 버전 하나인 첨부만 보여 주기로 진행")
    else:
        print("판단 불가: Baseline 아이템 수정 시각 없음 -> 아이템이 있는 트래커로 다시 실행")


if __name__ == "__main__":
    main()
