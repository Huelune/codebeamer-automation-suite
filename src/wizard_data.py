from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pandas as pd


if TYPE_CHECKING:
    from .codebeamer_client import CodebeamerClient
    from .excel_reader import ExcelReader
    from .hierarchy_processor import HierarchyProcessor
    from .mapping_service import MappingService
    from .models import WizardState

class WizardDataPreparationMixin:
    # 조립된 뒤 사용할 속성의 타입 선언이다. 실제 값은
    # `CodebeamerUploadWizard.__init__` 이 채우므로 여기서는 선언만 둔다.
    client: CodebeamerClient
    mapper: MappingService
    processor: HierarchyProcessor | None
    reader: ExcelReader | None
    state: WizardState

    def load_projects(self) -> list[dict]:
        """사용자가 선택할 프로젝트 목록을 가져온다."""
        return self.client.get_projects()

    def select_project(self, project_id: int) -> None:
        """작업 대상을 프로젝트 단위로 바꾸고 관련 캐시를 초기화한다."""
        if self.state.project_id != project_id:
            self.state.user_lookup_cache.clear()
            self.state.member_lookup_cache.clear()
            self.state.group_lookup_cache.clear()
            self.state.tracker_role_cache.clear()
            self.state.tracker_item_lookup_cache.clear()
            self._invalidate_payload_cache()
        self.state.project_id = project_id

    def load_trackers(self) -> list[dict]:
        """현재 프로젝트 안에서 선택 가능한 트래커 목록을 가져온다."""
        if self.state.project_id is None:
            raise ValueError("project_id must be selected first.")
        return self.client.get_trackers(self.state.project_id)

    def load_tracker_items(self, tracker_id: int) -> list[dict]:
        """트래커 안의 아이템 목록을 가져온다."""
        return self.client.get_tracker_items(tracker_id)

    def load_root_items(self, tracker_id: int) -> list[dict]:
        """트래커 루트 바로 아래의 아이템만 가져온다."""
        return self.client.get_tracker_children(tracker_id)

    def select_tracker(self, tracker_id: int) -> None:
        """업로드 대상 트래커를 저장한다."""
        if self.state.tracker_id != tracker_id:
            self.state.member_lookup_cache.clear()
            self.state.tracker_role_cache.clear()
            self.state.tracker_item_lookup_cache.clear()
            self._invalidate_payload_cache()
        self.state.tracker_id = tracker_id

    def _invalidate_payload_cache(self) -> None:
        """입력/매핑/schema가 바뀌면 payload cache를 비운다."""
        self.state.payload_df = None

    def load_raw_dataframe(self, raw_df: pd.DataFrame, list_cols: list[str] | None = None) -> None:
        """reader가 만든 raw DataFrame을 업로드용 중간 DataFrame들로 후처리한다."""
        if self.processor is None:
            raise ValueError("processor is required to transform raw dataframe.")

        if list_cols is None:
            list_cols = []

        self.state.list_cols = list_cols
        self.state.raw_df = raw_df.copy()
        self.state.merged_df = self.processor.merge_multiline_records(self.state.raw_df, list_cols=list_cols)
        self.state.hierarchy_df = self.processor.add_hierarchy_by_indent(self.state.merged_df)
        self.state.upload_df = self.processor.build_upload_df(self.state.hierarchy_df, list_cols=list_cols)
        self.state.converted_upload_df = None
        self.state.table_field_mapping = {}
        self.state.upload_result = None
        self._invalidate_payload_cache()

    def read_excel(self, file_path: str, sheet_name: str | int = 0, list_cols: list[str] | None = None) -> None:
        """호환용 메서드다. reader로 raw DataFrame을 만든 뒤 processor로 후처리한다."""
        if self.reader is not None:
            raw_df = self.reader.read_excel(file_path=file_path, sheet_name=sheet_name)
        elif self.processor is not None and hasattr(self.processor, "read_excel"):
            raw_df = self.processor.read_excel(file_path=file_path, sheet_name=sheet_name)
        else:
            raise ValueError("reader or compatible processor.read_excel() is required to load Excel files.")
        self.load_raw_dataframe(raw_df, list_cols=list_cols)

    def _payload_source_df(self) -> pd.DataFrame:
        if self.state.converted_upload_df is not None:
            return self.state.converted_upload_df
        if self.state.upload_df is not None:
            return self.state.upload_df
        raise ValueError("No upload dataframe is available.")

    def load_schema_and_compare(self, selected_mapping: dict[str, str]) -> pd.DataFrame:
        """트래커 schema를 읽고 업로드 컬럼과 비교 결과를 만든다."""
        if self.state.tracker_id is None:
            raise ValueError("tracker_id must be selected first.")
        if self.state.upload_df is None:
            raise ValueError("upload_df is not ready. Read Excel first.")

        self.state.selected_mapping = selected_mapping
        if self.state.schema is None or self.state.schema_df is None:
            self.state.schema = self.client.get_tracker_schema(self.state.tracker_id)
            self.state.schema_df = self.mapper.flatten_schema_fields(self.state.schema)
        self.state.comparison_df = self.mapper.compare_upload_df_with_schema(
            upload_df=self.state.upload_df,
            schema_df=self.state.schema_df,
            selected_mapping=selected_mapping,
        )
        self._invalidate_payload_cache()

        self._detect_table_field_columns()
        return self.state.comparison_df

    def _detect_table_field_columns(self) -> None:
        """`TableFieldName.ColumnName` 형태의 Excel 컬럼을 자동으로 감지한다."""
        if self.state.schema_df is None or self.state.upload_df is None:
            return

        table_fields = self.state.schema_df[self.state.schema_df.get("is_table_field", False)]
        if table_fields.empty:
            return

        table_field_info: dict[str, Any] = {}
        for _, tf_row in table_fields.iterrows():
            tf_name = tf_row["field_name"]
            tf_columns = tf_row.get("table_columns", [])

            if tf_columns:
                table_field_info[tf_name] = {}
                for col_def in tf_columns:
                    col_name = col_def.get("name")
                    if col_name:
                        table_field_info[tf_name][col_name] = col_def

        table_field_mapping = {}
        for df_col in self.state.upload_df.columns:
            if "." not in df_col:
                continue

            parts = df_col.split(".", 1)
            if len(parts) != 2:
                continue

            potential_tf_name = parts[0].strip()
            potential_col_name = parts[1].strip()

            if potential_tf_name in table_field_info and potential_col_name in table_field_info[potential_tf_name]:
                table_field_mapping[df_col] = {
                    "table_field_name": potential_tf_name,
                    "column_name": potential_col_name,
                    "column_info": table_field_info[potential_tf_name][potential_col_name],
                }

        self.state.table_field_mapping = table_field_mapping
