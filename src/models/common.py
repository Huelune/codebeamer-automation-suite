from __future__ import annotations

import math
import re
from enum import Enum
from typing import Any


FieldInfo = dict[str, Any]


class DescriptionFormat(str, Enum):
    PlainText = "PlainText"
    Html = "Html"
    Wiki = "Wiki"


class ReferenceType(str, Enum):
    ABSTRACT = "AbstractReference"
    CHOICE_OPTION = "ChoiceOptionReference"
    COMMENT = "CommentReference"
    GROUP = "GroupReference"
    PROJECT = "ProjectReference"
    REPOSITORY = "RepositoryReference"
    ROLE = "RoleReference"
    TRACKER = "TrackerReference"
    TRACKER_ITEM = "TrackerItemReference"
    TRACKER_PERMISSION = "TrackerPermissionReference"
    USER = "UserReference"
    USER_GROUP = "UserGroupReference"


class FieldValueType(str, Enum):
    BOOL = "BoolFieldValue"
    CHOICE = "ChoiceFieldValue"
    COLOR = "ColorFieldValue"
    COUNTRY = "CountryFieldValue"
    DATE = "DateFieldValue"
    DECIMAL = "DecimalFieldValue"
    DURATION = "DurationFieldValue"
    INTEGER = "IntegerFieldValue"
    LANGUAGE = "LanguageFieldValue"
    TABLE = "TableFieldValue"
    TEXT = "TextFieldValue"
    URL = "UrlFieldValue"
    WIKI_TEXT = "WikiTextFieldValue"


class SchemaFieldType(str, Enum):
    BOOL = "BoolField"
    COLOR = "ColorField"
    COUNTRY = "CountryField"
    DATE = "DateField"
    DECIMAL = "DecimalField"
    DURATION = "DurationField"
    INTEGER = "IntegerField"
    MEMBER = "MemberField"
    LANGUAGE = "LanguageField"
    OPTION_CHOICE = "OptionChoiceField"
    REFERENCE = "ReferenceField"
    TABLE = "TableField"
    TEXT = "TextField"
    TRACKER_ITEM_CHOICE = "TrackerItemChoiceField"
    URL = "UrlField"
    USER_CHOICE = "UserChoiceField"
    WIKI_TEXT = "WikiTextField"


CONNECTED_FIELD_TYPE_VALUE_MODEL_MAP: dict[str, str] = {
    SchemaFieldType.BOOL.value: FieldValueType.BOOL.value,
    SchemaFieldType.COLOR.value: FieldValueType.COLOR.value,
    SchemaFieldType.COUNTRY.value: FieldValueType.COUNTRY.value,
    SchemaFieldType.DATE.value: FieldValueType.DATE.value,
    SchemaFieldType.DECIMAL.value: FieldValueType.DECIMAL.value,
    SchemaFieldType.DURATION.value: FieldValueType.DURATION.value,
    SchemaFieldType.INTEGER.value: FieldValueType.INTEGER.value,
    SchemaFieldType.MEMBER.value: FieldValueType.CHOICE.value,
    SchemaFieldType.LANGUAGE.value: FieldValueType.LANGUAGE.value,
    SchemaFieldType.OPTION_CHOICE.value: FieldValueType.CHOICE.value,
    SchemaFieldType.REFERENCE.value: FieldValueType.CHOICE.value,
    SchemaFieldType.TABLE.value: FieldValueType.TABLE.value,
    SchemaFieldType.TEXT.value: FieldValueType.TEXT.value,
    SchemaFieldType.TRACKER_ITEM_CHOICE.value: FieldValueType.CHOICE.value,
    SchemaFieldType.URL.value: FieldValueType.URL.value,
    SchemaFieldType.USER_CHOICE.value: FieldValueType.CHOICE.value,
    SchemaFieldType.WIKI_TEXT.value: FieldValueType.WIKI_TEXT.value,
}
"""현재 코드에 실제로 구현체가 있어 로직에 연결한 schema field -> field value 매핑이다.

Swagger V3 상속/추상 모델 문서 기준으로 AbstractFieldValue 구현체가 확인되고,
현재 코드베이스에도 실제 FieldValue 클래스가 있는 항목만 여기에 둔다.
"""


