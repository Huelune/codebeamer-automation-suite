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
