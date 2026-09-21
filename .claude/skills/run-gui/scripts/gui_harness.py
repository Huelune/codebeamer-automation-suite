"""GUI를 오프스크린으로 띄우고 조작·캡처하기 위한 공용 harness.

드라이버 스크립트에서 이것만 import 하면 QApplication 준비, 오프라인 설정,
모달 창 가로채기, 위젯 캡처가 모두 해결된다.

사용 예는 `.claude/skills/run-gui/SKILL.md` 를 본다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


# QApplication 을 만들기 전에 정해야 한다. 창 관리자 없이 렌더링한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_DIR = PROJECT_ROOT / "data" / "gui-offline-sample"

_failures: list[str] = []


def make_app():
    """QApplication 을 하나만 만들어 돌려준다."""
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def offline_settings(**overrides: Any):
    """오프라인 샘플 데이터를 가리키는 GuiSettings 를 만든다.

    실서버에 붙지 않으므로 자격 증명이 필요 없고 결과가 매번 같다.
    """
    from src.gui.settings_store import GuiSettings

    values: dict[str, Any] = {
        "offline_mode": True,
        "offline_schema_path": str(SAMPLE_DIR / "offline_schema.json"),
        "offline_tracker_configuration_path": str(
            SAMPLE_DIR / "offline_tracker_configuration.json"
        ),
        "offline_query_data_path": str(SAMPLE_DIR / "offline_tracker_items.json"),
    }
    values.update(overrides)
    return GuiSettings(**values)


def open_modal(module: Any, class_name: str, action) -> Any:
    """`exec()` 로 열리는 모달 창을 가로채서 돌려준다.

    모달 창은 `exec()` 안에서 이벤트 루프를 돌기 때문에 그냥 부르면 스크립트가
    멈춘다. 그렇다고 `unittest.mock.patch.object` 로 Qt 메서드를 클래스에 직접
    갈아 끼우면 segfault 가 난다. 서브클래스에서 `exec` 만 덮는 것이 안전하다.

    진짜 클래스를 상속하므로 생성자는 그대로 실행된다. 창을 통째로 mock 으로
    바꾸면 생성자 인자가 잘못돼도 드러나지 않는다.
    """
    real = getattr(module, class_name)
    opened: list[Any] = []

    class _NonModal(real):  # type: ignore[misc, valid-type]
        def exec(self):
            opened.append(self)
            return 0

    setattr(module, class_name, _NonModal)
    try:
        action()
    finally:
        setattr(module, class_name, real)

    if not opened:
        raise AssertionError(f"{class_name} 이 열리지 않았다")
    return opened[-1]


def shot(widget, name: str, out_dir: str | Path = "shots") -> Path:
    """위젯을 PNG 로 저장한다. Read 도구로 바로 열어 볼 수 있다."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    image = widget.grab()
    path = target / f"{name}.png"
    image.save(str(path))
    print(f"  캡처 {path}  {image.width()}x{image.height()}")
    return path


def check(label: str, actual: Any, expected: Any) -> bool:
    """눈으로 볼 수 없는 값을 확인한다.

    오프스크린에는 한글 폰트가 없어 캡처에서 글자가 네모로 나온다. 레이아웃은
    캡처로 보고 텍스트는 이 함수로 확인하는 편이 확실하다.
    """
    ok = actual == expected
    print(f"  [{'OK' if ok else 'NG'}] {label}: {actual!r}")
    if not ok:
        _failures.append(f"{label}: {actual!r} != {expected!r}")
    return ok


def report() -> int:
    """확인 결과를 요약하고 종료 코드를 돌려준다."""
    print()
    if _failures:
        print(f"실패 {len(_failures)}건")
        for line in _failures:
            print(" -", line)
        return 1
    print("전부 통과")
    return 0


def drain(app) -> None:
    """남은 이벤트와 지연 파괴를 처리한다.

    `processEvents()` 만으로는 DeferredDelete 가 처리되지 않아 위젯이 살아남고,
    쌓이면 뒤 동작이 느려지거나 종료할 때 무너진다.
    """
    from PySide6.QtCore import QEvent

    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
