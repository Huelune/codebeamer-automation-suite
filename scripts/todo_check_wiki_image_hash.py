"""todo.md 1절: 본문 그림 해시가 첨부 내용의 md5인지, Baseline 그림을 첨부 이력에서 찾을 수 있는지 확인한다.

읽기 전용이다. 결과를 받으면 이 파일, 테스트, 절을 함께 지운다.
"""

import collections
import hashlib
import os
import sys
import warnings
from pathlib import Path
from typing import Any


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGE_SIZE = 500
MAX_ITEMS = 20
MAX_DOWNLOADS = 60
MAX_HISTORY_CALLS = 30
MAX_CONTENT_BYTES = 10 * 1024 * 1024


def failure(exc: Exception) -> str:
    # 원문에는 주소가 들어 있을 수 있어 종류와 상태 코드만 찍는다.
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


class Checker:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.downloads = 0
        self.history_calls = 0
        self.failures: collections.Counter[str] = collections.Counter()

    def items(self, tracker_id: int, baseline_id: int | None = None) -> dict[int, dict[str, Any]]:
        payload = self.client.search_items(
            query_string=f"tracker.id = {tracker_id} ORDER BY item.id DESC",
            baseline_id=baseline_id,
            page=1,
            page_size=PAGE_SIZE,
        )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return {int(item["id"]): item for item in items if isinstance(item, dict) and "id" in item}

    def md5_of(self, url: str) -> str | None:
        if self.downloads >= MAX_DOWNLOADS:
            return None
        self.downloads += 1
        try:
            _mime, data = self.client.download_authenticated_resource(url, max_bytes=MAX_CONTENT_BYTES)
        except Exception as exc:
            self.failures[failure(exc)] += 1
            return None
        return hashlib.md5(data).hexdigest()

    def content_url(self, attachment_id: int, version: int | None = None) -> str:
        url = f"{self.client.base_url}/v3/attachments/{attachment_id}/content"
        return url if version is None else f"{url}?version={version}"

    def versions(self, attachment_id: int) -> list[int]:
        """첨부 버전 번호. 최신부터."""
        if self.history_calls >= MAX_HISTORY_CALLS:
            return []
        self.history_calls += 1
        try:
            payload = self.client._get(
                f"/v3/attachments/{attachment_id}/history", params={"page": 1, "pageSize": 100}
            )
        except Exception as exc:
            self.failures[failure(exc)] += 1
            return []
        entries = payload.get("revisions", []) if isinstance(payload, dict) else payload
        numbers = {entry["version"] for entry in entries or [] if isinstance(entry.get("version"), int)}
        return sorted(numbers, reverse=True)


def references(item: dict[str, Any]) -> list[Any]:
    from src.gui.wiki_renderer import wiki_image_references

    return [reference for reference in wiki_image_references(item.get("description")) if reference.content_hash]


def check_current(checker: Checker, items: dict[int, dict[str, Any]]) -> collections.Counter[str]:
    """현재 본문 그림 해시와 같은 이름 첨부의 현재 내용 md5를 비교한다."""
    counts: collections.Counter[str] = collections.Counter()
    for item_id, item in items.items():
        refs = references(item)
        if not refs:
            continue
        if counts["items"] >= MAX_ITEMS:
            break
        counts["items"] += 1
        attachments = checker.client.get_item_attachments(item_id)
        for reference in refs:
            counts["refs"] += 1
            same_name = [value for value in attachments if value.get("name") == reference.name]
            if not same_name:
                counts["no_attachment"] += 1
                continue
            if len(same_name) > 1:
                counts["duplicate_name"] += 1
            digests = [checker.md5_of(checker.content_url(int(value["id"]))) for value in same_name]
            if reference.content_hash.casefold() in digests:
                counts["match"] += 1
            elif any(digests):
                counts["mismatch"] += 1
            else:
                counts["not_downloaded"] += 1
    return counts


