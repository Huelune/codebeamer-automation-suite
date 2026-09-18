"""서버 JSON 페이로드에서 값을 안전하게 꺼내는 공용 helper.

응답 값은 타입이 없고 필드가 빠져 있을 수 있다. 같은 변환을 여러 모듈이 각자
들고 있어 한 곳으로 모은다.
"""

from __future__ import annotations

from typing import Any


def as_mapping(value: Any) -> dict[str, Any]:
    """dict 가 아니면 빈 dict 로 바꿔 돌려준다.

    호출부에서 `x if isinstance(x, dict) else {}` 를 직접 쓰면 같은 식을 두 번
    평가하게 되고, 이후 `.get` 접근의 타입도 좁혀지지 않는다.
    """
    return value if isinstance(value, dict) else {}


def optional_int(value: Any) -> int | None:
    """정수로 바꿀 수 있으면 int, 아니면 None 을 돌려준다.

    빈 문자열과 bool 은 id 값이 될 수 없으므로 None 으로 본다.
    """
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
