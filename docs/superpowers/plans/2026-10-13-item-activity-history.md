# 아이템 활동 이력 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Baseline 비교 탭과 상세 창의 `변경 이력` 탭에서 기준 Baseline 이후 구간과 이력 유형(필드 변경·댓글·첨부)을 골라 필드별 변경량을 보고, 그 범위를 Excel로 내보낸다.

**Architecture:** Qt에 기대지 않는 모델 모듈(`item_activity.py`)이 이력·댓글·첨부를 활동 항목으로 바꾸고 거르고 요약한다. 화면 모듈(`item_activity_panel.py`)이 도구줄·요약 표·시간순 트리를 묶어 비교 탭과 상세 창에 같은 모양으로 들어가고, 조회는 소유자 콜백에 맡긴다. Excel 모듈(`item_activity_export.py`)은 패널이 만든 요청 하나로 통합 문서를 만든다.

**Tech Stack:** Python 3.13, PySide6, openpyxl, unittest, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-10-13-item-activity-history-design.md`

## Global Constraints

- 사용자에게 보이는 글, 커밋 메시지, 코드 주석은 한국어. 식별자는 영어.
- 커밋: Conventional Commits, summary는 명사형(`~ 추가`), 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 기능을 설명하는 문서는 그 기능 커밋에 함께 넣는다.
- 각 커밋 전: `.venv\Scripts\python.exe -m ruff check .`, `.venv\Scripts\python.exe -m mypy`, `.venv\Scripts\python.exe -m unittest discover -s tests -q` 통과.
- GUI 테스트는 `QT_QPA_PLATFORM=offscreen`. 새 GUI 테스트 모듈은 `from tests.gui_widget_cleanup import tearDownModule  # noqa: F401`을 둔다.
- import는 한 줄에 하나(`force-single-line`), import 뒤 빈 줄 2개. 줄 길이 120. ruff가 줄 길이를 지적하면 괄호 안에서 줄을 나눈다.
- 재내보내기 모듈을 만들지 않는다. mypy 제외 목록에 새 모듈을 넣지 않는다.
- 샘플 데이터와 테스트 fixture는 익명 값만 쓴다(`Sample User A`, `anonymous-*.txt`).
- 구간 경계: Baseline 생성 시각과 같은 시각의 항목은 Baseline에 들어간 것으로 보고 `기준 Baseline 이후`에서 제외한다.
- 관계 유형은 비활성 체크로만 두고 툴팁 `서버 응답에 시각 정보가 없어 지원하지 않습니다`.

### 스펙에서 바꾼 점 두 가지

- 9절 `이력` 시트의 같은 버전 칸 세로 합치기를 하지 않고 값을 행마다 반복한다. 합친 칸은 Excel 자동 필터와 정렬을 깨뜨려, 필드·사용자별로 걸러 보는 용도에 맞지 않는다. 대신 자동 필터를 건다.
- 7절의 유형별 `다시 시도` 버튼을 하나로 합친다. 실패한 유형만 다시 묻는다.
- 8절에서 상세 창 댓글을 댓글 탭의 `comments_requested`와 함께 쓰기로 했으나, 변경 이력 탭 전용 시그널 `activity_requested`로 받는다. Baseline 창은 댓글 탭을 막아 두므로 같은 시그널을 쓰면 막힘 조건이 엉킨다. 서비스 캐시가 같아 서버 요청은 늘지 않는다.

## Review Focus

1. 서버 시각이 `Z`가 아닌 `+09:00` 오프셋이나 소수 초를 달고 오면 Baseline 생성 시각(`Z`)과 같은 순간으로 비교해야 한다. Task 1에서 고정한다.
2. 아이템을 빠르게 바꿔 고르는 동안 앞 아이템 응답이 늦게 오면 버려야 한다. Task 4에서 고정한다.
3. 32,767자를 넘는 설명이나 댓글 본문도 Excel 저장이 실패하지 않고 `긴 값 전체보기` 시트로 넘어가야 한다. Task 3에서 고정한다.
4. 생성 시각이 없는 Baseline은 기준으로 고를 수 없어야 하고, 고를 수 있게 두면 구간이 전체로 조용히 바뀐다. Task 4에서 고정한다.
5. `=`, `+`, `@`, `-`로 시작하는 값이 수식으로 실행되지 않아야 한다. Task 3에서 고정한다.

## 파일 구조

| 파일 | 할 일 |
| --- | --- |
| `src/gui/item_activity.py` (새) | 활동 항목 모델, 변환, 병합, 구간 거르기, 필드별 요약, 서버 시각 해석, Baseline 이후 판정 |
| `src/gui/item_change_history_view.py` | 입력을 활동 항목으로 바꾸고 댓글·첨부 행 추가 |
| `src/gui/item_activity_panel.py` (새) | 도구줄·상태줄·요약 표·트리를 묶은 위젯, 내보내기 실행 함수 |
| `src/gui/item_activity_export.py` (새) | 내보내기 요청 모델과 통합 문서 생성·저장 |
| `src/gui/service_core.py` | 테스트 모드 첨부 목록 제공 |
| `src/gui/tracker_content_service.py` | 테스트 모드에서도 첨부 목록을 클라이언트로 조회 |
| `data/gui-offline-sample/offline_tracker_items.json` | 익명 첨부 두 건 |
| `src/gui/tracker_baseline_panel.py` | 이력 탭을 활동 패널로 교체 |
| `src/gui/tracker_baseline_workspace.py` | 유형별 조회와 내보내기 연결 |
| `src/gui/tracker_workspace.py` | 서비스 전달, Baseline 목록 보관, 오류 종류 등록 |
| `src/gui/activity_history.py` | 실행 기록 종류 `item_history_export` |
| `src/gui/tracker_item_detail_dialog.py` | 이력 탭을 활동 패널로 교체, Baseline 목록 받기 |
| `src/gui/tracker_detail_dialog.py` | 유형별 조회와 내보내기 연결 |
| `scripts/inspect_item_activity_contract.py` (새) | 실서버 응답 구조 확인 |
| `todo.md` (새) | 사용자가 돌릴 확인 절 |

---

### Task 1: 활동 이력 모델

**Files:**
- Create: `src/gui/item_activity.py`
- Test: `tests/test_gui_item_activity.py`

**Interfaces:**
- Consumes: `ItemHistorySnapshot`, `ItemFieldChange` (`tracker_item_context_models`), `ItemCommentsSnapshot` (`tracker_comment_models`), `AttachmentSummary` (`tracker_content_models`)
- Produces:
  - `ItemActivityKind(str, Enum)`: `FIELD_CHANGE`, `COMMENT`, `ATTACHMENT`
  - `ACTIVITY_KIND_LABELS: dict[ItemActivityKind, str]`
  - `ItemActivityEntry(kind, at="", by="", version=None, title="", changes=(), body="", change_summary="", edited=False, attachment_names=())`
  - `ActivityScope(label, after=None, until=None, versions=None, time_undetermined=False)`, `ALL_SCOPE`
  - `FilteredActivity(entries, untimed_count, undetermined_count)`
  - `FieldChangeSummary(field_name, first_value, last_value, change_count, last_at, last_by)`
  - `ItemActivitySummary(version_count, field_change_count, changed_field_count, versions_without_changes, comment_count, attachment_count, fields)`
  - `BaselineMarker(name, version=None, created_at=None)`
  - `parse_server_time(text) -> datetime | None`
  - `history_entries(snapshot) -> tuple[ItemActivityEntry, ...]`
  - `comment_entries(snapshot) -> tuple[ItemActivityEntry, ...]`
  - `attachment_entries(attachments) -> tuple[ItemActivityEntry, ...]`
  - `merge_entries(*groups) -> tuple[ItemActivityEntry, ...]`
  - `baseline_scope(name: str, created_at: str) -> ActivityScope | None`
  - `filter_entries(entries, *, scope, kinds) -> FilteredActivity`
  - `summarize(entries) -> ItemActivitySummary`
  - `is_after_baseline(entry, marker) -> bool`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gui_item_activity.py`:

```python
from __future__ import annotations

import unittest
from datetime import UTC
from datetime import datetime

from src.gui.item_activity import ALL_SCOPE
from src.gui.item_activity import ActivityScope
from src.gui.item_activity import BaselineMarker
from src.gui.item_activity import ItemActivityEntry
from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity import attachment_entries
from src.gui.item_activity import baseline_scope
from src.gui.item_activity import comment_entries
from src.gui.item_activity import filter_entries
from src.gui.item_activity import history_entries
from src.gui.item_activity import is_after_baseline
from src.gui.item_activity import merge_entries
from src.gui.item_activity import parse_server_time
from src.gui.item_activity import summarize
from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_item_context_models import ItemFieldChange
from src.gui.tracker_item_context_models import ItemHistorySnapshot


FIELD = ItemActivityKind.FIELD_CHANGE
COMMENT = ItemActivityKind.COMMENT
ATTACHMENT = ItemActivityKind.ATTACHMENT
ALL_KINDS = {FIELD, COMMENT, ATTACHMENT}


def _version(version: int, at: str, *changes: dict) -> dict:
    return {
        "itemRevision": {"version": version},
        "modifiedAt": at,
        "modifiedBy": {"displayName": "Sample User A"},
        "changes": list(changes),
    }


def _change(field_id: int, name: str, old: str | None, new: str | None) -> dict:
    return {
        "field": {"id": field_id, "name": name},
        "oldValue": None if old is None else {"fieldId": field_id, "value": old},
        "newValue": None if new is None else {"fieldId": field_id, "value": new},
    }


HISTORY = ItemHistorySnapshot.from_raw(
    {
        "versions": [
            _version(4, "2026-07-21T09:30:00Z", _change(101, "Risk Level", "Medium", "High")),
            _version(3, "2026-07-20T09:00:00Z", _change(101, "Risk Level", None, "Medium")),
            _version(2, "2026-07-19T08:00:00Z", _change(3, "Summary", "Old", "New")),
            {"itemRevision": {"version": 1}, "modifiedAt": "2026-07-01T00:00:00Z", "changeSummary": "Created"},
        ]
    }
)
COMMENTS = ItemCommentsSnapshot.from_raw(
    [
        {
            "id": 51001,
            "createdBy": {"displayName": "Sample User B"},
            "createdAt": "2026-07-20T09:10:00Z",
            "modifiedAt": "2026-07-20T11:00:00Z",
            "comment": "Review note",
            "attachments": [{"id": 52001, "name": "anonymous-evidence.txt"}],
        }
    ]
)
ATTACHMENTS = (
    AttachmentSummary(
        53001, "anonymous-spec.txt", size=2048, mime_type="text/plain", modified_at="2026-07-18T11:00:00Z"
    ),
    AttachmentSummary(53002, "anonymous-draft.txt", size=512, modified_at="2026-07-10T08:00:00Z"),
)


class ParseServerTimeTest(unittest.TestCase):
    def test_offsets_and_fractions_compare_as_the_same_instant(self) -> None:
        utc = parse_server_time("2026-07-15T09:00:00Z")
        self.assertEqual(parse_server_time("2026-07-15T18:00:00+09:00"), utc)
        self.assertEqual(parse_server_time("2026-07-15T09:00:00.000Z"), utc)
        # 시간대가 없으면 UTC로 본다.
        self.assertEqual(parse_server_time("2026-07-15T09:00:00"), utc)
        self.assertEqual(utc, datetime(2026, 7, 15, 9, tzinfo=UTC))

    def test_unreadable_text_is_none(self) -> None:
        for text in ("", None, "yesterday", "2026-13-01T00:00:00Z"):
            self.assertIsNone(parse_server_time(text))


class ConversionTest(unittest.TestCase):
    def test_history_comment_and_attachment_entries(self) -> None:
        history = history_entries(HISTORY)
        self.assertEqual([entry.version for entry in history], [4, 3, 2, 1])
        self.assertEqual(history[0].by, "Sample User A")
        self.assertEqual(history[0].changes[0].field_name, "Risk Level")
        self.assertEqual(history[3].change_summary, "Created")

        (comment,) = comment_entries(COMMENTS)
        self.assertEqual(
            (comment.kind, comment.at, comment.by, comment.title, comment.body, comment.edited),
            (COMMENT, "2026-07-20T09:10:00Z", "Sample User B", "댓글 #51001", "Review note", True),
        )
        self.assertEqual(comment.attachment_names, ("anonymous-evidence.txt",))

        spec, draft = attachment_entries(ATTACHMENTS)
        self.assertEqual((spec.kind, spec.title, spec.at), (ATTACHMENT, "anonymous-spec.txt", "2026-07-18T11:00:00Z"))
        self.assertEqual(spec.body, "2,048 bytes · text/plain")
        self.assertEqual(draft.body, "512 bytes")

    def test_merge_orders_newest_first_with_kind_tiebreak_and_untimed_last(self) -> None:
        untimed = ItemActivityEntry(COMMENT, at="")
        same_time_comment = ItemActivityEntry(COMMENT, at="2026-07-20T09:00:00Z")
        merged = merge_entries(
            (untimed, same_time_comment),
            history_entries(HISTORY),
            attachment_entries(ATTACHMENTS),
        )
        self.assertEqual(
            [(entry.kind, entry.version or entry.at) for entry in merged],
            [
                (FIELD, 4),
                (FIELD, 3),
                (COMMENT, "2026-07-20T09:00:00Z"),
                (FIELD, 2),
                (ATTACHMENT, "2026-07-18T11:00:00Z"),
                (ATTACHMENT, "2026-07-10T08:00:00Z"),
                (FIELD, 1),
                (COMMENT, ""),
            ],
        )


class FilterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = merge_entries(
            history_entries(HISTORY), comment_entries(COMMENTS), attachment_entries(ATTACHMENTS)
        )

    def test_all_scope_keeps_everything_of_the_chosen_kinds(self) -> None:
        result = filter_entries(self.entries, scope=ALL_SCOPE, kinds={FIELD})
        self.assertEqual([entry.version for entry in result.entries], [4, 3, 2, 1])
        self.assertEqual((result.untimed_count, result.undetermined_count), (0, 0))

    def test_baseline_scope_excludes_the_baseline_instant_itself(self) -> None:
        scope = baseline_scope("Sample Baseline", "2026-07-19T08:00:00Z")
        assert scope is not None
        self.assertEqual(scope.label, "Sample Baseline 이후")
        result = filter_entries(self.entries, scope=scope, kinds=ALL_KINDS)
        # 버전 2는 Baseline 생성 시각과 같아 Baseline에 들어간 것으로 본다.
        self.assertEqual(
            [(entry.kind, entry.version) for entry in result.entries],
            [(FIELD, 4), (COMMENT, None), (FIELD, 3)],
        )

    def test_baseline_without_created_at_has_no_scope(self) -> None:
        self.assertIsNone(baseline_scope("Sample Baseline", ""))

    def test_between_points_uses_versions_for_fields_and_times_for_the_rest(self) -> None:
        scope = ActivityScope(
            "비교 시점 사이",
            after=parse_server_time("2026-07-15T00:00:00Z"),
            until=parse_server_time("2026-07-20T09:00:00Z"),
            versions=(2, 4),
        )
        result = filter_entries(self.entries, scope=scope, kinds=ALL_KINDS)
        # 필드 변경은 버전 (2, 4], 댓글 09:10은 상한 뒤, 첨부 07-18만 구간 안.
        self.assertEqual(
            [(entry.kind, entry.version or entry.at) for entry in result.entries],
            [(FIELD, 4), (FIELD, 3), (ATTACHMENT, "2026-07-18T11:00:00Z")],
        )

    def test_undetermined_time_excludes_comments_and_attachments_but_not_fields(self) -> None:
        scope = ActivityScope("비교 시점 사이", versions=(0, 4), time_undetermined=True)
        result = filter_entries(self.entries, scope=scope, kinds=ALL_KINDS)
        self.assertEqual({entry.kind for entry in result.entries}, {FIELD})
        self.assertEqual(result.undetermined_count, 3)

    def test_untimed_entries_are_counted_when_a_time_bound_applies(self) -> None:
        scope = baseline_scope("Sample Baseline", "2026-07-01T00:00:00Z")
        assert scope is not None
        result = filter_entries((ItemActivityEntry(COMMENT, at="unknown"),), scope=scope, kinds=ALL_KINDS)
        self.assertEqual((result.entries, result.untimed_count), ((), 1))


class SummaryTest(unittest.TestCase):
    def test_fields_are_grouped_by_id_with_first_and_last_values(self) -> None:
        entries = merge_entries(history_entries(HISTORY), comment_entries(COMMENTS), attachment_entries(ATTACHMENTS))
        summary = summarize(entries)
        self.assertEqual(
            (
                summary.version_count,
                summary.field_change_count,
                summary.changed_field_count,
                summary.versions_without_changes,
                summary.comment_count,
                summary.attachment_count,
            ),
            (4, 3, 2, 1, 1, 2),
        )
        risk, title = summary.fields
        self.assertEqual(
            (risk.field_name, risk.first_value, risk.last_value, risk.change_count, risk.last_at, risk.last_by),
            ("Risk Level", None, "High", 2, "2026-07-21T09:30:00Z", "Sample User A"),
        )
        self.assertEqual(
            (title.field_name, title.first_value, title.last_value, title.change_count),
            ("Summary", "Old", "New", 1),
        )

    def test_fields_without_id_are_grouped_by_name(self) -> None:
        entries = (
            ItemActivityEntry(FIELD, at="2026-07-02", version=2, changes=(ItemFieldChange("Note", "b", "c"),)),
            ItemActivityEntry(FIELD, at="2026-07-01", version=1, changes=(ItemFieldChange("Note", "a", "b"),)),
        )
        (note,) = summarize(entries).fields
        self.assertEqual((note.first_value, note.last_value, note.change_count), ("a", "c", 2))


class BaselineMarkerTest(unittest.TestCase):
    def test_fields_use_version_and_others_use_time(self) -> None:
        marker = BaselineMarker("Baseline #7", version=2, created_at=parse_server_time("2026-07-19T08:00:00Z"))
        self.assertTrue(is_after_baseline(ItemActivityEntry(FIELD, version=3), marker))
        self.assertFalse(is_after_baseline(ItemActivityEntry(FIELD, version=2), marker))
        self.assertTrue(is_after_baseline(ItemActivityEntry(COMMENT, at="2026-07-20T00:00:00Z"), marker))
        self.assertFalse(is_after_baseline(ItemActivityEntry(COMMENT, at="2026-07-19T08:00:00Z"), marker))
        # 시각을 모르면 이후로 표시하지 않는다.
        self.assertFalse(is_after_baseline(ItemActivityEntry(COMMENT, at=""), marker))
        no_time = BaselineMarker("B", 2)
        self.assertFalse(is_after_baseline(ItemActivityEntry(COMMENT, at="2026-07-20T00:00:00Z"), no_time))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_activity -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.gui.item_activity'`

- [ ] **Step 3: 구현**

`src/gui/item_activity.py`:

```python
"""아이템 활동 이력 모델.

변경 이력·댓글·첨부 응답을 시간순 활동 항목 하나의 모양으로 바꾸고, 구간과 유형으로 거르고,
필드별로 얼마나 바뀌었는지 요약한다. 화면과 Excel 내보내기가 같은 결과를 쓰도록 Qt에 기대지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from enum import Enum
from typing import Any

from .tracker_comment_models import ItemCommentsSnapshot
from .tracker_content_models import AttachmentSummary
from .tracker_item_context_models import ItemFieldChange
from .tracker_item_context_models import ItemHistorySnapshot


class ItemActivityKind(str, Enum):
    FIELD_CHANGE = "field_change"
    COMMENT = "comment"
    ATTACHMENT = "attachment"


ACTIVITY_KIND_LABELS = {
    ItemActivityKind.FIELD_CHANGE: "필드 변경",
    ItemActivityKind.COMMENT: "댓글",
    ItemActivityKind.ATTACHMENT: "첨부",
}

# 같은 시각이면 필드 변경, 댓글, 첨부 순으로 보인다.
_KIND_ORDER = {ItemActivityKind.FIELD_CHANGE: 0, ItemActivityKind.COMMENT: 1, ItemActivityKind.ATTACHMENT: 2}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ItemActivityEntry:
    """시간순으로 늘어놓는 이력 한 건. 필드 변경 버전 하나, 댓글 하나, 첨부 하나가 각각 한 항목이다."""

    kind: ItemActivityKind
    at: str = ""
    by: str = ""
    # 필드 변경만 쓴다.
    version: int | None = None
    # 댓글은 `댓글 #ID`, 첨부는 파일명.
    title: str = ""
    changes: tuple[ItemFieldChange, ...] = ()
    # 댓글 본문, 첨부 크기·형식.
    body: str = ""
    # 바뀐 필드 정보가 없는 버전의 서버 요약.
    change_summary: str = ""
    # 댓글을 만든 뒤 고쳤는지.
    edited: bool = False
    # 댓글에 붙은 첨부 파일명.
    attachment_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActivityScope:
    """화면과 내보내기에 넣을 항목의 범위.

    `after` 뒤(같은 시각 제외)부터 `until`까지(같은 시각 포함)의 항목을 남긴다. `versions`가 있으면 필드 변경은
    시각 대신 버전 (낮은 버전 제외, 높은 버전 포함)으로 고른다. `time_undetermined`면 시각 구간을 정할 수 없어
    댓글·첨부를 뺀다.
    """

    label: str
    after: datetime | None = None
    until: datetime | None = None
    versions: tuple[int, int] | None = None
    time_undetermined: bool = False


