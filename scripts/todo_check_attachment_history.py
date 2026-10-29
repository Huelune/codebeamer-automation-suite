"""todo.md 1절: 첨부 버전 이력 응답의 모양을 읽기 전용으로 확인한다.

Baseline 시점 첨부를 고르려면 버전마다 시각이나 md5가 있어야 한다. 결과를 받으면 이 파일, 테스트, 절을 함께 지운다.
"""

import hashlib
import os
import re
import sys
import warnings
from pathlib import Path
from typing import Any


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCAN_ITEMS = 50
MAX_HISTORY_CALLS = 30
MAX_CONTENT_BYTES = 10 * 1024 * 1024
WIDTH = 118


def shape(value: Any) -> str:
    # 숫자만 9로 바꿔 모양만 남긴다. 값 자체는 찍지 않는다.
    return re.sub(r"\d", "9", str(value))


def is_time_key(key: str) -> bool:
    lowered = key.casefold()
    return lowered.endswith("at") or "date" in lowered or "time" in lowered


def keys_line(label: str, entries: list[dict[str, Any]]) -> str:
    keys = sorted({str(key) for entry in entries for key in entry})
    line = f"  {label}: {', '.join(keys) or '-'}"
    return line if len(line) <= WIDTH else line[: WIDTH - 3] + "..."


def time_keys_line(entries: list[dict[str, Any]]) -> str:
    found: dict[str, str] = {}
    for entry in entries:
        for key, value in entry.items():
            if is_time_key(str(key)) and isinstance(value, str) and value:
                found.setdefault(str(key), shape(value))
    text = ", ".join(f"{key}({value})" for key, value in sorted(found.items()))
    return f"  시각 키: {text or '없음'}"


