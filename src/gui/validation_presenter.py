from __future__ import annotations

from typing import Any

import pandas as pd

from src.models import MappingStatus
from src.models import OptionCheckStatus
from src.models import PayloadStatus

from .service_core import gui_display_text


DEFAULT_VALUE_COLUMN_LABEL = "(기본값)"
USER_HIDDEN_TABLE_COLUMNS = {
    "id",
    "parent",
    "parent_row_id",
    "upload_name",
    "depth",
    "_row_id",
    "_summary_indent",
    "_start_excel_row",
    "_end_excel_row",
    "_excel_row",
    "payload_json",
    "payload_status",
    "payload_error",
    "error_response_json",
}


class ValidationPresenter:
    @staticmethod
    def display_text(value: Any) -> str:
        return gui_display_text(value)

    @staticmethod
    def to_row_key(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            if pd.isna(value):
                return ""
            if value.is_integer():
                return str(int(value))
            return str(value)
        if isinstance(value, int):
            return str(value)

        text = str(value).strip()
        if not text or text.lower() == "nan":
            return ""
        try:
            numeric = float(text)
        except ValueError:
            return text
        if numeric.is_integer():
            return str(int(numeric))
        return text

    @classmethod
    def scoped_row_key(cls, row_id: Any, source_file_path: Any = None) -> str:
        normalized_row_key = cls.to_row_key(row_id)
        if not normalized_row_key:
            return ""
        normalized_source = str(source_file_path or "").strip()
        if not normalized_source:
            return normalized_row_key
        return f"{normalized_source}::{normalized_row_key}"

    @classmethod
    def build_row_label(cls, row: pd.Series) -> str:
        start_row = cls.to_row_key(row.get("_start_excel_row"))
        end_row = cls.to_row_key(row.get("_end_excel_row"))
        excel_row = cls.to_row_key(row.get("_excel_row"))
        row_key = cls.to_row_key(row.get("_row_id"))

        if start_row and end_row and start_row != end_row:
            return f"Excel {start_row}-{end_row}행"
        if start_row:
            return f"Excel {start_row}행"
        if excel_row:
            return f"Excel {excel_row}행"
        if row_key:
            return f"행 {row_key}"
        return ""

    @classmethod
    def build_row_context_map(
        cls,
        row_context_df: pd.DataFrame | None,
    ) -> dict[str, dict[str, Any]]:
        if row_context_df is None or row_context_df.empty:
            return {}

        show_source_prefix = False
        if "source_file_path" in row_context_df.columns:
            distinct_source_paths = {
                cls.display_text(value)
                for value in row_context_df["source_file_path"].tolist()
                if cls.display_text(value)
            }
            show_source_prefix = len(distinct_source_paths) > 1

        row_context_map: dict[str, dict[str, Any]] = {}
        for _, row in row_context_df.iterrows():
            row_key = cls.scoped_row_key(row.get("_row_id"), row.get("source_file_path"))
            if not row_key:
                continue

            item_name = cls.display_text(row.get("upload_name"))
            if not item_name:
                for fallback_column in ("Summary", "summary", "요약", "name"):
                    if fallback_column in row.index:
                        item_name = cls.display_text(row.get(fallback_column))
                    if item_name:
                        break

            source_file = cls.display_text(row.get("source_file"))
            row_label = cls.build_row_label(row)
            if show_source_prefix and source_file:
                row_label = f"[{source_file}] {row_label}" if row_label else f"[{source_file}]"

            row_context_map[row_key] = {
                "row_id": row_key,
                "row_label": row_label,
                "item_name": item_name,
                "source_file": source_file,
                "source_file_path": cls.display_text(row.get("source_file_path")),
                "values": row.to_dict(),
            }

        return row_context_map

    @staticmethod
    def row_context(
        row_key: str,
        row_context_map: dict[str, dict[str, Any]],
        *,
        fallback_item_name: str = "",
    ) -> dict[str, str]:
        context = row_context_map.get(row_key, {})
        return {
            "row_id": row_key,
            "row_label": str(context.get("row_label") or (f"행 {row_key}" if row_key else "")),
            "item_name": str(context.get("item_name") or fallback_item_name or ""),
            "source_file": str(context.get("source_file") or ""),
            "source_file_path": str(context.get("source_file_path") or ""),
        }

    @staticmethod
    def is_hidden_user_column(column_name: Any) -> bool:
        text = str(column_name or "").strip()
        if not text:
            return False
        return text in USER_HIDDEN_TABLE_COLUMNS or text.startswith("_") or "__" in text

    @classmethod
    def raw_value_from_row_context(
        cls,
        row_key: str,
        column_name: str,
        row_context_map: dict[str, dict[str, Any]],
    ) -> str:
        if not row_key or not column_name:
            return ""
        context = row_context_map.get(row_key, {})
        values = context.get("values") if isinstance(context, dict) else None
        if not isinstance(values, dict):
            return ""
        return cls.display_text(values.get(column_name))

    @staticmethod
    def message_from_option_status(row: pd.Series) -> tuple[str, str, str]:
        status = str(row.get("status") or "")
        field_name = str(row.get("schema_field") or "")
        df_column = str(row.get("df_column") or "")
        is_default_value = (
            str(row.get("value_source") or "") == "default"
            or df_column == DEFAULT_VALUE_COLUMN_LABEL
        )

        if status == OptionCheckStatus.FIELD_UNSUPPORTED.value:
            if is_default_value:
                return (
                    "오류",
                    f"{field_name} 필드는 공통 기본값으로 바로 넣을 수 없습니다.",
                    "기본값을 비우거나, Excel 컬럼으로 직접 매핑할 수 있는지 확인하세요.",
                )
            return (
                "오류",
                f"{field_name} 필드는 현재 GUI에서 지원하지 않습니다.",
                "이 컬럼 매핑을 해제하거나 지원되는 다른 필드로 다시 매핑하세요.",
            )
        if status == OptionCheckStatus.LOOKUP_REQUIRED.value:
            if is_default_value:
                return (
                    "오류",
                    f"{field_name} 기본값은 추가 조회가 필요해서 바로 넣을 수 없습니다.",
                    "기본값을 비우고 행별 값으로 관리하거나, 지원 로직을 추가해야 합니다.",
                )
            return (
                "오류",
                f"{field_name} 값은 업로드 전에 추가 조회가 필요합니다.",
                "이 컬럼 매핑을 해제하거나, 지원되는 필드로 다시 매핑하세요.",
            )
        if status == OptionCheckStatus.OPTION_NOT_FOUND.value:
            if is_default_value:
                return (
                    "오류",
                    f"{field_name} 기본값이 현재 트래커 옵션 목록에 없습니다.",
                    "기본값을 다시 선택하고, 트래커 옵션 이름과 정확히 일치하는지 확인하세요.",
                )
            return (
                "오류",
                f"{df_column} 입력값이 현재 트래커 옵션 목록에 없습니다.",
                "Excel 값을 트래커 옵션 이름과 동일하게 수정하세요.",
            )
        if status == OptionCheckStatus.DIRECT_PARSE_FAILED.value:
            if is_default_value:
                return (
                    "오류",
                    f"{field_name} 기본값을 아이디 형식으로 해석하지 못했습니다.",
                    "숫자 ID처럼 허용되는 형식으로 값을 다시 지정하세요.",
                )
            return (
                "오류",
                f"{df_column} 값을 아이디 형식으로 해석하지 못했습니다.",
                "셀 값을 숫자 ID처럼 허용되는 형식으로 수정하세요.",
            )
        if status == OptionCheckStatus.TRACKER_ITEM_REGEX_MISSING.value:
            return (
                "오류",
                f"{field_name or df_column} 필드의 정규식이 비어 있습니다.",
                "매핑 단계에서 Tracker Item 처리 방식을 다시 선택하거나 정규식을 입력하세요.",
            )
        if status == OptionCheckStatus.TRACKER_ITEM_LOOKUP_NOT_FOUND.value:
            return (
                "오류",
                f"{df_column} 값으로 source tracker에서 일치하는 항목을 찾지 못했습니다.",
                "입력 문구를 확인하거나 정규식 ID 추출 방식으로 바꾼 뒤 다시 검증하세요.",
            )
        if status == OptionCheckStatus.TRACKER_ITEM_LOOKUP_AMBIGUOUS.value:
            return (
                "오류",
                f"{df_column} 값이 source tracker에서 여러 항목과 겹칩니다.",
                "더 구체적인 문구를 쓰거나 정규식 ID 추출 방식으로 바꾼 뒤 다시 검증하세요.",
            )
        if status == OptionCheckStatus.DF_COLUMN_MISSING.value:
            return (
                "오류",
                f"매핑된 Excel 컬럼 {df_column} 을(를) 찾을 수 없습니다.",
                "파일을 다시 불러오고, 매핑 화면에서 컬럼 선택을 다시 확인하세요.",
            )
        if status == "SCHEMA_FIELD_MISSING":
            return (
                "오류",
                str(row.get("error") or "선택한 기본값 필드를 현재 스키마에서 찾을 수 없습니다."),
                "매핑 화면으로 돌아가 기본값 필드를 다시 선택하세요.",
            )
        if status == "OPTION_MAP_MISSING":
            return (
                "오류",
                str(row.get("error") or "기본값 검증에 필요한 option map을 만들 수 없습니다."),
                "트래커 스키마를 다시 불러오거나 해당 기본값을 비운 뒤 다시 검증하세요.",
            )
        if status == OptionCheckStatus.OPTION_SOURCE_UNAVAILABLE.value:
            return (
                "오류",
                f"{field_name} 필드의 값을 확인할 준비가 아직 되어 있지 않습니다.",
                "이 컬럼 매핑을 해제하거나 지원되는 다른 필드로 다시 매핑하세요.",
            )
        # 서버 조회 자체가 실패했다. 입력값 문제로 안내하면 맞는 값을 계속 고치게 된다.
        if status.endswith(("USER_LOOKUP_FAILED", "MEMBER_LOOKUP_FAILED")):
            return (
                "오류",
                f"{df_column} 값을 서버에서 조회하지 못했습니다.",
                "요청 제한이나 연결 문제일 수 있습니다. 잠시 후 다시 검증하고, 계속되면 연결 설정과 권한을 확인하세요.",
            )
        if status.endswith(("USER_LOOKUP_AMBIGUOUS", "USER_NOT_FOUND")):
            return (
                "오류",
                f"{df_column} 값으로 사용자를 찾지 못했습니다.",
                "사용자 이름, 이메일, 아이디를 확인하고 프로젝트 멤버인지 점검하세요.",
            )
        if status.endswith(("MEMBER_LOOKUP_AMBIGUOUS", "MEMBER_NOT_FOUND")):
            return (
                "오류",
                f"{df_column} 값으로 담당자, 역할, 그룹을 찾지 못했습니다.",
                "입력값을 확인하고, 대상 사용자가 프로젝트 역할 또는 그룹에 포함되는지 점검하세요.",
            )
        return (
            "안내",
            str(row.get("error") or row.get("detail") or status or ""),
            "내용을 확인한 뒤 필요하면 매핑이나 입력값을 조정하세요.",
        )

    @staticmethod
    def parse_payload_error(payload_error: str) -> dict[str, str]:
        work = str(payload_error or "").strip()
        parsed = {
            "code": "",
            "field": "",
            "df_column": "",
            "row_id": "",
            "detail": work,
        }
        if not work.startswith("[") or "]" not in work:
            return parsed

        code_end = work.find("]")
        parsed["code"] = work[1:code_end].strip()
        remainder = work[code_end + 1 :].strip()

        for key, token in (("field", "field='"), ("df_column", "df_column='")):
            token_index = remainder.find(token)
            if token_index >= 0:
                value_start = token_index + len(token)
                value_end = remainder.find("'", value_start)
                if value_end > value_start:
                    parsed[key] = remainder[value_start:value_end]

        row_token = "_row_id="
        row_index = remainder.find(row_token)
        if row_index >= 0:
            row_start = row_index + len(row_token)
            row_end = remainder.find(" ", row_start)
            parsed["row_id"] = remainder[row_start:] if row_end < 0 else remainder[row_start:row_end]

        detail_start = remainder.find(" ", row_index + len(row_token)) if row_index >= 0 else -1
        if detail_start >= 0:
            parsed["detail"] = remainder[detail_start + 1 :].strip()
        elif remainder:
            parsed["detail"] = remainder
        return parsed

    @classmethod
    def message_from_payload_error(cls, row: pd.Series) -> tuple[str, str, str, str]:
        parsed = cls.parse_payload_error(str(row.get("payload_error") or "").strip())
        code = parsed["code"]
        field = parsed["field"] or str(row.get("upload_name") or "")
        column = parsed["df_column"]
        detail = parsed["detail"]

        messages = {
            "FIELD_UNSUPPORTED": (
                "현재 GUI에서 지원하지 않는 필드가 포함되어 있습니다.",
                "매핑에서 해당 컬럼을 해제하거나 다른 필드로 바꾼 뒤 다시 검증하세요.",
            ),
            "LOOKUP_REQUIRED": (
                "필요한 값을 찾지 못해 업로드용 데이터를 만들 수 없습니다.",
                "입력값을 확인하거나, 지원되는 필드와 값으로 수정한 뒤 다시 검증하세요.",
            ),
            "DIRECT_PARSE_FAILED": (
                "입력값을 아이디 형식으로 해석하지 못했습니다.",
                "숫자 ID처럼 허용되는 형식으로 값을 수정한 뒤 다시 검증하세요.",
            ),
            "OPTION_RESOLUTION_FAILED": (
                "선택값을 업로드 형식으로 변환하지 못했습니다.",
                "Excel 값이나 기본값이 트래커 옵션 이름과 정확히 일치하는지 확인하세요.",
            ),
            "UPDATE_ITEM_ID_COLUMN_MISSING": (
                "업데이트 모드에서는 Excel에 id 열이 반드시 있어야 합니다.",
                "파일 단계에서 id 열이 포함된 파일을 선택한 뒤 다시 검증하세요.",
            ),
            "UPDATE_ITEM_ID_MISSING": (
                "업데이트 대상 item id 값이 비어 있습니다.",
                "해당 행의 id 값을 채운 뒤 다시 검증하세요.",
            ),
            "UPDATE_ITEM_ID_INVALID": (
                "업데이트 대상 item id를 숫자로 해석할 수 없습니다.",
                "해당 행의 id 값을 양의 정수로 수정한 뒤 다시 검증하세요.",
            ),
            "UPDATE_ITEM_ID_DUPLICATE": (
                "같은 item id가 같은 파일 안에 중복되어 있습니다.",
                "한 item id는 한 번만 나오도록 정리한 뒤 다시 검증하세요.",
            ),
            "UPDATE_ITEM_FETCH_FAILED": (
                "기존 item 정보를 조회하지 못해 업데이트 payload를 만들 수 없습니다.",
                "id 값과 서버 연결 상태를 확인한 뒤 다시 검증하세요.",
            ),
            "UPDATE_ITEM_TRACKER_MISMATCH": (
                "업데이트 대상 item이 선택한 트래커의 아이템이 아닙니다.",
                "다른 트래커에서 내보낸 파일인지 확인하고, 그 트래커를 선택하거나 id 값을 고친 뒤 다시 실행하세요.",
            ),
            "UPSERT_PARENT_ID_REQUIRED": (
                "계층형 신규 행을 연결할 기존 부모 item id가 없습니다.",
                "부모 행에 기존 id를 넣거나, 계층을 제거한 뒤 다시 검증하세요.",
            ),
            "UPSERT_UPDATE_WITH_NEW_ANCESTOR": (
                "기존 수정 행의 상위 계층에 신규 생성 행이 섞여 있습니다.",
                "상위 계층에도 기존 id를 넣거나, 해당 하위 행을 신규 생성으로 분리한 뒤 다시 검증하세요.",
            ),
        }
        if code in messages:
            message, action = messages[code]
            if code in {
                "UPDATE_ITEM_ID_COLUMN_MISSING",
                "UPDATE_ITEM_ID_MISSING",
                "UPDATE_ITEM_ID_INVALID",
                "UPDATE_ITEM_ID_DUPLICATE",
                "UPDATE_ITEM_FETCH_FAILED",
                "UPDATE_ITEM_TRACKER_MISMATCH",
                "UPSERT_PARENT_ID_REQUIRED",
                "UPSERT_UPDATE_WITH_NEW_ANCESTOR",
            }:
                column = column or "id"
                field = field or "id"
            return column, field, message, action
        if detail:
            return (
                column,
                field,
                detail,
                "문구를 확인하고 매핑 또는 입력값을 수정한 뒤 다시 검증하세요.",
            )
        return (
            column,
            field,
            "업로드용 데이터를 만들 수 없습니다.",
            "문구를 확인하고 매핑 또는 입력값을 수정한 뒤 다시 검증하세요.",
        )

    @classmethod
    def build_summary_stats(
        cls,
        issue_df: pd.DataFrame,
        row_context_df: pd.DataFrame | None,
    ) -> dict[str, int]:
        total_rows = 0
        if row_context_df is not None and not row_context_df.empty and "_row_id" in row_context_df.columns:
            total_rows = len(
                {
                    cls.scoped_row_key(row.get("_row_id"), row.get("source_file_path"))
                    for _, row in row_context_df.iterrows()
                    if cls.scoped_row_key(row.get("_row_id"), row.get("source_file_path"))
                }
            )

        if issue_df is None or issue_df.empty:
            return {
                "total_rows": total_rows,
                "ready_rows": total_rows,
                "error_rows": 0,
                "warning_rows": 0,
                "config_errors": 0,
                "config_warnings": 0,
                "error_count": 0,
                "info_count": 0,
            }

        row_id_series = issue_df["row_id"].fillna("").astype(str).str.strip()
        row_issue_df = issue_df[row_id_series != ""]
        config_issue_df = issue_df[row_id_series == ""]
        error_row_ids = set(
            row_issue_df.loc[row_issue_df["severity"] == "오류", "row_id"]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        error_row_ids.discard("")
        warning_row_ids = set(
            row_issue_df.loc[row_issue_df["severity"] != "오류", "row_id"]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        warning_row_ids.discard("")
        warning_row_ids -= error_row_ids

        return {
            "total_rows": total_rows,
            "ready_rows": max(total_rows - len(error_row_ids) - len(warning_row_ids), 0),
            "error_rows": len(error_row_ids),
            "warning_rows": len(warning_row_ids),
            "config_errors": int(config_issue_df["severity"].eq("오류").sum()),
            "config_warnings": int(config_issue_df["severity"].eq("안내").sum()),
            "error_count": int(issue_df["severity"].eq("오류").sum()),
            "info_count": int(issue_df["severity"].eq("안내").sum()),
        }

    @classmethod
    def build_user_issue_df(
        cls,
        comparison_df: pd.DataFrame,
        option_check_df: pd.DataFrame,
        payload_df: pd.DataFrame,
        *,
        row_context_df: pd.DataFrame | None = None,
        selected_default_values: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        row_context_map = cls.build_row_context_map(row_context_df)
        issue_columns = [
            "severity",
            "category",
            "row_id",
            "row_label",
            "item_name",
            "source_file",
            "source_file_path",
            "column",
            "field",
            "raw_value",
            "message",
            "action",
        ]
        issues: list[dict[str, str]] = []

        if comparison_df is not None and not comparison_df.empty:
            for _, row in comparison_df.iterrows():
                status = str(row.get("status") or "").strip()
                if status in {MappingStatus.OK.value, "ok", "matched", ""}:
                    continue
                if status in {MappingStatus.UNMAPPED.value, "unmapped"}:
                    continue
                if status in {MappingStatus.SCHEMA_FIELD_MISSING.value, "schema_field_missing"}:
                    issues.append(
                        {
                            "severity": "오류",
                            "category": "매핑",
                            "row_id": "",
                            "row_label": "",
                            "item_name": "",
                            "source_file": "",
                            "source_file_path": "",
                            "column": str(row.get("df_column") or ""),
                            "field": str(row.get("selected_schema_field") or ""),
                            "raw_value": "",
                            "message": "선택한 필드를 현재 트래커 스키마에서 찾을 수 없습니다.",
                            "action": "매핑 단계에서 다른 필드를 선택하거나, 해당 컬럼의 생성/수정 적용을 해제하세요.",
                        }
                    )

        if option_check_df is not None and not option_check_df.empty:
            for _, row in option_check_df.iterrows():
                if cls.is_hidden_user_column(row.get("df_column")):
                    continue
                severity, message, action = cls.message_from_option_status(row)
                if not message:
                    continue
                if str(row.get("status") or "") == OptionCheckStatus.PRECONSTRUCTION_REQUIRED.value:
                    continue
                row_key = cls.scoped_row_key(row.get("_row_id"), row.get("source_file_path"))
                row_context = cls.row_context(row_key, row_context_map)
                issues.append(
                    {
                        "severity": severity,
                        "category": "값 검증",
                        "row_id": row_context["row_id"],
                        "row_label": row_context["row_label"],
                        "item_name": row_context["item_name"],
                        "source_file": row_context["source_file"]
                        or cls.display_text(row.get("source_file")),
                        "source_file_path": row_context["source_file_path"]
                        or cls.display_text(row.get("source_file_path")),
                        "column": str(row.get("df_column") or ""),
                        "field": str(row.get("schema_field") or ""),
                        "raw_value": cls.display_text(row.get("raw_value")),
                        "message": message,
                        "action": action,
                    }
                )

        if payload_df is not None and not payload_df.empty:
            failed_df = payload_df[payload_df["payload_status"] != PayloadStatus.READY.value]
            for _, row in failed_df.iterrows():
                column, field, message, action = cls.message_from_payload_error(row)
                parsed = cls.parse_payload_error(str(row.get("payload_error") or ""))
                row_key = cls.scoped_row_key(
                    parsed.get("row_id") or row.get("_row_id"),
                    row.get("source_file_path"),
                )
                row_context = cls.row_context(
                    row_key,
                    row_context_map,
                    fallback_item_name=cls.display_text(row.get("upload_name")),
                )
                raw_value = ""
                if column == DEFAULT_VALUE_COLUMN_LABEL:
                    raw_value = cls.display_text((selected_default_values or {}).get(field))
                elif column:
                    raw_value = cls.raw_value_from_row_context(row_key, column, row_context_map)
                issues.append(
                    {
                        "severity": "오류",
                        "category": "Payload 생성",
                        "row_id": row_context["row_id"],
                        "row_label": row_context["row_label"],
                        "item_name": row_context["item_name"],
                        "source_file": row_context["source_file"]
                        or cls.display_text(row.get("source_file")),
                        "source_file_path": row_context["source_file_path"]
                        or cls.display_text(row.get("source_file_path")),
                        "column": column,
                        "field": field,
                        "raw_value": raw_value,
                        "message": message,
                        "action": action,
                    }
                )

        return cls.finalize_issue_df(pd.DataFrame(issues, columns=issue_columns))

    @staticmethod
    def finalize_issue_df(issue_df: pd.DataFrame) -> pd.DataFrame:
        if issue_df.empty:
            return issue_df
        issue_df = issue_df.drop_duplicates().reset_index(drop=True)
        severity_order = {"오류": 0, "안내": 1}
        issue_df["_sort"] = issue_df["severity"].map(severity_order).fillna(99)
        issue_df["_config_sort"] = (
            issue_df["row_id"].fillna("").astype(str).str.strip().ne("").astype(int)
        )
        issue_df["_row_order"] = pd.to_numeric(
            issue_df["row_id"], errors="coerce"
        ).fillna(10**9)
        return issue_df.sort_values(
            by=["_sort", "_config_sort", "_row_order", "category", "column", "field"]
        ).drop(columns=["_sort", "_config_sort", "_row_order"])
