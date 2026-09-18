from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QFormLayout
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QHeaderView
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QSpinBox
from PySide6.QtWidgets import QTableWidget
from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtWidgets import QTabWidget
from PySide6.QtWidgets import QVBoxLayout
from PySide6.QtWidgets import QWidget

from .developer_data_tools import build_read_only_query_preview
from .developer_data_tools import cache_entry_stats
from .developer_data_tools import clear_context_caches
from .developer_data_tools import diff_schema_frames
from .developer_data_tools import inspect_payload_row
from .developer_excel_tools import DeveloperExcelToolError
from .developer_excel_tools import DeveloperExcelToolService
from .tracker_query_models import TrackerQuery
from .tracker_query_models import TrackerSearchMode


PAYLOAD_TABLE_ROW_LIMIT = 500
_OPERATION_BUTTON_PROPERTY = "developer_tool_operation_button"
_OPERATION_BUSY_PROPERTY = "developer_tool_operation_busy"


def _mark_operation_button(button: QPushButton) -> QPushButton:
    button.setProperty(_OPERATION_BUTTON_PROPERTY, True)
    return button


def _begin_operation(panel: QWidget) -> tuple[QWidget, list[tuple[QPushButton, bool]]] | None:
    scope = panel.window()
    if bool(scope.property(_OPERATION_BUSY_PROPERTY)):
        return None
    scope.setProperty(_OPERATION_BUSY_PROPERTY, True)
    button_states: list[tuple[QPushButton, bool]] = []
    for button in scope.findChildren(QPushButton):
        if bool(button.property(_OPERATION_BUTTON_PROPERTY)):
            button_states.append((button, button.isEnabled()))
            button.setEnabled(False)
    return scope, button_states


def _finish_operation(
    operation: tuple[QWidget, list[tuple[QPushButton, bool]]],
) -> None:
    scope, button_states = operation
    for button, was_enabled in button_states:
        button.setEnabled(was_enabled)
    scope.setProperty(_OPERATION_BUSY_PROPERTY, False)


def _configure_table(table: QTableWidget) -> None:
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    if table.columnCount():
        table.horizontalHeader().setSectionResizeMode(
            table.columnCount() - 1,
            QHeaderView.ResizeMode.Stretch,
        )


