"""Read-side helpers over fhirEngine's tier tables (FH-0003: reads are delta-rs/DuckDB;
writes are the sidecar's alone). Shared by dq/ and mdm/.
"""
from __future__ import annotations

import json

from .catalog import PathCatalog


def read_current_resources(catalog: PathCatalog, tier: str, resource_type: str) -> list[dict]:
    """Current (non-deleted) resource bodies from a tier table via read-only delta-rs.
    Append-only tiers hold history: max version_id per id wins."""
    from deltalake import DeltaTable  # read-only; the writer lives in fhirEngine

    dt = DeltaTable(catalog.table_path(tier, resource_type))
    rows = dt.to_pyarrow_table(columns=["id", "version_id", "body_json", "deleted"]).to_pylist()
    current: dict[str, dict] = {}
    for r in rows:
        prev = current.get(r["id"])
        if prev is None or (r["version_id"] or 0) > (prev["version_id"] or 0):
            current[r["id"]] = r
    return [json.loads(r["body_json"]) for r in current.values() if not r["deleted"] and r["body_json"]]
