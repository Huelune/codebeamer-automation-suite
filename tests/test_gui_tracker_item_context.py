from __future__ import annotations

import unittest
from dataclasses import dataclass

from src.gui.tracker_item_context_models import ItemHistorySnapshot
from src.gui.tracker_item_context_models import ItemRelationsSnapshot
from src.gui.tracker_item_context_service import TrackerItemContextService
from src.gui.tracker_item_detail_session import TrackerItemDetailSession


@dataclass
class Settings:
    offline_mode: bool = False
    base_url: str = "https://example.test/cb"
    username: str = "sample"
    password: str = "placeholder"
    offline_query_data_path: str = ""
    rate_limit_retry_delay_seconds: float = 0.0
    rate_limit_max_retries: int = 0


class Client:
    relation_calls = 0
    history_calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def get_item_relations(self, item_id: int):
        self.__class__.relation_calls += 1
        return {
            "downstreamReferences": [
                {
                    "id": "ref-1",
                    "type": "TrackerItemReference",
                    "itemRevision": {
                        "id": "1206",
                        "commonItemId": "stable-1206",
                        "name": "Related item",
                        "version": 8,
                    },
                }
            ],
            "upstreamReferences": [],
            "incomingAssociations": [],
            "outgoingAssociations": [],
        }

    def get_item_history(self, item_id: int):
        self.__class__.history_calls += 1
        return {
            "versions": [
                {
                    "itemRevision": {"id": item_id, "version": 2},
                    "modifiedAt": "2026-01-02T00:00:00Z",
                    "modifiedBy": {"displayName": "Sample User"},
                },
                {
                    "itemRevision": {"id": item_id, "version": 2},
                    "modifiedAt": "2026-01-02T00:00:00Z",
                    "modifiedBy": {"displayName": "Duplicate"},
                },
                {
                    "itemRevision": {"id": item_id, "version": 3},
                    "modifiedAt": "2026-01-03T00:00:00Z",
                    "modifiedBy": {"name": "sample"},
                    "changeSummary": "Status updated",
                },
            ]
        }


class TrackerItemContextModelsTest(unittest.TestCase):
    def test_relations_preserve_groups_and_normalize_string_ids(self) -> None:
        snapshot = ItemRelationsSnapshot.from_raw(Client().get_item_relations(1205))

        relation = snapshot.downstream_references[0]
        self.assertEqual(relation.item_id, 1206)
        self.assertEqual(relation.common_item_id, "stable-1206")
        self.assertEqual(relation.relation_id, "ref-1")
        self.assertEqual(relation.direction, "downstream")

    def test_history_sorts_latest_version_first(self) -> None:
        snapshot = ItemHistorySnapshot.from_raw(Client().get_item_history(1205), current_version=3)

        self.assertEqual([entry.version for entry in snapshot.entries], [3, 2])
        self.assertEqual(snapshot.entries[0].modified_by, "sample")
        self.assertEqual(snapshot.current_version, 3)


class TrackerItemContextServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        Client.relation_calls = 0
        Client.history_calls = 0
        self.service = TrackerItemContextService(client_factory=Client)
        self.settings = Settings()

    def test_cache_uses_item_version_and_avoids_n_plus_one_calls(self) -> None:
        first = self.service.load_relations(self.settings, 1205, 3)
        second = self.service.load_relations(self.settings, 1205, 3)

        self.assertIs(first, second)
        self.assertEqual(Client.relation_calls, 1)
        self.assertEqual(first.downstream_references[0].display_name, "Related item")

        self.service.load_relations(self.settings, 1205, 4)
        self.assertEqual(Client.relation_calls, 2)

    def test_force_and_item_cache_invalidation(self) -> None:
        self.service.load_history(self.settings, 1205, 3)
        self.service.load_history(self.settings, 1205, 3, force=True)
        self.service.clear_item_cache(self.settings, 1205)
        self.service.load_history(self.settings, 1205, 3)

        self.assertEqual(Client.history_calls, 3)

    def test_baseline_context_is_rejected_before_client_call(self) -> None:
        with self.assertRaisesRegex(ValueError, "Baseline"):
            self.service.load_relations(self.settings, 1205, 3, baseline_id=7)
        with self.assertRaisesRegex(ValueError, "Baseline"):
            self.service.load_history(self.settings, 1205, 3, baseline_id=7)

        self.assertEqual(Client.relation_calls, 0)
        self.assertEqual(Client.history_calls, 0)


class TrackerItemDetailSessionTest(unittest.TestCase):
    def test_peek_does_not_change_current_location_or_generation(self) -> None:
        session = TrackerItemDetailSession(1)
        session.navigate(2)
        generation = session.generation

        self.assertEqual(session.peek_back().item_id, 1)
        self.assertIsNone(session.peek_forward())
        self.assertEqual(session.current.item_id, 2)
        self.assertEqual(session.generation, generation)

    def test_back_forward_and_branching_history(self) -> None:
        session = TrackerItemDetailSession(1)
        session.navigate(2)
        session.navigate(3)
        self.assertEqual(session.back().item_id, 2)
        self.assertTrue(session.can_go_forward)
        session.navigate(4)

        self.assertEqual(session.current.item_id, 4)
        self.assertFalse(session.can_go_forward)
        self.assertEqual(session.back().item_id, 2)

    def test_history_is_capped_at_fifty_entries(self) -> None:
        session = TrackerItemDetailSession(1)
        for item_id in range(2, 60):
            session.navigate(item_id)
        traversed = 1
        while session.back() is not None:
            traversed += 1
        self.assertEqual(traversed, 50)


if __name__ == "__main__":
    unittest.main()
