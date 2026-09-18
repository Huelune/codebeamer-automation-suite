from __future__ import annotations

import argparse
import ctypes
import os
import sys
from collections.abc import Sequence
from typing import TextIO

from src.app_metadata import APP_VERSION
from src.app_metadata import APPLICATION_NAME


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APPLICATION_NAME)
    parser.add_argument(
        "--version",
        action="store_true",
        help="애플리케이션 버전을 출력하고 종료합니다.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="offscreen에서 메인 창을 생성한 뒤 즉시 종료합니다.",
    )
    return parser


def _version_output_stream() -> TextIO | None:
    """Return a writable stream, attaching a parent console for windowed EXEs."""
    if sys.stdout is not None:
        return sys.stdout
    if os.name != "nt":
        return None

    try:
        if not ctypes.windll.kernel32.AttachConsole(-1):
            return None
        # sys.stdout 으로 넘겨 프로세스가 끝날 때까지 유지하므로 context manager 를 쓰지 않는다.
        stream = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    except (AttributeError, OSError):
        return None

    sys.stdout = stream
    return stream


def _write_version() -> None:
    stream = _version_output_stream()
    if stream is None:
        return
    stream.write(f"{APP_VERSION}\n")
    stream.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    if args.version:
        _write_version()
        return 0

    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    # --version은 Qt 또는 다른 GUI 의존성을 로드하지 않아야 한다.
    from src.gui.app import run_gui

    return run_gui(smoke_test=bool(args.smoke_test))


if __name__ == "__main__":
    raise SystemExit(main())
