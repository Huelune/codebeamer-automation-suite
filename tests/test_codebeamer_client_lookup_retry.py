from __future__ import annotations

import unittest

from src.codebeamer_client import CodebeamerClient


class _RateLimitError(Exception):
    def __init__(self) -> None:
        self.response = type("Response", (), {"status_code": 429, "headers": {}})()
        super().__init__("Too Many Requests")


class _OnceRateLimitedClient(CodebeamerClient):
    """요청마다 처음 한 번은 429, 다음은 성공 응답을 준다."""

    def __init__(self, response) -> None:
        super().__init__(
            "https://example.test/cb",
            "sample",
            "placeholder",
            rate_limit_retry_delay_seconds=0.0,
            rate_limit_max_retries=2,
            sleep_fn=lambda _seconds: None,
        )
        self.response = response
        self.calls = 0

    def _answer(self):
        self.calls += 1
        if self.calls == 1:
            raise _RateLimitError()
        return self.response

    def _get(self, path: str, params: dict | None = None):
        del path, params
        return self._answer()

    def _post(self, path: str, json_body: dict | None = None, params: dict | None = None):
        del path, json_body, params
        return self._answer()


class LookupRetryTest(unittest.TestCase):
    """사용자·멤버 조회도 요청 제한(429)이면 다시 시도한다. 한 번에 실패하면 검증이 입력 오류로 막힌다."""

    def test_lookup_reads_retry_after_rate_limit(self) -> None:
        user = {"id": 101, "name": "Kim QA"}
        cases = {
            "get_user_by_name": (user, lambda client: client.get_user_by_name("Kim QA")),
            "get_user": (user, lambda client: client.get_user(101)),
            "get_user_by_email": (user, lambda client: client.get_user_by_email("qa@example.test")),
            "get_user_groups": ([], lambda client: client.get_user_groups()),
            "get_project_members": ([], lambda client: client.get_project_members(10)),
            "get_tracker_field_permissions": ([], lambda client: client.get_tracker_field_permissions(20, 9)),
            "search_users": ({"users": []}, lambda client: client.search_users(name="Kim")),
        }
        for name, (response, call) in cases.items():
            with self.subTest(method=name):
                client = _OnceRateLimitedClient(response)

                call(client)

                self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
