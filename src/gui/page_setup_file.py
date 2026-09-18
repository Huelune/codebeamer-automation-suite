from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QWidget as QtWidget

from .page_common import PREVIEW_TABLE_MIN_HEIGHT
from .page_common import PRIMARY_TABLE_MIN_HEIGHT
from .page_common import WIDE_FORM_PANEL_MAX_WIDTH
from .page_common import _configure_constrained_panel
from .page_common import _configure_data_table
from .page_common import _configure_form_field
from .page_common import _configure_form_layout
from .page_common import _configure_inline_layout
from .page_common import _configure_page_layout
from .page_common import _configure_table_columns
from .page_common import _require_qt
from .root_item_service import ROOT_ASSIGNMENT_MODE_FILE_SOURCE
from .root_item_service import ROOT_ASSIGNMENT_MODE_FIXED_VALUE
from .root_item_service import ROOT_ITEM_MODE_FILE
from .root_item_service import ROOT_ITEM_MODE_GROUP_BY_COLUMN


def _initialize_file_selection_page(
    page,
    initial_settings,
    on_file_state_changed,
    on_file_preview_requested,
    on_error=None,
    *,
    on_file_metadata_requested=None,
    on_sheet_preview_requested=None,
    on_full_data_requested=None,
):
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QFormLayout = qt["QFormLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QPushButton = qt["QPushButton"]
    QSpinBox = qt["QSpinBox"]
    QComboBox = qt["QComboBox"]
    QTableWidget = qt["QTableWidget"]
    QTableWidgetItem = qt["QTableWidgetItem"]
    QFileDialog = qt["QFileDialog"]

    page.setObjectName("file_selection_page")
    layout = QVBoxLayout(page)
    _configure_page_layout(layout)

    form = QFormLayout()
    _configure_form_layout(form)
    file_path = QLineEdit(initial_settings.last_file_path)
    file_path.setReadOnly(True)
    file_button = QPushButton("파일 선택")
    file_row_widget = QWidget()
    file_row = QHBoxLayout(file_row_widget)
    _configure_inline_layout(file_row)
    file_row.addWidget(file_path)
    file_row.addWidget(file_button)
    preview_file = QComboBox()
    preview_file.setEditable(False)
    preview_file.setEnabled(False)
    sheet_name = QComboBox()
    sheet_name.setEditable(False)
    header_row = QSpinBox()
    header_row.setMinimum(1)
    header_row.setValue(initial_settings.excel_header_row)
    summary_column = QComboBox()
    summary_column.setEditable(False)
    summary_column.addItem("시트 미리보기 후 선택", "")
    summary_column.setEnabled(False)
    _configure_form_field(file_path)
    _configure_form_field(file_row_widget, minimum_width=320)
    _configure_form_field(preview_file)
    _configure_form_field(sheet_name)
    _configure_form_field(header_row)
    _configure_form_field(summary_column)
    form.addRow("Excel 파일", file_row_widget)
    form.addRow("미리보기 파일", preview_file)
    form.addRow("시트", sheet_name)
    form.addRow("헤더 행", header_row)
    form.addRow("Summary 컬럼", summary_column)
    form_container = QWidget()
    form_container.setLayout(form)
    _configure_constrained_panel(form_container, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(form_container)

    preview_label = QLabel("미리보기")
    preview_label.setObjectName("section_label")
    layout.addWidget(preview_label)
    preview_table = QTableWidget(5, 4)
    preview_table.setAlternatingRowColors(True)
    preview_table.setHorizontalHeaderLabels(["컬럼 A", "컬럼 B", "컬럼 C", "컬럼 D"])
    preview_table.setItem(0, 0, QTableWidgetItem("Summary"))
    preview_table.setItem(0, 1, QTableWidgetItem("담당자"))
    preview_table.setItem(1, 0, QTableWidgetItem("REQ-001"))
    preview_table.setItem(1, 1, QTableWidgetItem("홍길동"))
    _configure_data_table(preview_table, minimum_height=PREVIEW_TABLE_MIN_HEIGHT)
    _configure_table_columns(preview_table, [180, 180, 160, 160])
    page.preview_table = preview_table
    layout.addWidget(preview_table, 1)

    status_label = QLabel("Excel 파일을 선택하면 먼저 시트 정보만 불러옵니다.")
    status_label.setObjectName("status_label")
    _configure_constrained_panel(status_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(status_label)

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    previous_button = QPushButton("이전")
    preview_button = QPushButton("선택 시트 미리보기")
    load_button = QPushButton("전체 데이터 불러오기")
    next_button = QPushButton("다음")
    load_button.setObjectName("primary_button")
    next_button.setObjectName("primary_button")
    next_button.setEnabled(False)
    buttons.addWidget(previous_button)
    buttons.addWidget(preview_button)
    buttons.addWidget(load_button)
    buttons.addStretch(1)
    buttons.addWidget(next_button)
    layout.addLayout(buttons)

    page._metadata_ready = False
    page._sheet_preview_ready = False
    page._preview_ready = False
    page._selected_file_paths = [initial_settings.last_file_path] if initial_settings.last_file_path else []
    page._metadata_data = None
    page._sheet_preview_data = None
    page._preview_data = None
    page._preferred_summary_column = str(
        initial_settings.summary_column or "Summary"
    ).strip() or "Summary"
    page.preview_button = preview_button
    page.load_button = load_button
    page.summary_column_combo = summary_column

    def _update_next_button_state() -> None:
        next_button.setEnabled(bool(page._selected_file_paths) and page._preview_ready)

    def _selected_preview_file_path() -> str:
        preview_path = str(preview_file.currentData() or "").strip()
        if preview_path:
            return preview_path
        if page._selected_file_paths:
            return str(page._selected_file_paths[0]).strip()
        return ""

    def _update_file_display() -> None:
        selected_count = len(page._selected_file_paths)
        if selected_count <= 0:
            file_path.setText("")
            return
        if selected_count == 1:
            file_path.setText(page._selected_file_paths[0])
            return
        first_name = Path(page._selected_file_paths[0]).name
        file_path.setText(f"{selected_count}개 파일 선택됨 ({first_name} 외)")

    def _set_preview_file_items(selected_file_paths: list[str], selected_path: str | None = None) -> None:
        """`set_preview_file_items` 값을 설정한다."""
        preview_file.blockSignals(True)
        preview_file.clear()
        for current_path in selected_file_paths:
            preview_file.addItem(Path(current_path).name, current_path)
        preview_file.setEnabled(bool(selected_file_paths))
        if selected_file_paths:
            target_path = selected_path if selected_path in selected_file_paths else selected_file_paths[0]
            target_index = preview_file.findData(target_path)
            preview_file.setCurrentIndex(target_index if target_index >= 0 else 0)
        preview_file.blockSignals(False)

    def _collect_state():
        """`collect_state` 정보를 수집한다."""
        state = {
            "file_path": _selected_preview_file_path(),
            "file_paths": list(page._selected_file_paths),
            "preview_file_path": _selected_preview_file_path(),
            "sheet_name": sheet_name.currentText().strip() or "0",
            "header_row": header_row.value(),
            "summary_column": (
                str(summary_column.currentData() or "").strip()
                or page._preferred_summary_column
                or "Summary"
            ),
        }
        if page._metadata_data is not None:
            state["metadata_data"] = page._metadata_data
        if page._sheet_preview_data is not None:
            state["sheet_preview_data"] = page._sheet_preview_data
        if page._preview_ready and page._preview_data is not None:
            state["preview_data"] = page._preview_data
        return state

    def _set_preview(headers: list[str], rows: list[list[str]], resolved_summary: str) -> None:
        """`set_preview` 값을 설정한다."""
        preview_table.clear()
        preview_table.setColumnCount(len(headers))
        preview_table.setRowCount(len(rows))
        preview_table.setHorizontalHeaderLabels(headers)
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                preview_table.setItem(row_index, col_index, QTableWidgetItem(value))
        _configure_table_columns(preview_table, [180] * max(len(headers), 1))
        summary_column.blockSignals(True)
        try:
            summary_column.clear()
            for header in headers:
                summary_column.addItem(header, header)
            if not headers:
                summary_column.addItem("선택할 수 있는 헤더가 없습니다", "")
            target_summary = (
                resolved_summary
                if resolved_summary in headers
                else (headers[0] if headers else "")
            )
            if target_summary:
                summary_column.setCurrentIndex(summary_column.findData(target_summary))
                page._preferred_summary_column = target_summary
            summary_column.setEnabled(bool(headers))
        finally:
            summary_column.blockSignals(False)

    def _clear_preview() -> None:
        """`clear_preview` 상태를 비운다."""
        preview_table.clear()
        preview_table.setColumnCount(0)
        preview_table.setRowCount(0)
        summary_column.blockSignals(True)
        try:
            summary_column.clear()
            summary_column.addItem("시트 미리보기 후 선택", "")
            summary_column.setEnabled(False)
        finally:
            summary_column.blockSignals(False)

    def _mark_full_data_dirty(*, message: str | None = None) -> None:
        """전체 데이터만 무효화하고 제한 행 미리보기는 유지한다."""
        page._preview_ready = False
        page._preview_data = None
        _update_next_button_state()
        if message:
            status_label.setText(message)
        elif page._sheet_preview_ready:
            status_label.setText(
                "설정을 바꿨습니다. '전체 데이터 불러오기'를 눌러 다시 적용하세요."
            )

    def _mark_preview_dirty(*, clear_sheet_names: bool = False, message: str | None = None) -> None:
        """시트 미리보기와 전체 데이터를 함께 무효화한다."""
        page._sheet_preview_ready = False
        page._sheet_preview_data = None
        _mark_full_data_dirty()
        _clear_preview()
        if clear_sheet_names:
            page._metadata_ready = False
            page._metadata_data = None
            sheet_name.blockSignals(True)
            sheet_name.clear()
            sheet_name.blockSignals(False)
        if message:
            status_label.setText(message)
            return
        if page._selected_file_paths:
            status_label.setText(
                "시트 또는 헤더 설정을 바꿨습니다. '선택 시트 미리보기'를 다시 실행하세요."
            )
            return
        status_label.setText("Excel 파일을 선택하세요.")

    def _set_sheet_names(names: list[str], selected_name: str) -> None:
        """`set_sheet_names` 값을 설정한다."""
        sheet_name.blockSignals(True)
        sheet_name.clear()
        for name in names:
            sheet_name.addItem(name)
        if names:
            index = sheet_name.findText(selected_name)
            sheet_name.setCurrentIndex(index if index >= 0 else 0)
        sheet_name.blockSignals(False)

    def _load_metadata() -> None:
        """대표 파일의 시트 목록만 읽는다."""
        state = _collect_state()
        if not state["file_paths"]:
            status_label.setText("Excel 파일을 먼저 선택해야 합니다.")
            return
        _mark_preview_dirty(clear_sheet_names=True)
        if not callable(on_file_metadata_requested):
            status_label.setText(
                "파일을 선택했습니다. '전체 데이터 불러오기'를 눌러 확인하세요."
            )
            return
        try:
            metadata = on_file_metadata_requested(state["preview_file_path"])
        except Exception as exc:
            message = f"시트 정보 불러오기 실패: {exc}"
            status_label.setText(message)
            if callable(on_error):
                on_error("시트 정보 불러오기 실패", message)
            return
        page._metadata_data = metadata
        page._metadata_ready = True
        _set_sheet_names(list(metadata.sheet_names), state["sheet_name"])
        status_label.setText(
            f"{Path(state['preview_file_path']).name}에서 시트 {len(metadata.sheet_names)}개를 찾았습니다. "
            "시트를 정한 뒤 미리보기를 실행하세요."
        )
        on_file_state_changed(_collect_state())

    def _refresh_sheet_preview() -> None:
        """선택 시트의 헤더와 제한된 행만 읽는다."""
        state = _collect_state()
        if not state["file_paths"]:
            status_label.setText("Excel 파일을 먼저 선택해야 합니다.")
            return
        if callable(on_file_metadata_requested) and not page._metadata_ready:
            status_label.setText("시트 정보를 먼저 불러와야 합니다.")
            return
        _mark_preview_dirty()
        try:
            if callable(on_sheet_preview_requested):
                preview = on_sheet_preview_requested(
                    state["preview_file_path"],
                    sheet_name=state["sheet_name"],
                    header_row=state["header_row"],
                    summary_column=state["summary_column"],
                )
            else:
                preview = on_file_preview_requested(
                    state["preview_file_path"],
                    file_paths=state["file_paths"],
                    sheet_name=state["sheet_name"],
                    header_row=state["header_row"],
                    summary_column=state["summary_column"],
                )
        except Exception as exc:
            message = f"선택 시트 미리보기 실패: {exc}"
            status_label.setText(message)
            if callable(on_error):
                on_error("선택 시트 미리보기 실패", message)
            return
        _set_preview(
            preview.headers,
            preview.rows,
            getattr(preview, "summary_column", preview.suggested_summary),
        )
        page._sheet_preview_data = preview
        page._sheet_preview_ready = True
        status_label.setText(
            "헤더와 일부 행을 확인했습니다. Summary 컬럼을 정한 뒤 전체 데이터를 불러오세요."
        )
        on_file_state_changed(_collect_state())

    def _load_full_data() -> None:
        """명시적 호출에서만 선택한 모든 파일의 전체 데이터를 읽는다."""
        state = _collect_state()
        if not state["file_paths"]:
            status_label.setText("Excel 파일을 먼저 선택해야 합니다.")
            return
        if callable(on_sheet_preview_requested) and not page._sheet_preview_ready:
            status_label.setText("선택 시트 미리보기를 먼저 실행해야 합니다.")
            return
        page._preview_ready = False
        page._preview_data = None
        _update_next_button_state()
        try:
            if callable(on_full_data_requested):
                preview = on_full_data_requested(
                    state["preview_file_path"],
                    file_paths=state["file_paths"],
                    sheet_name=state["sheet_name"],
                    header_row=state["header_row"],
                    summary_column=state["summary_column"],
                    sheet_preview=page._sheet_preview_data,
                )
            else:
                preview = on_file_preview_requested(
                    state["preview_file_path"],
                    file_paths=state["file_paths"],
                    sheet_name=state["sheet_name"],
                    header_row=state["header_row"],
                    summary_column=state["summary_column"],
                )
        except Exception as exc:
            message = f"전체 데이터 불러오기 실패: {exc}"
            status_label.setText(message)
            if callable(on_error):
                on_error("전체 데이터 불러오기 실패", message)
            return
        if page._metadata_data is not None:
            preview.sheet_names = list(page._metadata_data.sheet_names)
        _set_preview(preview.headers, preview.rows, preview.summary_column)
        page._preview_data = preview
        page._preview_ready = True
        _update_next_button_state()
        cache_note = " · 기존 로드 데이터 재사용" if bool(getattr(preview, "cache_hit", False)) else ""
        status_label.setText(
            f"{len(page._selected_file_paths)}개 파일의 전체 데이터를 불러왔습니다{cache_note}."
        )
        on_file_state_changed(_collect_state())

    def _choose_files():
        """`choose_files` 선택 동작을 처리한다."""
        dialog_path = page._selected_file_paths[0] if page._selected_file_paths else initial_settings.last_file_path
        selected, _ = QFileDialog.getOpenFileNames(
            page,
            "Excel 파일 선택",
            dialog_path,
            "Excel Files (*.xlsx *.xlsm *.xls)",
        )
        if selected:
            page._selected_file_paths = [str(path) for path in selected]
            _set_preview_file_items(page._selected_file_paths)
            _update_file_display()
            _load_metadata()

    def _go_previous():
        """`go_previous` 단계 이동을 처리한다."""
        page.request_previous()

    def _on_summary_column_changed(_index: int) -> None:
        selected_summary = str(summary_column.currentData() or "").strip()
        if selected_summary:
            page._preferred_summary_column = selected_summary
        _mark_full_data_dirty()

    def _go_next():
        """`go_next` 단계 이동을 처리한다."""
        state = _collect_state()
        if not state["file_paths"]:
            status_label.setText("Excel 파일을 하나 이상 선택해야 합니다.")
            return
        if not page._preview_ready:
            status_label.setText("파일 설정을 마친 뒤 '전체 데이터 불러오기'를 실행해야 합니다.")
            return
        on_file_state_changed(state)
        page.request_next()

    file_button.clicked.connect(_choose_files)
    preview_button.clicked.connect(_refresh_sheet_preview)
    load_button.clicked.connect(_load_full_data)
    preview_file.currentIndexChanged.connect(lambda _: _load_metadata())
    sheet_name.currentTextChanged.connect(lambda _: _mark_preview_dirty())
    header_row.valueChanged.connect(lambda _: _mark_preview_dirty())
    summary_column.currentIndexChanged.connect(_on_summary_column_changed)
    previous_button.clicked.connect(_go_previous)
    next_button.clicked.connect(_go_next)

    _set_preview_file_items(page._selected_file_paths, initial_settings.last_file_path)
    _update_file_display()

    def _load_state(state: dict[str, object]) -> None:
        loaded_state = dict(state or {})
        loaded_file_paths = [
            str(path).strip()
            for path in loaded_state.get("file_paths") or []
            if str(path).strip()
        ]
        if loaded_file_paths:
            page._selected_file_paths = loaded_file_paths
            _set_preview_file_items(
                page._selected_file_paths,
                str(loaded_state.get("preview_file_path") or ""),
            )
            _update_file_display()

        sheet_name.blockSignals(True)
        header_row.blockSignals(True)
        try:
            loaded_sheet_name = str(loaded_state.get("sheet_name") or "").strip()
            loaded_header_row = int(loaded_state.get("header_row") or initial_settings.excel_header_row or 1)
            loaded_summary = str(
                loaded_state.get("summary_column") or initial_settings.summary_column or "Summary"
            ).strip() or "Summary"

            if loaded_sheet_name and sheet_name.findText(loaded_sheet_name) < 0:
                sheet_name.addItem(loaded_sheet_name)
            if loaded_sheet_name:
                sheet_name.setCurrentText(loaded_sheet_name)
            header_row.setValue(max(1, loaded_header_row))
            page._preferred_summary_column = loaded_summary
        finally:
            sheet_name.blockSignals(False)
            header_row.blockSignals(False)

        _mark_preview_dirty(
            message=(
                "저장된 파일 설정을 불러왔습니다. 시트 미리보기와 전체 데이터 로드를 "
                "순서대로 실행하세요."
            ),
        )
        if page._selected_file_paths:
            _load_metadata()
        on_file_state_changed(_collect_state())

    page.get_state = _collect_state
    page.load_state = _load_state
    page.load_metadata = _load_metadata
    page.refresh_sheet_preview = _refresh_sheet_preview
    page.refresh_preview = _load_full_data

    return page


class FileSelectionPage(QtWidget):
    """선택 파일과 명시적 데이터 로딩 상태를 소유하는 페이지."""

    def __init__(
        self,
        initial_settings,
        on_file_state_changed,
        on_file_preview_requested,
        on_error=None,
        *,
        on_file_metadata_requested=None,
        on_sheet_preview_requested=None,
        on_full_data_requested=None,
    ) -> None:
        super().__init__()
        _initialize_file_selection_page(
            self,
            initial_settings,
            on_file_state_changed,
            on_file_preview_requested,
            on_error,
            on_file_metadata_requested=on_file_metadata_requested,
            on_sheet_preview_requested=on_sheet_preview_requested,
            on_full_data_requested=on_full_data_requested,
        )


def create_file_selection_page(
    initial_settings,
    on_file_state_changed,
    on_file_preview_requested,
    on_error=None,
    *,
    on_file_metadata_requested=None,
    on_sheet_preview_requested=None,
    on_full_data_requested=None,
):
    """기존 factory 호출 계약으로 `FileSelectionPage`를 생성한다."""
    return FileSelectionPage(
        initial_settings,
        on_file_state_changed,
        on_file_preview_requested,
        on_error,
        on_file_metadata_requested=on_file_metadata_requested,
        on_sheet_preview_requested=on_sheet_preview_requested,
        on_full_data_requested=on_full_data_requested,
    )


def _initialize_root_item_page(
    page,
    on_preview_requested,
    *,
    page_mode: str = "structure",
):
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QFormLayout = qt["QFormLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QComboBox = qt["QComboBox"]
    QCheckBox = qt["QCheckBox"]
    QPushButton = qt["QPushButton"]
    QTableWidget = qt["QTableWidget"]
    QTableWidgetItem = qt["QTableWidgetItem"]

    is_structure_page = str(page_mode or "structure").strip() != "fields"
    is_field_page = not is_structure_page

    layout = QVBoxLayout(page)
    _configure_page_layout(layout)

    description_label = QLabel(

            "업로드 전에 생성할 상단 폴더 구조를 설정합니다. "
            "파일별 루트 폴더와 파일 내부 특정 컬럼 값별 그룹 폴더를 각각 독립적으로 사용할 수 있습니다."
            if is_structure_page
            else "앞 단계에서 정한 상단 폴더 구조에 어떤 필드 값을 넣을지 설정합니다."

    )
    description_label.setWordWrap(True)
    description_label.setObjectName("section_label")
    _configure_constrained_panel(description_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(description_label)

    enable_root_item = QCheckBox("파일별 최상단 폴더 생성")
    enable_root_item.setChecked(True)
    layout.addWidget(enable_root_item)

    enable_group_folder = QCheckBox("엑셀 컬럼별 그룹 폴더 생성")
    enable_group_folder.setChecked(False)
    layout.addWidget(enable_group_folder)

    structure_summary_label = QLabel("")
    structure_summary_label.setWordWrap(True)
    structure_summary_label.setObjectName("status_label")
    _configure_constrained_panel(structure_summary_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(structure_summary_label)

    form = QFormLayout()
    _configure_form_layout(form)
    group_by_column = QComboBox()
    group_by_column.addItem("사용 안 함", "")
    regex_target = QComboBox()
    regex_target.addItem("파일명(확장자 제외)", "file_stem")
    regex_target.addItem("전체 파일명", "file_name")
    regex_pattern = QLineEdit()
    regex_pattern.setPlaceholderText(r"예: ^(?P<project>[A-Z]+)_(?P<title>.+)$")
    _configure_form_field(group_by_column)
    _configure_form_field(regex_target)
    _configure_form_field(regex_pattern, minimum_width=320)
    form.addRow("그룹 컬럼", group_by_column)
    form.addRow("정규식 대상", regex_target)
    form.addRow("정규식", regex_pattern)
    form_container = QWidget()
    form_container.setLayout(form)
    _configure_constrained_panel(form_container, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(form_container)

    preview_label = QLabel("상단 데이터 소스 미리보기" if is_structure_page else "상단 폴더 미리보기")
    preview_label.setObjectName("section_label")
    layout.addWidget(preview_label)

    preview_table = QTableWidget(0, 0)
    preview_table.setAlternatingRowColors(True)
    _configure_data_table(preview_table, minimum_height=PREVIEW_TABLE_MIN_HEIGHT)
    page.preview_table = preview_table
    layout.addWidget(preview_table, 1)

    field_label = QLabel("상단 폴더 필드 매핑")
    field_label.setObjectName("section_label")
    layout.addWidget(field_label)

    field_table = QTableWidget(0, 6)
    field_table.setHorizontalHeaderLabels(["사용", "Codebeamer 필드", "타입", "필수", "값 방식", "값"])
    field_table.setAlternatingRowColors(True)
    _configure_data_table(field_table, minimum_height=PRIMARY_TABLE_MIN_HEIGHT)
    _configure_table_columns(field_table, [80, 240, 180, 90, 160, 240])
    page.field_table = field_table
    layout.addWidget(field_table, 2)

    status_label = QLabel("")
    status_label.setObjectName("status_label")
    _configure_constrained_panel(status_label, max_width=WIDE_FORM_PANEL_MAX_WIDTH)
    layout.addWidget(status_label)

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    previous_button = QPushButton("이전")
    next_button = QPushButton("다음")
    next_button.setObjectName("primary_button")
    next_button.setEnabled(False)
    buttons.addWidget(previous_button)
    buttons.addStretch(1)
    buttons.addWidget(next_button)
    layout.addLayout(buttons)

    page._loaded = False
    page._refreshing = False
    page._field_candidates = []
    page._current_preview_context = None

    enable_root_item.setVisible(is_structure_page)
    enable_group_folder.setVisible(is_structure_page)
    form_container.setVisible(is_structure_page)
    structure_summary_label.setVisible(is_field_page)
    field_label.setVisible(is_field_page)
    field_table.setVisible(is_field_page)

    def _sync_root_enabled_state(file_root_enabled: bool, group_enabled: bool) -> None:
        """`sync_root_enabled_state` 상태를 동기화한다."""
        has_any_root = file_root_enabled or group_enabled
        group_by_column.setEnabled(group_enabled)
        regex_target.setEnabled(has_any_root)
        regex_pattern.setEnabled(has_any_root)
        preview_table.setEnabled(has_any_root)
        field_table.setEnabled(has_any_root)
        preview_label.setEnabled(has_any_root)
        field_label.setEnabled(has_any_root)
        if group_enabled:
            field_label.setText("그룹 폴더 필드 매핑")
        elif file_root_enabled:
            field_label.setText("파일 루트 필드 매핑")
        else:
            field_label.setText("상단 데이터 필드 매핑")

    def _current_field_assignments() -> dict[str, dict[str, object]]:
        field_assignments: dict[str, dict[str, object]] = {}
        for row_index in range(field_table.rowCount()):
            enabled_widget = field_table.cellWidget(row_index, 0)
            mode_combo = field_table.cellWidget(row_index, 4)
            value_combo = field_table.cellWidget(row_index, 5)
            field_item = field_table.item(row_index, 1)
            if enabled_widget is None or mode_combo is None or value_combo is None or field_item is None:
                continue
            mode_key = str(mode_combo.currentData() or ROOT_ASSIGNMENT_MODE_FILE_SOURCE)
            field_assignments[field_item.text()] = {
                "enabled": bool(enabled_widget.isChecked()),
                "mode": mode_key,
                "value": (
                    str(value_combo.currentData() or "").strip()
                    if mode_key == ROOT_ASSIGNMENT_MODE_FILE_SOURCE
                    else value_combo.currentText().strip()
                ),
            }
        return field_assignments

    def _legacy_field_sources(field_assignments: dict[str, dict[str, object]]) -> dict[str, str]:
        field_sources: dict[str, str] = {}
        for schema_field, assignment in field_assignments.items():
            if not bool(assignment.get("enabled")):
                continue
            if str(assignment.get("mode") or "") != ROOT_ASSIGNMENT_MODE_FILE_SOURCE:
                continue
            source_key = str(assignment.get("value") or "").strip()
            if source_key:
                field_sources[schema_field] = source_key
        return field_sources

    def get_config() -> dict[str, object]:
        """`get_config` 값을 반환한다."""
        field_assignments = _current_field_assignments()
        if not field_assignments and page._current_preview_context is not None:
            field_assignments = {
                str(schema_field): dict(assignment)
                for schema_field, assignment in dict(
                    getattr(page._current_preview_context, "field_assignments", {}) or {}
                ).items()
                if str(schema_field).strip() and isinstance(assignment, dict)
            }
        group_enabled = bool(enable_group_folder.isChecked())
        return {
            "enabled": bool(enable_root_item.isChecked()),
            "group_enabled": group_enabled,
            "root_mode": ROOT_ITEM_MODE_GROUP_BY_COLUMN if group_enabled else ROOT_ITEM_MODE_FILE,
            "group_by_column": str(group_by_column.currentData() or "").strip(),
            "regex_pattern": regex_pattern.text().strip(),
            "regex_target": str(regex_target.currentData() or "file_stem"),
            "field_assignments": field_assignments,
            "field_sources": _legacy_field_sources(field_assignments),
        }

    def _column_label(column_name: str, source_options) -> str:
        if column_name == "file_name":
            return "파일"
        if column_name == "parse_target":
            return "파싱 대상"
        if column_name == "matched":
            return "일치"
        source_lookup = {str(option.key): str(option.label) for option in source_options}
        return source_lookup.get(column_name, column_name)

    def _mode_options(candidate) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        if bool(candidate.allows_file_source):
            options.append(("소스 값", ROOT_ASSIGNMENT_MODE_FILE_SOURCE))
        if bool(candidate.allows_fixed_value):
            options.append((
                "직접 입력" if bool(getattr(candidate, "allows_custom_value", False)) else "고정값",
                ROOT_ASSIGNMENT_MODE_FIXED_VALUE,
            ))
        return options

    def _populate_value_combo(value_combo, candidate, preview_context, mode_key: str, selected_value: str) -> None:
        value_combo.blockSignals(True)
        value_combo.clear()
        value_combo.setEditable(False)
        value_combo.addItem("", "")

        if mode_key == ROOT_ASSIGNMENT_MODE_FILE_SOURCE:
            for option in preview_context.source_options:
                value_combo.addItem(str(option.label), str(option.key))
            selected_index = value_combo.findData(selected_value)
            value_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        elif mode_key == ROOT_ASSIGNMENT_MODE_FIXED_VALUE:
            if bool(getattr(candidate, "allows_custom_value", False)):
                value_combo.setEditable(True)
                if value_combo.lineEdit() is not None:
                    value_combo.lineEdit().setPlaceholderText("직접 입력")
                value_combo.setCurrentText(selected_value)
            else:
                for option_name in getattr(candidate, "fixed_options", []):
                    value_combo.addItem(str(option_name), str(option_name))
                selected_index = value_combo.findData(selected_value)
                value_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        else:
            selected_index = value_combo.findData(selected_value)
            value_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        value_combo.blockSignals(False)

    def _bind_editable_combo_commit(combo, callback) -> None:
        line_edit = combo.lineEdit()
        if line_edit is None:
            return
        if bool(line_edit.property("_codex_commit_bound")):
            return
        line_edit.setProperty("_codex_commit_bound", True)
        line_edit.editingFinished.connect(callback)

    def _sync_row_enabled_state(enabled_widget, mode_combo, value_combo, *, candidate) -> None:
        """`sync_row_enabled_state` 상태를 동기화한다."""
        row_enabled = bool(enabled_widget.isChecked()) and bool(candidate.supported)
        has_mode_choice = mode_combo.count() > 0 and str(mode_combo.itemData(0) or "").strip() != ""
        mode_combo.setEnabled(row_enabled and has_mode_choice)
        value_combo.setEnabled(row_enabled and has_mode_choice)

    def _refresh_preview() -> None:
        """`refresh_preview` 표시를 새로 고친다."""
        if not page._loaded or page._refreshing:
            return
        page._refreshing = True
        try:
            preview_context = on_preview_requested(get_config())
            page.load_context(preview_context)
        finally:
            page._refreshing = False

    def load_context(preview_context) -> None:
        """`load_context` 데이터를 불러온다."""
        page._current_preview_context = preview_context
        page._loaded = False

        regex_pattern.blockSignals(True)
        regex_target.blockSignals(True)
        group_by_column.blockSignals(True)
        enable_root_item.blockSignals(True)
        enable_group_folder.blockSignals(True)
        enable_root_item.setChecked(bool(getattr(preview_context, "enabled", True)))
        enable_group_folder.setChecked(bool(getattr(preview_context, "group_enabled", False)))
        group_by_column.clear()
        group_by_column.addItem("사용 안 함", "")
        for column_name in getattr(preview_context, "group_column_options", []):
            group_by_column.addItem(str(column_name), str(column_name))
        group_index = group_by_column.findData(str(getattr(preview_context, "group_by_column", "") or ""))
        group_by_column.setCurrentIndex(group_index if group_index >= 0 else 0)
        regex_pattern.setText(str(preview_context.regex_pattern or ""))
        target_index = regex_target.findData(str(preview_context.regex_target or "file_stem"))
        regex_target.setCurrentIndex(target_index if target_index >= 0 else 0)
        regex_pattern.blockSignals(False)
        regex_target.blockSignals(False)
        group_by_column.blockSignals(False)
        enable_root_item.blockSignals(False)
        enable_group_folder.blockSignals(False)
        _sync_root_enabled_state(
            bool(getattr(preview_context, "enabled", True)),
            bool(getattr(preview_context, "group_enabled", False)),
        )
        if is_field_page:
            structure_parts: list[str] = []
            if bool(getattr(preview_context, "enabled", False)):
                structure_parts.append("파일별 최상단 폴더")
            if bool(getattr(preview_context, "group_enabled", False)):
                group_name = str(getattr(preview_context, "group_by_column", "") or "").strip()
                structure_parts.append(
                    f"그룹 폴더 ({group_name})" if group_name else "그룹 폴더"
                )
            structure_summary_label.setText(
                "현재 구조: " + (", ".join(structure_parts) if structure_parts else "상단 폴더 생성 안 함")
            )

        preview_headers = [
            _column_label(column_name, preview_context.source_options)
            for column_name in preview_context.preview_columns
        ]
        preview_table.clear()
        preview_table.setColumnCount(len(preview_headers))
        preview_table.setHorizontalHeaderLabels(preview_headers)
        preview_table.setRowCount(len(preview_context.preview_rows))
        for row_index, row_values in enumerate(preview_context.preview_rows):
            for col_index, column_name in enumerate(preview_context.preview_columns):
                preview_table.setItem(
                    row_index,
                    col_index,
                    QTableWidgetItem(str(row_values.get(column_name) or "")),
                )
        _configure_table_columns(preview_table, [180] * max(len(preview_headers), 1))

        current_field_assignments = dict(preview_context.field_assignments)
        field_table.setRowCount(len(preview_context.field_candidates))
        for row_index, candidate in enumerate(preview_context.field_candidates):
            enabled_widget = QCheckBox()
            current_assignment = dict(current_field_assignments.get(candidate.schema_field) or {})
            selected_mode = str(
                current_assignment.get("mode") or ROOT_ASSIGNMENT_MODE_FILE_SOURCE
            ).strip()
            selected_value = str(current_assignment.get("value") or "").strip()
            enabled_widget.setChecked(bool(current_assignment.get("enabled")))
            enabled_widget.setEnabled(bool(candidate.supported))
            field_table.setCellWidget(row_index, 0, enabled_widget)
            field_table.setItem(row_index, 1, QTableWidgetItem(candidate.schema_field))
            field_table.setItem(row_index, 2, QTableWidgetItem(candidate.field_type))
            field_table.setItem(row_index, 3, QTableWidgetItem("yes" if candidate.mandatory else "no"))

            mode_combo = QComboBox()
            mode_options = _mode_options(candidate)
            if not mode_options:
                mode_combo.addItem("지원 안 함", "")
            else:
                for mode_label, mode_key in mode_options:
                    mode_combo.addItem(mode_label, mode_key)
                mode_index = mode_combo.findData(selected_mode)
                if mode_index < 0:
                    mode_index = 0
                mode_combo.setCurrentIndex(mode_index)
            field_table.setCellWidget(row_index, 4, mode_combo)

            value_combo = QComboBox()
            _populate_value_combo(
                value_combo,
                candidate,
                preview_context,
                str(mode_combo.currentData() or ""),
                selected_value,
            )
            _bind_editable_combo_commit(value_combo, _refresh_preview)
            field_table.setCellWidget(row_index, 5, value_combo)
            _sync_row_enabled_state(
                enabled_widget,
                mode_combo,
                value_combo,
                candidate=candidate,
            )

            def _on_enabled_toggled(
                _checked,
                *,
                checkbox=enabled_widget,
                mode_widget=mode_combo,
                value_widget=value_combo,
                row_candidate=candidate,
            ):
                _sync_row_enabled_state(
                    checkbox,
                    mode_widget,
                    value_widget,
                    candidate=row_candidate,
                )
                _refresh_preview()

            def _on_mode_changed(_index, *, mode_widget=mode_combo, value_widget=value_combo, row_candidate=candidate):
                _populate_value_combo(
                    value_widget,
                    row_candidate,
                    preview_context,
                    str(mode_widget.currentData() or ""),
                    "",
                )
                _bind_editable_combo_commit(value_widget, _refresh_preview)
                _refresh_preview()

            def _on_value_changed(_text, *, value_widget=value_combo):
                if bool(value_widget.isEditable()):
                    return
                _refresh_preview()

            enabled_widget.toggled.connect(_on_enabled_toggled)
            mode_combo.currentIndexChanged.connect(_on_mode_changed)
            value_combo.currentTextChanged.connect(_on_value_changed)

        _configure_table_columns(field_table, [80, 240, 180, 90, 160, 240])
        status_label.setText(str(preview_context.status_message or ""))
        next_button.setEnabled(not bool(preview_context.has_blocking_issues))
        page._loaded = True

    previous_button.clicked.connect(lambda: page.request_previous())
    next_button.clicked.connect(lambda: page.request_next())
    regex_pattern.textChanged.connect(lambda _text: _refresh_preview())
    regex_target.currentIndexChanged.connect(lambda _index: _refresh_preview())
    group_by_column.currentIndexChanged.connect(lambda _index: _refresh_preview())
    def _on_root_item_toggled(checked: bool) -> None:
        _sync_root_enabled_state(bool(checked), bool(enable_group_folder.isChecked()))
        _refresh_preview()

    def _on_group_folder_toggled(checked: bool) -> None:
        _sync_root_enabled_state(bool(enable_root_item.isChecked()), bool(checked))
        _refresh_preview()

    enable_root_item.toggled.connect(_on_root_item_toggled)
    enable_group_folder.toggled.connect(_on_group_folder_toggled)

    page.get_config = get_config
    page.load_context = load_context
    return page


class RootItemPage(QtWidget):
    """루트 구조 또는 루트 필드 할당 상태를 소유하는 페이지."""

    def __init__(
        self,
        on_preview_requested,
        *,
        page_mode: str = "structure",
    ) -> None:
        super().__init__()
        _initialize_root_item_page(
            self,
            on_preview_requested,
            page_mode=page_mode,
        )


def create_root_item_page(on_preview_requested, *, page_mode: str = "structure"):
    """기존 factory 호출 계약으로 `RootItemPage`를 생성한다."""
    return RootItemPage(on_preview_requested, page_mode=page_mode)


def create_placeholder_page(title_text: str, description: str):
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    qt["QLabel"]
    QPushButton = qt["QPushButton"]
    QPlainTextEdit = qt["QPlainTextEdit"]

    page = QWidget()
    layout = QVBoxLayout(page)
    _configure_page_layout(layout)

    body = QPlainTextEdit()
    body.setReadOnly(True)
    body.setPlainText(description)
    layout.addWidget(body, 1)

    buttons = QHBoxLayout()
    _configure_inline_layout(buttons)
    previous_button = QPushButton("이전")
    next_button = QPushButton("다음")
    buttons.addWidget(previous_button)
    buttons.addStretch(1)
    buttons.addWidget(next_button)
    layout.addLayout(buttons)

    previous_button.clicked.connect(lambda: page.request_previous())
    next_button.clicked.connect(lambda: page.request_next())
    return page
