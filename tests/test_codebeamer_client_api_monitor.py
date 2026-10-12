from __future__ import annotations

import unittest

import requests

from src.api_monitor import API_OUTCOME_FAILED
from src.api_monitor import API_OUTCOME_RETRY
from src.api_monitor import API_OUTCOME_SUCCESS
from src.api_monitor import ApiMonitorService
from src.codebeamer_client import CodebeamerClient


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object | None = None,
        *,
        content: bytes = b"{}",
    ) -> None:
        self.status_code = status_code
        self.payload = {} if payload is None else payload
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code} with private server text",
                response=self,
            )

    def json(self):
        return self.payload


class _FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []
        self.closed = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.close()

    def close(self) -> None:
        self.closed += 1

    def _request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url: str, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self._request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self._request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self._request("DELETE", url, **kwargs)


class _SessionClient(CodebeamerClient):
    def __init__(self, responses: list[object], **kwargs) -> None:
        self.fake_session = _FakeSession(responses)
        super().__init__(
            base_url="https://private.example.test/cb",
            username="private-user",
            password="private-password",
            **kwargs,
        )

    def _session(self):
        return self.fake_session


class CodebeamerClientApiMonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = ApiMonitorService()
        self.monitor.configure(enabled=True, slow_threshold_ms=1000)

    def test_requests_have_connect_and_read_timeouts(self) -> None:
        """서버가 응답하지 않아도 무한히 기다리지 않는다."""
        client = _SessionClient(
            [_FakeResponse(200, []), _FakeResponse(201, {"id": 1})],
            api_monitor=self.monitor,
        )

        client.get_projects()
        client.create_item(10, {"name": "REQ"})

        timeouts = [kwargs.get("timeout") for _method, _url, kwargs in client.fake_session.calls]
        # 조회는 응답을 2분, 쓰기는 반영될 시간을 5분까지 기다린다. 연결은 10초.
        self.assertEqual(timeouts, [(10.0, 120.0), (10.0, 300.0)])

    def test_session_stays_open_for_the_next_request(self) -> None:
        """요청마다 연결을 닫지 않고 다음 요청에 다시 쓴다."""
        client = _SessionClient(
            [_FakeResponse(200, []), _FakeResponse(200, [])],
            api_monitor=self.monitor,
        )

        client.get_projects()
        client.get_projects()

        self.assertEqual(client.fake_session.closed, 0)

    def test_successful_create_records_only_safe_request_metadata(self) -> None:
        secret_payload = {"name": "private summary", "description": "secret body"}
        client = _SessionClient(
            [_FakeResponse(201, {"id": 7788})],
            api_monitor=self.monitor,
            rate_limit_max_retries=2,
        )

        result = client.create_item(12345, secret_payload, parent_item_id=98765)

        self.assertEqual(result, {"id": 7788})
        event = self.monitor.snapshot().events[0]
        self.assertEqual(event.request_kind, "create_item")
        self.assertEqual(event.method, "POST")
        self.assertEqual(event.path, "/v3/trackers/{id}/items")
        self.assertEqual(event.status_code, 201)
        self.assertEqual(event.outcome, API_OUTCOME_SUCCESS)
        serialized_event = repr(event)
        for secret in (
            "private summary",
            "secret body",
            "98765",
            "private-user",
            "private-password",
            "private.example.test",
        ):
            self.assertNotIn(secret, serialized_event)

    def test_rate_limit_attempt_and_success_are_recorded_as_two_rows(self) -> None:
        client = _SessionClient(
            [_FakeResponse(429), _FakeResponse(200, {"id": 42})],
            api_monitor=self.monitor,
            rate_limit_retry_delay_seconds=0,
            rate_limit_max_retries=2,
            sleep_fn=lambda _seconds: None,
        )

        result = client.get_item(42)

        self.assertEqual(result, {"id": 42})
        events = self.monitor.snapshot().events
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].outcome, API_OUTCOME_RETRY)
        self.assertEqual(events[0].status_code, 429)
        self.assertEqual((events[0].attempt, events[0].max_attempts), (1, 3))
        self.assertEqual(events[1].outcome, API_OUTCOME_SUCCESS)
        self.assertEqual((events[1].attempt, events[1].max_attempts), (2, 3))

    def test_connection_error_records_controlled_kind_without_raw_message(self) -> None:
        client = _SessionClient(
            [requests.ConnectionError("internal-host and bearer-secret")],
            api_monitor=self.monitor,
            rate_limit_max_retries=0,
        )

        with self.assertRaises(requests.ConnectionError):
            client.get_projects()

        event = self.monitor.snapshot().events[0]
        self.assertEqual(event.outcome, API_OUTCOME_FAILED)
        self.assertIsNone(event.status_code)
        self.assertEqual(event.error_kind, "Connection")
        self.assertNotIn("internal-host", repr(event))
        self.assertNotIn("bearer-secret", repr(event))

    def test_direct_lookup_query_value_is_not_present_in_event(self) -> None:
        client = _SessionClient(
            [_FakeResponse(200, {"id": 1, "name": "Anonymous"})],
            api_monitor=self.monitor,
        )

        client.get_user_by_email("sensitive.person@example.test")

        event = self.monitor.snapshot().events[0]
        self.assertEqual(event.path, "/v3/users/findByEmail")
        self.assertNotIn("sensitive.person", repr(event))

    def test_delete_with_empty_response_keeps_existing_empty_object_behavior(self) -> None:
        client = _SessionClient(
            [_FakeResponse(204, content=b"")],
            api_monitor=self.monitor,
            rate_limit_max_retries=0,
        )

        self.assertEqual(client.delete_item(12345), {})
        event = self.monitor.snapshot().events[0]
        self.assertEqual(event.method, "DELETE")
        self.assertEqual(event.status_code, 204)


if __name__ == "__main__":
    unittest.main()