ALL_SCOPE = ActivityScope("전체")


@dataclass(frozen=True)
class FilteredActivity:
    entries: tuple[ItemActivityEntry, ...]
    # 시각 구간이 있는데 시각을 읽지 못해 뺀 항목 수.
    untimed_count: int = 0
    # 시각 구간을 정할 수 없어 뺀 댓글·첨부 수.
    undetermined_count: int = 0


@dataclass(frozen=True)
class FieldChangeSummary:
    field_name: str
    # 구간에서 가장 이른 변경의 이전 값과 가장 늦은 변경의 새 값.
    first_value: Any
    last_value: Any
    change_count: int
    last_at: str
    last_by: str


@dataclass(frozen=True)
class ItemActivitySummary:
    version_count: int = 0
    field_change_count: int = 0
    changed_field_count: int = 0
    versions_without_changes: int = 0
    comment_count: int = 0
    attachment_count: int = 0
    fields: tuple[FieldChangeSummary, ...] = ()


@dataclass(frozen=True)
class BaselineMarker:
    """Baseline 상세 창에서 `[Baseline 이후]`를 가르는 기준. 필드 변경은 버전, 나머지는 생성 시각으로 본다."""

    name: str
    version: int | None = None
    created_at: datetime | None = None


def parse_server_time(text: Any) -> datetime | None:
    """서버 시각 글자를 시간대가 있는 시각으로 읽는다. 시간대가 없으면 UTC로 보고, 못 읽으면 None."""
    value = str(text or "").strip()
    if not value:
        return None
    if value[-1] in "Zz":
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def history_entries(snapshot: ItemHistorySnapshot) -> tuple[ItemActivityEntry, ...]:
    return tuple(
        ItemActivityEntry(
            ItemActivityKind.FIELD_CHANGE,
            at=entry.modified_at,
            by=entry.modified_by,
            version=entry.version,
            changes=entry.changes,
            change_summary=entry.change_summary,
        )
        for entry in snapshot.entries
    )


def comment_entries(snapshot: ItemCommentsSnapshot) -> tuple[ItemActivityEntry, ...]:
    return tuple(
        ItemActivityEntry(
            ItemActivityKind.COMMENT,
            at=comment.created_at,
            by=comment.author,
            title=f"댓글 #{comment.comment_id}" if comment.comment_id else "댓글",
            body=comment.body,
            edited=bool(comment.modified_at and comment.created_at and comment.modified_at != comment.created_at),
            attachment_names=tuple(attachment.name for attachment in comment.attachments),
        )
        for comment in snapshot.comments
    )


def attachment_entries(attachments: Iterable[AttachmentSummary]) -> tuple[ItemActivityEntry, ...]:
    entries = []
    for attachment in attachments:
        details = [f"{attachment.size:,} bytes" if attachment.size is not None else "", attachment.mime_type]
        entries.append(
            ItemActivityEntry(
                ItemActivityKind.ATTACHMENT,
                at=attachment.modified_at,
                title=attachment.name,
                body=" · ".join(detail for detail in details if detail),
            )
        )
    return tuple(entries)


def merge_entries(*groups: Iterable[ItemActivityEntry]) -> tuple[ItemActivityEntry, ...]:
    """최신부터 늘어놓는다. 시각을 읽을 수 없는 항목은 맨 뒤에 둔다."""

    def order(entry: ItemActivityEntry) -> tuple[bool, datetime, int, int]:
        at = parse_server_time(entry.at)
        version = entry.version if entry.version is not None else -1
        return at is not None, at or _EPOCH, -_KIND_ORDER[entry.kind], version

    return tuple(sorted((entry for group in groups for entry in group), key=order, reverse=True))


def baseline_scope(name: str, created_at: str) -> ActivityScope | None:
    """그 Baseline 생성 시각 뒤만 남기는 구간. 생성 시각이 없으면 기준으로 쓸 수 없다."""
    after = parse_server_time(created_at)
    if after is None:
        return None
    return ActivityScope(f"{name} 이후", after=after)


def filter_entries(
    entries: Iterable[ItemActivityEntry],
    *,
    scope: ActivityScope,
    kinds: set[ItemActivityKind],
) -> FilteredActivity:
    kept: list[ItemActivityEntry] = []
    untimed = 0
    undetermined = 0
    for entry in entries:
        if entry.kind not in kinds:
            continue
        if entry.kind is ItemActivityKind.FIELD_CHANGE and scope.versions is not None:
            low, high = scope.versions
            if entry.version is not None and low < entry.version <= high:
                kept.append(entry)
            continue
        if entry.kind is not ItemActivityKind.FIELD_CHANGE and scope.time_undetermined:
            undetermined += 1
            continue
        if scope.after is None and scope.until is None:
            kept.append(entry)
            continue
        at = parse_server_time(entry.at)
        if at is None:
            untimed += 1
            continue
        if scope.after is not None and at <= scope.after:
            continue
        if scope.until is not None and at > scope.until:
            continue
        kept.append(entry)
    return FilteredActivity(tuple(kept), untimed, undetermined)


def summarize(entries: Iterable[ItemActivityEntry]) -> ItemActivitySummary:
    """필드는 필드 ID가 있으면 ID, 없으면 이름으로 묶는다. 많이 바뀐 필드부터 둔다."""
    entries = tuple(entries)
    field_entries = sorted(
        (entry for entry in entries if entry.kind is ItemActivityKind.FIELD_CHANGE),
        key=lambda entry: (entry.version if entry.version is not None else -1, entry.at),
    )
    groups: dict[tuple[str, object], list[tuple[ItemActivityEntry, ItemFieldChange]]] = {}
    for entry in field_entries:
        for change in entry.changes:
            key: tuple[str, object] = (
                ("id", change.field_id) if change.field_id is not None else ("name", change.field_name)
            )
            groups.setdefault(key, []).append((entry, change))
    fields = []
    for changes in groups.values():
        _first_entry, first = changes[0]
        last_entry, last = changes[-1]
        fields.append(
            FieldChangeSummary(
                field_name=last.field_name,
                first_value=first.old_value,
                last_value=last.new_value,
                change_count=len(changes),
                last_at=last_entry.at,
                last_by=last_entry.by,
            )
        )
    fields.sort(key=lambda field: (-field.change_count, field.field_name.casefold()))
    return ItemActivitySummary(
        version_count=len(field_entries),
        field_change_count=sum(len(entry.changes) for entry in field_entries),
        changed_field_count=len(fields),
        versions_without_changes=sum(not entry.changes for entry in field_entries),
        comment_count=sum(entry.kind is ItemActivityKind.COMMENT for entry in entries),
        attachment_count=sum(entry.kind is ItemActivityKind.ATTACHMENT for entry in entries),
        fields=tuple(fields),
    )


def is_after_baseline(entry: ItemActivityEntry, marker: BaselineMarker) -> bool:
    if entry.kind is ItemActivityKind.FIELD_CHANGE and marker.version is not None and entry.version is not None:
        return entry.version > marker.version
    at = parse_server_time(entry.at)
    return marker.created_at is not None and at is not None and at > marker.created_at
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_activity -v`
Expected: 모든 테스트 PASS. 이어서 `.venv\Scripts\python.exe -m ruff check src/gui/item_activity.py tests/test_gui_item_activity.py`와 `.venv\Scripts\python.exe -m mypy` 통과.

- [ ] **Step 5: 커밋**

```bash
git add src/gui/item_activity.py tests/test_gui_item_activity.py
git commit -m "feat: 변경 이력·댓글·첨부를 합친 활동 이력 모델 추가" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: 이력 트리에 댓글·첨부 행

**Files:**
- Modify: `src/gui/item_change_history_view.py` (`show_entries`와 `_version_text` 교체)
- Modify: `src/gui/tracker_baseline_panel.py` (`set_history`의 호출 한 줄, 임시)
- Modify: `src/gui/tracker_item_detail_dialog.py` (`set_history`의 호출, 임시)
- Test: `tests/test_gui_item_change_history_view.py` (전체 교체)

**Interfaces:**
- Consumes: Task 1의 `ItemActivityEntry`, `ItemActivityKind`, `BaselineMarker`, `is_after_baseline`, `history_entries`, `merge_entries`
- Produces: `ItemChangeHistoryView.show_entries(entries: Sequence[ItemActivityEntry], *, current_version: int | None = None, baseline: BaselineMarker | None = None) -> None`. `history_time_text`, `MAX_CELL_TEXT`, `MAX_TOOLTIP_TEXT`는 그대로.

이 Task 뒤에도 상세 창과 비교 패널은 아직 옛 이력 탭을 쓴다. 두 호출부는 Task 6, 7에서 활동 패널로 바뀌므로, 여기서는 `history_entries(...)`와 `BaselineMarker`로 감싸 넘기는 최소 수정만 해 전체 테스트를 초록으로 유지한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gui_item_change_history_view.py` 전체:

```python
from __future__ import annotations

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.item_activity import BaselineMarker
from src.gui.item_activity import ItemActivityEntry
from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity import parse_server_time
from src.gui.item_change_history_view import MAX_CELL_TEXT
from src.gui.item_change_history_view import ItemChangeHistoryView
from src.gui.item_change_history_view import history_time_text
from src.gui.tracker_item_context_models import ItemFieldChange
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


FIELD = ItemActivityKind.FIELD_CHANGE


class ItemChangeHistoryViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _view(self) -> ItemChangeHistoryView:
        view = ItemChangeHistoryView()
        self.addCleanup(view.deleteLater)
        return view

    def test_versions_list_field_changes_with_long_values_shortened(self) -> None:
        long_text = "긴 설명 " * 200
        view = self._view()

        view.show_entries(
            (
                ItemActivityEntry(
                    FIELD,
                    at="2026-07-20T10:45:36.456",
                    by="Sample User A",
                    version=2,
                    changes=(
                        ItemFieldChange("Description", "짧은 설명", long_text),
                        ItemFieldChange(
                            "Owners",
                            None,
                            [{"id": 7001, "name": "Sample User A", "type": "UserReference"}],
                        ),
                    ),
                ),
                ItemActivityEntry(
                    FIELD, at="2026-07-19T08:00:00Z", by="Sample User B", version=1, change_summary="Created"
                ),
            ),
            current_version=2,
        )

        first = view.topLevelItem(0)
        self.assertEqual(first.text(0), "버전 2 (현재) · 2026-07-20 10:45 · Sample User A · 필드 2개")
        self.assertTrue(first.isExpanded())
        description = first.child(0)
        self.assertEqual(description.text(1), "짧은 설명")
        self.assertEqual(len(description.text(2)), MAX_CELL_TEXT)
        self.assertTrue(description.text(2).endswith("…"))
        self.assertGreater(len(description.toolTip(2)), MAX_CELL_TEXT)
        owners = first.child(1)
        self.assertEqual(owners.text(1), "-")
        self.assertIn("Sample User A", owners.text(2))
        second = view.topLevelItem(1)
        self.assertEqual(second.text(0), "버전 1 · 2026-07-19 08:00 · Sample User B")
        self.assertEqual(second.child(0).text(0), "Created")

    def test_comment_and_attachment_rows(self) -> None:
        view = self._view()

        view.show_entries(
            (
                ItemActivityEntry(
                    ItemActivityKind.COMMENT,
                    at="2026-07-20T09:10:00Z",
                    by="Sample User B",
                    title="댓글 #51001",
                    body="Review note",
                    edited=True,
                    attachment_names=("anonymous-evidence.txt",),
                ),
                ItemActivityEntry(
                    ItemActivityKind.ATTACHMENT,
                    at="2026-07-18T11:00:00Z",
                    title="anonymous-spec.txt",
                    body="2,048 bytes · text/plain",
                ),
            )
        )

        comment = view.topLevelItem(0)
        self.assertEqual(comment.text(0), "댓글 · 2026-07-20 09:10 · Sample User B (수정됨)")
        self.assertEqual(
            [comment.child(index).text(0) for index in range(comment.childCount())],
            ["Review note", "첨부: anonymous-evidence.txt"],
        )
        attachment = view.topLevelItem(1)
        self.assertEqual(
            attachment.text(0), "첨부 · 2026-07-18 11:00 · anonymous-spec.txt · 2,048 bytes · text/plain"
        )
        self.assertEqual(attachment.childCount(), 0)

    def test_baseline_boundary_is_placed_before_the_first_entry_inside_the_baseline(self) -> None:
        view = self._view()
        marker = BaselineMarker("Baseline #7", version=2, created_at=parse_server_time("2026-07-19T00:00:00Z"))
        entries = [
            ItemActivityEntry(FIELD, version=3),
            ItemActivityEntry(ItemActivityKind.COMMENT, at="2026-07-20T00:00:00Z", by="Sample User A"),
            ItemActivityEntry(FIELD, version=2),
            ItemActivityEntry(FIELD, version=1),
        ]

        view.show_entries(entries, baseline=marker)

        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            [
                "[Baseline 이후] 버전 3",
                "[Baseline 이후] 댓글 · 2026-07-20 00:00 · Sample User A",
                "── Baseline #7 시점 (버전 2) ──",
                "버전 2",
                "버전 1",
            ],
        )

        view.show_entries([ItemActivityEntry(FIELD, version=5)], baseline=marker)
        # Baseline 안쪽 이력이 없으면 구분선도 두지 않는다.
        self.assertEqual(view.topLevelItemCount(), 1)

    def test_time_text_keeps_unknown_shapes(self) -> None:
        self.assertEqual(history_time_text("2026-07-20T10:45:36.456"), "2026-07-20 10:45")
        self.assertEqual(history_time_text("2026-07-20T10:45:36Z"), "2026-07-20 10:45")
        self.assertEqual(history_time_text("yesterday"), "yesterday")
        self.assertEqual(history_time_text(""), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_change_history_view -v`
Expected: FAIL. `show_entries`가 `ItemActivityEntry`의 `at`·`by`를 읽지 못하고 `BaselineMarker`를 받지 못한다.

- [ ] **Step 3: 구현**

`src/gui/item_change_history_view.py`의 모듈 설명을 바꾼다.

```python
"""아이템 활동 이력을 시간순으로 보여 주는 트리.

상세 창과 Baseline 비교의 변경 이력 탭이 활동 패널 안에서 함께 쓴다.
필드 변경은 버전 줄 아래에 필드별 이전 값·새 값을 두고, 댓글은 본문, 첨부는 파일명 한 줄로 보인다.
값은 Baseline 비교와 같은 방식으로 글자로 바꾼다.
"""
```

import 구역에서 `from .tracker_item_context_models import ItemHistoryEntry`를 지우고 다음을 넣는다(`display_tracker_value` import는 둔다).

```python
from .item_activity import BaselineMarker
from .item_activity import ItemActivityEntry
from .item_activity import ItemActivityKind
from .item_activity import is_after_baseline
```

`show_entries`와 `_version_text`를 지우고 다음 메서드를 넣는다. `__init__`, `_add_spanned_row`, `_short`, `history_time_text`는 그대로 둔다.

```python
    def show_entries(
        self,
        entries: Sequence[ItemActivityEntry],
        *,
        current_version: int | None = None,
        baseline: BaselineMarker | None = None,
    ) -> None:
        """최신부터 보인다. `baseline`이 있으면 Baseline 안쪽의 첫 항목 앞에 구분선을 넣는다."""
        self.clear()
        boundary_shown = False
        for entry in entries:
            after_baseline = baseline is not None and is_after_baseline(entry, baseline)
            if baseline is not None and not after_baseline and not boundary_shown:
                version = f" (버전 {baseline.version})" if baseline.version is not None else ""
                boundary = self._add_spanned_row(f"── {baseline.name} 시점{version} ──")
                # 고를 일이 없는 구분선이라 흐리게 둔다.
                boundary.setDisabled(True)
                boundary_shown = True
            text = self._entry_text(entry, current_version)
            row = self._add_spanned_row(f"[Baseline 이후] {text}" if after_baseline else text)
            row.setToolTip(0, entry.at)
            font = row.font(0)
            font.setBold(True)
            row.setFont(0, font)
            if entry.kind is ItemActivityKind.FIELD_CHANGE:
                self._add_field_rows(row, entry)
            elif entry.kind is ItemActivityKind.COMMENT:
                self._add_text_row(row, entry.body or "(본문 없음)")
                if entry.attachment_names:
                    self._add_text_row(row, "첨부: " + ", ".join(entry.attachment_names))
        self.expandAll()

    def _add_field_rows(self, row: QTreeWidgetItem, entry: ItemActivityEntry) -> None:
        if not entry.changes:
            self._add_text_row(row, entry.change_summary or "바뀐 필드 정보가 없습니다.")
            return
        for change in entry.changes:
            values = [
                change.field_name,
                display_tracker_value(change.old_value),
                display_tracker_value(change.new_value),
            ]
            child = QTreeWidgetItem([_short(value, MAX_CELL_TEXT) for value in values])
            for column, value in enumerate(values):
                child.setToolTip(column, _short(value, MAX_TOOLTIP_TEXT))
            row.addChild(child)

    @staticmethod
    def _add_text_row(row: QTreeWidgetItem, text: str) -> None:
        child = QTreeWidgetItem([_short(text, MAX_CELL_TEXT)])
        child.setToolTip(0, _short(text, MAX_TOOLTIP_TEXT))
        row.addChild(child)
        child.setFirstColumnSpanned(True)

    @staticmethod
    def _entry_text(entry: ItemActivityEntry, current_version: int | None) -> str:
        time = history_time_text(entry.at)
        if entry.kind is ItemActivityKind.COMMENT:
            author = f"{entry.by} (수정됨)" if entry.edited and entry.by else entry.by
            parts = ["댓글", time, author]
        elif entry.kind is ItemActivityKind.ATTACHMENT:
            parts = ["첨부", time, entry.title, entry.body]
        else:
            version = f"버전 {entry.version}" if entry.version is not None else "버전 정보 없음"
            if entry.version is not None and entry.version == current_version:
                version += " (현재)"
            parts = [version, time, entry.by, f"필드 {len(entry.changes)}개" if entry.changes else ""]
        return " · ".join(part for part in parts if part)
```

호출부 임시 수정. Task 6, 7에서 이 부분은 활동 패널로 통째로 바뀐다.

`src/gui/tracker_baseline_panel.py`: import에 다음 두 줄을 더한다.

```python
from .item_activity import history_entries
from .item_activity import merge_entries
```

`set_history`의 `self.history_view.show_entries(entries)`를 다음으로 바꾼다.

```python
        self.history_view.show_entries(merge_entries(history_entries(ItemHistorySnapshot(tuple(entries)))))
```

`src/gui/tracker_item_detail_dialog.py`: import에 다음 세 줄을 더한다.

```python
from .item_activity import BaselineMarker
from .item_activity import history_entries
from .item_activity import merge_entries
```

`set_history`의 첫 `if`/`else` 블록을 다음으로 바꾼다(`later = ...`부터 끝은 그대로).

```python
        self._context_states["history"] = "loaded"
        entries = merge_entries(history_entries(snapshot))
        baseline_version = self.detail.version if self.baseline_id is not None else None
        if baseline_version is None:
            self.history_view.show_entries(entries, current_version=snapshot.current_version)
            status = f"변경 이력 {len(snapshot.entries)}건" if snapshot.entries else "변경 이력이 없습니다."
        else:
            # 이력은 아이템 전체 이력이다. 이 창의 버전이 Baseline 시점이므로 그 뒤 변경을 나눠 보인다.
            self.history_view.show_entries(
                entries,
                baseline=BaselineMarker(f"Baseline #{self.baseline_id}", version=baseline_version),
            )
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_change_history_view tests.test_gui_tracker_item_detail_dialog tests.test_gui_tracker_workspace -q`
Expected: PASS. 이어서 ruff, mypy 통과.

- [ ] **Step 5: 커밋**

```bash
git add src/gui/item_change_history_view.py src/gui/tracker_baseline_panel.py src/gui/tracker_item_detail_dialog.py tests/test_gui_item_change_history_view.py
git commit -m "feat: 변경 이력 트리의 댓글·첨부 행 표시" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: 활동 이력 Excel 내보내기 모듈

**Files:**
- Create: `src/gui/item_activity_export.py`
- Test: `tests/test_gui_item_activity_export.py`

**Interfaces:**
- Consumes: Task 1의 `ACTIVITY_KIND_LABELS`, `BaselineMarker`, `ItemActivityEntry`, `ItemActivityKind`, `ItemActivitySummary`, `is_after_baseline`. 기존 `excel_export_style`, `excel_long_value`, `display_tracker_value`.
- Produces:
  - `ItemActivityExportError(RuntimeError)`
  - `ItemActivityExportRequest(item_id: int, item_name: str, tracker_name: str, scope_label: str, kind_labels: tuple[str, ...], entries: tuple[ItemActivityEntry, ...], summary: ItemActivitySummary, baseline: BaselineMarker | None = None)`
  - `ItemActivityExportSummary(entry_count: int, row_count: int, long_value_count: int, output_path: str = "")`
  - `HISTORY_SHEET_TITLE = "이력"`
  - `create_item_activity_workbook(request, *, generated_at: datetime | None = None) -> tuple[Workbook, ItemActivityExportSummary]`
  - `export_item_activity_xlsx(request, output_path: str | Path) -> ItemActivityExportSummary`

`이력` 시트는 같은 버전의 칸을 합치지 않고 행마다 반복한다(위 "스펙에서 바꾼 점"). 시각 칸은 서버 원문을 그대로 쓴다. Excel에서 정렬해도 순서가 맞고, 화면용 시각 함수는 Qt 모듈에 있어 이 모듈이 기대지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gui_item_activity_export.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from src.gui.excel_long_value import LONG_VALUE_SHEET_TITLE
from src.gui.item_activity import BaselineMarker
from src.gui.item_activity import ItemActivityEntry
from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity import summarize
from src.gui.item_activity_export import HISTORY_SHEET_TITLE
from src.gui.item_activity_export import ItemActivityExportError
from src.gui.item_activity_export import ItemActivityExportRequest
from src.gui.item_activity_export import create_item_activity_workbook
from src.gui.item_activity_export import export_item_activity_xlsx
from src.gui.tracker_item_context_models import ItemFieldChange


FIELD = ItemActivityKind.FIELD_CHANGE
GENERATED = datetime(2026, 10, 13, 9, 0, 0)


def _request(*entries: ItemActivityEntry, baseline: BaselineMarker | None = None) -> ItemActivityExportRequest:
    return ItemActivityExportRequest(
        item_id=9001001,
        item_name="Sample requirement",
        tracker_name="Offline Requirements (ID 24680001)",
        scope_label="Offline Requirements Baseline 이후",
        kind_labels=("필드 변경", "댓글", "첨부"),
        entries=entries,
        summary=summarize(entries),
        baseline=baseline,
    )


ENTRIES = (
    ItemActivityEntry(
        FIELD,
        at="2026-07-20T09:00:00Z",
        by="Sample User A",
        version=3,
        changes=(ItemFieldChange("Risk Level", None, "Medium", 101), ItemFieldChange("Summary", "Old", "New", 3)),
    ),
    ItemActivityEntry(
        ItemActivityKind.COMMENT,
        at="2026-07-19T09:10:00Z",
        by="Sample User B",
        title="댓글 #51001",
        body="Review note",
        attachment_names=("anonymous-evidence.txt",),
    ),
    ItemActivityEntry(
        ItemActivityKind.ATTACHMENT, at="2026-07-18T11:00:00Z", title="anonymous-spec.txt", body="2,048 bytes"
    ),
    ItemActivityEntry(FIELD, at="2026-07-17T00:00:00Z", by="Sample User A", version=2, change_summary="Moved"),
)


def _rows(sheet) -> list[tuple]:
    return [tuple(cell.value for cell in row) for row in sheet.iter_rows()]


class ItemActivityExportTest(unittest.TestCase):
    def test_summary_field_and_history_sheets(self) -> None:
        workbook, summary = create_item_activity_workbook(_request(*ENTRIES), generated_at=GENERATED)

        self.assertEqual(workbook.sheetnames, ["요약", "필드별 요약", HISTORY_SHEET_TITLE])
        self.assertEqual((summary.entry_count, summary.row_count, summary.long_value_count), (4, 5, 0))
        overview = dict(_rows(workbook["요약"]))
        self.assertEqual(overview["아이템"], "#9001001 Sample requirement")
        self.assertEqual(overview["구간"], "Offline Requirements Baseline 이후")
        self.assertEqual(overview["유형"], "필드 변경, 댓글, 첨부")
        self.assertEqual(overview["생성 시각"], "2026-10-13T09:00:00")
        self.assertEqual((overview["버전"], overview["필드 변경"], overview["바뀐 필드"]), (2, 2, 2))
        self.assertEqual((overview["필드 변경 정보 없는 버전"], overview["댓글"], overview["첨부"]), (1, 1, 1))
        self.assertEqual(overview["긴 값 분할"], "없음")

        fields = _rows(workbook["필드별 요약"])
        self.assertEqual(fields[0], ("필드", "구간 처음 값", "구간 마지막 값", "변경 횟수", "마지막 수정 시각", "마지막 수정자"))
        self.assertIn(("Risk Level", "-", "Medium", 1, "2026-07-20T09:00:00Z", "Sample User A"), fields[1:])

        history = workbook[HISTORY_SHEET_TITLE]
        rows = _rows(history)
        self.assertEqual(rows[0], ("순번", "유형", "버전", "시각", "사용자", "대상", "이전 값", "새 값", "구간"))
        self.assertEqual(
            rows[1:],
            [
                (1, "필드 변경", 3, "2026-07-20T09:00:00Z", "Sample User A", "Risk Level", "-", "Medium", None),
                (1, "필드 변경", 3, "2026-07-20T09:00:00Z", "Sample User A", "Summary", "Old", "New", None),
                (2, "댓글", None, "2026-07-19T09:10:00Z", "Sample User B", "댓글 #51001", None,
                 "Review note\n\n첨부: anonymous-evidence.txt", None),
                (3, "첨부", None, "2026-07-18T11:00:00Z", None, "anonymous-spec.txt", None, "2,048 bytes", None),
                (4, "필드 변경", 2, "2026-07-17T00:00:00Z", "Sample User A", None, None, "Moved", None),
            ],
        )
        self.assertEqual(history.auto_filter.ref, "A1:I6")
        self.assertEqual(history.freeze_panes, "A2")

    def test_baseline_marker_fills_the_scope_column(self) -> None:
        marker = BaselineMarker("Baseline #7", version=2)
        workbook, _summary = create_item_activity_workbook(_request(*ENTRIES, baseline=marker), generated_at=GENERATED)

        scope_column = [row[8] for row in _rows(workbook[HISTORY_SHEET_TITLE])[1:]]
        # 필드 변경은 버전으로, 생성 시각을 모르는 Baseline이면 댓글·첨부는 표시하지 않는다.
        self.assertEqual(scope_column, ["Baseline 이후", "Baseline 이후", None, None, None])

    def test_long_values_move_to_the_long_value_sheet_with_links_both_ways(self) -> None:
        long_text = "가" * 40000
        entry = ItemActivityEntry(
            FIELD, at="2026-07-20T09:00:00Z", by="Sample User A", version=3,
            changes=(ItemFieldChange("Description", "짧은 설명", long_text, 80),),
        )

        workbook, summary = create_item_activity_workbook(_request(entry), generated_at=GENERATED)

        self.assertEqual(summary.long_value_count, 1)
        self.assertEqual(workbook.sheetnames[-1], LONG_VALUE_SHEET_TITLE)
        history_cell = workbook[HISTORY_SHEET_TITLE]["H2"]
        self.assertIn(LONG_VALUE_SHEET_TITLE, history_cell.value)
        self.assertEqual(history_cell.hyperlink.target, f"#'{LONG_VALUE_SHEET_TITLE}'!F2")
        long_rows = _rows(workbook[LONG_VALUE_SHEET_TITLE])
        self.assertEqual(long_rows[0], ("순번", "유형", "대상", "칸", "부분", "전체 내용", "이동"))
        self.assertEqual([row[4] for row in long_rows[1:]], ["1/2", "2/2"])
        self.assertEqual("".join(row[5] for row in long_rows[1:]), long_text)
        self.assertEqual(workbook[LONG_VALUE_SHEET_TITLE]["G2"].hyperlink.target, f"#'{HISTORY_SHEET_TITLE}'!H2")
        overview = dict(_rows(workbook["요약"]))
        self.assertEqual(overview["긴 값 분할"], "1개 값")

    def test_formula_like_values_are_written_as_text(self) -> None:
        entry = ItemActivityEntry(
            FIELD, at="2026-07-20T09:00:00Z", by="Sample User A", version=3,
            changes=(ItemFieldChange("=Field", "+1", "=HYPERLINK(\"x\")", 5), ItemFieldChange("Note", "-", "@x", 6)),
        )

        workbook, _summary = create_item_activity_workbook(_request(entry), generated_at=GENERATED)

        rows = _rows(workbook[HISTORY_SHEET_TITLE])
        self.assertEqual(rows[1][5:8], ("'=Field", "'+1", "'=HYPERLINK(\"x\")"))
        # 빈 값 표시 "-"는 그대로 둔다.
        self.assertEqual(rows[2][5:8], ("Note", "-", "'@x"))
        for row in workbook[HISTORY_SHEET_TITLE].iter_rows(min_row=2):
            for cell in row:
                self.assertNotEqual(cell.data_type, "f")

    def test_empty_request_is_rejected(self) -> None:
        with self.assertRaises(ItemActivityExportError):
            create_item_activity_workbook(_request())

    def test_export_saves_xlsx_without_leaving_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "item_history"

            summary = export_item_activity_xlsx(_request(*ENTRIES), target)

            saved = Path(summary.output_path)
            self.assertEqual(saved.suffix, ".xlsx")
            self.assertTrue(saved.is_file())
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), ["item_history.xlsx"])
            self.assertEqual(load_workbook(saved).sheetnames, ["요약", "필드별 요약", HISTORY_SHEET_TITLE])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_activity_export -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.gui.item_activity_export'`

- [ ] **Step 3: 구현**

`src/gui/item_activity_export.py`:

```python
"""아이템 활동 이력 Excel 내보내기.

화면에서 거른 구간과 유형의 항목을 그대로 받아 요약, 필드별 요약, 이력, 긴 값 전체보기 시트를 만든다.
서버에 다시 묻지 않는다.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import Cell
from openpyxl.utils import get_column_letter

from .excel_export_style import BODY_FONT
from .excel_export_style import CENTER_WRAP
from .excel_export_style import EXCEL_MAX_CELL_LINE_FEEDS
from .excel_export_style import EXCEL_MAX_CELL_TEXT
from .excel_export_style import GROUP_FILL
from .excel_export_style import HEADER_FILL
from .excel_export_style import HEADER_FONT
from .excel_export_style import LINK_FONT
from .excel_export_style import THIN_BORDER
from .excel_export_style import TOP_WRAP
from .excel_export_style import WHITE_FONT
from .excel_export_style import normalize_excel_text
from .excel_long_value import LONG_VALUE_SHEET_TITLE
from .excel_long_value import cell_preview
from .excel_long_value import long_value_preview
from .excel_long_value import requires_long_value_sheet
from .excel_long_value import split_long_value
from .item_activity import ACTIVITY_KIND_LABELS
from .item_activity import BaselineMarker
from .item_activity import ItemActivityEntry
from .item_activity import ItemActivityKind
from .item_activity import ItemActivitySummary
from .item_activity import is_after_baseline
from .tracker_baseline_compare import display_tracker_value


EXCEL_MAX_ROWS = 1048576
HISTORY_SHEET_TITLE = "이력"
_HISTORY_HEADERS = ("순번", "유형", "버전", "시각", "사용자", "대상", "이전 값", "새 값", "구간")
_HISTORY_WIDTHS = (8, 11, 8, 22, 18, 26, 40, 40, 14)
_VALUE_COLUMNS = (7, 8)
_FIELD_HEADERS = ("필드", "구간 처음 값", "구간 마지막 값", "변경 횟수", "마지막 수정 시각", "마지막 수정자")
_FIELD_WIDTHS = (26, 40, 40, 10, 22, 18)
_LONG_HEADERS = ("순번", "유형", "대상", "칸", "부분", "전체 내용", "이동")
_LONG_WIDTHS = (8, 11, 26, 10, 8, 80, 14)


class ItemActivityExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ItemActivityExportRequest:
    """화면에서 거른 결과 그대로. 내보내기는 이 값만으로 통합 문서를 만든다."""

    item_id: int
    item_name: str
    tracker_name: str
    scope_label: str
    kind_labels: tuple[str, ...]
    entries: tuple[ItemActivityEntry, ...]
    summary: ItemActivitySummary
    # Baseline 상세 창에서만 둔다. `구간` 칸에 `Baseline 이후`를 적는다.
    baseline: BaselineMarker | None = None


@dataclass(frozen=True)
class ItemActivityExportSummary:
    entry_count: int
    row_count: int
    long_value_count: int
    output_path: str = ""


@dataclass(frozen=True)
class _LongValue:
    number: int
    kind: str
    target: str
    column: str
    parts: tuple[str, ...]
    start_row: int
    source: str


def create_item_activity_workbook(
    request: ItemActivityExportRequest,
    *,
    generated_at: datetime | None = None,
) -> tuple[Workbook, ItemActivityExportSummary]:
    if not request.entries:
        raise ItemActivityExportError("내보낼 이력이 없습니다.")
    rows = _history_rows(request)
    if len(rows) + 1 > EXCEL_MAX_ROWS:
        raise ItemActivityExportError(
            f"아이템 #{request.item_id}의 이력이 Excel 행 한도({EXCEL_MAX_ROWS:,}행)를 넘습니다."
        )
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "요약"
    field_sheet = workbook.create_sheet("필드별 요약")
    history_sheet = workbook.create_sheet(HISTORY_SHEET_TITLE)
    long_values = _populate_history(history_sheet, rows, item_id=request.item_id)
    if long_values:
        _populate_long_values(workbook.create_sheet(LONG_VALUE_SHEET_TITLE), long_values)
    _populate_fields(field_sheet, request.summary)
    _populate_summary(
        summary_sheet,
        request,
        generated_at=generated_at or datetime.now().astimezone(),
        long_value_count=len(long_values),
    )
    workbook.properties.title = "Codebeamer 아이템 변경 이력"
    workbook.properties.subject = f"#{request.item_id}"
    workbook.properties.creator = "Codebeamer Automation Suite"
    return workbook, ItemActivityExportSummary(len(request.entries), len(rows), len(long_values))


def export_item_activity_xlsx(
    request: ItemActivityExportRequest,
    output_path: str | Path,
) -> ItemActivityExportSummary:
    path = Path(output_path).expanduser()
    if path.suffix.casefold() != ".xlsx":
        path = path.with_suffix(".xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook, summary = create_item_activity_workbook(request)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}-", suffix=".xlsx", dir=path.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        workbook.save(temporary_path)
        temporary_path.replace(path)
    except Exception as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ItemActivityExportError("Excel 파일을 저장하지 못했습니다.") from exc
    return ItemActivityExportSummary(
        summary.entry_count, summary.row_count, summary.long_value_count, output_path=str(path)
    )


def _history_rows(request: ItemActivityExportRequest) -> list[tuple[Any, ...]]:
    """항목마다 순번을 붙이고, 필드 변경은 바뀐 필드마다 한 행으로 편다."""
    rows: list[tuple[Any, ...]] = []
    for number, entry in enumerate(request.entries, start=1):
        kind = ACTIVITY_KIND_LABELS[entry.kind]
        after = request.baseline is not None and is_after_baseline(entry, request.baseline)
        scope = "Baseline 이후" if after else ""
        version = entry.version if entry.version is not None else ""
        if entry.kind is ItemActivityKind.FIELD_CHANGE and entry.changes:
            for change in entry.changes:
                rows.append(
                    (
                        number, kind, version, entry.at, entry.by, change.field_name,
                        display_tracker_value(change.old_value), display_tracker_value(change.new_value), scope,
                    )
                )
            continue
        if entry.kind is ItemActivityKind.FIELD_CHANGE:
            text = entry.change_summary or "바뀐 필드 정보 없음"
            rows.append((number, kind, version, entry.at, entry.by, "", "", text, scope))
            continue
        text = entry.body
        if entry.attachment_names:
            text += "\n\n첨부: " + ", ".join(entry.attachment_names)
        rows.append((number, kind, "", entry.at, entry.by, entry.title, "", text, scope))
    return rows


def _populate_history(sheet, rows: list[tuple[Any, ...]], *, item_id: int) -> list[_LongValue]:
    _write_headers(sheet, _HISTORY_HEADERS, _HISTORY_WIDTHS)
    long_values: list[_LongValue] = []
    next_long_row = 2
    for offset, row in enumerate(rows):
        row_index = offset + 2
        for column, value in enumerate(row, start=1):
            cell = sheet.cell(row_index, column)
            if column in _VALUE_COLUMNS and requires_long_value_sheet(normalize_excel_text(value)):
                parts = split_long_value(value)
                if next_long_row + len(parts) - 1 > EXCEL_MAX_ROWS:
                    raise ItemActivityExportError(
                        f"아이템 #{item_id}의 긴 값을 나누는 중 Excel 행 한도({EXCEL_MAX_ROWS:,}행)를 넘습니다."
                    )
                long_values.append(
                    _LongValue(
                        row[0], row[1], row[5], _HISTORY_HEADERS[column - 1], parts, next_long_row, cell.coordinate
                    )
                )
                _write(cell, long_value_preview(value))
                _link(cell, LONG_VALUE_SHEET_TITLE, f"F{next_long_row}")
                next_long_row += len(parts)
                continue
            _write(cell, value)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(_HISTORY_HEADERS))}{len(rows) + 1}"
    return long_values


def _populate_long_values(sheet, long_values: list[_LongValue]) -> None:
    _write_headers(sheet, _LONG_HEADERS, _LONG_WIDTHS)
    for record in long_values:
        for index, part in enumerate(record.parts):
            row_index = record.start_row + index
            values = (
                record.number, record.kind, record.target, record.column,
                f"{index + 1}/{len(record.parts)}", part, "이력으로 이동" if index == 0 else "",
            )
            for column, value in enumerate(values, start=1):
                _write(sheet.cell(row_index, column), value)
            if index == 0:
                _link(sheet.cell(row_index, 7), HISTORY_SHEET_TITLE, record.source)
    sheet.freeze_panes = "A2"


def _populate_fields(sheet, summary: ItemActivitySummary) -> None:
    _write_headers(sheet, _FIELD_HEADERS, _FIELD_WIDTHS)
    for row_index, field in enumerate(summary.fields, start=2):
        values = (
            field.field_name,
            display_tracker_value(field.first_value),
            display_tracker_value(field.last_value),
            field.change_count,
            field.last_at,
            field.last_by,
        )
        for column, value in enumerate(values, start=1):
            _write(sheet.cell(row_index, column), value)
    sheet.freeze_panes = "A2"
    if summary.fields:
        sheet.auto_filter.ref = f"A1:F{len(summary.fields) + 1}"


def _populate_summary(
    sheet,
    request: ItemActivityExportRequest,
    *,
    generated_at: datetime,
    long_value_count: int,
) -> None:
    summary = request.summary
    rows = (
        ("아이템", f"#{request.item_id} {request.item_name}".strip()),
        ("트래커", request.tracker_name or "-"),
        ("구간", request.scope_label),
        ("유형", ", ".join(request.kind_labels)),
        ("생성 시각", generated_at.isoformat(timespec="seconds")),
        ("이력 항목", len(request.entries)),
        ("버전", summary.version_count),
        ("필드 변경", summary.field_change_count),
        ("바뀐 필드", summary.changed_field_count),
        ("필드 변경 정보 없는 버전", summary.versions_without_changes),
        ("댓글", summary.comment_count),
        ("첨부", summary.attachment_count),
        ("긴 값 분할", f"{long_value_count:,}개 값" if long_value_count else "없음"),
    )
    for row_index, (label, value) in enumerate(rows, start=1):
        label_cell = sheet.cell(row_index, 1)
        _write(label_cell, label)
        label_cell.font = HEADER_FONT
        label_cell.fill = HEADER_FILL
        _write(sheet.cell(row_index, 2), value)
        if label == "긴 값 분할" and long_value_count:
            _link(sheet.cell(row_index, 2), LONG_VALUE_SHEET_TITLE, "A1")
    sheet.column_dimensions["A"].width = 26
    sheet.column_dimensions["B"].width = 60
    sheet.sheet_view.showGridLines = False


def _write_headers(sheet, headers: tuple[str, ...], widths: tuple[int, ...]) -> None:
    for column, (label, width) in enumerate(zip(headers, widths, strict=True), start=1):
        cell = sheet.cell(1, column, label)
        cell.fill = GROUP_FILL
        cell.font = WHITE_FONT
        cell.alignment = CENTER_WRAP
        cell.border = THIN_BORDER
        sheet.column_dimensions[get_column_letter(column)].width = width


def _write(cell: Cell, value: Any) -> None:
    """수식으로 읽힐 수 있는 머리글자는 작은따옴표로 막고, 셀 한도를 넘는 글은 줄인다."""
    cell.font = BODY_FONT
    cell.alignment = TOP_WRAP
    cell.border = THIN_BORDER
    if not isinstance(value, str):
        cell.value = value
        return
    text = cell_preview(
        value,
        max_text_units=EXCEL_MAX_CELL_TEXT - 1,
        max_line_feeds=EXCEL_MAX_CELL_LINE_FEEDS,
        suffix="\n…",
    )
    if text.startswith(("=", "+", "@")) or (text.startswith("-") and text != "-"):
        text = f"'{text}"
    cell.value = text or None


def _link(cell: Cell, sheet_title: str, coordinate: str) -> None:
    escaped = sheet_title.replace("'", "''")
    cell.hyperlink = f"#'{escaped}'!{coordinate}"
    cell.font = LINK_FONT
```