def _set_table_rows(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setUpdatesEnabled(False)
    try:
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column_index, value in enumerate(values):
                table.setItem(row_index, column_index, QTableWidgetItem(str(value)))
    finally:
        table.setUpdatesEnabled(True)


def _safe_provider(provider: Callable[[], Any] | None) -> Any:
    if not callable(provider):
        return None
    try:
        return provider()
    except Exception:
        return None


class ExcelToolPanel(QWidget):
    """원본을 건드리지 않는 Excel 검사와 값 전용 변환 화면."""

    def __init__(
        self,
        service: DeveloperExcelToolService | None = None,
        *,
        default_directory: str | Path | None = None,
        operation_runner: Callable[[str, Callable[[], Any]], Any] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service or DeveloperExcelToolService()
        self.default_directory = Path(default_directory or Path.cwd())
        self.operation_runner = operation_runner

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(9)
        title = QLabel("Excel 검사·안전 변환", self)
        title.setObjectName("application_route_title")
        description = QLabel(
            "원본을 덮어쓰지 않습니다. .xlsx는 검사·값 변환을 지원하고, .xlsm은 매크로를 보존하지 않는 값 변환만 제공합니다.",
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        form = QFormLayout()
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit(self)
        self.file_edit.setPlaceholderText("검사할 .xlsx, .xlsm, .xls 또는 .csv 파일")
        self.browse_button = _mark_operation_button(QPushButton("파일 선택", self))
        self.browse_button.clicked.connect(self.choose_input_file)
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(self.browse_button)
        form.addRow("입력 파일", file_row)
        self.sheet_edit = QLineEdit(self)
        self.sheet_edit.setPlaceholderText("비워 두면 첫 번째 시트")
        form.addRow("시트", self.sheet_edit)
        self.header_spin = QSpinBox(self)
        self.header_spin.setRange(1, 10_000)
        self.header_spin.setValue(1)
        form.addRow("헤더 행", self.header_spin)
        csv_row = QHBoxLayout()
        self.encoding_combo = QComboBox(self)
        self.encoding_combo.setEditable(True)
        self.encoding_combo.addItems(["utf-8-sig", "utf-8", "cp949"])
        self.delimiter_edit = QLineEdit(",", self)
        self.delimiter_edit.setMaxLength(1)
        self.delimiter_edit.setMaximumWidth(60)
        csv_row.addWidget(self.encoding_combo)
        csv_row.addWidget(QLabel("구분자", self))
        csv_row.addWidget(self.delimiter_edit)
        csv_row.addStretch(1)
        form.addRow("CSV 설정", csv_row)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.inspect_button = _mark_operation_button(QPushButton("파일 검사", self))
        self.inspect_button.setObjectName("primary_button")
        self.xlsx_button = _mark_operation_button(QPushButton("값 전용 .xlsx 저장", self))
        self.csv_button = _mark_operation_button(QPushButton("값 전용 .csv 저장", self))
        self.inspect_button.clicked.connect(self.inspect_current_file)
        self.xlsx_button.clicked.connect(self.choose_xlsx_output)
        self.csv_button.clicked.connect(self.choose_csv_output)
        actions.addWidget(self.inspect_button)
        actions.addWidget(self.xlsx_button)
        actions.addWidget(self.csv_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.summary_label = QLabel("파일을 선택한 뒤 검사하세요.", self)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.issue_table = QTableWidget(0, 4, self)
        self.issue_table.setHorizontalHeaderLabels(["수준", "종류", "위치", "내용"])
        _configure_table(self.issue_table)
        layout.addWidget(self.issue_table, 1)

    def choose_input_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Excel 또는 CSV 파일 선택",
            str(self.default_directory),
            "지원 파일 (*.xlsx *.xlsm *.xls *.csv)",
        )
        if selected:
            self.file_edit.setText(selected)

    def _input_options(self) -> dict[str, Any]:
        path = self.file_edit.text().strip()
        if not path:
            raise DeveloperExcelToolError("입력 파일을 선택하세요.")
        return {
            "file_path": path,
            "sheet_name": self.sheet_edit.text().strip() or None,
            "header_row": self.header_spin.value(),
            "csv_encoding": self.encoding_combo.currentText().strip() or "utf-8-sig",
            "csv_delimiter": self.delimiter_edit.text() or ",",
        }

    def inspect_current_file(self) -> None:
        try:
            options = self._input_options()
            report = self._run_operation(
                "Excel 파일을 검사하는 중입니다.",
                lambda: self.service.inspect(**options),
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        rows = [
            [issue.severity, issue.code, "!".join(filter(None, (issue.sheet_name, issue.cell))), issue.message]
            for issue in report.issues
        ]
        _set_table_rows(self.issue_table, rows)
        self.summary_label.setText(
            f"{report.selected_sheet or 'CSV'} · 데이터 {report.row_count}행 × {report.column_count}열 · "
            f"수식 {report.formula_count}개 · 확인 항목 {len(report.issues)}건"
        )

    def choose_xlsx_output(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "값 전용 Excel 저장",
            str(self.default_directory / "converted.xlsx"),
            "Excel 통합 문서 (*.xlsx)",
        )
        if selected:
            self.convert_to_xlsx(selected)

    def choose_csv_output(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "값 전용 CSV 저장",
            str(self.default_directory / "converted.csv"),
            "CSV 파일 (*.csv)",
        )
        if selected:
            self.convert_to_csv(selected)

    def convert_to_xlsx(self, output_path: str | Path) -> None:
        try:
            options = self._input_options()
            input_path = options.pop("file_path")
            result = self._run_operation(
                "값 전용 Excel 파일을 만드는 중입니다.",
                lambda: self.service.convert_to_value_xlsx(
                    input_path,
                    output_path,
                    **options,
                ),
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        warning = f" · {' · '.join(result.warnings)}" if result.warnings else ""
        self.summary_label.setText(f"값 전용 Excel을 저장했습니다: {result.output_path}{warning}")

    def convert_to_csv(self, output_path: str | Path) -> None:
        try:
            options = self._input_options()
            input_path = options.pop("file_path")
            result = self._run_operation(
                "값 전용 CSV 파일을 만드는 중입니다.",
                lambda: self.service.convert_to_csv(
                    input_path,
                    output_path,
                    sheet_name=options["sheet_name"],
                    output_encoding=options["csv_encoding"],
                    delimiter=options["csv_delimiter"],
                    input_encoding=options["csv_encoding"],
                    input_delimiter=options["csv_delimiter"],
                ),
            )
        except Exception as exc:
            self._show_error(str(exc))
            return
        warning = f" · {' · '.join(result.warnings)}" if result.warnings else ""
        self.summary_label.setText(f"값 전용 CSV를 저장했습니다: {result.output_path}{warning}")

    def _show_error(self, message: str) -> None:
        self.summary_label.setText(message or "Excel 작업을 완료하지 못했습니다.")

    def _run_operation(self, message: str, callback: Callable[[], Any]) -> Any:
        operation = _begin_operation(self)
        if operation is None:
            raise DeveloperExcelToolError("다른 개발자 도구 작업이 진행 중입니다.")
        try:
            if callable(self.operation_runner):
                return self.operation_runner(message, callback)
            return callback()
        finally:
            _finish_operation(operation)


class PayloadToolPanel(QWidget):
    def __init__(self, payload_provider: Callable[[], pd.DataFrame | None] | None, parent=None) -> None:
        super().__init__(parent)
        self.payload_provider = payload_provider
        self._payload_df = pd.DataFrame()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel("Payload 검사", self)
        title.setObjectName("application_route_title")
        refresh_button = QPushButton("현재 검증 결과 불러오기", self)
        refresh_button.clicked.connect(self.refresh_payloads)
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(refresh_button)
        layout.addLayout(heading)
        description = QLabel(
            "현재 세션에서 검증으로 생성된 payload만 읽습니다. token·password 등 민감 키는 표시 전에 마스킹합니다.",
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(["파일", "행", "상태", "작업", "대상 ID", "오류"])
        _configure_table(self.table)
        self.table.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self.table, 1)
        self.detail_view = QPlainTextEdit(self)
        self.detail_view.setReadOnly(True)
        self.detail_view.setPlaceholderText("행을 선택하면 마스킹된 payload를 표시합니다.")
        layout.addWidget(self.detail_view, 1)
        self.status_label = QLabel("검증 결과를 불러오세요.", self)
        layout.addWidget(self.status_label)

    def refresh_payloads(self) -> None:
        provided = _safe_provider(self.payload_provider)
        total_count = len(provided.index) if isinstance(provided, pd.DataFrame) else 0
        self._payload_df = (
            provided.head(PAYLOAD_TABLE_ROW_LIMIT).copy()
            if isinstance(provided, pd.DataFrame)
            else pd.DataFrame()
        )
        rows: list[list[str]] = []
        if not self._payload_df.empty and "_row_id" in self._payload_df.columns:
            for _, row in self._payload_df.iterrows():
                rows.append(
                    [
                        str(row.get("source_file") or ""),
                        str(row.get("_row_id") or ""),
                        str(row.get("payload_status") or ""),
                        str(row.get("_operation") or ""),
                        str(row.get("_target_item_id") or ""),
                        str(row.get("payload_error") or ""),
                    ]
                )
        _set_table_rows(self.table, rows)
        self.detail_view.clear()
        if rows and total_count > len(rows):
            self.status_label.setText(
                f"현재 세션 payload {total_count}건 중 앞의 {len(rows)}건을 표시합니다."
            )
        elif rows:
            self.status_label.setText(f"현재 세션 payload {len(rows)}건을 불러왔습니다.")
        else:
            self.status_label.setText(
                "검증된 payload가 없습니다. 배치 작업에서 먼저 검증을 실행하세요."
            )
        if rows:
            self.table.selectRow(0)

    def _show_selected(self) -> None:
        row_index = self.table.currentRow()
        if row_index < 0:
            self.detail_view.clear()
            return
        file_item = self.table.item(row_index, 0)
        row_item = self.table.item(row_index, 1)
        if row_item is None:
            return
        source_path = ""
        if 0 <= row_index < len(self._payload_df.index):
            source_path = str(
                self._payload_df.iloc[row_index].get("source_file_path") or ""
            )
        try:
            result = inspect_payload_row(
                self._payload_df,
                row_item.text(),
                source_file_path=source_path,
                source_file="" if file_item is None else file_item.text(),
            )
        except Exception as exc:
            self.detail_view.setPlainText(str(exc))
            return
        detail = result.pretty_json
        if result.error:
            detail = f"오류\n{result.error}\n\npayload\n{detail}"
        self.detail_view.setPlainText(detail)


class SchemaCacheToolPanel(QWidget):
    SUPPORT_HEADERS = ("필드 ID", "필드", "유형", "필수", "여러 값", "지원", "사유")

    def __init__(self, context_provider: Callable[[], Any] | None, parent=None) -> None:
        super().__init__(parent)
        self.context_provider = context_provider
        self._baseline_schema = pd.DataFrame()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)
        self._build_schema_tab()
        self._build_cache_tab()

    def _build_schema_tab(self) -> None:
        tab = QWidget(self.tabs)
        layout = QVBoxLayout(tab)
        heading = QHBoxLayout()
        title = QLabel("트래커 필드 지원 현황", tab)
        title.setObjectName("application_route_title")
        refresh = QPushButton("현재 스키마 표시", tab)
        baseline = QPushButton("비교 기준 저장", tab)
        compare = QPushButton("기준과 비교", tab)
        refresh.clicked.connect(self.refresh_schema)
        baseline.clicked.connect(self.capture_schema_baseline)
        compare.clicked.connect(self.compare_schema)
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(refresh)
        heading.addWidget(baseline)
        heading.addWidget(compare)
        layout.addLayout(heading)
        self.schema_status_label = QLabel("배치 작업에서 트래커 스키마를 불러온 뒤 확인할 수 있습니다.", tab)
        layout.addWidget(self.schema_status_label)
        self.schema_table = QTableWidget(0, len(self.SUPPORT_HEADERS), tab)
        self.schema_table.setHorizontalHeaderLabels(self.SUPPORT_HEADERS)
        _configure_table(self.schema_table)
        layout.addWidget(self.schema_table, 1)
        self.tabs.addTab(tab, "스키마·지원 현황")

    def _build_cache_tab(self) -> None:
        tab = QWidget(self.tabs)
        layout = QVBoxLayout(tab)
        heading = QHBoxLayout()
        title = QLabel("세션 조회 캐시", tab)
        title.setObjectName("application_route_title")
        refresh = QPushButton("현황 새로고침", tab)
        clear = QPushButton("선택 캐시 지우기", tab)
        clear.setObjectName("danger_button")
        refresh.clicked.connect(self.refresh_caches)
        clear.clicked.connect(self.clear_selected_caches)
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(refresh)
        heading.addWidget(clear)
        layout.addLayout(heading)
        note = QLabel("개수만 표시하며 캐시 키와 실제 업무 값은 노출하지 않습니다.", tab)
        layout.addWidget(note)
        self.cache_table = QTableWidget(0, 3, tab)
        self.cache_table.setHorizontalHeaderLabels(["선택", "캐시", "항목 수"])
        _configure_table(self.cache_table)
        layout.addWidget(self.cache_table, 1)
        self.cache_status_label = QLabel("현재 매핑 세션이 없습니다.", tab)
        layout.addWidget(self.cache_status_label)
        self.tabs.addTab(tab, "캐시")

    def _context(self) -> Any:
        return _safe_provider(self.context_provider)

    def _schema_df(self) -> pd.DataFrame:
        context = self._context()
        frame = getattr(context, "schema_df", None)
        return frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()

    def refresh_schema(self) -> None:
        frame = self._schema_df()
        rows: list[list[str]] = []
        for _, row in frame.iterrows():
            supported = row.get("is_supported", True)
            rows.append(
                [
                    str(row.get("field_id") or ""),
                    str(row.get("field_name") or ""),
                    str(row.get("field_type") or ""),
                    "예" if bool(row.get("mandatory", False)) else "아니요",
                    "예" if bool(row.get("multiple_values", False)) else "아니요",
                    "지원" if bool(supported) else "미지원",
                    str(row.get("unsupported_reason") or ""),
                ]
            )
        _set_table_rows(self.schema_table, rows)
        unsupported_count = sum(1 for values in rows if values[5] == "미지원")
        self.schema_status_label.setText(
            f"현재 필드 {len(rows)}개 · 지원 {len(rows) - unsupported_count}개 · 미지원 {unsupported_count}개"
            if rows
            else "현재 세션에 불러온 스키마가 없습니다."
        )

    def capture_schema_baseline(self) -> None:
        frame = self._schema_df()
        if frame.empty:
            self.schema_status_label.setText("저장할 현재 스키마가 없습니다.")
            return
        self._baseline_schema = frame.copy(deep=True)
        self.schema_status_label.setText(f"현재 필드 {len(frame.index)}개를 비교 기준으로 저장했습니다.")

    def compare_schema(self) -> None:
        if self._baseline_schema.empty:
            self.schema_status_label.setText("먼저 비교 기준을 저장하세요.")
            return
        differences = diff_schema_frames(self._baseline_schema, self._schema_df())
        rows = [
            [
                difference.identity.removeprefix("id:"),
                difference.field_name,
                difference.change,
                "",
                "",
                "",
                ", ".join(difference.changed_properties),
            ]
            for difference in differences
        ]
        _set_table_rows(self.schema_table, rows)
        self.schema_status_label.setText(f"비교 결과 {len(differences)}건의 차이가 있습니다.")

    def refresh_caches(self) -> None:
        stats = cache_entry_stats(self._context())
        self.cache_table.setRowCount(len(stats))
        for row_index, stat in enumerate(stats):
            checkbox = QCheckBox(self.cache_table)
            checkbox.setProperty("cache_key", stat.key)
            self.cache_table.setCellWidget(row_index, 0, checkbox)
            self.cache_table.setItem(row_index, 1, QTableWidgetItem(stat.label))
            self.cache_table.setItem(row_index, 2, QTableWidgetItem(str(stat.entry_count)))
        self.cache_status_label.setText(f"세션 캐시 {sum(stat.entry_count for stat in stats)}건")

    def selected_cache_keys(self) -> list[str]:
        keys: list[str] = []
        for row_index in range(self.cache_table.rowCount()):
            checkbox = self.cache_table.cellWidget(row_index, 0)
            if isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                keys.append(str(checkbox.property("cache_key") or ""))
        return [key for key in keys if key]

    def clear_selected_caches(self) -> None:
        keys = self.selected_cache_keys()
        if not keys:
            self.cache_status_label.setText("지울 캐시를 선택하세요.")
            return
        response = QMessageBox.question(
            self,
            "세션 캐시 지우기",
            "선택한 조회 캐시를 지우면 다음 검증에서 서버 조회가 다시 발생할 수 있습니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        removed = clear_context_caches(self._context(), keys)
        self.refresh_caches()
        self.cache_status_label.setText(f"선택한 캐시에서 {removed}건을 지웠습니다.")


class ReadOnlyQueryToolPanel(QWidget):
    def __init__(
        self,
        query_executor: Callable[[TrackerQuery], Any] | None = None,
        *,
        tracker_id_provider: Callable[[], int | None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.query_executor = query_executor
        self.tracker_id_provider = tracker_id_provider
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        title = QLabel("읽기 전용 Tracker Query", self)
        title.setObjectName("application_route_title")
        description = QLabel(
            "고정된 /v3/items/query 조회만 실행합니다. 생성·수정·삭제 API와 임의 URL은 사용할 수 없습니다.",
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)
        form = QFormLayout()
        self.tracker_spin = QSpinBox(self)
        self.tracker_spin.setRange(1, 2_147_483_647)
        self.baseline_edit = QLineEdit(self)
        self.baseline_edit.setPlaceholderText("현재 상태는 비워 둠")
        self.page_size_spin = QSpinBox(self)
        self.page_size_spin.setRange(1, 500)
        self.page_size_spin.setValue(100)
        form.addRow("트래커 ID", self.tracker_spin)
        form.addRow("Baseline ID", self.baseline_edit)
        form.addRow("페이지 크기", self.page_size_spin)
        layout.addLayout(form)
        self.cbql_edit = QPlainTextEdit(self)
        self.cbql_edit.setPlaceholderText("예: status = 'Open' ORDER BY item.id ASC\n트래커 범위는 자동으로 추가됩니다.")
        layout.addWidget(self.cbql_edit, 1)
        actions = QHBoxLayout()
        self.use_current_button = _mark_operation_button(QPushButton("현재 트래커 ID 사용", self))
        self.preview_button = _mark_operation_button(QPushButton("요청 미리보기", self))
        self.execute_button = _mark_operation_button(QPushButton("조회 실행", self))
        self.execute_button.setObjectName("primary_button")
        self.use_current_button.clicked.connect(self.use_current_tracker)
        self.preview_button.clicked.connect(self.preview_query)
        self.execute_button.clicked.connect(self.execute_query)
        actions.addWidget(self.use_current_button)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.execute_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.output_view = QPlainTextEdit(self)
        self.output_view.setReadOnly(True)
        layout.addWidget(self.output_view, 1)
        self.status_label = QLabel("요청을 미리 본 뒤 실행하세요.", self)
        layout.addWidget(self.status_label)

    def use_current_tracker(self) -> None:
        value = _safe_provider(self.tracker_id_provider)
        try:
            tracker_id = int(value)
        except (TypeError, ValueError):
            self.status_label.setText("현재 선택한 트래커를 확인할 수 없습니다.")
            return
        if tracker_id <= 0:
            self.status_label.setText("현재 선택한 트래커를 확인할 수 없습니다.")
            return
        self.tracker_spin.setValue(tracker_id)

    def build_query(self) -> TrackerQuery:
        baseline_text = self.baseline_edit.text().strip()
        return TrackerQuery(
            tracker_id=self.tracker_spin.value(),
            mode=TrackerSearchMode.CBQL,
            cbql=self.cbql_edit.toPlainText().strip(),
            page=1,
            page_size=self.page_size_spin.value(),
            baseline_id=int(baseline_text) if baseline_text else None,
        )

    def preview_query(self) -> None:
        try:
            preview = build_read_only_query_preview(self.build_query())
        except Exception as exc:
            self.status_label.setText(str(exc))
            return
        self.output_view.setPlainText(json.dumps(preview, ensure_ascii=False, indent=2))
        self.status_label.setText("읽기 전용 요청 미리보기를 만들었습니다.")

    def execute_query(self) -> None:
        if not callable(self.query_executor):
            self.status_label.setText("현재 화면에서 query 실행기를 사용할 수 없습니다.")
            return
        try:
            query = self.build_query()
        except Exception as exc:
            self.status_label.setText(str(exc) or "query를 실행하지 못했습니다.")
            return
        operation = _begin_operation(self)
        if operation is None:
            self.status_label.setText("다른 개발자 도구 작업이 진행 중입니다.")
            return
        try:
            result = self.query_executor(query)
        except Exception as exc:
            self.status_label.setText(str(exc) or "query를 실행하지 못했습니다.")
            return
        finally:
            _finish_operation(operation)
        items = getattr(result, "items", result if isinstance(result, (list, tuple)) else ())
        rendered = []
        for item in items or ():
            rendered.append(
                {
                    "id": getattr(item, "item_id", None),
                    "name": getattr(item, "name", ""),
                    "status": getattr(item, "status", ""),
                }
            )
        self.output_view.setPlainText(json.dumps(rendered, ensure_ascii=False, indent=2, default=str))
        self.status_label.setText(f"읽기 전용 query 결과 {len(rendered)}건을 불러왔습니다.")


__all__ = [
    "ExcelToolPanel",
    "PayloadToolPanel",
    "ReadOnlyQueryToolPanel",
    "SchemaCacheToolPanel",
]
