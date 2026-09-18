from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import ClassVar

from .common import DomainModel
from .common import FieldInfo
from .common import FieldValueType
from .common import SchemaFieldType
from .common import _as_list
from .common import _coerce_bool
from .common import _drop_none
from .common import _serialize_value
from .common import _stringify_scalar
from .references import _build_reference


@dataclass
class AbstractFieldValue(DomainModel):
    _REGISTRY: ClassVar[list[type[AbstractFieldValue]]] = []
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = ()
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = ()

    field_id: int
    type: str
    field_name: str | None = None

    def __init_subclass__(cls, **kwargs):
        """하위 FieldValue 클래스를 자동 등록해 팩토리에서 찾을 수 있게 한다."""
        super().__init_subclass__(**kwargs)
        if cls is not AbstractFieldValue:
            AbstractFieldValue._REGISTRY.append(cls)

    def to_dict(self) -> dict[str, Any]:
        """필드 값 객체를 Codebeamer payload용 dict로 바꾼다."""
        return _drop_none({
            "fieldId": int(self.field_id),
            "name": self.field_name,
            "type": self.type,
        })

    @classmethod
    def _base_kwargs(cls, field_info: FieldInfo) -> dict[str, Any]:
        """모든 FieldValue가 공통으로 쓰는 기본 생성 인자를 만든다."""
        return {
            "field_id": field_info["field_id"],
            "field_name": field_info.get("field_name"),
        }

    @classmethod
    def matches(cls, field_info: FieldInfo) -> bool:
        """현재 클래스가 이 field 정보를 처리할 수 있는지 판정한다."""
        value_model = field_info.get("value_model")
        field_type = field_info.get("field_type")
        return (
            value_model in cls.VALUE_MODEL_ALIASES
            or field_type in cls.FIELD_TYPE_ALIASES
        )

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> AbstractFieldValue:
        """입력값을 현재 FieldValue 클래스 인스턴스로 바꾼다."""
        return cls(**cls._base_kwargs(field_info), type=cls.__name__)

    @classmethod
    def resolve_class(cls, field_info: FieldInfo) -> type[AbstractFieldValue]:
        """field 정보에 맞는 구체 FieldValue 클래스를 선택한다."""
        for candidate in cls._REGISTRY:
            if candidate.matches(field_info):
                return candidate

        value_model = field_info.get("value_model")
        if isinstance(value_model, str) and value_model.endswith("FieldValue"):
            return ScalarFieldValue
        return TextFieldValue


@dataclass
class ChoiceFieldValue(AbstractFieldValue):
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (
        SchemaFieldType.MEMBER.value,
        SchemaFieldType.OPTION_CHOICE.value,
        SchemaFieldType.REFERENCE.value,
        SchemaFieldType.TRACKER_ITEM_CHOICE.value,
        SchemaFieldType.USER_CHOICE.value,
    )

    values: list[Any] = field(default_factory=list)
    type: str = FieldValueType.CHOICE.value

    def to_dict(self) -> dict[str, Any]:
        """선택형 필드 값을 직렬화하고 선택된 항목 목록을 포함한다."""
        data = super().to_dict()
        if self.values:
            data["values"] = _serialize_value(self.values)
        return data

    @classmethod
    def matches(cls, field_info: FieldInfo) -> bool:
        """choice 계열 valueModel을 가진 필드인지 확인한다."""
        value_model = field_info.get("value_model")
        return isinstance(value_model, str) and FieldValueType.CHOICE.value in value_model

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> ChoiceFieldValue:
        """입력값을 reference 목록으로 바꿔 선택형 필드 값 객체를 만든다."""
        reference_type = field_info.get("reference_type")
        values = [] if value is None else _as_list(value)
        return cls(
            **cls._base_kwargs(field_info),
            values=[_build_reference(item, reference_type) for item in values],
        )


@dataclass
class TextFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.TEXT.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.TEXT.value,)

    value: str | None = None
    type: str = FieldValueType.TEXT.value

    def to_dict(self) -> dict[str, Any]:
        """텍스트 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> TextFieldValue:
        """입력값을 문자열로 바꿔 텍스트 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_stringify_scalar(value),
        )


@dataclass
class ColorFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.COLOR.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.COLOR.value,)

    value: str | None = None
    type: str = FieldValueType.COLOR.value

    def to_dict(self) -> dict[str, Any]:
        """색상 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> ColorFieldValue:
        """입력값을 문자열로 보존해 색상 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_stringify_scalar(value),
        )


@dataclass
class CountryFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.COUNTRY.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.COUNTRY.value,)

    value: str | None = None
    type: str = FieldValueType.COUNTRY.value

    def to_dict(self) -> dict[str, Any]:
        """국가 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> CountryFieldValue:
        """입력값을 문자열로 보존해 국가 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_stringify_scalar(value),
        )