`_write`가 빈 글을 `None`으로 두는 것은 테스트의 빈 칸 기대값(`None`)과 맞추기 위해서다. openpyxl은 빈 글을 써도 저장 후 빈 칸이 된다.

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_activity_export -v`
Expected: PASS. 내부 링크는 기존 Baseline 내보내기와 같이 `hyperlink.target`에 `#'시트'!칸` 모양으로 들어간다. 이어서 ruff, mypy 통과.

- [ ] **Step 5: 커밋**

```bash
git add src/gui/item_activity_export.py tests/test_gui_item_activity_export.py
git commit -m "feat: 아이템 활동 이력 Excel 통합 문서 생성 추가" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: 활동 이력 패널

**Files:**
- Create: `src/gui/item_activity_panel.py`
- Modify: `src/gui/activity_history.py` (실행 기록 종류 하나)
- Test: `tests/test_gui_item_activity_panel.py`

**Interfaces:**
- Consumes: Task 1 전부, Task 2의 `ItemChangeHistoryView`·`history_time_text`·`MAX_CELL_TEXT`·`MAX_TOOLTIP_TEXT`, Task 3의 `ItemActivityExportRequest`·`export_item_activity_xlsx`, 기존 `TrackerBaseline`, `display_tracker_value`, `SortableTableItem`, `ActivityRecord`
- Produces:
  - `BETWEEN_POINTS = "between"`, `ALL_SCOPE_DATA = ""`
  - `ItemActivityPanel(parent=None, *, request_kind: Callable[[ItemActivityKind, bool], None], between_points: bool = False)`
    - 시그널 `export_requested(object)`: `ItemActivityExportRequest`
    - `set_baselines(baselines: tuple[TrackerBaseline, ...]) -> None`
    - `select_scope(data: int | str) -> None`: Baseline ID, `ALL_SCOPE_DATA`, `BETWEEN_POINTS`
    - `set_item(item_id: int | None, *, item_name="", tracker_name="", current_version=None, marker: BaselineMarker | None = None, between_scope: ActivityScope | None = None, waiting_message: str | None = None) -> None`
    - `set_active(active: bool) -> None`: 탭이 보이는지. 보이는 동안만 조회를 요청한다.
    - `set_note(text: str) -> None`
    - `set_source(item_id: int, kind: ItemActivityKind, data: object) -> None`: 필드 변경은 `ItemHistorySnapshot`, 댓글은 `ItemCommentsSnapshot`, 첨부는 `tuple[AttachmentSummary, ...]`
    - `set_source_error(item_id: int, kind: ItemActivityKind, message: str) -> None`
    - `set_export_busy(busy: bool, message: str = "") -> None`
    - 위젯 속성: `baseline_combo`, `kind_checks: dict[ItemActivityKind, QCheckBox]`, `relation_check`, `retry_button`, `export_button`, `status_label`, `summary_label`, `summary_table`, `history_view`
  - `run_activity_export(parent, panel, request, *, submit, record_activity, show_error, source: str, project_id: int | None, project_name: str, tracker_id: int | None, tracker_name: str) -> None`
  - `ActivityOperation.ITEM_HISTORY_EXPORT = "item_history_export"`, 라벨 `변경 이력 Excel 내보내기`

상태줄 모양: `#ID · 구간 이름 · (조회 중 유형) · 버전 N건 · 필드 변경 M건 · 바뀐 필드 K개 · (필드 변경 정보 없는 버전 X건) · 댓글 C건 · 첨부 A건 · (제외 안내) · (실패 유형) · (안내) · (내보내기 결과)`. 꺼진 유형과 아직 받지 않은 유형의 건수는 적지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gui_item_activity_panel.py`:

```python
from __future__ import annotations

import os
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.activity_history import ActivityOperation
from src.gui.activity_history import ActivityResult
from src.gui.item_activity import ActivityScope
from src.gui.item_activity import BaselineMarker
from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity_export import ItemActivityExportError
from src.gui.item_activity_export import ItemActivityExportSummary
from src.gui.item_activity_panel import ALL_SCOPE_DATA
from src.gui.item_activity_panel import ItemActivityPanel
from src.gui.item_activity_panel import run_activity_export
from src.gui.tracker_baseline_compare import TrackerBaseline
from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_item_context_models import ItemHistorySnapshot
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


FIELD = ItemActivityKind.FIELD_CHANGE
COMMENT = ItemActivityKind.COMMENT
ATTACHMENT = ItemActivityKind.ATTACHMENT


def _version(version: int, at: str, *changes: tuple[int, str, str | None, str]) -> dict:
    return {
        "itemRevision": {"version": version},
        "modifiedAt": at,
        "modifiedBy": {"displayName": "Sample User A"},
        "changes": [
            {
                "field": {"id": field_id, "name": name},
                "oldValue": None if old is None else {"fieldId": field_id, "value": old},
                "newValue": {"fieldId": field_id, "value": new},
            }
            for field_id, name, old, new in changes
        ],
    }


HISTORY = ItemHistorySnapshot.from_raw(
    {
        "versions": [
            _version(4, "2026-07-21T09:30:00Z", (101, "Risk Level", "Medium", "High")),
            _version(3, "2026-07-20T09:00:00Z", (101, "Risk Level", None, "Medium")),
            _version(2, "2026-07-19T08:00:00Z", (3, "Summary", "Old", "New")),
            {"itemRevision": {"version": 1}, "modifiedAt": "2026-07-01T00:00:00Z", "changeSummary": "Created"},
        ]
    }
)
COMMENTS = ItemCommentsSnapshot.from_raw(
    [{"id": 51001, "createdBy": {"displayName": "Sample User B"}, "createdAt": "2026-07-20T09:10:00Z",
      "comment": "Review note"}]
)
ATTACHMENTS = (
    AttachmentSummary(53001, "anonymous-spec.txt", size=2048, modified_at="2026-07-18T11:00:00Z"),
    AttachmentSummary(53002, "anonymous-draft.txt", size=512, modified_at="2026-07-10T08:00:00Z"),
)
SOURCES = {FIELD: HISTORY, COMMENT: COMMENTS, ATTACHMENT: ATTACHMENTS}
BASELINES = (
    TrackerBaseline(11, "Sample Baseline", "2026-07-19T08:00:00Z"),
    TrackerBaseline(12, "No Time Baseline", ""),
)


class ItemActivityPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.requests: list[tuple[ItemActivityKind, bool]] = []
        self.panel = ItemActivityPanel(request_kind=lambda kind, force: self.requests.append((kind, force)))
        self.addCleanup(self.panel.deleteLater)

    def _load_all(self, item_id: int = 1) -> None:
        self.panel.set_item(item_id, item_name="Sample requirement", tracker_name="Offline Requirements")
        self.panel.set_active(True)
        for kind, data in SOURCES.items():
            self.panel.set_source(item_id, kind, data)

    def test_requests_checked_kinds_only_while_the_tab_is_visible(self) -> None:
        self.panel.kind_checks[COMMENT].setChecked(False)
        self.panel.set_item(1)

        self.assertEqual(self.requests, [])
        self.assertEqual(self.panel.status_label.text(), "#1 · 탭을 열면 변경 이력을 조회합니다.")

        self.panel.set_active(True)

        self.assertEqual(self.requests, [(FIELD, False), (ATTACHMENT, False)])
        self.assertEqual(self.panel.status_label.text(), "#1 · 전체 · 필드 변경·첨부 조회 중")

        self.panel.kind_checks[COMMENT].setChecked(True)

        self.assertEqual(self.requests[-1], (COMMENT, False))
        self.assertEqual(len(self.requests), 3)

    def test_loaded_sources_fill_status_summary_tree_and_enable_export(self) -> None:
        self._load_all()

        self.assertEqual(
            self.panel.status_label.text(),
            "#1 · 전체 · 버전 4건 · 필드 변경 3건 · 바뀐 필드 2개 · 필드 변경 정보 없는 버전 1건 · 댓글 1건 · 첨부 2건",
        )
        table = self.panel.summary_table
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(
            [table.item(0, column).text() for column in range(5)],
            ["Risk Level", "-", "High", "2", "2026-07-21 09:30 · Sample User A"],
        )
        self.assertEqual(self.panel.history_view.topLevelItemCount(), 7)
        self.assertTrue(self.panel.export_button.isEnabled())
        self.assertFalse(self.panel.retry_button.isVisible())

    def test_late_response_for_the_previous_item_is_ignored(self) -> None:
        self.panel.set_item(1)
        self.panel.set_active(True)
        self.panel.set_item(2)

        self.panel.set_source(1, FIELD, HISTORY)

        self.assertEqual(self.panel.history_view.topLevelItemCount(), 0)
        self.assertEqual(self.panel.status_label.text(), "#2 · 전체 · 필드 변경·댓글·첨부 조회 중")
        self.assertEqual(self.requests.count((FIELD, False)), 2)

    def test_baseline_choice_refilters_without_new_requests(self) -> None:
        self.panel.set_baselines(BASELINES)
        self._load_all()
        request_count = len(self.requests)

        self.panel.select_scope(11)

        self.assertEqual(len(self.requests), request_count)
        self.assertEqual(
            self.panel.status_label.text(),
            "#1 · Sample Baseline 이후 · 버전 2건 · 필드 변경 2건 · 바뀐 필드 1개 · 댓글 1건 · 첨부 0건",
        )
        self.assertEqual(self.panel.baseline_combo.currentText(), "Sample Baseline (2026-07-19T08:00:00Z)")

    def test_baseline_without_created_at_cannot_be_chosen(self) -> None:
        self.panel.set_baselines(BASELINES)
        combo = self.panel.baseline_combo
        index = combo.findData(12)
        model_item = combo.model().item(index)

        self.assertFalse(model_item.isEnabled())
        self.assertEqual(model_item.toolTip(), "생성 시각이 없어 기준으로 쓸 수 없습니다")

        self.panel.select_scope(12)

        self.assertEqual(combo.currentData(), ALL_SCOPE_DATA)

    def test_failed_kind_is_reported_and_retry_asks_only_for_it(self) -> None:
        self.panel.set_item(1)
        self.panel.set_active(True)
        self.panel.set_source(1, FIELD, HISTORY)
        self.panel.set_source(1, ATTACHMENT, ATTACHMENTS)

        self.panel.set_source_error(1, COMMENT, "댓글을 볼 권한이 없습니다.")

        self.assertTrue(self.panel.status_label.text().endswith("댓글 조회 실패: 댓글을 볼 권한이 없습니다."))
        self.assertIn("첨부 2건", self.panel.status_label.text())
        self.assertFalse(self.panel.retry_button.isHidden())
        self.assertFalse(self.panel.export_button.isEnabled())

        self.panel.retry_button.click()

        self.assertEqual(self.requests[-1], (COMMENT, True))
        self.assertTrue(self.panel.retry_button.isHidden())

    def test_turning_field_changes_off_empties_the_summary(self) -> None:
        self._load_all()

        self.panel.kind_checks[FIELD].setChecked(False)

        self.assertEqual(self.panel.summary_table.rowCount(), 0)
        self.assertEqual(self.panel.summary_label.text(), "필드 변경 유형을 켜면 필드별 요약을 보입니다.")
        self.assertEqual(self.panel.status_label.text(), "#1 · 전체 · 댓글 1건 · 첨부 2건")

    def test_relation_kind_is_shown_but_disabled(self) -> None:
        self.assertFalse(self.panel.relation_check.isEnabled())
        self.assertFalse(self.panel.relation_check.isChecked())
        self.assertEqual(self.panel.relation_check.toolTip(), "서버 응답에 시각 정보가 없어 지원하지 않습니다")

    def test_between_points_panel_reports_missing_versions_and_undetermined_times(self) -> None:
        panel = ItemActivityPanel(request_kind=lambda *_args: None, between_points=True)
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.baseline_combo.itemText(0), "비교 시점 사이")

        panel.set_item(1, between_scope=ActivityScope("비교 시점 사이", versions=(2, 4), time_undetermined=True))
        panel.set_active(True)
        for kind, data in SOURCES.items():
            panel.set_source(1, kind, data)

        self.assertEqual(
            panel.status_label.text(),
            "#1 · 비교 시점 사이 · 버전 2건 · 필드 변경 2건 · 바뀐 필드 1개 · 댓글 0건 · 첨부 0건"
            " · Baseline 생성 시각이 없어 댓글·첨부 구간을 정할 수 없습니다",
        )

        panel.set_item(1, between_scope=None)

        self.assertEqual(panel.status_label.text(), "#1 · 두 시점의 버전 정보가 없어 사이 이력을 고를 수 없습니다.")
        self.assertFalse(panel.export_button.isEnabled())

    def test_export_button_emits_the_visible_range(self) -> None:
        marker = BaselineMarker("Baseline #11", version=2)
        self.panel.set_baselines(BASELINES)
        self.panel.set_item(1, item_name="Sample requirement", tracker_name="Offline Requirements", marker=marker)
        self.panel.set_active(True)
        for kind, data in SOURCES.items():
            self.panel.set_source(1, kind, data)
        self.panel.select_scope(11)
        self.panel.kind_checks[ATTACHMENT].setChecked(False)
        emitted = []
        self.panel.export_requested.connect(emitted.append)

        self.panel.export_button.click()

        (request,) = emitted
        self.assertEqual(
            (request.item_id, request.item_name, request.tracker_name),
            (1, "Sample requirement", "Offline Requirements"),
        )
        self.assertEqual(request.scope_label, "Sample Baseline 이후")
        self.assertEqual(request.kind_labels, ("필드 변경", "댓글"))
        self.assertEqual(
            [(entry.kind, entry.version) for entry in request.entries],
            [(FIELD, 4), (COMMENT, None), (FIELD, 3)],
        )
        self.assertEqual(request.summary.field_change_count, 2)
        self.assertIs(request.baseline, marker)


class RunActivityExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.panel = ItemActivityPanel(request_kind=lambda *_args: None)
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_item(1, item_name="Sample requirement")
        self.panel.set_active(True)
        for kind, data in SOURCES.items():
            self.panel.set_source(1, kind, data)
        self.requests = []
        self.panel.export_requested.connect(self.requests.append)
        self.panel.export_button.click()
        self.records = []
        self.errors = []
        self.submitted = []

    def _run(self) -> None:
        def submit(key, operation, completed, failed):
            self.submitted.append(key)
            try:
                result = operation()
            except Exception as exc:
                failed(exc)
            else:
                completed(result)

        run_activity_export(
            self.panel,
            self.panel,
            self.requests[0],
            submit=submit,
            record_activity=self.records.append,
            show_error=lambda exc, prefix="": self.errors.append(prefix),
            source="tracker_workspace",
            project_id=246800,
            project_name="Offline Project",
            tracker_id=24680001,
            tracker_name="Offline Requirements",
        )

    def test_success_records_activity_and_reports_on_the_panel(self) -> None:
        summary = ItemActivityExportSummary(entry_count=7, row_count=8, long_value_count=0)
        with (
            patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("history.xlsx", "")),
            patch("src.gui.item_activity_panel.export_item_activity_xlsx", return_value=summary) as export_mock,
        ):
            self._run()

        export_mock.assert_called_once_with(self.requests[0], "history.xlsx")
        self.assertEqual(self.submitted, ["item_activity_export"])
        (record,) = self.records
        self.assertEqual(record.operation, ActivityOperation.ITEM_HISTORY_EXPORT)
        self.assertEqual(record.result, ActivityResult.SUCCESS)
        self.assertEqual(record.item_id, 1)
        self.assertEqual(record.details["entryCount"], 7)
        self.assertTrue(self.panel.status_label.text().endswith("Excel 내보내기 완료 · 항목 7건 · 행 8개"))
        self.assertTrue(self.panel.export_button.isEnabled())

    def test_failure_shows_error_and_restores_the_button(self) -> None:
        with (
            patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("history.xlsx", "")),
            patch(
                "src.gui.item_activity_panel.export_item_activity_xlsx",
                side_effect=ItemActivityExportError("Excel 파일을 저장하지 못했습니다."),
            ),
        ):
            self._run()

        self.assertEqual(self.errors, ["변경 이력 Excel 내보내기 실패"])
        self.assertEqual(self.records[0].result, ActivityResult.FAILED)
        self.assertTrue(self.panel.status_label.text().endswith("Excel 내보내기 실패"))
        self.assertTrue(self.panel.export_button.isEnabled())

    def test_cancelled_file_dialog_does_nothing(self) -> None:
        with patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("", "")):
            self._run()

        self.assertEqual((self.submitted, self.records), ([], []))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_activity_panel -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.gui.item_activity_panel'`

- [ ] **Step 3: 실행 기록 종류 추가**

`src/gui/activity_history.py`의 `ActivityOperation`에 한 줄, `ACTIVITY_OPERATION_LABELS`에 한 줄을 더한다.

```python
    ITEM_HISTORY_EXPORT = "item_history_export"
```

```python
    ActivityOperation.ITEM_HISTORY_EXPORT: "변경 이력 Excel 내보내기",
```

- [ ] **Step 4: 패널 구현**

`src/gui/item_activity_panel.py`:

