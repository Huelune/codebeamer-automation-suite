from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.gui.page_batch_settings import create_batch_settings_page
from src.gui.page_common import _build_tracker_item_regex_preview_text
from src.gui.page_common import _configure_constrained_panel
from src.gui.page_common import _project_selection_refresh_button_text
from src.gui.page_common import _project_selection_source_signature
from src.gui.page_common import _project_selection_status_text
from src.gui.page_common import _settings_mode_description
from src.gui.page_common import _settings_mode_toggle_text
from src.gui.page_common import _tracker_item_sample_values
from src.gui.page_execution_mapping import MappingPage
from src.gui.page_execution_mapping import create_mapping_page
from src.gui.page_execution_run import UploadPage
from src.gui.page_execution_run import create_result_page
from src.gui.page_execution_run import create_upload_page
from src.gui.page_execution_run import create_validation_page
from src.gui.page_setup_file import FileSelectionPage
from src.gui.page_setup_file import RootItemPage
from src.gui.page_setup_file import create_file_selection_page
from src.gui.page_setup_file import create_root_item_page
from src.gui.service_core import FileSignature
from src.gui.service_core import PreviewData
from src.gui.service_core import SheetPreviewData
from src.gui.service_core import WorkbookMetadata
from src.gui.settings_store import GuiSettings
from src.gui.styles import build_gui_stylesheet


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GuiPagesSettingsModeTest(unittest.TestCase):
    def test_settings_mode_toggle_text_stays_compact_in_both_states(self) -> None:
        self.assertEqual(_settings_mode_toggle_text(True), "테스트")
        self.assertEqual(_settings_mode_toggle_text(False), "테스트")

    def test_settings_mode_description_changes_by_mode(self) -> None:
        self.assertIn("snapshot", _settings_mode_description(True))
        self.assertIn("Codebeamer", _settings_mode_description(False))


class GuiPagesProjectSelectionTest(unittest.TestCase):
    def test_project_selection_status_text_changes_by_mode(self) -> None:
        self.assertIn("자동으로", _project_selection_status_text(True))
        self.assertIn("프로젝트 불러오기", _project_selection_status_text(False))

    def test_project_selection_refresh_button_text_changes_by_mode(self) -> None:
        self.assertEqual(_project_selection_refresh_button_text(True), "스냅샷 불러오기")
        self.assertEqual(_project_selection_refresh_button_text(False), "프로젝트 불러오기")

    def test_project_selection_source_signature_ignores_selected_project_id(self) -> None:
        base_settings = {
            "offline_mode": True,
            "offline_schema_path": "/tmp/schema.json",
            "offline_tracker_configuration_path": "/tmp/config.json",
            "base_url": "https://example.test",
            "username": "tester",
        }
        left = SimpleNamespace(**base_settings, default_project_id="1")
        right = SimpleNamespace(**base_settings, default_project_id="99")

        self.assertEqual(
            _project_selection_source_signature(left),
            _project_selection_source_signature(right),
        )


class GuiPagesTrackerItemPreviewTest(unittest.TestCase):
    def test_tracker_item_regex_preview_text_shows_single_and_multi_value_examples(self) -> None:
        preview_text = _build_tracker_item_regex_preview_text(
            [
                "Candidate [REQ:20263671] extra",
                ["REQ [REQ:20263672]", "20263673"],
            ],
            pattern=r"\[(?:[^:\]]+:)?(\d+)[^\]]*\]|^(\d+)(?:\.0)?$",
            multiple_values=True,
        )

        self.assertIn("Candidate [REQ:20263671] extra -> 20263671", preview_text)
        self.assertIn("REQ [REQ:20263672], 20263673 -> 20263672, 20263673", preview_text)

    def test_tracker_item_regex_preview_text_shows_short_error_labels(self) -> None:
        preview_text = _build_tracker_item_regex_preview_text(
            ["REQ-ABC"],
            pattern=r"\[(?:[^:\]]+:)?(\d+)[^\]]*\]|^(\d+)(?:\.0)?$",
            multiple_values=False,
        )

        self.assertEqual(preview_text, "REQ-ABC -> 불일치")

    def test_tracker_item_sample_values_skips_blank_and_duplicate_values(self) -> None:
        upload_preview_df = pd.DataFrame({
            "연관 요구사항": [
                "",
                None,
                "REQ-100",
                "REQ-100",
                ["REQ-200", ""],
                ["REQ-200"],
                "REQ-300",
            ]
        })

        sample_values = _tracker_item_sample_values(upload_preview_df, "연관 요구사항")

        self.assertEqual(sample_values, ["REQ-100", ["REQ-200", ""], "REQ-300"])


class GuiPagesUploadPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWidgets import QSizePolicy

        cls._app = QApplication.instance() or QApplication([])
        cls._expanding_policy = QSizePolicy.Policy.Expanding

    def test_upload_page_reset_restores_start_button_state(self) -> None:
        page = create_upload_page(
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
        )

        self.assertIsInstance(page, UploadPage)
        page.start_button.setEnabled(False)
        page.pause_button.setEnabled(True)
        page.resume_button.setEnabled(True)
        page.cancel_button.setEnabled(True)
        page.result_button.setEnabled(True)

        page.reset(3)

        self.assertTrue(page.start_button.isEnabled())
        self.assertFalse(page.pause_button.isEnabled())
        self.assertFalse(page.resume_button.isEnabled())
        self.assertFalse(page.cancel_button.isEnabled())
        self.assertFalse(page.result_button.isEnabled())
        self.assertEqual(page.progress_label.text(), "진행률 0.0% (0 / 3)")
        self.assertEqual(page.eta_label.text(), "예상 종료: -")

    def test_file_selection_preview_table_uses_expanding_layout_space(self) -> None:
        page = create_file_selection_page(
            GuiSettings(),
            lambda _state: None,
            lambda _state: None,
        )

        self.assertIsInstance(page, FileSelectionPage)
        layout = page.layout()
        preview_index = layout.indexOf(page.preview_table)

        self.assertEqual(layout.stretch(preview_index), 1)
        self.assertEqual(
            page.preview_table.sizePolicy().verticalPolicy(),
            self._expanding_policy,
        )

    def test_file_selection_requires_explicit_preview_and_full_load_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.xlsx"
            path.write_bytes(b"sample")
            signature = FileSignature.capture(str(path))
            calls: list[str] = []
            states: list[dict[str, object]] = []

            def load_metadata(file_path: str) -> WorkbookMetadata:
                calls.append("metadata")
                return WorkbookMetadata(file_path, ["Main"], signature)

            def load_sheet_preview(file_path: str, **_kwargs) -> SheetPreviewData:
                calls.append("sheet_preview")
                return SheetPreviewData(
                    file_path=file_path,
                    sheet_name="Main",
                    header_row=1,
                    summary_column="Summary",
                    headers=["Summary", "담당자"],
                    rows=[["REQ-001", "홍길동"]],
                    suggested_summary="Summary",
                    signature=signature,
                )

            def load_full(file_path: str, **_kwargs) -> PreviewData:
                calls.append("full")
                raw_df = pd.DataFrame([{"Summary": "REQ-001", "담당자": "홍길동"}])
                return PreviewData(
                    file_path=file_path,
                    sheet_name="Main",
                    header_row=1,
                    summary_column="Summary",
                    sheet_names=["Main"],
                    headers=["Summary", "담당자"],
                    rows=[["REQ-001", "홍길동"]],
                    suggested_summary="Summary",
                    raw_df=raw_df,
                    raw_df_by_file={file_path: raw_df},
                    file_signatures={file_path: signature},
                )

            page = create_file_selection_page(
                GuiSettings(),
                lambda state: states.append(dict(state)),
                lambda *_args, **_kwargs: None,
                on_file_metadata_requested=load_metadata,
                on_sheet_preview_requested=load_sheet_preview,
                on_full_data_requested=load_full,
            )

            page.load_state(
                {
                    "file_paths": [str(path)],
                    "preview_file_path": str(path),
                    "sheet_name": "Main",
                    "header_row": 1,
                    "summary_column": "Summary",
                }
            )

            self.assertEqual(calls, ["metadata"])
            self.assertFalse(page._sheet_preview_ready)
            self.assertFalse(page._preview_ready)
            self.assertFalse(page.summary_column_combo.isEditable())
            self.assertFalse(page.summary_column_combo.isEnabled())

            page.preview_button.click()

            self.assertEqual(calls, ["metadata", "sheet_preview"])
            self.assertTrue(page._sheet_preview_ready)
            self.assertFalse(page._preview_ready)
            self.assertTrue(page.summary_column_combo.isEnabled())
            self.assertEqual(
                [
                    page.summary_column_combo.itemText(index)
                    for index in range(page.summary_column_combo.count())
                ],
                ["Summary", "담당자"],
            )
            page.summary_column_combo.setCurrentText("임의 컬럼")
            self.assertEqual(page.summary_column_combo.currentText(), "Summary")

            page.load_button.click()

            self.assertEqual(calls, ["metadata", "sheet_preview", "full"])
            self.assertTrue(page._preview_ready)
            self.assertIs(states[-1]["preview_data"], page._preview_data)

    def test_mapping_page_keeps_tabs_and_tables_expandable(self) -> None:
        page = create_mapping_page(lambda *_args: None)

        self.assertIsInstance(page, MappingPage)
        layout = page.layout()
        tabs_index = layout.indexOf(page.mapping_tabs)

        self.assertEqual(page.mapping_tabs.count(), 3)
        self.assertEqual(layout.stretch(tabs_index), 1)
        self.assertEqual(
            page.mapping_table.sizePolicy().verticalPolicy(),
            self._expanding_policy,
        )
        self.assertEqual(
            page.default_table.sizePolicy().verticalPolicy(),
            self._expanding_policy,
        )
        self.assertEqual(
            page.tracker_item_table.sizePolicy().verticalPolicy(),
            self._expanding_policy,
        )

    def test_mapping_table_checkbox_is_visible_and_clickable(self) -> None:
        from PySide6.QtWidgets import QStyle
        from PySide6.QtWidgets import QStyleOptionButton

        page = create_mapping_page(lambda *_args: None)
        page.load_context(
            "create",
            ["Summary"],
            pd.DataFrame([
                {
                    "field_name": "Summary",
                    "field_type": "TextField",
                    "multiple_values": False,
                    "is_supported": True,
                }
            ]),
            {"Summary": "Summary"},
            {"Summary": {"create": True, "update": False}},
            [],
            {},
            {},
            {},
        )
        previous_stylesheet = self._app.styleSheet()
        try:
            self._app.setStyleSheet(build_gui_stylesheet("kefico"))
            page.show()
            self._app.processEvents()

            checkbox = page.mapping_table.cellWidget(0, 0)
            option = QStyleOptionButton()
            checkbox.initStyleOption(option)
            indicator_rect = checkbox.style().subElementRect(
                QStyle.SubElement.SE_CheckBoxIndicator,
                option,
                checkbox,
            )

            self.assertGreaterEqual(indicator_rect.width(), 15)
            self.assertGreaterEqual(indicator_rect.height(), 15)
            self.assertTrue(checkbox.isChecked())
            checkbox.click()
            self.assertFalse(checkbox.isChecked())
        finally:
            page.close()
            self._app.setStyleSheet(previous_stylesheet)

    def test_root_item_page_is_a_concrete_widget_subclass(self) -> None:
        page = create_root_item_page(lambda *_args: None)

        self.assertIsInstance(page, RootItemPage)

    def test_validation_and_result_pages_prioritize_data_areas(self) -> None:
        validation_page = create_validation_page()
        result_page = create_result_page()

        validation_layout = validation_page.layout()
        result_layout = result_page.layout()

        self.assertEqual(
            validation_layout.stretch(validation_layout.indexOf(validation_page.issue_table)),
            1,
        )
        self.assertEqual(
            validation_page.issue_table.sizePolicy().verticalPolicy(),
            self._expanding_policy,
        )
        self.assertEqual(
            result_layout.stretch(result_layout.indexOf(result_page.result_tabs)),
            1,
        )
        self.assertEqual(
            result_page.tables["success_df"].sizePolicy().verticalPolicy(),
            self._expanding_policy,
        )

    def test_export_and_retry_buttons_follow_current_result_capabilities(self) -> None:
        validation_page = create_validation_page()
        result_page = create_result_page()

        self.assertFalse(validation_page.export_validation_button.isEnabled())
        validation_page.set_results(pd.DataFrame(), False, {"total_rows": 0})
        self.assertTrue(validation_page.export_validation_button.isEnabled())

        failed_df = pd.DataFrame(
            [{"_row_id": 1, "upload_name": "REQ-001", "error": "temporary"}]
        )
        result_page.set_results(
            {
                "success_df": pd.DataFrame(),
                "failed_df": failed_df,
                "unresolved_df": pd.DataFrame(),
                "retry_context": None,
                "retry_unavailable_reason": "검증 단계에서 수정하세요.",
            }
        )
        self.assertTrue(result_page.export_failed_button.isEnabled())
        self.assertFalse(result_page.retry_failed_button.isEnabled())
        self.assertIn("검증 단계", result_page.status_label.text())

        result_page.set_results(
            {
                "success_df": pd.DataFrame(),
                "failed_df": failed_df,
                "unresolved_df": pd.DataFrame(),
                "retry_context": SimpleNamespace(
                    retry_target_count=1,
                    non_retryable_count=0,
                ),
            }
        )
        self.assertTrue(result_page.retry_failed_button.isEnabled())
        self.assertIn("생성, 수정, 혼합 처리", result_page.status_label.text())

    def test_constrained_panel_remains_horizontally_responsive(self) -> None:
        from PySide6.QtWidgets import QWidget

        panel = QWidget()

        _configure_constrained_panel(panel)

        self.assertEqual(
            panel.sizePolicy().horizontalPolicy(),
            self._expanding_policy,
        )
        self.assertGreaterEqual(panel.maximumWidth(), 1_000_000)


class GuiBatchSettingsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_batch_settings_preserve_global_values_and_edit_only_batch_fields(self) -> None:
        changes = []
        initial = GuiSettings(
            base_url="https://example.test",
            username="tester",
            password="secret",
            theme_name="igloo",
            excel_header_row=1,
            summary_column="Summary",
        )
        page = create_batch_settings_page(initial, changes.append)

        page.header_row.setValue(3)
        page.summary_column.setText("요약")
        current = page.get_settings()

        self.assertEqual(current.base_url, "https://example.test")
        self.assertEqual(current.username, "tester")
        self.assertEqual(current.password, "secret")
        self.assertEqual(current.theme_name, "igloo")
        self.assertEqual(current.excel_header_row, 3)
        self.assertEqual(current.summary_column, "요약")
        self.assertTrue(changes)
        self.assertNotIn("base_url", page.__dict__)

    def test_batch_settings_link_opens_global_settings_callback(self) -> None:
        requests = []
        page = create_batch_settings_page(
            GuiSettings(),
            lambda _settings: None,
            lambda: requests.append("open"),
        )

        page.global_settings_button.click()

        self.assertEqual(requests, ["open"])
        self.assertFalse(page.next_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
