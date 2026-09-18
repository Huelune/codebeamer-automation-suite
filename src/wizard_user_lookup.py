from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

import pandas as pd

from .models import GroupReference
from .models import OptionMapKind
from .models import ReferenceType
from .models import RoleReference
from .models import UserGroupReference
from .models import UserInfo
from .models import UserLookupStatus


UserLookupCacheEntry = tuple[dict[str, Any] | None, dict[str, Any] | None, str, str | None]
MemberLookupCacheEntry = tuple[dict[str, Any] | None, dict[str, Any] | None, str, str | None]



if TYPE_CHECKING:
    from .codebeamer_client import CodebeamerClient
    from .models import WizardState

class WizardUserLookupMixin:
    # 조립된 뒤 사용할 속성의 타입 선언이다. 실제 값은
    # `CodebeamerUploadWizard.__init__` 이 채우므로 여기서는 선언만 둔다.
    client: CodebeamerClient
    state: WizardState

    @staticmethod
    def _normalize_lookup_text(value: Any) -> str:
        """lookup에 쓸 값을 공백 없는 문자열로 정리한다."""
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _http_status_code(exc: Exception) -> int | None:
        """예외 안에 담긴 HTTP 상태 코드를 안전하게 꺼낸다."""
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None)

    @staticmethod
    def _response_json(exc: Exception) -> Any:
        """예외 안의 HTTP 응답 JSON을 안전하게 꺼낸다."""
        response = getattr(exc, "response", None)
        if response is None:
            return None
        try:
            return response.json()
        except Exception:
            return None

    def _user_lookup_cache_key(self, value: Any) -> tuple[int | None, str]:
        """현재 프로젝트 기준으로 사용자 lookup 캐시 키를 만든다."""
        return (self.state.project_id, self._normalize_lookup_text(value).casefold())

    @classmethod
    def _user_lookup_aliases(cls, user_info: dict[str, Any] | None) -> set[str]:
        """한 사용자를 다시 찾기 쉬우도록 이름과 ID를 별칭으로 만든다."""
        if not user_info:
            return set()

        return {
            normalized.casefold()
            for value in [
                user_info.get("id"),
                user_info.get("name"),
            ]
            if (normalized := cls._normalize_lookup_text(value))
        }

    def _cache_user_lookup_entry(
        self,
        lookup_text: str,
        entry: UserLookupCacheEntry,
    ) -> UserLookupCacheEntry:
        """사용자 lookup 결과를 원래 입력값과 별칭 키 모두에 저장한다."""
        cache_key = self._user_lookup_cache_key(lookup_text)
        self.state.user_lookup_cache[cache_key] = entry

        resolved, user_info, _, _ = entry
        if resolved is not None and user_info is not None:
            for alias in self._user_lookup_aliases(user_info):
                self.state.user_lookup_cache[(self.state.project_id, alias)] = entry

        return entry

    @classmethod
    def _parse_user_id(cls, raw_value: Any) -> int | None:
        """사용자 lookup 입력이 숫자 문자열이면 정수 ID로 해석한다."""
        lookup_text = cls._normalize_lookup_text(raw_value)
        if not lookup_text:
            return None
        if lookup_text.isdigit():
            return int(lookup_text)
        return None

    @staticmethod
    def _to_user_reference(candidate: UserInfo) -> dict[str, Any]:
        """사용자 상세 객체를 업로드용 사용자 참조 dict로 바꾼다."""
        reference = candidate.to_reference()
        reference.type = ReferenceType.USER.value
        return reference.to_dict()

    def _lookup_user_reference(
        self,
        raw_value: Any,
    ) -> UserLookupCacheEntry:
        """사용자 이름을 우선 사용하고 필요시 ID로 fallback 하여 reference와 상세 정보를 돌려준다."""
        lookup_text = self._normalize_lookup_text(raw_value)
        cache_key = self._user_lookup_cache_key(lookup_text)
        if cache_key in self.state.user_lookup_cache:
            return self.state.user_lookup_cache[cache_key]

        try:
            if not lookup_text:
                raise ValueError("user lookup text is empty")

            try:
                direct_match = self.client.get_user_by_name(lookup_text)
            except Exception as exc:
                if self._http_status_code(exc) != 404:
                    raise
                direct_match = None

            if direct_match is None:
                user_id = self._parse_user_id(raw_value)
                if user_id is not None:
                    try:
                        direct_match = self.client.get_user(user_id)
                    except Exception as exc:
                        if self._http_status_code(exc) != 404:
                            raise
                        direct_match = None

            if direct_match is not None:
                resolved = self._to_user_reference(direct_match)
                user_info = direct_match.to_dict()
                return self._cache_user_lookup_entry(
                    lookup_text,
                    (resolved, user_info, UserLookupStatus.RESOLVED.value, None),
                )

            return self._cache_user_lookup_entry(
                lookup_text,
                (None, None, UserLookupStatus.USER_NOT_FOUND.value, None),
            )
        except Exception as exc:
            error_message = ""
            if hasattr(exc, "response") and exc.response is not None:
                try:
                    error_message = str(exc.response.json())
                except Exception:
                    error_message = str(exc)
            else:
                error_message = str(exc)
            return self._cache_user_lookup_entry(
                lookup_text,
                (None, None, UserLookupStatus.USER_LOOKUP_FAILED.value, error_message),
            )

    def _member_lookup_cache_key(
        self,
        field_id: int | None,
        lookup_text: Any,
    ) -> tuple[int | None, int | None, int | None, str]:
        """MemberField lookup 결과 캐시 키를 만든다."""
        return (
            self.state.project_id,
            self.state.tracker_id,
            field_id,
            self._normalize_lookup_text(lookup_text).casefold(),
        )

    @classmethod
    def _reference_payload_to_info(cls, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        """reference payload를 lookup 결과 정보 형태로 정리한다."""
        if payload is None:
            return None
        return {
            "id": payload.get("id"),
            "name": payload.get("name"),
            "type": payload.get("type"),
        }

    @staticmethod
    def _normalize_member_name_key(value: Any) -> str:
        """role/group 이름 비교용 정규화 키를 만든다."""
        if value is None:
            return ""
        return str(value).strip().casefold()

    @staticmethod
    def _extract_group_references(data: Any) -> list[dict[str, Any]]:
        """사용자 그룹 목록 응답에서 그룹 reference 후보를 평탄화한다."""
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("groups", "groupReferences", "items", "references"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_role_references(permission_matrix: Any) -> list[dict[str, Any]]:
        """field permission matrix에서 RoleReference 목록을 추출한다."""
        roles: dict[int, dict[str, Any]] = {}
        if not isinstance(permission_matrix, list):
            return []
        for status_row in permission_matrix:
            if not isinstance(status_row, dict):
                continue
            permissions = status_row.get("permissions") or []
            for permission_row in permissions:
                if not isinstance(permission_row, dict):
                    continue
                role = permission_row.get("role")
                if not isinstance(role, dict):
                    continue
                if role.get("id") is None:
                    continue
                normalized = dict(role)
                normalized.setdefault("type", ReferenceType.ROLE.value)
                roles[int(normalized["id"])] = normalized
        return list(roles.values())

    def _group_candidates(self) -> dict[str, list[dict[str, Any]]]:
        """전체 그룹 후보를 이름 키로 캐시한다."""
        cached = self.state.group_lookup_cache
        if cached:
            return cached

        grouped: dict[str, list[dict[str, Any]]] = {}
        for raw in self._extract_group_references(self.client.get_user_groups()):
            ref_type = raw.get("type") or ReferenceType.USER_GROUP.value
            key = self._normalize_member_name_key(raw.get("name"))
            if not key or raw.get("id") is None:
                continue
            grouped.setdefault(f"GROUP:{key}", []).append({
                "id": raw.get("id"),
                "name": raw.get("name"),
                "type": ref_type,
            })

        self.state.group_lookup_cache = grouped
        return grouped

    def _tracker_role_candidates(self, field_id: int | None) -> dict[str, list[dict[str, Any]]]:
        """현재 트래커/필드 기준 role 후보를 이름 키로 캐시한다."""
        if self.state.project_id is None or self.state.tracker_id is None or field_id is None:
            return {}
        cache_key = (self.state.project_id, self.state.tracker_id, int(field_id))
        cached = self.state.tracker_role_cache.get(cache_key)
        if cached is not None:
            return cached

        grouped: dict[str, list[dict[str, Any]]] = {}
        for role in self._extract_role_references(
            self.client.get_tracker_field_permissions(self.state.tracker_id, int(field_id))
        ):
            key = self._normalize_member_name_key(role.get("name"))
            if not key:
                continue
            grouped.setdefault(f"ROLE:{key}", []).append({
                "id": role.get("id"),
                "name": role.get("name"),
                "type": role.get("type") or ReferenceType.ROLE.value,
            })

        self.state.tracker_role_cache[cache_key] = grouped
        return grouped

    def _build_member_reference(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """member lookup 후보를 업로드용 reference payload로 정리한다."""
        ref_type = candidate.get("type") or ReferenceType.ABSTRACT.value
        if ref_type == ReferenceType.USER.value:
            return UserInfo(id=int(candidate["id"]), name=candidate.get("name")).to_reference().to_dict()
        if ref_type == ReferenceType.ROLE.value:
            return RoleReference(
                id=int(candidate["id"]), name=candidate.get("name"), type=ReferenceType.ROLE.value
            ).to_dict()
        if ref_type in {ReferenceType.GROUP.value, ReferenceType.USER_GROUP.value}:
            if ref_type == ReferenceType.GROUP.value:
                return GroupReference(
                    id=int(candidate["id"]),
                    name=candidate.get("name"),
                    type=ReferenceType.GROUP.value,
                ).to_dict()
            return UserGroupReference(
                id=int(candidate["id"]),
                name=candidate.get("name"),
                type=ReferenceType.USER_GROUP.value,
            ).to_dict()
        return {
            "id": int(candidate["id"]),
            "name": candidate.get("name"),
            "type": ref_type,
        }

    def _lookup_member_reference(
        self,
        raw_value: Any,
        *,
        field_id: int | None,
        member_types: list[str] | None,
    ) -> MemberLookupCacheEntry:
        """MemberField 값을 USER/ROLE/GROUP 후보에서 이름 기준으로 찾는다."""
        lookup_text = self._normalize_lookup_text(raw_value)
        cache_key = self._member_lookup_cache_key(field_id, lookup_text)
        if cache_key in self.state.member_lookup_cache:
            return self.state.member_lookup_cache[cache_key]

        try:
            if not lookup_text:
                raise ValueError("member lookup text is empty")

            allowed_types = [
                str(member_type).strip().upper() for member_type in (member_types or []) if str(member_type).strip()
            ]
            if not allowed_types:
                allowed_types = ["USER"]

            matches: list[dict[str, Any]] = []

            if "USER" in allowed_types:
                user_resolved, _user_info, user_status, user_error = self._lookup_user_reference(lookup_text)
                if user_resolved is not None and user_status == UserLookupStatus.RESOLVED.value:
                    matches.append(user_resolved)
                elif user_error and user_status not in {
                    UserLookupStatus.USER_NOT_FOUND.value,
                    UserLookupStatus.USER_LOOKUP_NOT_RUN.value,
                }:
                    entry: tuple[Any, Any, str, str | None] = (
                        None,
                        None,
                        UserLookupStatus.MEMBER_LOOKUP_FAILED.value,
                        user_error,
                    )
                    self.state.member_lookup_cache[cache_key] = entry
                    return entry

            member_name_key = self._normalize_member_name_key(lookup_text)
            if "GROUP" in allowed_types:
                matches.extend(self._group_candidates().get(f"GROUP:{member_name_key}", []))
            if "ROLE" in allowed_types:
                matches.extend(self._tracker_role_candidates(field_id).get(f"ROLE:{member_name_key}", []))

            unique_matches: dict[tuple[int, str], dict[str, Any]] = {}
            for match in matches:
                if match.get("id") is None or match.get("type") is None:
                    continue
                unique_matches[(int(match["id"]), str(match["type"]))] = match

            if len(unique_matches) == 1:
                candidate = next(iter(unique_matches.values()))
                resolved = self._build_member_reference(candidate)
                info = self._reference_payload_to_info(resolved)
                entry = (resolved, info, UserLookupStatus.RESOLVED.value, None)
                self.state.member_lookup_cache[cache_key] = entry
                return entry

            if len(unique_matches) > 1:
                entry = (
                    None,
                    None,
                    UserLookupStatus.MEMBER_LOOKUP_AMBIGUOUS.value,
                    f"Ambiguous member name: {lookup_text!r}",
                )
                self.state.member_lookup_cache[cache_key] = entry
                return entry

            entry = (None, None, UserLookupStatus.MEMBER_NOT_FOUND.value, None)
            self.state.member_lookup_cache[cache_key] = entry
            return entry
        except Exception as exc:
            entry = (None, None, UserLookupStatus.MEMBER_LOOKUP_FAILED.value, str(exc))
            self.state.member_lookup_cache[cache_key] = entry
            return entry

    def _resolve_user_reference_value(
        self,
        raw_value: Any,
        *,
        multiple_values: bool,
    ) -> tuple[Any, Any, str | None, str | None]:
        """단일 값 또는 목록 값을 사용자 reference 형태로 해석한다."""
        if multiple_values and isinstance(raw_value, list):
            resolved_values = []
            user_infos = []
            for item in raw_value:
                if item is None or self._normalize_lookup_text(item) == "":
                    continue
                resolved, user_info, status, error = self._lookup_user_reference(item)
                if resolved is None:
                    return None, None, status, error
                resolved_values.append(resolved)
                user_infos.append(user_info)
            return (
                resolved_values if resolved_values else None,
                user_infos if user_infos else None,
                UserLookupStatus.RESOLVED.value,
                None,
            )

        resolved, user_info, status, error = self._lookup_user_reference(raw_value)
        return resolved, user_info, status, error

    def _resolve_user_reference_fields(
        self,
        upload_df: pd.DataFrame,
        option_mapping: dict[str, str],
        option_maps: dict[str, dict],
    ) -> pd.DataFrame:
        """UserReference 필드의 각 행 값을 미리 찾아 `__resolved` 컬럼에 넣는다."""
        work = upload_df.copy()

        for df_col, schema_field in option_mapping.items():
            option_info = option_maps.get(schema_field, {})
            if option_info.get("kind") != OptionMapKind.USER_LOOKUP.value:
                continue

            resolved_values: list[Any] = []
            user_infos: list[Any] = []
            statuses: list[Any] = []
            errors: list[Any] = []
            multiple_values = option_info.get("multiple_values", False)

            for _, row in work.iterrows():
                raw_value = row[df_col]
                if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
                    resolved_values.append(None)
                    user_infos.append(None)
                    statuses.append(None)
                    errors.append(None)
                    continue

                resolved, user_info, status, error = self._resolve_user_reference_value(
                    raw_value,
                    multiple_values=multiple_values,
                )
                resolved_values.append(resolved)
                user_infos.append(user_info)
                statuses.append(status)
                errors.append(error)

            work[f"{df_col}__resolved"] = resolved_values
            work[f"{df_col}__user_info"] = user_infos
            work[f"{df_col}__lookup_status"] = statuses
            work[f"{df_col}__lookup_error"] = errors

        return work

    def _resolve_member_reference_value(
        self,
        raw_value: Any,
        *,
        multiple_values: bool,
        field_id: int | None,
        member_types: list[str] | None,
    ) -> tuple[Any, Any, str | None, str | None]:
        """단일 값 또는 목록 값을 member reference 형태로 해석한다."""
        if multiple_values and isinstance(raw_value, list):
            resolved_values = []
            member_infos = []
            for item in raw_value:
                if item is None or self._normalize_lookup_text(item) == "":
                    continue
                resolved, member_info, status, error = self._lookup_member_reference(
                    item,
                    field_id=field_id,
                    member_types=member_types,
                )
                if resolved is None:
                    return None, None, status, error
                resolved_values.append(resolved)
                member_infos.append(member_info)
            return (
                resolved_values if resolved_values else None,
                member_infos if member_infos else None,
                UserLookupStatus.RESOLVED.value,
                None,
            )

        return self._lookup_member_reference(
            raw_value,
            field_id=field_id,
            member_types=member_types,
        )

    def _resolve_member_reference_fields(
        self,
        upload_df: pd.DataFrame,
        option_mapping: dict[str, str],
        option_maps: dict[str, dict],
    ) -> pd.DataFrame:
        """MemberField 값을 미리 찾아 `__resolved` 컬럼에 넣는다."""
        work = upload_df.copy()

        for df_col, schema_field in option_mapping.items():
            option_info = option_maps.get(schema_field, {})
            if option_info.get("kind") != OptionMapKind.MEMBER_LOOKUP.value:
                continue

            resolved_values: list[Any] = []
            member_infos: list[Any] = []
            statuses: list[Any] = []
            errors: list[Any] = []
            multiple_values = option_info.get("multiple_values", False)
            field_id = option_info.get("field_id")
            member_types = option_info.get("member_types") or []

            for _, row in work.iterrows():
                raw_value = row[df_col]
                if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
                    resolved_values.append(None)
                    member_infos.append(None)
                    statuses.append(None)
                    errors.append(None)
                    continue

                resolved, member_info, status, error = self._resolve_member_reference_value(
                    raw_value,
                    multiple_values=multiple_values,
                    field_id=field_id,
                    member_types=member_types,
                )
                resolved_values.append(resolved)
                member_infos.append(member_info)
                statuses.append(status)
                errors.append(error)

            work[f"{df_col}__resolved"] = resolved_values
            work[f"{df_col}__user_info"] = member_infos
            work[f"{df_col}__lookup_status"] = statuses
            work[f"{df_col}__lookup_error"] = errors

        return work
