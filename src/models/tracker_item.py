from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import ClassVar

from .common import DomainModel
from .common import FieldInfo
from .common import PayloadTargetKind
from .common import PreconstructionKind
from .common import ReferenceType
from .common import SchemaFieldType
from .common import _as_list
from .common import _camel_to_snake
from .common import _coerce_bool
from .common import _drop_none
from .common import _stringify_scalar
from .field_values import AbstractFieldValue
from .field_values import _build_field_value
from .references import AbstractReference
from .references import CommentReference
from .references import Label
from .references import TrackerItemReference
from .references import TrackerReference
from .references import UserReference
from .references import _build_reference


@dataclass
class TrackerItemBase(DomainModel):
    """Tracker Item payload를 파이썬 객체로 조립하는 기본 모델이다."""
    NON_CREATABLE_FIELDS: ClassVar[set[str]] = {
        "angular_icon",
        "assigned_at",
        "children",
        "comments",
        "created_at",
        "created_by",
        "icon_color",
        "icon_url",
        "id",
        "modified_at",
        "modified_by",
        "parent",
        "tags",
        "tracker",
        "version",
    }
    CREATE_EXCLUDED_KEYS: ClassVar[set[str]] = {
        "angularIcon",
        "assignedAt",
        "children",
        "comments",
        "createdAt",
        "createdBy",
        "iconColor",
        "iconUrl",
        "id",
        "modifiedAt",
        "modifiedBy",
        "parent",
        "tags",
        "tracker",
        "version",
    }
    REFERENCE_LIST_FIELDS: ClassVar[set[str]] = {
        "areas",
        "assigned_to",
        "categories",
        "platforms",
        "resolutions",
        "severities",
        "subjects",
        "teams",
        "versions",
    }
    REFERENCE_SINGLE_FIELDS: ClassVar[set[str]] = {
        "formality",
        "owners",
        "priority",
        "release_method",
        "status",
    }
    INTEGER_FIELDS: ClassVar[set[str]] = {
        "ordinal",
        "story_points",
        "version",
    }
    STRING_FIELDS: ClassVar[set[str]] = {
        "closed_at",
        "description",
        "description_format",
        "end_date",
        "name",
        "start_date",
        "type_name",
    }
    PAYLOAD_FIELD_MAP: ClassVar[dict[str, str]] = {
        "accrued_millis": "accruedMillis",
        "angular_icon": "angularIcon",
        "areas": "areas",
        "assigned_at": "assignedAt",
        "assigned_to": "assignedTo",
        "categories": "categories",
        "children": "children",
        "closed_at": "closedAt",
        "comments": "comments",
        "created_at": "createdAt",
        "created_by": "createdBy",
        "custom_fields": "customFields",
        "description": "description",
        "description_format": "descriptionFormat",
        "end_date": "endDate",
        "estimated_millis": "estimatedMillis",
        "formality": "formality",
        "icon_color": "iconColor",
        "icon_url": "iconUrl",
        "id": "id",
        "modified_at": "modifiedAt",
        "modified_by": "modifiedBy",
        "name": "name",
        "ordinal": "ordinal",
        "owners": "owners",
        "parent": "parent",
        "platforms": "platforms",
        "priority": "priority",
        "release_method": "releaseMethod",
        "resolutions": "resolutions",
        "severities": "severities",
        "spent_millis": "spentMillis",
        "start_date": "startDate",
        "status": "status",
        "story_points": "storyPoints",
        "subjects": "subjects",
        "tags": "tags",
        "teams": "teams",
        "tracker": "tracker",
        "type_name": "typeName",
        "version": "version",
        "versions": "versions",
    }

    id: int | None = None
    tracker: TrackerReference | None = None

    name: str | None = None
    description: str | None = None
    description_format: str | None = None

    status: AbstractReference | None = None
    priority: AbstractReference | None = None
    categories: list[AbstractReference] | None = None

    subjects: list[TrackerItemReference] = field(default_factory=list)
    children: list[TrackerItemReference] = field(default_factory=list)

    ordinal: int | None = None
    version: int | None = None
    versions: list[AbstractReference] | None = None
    type_name: str | None = None

    custom_fields: list[AbstractFieldValue] = field(default_factory=list)

    modified_at: str | None = None
    modified_by: UserReference | None = None

    owners: AbstractReference | None = None
    parent: TrackerItemReference | None = None

    angular_icon: str | None = None
    assigned_at: list[str] = field(default_factory=list)
    comments: list[CommentReference] = field(default_factory=list)
    created_at: str | None = None
    created_by: UserReference | None = None
    icon_color: str | None = None
    icon_url: str | None = None
    tags: list[Label] = field(default_factory=list)

    accrued_millis: int | None = None
    areas: list[AbstractReference] | None = None
    assigned_to: list[UserReference] | None = None
    closed_at: str | None = None
    end_date: str | None = None
    estimated_millis: int | None = None
    formality: AbstractReference | None = None
    platforms: list[AbstractReference] | None = None
    release_method: AbstractReference | None = None
    resolutions: list[AbstractReference] | None = None
    severities: list[AbstractReference] | None = None
    spent_millis: int | None = None
    start_date: str | None = None
    story_points: int | None = None
    teams: list[AbstractReference] | None = None

    @staticmethod
    def _normalize_tracker_field_name(field_name: str) -> str:
        """schema 필드 이름을 현재 모델 속성 이름과 맞는 표기로 정리한다."""
        if not field_name:
            return field_name
        field_names = TrackerItemBase.__dataclass_fields__
        if field_name in field_names:
            return field_name
        normalized = _camel_to_snake(field_name)
        return normalized if normalized in field_names else field_name

    @classmethod
    def has_builtin_field(cls, field_name: str | None) -> bool:
        """주어진 필드가 TrackerItem의 기본 속성인지 확인한다."""
        if not field_name:
            return False
        normalized = cls._normalize_tracker_field_name(field_name)
        return normalized in cls.__dataclass_fields__

    @staticmethod
    def _reference_type(field_info: FieldInfo | None) -> str | None:
        """field 정보에서 기대하는 reference 타입 이름만 꺼낸다."""
        if not field_info:
            return None
        return field_info.get("reference_type")

    @staticmethod
    def _parse_tracker_item_reference_id(raw_value: Any) -> int:
        """입력값에서 `[]` 안의 첫 번째 정수 또는 전체 정수를 tracker item id로 추출한다."""
        if isinstance(raw_value, bool):
            raise ValueError(f"Cannot parse tracker item id from value: {raw_value!r}")
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, float):
            if raw_value.is_integer():
                return int(raw_value)
            raise ValueError(f"Cannot parse tracker item id from value: {raw_value!r}")
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

    def _to_tracker_item_reference(self, raw_value: Any) -> TrackerItemReference:
        """원본 값을 tracker item reference로 바꾼다."""
        if isinstance(raw_value, TrackerItemReference):
            return raw_value
        if isinstance(raw_value, dict):
            normalized = dict(raw_value)
            normalized.setdefault("type", ReferenceType.TRACKER_ITEM.value)
            return _build_reference(normalized, ReferenceType.TRACKER_ITEM.value)

        item_id = self._parse_tracker_item_reference_id(raw_value)
        return TrackerItemReference(
            id=item_id,
            type=ReferenceType.TRACKER_ITEM.value,
        )

    def _to_reference(self, raw_value: Any, reference_type: str | None = None) -> Any:
        """원본 값을 단일 reference 객체로 바꾼다."""
        if reference_type == ReferenceType.TRACKER_ITEM.value:
            return self._to_tracker_item_reference(raw_value)
        return _build_reference(raw_value, reference_type)

    def _to_reference_list(self, value: Any, field_info: FieldInfo | None = None) -> list[Any]:
        """원본 값을 reference 객체 목록으로 바꾼다."""
        reference_type = self._reference_type(field_info)
        return [self._to_reference(item, reference_type) for item in _as_list(value)]

    def _create_field_value(self, field_info: FieldInfo, value: Any) -> AbstractFieldValue | None:
        """schema 규칙이 요구할 때만 custom field value 객체를 만든다."""
        preconstruction_kind = field_info.get("preconstruction_kind")
        if preconstruction_kind not in {
            PreconstructionKind.FIELD_VALUE.value,
            PreconstructionKind.TABLE_FIELD_VALUE.value,
        }:
            return None
        return _build_field_value(field_info, value)

    def add_field_value(self, field_value: AbstractFieldValue) -> None:
        """만들어진 custom field value를 payload 목록에 추가한다."""
        self.custom_fields.append(field_value)

    def _set_builtin_field(self, tracker_field: str, value: Any, field_info: FieldInfo | None = None) -> bool:
        """기본 필드라면 타입 규칙에 맞춰 값을 넣고 성공 여부를 돌려준다."""
        if not hasattr(self, tracker_field):
            return False

        preconstruction_kind = field_info.get("preconstruction_kind") if field_info else None
        field_type = field_info.get("field_type") if field_info else None

        if (
            preconstruction_kind == PreconstructionKind.REFERENCE_LIST.value
            or tracker_field in self.REFERENCE_LIST_FIELDS
        ):
            setattr(self, tracker_field, self._to_reference_list(value, field_info))
            return True

        if (
            preconstruction_kind == PreconstructionKind.REFERENCE.value
            or tracker_field in self.REFERENCE_SINGLE_FIELDS
        ):
            setattr(self, tracker_field, self._to_reference(value, self._reference_type(field_info)))
            return True

        if tracker_field in self.INTEGER_FIELDS and value is not None:
            setattr(self, tracker_field, int(value))
            return True

        if field_type == SchemaFieldType.BOOL.value and value is not None:
            setattr(self, tracker_field, _coerce_bool(value))
            return True

        if tracker_field in self.STRING_FIELDS and value is not None:
            setattr(self, tracker_field, _stringify_scalar(value))
            return True

        setattr(self, tracker_field, value)
        return True

    def set_field_value(self, tracker_field: str, value: Any, field_info: FieldInfo | None = None) -> None:
        """field 분류 결과를 바탕으로 builtin 또는 custom payload에 값을 반영한다."""
        normalized_field = self._normalize_tracker_field_name(tracker_field)
        payload_target_kind = field_info.get("payload_target_kind") if field_info else None
        unsupported_reason = field_info.get("unsupported_reason") if field_info else None

        if field_info and not field_info.get("is_supported", True):
            detail = f": {unsupported_reason}" if unsupported_reason else ""
            raise ValueError(
                f"Field '{field_info.get('field_name') or tracker_field}' is unsupported for payload generation{detail}"
            )

        if normalized_field in self.NON_CREATABLE_FIELDS:
            return

        if payload_target_kind == PayloadTargetKind.BUILTIN_FIELD.value:
            if self._set_builtin_field(normalized_field, value, field_info):
                return
            field_label = (field_info.get("field_name") if field_info else None) or tracker_field
            raise ValueError(
                f"Field '{field_label}' is marked as builtin but could not be set."
            )

        if payload_target_kind == PayloadTargetKind.CUSTOM_FIELD.value:
            if not field_info:
                raise ValueError(f"Custom field '{tracker_field}' requires schema field info.")
            field_value = self._create_field_value(field_info, value)
            if field_value is None:
                raise ValueError(
                    f"Field '{field_info.get('field_name') or tracker_field}' requires a field value object "
                    f"but no supported builder was found."
                )
            self.add_field_value(field_value)
            return

        if self._set_builtin_field(normalized_field, value, field_info):
            return

        if field_info:
            field_value = self._create_field_value(field_info, value)
            if field_value is not None:
                self.add_field_value(field_value)
                return

        raise ValueError(f"Field '{tracker_field}' could not be mapped to a builtin or custom payload field.")

    def to_dict(self) -> dict[str, Any]:
        """현재 객체를 API 호출에 쓸 수 있는 dict로 직렬화한다."""
        return _drop_none({
            payload_key: getattr(self, attr_name)
            for attr_name, payload_key in self.PAYLOAD_FIELD_MAP.items()
        })

    def to_create_payload(self) -> dict[str, Any]:
        """생성 요청에서 허용되지 않는 읽기 전용 필드를 제거한다."""
        payload = self.to_dict()
        for key in self.CREATE_EXCLUDED_KEYS:
            payload.pop(key, None)
        return payload

    def create_new_item_payload(self) -> dict[str, Any]:
        """새 아이템 생성용 payload를 외부에서 바로 받을 수 있게 돌려준다."""
        return self.to_create_payload()