```python
"""변경 이력 탭의 활동 이력 패널.

기준 Baseline과 유형을 고르는 도구줄, 상태줄, 필드별 요약 표, 시간순 트리를 묶는다.
Baseline 비교 탭과 상세 창이 같은 패널을 쓰고, 조회는 생성자로 받은 콜백에 맡긴다.
받아 둔 데이터는 구간과 유형을 바꿔도 다시 묻지 않고 거르기만 한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


try:
    from PySide6.QtCore import Qt
    from PySide6.QtCore import Signal
    from PySide6.QtGui import QStandardItemModel
    from PySide6.QtWidgets import QAbstractItemView
    from PySide6.QtWidgets import QCheckBox
    from PySide6.QtWidgets import QComboBox
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtWidgets import QHBoxLayout
    from PySide6.QtWidgets import QHeaderView
    from PySide6.QtWidgets import QLabel
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtWidgets import QSplitter
    from PySide6.QtWidgets import QTableWidget
    from PySide6.QtWidgets import QVBoxLayout
    from PySide6.QtWidgets import QWidget
except ImportError as exc:  # pragma: no cover - GUI dependency guard
    raise RuntimeError("GUI 실행에는 PySide6 패키지가 필요합니다.") from exc

from .activity_history import ActivityOperation
from .activity_history import ActivityRecord
from .activity_history import ActivityResult
from .item_activity import ACTIVITY_KIND_LABELS
from .item_activity import ALL_SCOPE
from .item_activity import ActivityScope
from .item_activity import BaselineMarker
from .item_activity import FilteredActivity
from .item_activity import ItemActivityEntry
from .item_activity import ItemActivityKind
from .item_activity import ItemActivitySummary
from .item_activity import attachment_entries
from .item_activity import baseline_scope
from .item_activity import comment_entries
from .item_activity import filter_entries
from .item_activity import history_entries
from .item_activity import merge_entries
from .item_activity import summarize
from .item_activity_export import ItemActivityExportRequest
from .item_activity_export import export_item_activity_xlsx
from .item_change_history_view import MAX_CELL_TEXT
from .item_change_history_view import MAX_TOOLTIP_TEXT
from .item_change_history_view import ItemChangeHistoryView
from .item_change_history_view import history_time_text
from .tracker_baseline_compare import TrackerBaseline
from .tracker_baseline_compare import display_tracker_value
from .tracker_workspace_support import SortableTableItem


BETWEEN_POINTS = "between"
ALL_SCOPE_DATA = ""
_RELATION_TOOLTIP = "서버 응답에 시각 정보가 없어 지원하지 않습니다"
_NO_CREATED_AT_TOOLTIP = "생성 시각이 없어 기준으로 쓸 수 없습니다"


def _cell_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ItemActivityPanel(QWidget):
    """변경 이력 탭 하나. 아이템 하나의 활동 이력을 구간과 유형으로 걸러 보인다."""

    export_requested = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        request_kind: Callable[[ItemActivityKind, bool], None],
        between_points: bool = False,
    ) -> None:
        super().__init__(parent)
        self._request_kind = request_kind
        self._between_points = between_points
        self._item_id: int | None = None
        self._item_name = ""
        self._tracker_name = ""
        self._current_version: int | None = None
        self._marker: BaselineMarker | None = None
        self._between_scope: ActivityScope | None = None
        self._baselines: dict[int, TrackerBaseline] = {}
        self._sources: dict[ItemActivityKind, tuple[ItemActivityEntry, ...]] = {}
        self._loading: set[ItemActivityKind] = set()
        self._errors: dict[ItemActivityKind, str] = {}
        self._active = False
        self._export_busy = False
        self._export_message = ""
        self._note = ""
        self._waiting_message = "아이템을 고르면 변경 이력을 볼 수 있습니다."
        self._visible = FilteredActivity(())
        self._summary = ItemActivitySummary()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("기준 Baseline", self))
        self.baseline_combo = QComboBox(self)
        self.baseline_combo.setObjectName("activity_baseline_combo")
        # Baseline 이름이 길어도 창을 넓히지 않게 비교 탭 소스 콤보와 같은 정책을 쓴다.
        self.baseline_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.baseline_combo.setMinimumContentsLength(8)
        self.baseline_combo.currentIndexChanged.connect(self._render)
        toolbar.addWidget(self.baseline_combo, 1)
        self.kind_checks: dict[ItemActivityKind, QCheckBox] = {}
        for kind in ItemActivityKind:
            check = QCheckBox(ACTIVITY_KIND_LABELS[kind], self)
            check.setChecked(True)
            check.toggled.connect(self._on_kinds_changed)
            self.kind_checks[kind] = check
            toolbar.addWidget(check)
        self.relation_check = QCheckBox("관계", self)
        self.relation_check.setEnabled(False)
        self.relation_check.setToolTip(_RELATION_TOOLTIP)
        toolbar.addWidget(self.relation_check)
        self.retry_button = QPushButton("다시 시도", self)
        self.retry_button.hide()
        self.retry_button.clicked.connect(self._retry)
        toolbar.addWidget(self.retry_button)
        self.export_button = QPushButton("이력 Excel 내보내기", self)
        self.export_button.setObjectName("activity_export_button")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("tracker_panel_status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        summary_box = QWidget(splitter)
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary_label = QLabel(summary_box)
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        self.summary_table = QTableWidget(0, 5, summary_box)
        self.summary_table.setObjectName("activity_field_summary")
        self.summary_table.setHorizontalHeaderLabels(["필드", "구간 처음 값", "구간 마지막 값", "변경 횟수", "마지막 수정"])
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.summary_table.setWordWrap(True)
        self.summary_table.verticalHeader().setVisible(False)
        header = self.summary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.summary_table.setColumnWidth(0, 180)
        self.summary_table.setSortingEnabled(True)
        header.setSortIndicator(3, Qt.SortOrder.DescendingOrder)
        summary_layout.addWidget(self.summary_table, 1)
        self.history_view = ItemChangeHistoryView(splitter)
        splitter.addWidget(summary_box)
        splitter.addWidget(self.history_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self._fill_baseline_combo()
        self._render()

    # 소유자가 부르는 메서드

    def set_baselines(self, baselines: tuple[TrackerBaseline, ...]) -> None:
        self._baselines = {baseline.baseline_id: baseline for baseline in baselines}
        self._fill_baseline_combo()
        self._render()

    def select_scope(self, data: int | str) -> None:
        """구간을 고른다. 고를 수 없는 Baseline이면 전체로 둔다."""
        index = self.baseline_combo.findData(data)
        if index < 0 or not self._selectable(index):
            index = self.baseline_combo.findData(ALL_SCOPE_DATA)
        self.baseline_combo.setCurrentIndex(index)
        self._render()

    def set_item(
        self,
        item_id: int | None,
        *,
        item_name: str = "",
        tracker_name: str = "",
        current_version: int | None = None,
        marker: BaselineMarker | None = None,
        between_scope: ActivityScope | None = None,
        waiting_message: str | None = None,
    ) -> None:
        """다른 아이템이나 범위로 바꾼다. 받아 둔 데이터는 버리고, 탭이 보이면 다시 묻는다."""
        self._item_id = item_id
        self._item_name = item_name
        self._tracker_name = tracker_name
        self._current_version = current_version
        self._marker = marker
        self._between_scope = between_scope
        if waiting_message is not None:
            self._waiting_message = waiting_message
        self._sources.clear()
        self._loading.clear()
        self._errors.clear()
        self._export_message = ""
        # 요청을 먼저 걸어야 상태줄이 `조회 중`을 보인다.
        self._request_missing()
        self._render()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._request_missing()
        self._render()

    def set_note(self, text: str) -> None:
        self._note = str(text or "")
        self._render()

    def set_source(self, item_id: int, kind: ItemActivityKind, data: Any) -> None:
        if item_id != self._item_id:
            return
        self._loading.discard(kind)
        self._errors.pop(kind, None)
        if kind is ItemActivityKind.FIELD_CHANGE:
            self._sources[kind] = history_entries(data)
        elif kind is ItemActivityKind.COMMENT:
            self._sources[kind] = comment_entries(data)
        else:
            self._sources[kind] = attachment_entries(data)
        self._render()

    def set_source_error(self, item_id: int, kind: ItemActivityKind, message: str) -> None:
        if item_id != self._item_id:
            return
        self._loading.discard(kind)
        self._errors[kind] = str(message)
        self._render()

    def set_export_busy(self, busy: bool, message: str = "") -> None:
        self._export_busy = bool(busy)
        self._export_message = message
        self._render()

    # 내부 동작

    def _checked_kinds(self) -> set[ItemActivityKind]:
        return {kind for kind, check in self.kind_checks.items() if check.isChecked()}

    def _selectable(self, index: int) -> bool:
        model = self.baseline_combo.model()
        if not isinstance(model, QStandardItemModel):
            return True
        item = model.item(index)
        return item is None or item.isEnabled()

    def _fill_baseline_combo(self) -> None:
        combo = self.baseline_combo
        selected = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if self._between_points:
            combo.addItem("비교 시점 사이", BETWEEN_POINTS)
        combo.addItem("전체", ALL_SCOPE_DATA)
        model = combo.model()
        for baseline in self._baselines.values():
            label = f"{baseline.name} ({baseline.created_at})" if baseline.created_at else baseline.name
            combo.addItem(label, baseline.baseline_id)
            if baseline_scope(baseline.name, baseline.created_at) is None and isinstance(model, QStandardItemModel):
                item = model.item(combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
                    item.setToolTip(_NO_CREATED_AT_TOOLTIP)
        index = combo.findData(selected) if selected is not None else -1
        combo.setCurrentIndex(index if index >= 0 and self._selectable(index) else 0)
        combo.blockSignals(False)

    def _scope(self) -> ActivityScope | None:
        data = self.baseline_combo.currentData()
        if data == BETWEEN_POINTS:
            return self._between_scope
        baseline = self._baselines.get(data) if isinstance(data, int) else None
        if baseline is None:
            return ALL_SCOPE
        return baseline_scope(baseline.name, baseline.created_at) or ALL_SCOPE

    def _request_missing(self) -> None:
        if not self._active or self._item_id is None:
            return
        for kind in ItemActivityKind:
            if kind not in self._checked_kinds():
                continue
            if kind in self._sources or kind in self._loading or kind in self._errors:
                continue
            self._loading.add(kind)
            self._request_kind(kind, False)

    def _retry(self) -> None:
        for kind in [kind for kind in ItemActivityKind if kind in self._errors]:
            del self._errors[kind]
            if kind in self._checked_kinds():
                self._loading.add(kind)
                self._request_kind(kind, True)
        self._render()

    def _on_kinds_changed(self, _checked: bool) -> None:
        self._request_missing()
        self._render()

    def _render(self, *_args) -> None:
        kinds = self._checked_kinds()
        self.retry_button.setVisible(bool(self._errors))
        self._visible = FilteredActivity(())
        self._summary = ItemActivitySummary()
        scope = self._scope()
        if self._item_id is None or scope is None:
            self.history_view.clear()
            self._fill_summary_table(kinds)
            self.export_button.setEnabled(False)
            self.status_label.setText(
                self._waiting_message
                if self._item_id is None
                else f"#{self._item_id} · 두 시점의 버전 정보가 없어 사이 이력을 고를 수 없습니다."
            )
            return
        merged = merge_entries(*(self._sources[kind] for kind in ItemActivityKind if kind in self._sources))
        self._visible = filter_entries(merged, scope=scope, kinds=kinds)
        self._summary = summarize(self._visible.entries)
        self.history_view.show_entries(
            self._visible.entries, current_version=self._current_version, baseline=self._marker
        )
        self._fill_summary_table(kinds)
        ready = bool(kinds) and all(kind in self._sources for kind in kinds)
        self.export_button.setEnabled(ready and bool(self._visible.entries) and not self._export_busy)
        self.status_label.setText(self._status_text(scope, kinds))

    def _status_text(self, scope: ActivityScope, kinds: set[ItemActivityKind]) -> str:
        if not (self._active or self._sources or self._loading or self._errors):
            return f"#{self._item_id} · 탭을 열면 변경 이력을 조회합니다."
        parts = [f"#{self._item_id}", scope.label]
        loading = [ACTIVITY_KIND_LABELS[kind] for kind in ItemActivityKind if kind in self._loading and kind in kinds]
        if loading:
            parts.append(f"{'·'.join(loading)} 조회 중")
        summary = self._summary
        if ItemActivityKind.FIELD_CHANGE in kinds and ItemActivityKind.FIELD_CHANGE in self._sources:
            parts += [
                f"버전 {summary.version_count}건",
                f"필드 변경 {summary.field_change_count}건",
                f"바뀐 필드 {summary.changed_field_count}개",
            ]
            if summary.versions_without_changes:
                parts.append(f"필드 변경 정보 없는 버전 {summary.versions_without_changes}건")
        if ItemActivityKind.COMMENT in kinds and ItemActivityKind.COMMENT in self._sources:
            parts.append(f"댓글 {summary.comment_count}건")
        if ItemActivityKind.ATTACHMENT in kinds and ItemActivityKind.ATTACHMENT in self._sources:
            parts.append(f"첨부 {summary.attachment_count}건")
        if not kinds:
            parts.append("유형을 하나 이상 고르세요.")
        if self._visible.untimed_count:
            parts.append(f"시각 없는 항목 {self._visible.untimed_count}건 제외")
        if self._visible.undetermined_count:
            parts.append("Baseline 생성 시각이 없어 댓글·첨부 구간을 정할 수 없습니다")
        parts += [
            f"{ACTIVITY_KIND_LABELS[kind]} 조회 실패: {message}"
            for kind, message in self._errors.items()
            if kind in kinds
        ]
        parts += [text for text in (self._note, self._export_message) if text]
        return " · ".join(parts)

    def _fill_summary_table(self, kinds: set[ItemActivityKind]) -> None:
        table = self.summary_table
        header = table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        table.setSortingEnabled(False)
        table.setRowCount(0)
        fields = self._summary.fields
        if ItemActivityKind.FIELD_CHANGE not in kinds:
            self.summary_label.setText("필드 변경 유형을 켜면 필드별 요약을 보입니다.")
        elif fields:
            self.summary_label.setText(f"필드별 요약 · 바뀐 필드 {len(fields)}개")
        else:
            self.summary_label.setText("구간에 바뀐 필드가 없습니다.")
        if ItemActivityKind.FIELD_CHANGE in kinds:
            table.setRowCount(len(fields))
            for row, field in enumerate(fields):
                first = display_tracker_value(field.first_value)
                last = display_tracker_value(field.last_value)
                modified = " · ".join(part for part in (history_time_text(field.last_at), field.last_by) if part)
                values = (field.field_name, first, last, str(field.change_count), modified)
                sort_values = (field.field_name.casefold(), first.casefold(), last.casefold(), field.change_count,
                               field.last_at)
                for column, value in enumerate(values):
                    cell = SortableTableItem(_cell_text(value, MAX_CELL_TEXT), sort_values[column])
                    cell.setToolTip(_cell_text(value, MAX_TOOLTIP_TEXT))
                    table.setItem(row, column, cell)
        table.setSortingEnabled(True)
        table.sortItems(sort_column, sort_order)

    def _export(self) -> None:
        scope = self._scope()
        if self._item_id is None or scope is None or not self._visible.entries:
            return
        kinds = self._checked_kinds()
        self.export_requested.emit(
            ItemActivityExportRequest(
                item_id=self._item_id,
                item_name=self._item_name,
                tracker_name=self._tracker_name,
                scope_label=scope.label,
                kind_labels=tuple(ACTIVITY_KIND_LABELS[kind] for kind in ItemActivityKind if kind in kinds),
                entries=self._visible.entries,
                summary=self._summary,
                baseline=self._marker,
            )
        )


def run_activity_export(
    parent: QWidget,
    panel: ItemActivityPanel,
    request: ItemActivityExportRequest,
    *,
    submit: Callable[..., Any],
    record_activity: Callable[[ActivityRecord], None],
    show_error: Callable[..., None],
    source: str,
    project_id: int | None,
    project_name: str,
    tracker_id: int | None,
    tracker_name: str,
) -> None:
    """파일 위치를 묻고 백그라운드로 저장한 뒤 결과를 패널과 실행 기록에 남긴다.

    비교 탭과 상세 창이 같은 흐름을 쓴다.
    """
    output_path, _selected_filter = QFileDialog.getSaveFileName(
        parent,
        "변경 이력 Excel 저장",
        f"item_history_{request.item_id}.xlsx",
        "Excel 통합 문서 (*.xlsx)",
    )
    if not output_path:
        return

    def record(result: ActivityResult, summary: str, details: dict[str, Any]) -> None:
        record_activity(
            ActivityRecord.create(
                ActivityOperation.ITEM_HISTORY_EXPORT,
                result,
                source=source,
                summary=summary,
                project_id=project_id,
                project_name=project_name,
                tracker_id=tracker_id,
                tracker_name=tracker_name,
                item_id=request.item_id,
                item_name=request.item_name,
                details=details,
            )
        )

    def completed(summary) -> None:
        panel.set_export_busy(False, f"Excel 내보내기 완료 · 항목 {summary.entry_count}건 · 행 {summary.row_count}개")
        record(
            ActivityResult.SUCCESS,
            f"#{request.item_id} 변경 이력 {summary.entry_count}건을 Excel로 내보냈습니다.",
            {
                "kindCount": len(request.kind_labels),
                "entryCount": summary.entry_count,
                "rowCount": summary.row_count,
                "longValueCount": summary.long_value_count,
            },
        )

    def failed(exc: Exception) -> None:
        panel.set_export_busy(False, "Excel 내보내기 실패")
        show_error(exc, prefix="변경 이력 Excel 내보내기 실패")
        record(
            ActivityResult.FAILED,
            "변경 이력 Excel 내보내기 실패",
            {"kindCount": len(request.kind_labels), "entryCount": len(request.entries)},
        )

    panel.set_export_busy(True, "Excel 파일을 만드는 중입니다.")
    submit("item_activity_export", lambda: export_item_activity_xlsx(request, output_path), completed, failed)
```

- [ ] **Step 5: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_item_activity_panel -v`
Expected: PASS. 이어서 `.venv\Scripts\python.exe -m unittest tests.test_gui_activity_history tests.test_gui_main_window -q`(실행 기록 화면이 라벨 표를 돈다)와 ruff, mypy 통과.

- [ ] **Step 6: 커밋**

```bash
git add src/gui/item_activity_panel.py src/gui/activity_history.py tests/test_gui_item_activity_panel.py
git commit -m "feat: 기준 Baseline·유형으로 거르는 활동 이력 패널 추가" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: 테스트 모드 첨부 목록

**Files:**
- Modify: `src/gui/service_core.py` (테스트 데이터 읽기, `get_item_attachments` 추가)
- Modify: `src/gui/tracker_content_service.py:144-182` (`load_attachments`의 테스트 모드 조건)
- Modify: `data/gui-offline-sample/offline_tracker_items.json` (`attachmentsByItemId` 추가)
- Test: `tests/test_gui_offline_item_attachments.py`

**Interfaces:**
- Produces: 테스트 모드에서 `TrackerContentService.load_attachments(settings, 9001001)`이 익명 첨부 두 건을 돌려준다. 활동 패널의 첨부 유형이 테스트 모드에서도 보인다.

지금은 테스트 모드면 첨부 목록 API를 아예 부르지 않는다. 테스트 데이터 파일이 있으면 그 파일의 첨부 목록을 쓰도록 바꾼다. 테스트 데이터 경로가 없는 테스트 모드 설정은 지금처럼 부르지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gui_offline_item_attachments.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path

from src.gui.settings_store import GuiSettings
from src.gui.tracker_content_service import TrackerContentService


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "gui-offline-sample"


class OfflineItemAttachmentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = GuiSettings(
            offline_mode=True,
            offline_schema_path=str(SAMPLE_DIR / "offline_schema.json"),
            offline_tracker_configuration_path=str(SAMPLE_DIR / "offline_tracker_configuration.json"),
            offline_query_data_path=str(SAMPLE_DIR / "offline_tracker_items.json"),
        )

    def test_sample_attachments_are_listed_in_test_mode(self) -> None:
        attachments = TrackerContentService().load_attachments(self.settings, 9001001)

        self.assertEqual(
            [(value.attachment_id, value.name, value.size, value.modified_at) for value in attachments],
            [
                (53001, "anonymous-spec.txt", 2048, "2026-07-18T11:00:00Z"),
                (53002, "anonymous-draft.txt", 512, "2026-07-10T08:00:00Z"),
            ],
        )

    def test_items_without_sample_attachments_have_none(self) -> None:
        self.assertEqual(TrackerContentService().load_attachments(self.settings, 9001002), ())
        # 테스트 데이터가 모르는 아이템도 오류 없이 빈 목록이다.
        self.assertEqual(TrackerContentService().load_attachments(self.settings, 123), ())

    def test_baseline_attachments_are_still_not_listed(self) -> None:
        self.assertEqual(TrackerContentService().load_attachments(self.settings, 9001001, baseline_id=24681001), ())

    def test_test_mode_without_sample_data_does_not_ask(self) -> None:
        settings = GuiSettings(offline_mode=True)

        self.assertEqual(TrackerContentService().load_attachments(settings, 9001001), ())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_offline_item_attachments -v`
Expected: `test_sample_attachments_are_listed_in_test_mode` FAIL(빈 목록). 나머지는 PASS여도 된다.

- [ ] **Step 3: 샘플 데이터에 익명 첨부 추가**

이 파일은 손으로 줄을 맞춘 CRLF 파일이라 `json.dump`로 다시 쓰면 형식 전체가 바뀐다. `commentsByItemId` 줄 앞에 블록만 끼워 넣는다. 저장소 루트에서:

```bash
.venv\Scripts\python.exe - <<'EOF'
import json
from pathlib import Path

