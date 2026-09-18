from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pandas as pd

from .models import OptionCheckStatus
from .models import OptionMapKind
from .models import TrackerItemResolutionMode
from .upload_policy import DEFAULT_TRACKER_ITEM_ID_REGEX


TrackerItemLookupCacheEntry = tuple[Any, str | None, str | None]



if TYPE_CHECKING:
    from .mapping_service import MappingService
    from .models import WizardState

class WizardTrackerItemLookupMixin:
    # 조립된 뒤 사용할 속성의 타입 선언이다. 실제 값은
    # `CodebeamerUploadWizard.__init__` 이 채우므로 여기서는 선언만 둔다.
    mapper: MappingService
    state: WizardState

    def _tracker_item_setting(
        self,
        schema_field: str,
        option_info: dict[str, Any],
    ) -> dict[str, Any]:
        """필드별 TrackerItemChoiceField 처리 방식을 정규화한다."""
        raw_setting = self.state.selected_tracker_item_settings.get(str(schema_field).strip(), {})
        del option_info

        return {
            # Tracker Item 이름/summary 조회는 대량 검증 시 API 호출을 급증시키므로 잠근다.
            # 기존 preset의 query 모드도 여기서 강제로 ID 추출 방식으로 전환한다.
            "mode": TrackerItemResolutionMode.REGEX.value,
            "regex_pattern": str(raw_setting.get("regex_pattern") or DEFAULT_TRACKER_ITEM_ID_REGEX).strip(),
        }

    def _decorate_tracker_item_option_maps(
        self,
        option_maps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """TrackerItemChoiceField option map에 GUI 선택 설정을 반영한다."""
        decorated: dict[str, dict[str, Any]] = {}
        for schema_field, option_info in option_maps.items():
            if option_info.get("kind") != OptionMapKind.TRACKER_ITEM_DIRECT.value:
                decorated[schema_field] = option_info
                continue

            setting = self._tracker_item_setting(schema_field, option_info)
            decorated[schema_field] = {
                **option_info,
                "tracker_item_mode": setting["mode"],
                "tracker_item_regex_pattern": setting["regex_pattern"],
            }

        return decorated

    def _resolve_tracker_item_reference_value(
        self,
        schema_field: str,
        raw_value: Any,
        option_info: dict[str, Any],
    ) -> TrackerItemLookupCacheEntry:
        """TrackerItemChoiceField 값을 정규식 ID 추출 방식으로 해석한다."""
        multiple_values = bool(option_info.get("multiple_values", False))

        regex_pattern = str(option_info.get("tracker_item_regex_pattern") or "").strip()
        if not regex_pattern:
            return (
                None,
                OptionCheckStatus.TRACKER_ITEM_REGEX_MISSING.value,
                "tracker item regex pattern is empty",
            )

        try:
            resolved = self.mapper.resolve_tracker_item_reference_value_with_regex(
                raw_value,
                multiple_values=multiple_values,
                pattern=regex_pattern,
            )
            return resolved, "RESOLVED", None
        except Exception as exc:
            return None, OptionCheckStatus.DIRECT_PARSE_FAILED.value, str(exc)

    def _resolve_tracker_item_reference_fields(
        self,
        upload_df: pd.DataFrame,
        option_mapping: dict[str, str],
        option_maps: dict[str, dict[str, Any]],
    ) -> pd.DataFrame:
        """TrackerItemChoiceField 값을 정규식 ID 추출 방식으로 미리 해석한다."""
        work = upload_df.copy()

        for df_col, schema_field in option_mapping.items():
            option_info = option_maps.get(schema_field, {})
            if option_info.get("kind") != OptionMapKind.TRACKER_ITEM_DIRECT.value:
                continue

            resolved_values: list[Any] = []
            statuses: list[Any] = []
            errors: list[Any] = []

            for _, row in work.iterrows():
                raw_value = row[df_col]
                if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
                    resolved_values.append(None)
                    statuses.append(None)
                    errors.append(None)
                    continue

                resolved, status, error = self._resolve_tracker_item_reference_value(
                    schema_field,
                    raw_value,
                    option_info,
                )
                resolved_values.append(resolved)
                statuses.append(status)
                errors.append(error)

            work[f"{df_col}__resolved"] = resolved_values
            work[f"{df_col}__lookup_status"] = statuses
            work[f"{df_col}__lookup_error"] = errors

        return work
