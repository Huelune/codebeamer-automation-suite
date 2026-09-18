from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields
from typing import Any

from .common import DomainModel
from .common import _drop_none
from .references import UserReference


@dataclass
class UserInfo(DomainModel):
    id: int
    name: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    email: str | None = None
    title: str | None = None
    company: str | None = None
    address: str | None = None
    zip: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    dateFormat: str | None = None
    timeZone: str | None = None
    language: str | None = None
    phone: str | None = None
    skills: Any = None
    registryDate: str | None = None
    lastLoginDate: str | None = None
    status: str | None = None
    mobile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """사용자 정보를 최소 reference 형태로 축약한다."""
        return _drop_none({
            "id": self.id,
            "name": self.name,
            "type": "UserReference",
        })

    @classmethod
    def from_raw(cls, raw_value: dict[str, Any]) -> UserInfo:
        """서버에서 받은 사용자 JSON을 `UserInfo` 객체로 바꾼다."""
        init_kwargs: dict[str, Any] = {}
        for field_info in fields(cls):
            if field_info.name in raw_value:
                init_kwargs[field_info.name] = raw_value[field_info.name]
        return cls(**init_kwargs)

    def to_reference(self) -> UserReference:
        """상세 사용자 정보를 간단한 사용자 참조 객체로 축약한다."""
        return UserReference(
            id=self.id,
            name=self.name,
        )
