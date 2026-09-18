from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class WindowsReleasePackagingContractTest(unittest.TestCase):
    def test_spec_resolves_repository_from_spec_directory(self) -> None:
        spec = (
            REPOSITORY_ROOT / "packaging" / "CodebeamerAutomationSuite.spec"
        ).read_text(encoding="utf-8")

        ast.parse(spec)
        self.assertIn(
            "REPOSITORY_ROOT = Path(SPECPATH).resolve().parent\n",
            spec,
        )
        self.assertNotIn("Path(SPECPATH).resolve().parent.parent", spec)

    def test_spec_keeps_windowed_onedir_runtime_contract(self) -> None:
        spec = (
            REPOSITORY_ROOT / "packaging" / "CodebeamerAutomationSuite.spec"
        ).read_text(encoding="utf-8")

        for contract in (
            '"VERSION"',
            '"src" / "gui" / "assets"',
            '"PySide6.QtSvg"',
            '"keyring.backends.Windows"',
            '"win32ctypes.pywin32.win32cred"',
            'collect_submodules("win32com")',
            '"xlwings._xlwindows"',
            "console=False",
            "coll = COLLECT(",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, spec)

    def test_release_requirements_are_exactly_pinned(self) -> None:
        requirements = (
            REPOSITORY_ROOT / "requirements-release.txt"
        ).read_text(encoding="utf-8")

        requirement_lines = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            set(requirement_lines),
            {
                "pandas==3.0.2",
                "requests==2.33.1",
                "xlwings==0.35.1",
                "python-dotenv==1.2.2",
                "openpyxl==3.1.5",
                "PySide6==6.11.0",
                "cryptography==50.0.0",
                "keyring==25.7.0",
                "PyInstaller==6.21.0",
            },
        )
        self.assertTrue(all(line.count("==") == 1 for line in requirement_lines))

    def test_build_script_passes_native_python_arguments_explicitly(self) -> None:
        script = (
            REPOSITORY_ROOT / "scripts" / "build_windows_release.ps1"
        ).read_text(encoding="utf-8")

        self.assertNotIn("Invoke-Python -m", script)
        self.assertIn('Invoke-Python -Arguments @(\n        "-m",', script)
        self.assertIn(
            '"scripts/release_metadata.py"),\n            "validate-tag",',
            script,
        )

    def test_dependency_pem_files_are_not_rejected_from_internal_bundle(self) -> None:
        script = (
            REPOSITORY_ROOT / "scripts" / "build_windows_release.ps1"
        ).read_text(encoding="utf-8")
        sample_filter = script.split("function Copy-OfflineSample", 1)[1].split(
            "function Assert-PortableContents", 1
        )[0]
        portable_validation = script.split(
            "function Assert-PortableContents", 1
        )[1].split("function Build-Application", 1)[0]

        self.assertIn('".pem"', sample_filter)
        self.assertNotIn('".pem"', portable_validation)
        self.assertIn('$_.Name -eq ".DS_Store"', portable_validation)
        self.assertIn('$_.Name.StartsWith(".env"', portable_validation)

    def test_release_job_only_publishes_on_tag_push(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "windows-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "if: github.event_name == 'push' && "
            "startsWith(github.ref, 'refs/tags/v')",
            workflow,
        )
        self.assertNotIn("pull_request_target", workflow)

    def test_workflow_actions_are_pinned_to_full_commit_shas(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "windows-release.yml"
        ).read_text(encoding="utf-8")
        action_references = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)

        self.assertTrue(action_references)
        for reference in action_references:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r"^[^@\s]+@[0-9a-f]{40}$")
        self.assertIn(
            "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6",
            action_references,
        )
        self.assertIn("artifact-metadata: write", workflow)
        self.assertFalse(
            any(
                reference.startswith("actions/attest-build-provenance@")
                for reference in action_references
            )
        )

    def test_release_resume_uses_paginated_release_listing(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "windows-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("--paginate", workflow)
        self.assertIn("--slurp", workflow)
        self.assertIn('if ($release.tag_name -eq $tag)', workflow)
        self.assertNotIn("releases/tags/$tag", workflow)
        self.assertLess(
            workflow.index("- name: Create or resume draft release"),
            workflow.index("- name: Attest portable ZIP provenance"),
        )
        self.assertLess(
            workflow.index("- name: Attest portable ZIP provenance"),
            workflow.index("- name: Upload assets and publish draft release"),
        )


if __name__ == "__main__":
    unittest.main()
