"""todo.md 1절: 서버 렌더링(wiki2html)으로 Baseline 당시 본문 그림을 얻을 수 있는지 확인한다.

읽기 전용이다. 결과를 받으면 이 파일, 테스트, 절을 함께 지운다.
"""

import base64
import collections
import hashlib
import html
import os
import re
import sys
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
from urllib.parse import urlparse


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGE_SIZE = 500
MAX_ITEMS = 5
MAX_DOWNLOADS = 30
MAX_CONTENT_BYTES = 10 * 1024 * 1024
_IMG_SRC_RE = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
# 주소 모양에는 영문 단어로 된 경로 조각과 매개변수 이름만 남긴다.
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,30}")


def failure(exc: Exception) -> str:
    # 원문에는 주소가 들어 있을 수 있어 종류와 상태 코드만 찍는다.
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def image_sources(markup: str | None) -> list[str]:
    return [html.unescape(value) for value in _IMG_SRC_RE.findall(markup or "")]


def source_shape(client: Any, source: str) -> str:
    if source.startswith("data:"):
        return "data URI"
    parsed = urlparse(source)
    path = client._resource_monitor_path(parsed.path)
    segments = [part if not part or _WORD_RE.fullmatch(part) or part in ("{name}", "{resource}") else "{x}"
                for part in path.split("/")]
    names = sorted({name if _WORD_RE.fullmatch(name) else "{x}" for name, _ in parse_qsl(parsed.query, True)})
    return "/".join(segments) + (" ?" + "&".join(names) if names else "")


class Checker:
    def __init__(self, client: Any, project_id: int) -> None:
        self.client = client
        self.project_id = project_id
        self.downloads = 0
        self.renders = collections.Counter[str]()
        self.render_failures = collections.Counter[str]()
        self.download_failures = collections.Counter[str]()

    def render(self, item_id: int, version: int, markup: str) -> str | None:
        """앱의 wiki2html 호출과 같은 본문을 보낸다. 응답이 HTML이어도 읽도록 직접 보낸다."""
        try:
            response = self.client._session().post(
                f"{self.client.base_url}/v3/projects/{self.project_id}/wiki2html",
                json={
                    "contextId": item_id,
                    "contextVersion": version,
                    "markup": markup,
                    "renderingContextType": "TRACKER_ITEM",
                },
                timeout=self.client._timeout("POST"),
            )
            response.raise_for_status()
        except Exception as exc:
            self.render_failures[failure(exc)] += 1
            return None
        content_type = response.headers.get("Content-Type", "").casefold()
        if "json" not in content_type:
            self.renders["html" if "html" in content_type else "기타"] += 1
            return str(response.text)
        self.renders["json"] += 1
        try:
            payload = response.json()
        except ValueError:
            return str(response.text)
        if isinstance(payload, dict):
            payload = next((payload[key] for key in ("html", "value", "renderedMarkup", "markup")
                            if isinstance(payload.get(key), str)), "")
        return payload if isinstance(payload, str) else ""

    def md5_of(self, source: str) -> str | None:
        if source.startswith("data:"):
            try:
                return hashlib.md5(base64.b64decode(source.split(",", 1)[1])).hexdigest()
            except (IndexError, ValueError) as exc:
                self.download_failures[failure(exc)] += 1
                return None
        if self.downloads >= MAX_DOWNLOADS:
            return None
        self.downloads += 1
        try:
            _mime, data = self.client.download_authenticated_resource(source, max_bytes=MAX_CONTENT_BYTES)
        except Exception as exc:
            self.download_failures[failure(exc)] += 1
            return None
        return hashlib.md5(data).hexdigest()


def items(client: Any, tracker_id: int, baseline_id: int | None = None) -> dict[int, dict[str, Any]]:
    payload = client.search_items(
        query_string=f"tracker.id = {tracker_id} ORDER BY item.id DESC",
        baseline_id=baseline_id,
        page=1,
        page_size=PAGE_SIZE,
    )
    found = payload.get("items", []) if isinstance(payload, dict) else []
    return {int(item["id"]): item for item in found if isinstance(item, dict) and "id" in item}


def image_hashes(item: dict[str, Any]) -> set[str]:
    from src.gui.wiki_renderer import wiki_image_references

    return {ref.content_hash.casefold() for ref in wiki_image_references(item.get("description")) if ref.content_hash}