def entries_of(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    """응답에서 항목 목록을 꺼낸다. 최상위 모양도 함께 돌려준다."""
    if isinstance(payload, list):
        return "목록", [entry for entry in payload if isinstance(entry, dict)]
    if not isinstance(payload, dict):
        return type(payload).__name__, []
    top = f"객체({', '.join(sorted(str(key) for key in payload))})"
    for value in payload.values():
        if isinstance(value, list) and all(isinstance(entry, dict) for entry in value):
            return top, list(value)
    return top, []


def yes_no(value: bool) -> str:
    return "예" if value else "아니오"


def failure(exc: Exception) -> str:
    # 원문에는 주소가 들어 있을 수 있어 종류와 상태 코드만 찍는다.
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def find_attachment(client: Any, tracker_id: int, item_id: int | None) -> dict[str, Any]:
    """버전이 둘 이상인 첨부를 찾는다. 못 찾으면 마지막으로 본 첨부의 이력을 쓴다."""
    stats = {"items": 0, "with_attachments": 0, "history_calls": 0, "multi": 0}
    found: dict[str, Any] = {"stats": stats, "list_entries": [], "history": None, "attachment_id": None}
    if item_id is not None:
        item_ids = [item_id]
    else:
        payload = client.search_items(
            query_string=f"tracker.id = {tracker_id} ORDER BY item.id DESC",
            page=1,
            page_size=SCAN_ITEMS,
        )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        item_ids = [int(item["id"]) for item in items if isinstance(item, dict) and "id" in item]
    for current_item in item_ids:
        stats["items"] += 1
        attachments = client.get_item_attachments(current_item)
        if not attachments:
            continue
        stats["with_attachments"] += 1
        found["list_entries"].extend(attachments)
        for attachment in attachments:
            if stats["history_calls"] >= MAX_HISTORY_CALLS:
                return found
            attachment_id = attachment.get("id") or attachment.get("attachmentId")
            if attachment_id is None:
                continue
            stats["history_calls"] += 1
            history = client._get(f"/v3/attachments/{int(attachment_id)}/history")
            found["history"], found["attachment_id"] = history, int(attachment_id)
            if len(entries_of(history)[1]) >= 2:
                stats["multi"] += 1
                return found
    return found


def content_lines(client: Any, attachment_id: int, entries: list[dict[str, Any]]) -> list[str]:
    """첫 버전과 마지막 버전 내용을 `version`으로 받아 비교한다."""
    versions: list[int] = [entry["version"] for entry in entries if isinstance(entry.get("version"), int)]
    if not versions:
        return ["  version 값 없음 -> 버전으로 받기를 시험하지 못함"]
    results: list[tuple[int, str, str | None]] = []
    for version in dict.fromkeys((min(versions), max(versions))):
        url = f"{client.base_url}/v3/attachments/{attachment_id}/content?version={version}"
        try:
            _mime, data = client.download_authenticated_resource(url, max_bytes=MAX_CONTENT_BYTES)
        except Exception as exc:
            results.append((version, failure(exc), None))
            continue
        results.append((version, "HTTP 200", hashlib.md5(data).hexdigest()))
    lines = [f"  {'첫' if version == min(versions) else '마지막'} 버전: {outcome}" for version, outcome, _ in results]
    digests = {version: digest for version, _, digest in results if digest}
    if len(digests) == 2:
        lines.append(f"  두 버전 내용 다름: {yes_no(len(set(digests.values())) == 2)}")
    by_version = {entry.get("version"): str(entry.get("md5") or "").casefold() for entry in entries}
    matched = [by_version.get(version) == digest for version, digest in digests.items() if by_version.get(version)]
    if matched:
        lines.append(f"  받은 내용의 md5 = 이력의 md5: {yes_no(all(matched))} ({len(matched)}개 비교)")
    return lines


def main() -> None:
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 1절: 첨부 버전 이력 응답 모양 확인 (읽기 전용)")
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
    item_id = int(arguments[1]) if len(arguments) > 1 else None
    client = CodebeamerClient(settings.base_url, settings.username, settings.password, None)

    try:
        baselines = client.get_tracker_baselines(tracker_id)
    except Exception as exc:
        print(f"실패: Baseline 목록 조회 실패({failure(exc)}) -> 사내망/VPN과 트래커 ID 확인")
        return
    print(f"[Baseline] {len(baselines)}개")
    print(keys_line("항목 키", baselines))
    print(time_keys_line(baselines))

    try:
        found = find_attachment(client, tracker_id, item_id)
    except Exception as exc:
        print(f"실패: 첨부 조회 실패({failure(exc)}) -> 사내망/VPN과 GUI 연결 테스트 확인")
        return
    stats = found["stats"]
    print(
        f"[찾기] 아이템 {stats['items']}개 중 첨부 있는 아이템 {stats['with_attachments']}개, "
        f"이력 조회 {stats['history_calls']}회, 버전 2개 이상 첨부 {stats['multi']}개"
    )
    if found["history"] is None:
        print("판단 불가: 첨부가 있는 아이템을 못 찾음 -> 첨부가 있는 트래커나 아이템 ID로 다시 실행")
        return
    print("[첨부 목록 항목]")
    print(keys_line("키", found["list_entries"]))
    top, entries = entries_of(found["history"])
    print("[이력 응답]")
    print(f"  최상위: {top}"[:WIDTH])
    print(keys_line("항목 키", entries))
    print(time_keys_line(entries))
    versions = [entry.get("version") for entry in entries]
    print(
        f"  버전 {len(entries)}개, version 값 서로 다름: {yes_no(len(set(map(str, versions))) == len(versions))}, "
        f"id 모두 같음: {yes_no(len({str(entry.get('id')) for entry in entries}) <= 1)}, "
        f"md5 서로 다름: {yes_no(len({str(entry.get('md5')) for entry in entries}) == len(entries))}"
    )
    print("[version으로 내용 받기]")
    print("\n".join(content_lines(client, found["attachment_id"], entries)))
    if not stats["multi"]:
        print("참고: 버전 2개 이상 첨부를 못 찾음 -> 그림을 바꾼 적 있는 아이템 ID를 트래커 ID 뒤에 붙여 다시 실행")


if __name__ == "__main__":
    main()
