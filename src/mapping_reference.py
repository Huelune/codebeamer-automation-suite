from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .models import ReferenceType
from .models import TrackerItemField
from .models import TrackerSchemaName


class MappingReferenceMixin:
    @staticmethod
    def _is_missing_scalar(value: Any) -> bool:
        """None 또는 scalar NaN처럼 비어 있는 값을 공통 판정한다."""
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except Exception:
            return False

    @staticmethod
    def _is_truthy_flag(value: Any) -> bool:
        """문자열이나 숫자로 들어온 참/거짓 값을 불린으로 단순화한다."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        try:
            if bool(pd.isna(value)):
                return False
        except Exception:
            pass
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return bool(value)

    @staticmethod
    def _extract_status_option_ids(fields: list[dict[str, Any]]) -> set[int]:
        """상태 필드가 가진 모든 option ID를 모아 mandatory 계산에 사용한다."""
        for field in fields:
            tracker_item_field = field.get("trackerItemField")
            field_name = field.get("name")
            options = field.get("options") or []
            if (
                tracker_item_field == TrackerItemField.STATUS.value
                or field_name == TrackerSchemaName.STATUS.value
            ):
                return {
                    option["id"]
                    for option in options
                    if isinstance(option, dict) and option.get("id") is not None
                }
        return set()

    @staticmethod
    def _build_mandatory_metadata(
        field: dict[str, Any],
        all_status_option_ids: set[int],
    ) -> dict[str, Any]:
        """필드가 항상 필수인지, 특정 상태에서만 필수인지 정리한다."""
        mandatory_statuses = field.get("mandatoryInStatuses") or []
        mandatory_status_ids = {
            status["id"]
            for status in mandatory_statuses
            if isinstance(status, dict) and status.get("id") is not None
        }
        is_always_mandatory = bool(field.get("mandatory", False))
        covers_all_statuses = bool(all_status_option_ids) and mandatory_status_ids == all_status_option_ids
        mandatory = is_always_mandatory or covers_all_statuses

        return {
            "mandatory": mandatory,
            "mandatory_mode": (
                "always" if mandatory
                else "conditional" if mandatory_statuses
                else "never"
            ),
            "mandatory_statuses": mandatory_statuses,
            "mandatory_status_names": [
                status.get("name") for status in mandatory_statuses if status.get("name")
            ],
        }

    @staticmethod
    def _is_choice_value_model(value_model: Any) -> bool:
        """valueModel 문자열이 choice 계열인지 빠르게 판정한다."""
        return isinstance(value_model, str) and "Choice" in value_model

    @staticmethod
    def _parse_tracker_item_reference_id(raw_value: Any) -> int:
        """Tracker item 입력값에서 실제 item id를 추출한다."""
        if isinstance(raw_value, bool):
            raise ValueError(f"Cannot parse tracker item id from value: {raw_value!r}")
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, float):
            if pd.isna(raw_value) or not raw_value.is_integer():
                raise ValueError(f"Cannot parse tracker item id from value: {raw_value!r}")
            return int(raw_value)
        if isinstance(raw_value, dict) and raw_value.get("id") is not None:
            return int(raw_value["id"])

        text = str(raw_value).strip()
        bracket_match = re.search(r"\[.*?:(\d+).*?\]", text)
        if bracket_match:
            return int(bracket_match.group(1))
        bracket_match = re.search(r"\[(\d+)\]", text)
        if bracket_match:
            return int(bracket_match.group(1))
        if text.isdigit():
            return int(text)
        if text.endswith(".0") and text[:-2].isdigit():
            return int(text[:-2])
        raise ValueError(f"Cannot parse tracker item id from value: {raw_value!r}")

    @classmethod
    def _parse_tracker_item_reference_id_with_regex(
        cls,
        raw_value: Any,
        *,
        pattern: str,
    ) -> int:
        """사용자 지정 정규식에서 tracker item id를 추출한다."""
        ids = cls._parse_tracker_item_reference_ids_with_regex(raw_value, pattern=pattern)
        return ids[0]

    @classmethod
    def _parse_tracker_item_reference_ids_with_regex(
        cls,
        raw_value: Any,
        *,
        pattern: str,
    ) -> list[int]:
        """사용자 지정 정규식에서 tracker item id 후보를 모두 추출한다."""
        if isinstance(raw_value, dict) and raw_value.get("id") is not None:
            return [int(raw_value["id"])]

        regex_pattern = str(pattern or "").strip()
        if not regex_pattern:
            raise ValueError("Tracker item regex pattern is empty.")

        text = str(raw_value).strip()
        matches = list(re.finditer(regex_pattern, text))
        if not matches:
            raise ValueError(f"Tracker item regex did not match value: {raw_value!r}")

        resolved_ids: list[int] = []
        for match in matches:
            groups = [group for group in match.groups() if group is not None and str(group).strip()]
            candidate = groups[0] if groups else match.group(0)
            candidate_text = str(candidate).strip()
            if not candidate_text:
                raise ValueError(f"Tracker item regex produced empty match: {raw_value!r}")
            if candidate_text.endswith(".0") and candidate_text[:-2].isdigit():
                resolved_ids.append(int(candidate_text[:-2]))
                continue
            if candidate_text.isdigit():
                resolved_ids.append(int(candidate_text))
                continue
            raise ValueError(f"Tracker item regex did not produce numeric id: {candidate_text!r}")

        return resolved_ids

    @classmethod
    def normalize_multi_value_items(cls, raw_value: Any) -> list[Any]:
        """다중값 필드 입력을 개별 항목 목록으로 정규화한다."""
        if raw_value is None:
            return []

        if isinstance(raw_value, list):
            candidates = raw_value
        elif isinstance(raw_value, tuple | set):
            candidates = list(raw_value)
        elif isinstance(raw_value, str):
            text = raw_value.strip()
            if not text:
                return []
            if "\n" in text or "\r" in text:
                candidates = text.splitlines()
            elif ";" in text:
                candidates = text.split(";")
            else:
                candidates = [raw_value]
        else:
            candidates = [raw_value]

        normalized_items: list[Any] = []
        for item in candidates:
            if item is None:
                continue
            if isinstance(item, str):
                stripped = item.strip()
                if not stripped:
                    continue
                normalized_items.append(stripped)
                continue
            normalized_items.append(item)
        return normalized_items

    @classmethod
    def _to_tracker_item_reference_payload(cls, raw_value: Any) -> dict[str, Any]:
        """원본 값을 tracker item reference payload dict로 정규화한다."""
        item_id = cls._parse_tracker_item_reference_id(raw_value)
        if isinstance(raw_value, dict):
            normalized = dict(raw_value)
            normalized["id"] = item_id
            normalized.setdefault("type", ReferenceType.TRACKER_ITEM.value)
            result = {
                "id": normalized.get("id"),
                "name": normalized.get("name"),
                "type": normalized.get("type"),
            }
            return {key: value for key, value in result.items() if value is not None}

        return {
            "id": item_id,
            "type": ReferenceType.TRACKER_ITEM.value,
        }

    @classmethod
    def _to_tracker_item_reference_payload_with_regex(
        cls,
        raw_value: Any,
        *,
        pattern: str,
    ) -> dict[str, Any]:
        """정규식 결과를 tracker item reference payload dict로 정규화한다."""
        item_id = cls._parse_tracker_item_reference_id_with_regex(raw_value, pattern=pattern)
        if isinstance(raw_value, dict):
            normalized = dict(raw_value)
            normalized["id"] = item_id
            normalized.setdefault("type", ReferenceType.TRACKER_ITEM.value)
            result = {
                "id": normalized.get("id"),
                "name": normalized.get("name"),
                "type": normalized.get("type"),
            }
            return {key: value for key, value in result.items() if value is not None}

        return {
            "id": item_id,
            "type": ReferenceType.TRACKER_ITEM.value,
        }

    @classmethod
    def resolve_tracker_item_reference_value(
        cls,
        raw_value: Any,
        *,
        multiple_values: bool,
    ) -> Any:
        """TrackerItemChoiceField 입력을 업로드용 reference payload로 바꾼다."""
        if raw_value is None or str(raw_value).strip() == "":
            return None

        if multiple_values:
            values = cls.normalize_multi_value_items(raw_value)
            resolved_values = []
            for item in values:
                if item is None or str(item).strip() == "":
                    continue
                resolved_values.append(cls._to_tracker_item_reference_payload(item))
            return resolved_values or None

        return cls._to_tracker_item_reference_payload(raw_value)

    @classmethod
    def resolve_tracker_item_reference_value_with_regex(
        cls,
        raw_value: Any,
        *,
        multiple_values: bool,
        pattern: str,
    ) -> Any:
        """TrackerItemChoiceField 입력을 사용자 지정 정규식으로 업로드용 reference payload로 바꾼다."""
        if raw_value is None or str(raw_value).strip() == "":
            return None

        if multiple_values:
            values = cls.normalize_multi_value_items(raw_value)
            resolved_values: list[Any] = []
            for item in values:
                if item is None or str(item).strip() == "":
                    continue
                if isinstance(item, str):
                    matched_ids = cls._parse_tracker_item_reference_ids_with_regex(item, pattern=pattern)
                    if len(matched_ids) > 1:
                        resolved_values.extend(
                            {
                                "id": item_id,
                                "type": ReferenceType.TRACKER_ITEM.value,
                            }
                            for item_id in matched_ids
                        )
                        continue
                resolved_values.append(
                    cls._to_tracker_item_reference_payload_with_regex(item, pattern=pattern)
                )
            return resolved_values or None

        return cls._to_tracker_item_reference_payload_with_regex(raw_value, pattern=pattern)
