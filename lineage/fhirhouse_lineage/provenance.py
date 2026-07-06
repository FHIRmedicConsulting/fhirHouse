"""FHIR Provenance emission for fhirHouse governance transforms.

Mirrors upstream's writeMergeProvenance (packages/server/src/repository/promote.ts):
a Bronze-shaped row per decision, search-indexed on `target`, ingested via the
sidecar. Activity codes follow ADR-0012 §8's v3-DataOperation usage.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fhirhouse_contracts import PathCatalog, SidecarClient

V3_DATA_OPERATION = "http://terminology.hl7.org/CodeSystem/v3-DataOperation"


def _uuid7ish() -> str:
    # Upstream mints uuid v7 for ordering; stdlib has no v7 — v4 is acceptable here
    # (Provenance ids only need uniqueness; ordering comes from `recorded`).
    return str(uuid.uuid4())


def build_provenance(
    activity: str,
    targets: list[str],
    agent_display: str,
    reason: str,
    recorded: str | None = None,
) -> dict:
    """A Provenance resource body. `targets` are reference strings (e.g. "Patient/x")."""
    return {
        "resourceType": "Provenance",
        "id": _uuid7ish(),
        "target": [{"reference": t} for t in targets],
        "recorded": recorded or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "activity": {"coding": [{"system": V3_DATA_OPERATION, "code": activity}]},
        "agent": [{"who": {"display": agent_display}}],
        "reason": [{"text": reason}],
    }


def write_provenance(prov: dict, sidecar: SidecarClient | None = None,
                     catalog: PathCatalog | None = None, ingest_source: str = "fhirhouse") -> dict:
    """Land a Provenance body in Bronze (sidecar write, Bronze row shape) so fhirEngine
    promotes and serves it like any resource."""
    sidecar = sidecar or SidecarClient()
    catalog = catalog or PathCatalog()
    now = prov.get("recorded") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    import json

    row = {
        "id": prov["id"],
        "version_id": 1,
        "last_updated": now,
        "body_json": json.dumps(prov),
        "identifier_index": [],
        "search_param_index": [
            {"code": "target", "system": "", "value": t["reference"]} for t in prov.get("target", [])
        ],
        "ext_json": "{}",
        "deleted": False,
        "is_current": True,
        "_ingested_at": now,
        "_ingest_source": ingest_source,
    }
    return sidecar.write_bronze_resource(catalog.table_path("bronze", "Provenance"), row)
