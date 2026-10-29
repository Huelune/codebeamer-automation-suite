"""todo.md 1절 스크립트가 서버 주소·이름·값 없이 한 화면에 결과를 찍는지 확인한다.

스크립트와 절을 지울 때 이 테스트도 함께 지운다.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "todo_check_baseline_created_time.py"
_spec = importlib.util.spec_from_file_location("todo_check_baseline_created_time", SCRIPT)
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

BASE_URL = "https://secret-host.test/secret-context"


class FakeClient:
    single: Any = None
    listed: Any = None

    def __init__(self, base_url: str, username: str, password: str, logger: Any = None) -> None:
        self.base_url = base_url

    def get_tracker_baselines(self, tracker_id: int) -> list[dict[str, Any]]:
        return [{"id": 777001, "name": "secret baseline"}, {"id": 777002, "name": "secret newer"}]

    def get_tracker(self, tracker_id: int) -> dict[str, Any]:
        return {"id": tracker_id, "name": "secret tracker", "project": {"id": 333001, "name": "secret project"}}

    def _get(self, path: str, params: Any = None) -> Any:
        value = self.single if path.startswith("/v3/baselines/") else self.listed
        if isinstance(value, Exception):
            raise value
        return value

    def search_items(self, **kwargs: Any) -> dict[str, Any]:
        return {"items": [
            {"id": 900001, "name": "secret item", "modifiedAt": "2026-01-01T09:00:00.000"},
            {"id": 900002, "name": "secret item", "modifiedAt": "2026-01-01T10:00:00.000"},
        ]}


class HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"{status} for url {BASE_URL}/secret-path")
        self.response = SimpleNamespace(status_code=status)


def run_script(single: Any, listed: Any, *arguments: str) -> str:
    settings = SimpleNamespace(base_url=BASE_URL, username="secret-user", password="secret-password")
    output = io.StringIO()
    with (
        patch("os.system"),
        patch("sys.argv", ["script", *arguments]),
        patch("src.gui.settings_store.GuiSettingsStore.load", return_value=settings),
        patch("src.codebeamer_client.CodebeamerClient", FakeClient),
        patch.object(FakeClient, "single", single),
        patch.object(FakeClient, "listed", listed),
        contextlib.redirect_stdout(output),
    ):
        script.main()
    return output.getvalue()


def assert_no_internal_values(test: unittest.TestCase, output: str) -> None:
    test.assertNotIn("secret", output)
    for value in ("123456", "777002", "333001", "900001", "2026-01-01"):
        test.assertNotIn(value, output)
    test.assertLessEqual(len(output.splitlines()), 40)
    test.assertTrue(all(len(line) <= 120 for line in output.splitlines()))


class TodoCheckBaselineCreatedTimeTest(unittest.TestCase):
    def test_creation_time_after_every_item_is_usable(self) -> None:
        single = {
            "id": 777002,
            "name": "secret newer",
            "description": "secret text",
            "createdAt": "2026-01-01T11:30:00.000",
            "createdBy": {"id": 1, "name": "secret-user"},
            "secret key with spaces": "secret value",
        }
        listed = {"page": 1, "baselines": [{"id": 777002, "name": "secret newer", "type": "BaselineReference"}]}

        output = run_script(single, listed, "123456")

        assert_no_internal_values(self, output)
        self.assertIn("[대상] 가장 최근 Baseline (트래커 Baseline 2개)", output)
        self.assertIn("createdAt(시각)", output)
        self.assertIn("createdBy(dict)", output)
        self.assertIn("외 1개", output)
        self.assertIn("[프로젝트 Baseline 목록] 키 3개: id(int), name(str), type(str)", output)
        self.assertIn("단건 createdAt: 이 시각보다 늦게 수정된 아이템 0개, 가장 늦은 수정보다 90분 뒤", output)
        self.assertIn("판정: 만든 시각으로 쓸 수 있는 값 있음", output)

    def test_time_before_item_changes_is_not_creation_time(self) -> None:
        listed = [{"id": 777001, "modifiedAt": "2026-01-01T09:30:00Z"}]

        output = run_script(HttpError(404), listed, "123456", "777001")

        assert_no_internal_values(self, output)
        self.assertIn("[Baseline 단건] 실패: HTTP 404", output)
        self.assertIn("목록 modifiedAt: 이 시각보다 늦게 수정된 아이템 1개", output)
        self.assertIn("판정: 시각 값이 Baseline 아이템 수정보다 앞섬", output)

    def test_no_time_key_points_to_the_single_version_approach(self) -> None:
        output = run_script({"id": 777002, "name": "secret"}, {"baselines": []}, "123456")

        assert_no_internal_values(self, output)
        self.assertIn("[프로젝트 Baseline 목록] 항목 0개 중 이 Baseline 없음", output)
        self.assertIn("판정: 만든 시각 없음", output)

    def test_missing_tracker_id_is_explained(self) -> None:
        self.assertIn("실패: 트래커 ID 없음", run_script(None, None))


if __name__ == "__main__":
    unittest.main()
