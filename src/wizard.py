from __future__ import annotations

from .codebeamer_client import CodebeamerClient
from .excel_reader import ExcelReader
from .hierarchy_processor import HierarchyProcessor
from .mapping_service import MappingService
from .models import WizardState
from .wizard_data import WizardDataPreparationMixin
from .wizard_item_builder import WizardItemBuilderService
from .wizard_operations import WizardOperationMixin
from .wizard_option_resolution import WizardOptionResolutionService
from .wizard_payload import WizardPayloadMixin
from .wizard_payload_cache import WizardPayloadCacheService
from .wizard_tracker_lookup import WizardTrackerItemLookupMixin
from .wizard_update_payload import WizardUpdatePayloadService
from .wizard_user_lookup import WizardUserLookupMixin


class CodebeamerUploadWizard(
    WizardDataPreparationMixin,
    WizardUserLookupMixin,
    WizardTrackerItemLookupMixin,
    WizardPayloadMixin,
    WizardOperationMixin,
):
    """업로드 전처리, lookup, payload 생성, 실행을 조합하는 최상위 서비스다."""

    def __init__(
        self,
        client: CodebeamerClient,
        processor: HierarchyProcessor | None,
        mapper: MappingService,
        reader: ExcelReader | None = None,
        logger=None,
    ):
        """의존 서비스를 주입받아 업로드 워크플로를 초기화한다."""
        self.client = client
        self.reader = reader
        self.processor = processor
        self.mapper = mapper
        self.logger = logger
        self.state = WizardState()
        self.item_builder = WizardItemBuilderService(
            state=self.state,
            mapper=self.mapper,
            resolve_tracker_item_reference_value=self._resolve_tracker_item_reference_value,
            resolve_user_reference_value=self._resolve_user_reference_value,
            resolve_member_reference_value=self._resolve_member_reference_value,
        )
        self.option_resolution = WizardOptionResolutionService(
            state=self.state,
            mapper=self.mapper,
            update_item_id_column_name=self._update_item_id_column_name,
            parse_update_item_id=self._parse_update_item_id,
            has_configured_value=self.item_builder._has_configured_value,
            invalidate_payload_cache=self._invalidate_payload_cache,
            decorate_tracker_item_option_maps=self._decorate_tracker_item_option_maps,
            resolve_user_reference_fields=self._resolve_user_reference_fields,
            resolve_tracker_item_reference_fields=self._resolve_tracker_item_reference_fields,
            resolve_member_reference_fields=self._resolve_member_reference_fields,
            resolve_default_field_values=self.item_builder._resolve_default_field_values,
        )
        self.update_payloads = WizardUpdatePayloadService(
            state=self.state,
            client=self.client,
            build_row_item=self.item_builder._build_row_item,
            serialize_payload_value=self.item_builder._serialize_payload_value,
            raise_payload_error=self.item_builder._raise_payload_error,
        )
        self.payload_cache = WizardPayloadCacheService(
            state=self.state,
            payload_source_df=self._payload_source_df,
            update_item_id_column_name=self._update_item_id_column_name,
            parse_update_item_id=self._parse_update_item_id,
            raise_payload_error=self._raise_payload_error,
            build_update_row_payload=self._build_update_row_payload,
            build_row_payload=self._build_row_payload,
            resolve_update_target_item_id=self._resolve_update_target_item_id,
            apply_upsert_hierarchy_validation=self._apply_upsert_hierarchy_validation,
        )


__all__ = ["CodebeamerUploadWizard"]