path = Path("data/gui-offline-sample/offline_tracker_items.json")
raw = path.read_bytes().decode("utf-8")
anchor = '  "commentsByItemId": {\r\n'
assert raw.count(anchor) == 1
block = "\r\n".join(
    [
        '  "attachmentsByItemId": {',
        '    "9001001": [',
        '      {"id": 53001, "name": "anonymous-spec.txt", "size": 2048, "mimeType": "text/plain",'
        ' "modifiedAt": "2026-07-18T11:00:00Z"},',
        '      {"id": 53002, "name": "anonymous-draft.txt", "size": 512, "mimeType": "text/plain",'
        ' "modifiedAt": "2026-07-10T08:00:00Z"}',
        "    ]",
        "  },",
    ]
) + "\r\n"
path.write_bytes(raw.replace(anchor, block + anchor).encode("utf-8"))
json.loads(path.read_text(encoding="utf-8"))
print("ok")
EOF
```

PowerShell에서는 heredoc이 없으므로 위 Python 본문을 스크래치 파일로 저장해 `.venv\Scripts\python.exe <파일>`로 돌린다. `git diff --stat data/`가 그 파일에 추가 줄만 보여야 한다.

- [ ] **Step 4: 테스트 모드 클라이언트와 첨부 조회 수정**

`src/gui/service_core.py`의 `__init__`에서 `self._offline_comments: dict[str, Any] = {}` 다음 줄에 넣는다.

```python
        self._offline_attachments: dict[str, Any] = {}
```

테스트 데이터를 읽는 곳에서 `self._offline_comments = deepcopy(comments)` 다음에 넣는다.

```python
        attachments = payload.get("attachmentsByItemId", {})
        if not isinstance(attachments, dict):
            raise ValueError("테스트 첨부 데이터는 아이템 ID별 객체여야 합니다.")
        self._offline_attachments = deepcopy(attachments)
```

`get_item_comments` 다음에 메서드를 더한다.

```python
    def get_item_attachments(self, item_id: int) -> list[dict[str, Any]]:
        """테스트 데이터의 첨부 목록. 테스트 데이터가 모르는 아이템은 첨부가 없는 것으로 본다."""
        payload = self._offline_attachments.get(str(int(item_id)), [])
        if not isinstance(payload, list):
            raise ValueError("테스트 첨부 데이터 형식이 올바르지 않습니다.")
        return deepcopy([value for value in payload if isinstance(value, dict)])
```

`src/gui/tracker_content_service.py`의 `load_attachments`에서

```python
        if not payloads and not bool(getattr(settings, "offline_mode", False)):
```

를 다음으로 바꾼다.

```python
        offline = bool(getattr(settings, "offline_mode", False))
        # 테스트 모드는 테스트 데이터 파일이 있을 때만 그 파일의 첨부 목록을 쓴다.
        if not payloads and (not offline or str(getattr(settings, "offline_query_data_path", "") or "").strip()):
```

- [ ] **Step 5: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_offline_item_attachments tests.test_gui_tracker_content_service tests.test_offline_payload_integration -v`
Expected: PASS.

이어서 전체 테스트를 돌린다. 테스트 모드 작업공간에서 아이템 9001001의 상세 첨부 표가 이제 두 행을 보이므로, 샘플 아이템의 첨부가 없다고 단언한 테스트가 있으면 익명 첨부 두 건을 기대하도록 고친다. 그 외 실패는 이 Task의 결함이다.

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -q`
Expected: PASS. 이어서 ruff, mypy 통과.

- [ ] **Step 6: 커밋**

```bash
git add src/gui/service_core.py src/gui/tracker_content_service.py data/gui-offline-sample/offline_tracker_items.json tests/test_gui_offline_item_attachments.py
git commit -m "feat: 테스트 모드 샘플 아이템의 익명 첨부 목록 제공" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Baseline 비교 탭의 변경 이력을 활동 패널로 교체