TODO_FIELD_TYPE_VALUE_MODEL_MAP: dict[str, str | tuple[str, ...] | None] = {
    # TODO: 아래 field 들은 공식 문서에서 AbstractFieldValue 구현체가 확인되므로
    # single-value 형태는 우선 연결했다. multi-value 또는 세부 coercion 규칙은 추가 확인이 필요하다.
    "CountryField": ("CountryFieldValue", "CountryFieldMultiValue"),
    "LanguageField": ("LanguageFieldValue", "LanguageFieldMultiValue"),
    "LayoutField": None,
    # TODO: 아래 choice/reference 계열은 OptionChoiceField와 UserChoiceField를 제외하고
    # schema 예시를 더 확인한 뒤 referenceType, multipleValues, valueModel 조합으로 연결한다.
    "ProjectChoiceField": None,
    "RepositoryChoiceField": None,
    "ReviewMemberReferenceField": None,
    "TrackerChoiceField": None,
    "TrackerField": None,
    "TrackerItemField": None,
    "UpdateTrackerItemField": None,
    "UpdateTrackerItemTableField": None,
    # TODO: UrlField / WikiTextField 는 single-value 구현만 우선 반영했다.
    "WikiTextField": ("WikiTextFieldValue", "WikiTextFieldMultiValue"),
}
"""다음 단계에서 구현할 field/value 연결 후보 목록이다.

- 값이 문자열이면 예상되는 FieldValue 이름이다.
- 값이 tuple이면 single/multi value 분기가 필요하다.
- 값이 None이면 아직 payload 규칙을 확정하지 못한 field다.
"""


class ResolvedFieldKind(str, Enum):
    MEMBER_REFERENCE = "member_reference"
    SCALAR_TEXT = "scalar_text"
    SCALAR_BOOL = "scalar_bool"
    STATIC_OPTION = "static_option"
    TRACKER_ITEM_REFERENCE = "tracker_item_reference"
    USER_REFERENCE = "user_reference"
    GENERIC_REFERENCE = "generic_reference"
    TABLE = "table"
    UNSUPPORTED = "unsupported"


class ResolutionStrategy(str, Enum):
    BUILTIN_SCALAR = "builtin_scalar"
    CUSTOM_SCALAR = "custom_scalar"
    TYPE_BOOL = "type_bool"
    TYPE_MEMBER = "type_member"
    TYPE_TABLE = "type_table"
    TYPE_OPTION_WITH_OPTIONS = "type_option_with_options"
    TYPE_TRACKER_ITEM_CHOICE = "type_tracker_item_choice"
    TYPE_OPTION_WITH_USER_REFERENCE = "type_option_with_user_reference"
    TYPE_OPTION_WITH_REFERENCE_TYPE = "type_option_with_reference_type"
    TYPE_OPTION_AMBIGUOUS = "type_option_ambiguous"
    TYPE_REFERENCE_WITH_USER_REFERENCE = "type_reference_with_user_reference"
    TYPE_REFERENCE_WITH_REFERENCE_TYPE = "type_reference_with_reference_type"
    TYPE_REFERENCE_WITHOUT_REFERENCE_TYPE = "type_reference_without_reference_type"
    UNKNOWN_TYPE = "unknown_type"


class LookupTargetKind(str, Enum):
    MEMBER = "member"
    NONE = "none"
    USER = "user"
    REFERENCE = "reference"


class PreconstructionKind(str, Enum):
    NONE = "none"
    BUILTIN_DIRECT = "builtin_direct"
    FIELD_VALUE = "field_value"
    REFERENCE = "reference"
    REFERENCE_LIST = "reference_list"
    TABLE_FIELD_VALUE = "table_field_value"


class PayloadTargetKind(str, Enum):
    BUILTIN_FIELD = "builtin_field"
    CUSTOM_FIELD = "custom_field"
    UNSUPPORTED = "unsupported"


class OptionSourceKind(str, Enum):
    DIRECT_PARSE = "direct_parse"
    SCHEMA_OPTIONS = "schema_options"
    REFERENCE_LOOKUP = "reference_lookup"
    UNSUPPORTED = "unsupported"


class OptionMapKind(str, Enum):
    MEMBER_LOOKUP = "member_lookup"
    TRACKER_ITEM_DIRECT = "tracker_item_direct"
    STATIC_OPTIONS = "static_options"
    USER_LOOKUP = "user_lookup"
    REFERENCE_LOOKUP = "reference_lookup"
    UNSUPPORTED = "unsupported"


class OptionSourceStatus(str, Enum):
    READY = "READY"
    LOOKUP_REQUIRED = "LOOKUP_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


class MappingStatus(str, Enum):
    OK = "OK"
    SCHEMA_FIELD_MISSING = "SCHEMA_FIELD_MISSING"
    UNMAPPED = "UNMAPPED"


