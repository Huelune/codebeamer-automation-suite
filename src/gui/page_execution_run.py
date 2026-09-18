from __future__ import annotations

from PySide6.QtWidgets import QWidget as QtWidget

from .page_common import ACTIVITY_TABLE_MIN_HEIGHT
from .page_common import DETAIL_PANE_MIN_HEIGHT
from .page_common import PRIMARY_TABLE_MIN_HEIGHT
from .page_common import UPLOAD_DETAIL_TABS_MIN_HEIGHT
from .page_common import WIDE_FORM_PANEL_MAX_WIDTH
from .page_common import _configure_constrained_panel
from .page_common import _configure_data_table
from .page_common import _configure_inline_layout
from .page_common import _configure_page_layout
from .page_common import _configure_table_columns
from .page_common import _is_hidden_user_table_column
from .page_common import _require_qt
from .service_core import gui_display_text


def create_validation_page():
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QPushButton = qt["QPushButton"]
    QTableWidget = qt["QTableWidget"]
    QTableWidgetItem = qt["QTableWidgetItem"]

    page = QWidget()
    layout = QVBoxLayout(page)
    _configure_page_layout(layout)
    summary_label = QLabel("")
    summary_label.setObjectName("summary_label")
    _configure_constrained_panel(summary_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(summary_label)

    table = QTableWidget(0, 7)
    table.setHorizontalHeaderLabels(["상태", "행", "항목", "컬럼", "입력값", "문제", "조치"])
    table.setAlternatingRowColors(True)
    _configure_data_table(table, minimum_height=PRIMARY_TABLE_MIN_HEIGHT)
    _configure_table_columns(table, [90, 120, 180, 160, 160, 260, 280])
    page.issue_table = table
    layout.addWidget(table, 1)

    status_label = QLabel("")
    status_label.setObjectName("status_label")
    _configure_constrained_panel(status_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(status_label)

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    previous_button = QPushButton("이전")
    export_button = QPushButton("검증 결과 Excel 내보내기")
    template_button = QPushButton("트래커 업로드 템플릿")
    next_button = QPushButton("다음")
    next_button.setObjectName("primary_button")
    next_button.setEnabled(False)
    buttons.addWidget(previous_button)
    buttons.addWidget(export_button)
    buttons.addWidget(template_button)
    buttons.addStretch(1)
    buttons.addWidget(next_button)
    layout.addLayout(buttons)

    page.has_blocking_issues = True
    page.status_label = status_label
    page.export_validation_button = export_button
    page.export_template_button = template_button
    page.request_export_validation = lambda: None
    page.request_export_template = lambda: None
    export_button.setEnabled(False)

    def set_results(issue_df, has_blocking_issues: bool, summary_stats: dict | None = None) -> None:
        """`set_results` 값을 설정한다."""
        rows: list[list[str]] = []
        if issue_df is not None and not issue_df.empty:
            for _, row in issue_df.iterrows():
                rows.append([
                    gui_display_text(row.get("severity")),
                    gui_display_text(row.get("row_label")),
                    gui_display_text(row.get("item_name")),
                    gui_display_text(row.get("column")),
                    gui_display_text(row.get("raw_value")),
                    gui_display_text(row.get("message")),
                    gui_display_text(row.get("action")),
                ])
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for col_index, value in enumerate(values):
                table.setItem(row_index, col_index, QTableWidgetItem(value))
        _configure_table_columns(table, [90, 120, 180, 160, 160, 260, 280])

        summary_stats = summary_stats or {}
        total_rows = int(summary_stats.get("total_rows", 0))
        ready_rows = int(summary_stats.get("ready_rows", 0))
        error_rows = int(summary_stats.get("error_rows", 0))
        warning_rows = int(summary_stats.get("warning_rows", 0))
        config_errors = int(summary_stats.get("config_errors", 0))
        config_warnings = int(summary_stats.get("config_warnings", 0))
        file_count = int(summary_stats.get("file_count", 1))
        batch_total_rows = int(summary_stats.get("batch_total_rows", total_rows))

        summary_parts = []
        if file_count > 1:
            summary_parts.append(f"선택 파일 {file_count}개")
            summary_parts.append(f"전체 예상 항목 {batch_total_rows}행")
            summary_parts.append(f"전체 검증 {total_rows}행")
        else:
            summary_parts.append(f"전체 {total_rows}행")

        summary_parts.extend([
            f"바로 업로드 가능 {ready_rows}행",
            f"수정 필요 {error_rows}행",
            f"안내 {warning_rows}행",
        ])
        if config_errors:
            summary_parts.append(f"설정 오류 {config_errors}건")
        if config_warnings:
            summary_parts.append(f"설정 안내 {config_warnings}건")
        summary_label.setText(" | ".join(summary_parts))
        page.has_blocking_issues = has_blocking_issues
        export_button.setEnabled(True)
        next_button.setEnabled(not has_blocking_issues)
        if has_blocking_issues:
            status_label.setText("수정이 필요한 항목이 있어 업로드를 시작할 수 없습니다.")
        elif not rows:
            status_label.setText("문제가 있는 항목이 없습니다. 바로 업로드할 수 있습니다.")
        else:
            status_label.setText("오류는 없고 업로드 전에 확인할 안내 항목만 남아 있습니다.")

    def _go_next():
        """`go_next` 단계 이동을 처리한다."""
        if page.has_blocking_issues:
            status_label.setText("차단 이슈를 해결해야 다음 단계로 이동할 수 있습니다.")
            return
        page.request_next()

    previous_button.clicked.connect(lambda: page.request_previous())
    export_button.clicked.connect(lambda: page.request_export_validation())
    template_button.clicked.connect(lambda: page.request_export_template())
    next_button.clicked.connect(_go_next)
    page.set_results = set_results
    return page


def _initialize_upload_page(
    page,
    on_start_requested,
    on_pause_requested,
    on_resume_requested,
    on_cancel_requested,
):
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QTabWidget = qt["QTabWidget"]
    QLabel = qt["QLabel"]
    QPushButton = qt["QPushButton"]
    QPlainTextEdit = qt["QPlainTextEdit"]
    QProgressBar = qt["QProgressBar"]
    QCheckBox = qt["QCheckBox"]
    QTableWidget = qt["QTableWidget"]
    QTableWidgetItem = qt["QTableWidgetItem"]

    layout = QVBoxLayout(page)
    _configure_page_layout(layout)

    page.progress_bar = QProgressBar()
    page.progress_bar.setTextVisible(True)
    page.progress_bar.setFormat("0 / 0 (0.0%)")
    layout.addWidget(page.progress_bar)
    page.progress_label = QLabel("진행률 0.0% (0 / 0)")
    page.progress_label.setObjectName("section_label")
    layout.addWidget(page.progress_label)

    page.phase_label = QLabel("현재 단계: -")
    page.current_label = QLabel("현재 항목: -")
    page.total_label = QLabel("총 대상 0건 / 완료 0건")
    page.phase_total_label = QLabel("단계별 총 대상: 생성 0건 / 수정 0건")
    page.phase_counter_label = QLabel("단계별 결과: 생성 성공 0 / 실패 0 | 수정 성공 0 / 실패 0")
    page.counter_label = QLabel("성공 0 / 실패 0 / 재시도 0")
    page.status_label = QLabel("준비")
    page.status_label.setObjectName("status_label")
    page.time_label = QLabel("배치 시간: -")
    page.time_label.setObjectName("section_label")
    page.eta_label = QLabel("예상 종료: -")
    page.eta_label.setObjectName("section_label")

    summary_row = QHBoxLayout()
    _configure_inline_layout(summary_row, spacing=10)

    left_col = QVBoxLayout()
    _configure_inline_layout(left_col, spacing=2)
    left_col.addWidget(page.phase_label)
    left_col.addWidget(page.current_label)
    summary_row.addLayout(left_col, 2)

    middle_col = QVBoxLayout()
    _configure_inline_layout(middle_col, spacing=2)
    middle_col.addWidget(page.total_label)
    middle_col.addWidget(page.counter_label)
    summary_row.addLayout(middle_col, 2)

    phase_col = QVBoxLayout()
    _configure_inline_layout(phase_col, spacing=2)
    phase_col.addWidget(page.phase_total_label)
    phase_col.addWidget(page.phase_counter_label)
    summary_row.addLayout(phase_col, 3)

    time_col = QVBoxLayout()
    _configure_inline_layout(time_col, spacing=2)
    time_col.addWidget(page.time_label)
    time_col.addWidget(page.eta_label)
    summary_row.addLayout(time_col, 2)

    layout.addLayout(summary_row)
    layout.addWidget(page.status_label)

    page.dry_run_checkbox = QCheckBox("Dry Run")
    page.continue_checkbox = QCheckBox("Continue on error")
    page.continue_checkbox.setChecked(True)
    controls = QHBoxLayout()
    _configure_inline_layout(controls)
    controls.addWidget(page.dry_run_checkbox)
    controls.addWidget(page.continue_checkbox)
    controls.addStretch(1)
    page.start_button = QPushButton("시작")
    page.pause_button = QPushButton("일시정지")
    page.resume_button = QPushButton("재개")
    page.cancel_button = QPushButton("중단")
    page.result_button = QPushButton("결과 보기")
    page.start_button.setObjectName("primary_button")
    page.resume_button.setObjectName("primary_button")
    page.cancel_button.setObjectName("danger_button")
    page.result_button.setObjectName("primary_button")
    page.pause_button.setEnabled(False)
    page.resume_button.setEnabled(False)
    page.cancel_button.setEnabled(False)
    page.result_button.setEnabled(False)
    controls.addWidget(page.start_button)
    controls.addWidget(page.pause_button)
    controls.addWidget(page.resume_button)
    controls.addWidget(page.cancel_button)
    controls.addWidget(page.result_button)
    layout.addLayout(controls)

    page.detail_tabs = QTabWidget()
    page.detail_tabs.setDocumentMode(True)
    page.detail_tabs.setMinimumHeight(UPLOAD_DETAIL_TABS_MIN_HEIGHT)

    activity_tab = QWidget()
    activity_layout = QVBoxLayout(activity_tab)
    _configure_inline_layout(activity_layout)
    page.activity_table = QTableWidget(0, 8)
    page.activity_table.setHorizontalHeaderLabels(["파일", "단계", "항목", "상태", "시작", "완료", "소요", "로그"])
    page.activity_table.setAlternatingRowColors(True)
    page.activity_table.setMinimumHeight(ACTIVITY_TABLE_MIN_HEIGHT)
    _configure_table_columns(page.activity_table, [140, 80, 160, 90, 95, 95, 80, 260])
    activity_layout.addWidget(page.activity_table)
    page.detail_tabs.addTab(activity_tab, "진행 기록")

    log_tab = QWidget()
    log_layout = QVBoxLayout(log_tab)
    _configure_inline_layout(log_layout)
    page.log_view = QPlainTextEdit()
    page.log_view.setReadOnly(True)
    page.log_view.setPlaceholderText("업로드 진행 로그와 시각이 여기에 표시됩니다.")
    log_layout.addWidget(page.log_view)
    page.detail_tabs.addTab(log_tab, "실시간 로그")

    response_tab = QWidget()
    response_layout = QVBoxLayout(response_tab)
    _configure_inline_layout(response_layout)
    page.response_view = QPlainTextEdit()
    page.response_view.setReadOnly(True)
    page.response_view.setPlaceholderText("실패한 요청의 서버 응답 JSON이 여기에 표시됩니다.")
    response_layout.addWidget(page.response_view)
    page.detail_tabs.addTab(response_tab, "실패 응답")

    page.activity_tab = activity_tab
    page.log_tab = log_tab
    page.response_tab = response_tab
    layout.addWidget(page.detail_tabs, 1)

    page._activity_row_map = {}

    page.start_button.clicked.connect(on_start_requested)
    page.pause_button.clicked.connect(on_pause_requested)
    page.resume_button.clicked.connect(on_resume_requested)
    page.cancel_button.clicked.connect(on_cancel_requested)
    page.result_button.clicked.connect(lambda: page.request_next())

    def _set_activity_cell(row_index: int, col_index: int, value: str) -> None:
        """`set_activity_cell` 값을 설정한다."""
        item = page.activity_table.item(row_index, col_index)
        if item is None:
            item = QTableWidgetItem(value)
            page.activity_table.setItem(row_index, col_index, item)
            return
        item.setText(value)

    def _ensure_activity_row(row_key: str, file_label: str, phase_name: str, item_name: str) -> int:
        """`ensure_activity_row` 상태를 보장한다."""
        if row_key in page._activity_row_map:
            row_index = int(page._activity_row_map[row_key])
        else:
            row_index = page.activity_table.rowCount()
            page.activity_table.insertRow(row_index)
            page._activity_row_map[row_key] = row_index
        _set_activity_cell(row_index, 0, file_label)
        _set_activity_cell(row_index, 1, phase_name)
        _set_activity_cell(row_index, 2, item_name)
        return row_index

    def record_activity_started(
        row_key: str,
        file_label: str,
        phase_name: str,
        item_name: str,
        started_at: str,
    ) -> None:
        """`record_activity_started` 기록을 남긴다."""
        row_index = _ensure_activity_row(row_key, file_label, phase_name, item_name)
        _set_activity_cell(row_index, 3, "진행 중")
        _set_activity_cell(row_index, 4, started_at)
        _set_activity_cell(row_index, 5, "")
        _set_activity_cell(row_index, 6, "")
        _set_activity_cell(row_index, 7, "업로드 시작")
        _configure_table_columns(page.activity_table, [140, 80, 160, 90, 95, 95, 80, 260])
        page.activity_table.scrollToBottom()

    def record_activity_finished(
        row_key: str,
        file_label: str,
        phase_name: str,
        item_name: str,
        *,
        status: str,
        finished_at: str,
        duration_text: str,
        message: str,
    ) -> None:
        """`record_activity_finished` 기록을 남긴다."""
        row_index = _ensure_activity_row(row_key, file_label, phase_name, item_name)
        _set_activity_cell(row_index, 3, status)
        if not page.activity_table.item(row_index, 4):
            _set_activity_cell(row_index, 4, finished_at)
        _set_activity_cell(row_index, 5, finished_at)
        _set_activity_cell(row_index, 6, duration_text)
        _set_activity_cell(row_index, 7, message)
        _configure_table_columns(page.activity_table, [140, 80, 160, 90, 95, 95, 80, 260])
        page.activity_table.scrollToBottom()

    def reset(total_count: int) -> None:
        page.progress_bar.setMaximum(max(total_count, 1))
        page.progress_bar.setValue(0)
        page.progress_bar.setFormat("0 / 0 (0.0%)" if total_count <= 0 else f"0 / {total_count} (0.0%)")
        page.progress_label.setText(f"진행률 0.0% (0 / {max(total_count, 0)})")
        page.phase_label.setText("현재 단계: -")
        page.current_label.setText("현재 항목: -")
        page.total_label.setText("총 대상 0건 / 완료 0건")
        page.phase_total_label.setText("단계별 총 대상: 생성 0건 / 수정 0건")
        page.phase_counter_label.setText("단계별 결과: 생성 성공 0 / 실패 0 | 수정 성공 0 / 실패 0")
        page.counter_label.setText("성공 0 / 실패 0 / 재시도 0")
        page.status_label.setText("준비")
        page.time_label.setText("배치 시간: -")
        page.eta_label.setText("예상 종료: -")
        page.activity_table.setRowCount(0)
        page._activity_row_map = {}
        page.log_view.clear()
        page.response_view.clear()
        page.start_button.setEnabled(True)
        page.pause_button.setEnabled(False)
        page.resume_button.setEnabled(False)
        page.cancel_button.setEnabled(False)
        page.result_button.setEnabled(False)

    page.record_activity_started = record_activity_started
    page.record_activity_finished = record_activity_finished
    page.reset = reset
    return page


class UploadPage(QtWidget):
    """배치 업로드 실행 상태와 활동 로그를 소유하는 페이지."""

    def __init__(
        self,
        on_start_requested,
        on_pause_requested,
        on_resume_requested,
        on_cancel_requested,
    ) -> None:
        super().__init__()
        _initialize_upload_page(
            self,
            on_start_requested,
            on_pause_requested,
            on_resume_requested,
            on_cancel_requested,
        )


def create_upload_page(
    on_start_requested,
    on_pause_requested,
    on_resume_requested,
    on_cancel_requested,
):
    """기존 factory 호출 계약으로 `UploadPage`를 생성한다."""
    return UploadPage(
        on_start_requested,
        on_pause_requested,
        on_resume_requested,
        on_cancel_requested,
    )


def create_result_page():
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QPushButton = qt["QPushButton"]
    QPlainTextEdit = qt["QPlainTextEdit"]
    QTableWidget = qt["QTableWidget"]
    QTableWidgetItem = qt["QTableWidgetItem"]
    QTabWidget = qt["QTabWidget"]

    page = QWidget()
    layout = QVBoxLayout(page)
    _configure_page_layout(layout)

    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    page.result_tabs = tabs
    page.tables = {}
    for key, label in (
        ("success_df", "성공"),
        ("failed_df", "실패"),
        ("unresolved_df", "미해결"),
    ):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        _configure_inline_layout(tab_layout)
        table = QTableWidget(0, 0)
        table.setAlternatingRowColors(True)
        _configure_data_table(table, minimum_height=PRIMARY_TABLE_MIN_HEIGHT)
        tab_layout.addWidget(table, 1)
        tabs.addTab(tab, label)
        page.tables[key] = table
    layout.addWidget(tabs, 1)

    page.response_view = QPlainTextEdit()
    page.response_view.setReadOnly(True)
    page.response_view.setMinimumHeight(DETAIL_PANE_MIN_HEIGHT)
    layout.addWidget(page.response_view)

    status_label = QLabel("")
    status_label.setObjectName("status_label")
    _configure_constrained_panel(status_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(status_label)

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    previous_button = QPushButton("이전")
    export_failed_button = QPushButton("실패 보고서 Excel 내보내기")
    retry_failed_button = QPushButton("실패 항목 재시도")
    restart_button = QPushButton("새 업로드 시작")
    restart_button.setObjectName("primary_button")
    buttons.addWidget(previous_button)
    buttons.addWidget(export_failed_button)
    buttons.addWidget(retry_failed_button)
    buttons.addStretch(1)
    buttons.addWidget(restart_button)
    layout.addLayout(buttons)

    page.status_label = status_label
    page.export_failed_button = export_failed_button
    page.retry_failed_button = retry_failed_button
    page.request_export_failed = lambda: None
    page.request_retry_failed = lambda: None
    page.upload_result = {}
    export_failed_button.setEnabled(False)
    retry_failed_button.setEnabled(False)

    def set_results(upload_result: dict) -> None:
        """`set_results` 값을 설정한다."""
        page.upload_result = upload_result
        for key, table in page.tables.items():
            df = upload_result.get(key)
            if df is None or getattr(df, "empty", True):
                table.setRowCount(0)
                table.setColumnCount(0)
                continue

            visible_columns = [
                column_name
                for column_name in df.columns
                if not _is_hidden_user_table_column(column_name)
            ]
            if not visible_columns:
                visible_columns = [str(col) for col in df.columns]

            table.setColumnCount(len(visible_columns))
            table.setHorizontalHeaderLabels([str(col) for col in visible_columns])
            table.setRowCount(len(df))
            for row_index, (_, row) in enumerate(df.iterrows()):
                for col_index, column_name in enumerate(visible_columns):
                    table.setItem(row_index, col_index, QTableWidgetItem(str(row.get(column_name) or "")))
            _configure_table_columns(table, [140] * max(len(visible_columns), 1))

        failed_df = upload_result.get("failed_df")
        if failed_df is not None and not getattr(failed_df, "empty", True) and "error_response_json" in failed_df.columns:
            page.response_view.setPlainText(str(failed_df.iloc[0].get("error_response_json") or ""))
        else:
            page.response_view.clear()

        failed_df = upload_result.get("failed_df")
        unresolved_df = upload_result.get("unresolved_df")
        failed_count = (
            0 if failed_df is None or getattr(failed_df, "empty", True) else len(failed_df)
        )
        unresolved_count = (
            0
            if unresolved_df is None or getattr(unresolved_df, "empty", True)
            else len(unresolved_df)
        )
        export_failed_button.setEnabled(bool(failed_count or unresolved_count))
        retry_context = upload_result.get("retry_context")
        retry_target_count = int(
            getattr(retry_context, "retry_target_count", 0) or 0
        )
        retry_failed_button.setEnabled(retry_target_count > 0)
        non_retryable_count = int(
            getattr(retry_context, "non_retryable_count", 0) or 0
        )
        if retry_target_count:
            status_text = (
                f"현재 세션 캐시로 실패/미해결 {retry_target_count}건을 재시도할 수 있습니다. "
                "생성, 수정, 혼합 처리 모두 지원합니다."
            )
            if non_retryable_count:
                status_text += (
                    f" 준비·매핑·데이터 오류 {non_retryable_count}건은 검증 단계에서 수정해야 합니다."
                )
            status_label.setText(status_text)
        elif failed_count or unresolved_count:
            status_label.setText(
                str(upload_result.get("retry_unavailable_reason") or "")
                or "남은 항목은 자동 재시도할 수 없습니다. 검증 단계로 돌아가 원인을 수정하세요."
            )
        else:
            status_label.setText("모든 업로드 항목이 성공했습니다.")

    previous_button.clicked.connect(lambda: page.request_previous())
    export_failed_button.clicked.connect(lambda: page.request_export_failed())
    retry_failed_button.clicked.connect(lambda: page.request_retry_failed())
    restart_button.clicked.connect(lambda: page.request_restart())
    page.set_results = set_results
    return page