def check(
    checker: Checker,
    current: dict[int, dict[str, Any]],
    baseline: dict[int, dict[str, Any]],
) -> collections.Counter[str]:
    counts = collections.Counter[str]()
    changed = [
        item_id
        for item_id, item in baseline.items()
        if item_id in current and image_hashes(item) - image_hashes(current[item_id])
    ]
    counts["changed"] = len(changed)
    for item_id in changed[:MAX_ITEMS]:
        now, then = current[item_id], baseline[item_id]
        if not isinstance(now.get("version"), int) or not isinstance(then.get("version"), int):
            counts["no_version"] += 1
            continue
        counts["items"] += 1
        now_html = checker.render(item_id, now["version"], str(now.get("description") or ""))
        then_html = checker.render(item_id, then["version"], str(then.get("description") or ""))
        if now_html is None and then_html is None and not checker.renders:
            break  # 첫 아이템부터 전부 실패하면 같은 실패를 더 쌓지 않는다.
        # Baseline 본문을 현재 버전으로 그려 보면 버전 값이 그림 고르기에 쓰이는지 알 수 있다.
        mixed_html = checker.render(item_id, now["version"], str(then.get("description") or ""))
        now_sources, then_sources = image_sources(now_html), image_sources(then_html)
        counts["now_img"] += len(now_sources)
        counts["then_img"] += len(then_sources)
        for source in then_sources:
            counts["shape:" + source_shape(checker.client, source)] += 1
        differing = [source for source in then_sources if source not in now_sources]
        counts["differing"] += len(differing)
        counts["same_without_version"] += sum(source in image_sources(mixed_html) for source in differing)
        if not differing:
            continue
        now_digests = {checker.md5_of(source) for source in now_sources} - {None}
        for source in differing:
            digest = checker.md5_of(source)
            if digest is None:
                continue
            counts["downloaded"] += 1
            if digest not in now_digests:
                counts["new_content"] += 1
    return counts


def main() -> None:
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 1절: 서버 렌더링(wiki2html)으로 Baseline 본문 그림 확인 (읽기 전용)")
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
        project_id = int((client.get_tracker(tracker_id).get("project") or {})["id"])
        baseline_ids = [int(value["id"]) for value in client.get_tracker_baselines(tracker_id) if "id" in value]
        baseline_id = int(arguments[1]) if len(arguments) > 1 else (max(baseline_ids) if baseline_ids else None)
        if baseline_id is None:
            print("판단 불가: Baseline 없음 -> Baseline이 있는 트래커로 다시 실행")
            return
        current = items(client, tracker_id)
        baseline = items(client, tracker_id, baseline_id)
    except Exception as exc:
        print(f"실패: 트래커·Baseline 조회 실패({failure(exc)}) -> 사내망/VPN과 트래커·Baseline ID 확인")
        return

    checker = Checker(client, project_id)
    counts = check(checker, current, baseline)
    print(
        f"[대상] {'지정한' if len(arguments) > 1 else '가장 최근'} Baseline, "
        f"본문 그림 해시가 현재와 다른 아이템 {counts['changed']}개 중 {counts['items']}개 확인"
        + (f" (버전 없음 {counts['no_version']}개)" if counts["no_version"] else "")
    )
    if not counts["changed"]:
        print("판단 불가: 그림이 바뀐 아이템 없음 -> 그림을 바꾼 Baseline ID를 트래커 ID 뒤에 붙여 다시 실행")
        return
    rendered = sum(checker.renders.values())
    kinds = ", ".join(f"{kind} {count}회" for kind, count in checker.renders.most_common())
    fails = ", ".join(f"{kind} {count}회" for kind, count in checker.render_failures.most_common(3))
    print(
        f"[wiki2html] 성공 {rendered}회"
        + (f" (응답 {kinds})" if kinds else "")
        + (f", 실패: {fails}" if fails else "")
    )
    if not rendered:
        print("판정: 이 서버에서 wiki2html을 쓸 수 없음 -> 웹 화면의 그림 주소를 직접 보는 방법으로 확인")
        return
    print(
        f"[그림 주소] 현재 본문 img {counts['now_img']}개, Baseline 본문 img {counts['then_img']}개, "
        f"그중 현재와 다른 주소 {counts['differing']}개"
    )
    shapes = [(key.removeprefix("shape:"), count) for key, count in counts.most_common() if key.startswith("shape:")]
    for shape, count in shapes[:3]:
        print(f"[주소 모양] {shape[:90]} {count}개")
    print(f"[버전 영향] Baseline 본문을 현재 버전으로 그려도 같은 주소 {counts['same_without_version']}개 / "
          f"{counts['differing']}개")
    download_fails = ", ".join(f"{kind} {count}회" for kind, count in checker.download_failures.most_common(3))
    print(
        f"[받기] 다른 주소 {counts['differing']}개 중 받음 {counts['downloaded']}개, "
        f"현재 그림과 내용 다름 {counts['new_content']}개 (받기 {checker.downloads}회)"
        + (f", 실패: {download_fails}" if download_fails else "")
    )
    if not counts["differing"]:
        print("판정: Baseline 본문을 그려도 그림 주소가 현재와 같음 -> 서버 렌더링으로는 옛 그림을 못 고름")
    elif counts["new_content"]:
        needs_version = counts["same_without_version"] < counts["differing"]
        print("판정: 서버 렌더링으로 Baseline 당시 그림을 받을 수 있음"
              + (" (Baseline 버전 값이 필요)" if needs_version else " (본문 해시만으로 충분)"))
    else:
        print("판정: 주소는 다르지만 현재와 다른 그림을 받지 못함 -> [받기] 실패 종류 확인")


if __name__ == "__main__":
    main()
