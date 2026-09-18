from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.gui.service_core import GuiExcelService


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "gui-offline-sample"
FILES_DIR = SAMPLE_DIR / "files"


class GuiOfflineSampleDataTest(unittest.TestCase):
    def test_query_snapshot_contains_two_isolated_tracker_hierarchies(self) -> None:
        payload = json.loads(
            (SAMPLE_DIR / "offline_tracker_items.json").read_text(encoding="utf-8")
        )
        tracker_ids = {int(tracker["id"]) for tracker in payload["trackers"]}
        items_by_id = {int(item["id"]): item for item in payload["items"]}

        self.assertEqual(tracker_ids, {24680001, 24680002})
        self.assertTrue(
            {int(item["trackerId"]) for item in payload["items"]} <= tracker_ids
        )
        for item in payload["items"]:
            parent_id = item.get("parentId")
            if parent_id is None:
                continue
            self.assertEqual(
                int(items_by_id[int(parent_id)]["trackerId"]),
                int(item["trackerId"]),
            )

    def test_sample_snapshot_includes_tracker_item_query_source(self) -> None:
        schema = json.loads((SAMPLE_DIR / "offline_schema.json").read_text(encoding="utf-8"))
        config = json.loads((SAMPLE_DIR / "offline_tracker_configuration.json").read_text(encoding="utf-8"))

        schema_field_names = [field.get("name") for field in schema.get("fields", [])]
        self.assertIn("Related Requirement", schema_field_names)

        related_requirement_config = next(
            field
            for field in config.get("fields", [])
            if int(field.get("referenceId") or 0) == 7
        )
        filters = related_requirement_config["choiceOptionSetting"]["referenceFilters"]

        self.assertEqual(filters[0]["domainType"], "TRACKER")
        self.assertEqual(int(filters[0]["domainId"]), 24680001)

    def test_query_snapshot_status_and_custom_fields_exist_in_editor_schema(self) -> None:
        schema = json.loads((SAMPLE_DIR / "offline_schema.json").read_text(encoding="utf-8"))
        query_data = json.loads(
            (SAMPLE_DIR / "offline_tracker_items.json").read_text(encoding="utf-8")
        )
        fields_by_name = {
            str(field.get("name")): field for field in schema.get("fields", [])
        }
        status_ids = {
            int(option["id"]) for option in fields_by_name["Status"]["options"]
        }
        snapshot_status_ids = {
            int(item["status"]["id"])
            for item in query_data["items"]
            if isinstance(item.get("status"), dict)
        }

        self.assertIn("Risk Level", fields_by_name)
        self.assertEqual(status_ids, {201, 202, 203})
        self.assertLessEqual(snapshot_status_ids, status_ids)

    def test_happy_path_sample_workbooks_load_in_gui_excel_service(self) -> None:
        service = GuiExcelService()
        brake_file = FILES_DIR / "SAMPLE_MODULE_A_TC_001.xlsx"
        motor_file = FILES_DIR / "SAMPLE_MODULE_B_TC_002.xlsx"

        preview = service.load_preview(
            str(brake_file),
            file_paths=[str(motor_file)],
            sheet_name="Upload",
            header_row=1,
            summary_column="Summary",
        )

        self.assertEqual(preview.sheet_names, ["Upload"])
        self.assertEqual(preview.summary_column, "Summary")
        self.assertEqual(len(preview.raw_df_by_file), 2)
        self.assertIn("Related Requirement", preview.headers)
        self.assertEqual(int((~preview.raw_df["Summary"].isna()).sum()), 3)
        self.assertIsNone(preview.raw_df.iloc[1]["Summary"])
        self.assertEqual(preview.rows[1][0], "")

    def test_lookup_issue_sample_contains_expected_problem_values(self) -> None:
        service = GuiExcelService()
        lookup_file = FILES_DIR / "SAMPLE_LOOKUP_TC_003.xlsx"

        preview = service.load_preview(
            str(lookup_file),
            sheet_name="Upload",
            header_row=1,
            summary_column="Summary",
        )

        self.assertEqual(preview.raw_df.loc[0, "Owner"], "sample_user")
        self.assertEqual(preview.raw_df.loc[0, "Review Team"], "sample_group_a")
        self.assertEqual(preview.raw_df.loc[0, "Related Requirement"], "SAMPLE-ALPHA")


if __name__ == "__main__":
    unittest.main()