class OptionCheckStatus(str, Enum):
    DF_COLUMN_MISSING = "DF_COLUMN_MISSING"
    DIRECT_PARSE_FAILED = "DIRECT_PARSE_FAILED"
    FIELD_UNSUPPORTED = "FIELD_UNSUPPORTED"
    LOOKUP_REQUIRED = "LOOKUP_REQUIRED"
    OPTION_MAP_MISSING = "OPTION_MAP_MISSING"
    OPTION_NOT_FOUND = "OPTION_NOT_FOUND"
    OPTION_SOURCE_UNAVAILABLE = "OPTION_SOURCE_UNAVAILABLE"
    PRECONSTRUCTION_REQUIRED = "PRECONSTRUCTION_REQUIRED"
    TRACKER_ITEM_LOOKUP_NOT_FOUND = "TRACKER_ITEM_LOOKUP_NOT_FOUND"
    TRACKER_ITEM_LOOKUP_AMBIGUOUS = "TRACKER_ITEM_LOOKUP_AMBIGUOUS"
    TRACKER_ITEM_REGEX_MISSING = "TRACKER_ITEM_REGEX_MISSING"


class TrackerItemResolutionMode(str, Enum):
    REGEX = "regex"
    QUERY = "query"


class TrackerItemQueryMatchStrategy(str, Enum):
    FIRST = "first"
    LAST = "last"
    BEST = "best"
    ERROR = "error"


class UserLookupStatus(str, Enum):
    MEMBER_LOOKUP_AMBIGUOUS = "MEMBER_LOOKUP_AMBIGUOUS"
    MEMBER_LOOKUP_FAILED = "MEMBER_LOOKUP_FAILED"
    MEMBER_NOT_FOUND = "MEMBER_NOT_FOUND"
    RESOLVED = "RESOLVED"
    USER_LOOKUP_AMBIGUOUS = "USER_LOOKUP_AMBIGUOUS"
    USER_LOOKUP_FAILED = "USER_LOOKUP_FAILED"
    USER_LOOKUP_NOT_RUN = "USER_LOOKUP_NOT_RUN"
    USER_NOT_FOUND = "USER_NOT_FOUND"


class PayloadStatus(str, Enum):
    READY = "PAYLOAD_READY"
    FAILED = "PAYLOAD_FAILED"


class UploadStatus(str, Enum):
    SUCCESS = "UPLOAD_SUCCESS"
    FAILED = "UPLOAD_FAILED"
    UNRESOLVED_PARENT = "UNRESOLVED_PARENT"


class TrackerItemField(str, Enum):
    STATUS = "status"


class TrackerSchemaName(str, Enum):
    STATUS = "Status"


OPTION_CONTAINER_KEYS: tuple[str, ...] = ("items", "options", "references", "values")
USER_SEARCH_RESULT_KEYS: tuple[str, ...] = ("users", "userRefs", "items", "references", "content")
ITEM_SEARCH_RESULT_KEYS: tuple[str, ...] = ("items", "itemRefs", "references", "content")


class DomainModel:
    def to_dict(self) -> dict[str, Any]:
        """각 모델이 스스로를 dict로 바꾸도록 강제하는 공통 규약이다."""
        raise NotImplementedError


def _normalize_scalar_value(value: Any) -> Any:
    """payload에서 다루기 어려운 결측값만 정리하고 나머지 원래 값은 보존한다."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _stringify_scalar(value: Any) -> str | None:
    """문자열 필드 직렬화 전에 결측값만 정리하고 원래 표현은 유지한다."""
    normalized = _normalize_scalar_value(value)
    if normalized is None:
        return None
    return str(normalized)


def _serialize_value(value: Any) -> Any:
    """중첩된 모델 객체를 재귀적으로 일반 dict/list 값으로 바꾼다."""
    if isinstance(value, DomainModel):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    """값이 비어 있는 항목을 빼서 API payload를 간단하게 만든다."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        result[key] = _serialize_value(value)
    return result


def _camel_to_snake(name: str) -> str:
    """카멜 표기 이름을 파이썬에서 쓰기 쉬운 스네이크 표기로 바꾼다."""
    if not name:
        return name
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _as_list(value: Any) -> list[Any]:
    """단일 값도 항상 목록처럼 다룰 수 있게 감싼다."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _coerce_bool(value: Any) -> bool:
    """문자열이나 불린 값을 실제 True/False로 통일한다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    raise ValueError(f"Cannot convert value to bool: {value}")
