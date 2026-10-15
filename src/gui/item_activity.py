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
