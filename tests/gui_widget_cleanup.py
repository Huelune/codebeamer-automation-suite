"""GUI 테스트가 남긴 Qt 위젯을 모듈 단위로 정리한다.

Qt 위젯은 `close()` 해도 파괴되지 않는다. 테스트가 만든 창이 계속 살아 있으면
이후 Qt 작업이 살아 있는 위젯 수에 비례해 느려진다. 정리 전 전체 스위트에서
후반 GUI 테스트 11개가 단독 실행 3.4초 대비 265초까지 늘어나 있었다.

사용법: GUI 위젯을 만드는 테스트 모듈에서 아래 한 줄을 import 한다.
unittest 가 모듈 이름 공간에서 `tearDownModule` 을 찾아 호출한다.

    from tests.gui_widget_cleanup import tearDownModule  # noqa: F401
"""

from __future__ import annotations


def tearDownModule() -> None:
    """모듈의 테스트가 끝난 뒤 남아 있는 최상위 위젯을 파괴한다."""
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - PySide6 없는 환경
        return

    app = QApplication.instance()
    if app is None:
        return

    for widget in list(app.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    app.processEvents()
    # processEvents 는 DeferredDelete 를 처리하지 않는다.
    # 이 호출이 있어야 위젯이 실제로 파괴된다.
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
