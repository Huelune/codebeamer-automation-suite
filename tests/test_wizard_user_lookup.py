from __future__ import annotations

import atexit
import contextlib
import unittest

import pandas as pd

from src.mapping_service import MappingService
from src.models import OptionMapKind
from src.models import UserInfo
from src.wizard import CodebeamerUploadWizard


try:
    import xlwings._xlmac as _xlmac

    for cleanup_name in ("cleanup", "clean_up"):
        cleanup_func = getattr(_xlmac, cleanup_name, None)
        if cleanup_func is not None:
            with contextlib.suppress(Exception):
                atexit.unregister(cleanup_func)
except Exception:
    pass


class NotFoundError(Exception):
    def __init__(self) -> None:
        """실제 API의 404 응답처럼 보이는 테스트용 예외를 만든다."""
        self.response = type("Response", (), {"status_code": 404})()
        super().__init__("not found")


class FakeClient:
    def __init__(self) -> None:
        """사용자 lookup 테스트에 필요한 최소 기능만 가진 가짜 client를 만든다."""
        self.get_user_calls = 0
        self.get_user_by_name_calls = 0
        self.users_by_id: dict[int, UserInfo] = {}
        self.users_by_name: dict[str, UserInfo] = {}

    def get_user_by_name(self, name: str) -> UserInfo:
        self.get_user_by_name_calls += 1
        if name not in self.users_by_name:
            raise NotFoundError()
        return self.users_by_name[name]

    def get_user(self, user_id: int) -> UserInfo:
        """ID로 사용자를 찾고 없으면 404 예외를 흉내 낸다."""
        self.get_user_calls += 1
        if user_id not in self.users_by_id:
            raise NotFoundError()
        return self.users_by_id[user_id]


class WizardUserLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        """각 테스트마다 가짜 client와 wizard를 새로 만든다."""
        self.client = FakeClient()
        self.wizard = CodebeamerUploadWizard(
            client=self.client,
            processor=None,
            mapper=MappingService(),
        )
        self.wizard.select_project(101)

    def test_lookup_uses_cached_name_without_additional_requests(self) -> None:
        """한 번 찾은 사용자는 같은 이름 입력에서 캐시가 재사용돼야 한다."""
        user = UserInfo(
            id=7,
            name="Jane Doe",
        )
        self.client.users_by_name[user.name] = user

        first_resolved, first_user_info, first_status, first_error = self.wizard._lookup_user_reference("Jane Doe")
        second_resolved, second_user_info, second_status, second_error = self.wizard._lookup_user_reference("Jane Doe")

        self.assertEqual(first_status, "RESOLVED")
        self.assertIsNone(first_error)
        self.assertEqual(first_resolved, second_resolved)
        self.assertEqual(first_user_info, second_user_info)
        self.assertEqual(second_status, "RESOLVED")
        self.assertIsNone(second_error)
        self.assertEqual(self.client.get_user_by_name_calls, 1)

    def test_lookup_falls_back_to_id_when_name_lookup_misses(self) -> None:
        """이름 조회가 없으면 숫자 입력에서 ID 조회로 fallback 해야 한다."""
        user = UserInfo(
            id=8,
            name="User 8",
        )
        self.client.users_by_id[user.id] = user

        resolved, user_info, status, error = self.wizard._lookup_user_reference("8")

        self.assertEqual(status, "RESOLVED")
        self.assertIsNone(error)
        self.assertEqual(resolved["id"], 8)
        self.assertEqual(user_info["name"], "User 8")
        self.assertEqual(self.client.get_user_by_name_calls, 1)
        self.assertEqual(self.client.get_user_calls, 1)

    def test_lookup_cache_is_cleared_when_project_changes(self) -> None:
        """프로젝트가 바뀌면 이전 프로젝트의 사용자 캐시를 버려야 한다."""
        user = UserInfo(
            id=9,
            name="John Smith",
        )
        self.client.users_by_name[user.name] = user

        self.wizard._lookup_user_reference("John Smith")
        self.wizard.select_project(202)
        self.wizard._lookup_user_reference("John Smith")

        self.assertEqual(self.client.get_user_by_name_calls, 2)

    def test_resolve_user_reference_fields_reuses_cached_name_results(self) -> None:
        """같은 사용자 이름이 반복되면 조회 결과를 재사용해야 한다."""
        user = UserInfo(
            id=11,
            name="Fallback User",
        )
        self.client.users_by_name[user.name] = user

        upload_df = pd.DataFrame([
            {"_row_id": 1, "owner": "Fallback User"},
            {"_row_id": 2, "owner": "Fallback User"},
        ])
        option_mapping = {"owner": "Owner"}
        option_maps = {
            "Owner": {
                "kind": OptionMapKind.USER_LOOKUP.value,
                "multiple_values": False,
            }
        }

        resolved_df = self.wizard._resolve_user_reference_fields(upload_df, option_mapping, option_maps)

        self.assertEqual(self.client.get_user_by_name_calls, 1)
        self.assertEqual(list(resolved_df["owner__lookup_status"]), ["RESOLVED", "RESOLVED"])
        self.assertTrue(resolved_df["owner__user_info"].notna().all())
        self.assertEqual(resolved_df.iloc[0]["owner__resolved"]["id"], 11)
        self.assertEqual(resolved_df.iloc[1]["owner__resolved"]["id"], 11)
        self.assertEqual(resolved_df.iloc[0]["owner__user_info"]["type"], "UserReference")


if __name__ == "__main__":
    unittest.main()
