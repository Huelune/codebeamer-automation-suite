from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


def _optional_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _person_name(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("displayName") or value.get("name") or value.get("email") or value.get("id"))
    return _text(value)


@dataclass(frozen=True)
class ItemRelationSummary:
    group: str
    direction: str
    relation_type: str = ""
    relation_id: str = ""
    item_id: int | None = None
    common_item_id: str = ""
    display_name: str = ""
    version: int | None = None
    external_url: str = ""

    @classmethod
    def from_raw(cls, group: str, raw: dict[str, Any]) -> ItemRelationSummary:
        revision = raw.get("itemRevision")
        if not isinstance(revision, dict):
            revision = raw.get("item") if isinstance(raw.get("item"), dict) else {}
        item_id = _optional_int(revision.get("id") or raw.get("itemId") or raw.get("targetItemId"))
        common_item_id = _text(revision.get("commonItemId") or raw.get("commonItemId") or raw.get("targetCommonItemId"))
        display_name = _text(revision.get("name") or revision.get("summary") or raw.get("name") or raw.get("summary"))
        if not display_name:
            display_name = f"#{item_id}" if item_id is not None else common_item_id or "이름 없음"
        return cls(
            group=group,
            direction="downstream" if group in {"downstreamReferences", "outgoingAssociations"} else "upstream",
            relation_type=_text(raw.get("type") or raw.get("relationType")),
            relation_id=_text(raw.get("id")),
            item_id=item_id,
            common_item_id=common_item_id,
            display_name=display_name,
            version=_optional_int(revision.get("version") or raw.get("version")),
            external_url=_text(raw.get("url") or raw.get("uri") or raw.get("externalUrl")),
        )


@dataclass(frozen=True)
class ItemRelationsSnapshot:
    downstream_references: tuple[ItemRelationSummary, ...] = field(default_factory=tuple)
    upstream_references: tuple[ItemRelationSummary, ...] = field(default_factory=tuple)
    incoming_associations: tuple[ItemRelationSummary, ...] = field(default_factory=tuple)
    outgoing_associations: tuple[ItemRelationSummary, ...] = field(default_factory=tuple)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ItemRelationsSnapshot:
        def values(key: str) -> tuple[ItemRelationSummary, ...]:
            candidates = raw.get(key)
            if not isinstance(candidates, list):
                return ()
            return tuple(ItemRelationSummary.from_raw(key, value) for value in candidates if isinstance(value, dict))

        return cls(
            downstream_references=values("downstreamReferences"),
            upstream_references=values("upstreamReferences"),
            incoming_associations=values("incomingAssociations"),
            outgoing_associations=values("outgoingAssociations"),
        )

    def grouped(self) -> tuple[tuple[str, tuple[ItemRelationSummary, ...]], ...]:
        return (
            ("하위 참조", self.downstream_references),
            ("상위 참조", self.upstream_references),
            ("들어오는 연관", self.incoming_associations),
            ("나가는 연관", self.outgoing_associations),
        )


@dataclass(frozen=True)
class ItemHistoryEntry:
    version: int | None
    modified_at: str = ""
    modified_by: str = ""
    change_summary: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ItemHistoryEntry:
        revision = raw.get("itemRevision")
        if not isinstance(revision, dict):
            revision = raw
        summary_value = raw.get("changeSummary") or raw.get("summary") or raw.get("change") or raw.get("comment")
        if isinstance(summary_value, (list, dict)):
            summary_value = ""
        return cls(
            version=_optional_int(revision.get("version") or raw.get("version")),
            modified_at=_text(raw.get("modifiedAt") or revision.get("modifiedAt")),
            modified_by=_person_name(raw.get("modifiedBy") or revision.get("modifiedBy")),
            change_summary=_text(summary_value),
        )


@dataclass(frozen=True)
class ItemHistorySnapshot:
    entries: tuple[ItemHistoryEntry, ...] = field(default_factory=tuple)
    current_version: int | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | list[Any], *, current_version: int | None = None) -> ItemHistorySnapshot:
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, dict):
            candidates = next((raw.get(key) for key in ("versions", "history", "items", "content") if isinstance(raw.get(key), list)), [])
        else:
            candidates = []
        entries = [ItemHistoryEntry.from_raw(value) for value in candidates if isinstance(value, dict)]
        deduplicated: list[ItemHistoryEntry] = []
        seen: set[tuple[int | None, str]] = set()
        for entry in entries:
            identity = entry.version, entry.modified_at
            if identity in seen:
                continue
            seen.add(identity)
            deduplicated.append(entry)
        entries = deduplicated
        entries.sort(key=lambda entry: (entry.version is not None, entry.version if entry.version is not None else -1, entry.modified_at), reverse=True)
        return cls(tuple(entries), current_version=current_version)


__all__ = ["ItemHistoryEntry", "ItemHistorySnapshot", "ItemRelationSummary", "ItemRelationsSnapshot"]
