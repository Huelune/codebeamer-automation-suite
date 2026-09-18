from __future__ import annotations

import sys
from pathlib import Path


APPLICATION_NAME = "Codebeamer Automation Suite"
VERSION_FILE_NAME = "VERSION"


def application_root() -> Path:
    """Return the source or PyInstaller bundle root containing VERSION."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    return Path(__file__).resolve().parents[1]


def read_application_version(version_path: Path | None = None) -> str:
    path = version_path or (application_root() / VERSION_FILE_NAME)
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError(f"애플리케이션 버전 파일이 비어 있습니다: {path}")
    return version


APP_VERSION = read_application_version()
APPLICATION_TITLE = f"{APPLICATION_NAME} v{APP_VERSION}"


__all__ = [
    "APPLICATION_NAME",
    "APPLICATION_TITLE",
    "APP_VERSION",
    "VERSION_FILE_NAME",
    "application_root",
    "read_application_version",
]
