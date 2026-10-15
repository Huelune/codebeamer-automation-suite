from __future__ import annotations

import base64
import random
import threading
import time
from contextvars import ContextVar
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests

from .api_monitor import API_MONITOR
from .api_monitor import API_OUTCOME_FAILED
from .api_monitor import API_OUTCOME_RETRY
from .api_monitor import API_OUTCOME_SUCCESS
from .api_monitor import normalize_api_path
from .models import ITEM_SEARCH_RESULT_KEYS
from .models import USER_SEARCH_RESULT_KEYS
from .models import UserInfo


_API_REQUEST_CONTEXT: ContextVar[tuple[str, int, int] | None] = ContextVar(
    "codebeamer_api_request_context",
    default=None,
)

# 서버에 닿지 않으면 빨리 포기하고, 닿은 뒤에는 큰 조회를 처리할 시간을 준다.
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 120.0
# 쓰기는 응답을 받지 못하면 반영됐는지 알 수 없다. 서버가 끝낼 시간을 더 준다.
WRITE_READ_TIMEOUT_SECONDS = 300.0
# 429 응답의 Retry-After 를 따르되 이보다 오래 붙잡혀 있지는 않는다.
MAX_RETRY_AFTER_SECONDS = 60.0
# 동시에 막힌 요청이 같은 순간에 다시 몰리지 않도록 재시도 간격에 더하는 최대 비율.
RETRY_JITTER_RATIO = 0.25


class CodebeamerClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        logger=None,
        *,
        rate_limit_retry_delay_seconds: float = 1.0,
        rate_limit_max_retries: int = 5,
        sleep_fn=time.sleep,
        jitter_fn=random.random,
        api_monitor=API_MONITOR,
    ):
        """Codebeamer 서버에 요청할 때 필요한 접속 정보를 보관한다."""
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.logger = logger
        self.rate_limit_retry_delay_seconds = rate_limit_retry_delay_seconds
        self.rate_limit_max_retries = rate_limit_max_retries
        self._sleep_fn = sleep_fn
        self._jitter_fn = jitter_fn
        self.api_monitor = api_monitor
        # requests.Session 은 스레드끼리 나눠 쓰면 안전하지 않다. 스레드마다 하나씩 두고 다시 쓴다.
        self._sessions = threading.local()

    def _session(self) -> requests.Session:
        """인증 헤더가 포함된 이 스레드의 HTTP 세션. 연결을 다음 요청에 다시 쓴다."""
        session = getattr(self._sessions, "session", None)
        if session is not None:
            return session
        session = requests.Session()
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        session.headers.update({
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self._sessions.session = session
        return session

    @staticmethod
    def _timeout(method: str) -> tuple[float, float]:
        read_timeout = READ_TIMEOUT_SECONDS if method == "GET" else WRITE_READ_TIMEOUT_SECONDS
        return (CONNECT_TIMEOUT_SECONDS, read_timeout)

    def _get(self, path: str, params: dict | None = None) -> Any:
        """GET 요청을 보내고 JSON 응답을 돌려준다."""
        return self._request_json("GET", path, params=params)

    def _post(self, path: str, json_body: dict | None = None, params: dict | None = None) -> Any:
        """POST 요청을 보내고 JSON 응답을 돌려준다."""
        return self._request_json("POST", path, json_body=json_body, params=params)

    def _put(self, path: str, json_body: Any = None, params: dict | None = None) -> Any:
        """PUT 요청을 보내고 JSON 응답을 돌려준다."""
        return self._request_json("PUT", path, json_body=json_body, params=params)

    def _delete(self, path: str, params: dict | None = None) -> Any:
        """DELETE 요청을 보내고 본문이 없으면 빈 객체를 돌려준다."""
        return self._request_json("DELETE", path, params=params, empty_ok=True)

    @staticmethod
    def _resource_monitor_path(resource_path: str) -> str:
        """다운로드 경로를 API 모니터와 진단 파일에 남길 모양으로 줄인다.

        첨부·그림 경로는 서버 context 경로와 첨부 파일 이름을 담고 있다. `/v3` API는 그 뒤만 남기고,
        그 밖의 경로는 정해 둔 이름으로만 남긴다.
        """
        segments = [segment for segment in str(resource_path or "").split("/") if segment]
        lowered = [segment.casefold() for segment in segments]
        if "v3" in lowered:
            return "/" + "/".join(segments[lowered.index("v3"):])
        if "displaydocument" in lowered:
            return "/displayDocument/{name}"
        return "/{resource}"

    def _request_binary(self, source_url: str, *, max_bytes: int) -> tuple[str, bytes]:
        """같은 Codebeamer origin의 첨부 리소스를 제한된 크기로 가져온다."""
        normalized_limit = max(int(max_bytes), 1)
        base = urlparse(self.base_url)
        absolute = urljoin(f"{self.base_url}/", str(source_url or "").strip())
        parsed = urlparse(absolute)
        if (parsed.scheme.casefold(), parsed.netloc.casefold()) != (
            base.scheme.casefold(),
            base.netloc.casefold(),
        ):
            raise ValueError("Codebeamer와 다른 서버의 리소스는 다운로드할 수 없습니다.")
        lowered_target = f"{parsed.path}?{parsed.query}".casefold()
        if "attachment" not in lowered_target and "displaydocument" not in lowered_target:
            raise ValueError("확인되지 않은 Codebeamer 리소스 경로입니다.")

        monitor_path = self._resource_monitor_path(parsed.path)
        retry_context = _API_REQUEST_CONTEXT.get()
        request_kind, attempt, max_attempts = (
            (f"GET {normalize_api_path(monitor_path)}", 1, 1)
            if retry_context is None
            else retry_context
        )
        monitor_handle = self.api_monitor.start_request(
            request_kind=request_kind,
            method="GET",
            path=monitor_path,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        response = None
        status_code = None
        outcome = API_OUTCOME_SUCCESS
        error_kind = None
        try:
            session = self._session()
            response = session.get(
                absolute,
                headers={"Accept": "*/*"},
                stream=True,
                allow_redirects=False,
                timeout=self._timeout("GET"),
            )
            status_code = self._response_status_code(response)
            if status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location", "")
                redirected = urljoin(absolute, location)
                redirected_url = urlparse(redirected)
                if (redirected_url.scheme.casefold(), redirected_url.netloc.casefold()) != (
                    base.scheme.casefold(),
                    base.netloc.casefold(),
                ):
                    raise ValueError("첨부 다운로드가 다른 서버로 이동하려고 합니다.")
                redirected_target = f"{redirected_url.path}?{redirected_url.query}".casefold()
                if "attachment" not in redirected_target and "displaydocument" not in redirected_target:
                    raise ValueError("첨부 다운로드가 확인되지 않은 경로로 이동하려고 합니다.")
                response.close()
                response = session.get(
                    redirected,
                    headers={"Accept": "*/*"},
                    stream=True,
                    allow_redirects=False,
                    timeout=self._timeout("GET"),
                )
                status_code = self._response_status_code(response)
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length is not None and content_length != "" and int(content_length) > normalized_limit:
                raise ValueError("첨부 리소스가 허용 크기를 초과합니다.")
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > normalized_limit:
                    raise ValueError("첨부 리소스가 허용 크기를 초과합니다.")
                chunks.append(chunk)
            return str(response.headers.get("Content-Type") or ""), b"".join(chunks)
        except Exception as exc:
            status_code = self._response_status_code(response, exc)
            is_retry = self._is_rate_limited(exc) and attempt < max_attempts
            outcome = API_OUTCOME_RETRY if is_retry else API_OUTCOME_FAILED
            error_kind = self._monitor_error_kind(exc, status_code)
            raise
        finally:
            if response is not None:
                response.close()
            self.api_monitor.finish_request(
                monitor_handle,
                status_code=status_code,
                outcome=outcome,
                error_kind=error_kind,
            )

    @staticmethod
    def _response_status_code(response: object | None, exc: Exception | None = None) -> int | None:
        candidate = response
        if candidate is None and exc is not None:
            candidate = getattr(exc, "response", None)
        value = getattr(candidate, "status_code", None)
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _monitor_error_kind(exc: Exception, status_code: int | None) -> str:
        if isinstance(exc, requests.Timeout):
            return "Timeout"
        if isinstance(exc, requests.ConnectionError):
            return "Connection"
        if status_code == 429:
            return "RateLimit"
        if isinstance(exc, requests.HTTPError) or status_code is not None:
            return "HTTP"
        if isinstance(exc, ValueError):
            return "Parse"
        return "Unknown"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        empty_ok: bool = False,
    ) -> Any:
        """Send one HTTP attempt and record metadata without payload or credentials."""

        normalized_method = str(method or "").upper()
        retry_context = _API_REQUEST_CONTEXT.get()
        if retry_context is None:
            request_kind = f"{normalized_method} {normalize_api_path(path)}"
            attempt = 1
            max_attempts = 1
        else:
            request_kind, attempt, max_attempts = retry_context

        monitor_handle = self.api_monitor.start_request(
            request_kind=request_kind,
            method=normalized_method,
            path=path,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        response = None
        status_code = None
        outcome = API_OUTCOME_SUCCESS
        error_kind = None
        try:
            url = f"{self.base_url}{path}"
            request_method = getattr(self._session(), normalized_method.lower())
            request_kwargs: dict[str, Any] = {
                "params": params,
                "timeout": self._timeout(normalized_method),
            }
            if normalized_method in {"POST", "PUT"}:
                request_kwargs["json"] = json_body
            response = request_method(url, **request_kwargs)
            status_code = self._response_status_code(response)
            response.raise_for_status()
            if empty_ok and not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                if empty_ok:
                    return {}
                raise
        except Exception as exc:
            status_code = self._response_status_code(response, exc)
            is_retry = self._is_rate_limited(exc) and attempt < max_attempts
            outcome = API_OUTCOME_RETRY if is_retry else API_OUTCOME_FAILED
            error_kind = self._monitor_error_kind(exc, status_code)
            raise
        finally:
            self.api_monitor.finish_request(
                monitor_handle,
                status_code=status_code,
                outcome=outcome,
                error_kind=error_kind,
            )

    @staticmethod
    def _extract_user_payloads(data: Any) -> list[dict[str, Any]]:
        """사용자 검색 응답에서 실제 사용자 목록만 골라낸다."""
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in USER_SEARCH_RESULT_KEYS:
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_item_payloads(data: Any) -> list[dict[str, Any]]:
        """아이템 검색 응답에서 실제 아이템 목록만 골라낸다."""
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ITEM_SEARCH_RESULT_KEYS:
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _tracker_item_display_name(item: dict[str, Any]) -> str:
        """아이템 검색 결과에서 화면에 표시할 이름을 우선순위대로 고른다."""
        for key in ("name", "summary", "itemName", "title"):
            value = item.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _is_rate_limited(exc: Exception) -> bool:
        """예외가 rate limit 상황인지 판정한다."""
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code == 429:
            return True
        message = str(exc).lower()
        return "max request" in message or "too many requests" in message or "rate limit" in message

    def get_projects(self) -> list[dict]:
        """접근 가능한 프로젝트 목록을 가져온다."""
        return self._run_rate_limited_request(
            "get_projects",
            lambda: self._get("/v3/projects"),
        )

    def get_trackers(self, project_id: int) -> list[dict]:
        """프로젝트 안에 있는 트래커 목록을 가져온다."""
        return self._run_rate_limited_request(
            "get_trackers",
            lambda: self._get(f"/v3/projects/{project_id}/trackers"),
        )

    def get_tracker(self, tracker_id: int) -> dict:
        """트래커 한 개의 상세 정보를 가져온다."""
        return self._run_rate_limited_request(
            "get_tracker",
            lambda: self._get(f"/v3/trackers/{tracker_id}"),
        )

    def get_tracker_items(self, tracker_id: int) -> list[dict]:
        """트래커에 속한 아이템 참조 목록을 가져온다."""
        return self._get(f"/v3/trackers/{tracker_id}/items").get("itemRefs", [])

    def get_tracker_items_page(
        self,
        tracker_id: int,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict:
        """트래커 아이템 참조와 서버 pagination 메타데이터를 함께 가져온다."""
        return self._run_rate_limited_request(
            "get_tracker_items_page",
            lambda: self._get(
                f"/v3/trackers/{int(tracker_id)}/items",
                params={
                    "page": max(int(page), 1),
                    "pageSize": min(max(int(page_size), 1), 500),
                },
            ),
        )

    def get_tracker_children(self, tracker_id: int) -> list[dict]:
        """트래커 루트 아래에 있는 자식 아이템 목록을 가져온다."""
        return self._get(f"/v3/trackers/{tracker_id}/children").get("itemRefs", [])

    def get_tracker_children_page(
        self,
        tracker_id: int,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict:
        """트래커 최상위 아이템과 서버 pagination 메타데이터를 가져온다."""
        return self._run_rate_limited_request(
            "get_tracker_children_page",
            lambda: self._get(
                f"/v3/trackers/{int(tracker_id)}/children",
                params={
                    "page": max(int(page), 1),
                    "pageSize": min(max(int(page_size), 1), 500),
                },
            ),
        )

    def get_item_children(self, item_id: int) -> list[dict]:
        """아이템의 직접 하위 아이템 참조 목록을 가져온다."""
        return self._get(f"/v3/items/{int(item_id)}/children").get("itemRefs", [])

    def get_item_children_page(
        self,
        item_id: int,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict:
        """아이템의 직접 하위 목록과 서버 pagination 메타데이터를 가져온다."""
        return self._run_rate_limited_request(
            "get_item_children_page",
            lambda: self._get(
                f"/v3/items/{int(item_id)}/children",
                params={
                    "page": max(int(page), 1),
                    "pageSize": min(max(int(page_size), 1), 500),
                },
            ),
        )

    def get_tracker_schema(self, tracker_id: int) -> dict | list[dict]:
        """트래커 스키마를 가져와 필드 구조를 분석할 수 있게 한다."""
        return self._run_rate_limited_request(
            "get_tracker_schema",
            lambda: self._get(f"/v3/trackers/{tracker_id}/schema"),
        )

    def render_wiki_to_html(
        self,
        project_id: int,
        *,
        context_id: int,
        context_version: int,
        markup: str,
        rendering_context_type: str = "TRACKER_ITEM",
    ) -> str:
        """Codebeamer Wiki 엔진으로 문맥이 있는 markup을 HTML로 변환한다."""
        payload = self._run_rate_limited_request(
            "render_wiki_to_html",
            lambda: self._post(
                f"/v3/projects/{int(project_id)}/wiki2html",
                json_body={
                    "contextId": int(context_id),
                    "contextVersion": int(context_version),
                    "markup": str(markup or ""),
                    "renderingContextType": str(rendering_context_type or "TRACKER_ITEM"),
                },
            ),
        )
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            for key in ("html", "value", "renderedMarkup", "markup"):
                if isinstance(payload.get(key), str):
                    return payload[key]
        raise ValueError("Wiki HTML 응답 형식을 해석할 수 없습니다.")

    def get_item_attachments(self, item_id: int) -> Any:
        """아이템 첨부 메타데이터를 조회한다.

        이 v3 경로는 대상 서버 Swagger에서 반드시 확인해야 하며, 미지원 서버의
        404는 상위 content service가 사용자에게 명시적인 조회 실패로 전달한다.
        """
        page = 1
        page_size = 500
        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        while True:
            payload = self._run_rate_limited_request(
                "get_item_attachments",
                lambda current_page=page: self._get(
                    f"/v3/items/{int(item_id)}/attachments",
                    params={"page": current_page, "pageSize": page_size},
                ),
            )
            references = self._extract_attachment_references(payload)
            added = 0
            for reference in references:
                identity = str(reference.get("id") or reference.get("attachmentId") or "").strip()
                if not identity or identity in seen_ids:
                    continue
                seen_ids.add(identity)
                collected.append(reference)
                added += 1
            if isinstance(payload, list):
                break
            raw_total = payload.get("total") if isinstance(payload, dict) else None
            try:
                total = int(raw_total) if raw_total is not None else None
            except (TypeError, ValueError):
                total = None
            if total is not None and len(collected) >= max(total, 0):
                break
            # 서버 JSON 값이라 타입이 없다. 아래 try/except 가 실제 방어 장치다.
            raw_response_page_size: Any = (
                payload.get("pageSize") if isinstance(payload, dict) else None
            )
            try:
                response_page_size = int(raw_response_page_size)
            except (TypeError, ValueError):
                response_page_size = page_size
            if not references or (
                total is None and len(references) < max(response_page_size, 1)
            ):
                break
            if added == 0:
                raise RuntimeError("서버가 첨부 목록의 다음 페이지를 적용하지 않았습니다.")
            page += 1
        return collected

    def get_item_comments(self, item_id: int) -> list[dict[str, Any]]:
        """아이템 댓글을 서버 페이지 끝까지 수집한다."""
        page = 1
        page_size = 500
        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        while True:
            payload = self._run_rate_limited_request(
                "get_item_comments",
                lambda current_page=page: self._get(
                    f"/v3/items/{int(item_id)}/comments",
                    params={"page": current_page, "pageSize": page_size},
                ),
            )
            references = self._extract_comment_references(payload)
            added = 0
            for reference in references:
                identity = str(reference.get("id") or reference.get("commentId") or "").strip()
                if not identity or identity in seen_ids:
                    continue
                seen_ids.add(identity)
                collected.append(reference)
                added += 1
            if isinstance(payload, list):
                break
            raw_total = payload.get("total") if isinstance(payload, dict) else None
            try:
                total = int(raw_total) if raw_total is not None else None
            except (TypeError, ValueError):
                total = None
            if total is not None and len(collected) >= max(total, 0):
                break
            raw_response_page_size: Any = (
                payload.get("pageSize") if isinstance(payload, dict) else None
            )
            try:
                response_page_size = int(raw_response_page_size)
            except (TypeError, ValueError):
                response_page_size = page_size
            if not references or (total is None and len(references) < max(response_page_size, 1)):
                break
            if added == 0:
                raise RuntimeError("서버가 댓글 목록의 다음 페이지를 적용하지 않았습니다.")
            page += 1
        return collected

    @staticmethod
    def _extract_comment_references(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("comments", "items", "content"):
            values = payload.get(key)
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_attachment_references(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("attachments", "attachmentRefs", "items", "references", "content"):
            values = payload.get(key)
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]
        return []

    def download_authenticated_resource(
        self,
        source_url: str,
        *,
        max_bytes: int,
    ) -> tuple[str, bytes]:
        return self._run_rate_limited_request(
            "download_attachment_resource",
            lambda: self._request_binary(source_url, max_bytes=max_bytes),
        )

    def download_attachment_content(
        self,
        attachment_id: int,
        *,
        max_bytes: int,
    ) -> tuple[str, bytes]:
        """첨부 ID로 공식 v3 content endpoint의 바이너리를 가져온다."""
        return self.download_authenticated_resource(
            f"{self.base_url}/v3/attachments/{int(attachment_id)}/content",
            max_bytes=max_bytes,
        )

    def get_project_members(self, project_id: int) -> Any:
        """프로젝트 멤버 목록을 가져온다."""
        return self._run_rate_limited_request(
            "get_project_members",
            lambda: self._get(f"/v3/projects/{project_id}/members"),
        )

    def get_user_groups(self) -> Any:
        """전체 사용자 그룹 목록을 가져온다."""
        return self._run_rate_limited_request(
            "get_user_groups",
            lambda: self._get("/v3/users/groups"),
        )

    def get_tracker_field_permissions(self, tracker_id: int, field_id: int) -> Any:
        """특정 field의 permission matrix를 가져온다."""
        return self._run_rate_limited_request(
            "get_tracker_field_permissions",
            lambda: self._get(f"/v3/trackers/{tracker_id}/fields/{field_id}/permissions"),
        )

    def get_tracker_baselines(self, tracker_id: int) -> list[dict]:
        """트래커에 정의된 baseline을 서버 페이지 끝까지 수집한다."""
        normalized_tracker_id = int(tracker_id)
        page_size = 500
        page = 1
        baselines: list[dict] = []
        seen_ids: set[str] = set()

        while True:
            data = self._run_rate_limited_request(
                "get_tracker_baselines",
                lambda current_page=page: self._get(
                    f"/v3/trackers/{normalized_tracker_id}/baselines",
                    params={"page": current_page, "pageSize": page_size},
                ),
            )
            references = self._extract_baseline_references(data)
            added = 0
            for reference in references:
                raw_id: Any = reference.get("id")
                if raw_id in (None, "") or isinstance(raw_id, bool):
                    continue
                try:
                    baseline_id = str(int(raw_id))
                except (TypeError, ValueError):
                    baseline_id = str(raw_id).strip()
                if not baseline_id or baseline_id in seen_ids:
                    continue
                seen_ids.add(baseline_id)
                baselines.append(reference)
                added += 1

            if isinstance(data, list):
                break

            raw_total = data.get("total") if isinstance(data, dict) else None
            try:
                total = int(raw_total) if raw_total is not None else None
            except (TypeError, ValueError):
                total = None
            if total is not None and len(baselines) >= max(total, 0):
                break
            if not references:
                if total is not None and len(baselines) < total:
                    raise RuntimeError(
                        "서버가 baseline 목록의 다음 페이지를 반환하지 않았습니다."
                    )
                break
            if added == 0:
                if total is not None and len(baselines) < total:
                    raise RuntimeError(
                        "서버가 baseline 목록의 다음 페이지를 적용하지 않았습니다."
                    )
                break

            raw_response_page_size: Any = (
                data.get("pageSize") if isinstance(data, dict) else None
            )
            try:
                response_page_size = int(raw_response_page_size)
            except (TypeError, ValueError):
                response_page_size = page_size
            if total is None and len(references) < max(response_page_size, 1):
                break
            page += 1

        return baselines

    @classmethod
    def _extract_baseline_references(cls, data: Any) -> list[dict]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in (
            "references",
            "baselines",
            "trackerBaselines",
            "baselineList",
            "items",
            "results",
            "content",
        ):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        nested = data.get("data")
        if isinstance(nested, (dict, list)):
            return cls._extract_baseline_references(nested)
        return []

    def get_item(self, item_id: int, baseline_id: int | None = None) -> dict:
        """아이템 한 개의 상세 정보를 가져온다."""
        params = None if baseline_id is None else {"baselineId": int(baseline_id)}
        return self._run_rate_limited_request(
            "get_item",
            lambda: self._get(f"/v3/items/{item_id}", params=params),
        )

    def get_item_relations(self, item_id: int) -> dict:
        """현재 아이템의 참조와 association을 한 번에 조회한다."""
        return self._run_rate_limited_request(
            "get_item_relations",
            lambda: self._get(f"/v3/items/{int(item_id)}/relations"),
        )

    def get_item_history(self, item_id: int) -> dict:
        """현재 아이템의 버전 이력 메타데이터를 조회한다."""
        return self._run_rate_limited_request(
            "get_item_history",
            lambda: self._get(f"/v3/items/{int(item_id)}/history"),
        )

    def search_items(
        self,
        *,
        query_string: str,
        baseline_id: int | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict:
        """조건에 맞는 아이템 검색 결과를 원본 JSON 형태로 돌려준다."""
        params: dict[str, Any] = {
            "queryString": query_string,
            "page": max(int(page), 1),
            "pageSize": min(max(int(page_size), 1), 500),
        }
        if baseline_id is not None:
            params["baselineId"] = int(baseline_id)
        return self._run_rate_limited_request(
            "search_items",
            lambda: self._get("/v3/items/query", params=params),
        )

    def search_tracker_items_by_name(
        self,
        *,
        tracker_id: int,
        name: str,
        baseline_id: int | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """특정 트래커 안에서 이름 또는 summary와 유사한 아이템을 찾는다."""
        lookup_text = str(name or "").strip()
        if not lookup_text:
            return []

        escaped = lookup_text.replace("'", "''")
        query_string = f"Summary LIKE '%{escaped}%' AND tracker.id = {int(tracker_id)}"
        data = self.search_items(
            query_string=query_string,
            baseline_id=baseline_id,
            page=page,
            page_size=page_size,
        )
        item_payloads = self._extract_item_payloads(data)
        normalized_lookup = lookup_text.casefold()
        exact_matches: list[dict[str, Any]] = []
        partial_matches: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        for item in item_payloads:
            item_id = item.get("id")
            if item_id is None:
                continue
            try:
                normalized_id = int(item_id)
            except (TypeError, ValueError):
                continue
            if normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)

            item_name = self._tracker_item_display_name(item)
            normalized_item = item_name.casefold()
            payload = {
                "id": normalized_id,
                "name": item_name or lookup_text,
                "type": "TrackerItemReference",
            }
            if normalized_item == normalized_lookup:
                exact_matches.append(payload)
            else:
                partial_matches.append(payload)

        return exact_matches or partial_matches

    def get_user(self, user_id: int) -> UserInfo:
        """사용자 ID로 사용자 상세 정보를 가져온다."""
        return UserInfo.from_raw(
            self._run_rate_limited_request("get_user", lambda: self._get(f"/v3/users/{user_id}"))
        )

    def get_user_by_name(self, name: str) -> UserInfo:
        """이름으로 사용자를 바로 한 건 조회한다."""
        return UserInfo.from_raw(
            self._run_rate_limited_request(
                "get_user_by_name",
                lambda: self._get("/v3/users/findByName", params={"name": name}),
            )
        )

    def get_user_by_email(self, email: str) -> UserInfo:
        """이메일 주소로 사용자를 바로 한 건 조회한다."""
        return UserInfo.from_raw(
            self._run_rate_limited_request(
                "get_user_by_email",
                lambda: self._get("/v3/users/findByEmail", params={"email": email}),
            )
        )

    def search_users(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        user_status: str | None = None,
        project_id: int | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> dict:
        """조건에 맞는 사용자 검색 결과를 원본 JSON 형태로 돌려준다."""
        params = {
            "page": page,
            "pageSize": min(page_size, 500),
        }
        body = {
            "name": name,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "userStatus": user_status,
            "projectId": project_id,
        }
        body = {key: value for key, value in body.items() if value not in (None, "")}
        # 조회용 POST라 다시 보내도 서버 상태가 바뀌지 않는다.
        return self._run_rate_limited_request(
            "search_users",
            lambda: self._post("/v3/users/search", json_body=body, params=params),
        )

    def create_item(self, tracker_id: int, payload: dict, parent_item_id: int | None = None) -> dict:
        """트래커에 새 아이템을 만들고 서버 응답을 돌려준다."""
        params = {}
        if parent_item_id is not None:
            params["parentItemId"] = parent_item_id
        return self._run_rate_limited_request(
            "create_item",
            lambda: self._post(f"/v3/trackers/{tracker_id}/items", json_body=payload, params=params),
        )

    def update_item(self, item_id: int, payload: dict) -> dict:
        """기존 아이템을 갱신하고 서버 응답을 돌려준다."""
        return self._run_rate_limited_request(
            "update_item",
            lambda: self._put(f"/v3/items/{int(item_id)}", json_body=payload),
        )

    def update_item_fields(self, item_id: int, field_values: list[dict]) -> dict:
        """지정한 필드만 갱신하고 나머지 아이템 상태는 유지한다."""
        return self._run_rate_limited_request(
            "update_item_fields",
            lambda: self._put(
                f"/v3/items/{int(item_id)}/fields",
                json_body={"fieldValues": list(field_values)},
            ),
        )

    def bulk_update_item_fields(
        self,
        operations: list[dict],
        *,
        atomic: bool = True,
    ) -> dict:
        """여러 아이템의 지정 필드를 한 번의 v3 bulk 요청으로 갱신한다."""
        return self._run_rate_limited_request(
            "bulk_update_item_fields",
            lambda: self._put(
                "/v3/items/fields",
                json_body=list(operations),
                params={"atomic": str(bool(atomic)).lower()},
            ),
        )

    def delete_item(self, item_id: int) -> dict:
        """트래커 아이템 한 개를 삭제한다."""
        return self._run_rate_limited_request(
            "delete_item",
            lambda: self._delete(f"/v3/items/{int(item_id)}"),
        )

    @staticmethod
    def _retry_after_seconds(exc: Exception) -> float | None:
        """429 응답이 알려 준 대기 시간(초). 없거나 날짜 형식이면 None."""
        headers: Any = getattr(getattr(exc, "response", None), "headers", None)
        raw_value = headers.get("Retry-After") if hasattr(headers, "get") else None
        try:
            seconds = float(str(raw_value).strip())
        except (TypeError, ValueError):
            return None
        return seconds if seconds >= 0 else None

    def _run_rate_limited_request(self, request_name: str, request_func) -> Any:
        """rate limit 재시도를 포함해 요청을 실행한다."""
        attempts = self.rate_limit_max_retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            context_token = _API_REQUEST_CONTEXT.set((request_name, attempt, attempts))
            try:
                return request_func()
            except Exception as exc:
                last_exc = exc
                if not self._is_rate_limited(exc) or attempt >= attempts:
                    raise

                delay_seconds = self.rate_limit_retry_delay_seconds * attempt
                retry_after = self._retry_after_seconds(exc)
                if retry_after is not None:
                    delay_seconds = max(delay_seconds, min(retry_after, MAX_RETRY_AFTER_SECONDS))
                delay_seconds += delay_seconds * RETRY_JITTER_RATIO * float(self._jitter_fn())
                if self.logger is not None:
                    self.logger.warning(
                        "%s rate limited; retrying in %.2fs (attempt %s/%s)",
                        request_name,
                        delay_seconds,
                        attempt,
                        attempts,
                    )
                self._sleep_fn(delay_seconds)
            finally:
                _API_REQUEST_CONTEXT.reset(context_token)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{request_name} retry loop exited unexpectedly")
