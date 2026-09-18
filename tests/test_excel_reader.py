from __future__ import annotations

from copy import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook

from src.excel_reader import ExcelReader


class ExcelReaderTest(unittest.TestCase):
    def test_openpyxl_path_reads_sheet_names_headers_rows_and_indent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Main"
            sheet.append(["메타", "메타"])
            sheet.append(["Summary", "설명"])
            sheet.append(["Parent", "상위"])
            sheet.append([None, "연속 행"])
            sheet.append(["Child", "하위"])
            parent_alignment = copy(sheet["A3"].alignment)
            parent_alignment.indent = 1
            sheet["A3"].alignment = parent_alignment
            child_alignment = copy(sheet["A5"].alignment)
            child_alignment.indent = 2
            sheet["A5"].alignment = child_alignment
            workbook.create_sheet("Other")
            workbook.save(path)
            workbook.close()

            reader = ExcelReader(header_row=2, summary_col="Summary")

            self.assertEqual(reader.list_sheet_names(str(path)), ["Main", "Other"])
            self.assertEqual(reader.read_headers(str(path), "0"), ["Summary", "설명"])

            raw_df = reader.read_excel(str(path), sheet_name=0)

            self.assertEqual(raw_df["Summary"].tolist(), ["Parent", None, "Child"])
            self.assertEqual(raw_df["_excel_row"].tolist(), [3, 4, 5])
            self.assertEqual(raw_df["_summary_indent"].tolist(), [1, 0, 2])

    def test_count_upload_rows_supports_sheet_index_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Main"
            sheet.append(["Summary", "설명"])
            sheet.append(["REQ-001", "첫 번째"])
            sheet.append([None, "연속 행"])
            sheet.append(["REQ-002", "두 번째"])
            workbook.save(path)
            workbook.close()

            reader = ExcelReader(header_row=1, summary_col="Summary")

            self.assertEqual(reader.count_upload_rows(str(path), "0"), 2)

    def test_read_preview_rows_limits_non_blank_rows_without_loading_full_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Main"
            sheet.append(["metadata", "metadata"])
            sheet.append(["Summary", "설명"])
            sheet.append([None, None])
            sheet.append(["REQ-001", 101])
            sheet.append(["REQ-002", 202])
            sheet.append(["REQ-003", 303])
            workbook.save(path)
            workbook.close()

            reader = ExcelReader(header_row=2, summary_col="Summary")

            headers, rows = reader.read_preview_rows(
                str(path),
                "Main",
                max_rows=2,
            )

            self.assertEqual(headers, ["Summary", "설명"])
            self.assertEqual(rows, [["REQ-001", 101], ["REQ-002", 202]])

    def test_openpyxl_reads_only_through_last_non_blank_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "formatted-range.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Summary", "설명"])
            sheet.append(["REQ-001", "첫 번째"])
            sheet.cell(row=20, column=200).number_format = "0"
            workbook.save(path)
            workbook.close()

            reader = ExcelReader(header_row=1, summary_col="Summary")

            headers, rows = reader.read_preview_rows(
                str(path),
                0,
                max_rows=1,
            )
            raw_df = reader.read_excel(str(path), sheet_name=0)

            self.assertEqual(headers, ["Summary", "설명"])
            self.assertEqual(rows, [["REQ-001", "첫 번째"]])
            self.assertEqual(list(raw_df.columns), [
                "Summary",
                "설명",
                "_excel_row",
                "_summary_indent",
            ])

    def test_preview_rejects_excessive_blank_used_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "excessive-range.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Summary", "설명"])
            sheet.append(["REQ-001", "첫 번째"])
            sheet.cell(row=20, column=2).number_format = "0"
            workbook.save(path)
            workbook.close()

            reader = ExcelReader(header_row=1, summary_col="Summary")

            with patch("src.excel_reader.OPENPYXL_PREVIEW_SCAN_ROW_LIMIT", 5):
                with self.assertRaisesRegex(
                    ValueError,
                    "사용 범위가 지나치게 큽니다",
                ):
                    reader.read_preview_rows(
                        str(path),
                        0,
                        max_rows=10,
                    )

    def test_read_excel_normalizes_integer_like_numbers_without_decimal_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Main"
            sheet.append(["Summary", "번호", "실수"])
            sheet.append(["REQ-001", 101, 1.5])
            sheet.append([None, 202, 2.0])
            sheet.append(["REQ-002", None, 3.0])
            workbook.save(path)
            workbook.close()

            reader = ExcelReader(header_row=1, summary_col="Summary")

            raw_df = reader.read_excel(str(path), sheet_name=0)

            self.assertEqual(raw_df["번호"].tolist(), [101, 202, None])
            self.assertEqual(raw_df["실수"].tolist(), [1.5, 2, 3])
            self.assertIsInstance(raw_df.iloc[0]["번호"], int)
            self.assertIsInstance(raw_df.iloc[1]["실수"], int)

    def test_xls_header_preview_and_full_load_use_absolute_worksheet_rows(self) -> None:
        values = [
            ["metadata", None],
            ["Summary", "설명"],
            [None, None],
            ["REQ-001", "첫 번째"],
            ["REQ-002", "두 번째"],
        ]
        apps = []

        def create_app(*, visible: bool = False):
            app = self._fake_xlwings_app(
                values,
                first_row=5,
                first_column=3,
                indent_by_cell={(8, 3): 1, (9, 3): 2},
            )
            app.visible = visible
            apps.append(app)
            return app

        reader = ExcelReader(header_row=6, summary_col="Summary")
        with patch.object(reader, "_create_xlwings_app", side_effect=create_app):
            headers = reader.read_headers("sample.xls", "Main")
            preview_headers, preview_rows = reader.read_preview_rows(
                "sample.xls",
                "Main",
                max_rows=2,
            )
            raw_df = reader.read_excel("sample.xls", "Main")
            upload_count = reader.count_upload_rows("sample.xls", "Main")

        self.assertEqual(headers, ["Summary", "설명"])
        self.assertEqual(preview_headers, headers)
        self.assertEqual(
            preview_rows,
            [["REQ-001", "첫 번째"], ["REQ-002", "두 번째"]],
        )
        self.assertEqual(raw_df["Summary"].tolist(), ["REQ-001", "REQ-002"])
        self.assertEqual(raw_df["_excel_row"].tolist(), [8, 9])
        self.assertEqual(raw_df["_summary_indent"].tolist(), [1, 2])
        self.assertEqual(upload_count, 2)
        self.assertTrue(all(app.quit_called for app in apps))
        self.assertTrue(all(app.books.last_workbook.closed for app in apps))

    @staticmethod
    def _fake_xlwings_app(
        values,
        *,
        first_row: int,
        first_column: int,
        indent_by_cell: dict[tuple[int, int], int],
    ):
        class FakeRange:
            def __init__(self, value, indent: int = 0):
                self.value = value
                self.alignment = SimpleNamespace(indent=indent)
                self.api = SimpleNamespace(IndentLevel=indent)

        class FakeSheet:
            name = "Main"

            def __init__(self):
                width = max((len(row) for row in values), default=0)
                self.used_range = SimpleNamespace(
                    row=first_row,
                    column=first_column,
                    columns=SimpleNamespace(count=width),
                    last_cell=SimpleNamespace(
                        row=first_row + len(values) - 1,
                        column=first_column + width - 1,
                    ),
                )

            def range(self, start, end=None):
                if end is None:
                    row, column = start
                    value = self._value_at(row, column)
                    return FakeRange(value, indent_by_cell.get((row, column), 0))

                start_row, start_column = start
                end_row, end_column = end
                matrix = [
                    [
                        self._value_at(row, column)
                        for column in range(start_column, end_column + 1)
                    ]
                    for row in range(start_row, end_row + 1)
                ]
                if start_row == end_row:
                    return FakeRange(matrix[0])
                if start_column == end_column:
                    return FakeRange([row[0] for row in matrix])
                return FakeRange(matrix)

            @staticmethod
            def _value_at(row, column):
                relative_row = row - first_row
                relative_column = column - first_column
                if not (0 <= relative_row < len(values)):
                    return None
                source_row = values[relative_row]
                if not (0 <= relative_column < len(source_row)):
                    return None
                return source_row[relative_column]

        class FakeSheets(list):
            def __getitem__(self, key):
                if isinstance(key, str):
                    if key != "Main":
                        raise KeyError(key)
                    return super().__getitem__(0)
                return super().__getitem__(key)

        class FakeWorkbook:
            def __init__(self):
                self.sheets = FakeSheets([FakeSheet()])
                self.closed = False

            def close(self):
                self.closed = True

        class FakeBooks:
            def __init__(self):
                self.last_workbook = None

            def open(self, _path):
                self.last_workbook = FakeWorkbook()
                return self.last_workbook

        class FakeApp:
            def __init__(self):
                self.books = FakeBooks()
                self.display_alerts = True
                self.screen_updating = True
                self.quit_called = False

            def quit(self):
                self.quit_called = True

        return FakeApp()


if __name__ == "__main__":
    unittest.main()
