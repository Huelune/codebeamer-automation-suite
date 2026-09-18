from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gui_main
from src.app_metadata import APP_VERSION
from src.app_metadata import read_application_version


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GUI_ENTRYPOINT = REPOSITORY_ROOT / "gui_main.py"


class ApplicationVersionTest(unittest.TestCase):
    def test_version_comes_from_repository_version_file(self) -> None:
        version_file = REPOSITORY_ROOT / "VERSION"
        expected_version = version_file.read_text(encoding="utf-8").strip()

        self.assertRegex(
            expected_version,
            r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$",
        )
        self.assertEqual(APP_VERSION, expected_version)
        self.assertEqual(read_application_version(version_file), expected_version)

    def test_empty_version_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            version_path = Path(temp_dir) / "VERSION"
            version_path.write_text("\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "버전 파일이 비어 있습니다"):
                read_application_version(version_path)


class GuiEntrypointTest(unittest.TestCase):
    def test_version_exits_cleanly_when_windowed_build_has_no_stdout(self) -> None:
        with patch.object(gui_main, "_version_output_stream", return_value=None):
            self.assertEqual(gui_main.main(["--version"]), 0)

    def test_version_exits_without_starting_gui(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GUI_ENTRYPOINT), "--version"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), APP_VERSION)
        self.assertEqual(result.stderr, "")

    def test_smoke_test_creates_main_window_and_exits(self) -> None:
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, str(GUI_ENTRYPOINT), "--smoke-test"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