def check_baseline(
    checker: Checker,
    current: dict[int, dict[str, Any]],
    baseline: dict[int, dict[str, Any]],
) -> collections.Counter[str]:
    """Baseline 이후 바뀐 그림을 첨부 이력의 버전 내용 md5로 찾는다."""
    counts: collections.Counter[str] = collections.Counter()
    for item_id, item in baseline.items():
        current_hashes = {ref.content_hash.casefold() for ref in references(current.get(item_id, {}))}
        changed = [ref for ref in references(item) if ref.content_hash.casefold() not in current_hashes]
        if not changed:
            continue
        if counts["items"] >= MAX_ITEMS:
            break
        counts["items"] += 1
        attachments = checker.client.get_item_attachments(item_id)
        for reference in changed:
            counts["refs"] += 1
            same_name = [value for value in attachments if value.get("name") == reference.name]
            if not same_name:
                counts["no_attachment"] += 1
                continue
            found = ""
            for attachment in same_name:
                versions = checker.versions(int(attachment["id"]))
                for position, version in enumerate(versions):
                    digest = checker.md5_of(checker.content_url(int(attachment["id"]), version))
                    if digest == reference.content_hash.casefold():
                        found = "latest" if position == 0 else "older"
                        break
                if found:
                    break
            counts[found or "not_found"] += 1
    return counts


def main() -> None:
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 1절: 본문 그림 해시와 첨부 내용 md5 비교 (읽기 전용)")
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
    checker = Checker(client)

    try:
        current = checker.items(tracker_id)
        now = check_current(checker, current)
    except Exception as exc:
        print(f"실패: 현재 아이템 조회 실패({failure(exc)}) -> 사내망/VPN과 트래커 ID 확인")
        return
    print(
        f"[현재] 아이템 {len(current)}개 중 본문 그림 있는 아이템 {now['items']}개, "
        f"해시 붙은 그림 자리 {now['refs']}개"
    )
    print(
        f"  같은 이름 첨부 없음 {now['no_attachment']}개, 이름 겹침 {now['duplicate_name']}개, "
        f"내용 md5 = 해시 {now['match']}개, 다름 {now['mismatch']}개, 못 받음 {now['not_downloaded']}개"
    )
    if now["match"] and not now["mismatch"]:
        print("  판정: 본문 해시는 첨부 내용의 md5")
    elif now["mismatch"] and not now["match"]:
        print("  판정: 본문 해시는 첨부 내용의 md5가 아님")
    elif now["match"]:
        print("  판정: 섞임 -> 다른 경우는 Baseline 이후 그림이 바뀐 것일 수 있음")
    else:
        print("  판단 불가: 비교한 그림 없음 -> 본문에 붙여 넣은 그림이 있는 트래커로 다시 실행")

    try:
        baselines = client.get_tracker_baselines(tracker_id)
        ids = [int(value["id"]) for value in baselines if isinstance(value, dict) and "id" in value]
        baseline_id = int(arguments[1]) if len(arguments) > 1 else (max(ids) if ids else None)
        if baseline_id is None:
            print("[Baseline] 판단 불가: Baseline 없음 -> Baseline이 있는 트래커로 다시 실행")
            return
        then = check_baseline(checker, current, checker.items(tracker_id, baseline_id))
    except Exception as exc:
        print(f"실패: Baseline 조회 실패({failure(exc)}) -> 사내망/VPN과 Baseline ID 확인")
        return
    print(
        f"[Baseline] {'지정한' if len(arguments) > 1 else '가장 최근'} Baseline, "
        f"현재와 해시가 다른 그림 자리 {then['refs']}개 (아이템 {then['items']}개)"
    )
    print(
        f"  이력에서 찾음: 최신 버전 {then['latest']}개, 이전 버전 {then['older']}개 / "
        f"못 찾음 {then['not_found']}개, 같은 이름 첨부 없음 {then['no_attachment']}개"
    )
    if not then["refs"]:
        print("  판단 불가: Baseline 이후 바뀐 그림 없음 -> 그림을 바꾼 Baseline ID를 트래커 ID 뒤에 붙여 다시 실행")
    elif then["older"]:
        print("  판정: Baseline 그림을 이전 버전에서 찾을 수 있음")
    else:
        print("  판정: 이전 버전에서 찾지 못함 -> 버전 맞추기로는 Baseline 그림을 못 고름")
    print(f"[요청] 이력 조회 {checker.history_calls}회, 내용 받기 {checker.downloads}회")
    if checker.failures:
        print("  실패: " + ", ".join(f"{kind} {count}회" for kind, count in checker.failures.most_common(4)))


if __name__ == "__main__":
    main()
