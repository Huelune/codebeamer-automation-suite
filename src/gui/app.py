from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.diagnostics import DIAGNOSTICS

from .settings_store import GuiSettingsStore
from .styles import build_gui_stylesheet


def run_gui(*, smoke_test: bool = False) -> int:
    """PySide6 애플리케이션을 만들고 메인 윈도우를 띄운다."""
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError(
            "GUI 실행에는 PySide6 패키지가 필요합니다. requirements.txt 를 설치한 뒤 다시 실행해야 합니다."
        ) from exc

    from .error_reporting import install_global_exception_handler
    from .main_window import MainWindow

    existing_app = QApplication.instance()
    app = existing_app if isinstance(existing_app, QApplication) else QApplication([])
    DIAGNOSTICS.clear()
    install_global_exception_handler(app, diagnostics=DIAGNOSTICS)
    smoke_settings_dir = (
        TemporaryDirectory(prefix="codebeamer-smoke-") if smoke_test else None
    )
    window = None
    try:
        store = GuiSettingsStore(
            root_dir=(Path(smoke_settings_dir.name) if smoke_settings_dir else None)
        )
        app.setStyleSheet(build_gui_stylesheet(store.load().theme_name))
        window = MainWindow(store)
        window.show()
        if smoke_test:
            QTimer.singleShot(0, app.quit)
        return app.exec()
    finally:
        if smoke_test and window is not None:
            window.close()
        if smoke_settings_dir is not None:
            smoke_settings_dir.cleanup()
