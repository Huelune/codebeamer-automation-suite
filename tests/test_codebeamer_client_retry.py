from __future__ import annotations

import threading
import unittest

from src.codebeamer_client import MAX_RETRY_AFTER_SECONDS
from src.codebeamer_client import CodebeamerClient


class _RateLimitError(Exception):
    def __init__(
        self,
        status_code: int = 429,
        message: str = "Too Many Requests",
        *,
        retry_after: str | None = None,
    ) -> None:
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        self.response = type("Response", (), {"status_code": status_code, "headers": headers})()
        super().__init__(message)


class RetryingClient(CodebeamerClient):
    def __init__(self, responses, *args, **kwargs) -> None:
        # 재시도 간격을 정확히 비교하려고 흔들림을 끈다. 흔들림은 따로 확인한다.
        kwargs.setdefault("jitter_fn", lambda: 0.0)
        super().__init__(*args, **kwargs)
        self._responses = list(responses)
        self.calls = 0

    def _post(self, path: str, json_body: dict | None = None, params: dict | None = None):
        del path, json_body, params
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def _put(self, path: str, json_body: dict | None = None, params: dict | None = None):
        del path, json_body, params
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def _get(self, path: str, params: dict | None = None):
        del path, params
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def _delete(self, path: str, params: dict | None = None):
        del path, params
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CodebeamerClientRetryTest(unittest.TestCase):
    def test_create_item_retries_with_configured_delay_multiples(self) -> None:
        slept: list[float] = []
        client = RetryingClient(
            [_RateLimitError(), _RateLimitError(), {"id": 123}],
            base_url="https://example.com/cb",
            username="user",
            password="pass",
            rate_limit_retry_delay_seconds=2.0,
            rate_limit_max_retries=3,
            sleep_fn=slept.append,
        )

        result = client.create_item(1, {"name": "REQ-1"})

        self.assertEqual(result["id"], 123)
        self.assertEqual(client.calls, 3)
        self.assertEqual(slept, [2.0, 4.0])

    def test_create_item_raises_after_max_retries(self) -> None:
        slept: list[float] = []
        client = RetryingClient(
            [_RateLimitError(), _RateLimitError(), _RateLimitError()],
            base_url="https://example.com/cb",
            username="user",
            password="pass",
            rate_limit_retry_delay_seconds=1.5,
            rate_limit_max_retries=2,
            sleep_fn=slept.append,
        )

        with self.assertRaises(_RateLimitError):
            client.create_item(1, {"name": "REQ-1"})

        self.assertEqual(client.calls, 3)
        self.assertEqual(slept, [1.5, 3.0])

    def test_update_item_retries_with_configured_delay_multiples(self) -> None:
        slept: list[float] = []
        client = RetryingClient(
            [_RateLimitError(), {"id": 456}],
            base_url="https://example.com/cb",
            username="user",
            password="pass",
            rate_limit_retry_delay_seconds=3.0,
            rate_limit_max_retries=2,
            sleep_fn=slept.append,
        )

        result = client.update_item(456, {"name": "REQ-456"})

        self.assertEqual(result["id"], 456)
        self.assertEqual(client.calls, 2)
        self.assertEqual(slept, [3.0])

    def test_search_items_reuses_rate_limit_retry_policy_for_reads(self) -> None:
        slept: list[float] = []
        client = RetryingClient(
            [_RateLimitError(), {"page": 1, "pageSize": 10, "total": 0, "items": []}],
            base_url="https://example.com/cb",
            username="user",
            password="pass",
            rate_limit_retry_delay_seconds=0.5,
            rate_limit_max_retries=2,
            sleep_fn=slept.append,
        )

        result = client.search_items(query_string="tracker.id = 10", page_size=10)

        self.assertEqual(result["items"], [])
        self.assertEqual(client.calls, 2)
        self.assertEqual(slept, [0.5])

    def test_delete_item_reuses_rate_limit_retry_policy(self) -> None:
        slept: list[float] = []
        client = RetryingClient(
            [_RateLimitError(), {}],
            base_url="https://example.com/cb",
            username="user",
            password="pass",
            rate_limit_retry_delay_seconds=0.75,
            rate_limit_max_retries=2,
            sleep_fn=slept.append,
        )

        result = client.delete_item(456)

        self.assertEqual(result, {})
        self.assertEqual(client.calls, 2)
        self.assertEqual(slept, [0.75])

    def _client(self, responses, slept, **kwargs) -> RetryingClient:
        return RetryingClient(
            responses,
            base_url="https://example.com/cb",
            username="user",
            password="pass",
            rate_limit_retry_delay_seconds=1.0,
            rate_limit_max_retries=3,
            sleep_fn=slept.append,
            **kwargs,
        )

    def test_retry_waits_at_least_as_long_as_retry_after(self) -> None:
        slept: list[float] = []
        client = self._client([_RateLimitError(retry_after="7"), {"id": 1}], slept)

        client.create_item(1, {"name": "REQ-1"})

        self.assertEqual(slept, [7.0])

    def test_retry_after_is_capped_and_ignored_when_unreadable(self) -> None:
        slept: list[float] = []
        client = self._client(
            [
                _RateLimitError(retry_after="100000"),
                _RateLimitError(retry_after="Wed, 21 Oct 2026 07:28:00 GMT"),
                {"id": 1},
            ],
            slept,
        )

        client.create_item(1, {"name": "REQ-1"})

        # 너무 긴 값은 상한까지만 기다리고, 날짜 형식은 기본 간격(1초 x 2회째)을 쓴다.
        self.assertEqual(slept, [MAX_RETRY_AFTER_SECONDS, 2.0])

    def test_retry_delay_is_spread_so_parallel_requests_do_not_retry_together(self) -> None:
        slept: list[float] = []
        client = self._client(
            [_RateLimitError(), _RateLimitError(), {"id": 1}],
            slept,
            jitter_fn=lambda: 1.0,
        )

        client.create_item(1, {"name": "REQ-1"})

        # 기본 간격에 최대 25%까지 더한다.
        self.assertEqual(slept, [1.25, 2.5])


class CodebeamerClientSessionTest(unittest.TestCase):
    def test_session_is_reused_per_thread_with_auth_headers(self) -> None:
        client = CodebeamerClient("https://example.com/cb", "user", "pass")
        first = client._session()
        other_thread: list[object] = []
        worker = threading.Thread(target=lambda: other_thread.append(client._session()))
        worker.start()
        worker.join()

        self.assertIs(client._session(), first)
        self.assertIsNot(other_thread[0], first)
        self.assertTrue(first.headers["Authorization"].startswith("Basic "))


if __name__ == "__main__":
    unittest.main()
