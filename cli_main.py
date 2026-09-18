from __future__ import annotations

from pathlib import Path

from src.cli_helpers import choose_one
from src.cli_helpers import confirm
from src.codebeamer_client import CodebeamerClient
from src.config import load_config
from src.excel_reader import ExcelReader
from src.hierarchy_processor import HierarchyProcessor
from src.logger import setup_logger
from src.mapping_service import MappingService
from src.models import OptionCheckStatus
from src.models import PayloadStatus
from src.upload_pipeline import load_tracker_schema_df
from src.upload_pipeline import prepare_upload_dataframe
from src.upload_pipeline import run_validation_pipeline
from src.upload_pipeline import suggest_mapping_from_headers
from src.wizard import CodebeamerUploadWizard


BLOCKING_OPTION_STATUSES = {
    OptionCheckStatus.DIRECT_PARSE_FAILED.value,
    OptionCheckStatus.DF_COLUMN_MISSING.value,
    OptionCheckStatus.FIELD_UNSUPPORTED.value,
    OptionCheckStatus.LOOKUP_REQUIRED.value,
    OptionCheckStatus.OPTION_MAP_MISSING.value,
    OptionCheckStatus.OPTION_NOT_FOUND.value,
    OptionCheckStatus.OPTION_SOURCE_UNAVAILABLE.value,
}
INFO_OPTION_STATUSES = {
    OptionCheckStatus.PRECONSTRUCTION_REQUIRED.value,
}
USER_LOOKUP_FAILURE_SUFFIXES = (
    "USER_LOOKUP_NOT_RUN",
    "USER_LOOKUP_FAILED",
    "USER_LOOKUP_AMBIGUOUS",
    "USER_NOT_FOUND",
)


