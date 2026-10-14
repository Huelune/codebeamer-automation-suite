from __future__ import annotations

from typing import Any

import pandas as pd


UPLOAD_RECORD_KEY_COLUMN = "Upload Record Key"


class HierarchyProcessor:
    """raw DataFrame를 계층 업로드용 DataFrame으로 후처리하는 전용 processor다."""

    def __init__(self, header_row: int = 1, summary_col: str = "Summary", logger=None):
        self.header_row = header_row
        self.summary_col = summary_col
        self.logger = logger

    @staticmethod
    def is_blank(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, float) and pd.isna(value):
            return True
        return isinstance(value, str) and value.strip() == ""

    @classmethod
    def normalize_scalar(cls, value: Any) -> Any:
        if cls.is_blank(value):
            return None
        if isinstance(value, str):
            return value.strip()
        return value

    @classmethod
    def _normalize_dataframe_values(cls, dataframe: pd.DataFrame) -> pd.DataFrame:
        if dataframe.empty:
            return dataframe

        work = dataframe.copy().astype(object)
        for column in work.columns:
            work[column] = pd.Series(
                [cls.normalize_scalar(value) for value in work[column].tolist()],
                dtype=object,
            )
        return work

    @classmethod
    def collect_values(cls, values: list[Any], single_to_scalar: bool = False):
        cleaned = [cls.normalize_scalar(value) for value in values if not cls.is_blank(value)]
        if not cleaned:
            return None
        if single_to_scalar and len(cleaned) == 1:
            return cleaned[0]
        return cleaned

    @classmethod
    def keep_value(cls, values: list[Any], mode: str = "first"):
        cleaned = [cls.normalize_scalar(value) for value in values if not cls.is_blank(value)]
        if not cleaned:
            return None
        if mode == "first":
            return cleaned[0]
        if mode == "last":
            return cleaned[-1]
        if mode == "list":
            return cleaned
        raise ValueError("mode must be one of: first, last, list")

    @staticmethod
    def _item_id_column(columns: Any) -> str | None:
        """update/upsert 대상 id 열. 업로드 단계와 같은 규칙으로 찾는다."""
        case_insensitive_match = None
        for column in columns:
            name = str(column or "").strip()
            if not name or name.startswith("_"):
                continue
            if name == "id":
                return column
            if name.casefold() == "id" and case_insensitive_match is None:
                case_insensitive_match = column
        return case_insensitive_match

    @classmethod
    def _item_id_text(cls, value: Any) -> str | None:
        normalized = cls.normalize_scalar(value)
        if cls.is_blank(normalized):
            return None
        if isinstance(normalized, float) and normalized.is_integer():
            normalized = int(normalized)
        return str(normalized).strip() or None

    def merge_multiline_records(
        self,
        raw_df: pd.DataFrame,
        list_cols: list[str],
        keep_mode: str = "first",
        single_to_scalar: bool = False,
    ) -> pd.DataFrame:
        work = raw_df.copy().reset_index(drop=True)

        record_key_mode = UPLOAD_RECORD_KEY_COLUMN in work.columns
        group_ids = []
        if record_key_mode:
            key_to_group: dict[str, int] = {}
            closed_keys: set[str] = set()
            previous_key: str | None = None
            # 빈 행은 읽을 때 빠지므로 순번으로는 Excel 행을 알 수 없다. 읽을 때 남긴 실제 행을 쓴다.
            excel_rows = (
                work["_excel_row"].tolist()
                if "_excel_row" in work.columns
                else [index + self.header_row + 1 for index in range(len(work.index))]
            )
            for index, raw_key in enumerate(work[UPLOAD_RECORD_KEY_COLUMN].tolist()):
                key = str(self.normalize_scalar(raw_key) or "").strip()
                if not key:
                    raise ValueError(
                        f"{UPLOAD_RECORD_KEY_COLUMN} 값이 비어 있습니다. Excel {excel_rows[index]}행"
                    )
                if previous_key is not None and key != previous_key:
                    closed_keys.add(previous_key)
                if key in closed_keys:
                    raise ValueError(
                        f"{UPLOAD_RECORD_KEY_COLUMN} '{key}' 행은 연속해서 배치해야 합니다. Excel {excel_rows[index]}행"
                    )
                if key not in key_to_group:
                    key_to_group[key] = len(key_to_group) + 1
                group_ids.append(key_to_group[key])
                previous_key = key
        else:
            # 수정용 파일은 id가 레코드 경계다. Summary가 비어도 다른 id가 나오면 새 레코드로 본다.
            # 첫 Summary 앞의 행도 버리지 않고 레코드로 남겨 검증에서 이름이나 id가 없다고 알린다.
            id_column = self._item_id_column(work.columns)
            current_group = 0
            current_item_id: str | None = None
            for _, row in work.iterrows():
                item_id = self._item_id_text(row[id_column]) if id_column is not None else None
                if (
                    current_group == 0
                    or not self.is_blank(row[self.summary_col])
                    or (item_id is not None and item_id != current_item_id)
                ):
                    current_group += 1
                    current_item_id = item_id
                group_ids.append(current_group)

        work["_group"] = group_ids
        work = work[work["_group"] > 0].copy()

        keep_cols = [
            column
            for column in work.columns
            if column not in [self.summary_col, "_group", UPLOAD_RECORD_KEY_COLUMN, *list_cols]
        ]
        merged_rows = []

        for _, group_df in work.groupby("_group", sort=True):
            record_key = None
            if record_key_mode:
                record_key = str(group_df[UPLOAD_RECORD_KEY_COLUMN].iloc[0]).strip()
                scalar_columns = [self.summary_col, *keep_cols]
                for column in scalar_columns:
                    if column in {"_summary_indent", "_excel_row"}:
                        continue
                    normalized_values = [
                        self.normalize_scalar(value)
                        for value in group_df[column].tolist()
                    ]
                    if any(value != normalized_values[0] for value in normalized_values[1:]):
                        group_rows = group_df["_excel_row"].tolist() if "_excel_row" in group_df.columns else []
                        location = f" Excel {group_rows[0]}-{group_rows[-1]}행" if group_rows else ""
                        raise ValueError(
                            f"{UPLOAD_RECORD_KEY_COLUMN} '{record_key}'의 일반 필드 '{column}' 값이 행마다 다릅니다."
                            f"{location}"
                        )
            row_out = {
                self.summary_col: (
                    self.normalize_scalar(group_df[self.summary_col].iloc[0])
                    if record_key_mode
                    else self.keep_value(group_df[self.summary_col].tolist(), mode="first")
                ),
                "_summary_indent": self.keep_value(group_df["_summary_indent"].tolist(), mode="first"),
                "_start_excel_row": self.keep_value(group_df["_excel_row"].tolist(), mode="first"),
                "_end_excel_row": self.keep_value(group_df["_excel_row"].tolist(), mode="last"),
            }
            if record_key is not None:
                row_out["_upload_record_key"] = record_key

            for column in list_cols:
                if "." in str(column):
                    row_out[column] = [
                        self.normalize_scalar(value)
                        for value in group_df[column].tolist()
                    ]
                else:
                    row_out[column] = self.collect_values(
                        group_df[column].tolist(),
                        single_to_scalar=single_to_scalar,
                    )

            for column in keep_cols:
                if column in {"_summary_indent", "_excel_row"}:
                    continue
                row_out[column] = (
                    self.normalize_scalar(group_df[column].iloc[0])
                    if record_key_mode
                    else self.keep_value(group_df[column].tolist(), mode=keep_mode)
                )

            merged_rows.append(row_out)

        merged_df = self._normalize_dataframe_values(pd.DataFrame(merged_rows, dtype=object).reset_index(drop=True))
        merged_df["_row_id"] = merged_df.index
        return merged_df

    def add_hierarchy_by_indent(self, merged_df: pd.DataFrame) -> pd.DataFrame:
        work = merged_df.copy().reset_index(drop=True)

        parent_row_ids = []
        depths = []
        stack: list[Any] = []
        prev_indent = None

        for index, row in work.iterrows():
            current_indent = int(row["_summary_indent"]) if not self.is_blank(row["_summary_indent"]) else 0

            if prev_indent is not None and current_indent > prev_indent + 1:
                raise ValueError(
                    f"들여쓰기 단계가 1단계 이상 점프했습니다. "
                    f"row_id={index}, prev={prev_indent}, current={current_indent}"
                )

            while stack and stack[-1]["indent"] >= current_indent:
                stack.pop()

            parent_row_id = stack[-1]["row_id"] if stack else None
            parent_row_ids.append(parent_row_id)
            depths.append(current_indent)

            stack.append({"row_id": index, "indent": current_indent})
            prev_indent = current_indent

        work["depth"] = pd.Series(depths, dtype=object)
        work["parent_row_id"] = pd.Series(parent_row_ids, dtype=object)
        return self._normalize_dataframe_values(work)

    def build_upload_df(self, hierarchy_df: pd.DataFrame, list_cols: list[str] | None = None) -> pd.DataFrame:
        work = hierarchy_df.copy()
        del list_cols
        work["upload_name"] = work[self.summary_col].apply(self.normalize_scalar)
        return self._normalize_dataframe_values(work)


__all__ = ["UPLOAD_RECORD_KEY_COLUMN", "HierarchyProcessor"]
