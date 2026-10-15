"""todo.md 1절: 서버가 쓰는 날짜 형식을 읽기 전용으로 확인한다. 결과를 받으면 이 파일과 절을 지운다."""

import collections
import os
import re
import sys
import warnings
from pathlib import Path


warnings.simplefilter("ignore")
# 이 파일 위치에서 저장소 루트를 찾는다. 어느 폴더에서 실행해도 같다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BUILTIN_KEYS = ("createdAt", "modifiedAt", "startDate", "endDate", "closedAt")


def shape(value):
    # 숫자만 9로 바꿔 모양만 남긴다. 날짜 값 자체는 찍지 않는다.
    return re.sub(r"\d", "9", str(value))


def collect(client, tracker_id):
    schema = client.get_tracker_schema(tracker_id)
    fields = schema.get("fields", []) if isinstance(schema, dict) else schema
    date_field_count = sum(1 for field in fields if str(field.get("type")) == "DateField")
    payload = client.search_items(
        query_string=f"tracker.id = {tracker_id} ORDER BY item.id DESC",
        page=1,
        page_size=50,
    )
    items = payload.get("items", []) if isinstance(payload, dict) else []
    builtin: collections.Counter[tuple[str, str]] = collections.Counter()
    custom: collections.Counter[str] = collections.Counter()
    for item in items:
        for key in BUILTIN_KEYS:
            if item.get(key):
                builtin[(key, shape(item[key]))] += 1
        for field in item.get("customFields") or []:
            if str(field.get("type")) == "DateFieldValue" and field.get("value"):
                custom[shape(field["value"])] += 1
    return date_field_count, len(items), builtin, custom


def main():
    # 고정 문자열이라 입력이 섞이지 않는다. 결과를 한 화면에 담으려고 먼저 지운다.
    os.system("cls" if os.name == "nt" else "clear")
    print("todo 1절: 서버 날짜 형식 확인 (읽기 전용)")
    from src.codebeamer_client import CodebeamerClient
    from src.gui.settings_store import GuiSettingsStore

    settings = GuiSettingsStore().load()
    if not settings.base_url or not settings.password:
        print("실패: 저장된 연결 정보 없음 -> GUI에서 연결 테스트를 통과시킨 뒤 다시 실행")
        return
    if not str(settings.default_tracker_id or "").strip():
        print("실패: 기본 트래커 없음 -> GUI 설정에서 트래커를 고르고 저장한 뒤 다시 실행")
        return
    client = CodebeamerClient(settings.base_url, settings.username, settings.password, None)
    try:
        date_field_count, item_count, builtin, custom = collect(client, int(settings.default_tracker_id))
    except Exception as exc:  # 원문에는 주소가 들어 있을 수 있어 종류만 찍는다.
        print(f"실패: 서버 조회 실패({type(exc).__name__}) -> 사내망/VPN과 GUI 연결 테스트 확인")
        return
    print(f"DateField 정의 {date_field_count}개, 읽은 아이템 {item_count}개")
    print("[기본 필드]")
    for (key, value_shape), count in sorted(builtin.items()):
        print(f"  {key:<10} {value_shape:<32} {count}개")
    print("[사용자 정의 DateField 값]")
    if not custom:
        print("  값 있는 항목 없음")
    for value_shape, count in custom.most_common(8):
        print(f"  {value_shape:<43} {count}개")


if __name__ == "__main__":
    main()
