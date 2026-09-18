from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields
from typing import Any
from typing import ClassVar

from .common import DomainModel
from .common import ReferenceType
from .common import _drop_none


@dataclass
class BaseReference(DomainModel):
    TYPE_NAME: ClassVar[str | None] = None
    _TYPE_REGISTRY: ClassVar[dict[str, type[BaseReference]]] = {}

    id: int
    name: str | None = None
    type: str | None = None

    def __init_subclass__(cls, **kwargs):
        """하위 reference 클래스를 타입 이름 기준 레지스트리에 자동 등록한다."""
        super().__init_subclass__(**kwargs)
        if cls.TYPE_NAME:
            BaseReference._TYPE_REGISTRY[cls.TYPE_NAME] = cls

    def to_dict(self) -> dict[str, Any]:
        """reference 객체를 API가 기대하는 최소 dict 구조로 바꾼다."""
        return _drop_none({
            "id": self.id,
            "name": self.name,
            "type": self.type,
        })

    @classmethod
    def from_raw(
        cls,
        raw_value: dict[str, Any],
        reference_type: str | None = None,
    ) -> BaseReference:
        """원본 dict를 현재 reference 클래스 인스턴스로 만든다."""
        resolved_type = raw_value.get("type") or reference_type or cls.TYPE_NAME
        init_kwargs: dict[str, Any] = {}

        for field_info in fields(cls):
            if not field_info.init:
                continue
            if field_info.name == "type":
                init_kwargs["type"] = resolved_type
                continue
            if field_info.name in raw_value:
                init_kwargs[field_info.name] = raw_value[field_info.name]

        return cls(**init_kwargs)

    @classmethod
    def resolve_type(cls, reference_type: str | None) -> type[BaseReference]:
        """type 문자열에 맞는 reference 클래스를 찾아준다."""
        if reference_type in {None, ReferenceType.ABSTRACT.value}:
            return AbstractReference
        return cls._TYPE_REGISTRY.get(reference_type, BaseReference)


@dataclass
class AbstractReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.ABSTRACT.value
    type: str = ReferenceType.ABSTRACT.value


@dataclass
class ChoiceOptionReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.CHOICE_OPTION.value
    type: str = ReferenceType.CHOICE_OPTION.value


@dataclass
class CommentReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.COMMENT.value
    type: str = ReferenceType.COMMENT.value


@dataclass
class GroupReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.GROUP.value
    type: str = ReferenceType.GROUP.value


@dataclass
class ProjectReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.PROJECT.value
    type: str = ReferenceType.PROJECT.value


@dataclass
class RepositoryReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.REPOSITORY.value
    type: str = ReferenceType.REPOSITORY.value


@dataclass
class RoleReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.ROLE.value
    type: str = ReferenceType.ROLE.value


@dataclass
class TrackerPermissionReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.TRACKER_PERMISSION.value
    type: str = ReferenceType.TRACKER_PERMISSION.value


@dataclass
class UserReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.USER.value
    type: str = ReferenceType.USER.value
    email: str | None = None


@dataclass
class UserGroupReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.USER_GROUP.value
    type: str = ReferenceType.USER_GROUP.value


@dataclass
class TrackerItemReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.TRACKER_ITEM.value
    type: str = ReferenceType.TRACKER_ITEM.value


@dataclass
class TrackerReference(BaseReference):
    TYPE_NAME: ClassVar[str] = ReferenceType.TRACKER.value
    type: str = ReferenceType.TRACKER.value


@dataclass
class Label(DomainModel):
    id: int
    name: str | None = None
    createdAt: str | None = None
    createdBy: UserReference | None = None
    hidden: bool | None = None
    privateLabel: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """라벨 객체를 직렬화해 payload에 넣을 수 있게 만든다."""
        return _drop_none({
            "id": self.id,
            "name": self.name,
            "createdAt": self.createdAt,
            "createdBy": self.createdBy,
            "hidden": self.hidden,
            "privateLabel": self.privateLabel,
        })


def _build_reference(raw_value: Any, reference_type: str | None = None) -> Any:
    """dict 또는 모델 값을 알맞은 reference 객체로 정리한다."""
    if isinstance(raw_value, DomainModel):
        return raw_value
    if not isinstance(raw_value, dict):
        return raw_value

    resolved_type = raw_value.get("type") or reference_type
    reference_cls = BaseReference.resolve_type(resolved_type)
    return reference_cls.from_raw(raw_value, reference_type=resolved_type)