def _suggest_excel_path() -> str | None:
    """자주 쓰는 위치에서 기본 Excel 파일 경로를 찾아 제안한다."""
    candidates = [
        Path("./data/codebeamer_test_data_en_small.xlsx"),
        Path("./data.xlsx"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _prompt_excel_path() -> str:
    """사용자에게 Excel 파일 경로를 묻고 기본 경로가 있으면 함께 제안한다."""
    suggested = _suggest_excel_path()
    if suggested:
        raw = input(f"Excel file path (Enter={suggested}): ").strip()
        return raw or suggested
    return input("Excel file path: ").strip()

def _print_option_check_summary(option_check_df):
    """옵션 검증 결과를 읽기 쉬운 정보와 차단 이슈로 나눠 출력한다."""
    if option_check_df.empty:
        print("옵션/참조형 필드 검증 통과")
        return False

    print("\n[옵션 검증 결과]")
    print(option_check_df)

    status_series = option_check_df["status"].fillna("")
    info_df = option_check_df[status_series.isin(INFO_OPTION_STATUSES)]
    blocking_df = option_check_df[
        status_series.isin(BLOCKING_OPTION_STATUSES)
        | status_series.astype(str).str.endswith(USER_LOOKUP_FAILURE_SUFFIXES)
    ]

    if not info_df.empty:
        print("\n[사전 구성 정보]")
        print(
            info_df[
                [
                    "df_column",
                    "schema_field",
                    "resolved_field_kind",
                    "preconstruction_kind",
                    "preconstruction_detail",
                    "payload_target_kind",
                ]
            ].drop_duplicates()
        )

    if not blocking_df.empty:
        print("\n[차단 이슈 요약]")

        unsupported_df = blocking_df[
            blocking_df["status"] == OptionCheckStatus.FIELD_UNSUPPORTED.value
        ]
        if not unsupported_df.empty:
            print("- 미지원 필드가 있습니다. unsupported_reason을 확인해야 합니다.")

        lookup_required_df = blocking_df[
            blocking_df["status"] == OptionCheckStatus.LOOKUP_REQUIRED.value
        ]
        if not lookup_required_df.empty:
            print("- generic_reference lookup resolver가 없어 payload 생성 전에 중단됩니다.")

        option_not_found_df = blocking_df[
            blocking_df["status"] == OptionCheckStatus.OPTION_NOT_FOUND.value
        ]
        if not option_not_found_df.empty:
            print("- schema option에 없는 값이 업로드 데이터에 있습니다.")

        direct_parse_failed_df = blocking_df[
            blocking_df["status"] == OptionCheckStatus.DIRECT_PARSE_FAILED.value
        ]
        if not direct_parse_failed_df.empty:
            print("- tracker item ID를 직접 파싱하지 못한 값이 있습니다.")

        user_lookup_df = blocking_df[
            blocking_df["status"].astype(str).str.endswith(USER_LOOKUP_FAILURE_SUFFIXES)
        ]
        if not user_lookup_df.empty:
            print("- 사용자 lookup 실패 행이 있습니다. __lookup_error 또는 error 컬럼을 확인해야 합니다.")

        print("\n[차단 이슈 상세]")
        print(blocking_df)
        return True

    return False


def _prompt_default_field_values(mapper: MappingService, schema_df) -> dict[str, str]:
    """공통 기본값으로 쓸 static option 필드를 사용자에게 선택받는다."""
    candidates = mapper.get_default_value_candidates(schema_df)
    if not candidates:
        return {}

    print("\n[공통 기본값 후보]")
    print("행 값이 있으면 행 값이 우선하고, 비어 있으면 아래 기본값을 사용합니다.")
    for candidate in candidates:
        print(f"- {candidate['field_name']}: {', '.join(candidate['options'])}")

    if not confirm("공통 기본값을 지정할까요?", default=False):
        return {}

    selected_defaults: dict[str, str] = {}
    for candidate in candidates:
        options = ["설정 안 함", *list(candidate["options"])]
        selected_index = choose_one(
            f"필드 '{candidate['field_name']}' 기본값 선택",
            options,
            default_index=0,
        )
        if selected_index == 0:
            continue
        selected_defaults[candidate["field_name"]] = options[selected_index]

    return selected_defaults


def main():
    """프로젝트 선택부터 업로드 실행까지 전체 CLI 흐름을 실행한다."""
    cfg = load_config()
    logger = setup_logger("cb-cli", level=cfg.log_level)

    client = CodebeamerClient(
        cfg.base_url,
        cfg.username,
        cfg.password,
        logger,
        rate_limit_retry_delay_seconds=cfg.rate_limit_retry_delay_seconds,
        rate_limit_max_retries=cfg.rate_limit_max_retries,
    )
    reader = ExcelReader(header_row=cfg.excel_header_row, logger=logger)
    wizard = CodebeamerUploadWizard(
        client=client,
        processor=None,
        mapper=MappingService(logger=logger),
        reader=reader,
        logger=logger,
    )

    projects = wizard.load_projects()
    project_index = choose_one("프로젝트 선택", [p["name"] for p in projects])
    wizard.select_project(projects[project_index]["id"])

    trackers = wizard.load_trackers()
    tracker_index = choose_one("트래커 선택", [t["name"] for t in trackers])
    tracker_id = trackers[tracker_index]["id"]
    wizard.select_tracker(tracker_id)

    file_path = _prompt_excel_path()
    sheet_names = reader.list_sheet_names(file_path)
    sheet_index = choose_one("시트 선택", sheet_names)
    sheet_name = sheet_names[sheet_index]

    headers = reader.read_headers(file_path, sheet_name)
    summary_candidates = [col for col in headers if col.lower() == "summary"]
    if not summary_candidates:
        summary_candidates = [col for col in headers if col == "요약"]
    if summary_candidates:
        summary_col = summary_candidates[0]
        print(f"자동으로 요약 컬럼을 '{summary_col}' 로 선택했습니다.")
    else:
        summary_index = choose_one("요약 컬럼 선택", headers)
        summary_col = headers[summary_index]

    tracker_schema, schema_df = load_tracker_schema_df(wizard)
    suggested_mapping = suggest_mapping_from_headers(headers, schema_df)

    print("\n[컬럼 자동 매핑 확인]")
    selected_mapping: dict[str, str] = {}
    for col, matched_field in suggested_mapping.items():
        if confirm(f"Map '{col}' -> '{matched_field}'?", default=True):
            selected_mapping[col] = matched_field
            print(f"  mapped: {col} -> {matched_field}")

    wizard.processor = HierarchyProcessor(
        header_row=cfg.excel_header_row,
        summary_col=summary_col,
        logger=logger,
    )
    _, list_cols = prepare_upload_dataframe(
        wizard,
        file_path=file_path,
        sheet_name=sheet_name,
        summary_col=summary_col,
        selected_mapping=selected_mapping,
        schema=tracker_schema,
        schema_df=schema_df,
    )

    if list_cols:
        print("\n[multipleValues 기준 자동 선택된 list 컬럼]")
        for col in list_cols:
            print("-", col)
    else:
        print("\n[multipleValues 기준 자동 선택된 list 컬럼 없음]")

    print("\n[업로드 컬럼 목록]")
    for col in wizard.state.upload_df.columns:
        print("-", col)

    selected_default_values = _prompt_default_field_values(wizard.mapper, schema_df)
    validation_result = run_validation_pipeline(
        wizard,
        selected_mapping,
        selected_default_values=selected_default_values,
    )
    comparison_df = validation_result.comparison_df
    print("\n[Schema Comparison]")
    print(comparison_df[["df_column", "selected_schema_field", "status"]])

    if wizard.state.table_field_mapping:
        print("\n[자동 감지된 TableField 컬럼]")
        for df_col, tf_info in wizard.state.table_field_mapping.items():
            print(f"- {df_col} -> {tf_info['table_field_name']}.{tf_info['column_name']}")
    else:
        print("\n[감지된 TableField 컬럼 없음]")

    print("\n[옵션/참조형 필드 처리 중]")
    selected_option_mapping = validation_result.selected_option_mapping
    option_check_df = validation_result.option_check_df

    if selected_option_mapping:
        print(f"자동 감지된 옵션/참조형 필드 수: {len(selected_option_mapping)}")

        has_blocking_issues = _print_option_check_summary(option_check_df)
        if has_blocking_issues:
            if not confirm("차단 이슈를 확인했습니다. 그래도 계속 진행할까요?", default=False):
                return
        elif not option_check_df.empty and not confirm(
            "사전 구성 정보를 확인했습니다. 계속 진행할까요?", default=True
        ):
            return
    else:
        print("옵션/참조형 필드 매핑 대상이 없습니다.")

    payload_df = validation_result.payload_df
    ready_count = len(payload_df[payload_df["payload_status"] == PayloadStatus.READY.value])
    failed_count = len(payload_df[payload_df["payload_status"] == PayloadStatus.FAILED.value])
    print(f"\n[Payload Cache] ready={ready_count}, failed={failed_count}")

    preview_row_id = int(wizard.state.upload_df["_row_id"].min())
    print(f"\n[Payload Preview row_id={preview_row_id}]")
    print(wizard.preview_payload(preview_row_id))

    is_dry = confirm("Dry run으로 진행할까요?", default=True)
    result = wizard.upload(dry_run=is_dry)

    print("\n[Upload Result]")
    success_df = result["success_df"]
    failed_df = result["failed_df"]
    unresolved_df = result["unresolved_df"]
    print(f"success={len(success_df)}, failed={len(failed_df)}, unresolved={len(unresolved_df)}")

    if not success_df.empty:
        print("\n[Success Preview]")
        print(success_df.head(20))

    if not failed_df.empty:
        print("\n[Failed Preview]")
        print(failed_df.head(20))

    if not unresolved_df.empty:
        print("\n[Unresolved Preview]")
        print(unresolved_df.head(20))

    if confirm(f"상태를 '{cfg.output_dir}' 디렉터리에 저장할까요?", default=True):
        wizard.save_state(cfg.output_dir)
        print(f"저장 완료: {cfg.output_dir}")


if __name__ == "__main__":
    main()
