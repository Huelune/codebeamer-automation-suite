"""todo.md 1절: 첨부 API가 Baseline 시점을 받는지 서버 Swagger 명세로 확인한다.

결과를 받으면 이 파일, 테스트, 절을 함께 지운다.
"""

import os
import re
import sys
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SWAGGER_PAGE = "/v3/swagger/editor.spr"
SPEC_CANDIDATES = (
    "/v3/swagger/v3.json",
    "/v3/swagger.json",
    "/v3/openapi.json",
    "/v3/api-docs",
)
# 시점을 고르는 매개변수로 볼 이름.
TIME_WORDS = ("baseline", "version", "revision")
MAX_OPERATIONS = 24
WIDTH = 118


def same_origin(url: str, base_url: str) -> bool:
    left, right = urlparse(url), urlparse(base_url)
    return (left.scheme, left.netloc) == (right.scheme, right.netloc)


def spec_urls(session: Any, base_url: str) -> list[str]:
    """명세 주소 후보. Swagger 화면이 가리키는 JSON을 먼저, 흔한 위치를 뒤에 둔다."""
    urls: list[str] = []
    page_url = f"{base_url}{SWAGGER_PAGE}"
    try:
        page = session.get(page_url, timeout=(10, 60))
        if page.ok:
            for found in re.findall(r"""["']([^"'\s]+(?:\.json|api-docs)[^"'\s]*)["']""", page.text):
                urls.append(urljoin(page_url, found))
    except Exception:  # 화면을 못 읽어도 흔한 위치로 계속 찾는다.
        pass
    urls.extend(f"{base_url}{path}" for path in SPEC_CANDIDATES)
    unique = dict.fromkeys(url for url in urls if same_origin(url, base_url))
    return list(unique)


def find_spec(session: Any, base_url: str) -> tuple[dict[str, Any] | None, list[str]]:
    """명세를 찾는다. 못 찾으면 후보마다 결과 종류만 돌려준다(주소는 찍지 않는다)."""
    outcomes: list[str] = []
    for url in spec_urls(session, base_url):
        try:
            response = session.get(url, timeout=(10, 120))
        except Exception as exc:
            outcomes.append(type(exc).__name__)
            continue
        if not response.ok:
            outcomes.append(f"HTTP {response.status_code}")
            continue
        try:
            payload = response.json()
        except ValueError:
            outcomes.append("JSON 아님")
            continue
        if isinstance(payload, dict) and isinstance(payload.get("paths"), dict):
            return payload, outcomes
        outcomes.append("명세 아님")
    return None, outcomes


def resolve(spec: dict[str, Any], value: Any) -> Any:
    """`$ref`를 따라간다. 따라갈 수 없으면 원래 값을 돌려준다."""
    if not isinstance(value, dict) or "$ref" not in value:
        return value
    target: Any = spec
    for part in str(value["$ref"]).lstrip("#/").split("/"):
        if not isinstance(target, dict) or part not in target:
            return value
        target = target[part]
    return target


def parameter_name(spec: dict[str, Any], parameter: Any) -> str:
    resolved = resolve(spec, parameter)
    if isinstance(resolved, dict) and resolved.get("name"):
        return str(resolved["name"])
    if isinstance(parameter, dict) and "$ref" in parameter:
        return str(parameter["$ref"]).rsplit("/", 1)[-1]
    return "?"


def marked(names: list[str]) -> list[str]:
    return [f"*{name}" if any(word in name.casefold() for word in TIME_WORDS) else name for name in names]


def operation_lines(spec: dict[str, Any]) -> list[str]:
    """첨부 경로와 비교용 아이템 단건 조회의 GET 매개변수."""
    lines: list[str] = []
    for path, operations in sorted(spec["paths"].items()):
        lowered = path.casefold()
        is_item = lowered.rstrip("/").endswith("/items/{itemid}")
        if "attachment" not in lowered and not is_item:
            continue
        if not isinstance(operations, dict) or not isinstance(operations.get("get"), dict):
            continue
        parameters = [*operations.get("parameters", []), *operations["get"].get("parameters", [])]
        names = marked([parameter_name(spec, parameter) for parameter in parameters])
        line = f"  GET {path}  [{', '.join(names) or '-'}]"
        lines.append(line if len(line) <= WIDTH else line[: WIDTH - 3] + "...")
    if len(lines) > MAX_OPERATIONS:
        lines = [*lines[:MAX_OPERATIONS], f"  ... 외 {len(lines) - MAX_OPERATIONS}개"]
    return lines


def schema_lines(spec: dict[str, Any]) -> list[str]:
    """첨부 모델에 시점을 나타내는 속성이 있는지."""
    schemas = spec.get("components", {}).get("schemas") or spec.get("definitions") or {}
    lines: list[str] = []
    for name, schema in sorted(schemas.items()):
        if "attachment" not in name.casefold() or not isinstance(schema, dict):
            continue
        properties = schema.get("properties") or {}
        for part in schema.get("allOf", []):
            resolved = resolve(spec, part)
            if isinstance(resolved, dict):
                properties = {**properties, **(resolved.get("properties") or {})}
        found = [key for key in properties if any(word in key.casefold() for word in TIME_WORDS)]
        lines.append(f"  {name}: {', '.join(found) if found else '시점 속성 없음'}")
    return lines[:8]


def main() -> None:
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 1절: 첨부 API의 Baseline 시점 지원 확인 (읽기 전용)")
    from src.codebeamer_client import CodebeamerClient
    from src.gui.settings_store import GuiSettingsStore

    settings = GuiSettingsStore().load()
    if not settings.base_url or not settings.password:
        print("실패: 저장된 연결 정보 없음 -> GUI에서 연결 테스트를 통과시킨 뒤 다시 실행")
        return
    client = CodebeamerClient(settings.base_url, settings.username, settings.password, None)
    spec, outcomes = find_spec(client._session(), client.base_url)
    if spec is None:
        print(f"실패: Swagger 명세를 찾지 못함 (후보 {len(outcomes)}개: {', '.join(outcomes) or '-'})")
        print("  -> 사내망/VPN과 GUI 연결 테스트 확인. 그래도 실패하면 이 화면만 보내 주세요")
        return
    version = spec.get("openapi") or spec.get("swagger") or "?"
    print(f"명세 형식 {version}, 경로 {len(spec['paths'])}개. *표는 baseline/version/revision이 든 매개변수")
    print("[첨부 경로와 아이템 단건 조회의 GET 매개변수]")
    print("\n".join(operation_lines(spec)) or "  첨부 경로 없음")
    print("[첨부 모델의 시점 속성]")
    print("\n".join(schema_lines(spec)) or "  첨부 모델 없음")


if __name__ == "__main__":
    main()
