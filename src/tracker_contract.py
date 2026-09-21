from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .mapping_service import MappingService
from .models import TrackerItemBase


@dataclass
class TrackerContractBundle:
    project_id: int
    tracker_id: int
    schema: dict[str, Any] | list[dict[str, Any]]
    schema_df: pd.DataFrame
    contract: dict[str, Any]


def _is_missing_scalar(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_ready(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _json_ready(value.item())
        except Exception:
            pass
    if _is_missing_scalar(value):
        return None
    return value


def _dataframe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record = {
            str(column): _json_ready(value)
            for column, value in row.to_dict().items()
        }
        records.append(record)
    return records


def _normalized_builtin_field(tracker_item_field: Any) -> str | None:
    if tracker_item_field is None:
        return None
    text = str(tracker_item_field).strip()
    if not text:
        return None
    return TrackerItemBase._normalize_tracker_field_name(text)


def _field_summary(schema_df: pd.DataFrame) -> dict[str, Any]:
    builtin_fields: list[dict[str, Any]] = []
    custom_fields: list[dict[str, Any]] = []
    multiple_value_fields: list[str] = []
    lookup_required_fields: list[str] = []
    unsupported_fields: list[dict[str, Any]] = []
    option_like_fields: list[str] = []

    for _, row in schema_df.iterrows():
        field_name = str(row.get("field_name") or "").strip()
        if not field_name:
            continue

        tracker_item_field = row.get("tracker_item_field")
        normalized_tracker_item_field = _normalized_builtin_field(tracker_item_field)
        field_info = {
            "field_name": field_name,
            "field_id": _json_ready(row.get("field_id")),
            "field_type": _json_ready(row.get("field_type")),
            "tracker_item_field": _json_ready(tracker_item_field),
            "normalized_tracker_item_field": normalized_tracker_item_field,
            "resolved_field_kind": _json_ready(row.get("resolved_field_kind")),
            "payload_target_kind": _json_ready(row.get("payload_target_kind")),
            "multiple_values": bool(row.get("multiple_values", False)),
            "requires_lookup": bool(row.get("requires_lookup", False)),
        }

        if TrackerItemBase.has_builtin_field(tracker_item_field):
            builtin_fields.append(field_info)
        else:
            custom_fields.append(field_info)

        if bool(row.get("multiple_values", False)):
            multiple_value_fields.append(field_name)
        if bool(row.get("requires_lookup", False)):
            lookup_required_fields.append(field_name)
        if bool(row.get("is_option_like", False)):
            option_like_fields.append(field_name)
        if not bool(row.get("is_supported", True)):
            unsupported_fields.append({
                "field_name": field_name,
                "field_type": _json_ready(row.get("field_type")),
                "resolved_field_kind": _json_ready(row.get("resolved_field_kind")),
                "unsupported_reason": _json_ready(row.get("unsupported_reason")),
            })

    return {
        "builtin_fields": builtin_fields,
        "custom_fields": custom_fields,
        "multiple_value_fields": multiple_value_fields,
        "lookup_required_fields": lookup_required_fields,
        "option_like_fields": option_like_fields,
        "unsupported_fields": unsupported_fields,
    }


def build_tracker_contract_bundle(
    *,
    client: Any,
    mapper: MappingService,
    project_id: int,
    tracker_id: int,
) -> TrackerContractBundle:
    schema = client.get_tracker_schema(tracker_id)
    schema_df = mapper.flatten_schema_fields(schema)
    schema_records = _dataframe_records(schema_df)
    field_summary = _field_summary(schema_df)

    contract = {
        "contract_version": "2026-06-17",
        "project_id": int(project_id),
        "tracker_id": int(tracker_id),
        "schema_policy": {
            "fetch_at_runtime": True,
            "runtime_endpoint": f"/v3/trackers/{tracker_id}/schema",
            "snapshot_generated_during_discovery": True,
            "snapshot_required_for_offline_tests": True,
            "snapshot_required_for_contract_diff": True,
        },
        "runtime_endpoints": {
            "tracker_schema": "/v3/trackers/{trackerId}/schema",
            "user_by_name": "/v3/users/findByName",
            "user_by_id": "/v3/users/{userId}",
            "user_groups": "/v3/users/groups",
            "tracker_field_permissions": "/v3/trackers/{trackerId}/fields/{fieldId}/permissions",
            "create_item": "/v3/trackers/{trackerId}/items",
        },
        "field_summary": field_summary,
        "schema_snapshot": _json_ready(schema),
        "schema_flattened": schema_records,
    }

    return TrackerContractBundle(
        project_id=int(project_id),
        tracker_id=int(tracker_id),
        schema=schema,
        schema_df=schema_df,
        contract=contract,
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def scaffold_start_kit_templates(template_dir: str | Path, output_dir: str | Path) -> list[Path]:
    template_root = Path(template_dir)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for source in sorted(template_root.rglob("*")):
        relative_path = source.relative_to(template_root)
        target = output_root / relative_path

        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
            copied.append(target)

    return copied


def save_tracker_contract_bundle(
    bundle: TrackerContractBundle,
    output_dir: str | Path,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    tracker_schema_path = out / "tracker-schema.json"
    tracker_schema_flat_json_path = out / "tracker-schema-flat.json"
    tracker_schema_flat_csv_path = out / "tracker-schema-flat.csv"
    tracker_contract_path = out / "tracker-contract.json"

    _write_json(tracker_schema_path, bundle.schema)
    _write_json(tracker_schema_flat_json_path, _dataframe_records(bundle.schema_df))
    bundle.schema_df.to_csv(tracker_schema_flat_csv_path, index=False)
    _write_json(tracker_contract_path, bundle.contract)

    return {
        "tracker_schema": tracker_schema_path,
        "tracker_schema_flat_json": tracker_schema_flat_json_path,
        "tracker_schema_flat_csv": tracker_schema_flat_csv_path,
        "tracker_contract": tracker_contract_path,
    }
