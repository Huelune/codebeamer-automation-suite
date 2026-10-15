"""변경 이력·댓글·첨부·관계 API 응답 구조를 실서버에서 확인한다.

화면에는 응답의 키 이름, `type` 값, 건수만 찍는다. 필드 이름, 본문, 파일명, 사용자 같은 값은 찍지 않는다.
전체 응답은 임시 폴더의 파일에 써서 이 PC에서만 본다.

저장소 루트의 가상환경으로 실행한다.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "cb_item_activity_contract.json"
WIDTH = 116
MAX_LINES = 38
_SCHEMA_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_HTTP_ACTIONS = {
    401: "인증 실패 · 사용자·비밀번호 확인",
    403: "권한 없음 · 아이템을 볼 수 있는 계정으로 다시 실행",
    404: "없음 · 아이템 ID 확인",
    429: "요청 제한 · 잠시 뒤 다시 실행",
}


def _names(values: Iterable[Any]) -> str:
    values = list(values)
    safe = sorted({value for value in values if isinstance(value, str) and _SCHEMA_NAME.fullmatch(value)})
    other = len({repr(value) for value in values if not (isinstance(value, str) and _SCHEMA_NAME.fullmatch(value))})
    text = ", ".join(safe) or "-"
    return f"{text} (기타 {other}개)" if other else text


def _line(label: str, values: Iterable[Any]) -> str:
    text = f"  {label}: {_names(values)}"
    return text if len(text) <= WIDTH else text[: WIDTH - 1] + "…"


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _items(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _dicts(payload)
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), list):
                return _dicts(payload[key])
    return []


def _keys(items: Iterable[dict[str, Any]]) -> set[str]:
    return {key for item in items for key in item}


def summarize_contract(history: Any, comments: Any, attachments: Any, relations: Any) -> list[str]:
    versions = _items(history, ("versions", "history", "items", "content"))
    changes = [change for version in versions for change in _dicts(version.get("changes"))]
    fields = [change["field"] for change in changes if isinstance(change.get("field"), dict)]
    values = [
        change[side] for change in changes for side in ("oldValue", "newValue") if isinstance(change.get(side), dict)
    ]
    comment_items = _items(comments, ("comments", "items", "content"))
    attachment_items = _items(attachments, ("attachments", "attachmentRefs", "items", "references", "content"))
    groups = relations if isinstance(relations, dict) else {}
    relation_groups = [group for group in groups.values() if isinstance(group, list)]
    relation_items = [item for group in relation_groups for item in _dicts(group)]
    time_keys = ("createdAt", "createdBy", "modifiedAt", "modifiedBy")
    return [
        f"[변경 이력] 버전 {len(versions)}건 · 변경 {len(changes)}건",
        _line("응답 키", history.keys() if isinstance(history, dict) else []),
        _line("버전 키", _keys(versions)),
        _line("변경 키", _keys(changes)),
        _line("변경 type 값", [change.get("type") for change in changes if "type" in change]),
        _line("field 키", _keys(fields)),
        _line("값 type 값", [value.get("type") for value in values if "type" in value]),
        f"  field 없는 변경: {len(changes) - len(fields)}건",
        f"[댓글] {len(comment_items)}건",
        _line("댓글 키", _keys(comment_items)),
        f"[첨부] {len(attachment_items)}건",
        _line("첨부 키", _keys(attachment_items)),
        "  시각·사용자 키가 있는 첨부: "
        + " · ".join(f"{key} {sum(key in item for item in attachment_items)}" for key in time_keys),
        f"[관계] 그룹 {len(relation_groups)}개 · 항목 {len(relation_items)}건",
        _line("관계 그룹 키", groups.keys()),
        _line("관계 항목 키", _keys(relation_items)),
        _line("관계 type 값", [item.get("type") for item in relation_items if "type" in item]),
    ]


def failure_text(exc: Exception) -> str:
    """오류 종류와 할 일만 돌려준다. 예외 메시지에는 주소나 값이 들어 있을 수 있어 쓰지 않는다."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return f"HTTP {status} {_HTTP_ACTIONS.get(status, '서버 오류 · 잠시 뒤 다시 실행')}"
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return "연결 실패 · 서버 주소와 네트워크 확인"
    return f"{type(exc).__name__} · 응답 형식 확인 필요"


def _clear_screen() -> None:
    # 사용자 입력이 섞이지 않는 고정 명령이다.
    os.system("cls" if os.name == "nt" else "clear")


def main() -> int:
    """입력 취소와 예상하지 못한 오류도 traceback 대신 안내 문구 한 줄로 끝낸다."""
    try:
        return _run()
    except (KeyboardInterrupt, EOFError):
        print("입력을 취소했습니다. 다시 실행하세요.")
        return 1
    except Exception:
        print("예상하지 못한 오류 · 다시 실행하고, 반복되면 이 화면만 알려 주세요.")
        return 1


def _run() -> int:
    sys.path.insert(0, str(ROOT))
    from src.codebeamer_client import CodebeamerClient

    _clear_screen()
    base_url = input("서버 주소: ").strip()
    username = input("사용자: ").strip()
    password = getpass.getpass("비밀번호(화면에 보이지 않음): ")
    item_text = input("아이템 ID(변경 이력·댓글·첨부가 있는 것): ").strip()
    # 입력한 주소와 계정이 캡처에 남지 않게 지운다.
    _clear_screen()
    if not (item_text.isascii() and item_text.isdigit()):
        print("아이템 ID는 숫자여야 합니다. 다시 실행하세요.")
        return 2
    client = CodebeamerClient(base_url, username, password)
    item_id = int(item_text)
    calls = {
        "history": client.get_item_history,
        "comments": client.get_item_comments,
        "attachments": client.get_item_attachments,
        "relations": client.get_item_relations,
    }
    responses: dict[str, Any] = {}
    failures: list[str] = []
    for name, call in calls.items():
        try:
            responses[name] = call(item_id)
        except Exception as exc:
            responses[name] = None
            failures.append(f"  {name}: {failure_text(exc)}")
    text = json.dumps(responses, ensure_ascii=False, indent=2, default=str)
    try:
        report = Path(tempfile.gettempdir()) / REPORT_NAME
        report.write_text(text, encoding="utf-8")
    except OSError:
        footer = "전체 응답 파일 쓰기 실패 · 임시 폴더 쓰기 권한 확인"
        status = 1
    else:
        footer = f"전체 응답: %TEMP%\\{REPORT_NAME} (이 PC에서만 보고 밖으로 보내지 않습니다)"
        status = 0
    lines = summarize_contract(
        responses["history"], responses["comments"], responses["attachments"], responses["relations"]
    )
    if failures:
        lines += ["[조회 실패]", *failures]
    lines.append(footer)
    print("\n".join(lines[:MAX_LINES]))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
