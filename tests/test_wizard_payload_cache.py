from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.wizard_payload_cache import WizardPayloadCacheService


class WizardPayloadCacheServiceTest(unittest.TestCase):
    def test_build_payloads_reuses_cached_dataframe(self) -> None:
        state = SimpleNamespace(
            schema_df=pd.DataFrame([{"field_name": "Summary"}]),
            payload_df=None,
            upload_mode="create",
        )
        build_row_payload = Mock(return_value={"name": "Requirement"})
        service = WizardPayloadCacheService(
            state=state,
            payload_source_df=lambda: pd.DataFrame(
                [
                    {
                        "_row_id": 1,
                        "parent_row_id": None,
                        "upload_name": "Requirement",
                    }
                ]
            ),
            update_item_id_column_name=Mock(),
            parse_update_item_id=Mock(),
            raise_payload_error=Mock(),
            build_update_row_payload=Mock(),
            build_row_payload=build_row_payload,
            resolve_update_target_item_id=Mock(),
            apply_upsert_hierarchy_validation=Mock(),
        )

        first = service.build_payloads()
        second = service.build_payloads()

        self.assertIs(first, second)
        build_row_payload.assert_called_once()


if __name__ == "__main__":
    unittest.main()