@dataclass
class LanguageFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.LANGUAGE.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.LANGUAGE.value,)

    value: str | None = None
    type: str = FieldValueType.LANGUAGE.value

    def to_dict(self) -> dict[str, Any]:
        """언어 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> LanguageFieldValue:
        """입력값을 문자열로 보존해 언어 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_stringify_scalar(value),
        )


@dataclass
class WikiTextFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.WIKI_TEXT.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.WIKI_TEXT.value,)

    value: str | None = None
    type: str = FieldValueType.WIKI_TEXT.value

    def to_dict(self) -> dict[str, Any]:
        """위키 텍스트 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> WikiTextFieldValue:
        """입력값을 문자열로 바꿔 위키 텍스트 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_stringify_scalar(value),
        )


@dataclass
class TableFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.TABLE.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.TABLE.value,)

    values: list[list[Any]] = field(default_factory=list)
    type: str = FieldValueType.TABLE.value

    def to_dict(self) -> dict[str, Any]:
        """테이블 필드의 행/열 데이터를 직렬화한다."""
        data = super().to_dict()
        if self.values:
            data["values"] = _serialize_value(self.values)
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> TableFieldValue:
        """입력값을 테이블 형태로 감싸 `TableFieldValue`로 만든다."""
        if isinstance(value, TableFieldValue):
            return value

        table_values = value if isinstance(value, list) else [[value]]

        return cls(
            **cls._base_kwargs(field_info),
            values=table_values,
        )


@dataclass
class BoolFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.BOOL.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.BOOL.value,)

    value: bool = False
    type: str = FieldValueType.BOOL.value

    def to_dict(self) -> dict[str, Any]:
        """불린 필드 값을 직렬화한다."""
        data = super().to_dict()
        data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> BoolFieldValue:
        """입력값을 True/False로 바꿔 불린 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_coerce_bool(value),
        )


@dataclass
class IntegerFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.INTEGER.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.INTEGER.value,)

    value: int | None = None
    type: str = FieldValueType.INTEGER.value

    def to_dict(self) -> dict[str, Any]:
        """정수 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> IntegerFieldValue:
        """입력값을 정수로 바꿔 정수 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=int(value) if value is not None else None,
        )


@dataclass
class DecimalFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.DECIMAL.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.DECIMAL.value,)

    value: float | None = None
    type: str = FieldValueType.DECIMAL.value

    def to_dict(self) -> dict[str, Any]:
        """소수 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> DecimalFieldValue:
        """입력값을 소수로 바꿔 소수 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=float(value) if value is not None else None,
        )


@dataclass
class DurationFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.DURATION.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.DURATION.value,)

    value: int | None = None
    type: str = FieldValueType.DURATION.value

    def to_dict(self) -> dict[str, Any]:
        """기간 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> DurationFieldValue:
        """입력값을 정수 기간값으로 바꿔 기간 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=int(value) if value is not None else None,
        )


@dataclass
class DateFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.DATE.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.DATE.value,)

    value: str | None = None
    type: str = FieldValueType.DATE.value

    def to_dict(self) -> dict[str, Any]:
        """날짜 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> DateFieldValue:
        """입력값을 문자열로 보존해 날짜 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_stringify_scalar(value),
        )


@dataclass
class UrlFieldValue(AbstractFieldValue):
    VALUE_MODEL_ALIASES: ClassVar[tuple[str, ...]] = (FieldValueType.URL.value,)
    FIELD_TYPE_ALIASES: ClassVar[tuple[str, ...]] = (SchemaFieldType.URL.value,)

    value: str | None = None
    type: str = FieldValueType.URL.value

    def to_dict(self) -> dict[str, Any]:
        """URL 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> UrlFieldValue:
        """입력값을 문자열로 바꿔 URL 필드 값 객체를 만든다."""
        return cls(
            **cls._base_kwargs(field_info),
            value=_stringify_scalar(value),
        )


@dataclass
class ScalarFieldValue(AbstractFieldValue):
    value: Any = None
    type: str = FieldValueType.TEXT.value

    def to_dict(self) -> dict[str, Any]:
        """별도 전용 클래스가 없는 단순 필드 값을 직렬화한다."""
        data = super().to_dict()
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_value(cls, field_info: FieldInfo, value: Any) -> ScalarFieldValue:
        """입력값을 그대로 담는 일반용 필드 값 객체를 만든다."""
        value_model = field_info.get("value_model") or FieldValueType.TEXT.value
        return cls(
            **cls._base_kwargs(field_info),
            value=value,
            type=value_model,
        )


def _build_field_value(field_info: FieldInfo, value: Any) -> AbstractFieldValue | None:
    """field 정보에 맞는 FieldValue 클래스를 골라 실제 객체를 만든다."""
    field_value_cls = AbstractFieldValue.resolve_class(field_info)
    return field_value_cls.from_value(field_info, value)