**Files:**
- Modify: `src/gui/tracker_baseline_panel.py` (생성자, 이력 탭, `set_baselines`, `reset_state`, `_select_comparison`, 이력 메서드들)
- Modify: `src/gui/tracker_baseline_workspace.py` (생성자 인자, 패널 생성, `_load_comparison_history` 교체, 내보내기 추가)
- Modify: `src/gui/tracker_workspace.py` (`_build_baseline_workspace`, `_show_error`)
- Modify: `docs/feature-status.md:34`, `docs/tracker-query-service.md:59-63`, `docs/activity-history.md:17`, `README.md:13`
- Test: `tests/test_gui_tracker_workspace.py` (`test_comparison_history_shows_field_changes_between_the_two_points` 교체, 내보내기 테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `ActivityScope`, `ItemActivityKind`, `parse_server_time`. Task 3의 `ItemActivityExportRequest`, `ItemActivityExportError`. Task 4의 `ItemActivityPanel`, `run_activity_export`.
- Produces:
  - `BaselineComparisonPanel(run_comparison, sources_changed, export_comparison, parent=None, *, request_activity: Callable[[TrackerItemComparison, ItemActivityKind, bool], None] | None = None, export_activity: Callable[[ItemActivityExportRequest], None] | None = None)`
  - `BaselineComparisonPanel.activity_panel: ItemActivityPanel`
  - `BaselineComparisonPanel.set_activity(item_id: int, kind: ItemActivityKind, data: object) -> None`
  - `BaselineComparisonPanel.set_activity_error(item_id: int, kind: ItemActivityKind, message: str) -> None`
  - `BaselineComparisonPanel.history_range(comparison)`는 그대로 둔다.
  - `BaselineWorkspacePanel(parent, *, host, settings_provider, service, context_service, comment_service, content_service)`
  - 지우는 것: `BaselineComparisonPanel.history_status`, `history_view`, `set_history`, `set_history_error`, `_refresh_history`, `_history_item_id`, 생성자 인자 `request_history`, `BaselineWorkspacePanel._load_comparison_history`

- [ ] **Step 1: 실패하는 테스트로 교체**

`tests/test_gui_tracker_workspace.py`의 import에 다음을 더한다.

```python
from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity_export import ItemActivityExportSummary
```

`test_comparison_history_shows_field_changes_between_the_two_points`를 지우고 다음 두 테스트를 그 자리에 넣는다. 둘 다 `_select_comparison_row`(기존 도우미)를 쓴다.

```python
    def _open_comparison_history(self, item_id: int = 9001001):
        """현재 상태와 샘플 Baseline을 전체 비교하고 아이템을 골라 변경 이력 탭을 연다."""
        self.page.activate()
        self.page.workspace_mode_tabs.setCurrentIndex(self.page.baseline_mode_index)
        self._app.processEvents()
        panel = self.page.baseline_workspace.baseline_comparison_panel
        panel.after_combo.setCurrentIndex(panel.after_combo.findData(24681001))
        panel.run_button.click()
        self._app.processEvents()
        self._select_comparison_row(item_id)
        return panel

    def test_comparison_history_lists_changes_comments_and_attachments_between_the_two_points(self) -> None:
        """비교 결과에서 고른 아이템의 두 시점 사이 이력을 탭을 열 때만 유형별로 조회해 시간순으로 보인다."""
        requested: list[tuple[str, int, int | None]] = []
        load_history = self.page.context_service.load_history
        load_comments = self.page.comment_service.load_comments
        load_attachments = self.page.content_service.load_attachments

        def recording_history(settings, item_id, item_version, **kwargs):
            requested.append(("history", item_id, item_version))
            return load_history(settings, item_id, item_version, **kwargs)

        def recording_comments(settings, item_id, item_version, **kwargs):
            requested.append(("comments", item_id, item_version))
            return load_comments(settings, item_id, item_version, **kwargs)

        def recording_attachments(settings, item_id, **kwargs):
            requested.append(("attachments", item_id, None))
            return load_attachments(settings, item_id, **kwargs)

        self.page.context_service.load_history = recording_history  # type: ignore[method-assign]
        self.page.comment_service.load_comments = recording_comments  # type: ignore[method-assign]
        self.page.content_service.load_attachments = recording_attachments  # type: ignore[method-assign]
        panel = self._open_comparison_history()
        activity = panel.activity_panel

        # 필드 비교만 볼 때는 이력을 묻지 않는다.
        self.assertEqual(requested, [])
        self.assertEqual(activity.status_label.text(), "#9001001 · 탭을 열면 변경 이력을 조회합니다.")
        self.assertEqual(activity.baseline_combo.currentText(), "비교 시점 사이")

        panel.detail_tabs.setCurrentWidget(panel.history_tab)
        self._app.processEvents()

        self.assertEqual(
            requested,
            [("history", 9001001, 3), ("comments", 9001001, 3), ("attachments", 9001001, None)],
        )
        # 필드 변경은 버전 1 → 3 사이, 댓글·첨부는 Baseline 생성 시각(07-15) 뒤만 남는다.
        self.assertEqual(
            activity.status_label.text(),
            "#9001001 · 비교 시점 사이 · 버전 2건 · 필드 변경 3건 · 바뀐 필드 3개 · 댓글 2건 · 첨부 1건",
        )
        view = activity.history_view
        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            [
                "댓글 · 2026-07-20 10:00 · Sample User B",
                "댓글 · 2026-07-20 09:10 · Sample User A",
                "버전 3 · 2026-07-20 09:00 · Sample User A · 필드 1개",
                "버전 2 · 2026-07-19 08:00 · Sample User B · 필드 2개",
                "첨부 · 2026-07-18 11:00 · anonymous-spec.txt · 2,048 bytes · text/plain",
            ],
        )
        risk = view.topLevelItem(2).child(0)
        self.assertEqual([risk.text(column) for column in range(3)], ["Risk Level", "-", "Medium"])
        table = activity.summary_table
        self.assertEqual(
            {table.item(row, 0).text() for row in range(table.rowCount())},
            {"Risk Level", "Summary", "Description"},
        )

        # 탭을 연 채 다른 아이템을 고르면 그 아이템을 묻는다.
        self._select_comparison_row(9001003)

        self.assertEqual(requested[-3:], [("history", 9001003, 4), ("comments", 9001003, 4), ("attachments", 9001003, None)])
        self.assertTrue(activity.status_label.text().startswith("#9001003 · 비교 시점 사이 · 버전 3건"))
        self.assertTrue(activity.status_label.text().endswith("댓글 0건 · 첨부 0건"))

        # 앞 아이템의 늦은 응답은 지금 고른 아이템 이력을 덮지 않는다.
        panel.set_activity(9001001, ItemActivityKind.FIELD_CHANGE, load_history(self.settings, 9001001, 3))
        self.assertTrue(activity.status_label.text().startswith("#9001003"))

        # 구간을 전체로 바꾸면 다시 묻지 않고 거르기만 한다.
        request_count = len(requested)
        activity.select_scope("")
        self.assertEqual(len(requested), request_count)
        self.assertTrue(activity.status_label.text().startswith("#9001003 · 전체"))

    def test_comparison_history_export_saves_the_visible_range_in_background(self) -> None:
        panel = self._open_comparison_history()
        panel.detail_tabs.setCurrentWidget(panel.history_tab)
        self._app.processEvents()
        activity = panel.activity_panel
        tasks = []
        self.page.synchronous = False
        self.page.task_factory = lambda operation: tasks.append(_DeferredTask(operation)) or tasks[-1]
        summary = ItemActivityExportSummary(entry_count=5, row_count=6, long_value_count=0)

        with (
            patch(
                "src.gui.item_activity_panel.QFileDialog.getSaveFileName",
                return_value=("history.xlsx", "Excel 통합 문서 (*.xlsx)"),
            ),
            patch("src.gui.item_activity_panel.export_item_activity_xlsx", return_value=summary) as export_mock,
        ):
            activity.export_button.click()

            self.assertEqual(len(tasks), 1)
            export_mock.assert_not_called()
            self.assertFalse(activity.export_button.isEnabled())
            self.assertIn("Excel 파일을 만드는 중입니다.", activity.status_label.text())

            tasks[0].finish()

        request = export_mock.call_args.args[0]
        tracker = self.page._current_tracker
        self.assertEqual(request.tracker_name, f"{tracker.name} (ID {tracker.tracker_id})")
        self.assertEqual(request.scope_label, "비교 시점 사이")
        self.assertEqual(request.kind_labels, ("필드 변경", "댓글", "첨부"))
        self.assertEqual(len(request.entries), 5)
        self.assertTrue(activity.export_button.isEnabled())
        self.assertTrue(activity.status_label.text().endswith("Excel 내보내기 완료 · 항목 5건 · 행 6개"))
```

`requested[-3:]` 단언 줄이 120자를 넘으면 괄호 안에서 줄을 나눈다.

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_tracker_workspace -k comparison_history -v`
Expected: FAIL, `AttributeError: 'BaselineComparisonPanel' object has no attribute 'activity_panel'`

- [ ] **Step 3: 비교 패널 교체**

`src/gui/tracker_baseline_panel.py`

import에서 Task 2의 임시 import 두 줄(`history_entries`, `merge_entries`), `from .item_change_history_view import ItemChangeHistoryView`, `from .tracker_item_context_models import ItemHistorySnapshot`을 지우고 다음을 넣는다.

```python
from datetime import UTC
from datetime import datetime
from typing import Any

from .item_activity import ActivityScope
from .item_activity import ItemActivityKind
from .item_activity import parse_server_time
from .item_activity_export import ItemActivityExportRequest
from .item_activity_panel import ItemActivityPanel
```

(`from datetime ...`, `from typing ...`는 표준 라이브러리 import 구역에, 나머지는 상대 import 구역에 정렬해 넣는다. ruff `I`가 순서를 고친다.)

생성자 시그니처의 `request_history` 인자를 다음 두 인자로 바꾼다.

```python
        request_activity: Callable[[TrackerItemComparison, ItemActivityKind, bool], None] | None = None,
        export_activity: Callable[[ItemActivityExportRequest], None] | None = None,
```

생성자 본문의 `self._request_history = request_history`와 `self._history_item_id: int | None = None` 두 줄(그 위 주석 포함)을 다음으로 바꾼다.

```python
        # 고른 아이템의 이력·댓글·첨부를 유형마다 받는다. 두 시점 사이 구간은 활동 패널이 거른다.
        self._request_activity = request_activity
        self._baselines: dict[int, TrackerBaseline] = {}
```

`# 이력은 탭을 열 때만 조회한다.` 주석부터 `self.detail_tabs.currentChanged.connect(self._refresh_history)`까지를 다음으로 바꾼다. `layout.addWidget(self.detail_tabs, 1)`과 `self._select_comparison(None)`은 그대로 둔다.

```python
        # 이력은 탭을 열 때만 조회한다. 아이템을 고를 때마다 서버에 묻지 않게 한다.
        self.detail_tabs = QTabWidget(self)
        self.detail_tabs.addTab(self.detail, "필드 비교")
        self.history_tab = QWidget(self.detail_tabs)
        history_layout = QVBoxLayout(self.history_tab)
        history_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_panel = ItemActivityPanel(
            self.history_tab,
            request_kind=self._request_activity_kind,
            between_points=True,
        )
        if export_activity is not None:
            self.activity_panel.export_requested.connect(export_activity)
        history_layout.addWidget(self.activity_panel, 1)
        self.detail_tabs.addTab(self.history_tab, "변경 이력")
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
```

`set_baselines`의 끝(`self.status_label.setText(...)` 앞)에 넣는다.

```python
        self._baselines = {baseline.baseline_id: baseline for baseline in baselines}
        self.activity_panel.set_baselines(baselines)
```

`reset_state`의 `self.clear_result(message)` 앞에 넣는다.

```python
        self._baselines = {}
        self.activity_panel.set_baselines(())
```

`set_result`의 다음 두 줄을 지운다(새 비교 결과는 새 비교 객체라 `_select_comparison`이 이력을 다시 고른다).

```python
        # 비교를 다시 받았으면 같은 아이템이라도 이력 범위가 달라질 수 있다.
        self._history_item_id = None
```

`_select_comparison`, `_refresh_history`, `set_history`, `set_history_error`를 지우고 다음을 넣는다. `history_range`는 그대로 둔다.

```python
    def _select_comparison(self, comparison: TrackerItemComparison | None) -> None:
        # 같은 비교 결과에서 같은 아이템을 다시 고르면 받아 둔 이력을 그대로 둔다.
        if comparison is not None and comparison is self._selected_comparison:
            return
        self._selected_comparison = comparison
        if comparison is None:
            self.activity_panel.set_item(
                None, waiting_message="아이템을 고르면 두 시점 사이 변경 이력을 볼 수 있습니다."
            )
            return
        self.activity_panel.set_item(
            comparison.item_id,
            item_name=comparison.name,
            between_scope=self._between_points_scope(comparison),
        )

    def _on_detail_tab_changed(self, _index: int) -> None:
        self.activity_panel.set_active(self.detail_tabs.currentWidget() is self.history_tab)

    def _request_activity_kind(self, kind: ItemActivityKind, force: bool) -> None:
        comparison = self._selected_comparison
        if comparison is not None and self._request_activity is not None:
            self._request_activity(comparison, kind, force)

    def _between_points_scope(self, comparison: TrackerItemComparison) -> ActivityScope | None:
        """두 시점 사이 구간. 필드 변경은 버전 범위, 댓글·첨부는 두 시점의 생성 시각 사이로 거른다."""
        version_range = self.history_range(comparison)
        result = self._result
        if version_range is None or result is None:
            return None
        present = [
            source
            for summary, source in (
                (comparison.reference, result.reference_source),
                (comparison.comparison, result.comparison_source),
            )
            if summary is not None
        ]
        times: list[datetime | None] = []
        unknown = False
        for source in present:
            if source.is_head:
                # 현재 상태는 상한이 없다.
                times.append(None)
                continue
            baseline = self._baselines.get(int(source.baseline_id or 0))
            created_at = parse_server_time(baseline.created_at if baseline is not None else "")
            unknown = unknown or created_at is None
            times.append(created_at)
        if len(times) == 1:
            # 한쪽에만 있는 아이템은 처음부터 그 시점까지다.
            start, end = None, times[0]
        else:
            earliest = datetime.min.replace(tzinfo=UTC)
            start, end = sorted(times, key=lambda value: (value is None, value or earliest))
        return ActivityScope(
            "비교 시점 사이",
            after=start,
            until=end,
            versions=version_range,
            time_undetermined=unknown,
        )

    def set_activity(self, item_id: int, kind: ItemActivityKind, data: Any) -> None:
        self.activity_panel.set_source(int(item_id), kind, data)

    def set_activity_error(self, item_id: int, kind: ItemActivityKind, message: str) -> None:
        self.activity_panel.set_source_error(int(item_id), kind, message)
```

`set_result`의 `self._select_comparison(None)` 경로와 `select_item`은 그대로 둔다.

- [ ] **Step 4: 작업공간 연결**

`src/gui/tracker_baseline_workspace.py`

import에 다음을 더한다.

```python
from dataclasses import replace

from .item_activity import ItemActivityKind
from .item_activity_export import ItemActivityExportRequest
from .item_activity_panel import run_activity_export
```

생성자에 키워드 인자 두 개를 더하고 보관한다.

```python
        comment_service: Any,
        content_service: Any,
```

```python
        # 비교 결과에서 고른 아이템의 이력·댓글·첨부. 상세 창과 같은 서비스와 캐시를 쓴다.
        self.context_service = context_service
        self.comment_service = comment_service
        self.content_service = content_service
```

(기존 `self.context_service = context_service`와 그 위 주석을 이 세 줄로 바꾼다.)

패널 생성의 `request_history=self._load_comparison_history,`를 다음 두 줄로 바꾼다.

```python
            request_activity=self._load_comparison_activity,
            export_activity=self._export_comparison_activity,
```

`_load_comparison_history`를 지우고 다음을 넣는다.

```python
    def _load_comparison_activity(
        self,
        comparison: TrackerItemComparison,
        kind: ItemActivityKind,
        force: bool,
    ) -> None:
        """고른 아이템의 이력·댓글·첨부를 유형마다 따로 받는다. 한 유형이 실패해도 나머지는 보인다."""
        settings = self.settings_provider()
        item_id = comparison.item_id
        present = [item for item in (comparison.reference, comparison.comparison) if item is not None]
        latest = max(present, key=lambda item: item.version if item.version is not None else -1, default=None)
        latest_version = latest.version if latest is not None else None
        # 더 늦은 시점의 아이템 응답에 첨부가 있으면 그것을 쓰고, 없으면 첨부 목록을 묻는다.
        raw = latest.raw_reference if latest is not None else None

        def operation() -> Any:
            if kind is ItemActivityKind.FIELD_CHANGE:
                return self.context_service.load_history(settings, item_id, latest_version, force=force)
            if kind is ItemActivityKind.COMMENT:
                return self.comment_service.load_comments(settings, item_id, latest_version, force=force)
            return self.content_service.load_attachments(settings, item_id, raw_payload=raw)

        panel = self.baseline_comparison_panel
        self._host.submit(
            f"baseline_item_activity:{kind.value}",
            operation,
            lambda data: panel.set_activity(item_id, kind, data),
            lambda exc: panel.set_activity_error(item_id, kind, str(exc)),
        )

    def _export_comparison_activity(self, request: ItemActivityExportRequest) -> None:
        tracker = self._host.current_tracker()
        project = self._host.current_project()
        if tracker is not None:
            request = replace(request, tracker_name=f"{tracker.name} (ID {tracker.tracker_id})")
        run_activity_export(
            self,
            self.baseline_comparison_panel.activity_panel,
            request,
            submit=self._host.submit,
            record_activity=self._host.record_activity,
            show_error=self._host.show_error,
            source="tracker_workspace",
            project_id=project.project_id if project else (tracker.project_id if tracker else None),
            project_name=project.name if project else (tracker.project_name if tracker else ""),
            tracker_id=tracker.tracker_id if tracker else None,
            tracker_name=tracker.name if tracker else "",
        )
```

`src/gui/tracker_workspace.py`

`_build_baseline_workspace`의 `BaselineWorkspacePanel(...)` 호출에 두 인자를 더한다.

```python
            comment_service=self.comment_service,
            content_service=self.content_service,
```

`_show_error`의 오류 종류 튜플에 `ItemActivityExportError`를 더하고 import한다.

```python
from .item_activity_export import ItemActivityExportError
```

- [ ] **Step 5: 문서 갱신**

`docs/feature-status.md` 34행의 `` `변경 이력` 탭을 열면 두 시점 사이 버전의 수정자·시각과 필드별 이전 → 새 값을 표시(탭을 열 때만 조회)``를 다음으로 바꾼다.

```markdown
`변경 이력` 탭에서 두 시점 사이·기준 Baseline 이후·전체 중 구간을 고르고 필드 변경·댓글·첨부 유형을 골라 시간순 이력과 필드별 구간 처음·마지막 값·변경 횟수 요약을 보며, `이력 Excel 내보내기`로 요약·필드별 요약·이력 시트를 저장(유형마다 탭을 열 때만 조회, 관계는 응답에 시각이 없어 미지원)
```

`docs/tracker-query-service.md`의 변경 이력 문단(59~63행, "한쪽에만 있는 아이템은 처음부터 그 버전까지 보입니다."로 끝남) 뒤에 문단을 더한다.

```markdown
변경 이력 탭은 이력·댓글·첨부 응답을 `item_activity`의 활동 항목으로 합쳐 시간순으로 보입니다. 기준 Baseline을 고르면
그 생성 시각 뒤(같은 시각은 Baseline에 든 것으로 보고 제외)의 항목만 남기고, 생성 시각이 없는 Baseline은 기준으로 고를 수
없습니다. Baseline 비교의 `비교 시점 사이`는 필드 변경을 위처럼 버전 범위로, 댓글·첨부를 두 시점의 생성 시각 사이로
거릅니다. 첨부 시각은 첨부 목록의 `modifiedAt`이라 지워진 첨부는 나오지 않습니다. 관계 응답에는 시각이 없어 이력 유형으로
지원하지 않습니다. 구간과 유형을 바꿔도 다시 조회하지 않고 받아 둔 응답을 거르기만 합니다.
```

`docs/activity-history.md`의 표에서 `| Baseline Excel 내보내기 |` 행 다음에 행을 더한다.

```markdown
| 변경 이력 Excel 내보내기 | 파일 저장 완료·실패 | 아이템, 유형 수, 이력 항목 수, 생성된 행 수, 긴 값 수 |
```

`README.md` 13행 다음에 한 줄을 더한다.

```markdown
- 아이템 변경 이력을 기준 Baseline 이후로 추려 필드 변경·댓글·첨부별로 보고 Excel로 내보냅니다.
```

- [ ] **Step 6: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_tracker_workspace -q`
Expected: PASS. 이어서 전체 테스트, ruff, mypy 통과. `rg -n "history_status|set_history\b|request_history" src/gui/tracker_baseline_panel.py src/gui/tracker_baseline_workspace.py`가 아무것도 찾지 않아야 한다.

- [ ] **Step 7: 커밋**

```bash
git add src/gui/tracker_baseline_panel.py src/gui/tracker_baseline_workspace.py src/gui/tracker_workspace.py tests/test_gui_tracker_workspace.py docs/feature-status.md docs/tracker-query-service.md docs/activity-history.md README.md
git commit -m "feat: Baseline 비교 변경 이력의 기준 Baseline·유형 선택과 Excel 내보내기" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: 상세 창의 변경 이력을 활동 패널로 교체

**Files:**
- Modify: `src/gui/tracker_item_detail_dialog.py` (시그널, 생성자, 이력 탭, 문맥 탭 처리, `set_history` 교체, `replace_detail`, Baseline 안내)
- Modify: `src/gui/tracker_detail_dialog.py` (`open_dialog`, `load_context`, `load_activity`·`export_activity` 추가)
- Modify: `src/gui/tracker_workspace.py` (Baseline 목록 보관)
- Modify: `docs/feature-status.md:89,91`, `docs/tracker-query-service.md` (댓글 문단 끝 문장)
- Test: `tests/test_gui_tracker_item_detail_dialog.py`, `tests/test_gui_tracker_workspace.py`

**Interfaces:**
- Consumes: Task 1의 `BaselineMarker`, `ItemActivityKind`, `baseline_scope`, `parse_server_time`. Task 4의 `ItemActivityPanel`, `ALL_SCOPE_DATA`, `run_activity_export`.
- Produces:
  - `TrackerItemDetailDialog(detail, *, description_html, attachments=(), image_resources=(), baseline_id=None, baselines: tuple[TrackerBaseline, ...] = (), parent=None)`
  - 시그널 `activity_requested(str, bool)`: `ItemActivityKind.value`, force
  - 시그널 `history_export_requested(object)`: `ItemActivityExportRequest`
  - `TrackerItemDetailDialog.activity_panel`, `set_activity(item_id, kind, data)`, `set_activity_error(item_id, kind, message)`
  - `DetailDialogController.load_activity(dialog, session, kind, *, force=False)`, `export_activity(dialog, request)`
  - `TrackerWorkspacePage._tracker_baselines: tuple[TrackerBaseline, ...]`
  - 지우는 것: `TrackerItemDetailDialog.history_status`, `history_retry`, `history_view`, `set_history`, `context_tab_requested("history", ...)` 경로

- [ ] **Step 1: 실패하는 테스트로 교체**

`tests/test_gui_tracker_item_detail_dialog.py`

import에 다음을 더한다.

```python
from src.gui.item_activity import ItemActivityKind
from src.gui.tracker_baseline_compare import TrackerBaseline
```

모듈 수준에 도우미를 두고, `test_baseline_dialog_loads_history_but_not_current_relations` 안의 `ItemHistorySnapshot.from_raw({...})` 덩어리를 이 도우미 호출로 바꾼다.

```python
def _history_snapshot() -> ItemHistorySnapshot:
    return ItemHistorySnapshot.from_raw(
        {
            "versions": [
                {
                    "itemRevision": {"version": version},
                    "modifiedAt": f"2026-07-2{version}T09:00:00",
                    "modifiedBy": {"name": "Sample User A"},
                    "changes": [
                        {
                            "field": {"id": 3, "name": "Summary"},
                            "oldValue": {"fieldId": 3, "value": f"v{version - 1}"},
                            "newValue": {"fieldId": 3, "value": f"v{version}"},
                        }
                    ],
                }
                for version in (5, 4, 3)
            ]
        }
    )
```

`test_baseline_dialog_loads_history_but_not_current_relations`를 다음으로 바꾼다.

```python
    def test_baseline_dialog_loads_history_but_not_current_relations(self) -> None:
        """관계는 현재 것만 있어 Baseline 창에서 묻지 않는다. 이력·댓글·첨부는 전체 기록이라 묻고 Baseline 이후를 나눈다."""
        dialog = TrackerItemDetailDialog(self.detail(), description_html="", baseline_id=7)
        context_requests = []
        activity_requests = []
        dialog.context_tab_requested.connect(lambda kind, force: context_requests.append((kind, force)))
        dialog.activity_requested.connect(lambda kind, force: activity_requests.append((kind, force)))
        dialog.show()
        dialog.tabs.setCurrentWidget(dialog.relations_tab)
        dialog.tabs.setCurrentWidget(dialog.history_tab)
        self.app.processEvents()

        self.assertEqual(context_requests, [])
        self.assertEqual(activity_requests, [("field_change", False), ("comment", False), ("attachment", False)])
        self.assertIn("현재 상태를 대신 조회하지 않습니다", dialog.relations_status.text())

        dialog.set_activity(1205, ItemActivityKind.FIELD_CHANGE, _history_snapshot())

        view = dialog.activity_panel.history_view
        rows = [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())]
        # 목록에 없는 Baseline이라 전체 구간이고, 이 창의 버전 4 뒤인 버전 5만 Baseline 이후로 나눈다.
        self.assertEqual(
            rows,
            [
                "[Baseline 이후] 버전 5 · 2026-07-25 09:00 · Sample User A · 필드 1개",
                "── Baseline #7 시점 (버전 4) ──",
                "버전 4 · 2026-07-24 09:00 · Sample User A · 필드 1개",
                "버전 3 · 2026-07-23 09:00 · Sample User A · 필드 1개",
            ],
        )
        change = view.topLevelItem(0).child(0)
        self.assertEqual([change.text(column) for column in range(3)], ["Summary", "v4", "v5"])
        self.assertIn("댓글·첨부는 현재 목록이며 Baseline 시점 내용이 아닙니다", dialog.activity_panel.status_label.text())
        dialog.close()

    def test_baseline_dialog_starts_after_its_baseline_when_the_list_knows_it(self) -> None:
        baselines = (TrackerBaseline(7, "Sample Baseline", "2026-07-24T12:00:00Z"),)
        dialog = TrackerItemDetailDialog(self.detail(), description_html="", baseline_id=7, baselines=baselines)

        self.assertEqual(dialog.activity_panel.baseline_combo.currentData(), 7)

        dialog.set_activity(1205, ItemActivityKind.FIELD_CHANGE, _history_snapshot())

        view = dialog.activity_panel.history_view
        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            ["[Baseline 이후] 버전 5 · 2026-07-25 09:00 · Sample User A · 필드 1개"],
        )
        dialog.close()

    def test_current_dialog_shows_the_whole_history_and_marks_the_current_version(self) -> None:
        dialog = TrackerItemDetailDialog(self.detail(), description_html="")

        dialog.set_activity(1205, ItemActivityKind.FIELD_CHANGE, _history_snapshot())

        self.assertEqual(dialog.activity_panel.baseline_combo.currentData(), "")
        current_row = dialog.activity_panel.history_view.topLevelItem(1)
        self.assertEqual(current_row.text(0), "버전 4 (현재) · 2026-07-24 09:00 · Sample User A · 필드 1개")
        dialog.close()
```

`test_replacing_detail_resets_context_and_comments_for_lazy_reload`의 `dialog.history_view.topLevelItemCount()`를 `dialog.activity_panel.history_view.topLevelItemCount()`로 바꾼다.

`tests/test_gui_tracker_workspace.py`의 `test_baseline_detail_dialog_history_marks_changes_after_the_baseline`에서 `dialog.tabs.setCurrentWidget(dialog.history_tab)`·`processEvents` 다음 단언을 다음으로 바꾼다(관계 안내 단언은 둔다).

```python
        activity = dialog.activity_panel
        self.assertEqual(dialog.detail.version, 1)
        self.assertEqual(activity.baseline_combo.currentData(), 24681001)
        self.assertEqual(
            activity.status_label.text(),
            "#9001001 · Offline Requirements Baseline 이후 · 버전 2건 · 필드 변경 3건 · 바뀐 필드 3개"
            " · 댓글 2건 · 첨부 1건 · 댓글·첨부는 현재 목록이며 Baseline 시점 내용이 아닙니다",
        )
        view = activity.history_view
        self.assertEqual(
            [view.topLevelItem(index).text(0) for index in range(view.topLevelItemCount())],
            [
                "[Baseline 이후] 댓글 · 2026-07-20 10:00 · Sample User B",
                "[Baseline 이후] 댓글 · 2026-07-20 09:10 · Sample User A",
                "[Baseline 이후] 버전 3 · 2026-07-20 09:00 · Sample User A · 필드 1개",
                "[Baseline 이후] 버전 2 · 2026-07-19 08:00 · Sample User B · 필드 2개",
                "[Baseline 이후] 첨부 · 2026-07-18 11:00 · anonymous-spec.txt · 2,048 bytes · text/plain",
            ],
        )
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_tracker_item_detail_dialog tests.test_gui_tracker_workspace -q`
Expected: FAIL, `activity_requested`·`activity_panel` 속성이 없고 `baselines` 인자를 받지 못한다.

- [ ] **Step 3: 상세 창 교체**

`src/gui/tracker_item_detail_dialog.py`

import에서 `from .item_change_history_view import ItemChangeHistoryView`, Task 2의 임시 import(`history_entries`, `merge_entries`), 쓰이지 않게 되는 `ItemHistorySnapshot`을 지우고 다음을 넣는다(`BaselineMarker`는 이미 있다).

```python
from typing import Any

from .item_activity import ItemActivityKind
from .item_activity import baseline_scope
from .item_activity import parse_server_time
from .item_activity_panel import ALL_SCOPE_DATA
from .item_activity_panel import ItemActivityPanel
from .tracker_baseline_compare import TrackerBaseline
```

시그널 정의(`context_tab_requested = Signal(str, bool)` 근처)에 두 줄을 더한다.

```python
    # 변경 이력 탭의 유형 하나를 받아 달라는 요청. 값은 `ItemActivityKind.value`와 force다.
    activity_requested = Signal(str, bool)
    history_export_requested = Signal(object)
```

생성자 시그니처의 `baseline_id: int | None = None,` 다음에 `baselines: tuple[TrackerBaseline, ...] = (),`를 넣고, 본문의 `self.baseline_id = baseline_id` 다음에 `self.baselines = tuple(baselines)`를 넣는다. `self._context_states = {"relations": "idle", "history": "idle"}`를 `self._context_states = {"relations": "idle"}`로 바꾼다.

`if baseline_id is not None: self._show_baseline_context_notice()` 블록 바로 앞에 넣는다.

```python
        self.activity_panel.set_baselines(self.baselines)
        self._reset_activity()
```

`_build_history_tab`을 다음으로 바꾼다.

```python
    def _build_history_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        self.activity_panel = ItemActivityPanel(
            tab,
            request_kind=lambda kind, force: self.activity_requested.emit(kind.value, force),
        )
        self.activity_panel.export_requested.connect(self.history_export_requested.emit)
        layout.addWidget(self.activity_panel, 1)
        return tab

    def _reset_activity(self) -> None:
        """이 창의 아이템으로 변경 이력 탭을 맞춘다.

        Baseline 창이면 그 Baseline 버전으로 `[Baseline 이후]`를 가르고, 목록에 생성 시각이 있으면 그 Baseline
        이후 구간에서 시작한다. 현재 창은 전체 구간이다.
        """
        detail = self.detail
        marker = None
        scope: int | str = ALL_SCOPE_DATA
        if self.baseline_id is not None:
            baseline = next((value for value in self.baselines if value.baseline_id == self.baseline_id), None)
            name = baseline.name if baseline is not None else f"Baseline #{self.baseline_id}"
            created_at = baseline.created_at if baseline is not None else ""
            marker = BaselineMarker(name, version=detail.version, created_at=parse_server_time(created_at))
            if baseline is not None and baseline_scope(baseline.name, baseline.created_at) is not None:
                scope = baseline.baseline_id
        self.activity_panel.set_item(
            detail.item_id,
            item_name=detail.summary.name,
            tracker_name=detail.summary.tracker_name,
            current_version=detail.version if self.baseline_id is None else None,
            marker=marker,
        )
        self.activity_panel.select_scope(scope)
        if self.baseline_id is not None:
            self.activity_panel.set_note("댓글·첨부는 현재 목록이며 Baseline 시점 내용이 아닙니다")

    def set_activity(self, item_id: int, kind: ItemActivityKind, data: Any) -> None:
        self.activity_panel.set_source(int(item_id), kind, data)

    def set_activity_error(self, item_id: int, kind: ItemActivityKind, message: str) -> None:
        self.activity_panel.set_source_error(int(item_id), kind, message)
```

`_context_tab_changed`를 다음으로 바꾼다.

```python
    def _context_tab_changed(self, _index: int) -> None:
        if (
            self.baseline_id is None
            and self.tabs.currentWidget() is self.relations_tab
            and self._context_states["relations"] == "idle"
        ):
            self.set_context_loading("relations")
            self.context_tab_requested.emit("relations", False)
        self.activity_panel.set_active(self.tabs.currentWidget() is self.history_tab)
```

`set_context_loading`, `set_context_error`는 관계만 남는다.

```python
    def set_context_loading(self, kind: str) -> None:
        self._context_states[kind] = "loading"
        self.relations_status.setText("불러오는 중입니다.")
        self.relations_retry.hide()

    def set_context_error(self, kind: str, message: str) -> None:
        self._context_states[kind] = "error"
        self.relations_status.setText(message)
        self.relations_retry.show()
```

`set_history` 메서드를 통째로 지운다.

`_show_baseline_context_notice`에서 `self.history_status.setText(...)` 한 줄을 지우고, 독스트링 둘째 문단을 "변경 이력은 시점과 관계없는 아이템 전체 기록이라 이력·현재 댓글·현재 첨부를 받고, 활동 패널이 Baseline 이후를 나눠 보인다."로 바꾼다.

`replace_detail`에서

```python
        self._context_states = {"relations": "idle", "history": "idle"}
```

를 `self._context_states = {"relations": "idle"}`로 바꾸고, `self.history_view.clear()`, `self.history_status.setText(...)`, `self.history_retry.hide()` 세 줄을 지운다. `self._comments_state = "idle"`(두 번째) 다음 줄에 넣는다.

```python
        # 탭을 처음으로 되돌리므로 새 아이템 이력은 탭을 다시 열 때 묻는다.
        self.activity_panel.set_active(False)
        self._reset_activity()
```

- [ ] **Step 4: 컨트롤러와 작업공간 연결**

`src/gui/tracker_workspace.py`

생성자의 `self._activated = False` 근처에 넣는다.

```python
        # 지금 트래커의 Baseline 목록. 상세 창의 기준 Baseline 선택에 넘긴다.
        self._tracker_baselines: tuple[TrackerBaseline, ...] = ()
```

`_refresh_baseline_comparison`의 `loaded` 안 `self.hierarchy_panel.set_baselines(baselines)` 앞에 `self._tracker_baselines = baselines`, `failed` 안 `self.hierarchy_panel.set_baselines(())` 앞에 `self._tracker_baselines = ()`를 넣는다. `_reset_baseline_state`의 첫 줄에도 `self._tracker_baselines = ()`를 넣는다.

`src/gui/tracker_detail_dialog.py`

import에 다음을 더한다.

```python
from typing import Any

from .item_activity import ItemActivityKind
from .item_activity_export import ItemActivityExportRequest
from .item_activity_panel import run_activity_export
```

`open_dialog`의 `TrackerItemDetailDialog(...)` 호출에 `baselines=self.page._tracker_baselines,`를 더하고, `dialog.context_tab_requested.connect(...)` 다음에 넣는다.

```python
        dialog.activity_requested.connect(
            lambda kind, force=False: self.load_activity(dialog, session, ItemActivityKind(kind), force=force)
        )
        dialog.history_export_requested.connect(lambda request: self.export_activity(dialog, request))
```

`load_context`를 관계만 받도록 줄인다.

```python
    def load_context(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        kind: str,
        *,
        force: bool = False,
    ) -> None:
        # 관계는 조회 시점의 것이라 Baseline 창에서 막는다. 변경 이력은 `load_activity`가 받는다.
        if kind != "relations" or dialog.baseline_id is not None:
            return
        detail = dialog.detail
        generation = session.generation
        dialog.set_context_loading(kind)
        settings = self.page.settings_provider()

        def current() -> bool:
            return (
                isValid(dialog)
                and dialog.isVisible()
                and session.generation == generation
                and session.current.item_id == detail.item_id
            )

        self.page._submit(
            "detail_dialog_relations",
            lambda: self.page.context_service.load_relations(settings, detail.item_id, detail.version, force=force),
            lambda result: dialog.set_relations(result) if current() else None,
            lambda exc: dialog.set_context_error(kind, str(exc)) if current() else None,
        )

    def load_activity(
        self,
        dialog: TrackerItemDetailDialog,
        session: TrackerItemDetailSession,
        kind: ItemActivityKind,
        *,
        force: bool = False,
    ) -> None:
        """변경 이력 탭의 유형 하나를 받는다. 이력·댓글·첨부는 아이템 전체 기록이라 Baseline 창도 받는다."""
        detail = dialog.detail
        generation = session.generation
        settings = self.page.settings_provider()

        def current() -> bool:
            return (
                isValid(dialog)
                and dialog.isVisible()
                and session.generation == generation
                and dialog.detail.item_id == detail.item_id
            )

        def operation() -> Any:
            if kind is ItemActivityKind.FIELD_CHANGE:
                return self.page.context_service.load_history(settings, detail.item_id, detail.version, force=force)
            if kind is ItemActivityKind.COMMENT:
                return self.page.comment_service.load_comments(settings, detail.item_id, detail.version, force=force)
            # Baseline 창의 아이템 응답은 그 시점 것이라 첨부 목록을 따로 묻는다.
            raw = detail.raw_payload if dialog.baseline_id is None else None
            return self.page.content_service.load_attachments(settings, detail.item_id, raw_payload=raw)

        self.page._submit(
            f"detail_dialog_activity:{kind.value}",
            operation,
            lambda data: dialog.set_activity(detail.item_id, kind, data) if current() else None,
            lambda exc: dialog.set_activity_error(detail.item_id, kind, str(exc)) if current() else None,
        )

    def export_activity(self, dialog: TrackerItemDetailDialog, request: ItemActivityExportRequest) -> None:
        tracker = self.page._current_tracker
        project = self.page._current_project
        run_activity_export(
            dialog,
            dialog.activity_panel,
            request,
            submit=self.page._submit,
            record_activity=self.page._record_activity,
            show_error=self.page._show_error,
            source="tracker_detail_dialog",
            project_id=project.project_id if project else (tracker.project_id if tracker else None),
            project_name=project.name if project else (tracker.project_name if tracker else ""),
            tracker_id=tracker.tracker_id if tracker else None,
            tracker_name=tracker.name if tracker else "",
        )
```

`page._submit`의 키가 `detail_dialog_activity:...`이면 진단 종류는 앞부분 `tracker_detail_dialog_activity`로 묶인다. 유형마다 키가 달라 서로의 응답을 취소하지 않는다.

- [ ] **Step 5: 문서 갱신**

`docs/feature-status.md` 89행의 `(이력은 버전별 수정자·시각과 필드별 이전 → 새 값)`을 `(변경 이력은 Baseline 비교와 같은 패널로 구간·유형을 골라 보고 Excel로 내보냄)`으로 바꾼다.

91행의 `변경 이력은 시점과 관계없는 아이템 전체 이력이라 조회하고, 그 Baseline 버전 위치에 구분선을 두고 이후 변경에 `[Baseline 이후]`를 표시`를 다음으로 바꾼다.

```markdown
변경 이력은 시점과 관계없는 아이템 전체 기록이라 이력·현재 댓글·현재 첨부를 받고, Baseline 목록에 생성 시각이 있으면 그 Baseline 이후 구간에서 시작하며 이후 항목에 `[Baseline 이후]`를 표시(댓글 탭은 계속 막음)
```

`docs/tracker-query-service.md` 댓글 문단 끝의 `Baseline에서는 현재 댓글 endpoint를 호출하지 않습니다.`를 다음으로 바꾼다.

```markdown
Baseline 상세의 댓글 탭은 현재 댓글 endpoint를 호출하지 않습니다. 변경 이력 탭은 아이템 전체 기록으로 현재 댓글과 첨부
목록을 받아 `[Baseline 이후]`로 나눠 보이고, Baseline 시점 내용이 아니라는 안내를 상태줄에 둡니다.
```

- [ ] **Step 6: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_gui_tracker_item_detail_dialog tests.test_gui_tracker_workspace -q`
Expected: PASS. 이어서 전체 테스트, ruff, mypy 통과. `rg -n "history_status|history_retry|set_history\b" src/gui`가 아무것도 찾지 않아야 한다.

- [ ] **Step 7: 커밋**

```bash
git add src/gui/tracker_item_detail_dialog.py src/gui/tracker_detail_dialog.py src/gui/tracker_workspace.py tests/test_gui_tracker_item_detail_dialog.py tests/test_gui_tracker_workspace.py docs/feature-status.md docs/tracker-query-service.md
git commit -m "feat: 상세 창 변경 이력의 기준 Baseline·유형 선택과 Excel 내보내기" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: 실서버 응답 구조 확인 스크립트와 todo.md

**Files:**
- Create: `scripts/inspect_item_activity_contract.py`
- Create: `todo.md`
- Test: `tests/test_inspect_item_activity_contract.py`

**Interfaces:**
- Consumes: `CodebeamerClient.get_item_history`, `get_item_comments`, `get_item_attachments`, `get_item_relations`
- Produces: `summarize_contract(history, comments, attachments, relations) -> list[str]`, `failure_text(exc: Exception) -> str`, `main() -> int`

사용자가 화면을 캡처해 회사 밖으로 보낸다. 화면에는 API 스키마의 키 이름, `type` 값, 건수, 미리 정한 안내 문구만 찍는다. 키와 `type` 값도 영문자로 시작하는 40자 이하 식별자 모양일 때만 이름을 찍고, 아니면 `기타 N개`로 센다. 서버 주소는 입력 뒤 화면을 지워 남기지 않는다. 오류는 HTTP 상태 번호와 할 일만 찍고 예외 메시지는 찍지 않는다. 전체 응답은 `%TEMP%` 파일에 남겨 사용자 PC에서만 본다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_inspect_item_activity_contract.py`:

```python
from __future__ import annotations

import unittest
from types import SimpleNamespace

import requests

from scripts.inspect_item_activity_contract import MAX_LINES
from scripts.inspect_item_activity_contract import WIDTH
from scripts.inspect_item_activity_contract import failure_text
from scripts.inspect_item_activity_contract import summarize_contract


HISTORY = {
    "versions": [
        {
            "itemRevision": {"version": 2, "name": "secret item name"},
            "modifiedAt": "2026-07-20T09:00:00Z",
            "modifiedBy": {"name": "secret-user"},
            "changes": [
                {
                    "type": "TrackerItemChange",
                    "field": {"id": 1, "name": "secret field", "type": "FieldReference"},
                    "name": "secret field",
                    "oldValue": {"value": "secret old", "type": "TextFieldValue"},
                    "newValue": {"value": "secret new", "type": "TextFieldValue"},
                },
                {"type": "secret type with spaces", "name": "secret comment"},
            ],
        }
    ],
    "secret key with spaces": 1,
}
COMMENTS = [{"id": 1, "comment": "secret body", "createdBy": {"name": "secret-user"}, "createdAt": "2026-07-20"}]
ATTACHMENTS = [{"id": 2, "name": "secret-file.txt", "modifiedAt": "2026-07-18", "createdBy": {"name": "secret-user"}}]
RELATIONS = {
    "downstreamReferences": [{"id": "secret-relation", "type": "OutgoingTrackerItemAssociation",
                              "itemRevision": {"name": "secret target"}}],
    "upstreamReferences": [],
}


class InspectItemActivityContractTest(unittest.TestCase):
    def test_report_lists_only_schema_names_and_counts(self) -> None:
        lines = summarize_contract(HISTORY, COMMENTS, ATTACHMENTS, RELATIONS)
        text = "\n".join(lines)

        self.assertNotIn("secret", text)
        self.assertLessEqual(len(lines), MAX_LINES)
        self.assertTrue(all(len(line) <= WIDTH for line in lines))
        self.assertIn("[변경 이력] 버전 1건 · 변경 2건", text)
        self.assertIn("응답 키: versions (기타 1개)", text)
        self.assertIn("변경 type 값: TrackerItemChange (기타 1개)", text)
        self.assertIn("field 없는 변경: 1건", text)
        self.assertIn("[댓글] 1건", text)
        self.assertIn("[첨부] 1건", text)
        self.assertIn("createdAt 0 · createdBy 1 · modifiedAt 1 · modifiedBy 0", text)
        self.assertIn("[관계] 그룹 2개 · 항목 1건", text)
        self.assertIn("관계 type 값: OutgoingTrackerItemAssociation", text)

    def test_missing_responses_are_reported_as_empty(self) -> None:
        lines = summarize_contract(None, None, None, None)

        self.assertIn("[변경 이력] 버전 0건 · 변경 0건", lines)
        self.assertIn("[관계] 그룹 0개 · 항목 0건", lines)

    def test_failures_show_kind_and_action_without_the_message(self) -> None:
        http_error = requests.HTTPError("secret path /items/1")
        http_error.response = SimpleNamespace(status_code=403)
        server_error = requests.HTTPError("secret")
        server_error.response = SimpleNamespace(status_code=500)

        self.assertEqual(failure_text(http_error), "HTTP 403 권한 없음 · 아이템을 볼 수 있는 계정으로 다시 실행")
        self.assertEqual(failure_text(server_error), "HTTP 500 서버 오류 · 잠시 뒤 다시 실행")
        self.assertEqual(
            failure_text(requests.ConnectionError("secret host")), "연결 실패 · 서버 주소와 네트워크 확인"
        )
        self.assertEqual(failure_text(ValueError("secret")), "ValueError · 응답 형식 확인 필요")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_inspect_item_activity_contract -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scripts.inspect_item_activity_contract'`

- [ ] **Step 3: 스크립트 구현**

`scripts/inspect_item_activity_contract.py`:

```python
"""변경 이력·댓글·첨부·관계 API 응답 구조를 실서버에서 확인한다.

화면에는 응답의 키 이름, `type` 값, 건수만 찍는다. 필드 이름, 본문, 파일명, 사용자 같은 값은 찍지 않는다.
전체 응답은 임시 폴더의 파일에 써서 이 PC에서만 본다.

저장소 루트의 가상환경으로 실행한다.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "cb_item_activity_contract.json"
WIDTH = 116
MAX_LINES = 38
_SCHEMA_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_HTTP_ACTIONS = {
    401: "인증 실패 · 사용자·비밀번호 확인",
    403: "권한 없음 · 아이템을 볼 수 있는 계정으로 다시 실행",
    404: "없음 · 아이템 ID 확인",
    429: "요청 제한 · 잠시 뒤 다시 실행",
}


def _names(values: Iterable[Any]) -> str:
    values = list(values)
    safe = sorted({value for value in values if isinstance(value, str) and _SCHEMA_NAME.fullmatch(value)})
    other = len({repr(value) for value in values if not (isinstance(value, str) and _SCHEMA_NAME.fullmatch(value))})
    text = ", ".join(safe) or "-"
    return f"{text} (기타 {other}개)" if other else text


def _line(label: str, values: Iterable[Any]) -> str:
    text = f"  {label}: {_names(values)}"
    return text if len(text) <= WIDTH else text[: WIDTH - 1] + "…"


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _items(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _dicts(payload)
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), list):
                return _dicts(payload[key])
    return []


def _keys(items: Iterable[dict[str, Any]]) -> set[str]:
    return {key for item in items for key in item}


def summarize_contract(history: Any, comments: Any, attachments: Any, relations: Any) -> list[str]:
    versions = _items(history, ("versions", "history", "items", "content"))
    changes = [change for version in versions for change in _dicts(version.get("changes"))]
    fields = [change["field"] for change in changes if isinstance(change.get("field"), dict)]
    values = [
        change[side] for change in changes for side in ("oldValue", "newValue") if isinstance(change.get(side), dict)
    ]
    comment_items = _items(comments, ("comments", "items", "content"))
    attachment_items = _items(attachments, ("attachments", "attachmentRefs", "items", "references", "content"))
    groups = relations if isinstance(relations, dict) else {}
    relation_groups = [group for group in groups.values() if isinstance(group, list)]
    relation_items = [item for group in relation_groups for item in _dicts(group)]
    time_keys = ("createdAt", "createdBy", "modifiedAt", "modifiedBy")
    return [
        f"[변경 이력] 버전 {len(versions)}건 · 변경 {len(changes)}건",
        _line("응답 키", history.keys() if isinstance(history, dict) else []),
        _line("버전 키", _keys(versions)),
        _line("변경 키", _keys(changes)),
        _line("변경 type 값", [change.get("type") for change in changes if "type" in change]),
        _line("field 키", _keys(fields)),
        _line("값 type 값", [value.get("type") for value in values if "type" in value]),
        f"  field 없는 변경: {len(changes) - len(fields)}건",
        f"[댓글] {len(comment_items)}건",
        _line("댓글 키", _keys(comment_items)),
        f"[첨부] {len(attachment_items)}건",
        _line("첨부 키", _keys(attachment_items)),
        "  시각·사용자 키가 있는 첨부: "
        + " · ".join(f"{key} {sum(key in item for item in attachment_items)}" for key in time_keys),
        f"[관계] 그룹 {len(relation_groups)}개 · 항목 {len(relation_items)}건",
        _line("관계 그룹 키", groups.keys()),
        _line("관계 항목 키", _keys(relation_items)),
        _line("관계 type 값", [item.get("type") for item in relation_items if "type" in item]),
    ]


def failure_text(exc: Exception) -> str:
    """오류 종류와 할 일만 돌려준다. 예외 메시지에는 주소나 값이 들어 있을 수 있어 쓰지 않는다."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return f"HTTP {status} {_HTTP_ACTIONS.get(status, '서버 오류 · 잠시 뒤 다시 실행')}"
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return "연결 실패 · 서버 주소와 네트워크 확인"
    return f"{type(exc).__name__} · 응답 형식 확인 필요"


def _clear_screen() -> None:
    # 사용자 입력이 섞이지 않는 고정 명령이다.
    os.system("cls" if os.name == "nt" else "clear")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from src.codebeamer_client import CodebeamerClient

    _clear_screen()
    base_url = input("서버 주소: ").strip()
    username = input("사용자: ").strip()
    password = getpass.getpass("비밀번호(화면에 보이지 않음): ")
    item_text = input("아이템 ID(변경 이력·댓글·첨부가 있는 것): ").strip()
    # 입력한 주소와 계정이 캡처에 남지 않게 지운다.
    _clear_screen()
    if not item_text.isdigit():
        print("아이템 ID는 숫자여야 합니다. 다시 실행하세요.")
        return 2
    client = CodebeamerClient(base_url, username, password)
    item_id = int(item_text)
    calls = {
        "history": client.get_item_history,
        "comments": client.get_item_comments,
        "attachments": client.get_item_attachments,
        "relations": client.get_item_relations,
    }
    responses: dict[str, Any] = {}
    failures: list[str] = []
    for name, call in calls.items():
        try:
            responses[name] = call(item_id)
        except Exception as exc:
            responses[name] = None
            failures.append(f"  {name}: {failure_text(exc)}")
    report = Path(tempfile.gettempdir()) / REPORT_NAME
    report.write_text(json.dumps(responses, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = summarize_contract(
        responses["history"], responses["comments"], responses["attachments"], responses["relations"]
    )
    if failures:
        lines += ["[조회 실패]", *failures]
    lines.append(f"전체 응답: %TEMP%\\{REPORT_NAME} (이 PC에서만 보고 밖으로 보내지 않습니다)")
    print("\n".join(lines[:MAX_LINES]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: todo.md 작성**

저장소 루트 `todo.md`:

````markdown
# 사용자가 직접 돌릴 것

Claude가 돌릴 수 없는 환경(실서버)에서 확인할 것을 적는다. 결과를 붙여 주면 해당 절은 지운다.

## 1. 변경 이력·댓글·첨부·관계 API 응답 구조 확인

왜: 변경 이력 탭은 이력·댓글·첨부 API를 따로 받아 합친다. 실서버의 이력 응답에 댓글·첨부 같은 다른 사건이 함께
들어오는지, 첨부 목록에 올린 사람과 올린 시각이 있는지 확인해 다음 작업에 반영한다.

돌리는 법: 저장소 안 어느 폴더에서든 PowerShell로 아래 두 줄을 붙여 넣는다. 서버 주소, 사용자, 비밀번호, 아이템 ID를
묻는다. 비밀번호는 화면에 보이지 않고 어디에도 저장하지 않는다. 변경 이력·댓글·첨부가 모두 있는 아이템을 고른다.

```powershell
$root = git rev-parse --show-toplevel
& "$root\.venv\Scripts\python.exe" "$root\scripts\inspect_item_activity_contract.py"
```

확인할 것:

- 입력이 끝나면 화면이 지워지고 결과만 한 화면에 나온다.
- 결과에 서버 주소, 사람 이름, 필드 이름, 본문, 파일명이 없다. 있으면 캡처하지 말고 그 사실만 알려 준다.

돌려줄 것: 결과 화면 캡처 한 장. `%TEMP%\cb_item_activity_contract.json`은 원문이 들어 있으므로 보내지 않는다.
````

- [ ] **Step 5: 통과 확인**

Run: `.venv\Scripts\python.exe -m unittest tests.test_inspect_item_activity_contract -v`
Expected: PASS. 이어서 `.venv\Scripts\python.exe -m ruff check .`, mypy(이 스크립트는 `src` 밖이라 대상이 아니다), 전체 테스트 통과.

- [ ] **Step 6: 커밋**

```bash
git add scripts/inspect_item_activity_contract.py tests/test_inspect_item_activity_contract.py todo.md
git commit -m "chore: 변경 이력 관련 API 응답 구조 확인 스크립트와 todo.md 1절 추가" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: 실제 창 확인과 마무리

**Files:** 없음(결함이 나오면 해당 Task 파일)

- [ ] **Step 1: 전체 검증**

```bash
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Expected: 셋 다 오류 없음.

- [ ] **Step 2: 실제 창으로 확인**

`run-gui` 스킬로 앱을 테스트 모드로 띄워 아래를 차례로 누르고 화면을 캡처한다. GUI 테스트는 창 클래스를 patch하므로 생성자 인자 결함은 여기서만 드러난다. 일반 창 크기와 전체 화면, `kefico`·`igloo` 테마 양쪽에서 본다.

1. 트래커 작업공간 > Baseline 비교 > 기준 `현재 상태`, 비교 `Offline Requirements Baseline` > 전체 비교 실행.
2. 결과에서 9001001을 고르고 `변경 이력` 탭을 연다. 상태줄이 `비교 시점 사이 · 버전 2건 · 필드 변경 3건 · 바뀐 필드 3개 · 댓글 2건 · 첨부 1건`인지, 요약 표와 트리가 함께 늘어나는지 본다.
3. `기준 Baseline`을 `전체`로 바꾸면 첨부가 2건이 되는지, `댓글` 체크를 끄면 트리에서 댓글이 빠지는지 본다.
4. `이력 Excel 내보내기`로 스크래치 폴더에 저장하고, 파일을 openpyxl로 열어 시트 이름과 `이력` 행 수를 확인한다.
5. 기본 계층 탭에서 9001001 상세 창을 열어 `변경 이력` 탭을 보고, `조회 기준`을 Baseline으로 바꿔 Baseline 상세 창을 열어 `Offline Requirements Baseline 이후`로 시작하는지와 안내 문구를 본다.
6. 좁은 창 폭에서 도구줄 때문에 창 최소 폭이 커지지 않는지 본다. 커지면 도구줄을 두 줄로 나누는 수정을 Task 4에 더한다.

- [ ] **Step 3: 브랜치 전체 리뷰**

`superpowers:requesting-code-review`로 `main` 대비 전체 변경을 리뷰받고, 받은 지적은 `superpowers:receiving-code-review`로 검토해 고친다.

- [ ] **Step 4: 작업 이력 기록과 보고**

AGENTS.md의 Notion 동기화 규칙에 따라 개발 작업 이력에 `로컬 전용`으로 기록한다. Notion 도구를 쓸 수 없으면 보고에 "작업 이력 등록 보류"를 적는다. push와 PR은 사용자가 요청할 때 한다. 보고에는 todo.md 1절을 돌려 달라는 안내를 넣는다.

