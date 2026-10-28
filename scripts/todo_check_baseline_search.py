"""todo.md 1절: Baseline 검색 조건을 서버가 어느 시점 값으로 거르는지 읽기 전용으로 확인한다.

결과를 받으면 이 파일과 절을 지운다.
"""

import os
import sys
import warnings
from pathlib import Path


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGE_SIZE = 500
MAX_NAME_CHECKS = 5


def all_items(client, query_string, baseline_id=None):
    """조건에 맞는 아이템을 서버 페이지 끝까지 모은다. 아이템 ID -> 원본."""
    collected: dict[int, dict] = {}
    page = 1
    while True:
        payload = client.search_items(
            query_string=query_string,
            baseline_id=baseline_id,
            page=page,
            page_size=PAGE_SIZE,
        )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        before = len(collected)
        for item in items:
            collected[int(item["id"])] = item
        total = payload.get("total") if isinstance(payload, dict) else None
        if not items or len(items) < PAGE_SIZE or len(collected) == before:
            break
        if isinstance(total, int) and len(collected) >= total:
            break
        page += 1
    return collected


def status_name(item):
    status = item.get("status")
    return str(status.get("name") or "") if isinstance(status, dict) else ""


def quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def verdict(baseline_hits, current_hits, checks):
    if checks == 0:
        return "판단 불가: Baseline 이후 값이 바뀐 아이템이 없음 -> 다른 Baseline 또는 트래커로 다시 실행"
    if baseline_hits == checks and current_hits == 0:
        return "Baseline 시점 값으로 거름"
    if current_hits == checks and baseline_hits == 0:
        return "현재 값으로 거름"
    return "섞임: 일부만 Baseline 값과 맞음"


def check_status(client, tracker_id, baseline_id, baseline_items, current_items):
    """Baseline 이후 상태가 바뀐 아이템이 가장 많은 상태 값 하나로 서버 결과를 비교한다."""
    best = None
    for name in {status_name(item) for item in baseline_items.values()} - {""}:
        in_baseline = {item_id for item_id, item in baseline_items.items() if status_name(item) == name}
        in_current = {
            item_id
            for item_id, item in current_items.items()
            if item_id in baseline_items and status_name(item) == name
        }
        changed = len(in_baseline ^ in_current)
        if best is None or changed > best[0]:
            best = (changed, name, in_baseline, in_current)
    if best is None or best[0] == 0:
        return None
    _changed, name, in_baseline, in_current = best
    server = set(
        all_items(
            client,
            f"tracker.id = {tracker_id} AND status = {quote(name)} ORDER BY item.id ASC",
            baseline_id,
        )
    )
    return len(in_baseline), len(in_current), len(server), server == in_baseline, server == in_current


def check_names(client, tracker_id, baseline_id, baseline_items, current_items):
    """이름이 바뀐 아이템 몇 개를 Baseline 이름과 현재 이름으로 각각 찾아 본다."""
    changed = [
        item_id
        for item_id, item in baseline_items.items()
        if item_id in current_items and item.get("name") and current_items[item_id].get("name")
        and item.get("name") != current_items[item_id].get("name")
    ][:MAX_NAME_CHECKS]
    baseline_hits = 0
    current_hits = 0
    for item_id in changed:
        for name, is_baseline in (
            (baseline_items[item_id]["name"], True),
            (current_items[item_id]["name"], False),
        ):
            found = all_items(
                client,
                f"tracker.id = {tracker_id} AND item.id = {item_id} "
                f"AND summary LIKE {quote('%' + name + '%')} ORDER BY item.id ASC",
                baseline_id,
            )
            if item_id in found:
                if is_baseline:
                    baseline_hits += 1
                else:
                    current_hits += 1
    return baseline_hits, current_hits, len(changed)


def latest_baseline_id(client, tracker_id):
    baselines = client.get_tracker_baselines(tracker_id)
    ids = []
    for baseline in baselines:
        try:
            ids.append((str(baseline.get("createdAt") or ""), int(baseline["id"])))
        except (KeyError, TypeError, ValueError):
            continue
    return max(ids)[1] if ids else None


def main():
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 1절: Baseline 검색 조건의 시점 확인 (읽기 전용)")
    from src.codebeamer_client import CodebeamerClient
    from src.gui.settings_store import GuiSettingsStore

    settings = GuiSettingsStore().load()
    if not settings.base_url or not settings.password:
        print("실패: 저장된 연결 정보 없음 -> GUI에서 연결 테스트를 통과시킨 뒤 다시 실행")
        return
    args = [arg.strip() for arg in sys.argv[1:]]
    if not args or not args[0].isdigit() or (len(args) > 1 and not args[1].isdigit()):
        print("실패: 트래커 ID 없음 -> 명령 뒤에 트래커 ID 숫자를 붙여 다시 실행")
        return
    tracker_id = int(args[0])
    client = CodebeamerClient(settings.base_url, settings.username, settings.password, None)
    try:
        baseline_id = int(args[1]) if len(args) > 1 else latest_baseline_id(client, tracker_id)
        if baseline_id is None:
            print("실패: 이 트래커에 Baseline 없음 -> Baseline이 있는 트래커 ID로 다시 실행")
            return
        print("지정한 Baseline 사용" if len(args) > 1 else "가장 최근 Baseline 사용")
        scope = f"tracker.id = {tracker_id} ORDER BY item.id ASC"
        baseline_items = all_items(client, scope, baseline_id)
        current_items = all_items(client, scope)
        status = check_status(client, tracker_id, baseline_id, baseline_items, current_items)
        name_baseline_hits, name_current_hits, name_checks = check_names(
            client, tracker_id, baseline_id, baseline_items, current_items
        )
    except Exception as exc:  # 원문에는 주소가 들어 있을 수 있어 종류만 찍는다.
        print(f"실패: 서버 조회 실패({type(exc).__name__}) -> 사내망/VPN과 GUI 연결 테스트 확인")
        return
    print(f"Baseline 아이템 {len(baseline_items)}개, 현재 아이템 {len(current_items)}개")
    print("[상태 조건]")
    if status is None:
        print("  판단 불가: Baseline 이후 상태가 바뀐 아이템이 없음")
    else:
        in_baseline, in_current, server, same_baseline, same_current = status
        print(f"  Baseline 값 기준 {in_baseline}개, 현재 값 기준 {in_current}개, 서버 결과 {server}개")
        if same_baseline:
            print("  판정: Baseline 시점 값으로 거름")
        elif same_current:
            print("  판정: 현재 값으로 거름")
        else:
            print("  판정: 둘 다와 다름")
    print("[요약 조건]")
    print(
        f"  확인 {name_checks}개 중 Baseline 이름으로 찾음 {name_baseline_hits}개, "
        f"현재 이름으로 찾음 {name_current_hits}개"
    )
    print(f"  판정: {verdict(name_baseline_hits, name_current_hits, name_checks)}")


if __name__ == "__main__":
    main()
