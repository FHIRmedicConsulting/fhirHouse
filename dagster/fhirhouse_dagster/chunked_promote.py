"""Chunked external promoter — Bronze→Silver+Gold for tables the reference CLI can't.

fhirEngine's `fhirengine-promote` is the full-rebuild correctness backstop; it moves
each table through ONE sidecar request/response, which caps out at V8's ~512 MB
string limit (~150k medium resources — see docs/research/2026-07-06-bulk-1k-patient-
test-run.md). ADR-0026 explicitly plans for external promoters; this is fhirHouse's:

  - Bronze is read READ-SIDE (local delta-rs record batches — no giant HTTP body);
  - Gold is MERGE-upserted through the sidecar in bounded chunks (idempotent,
    fixed Bronze row schema — same serving shape the reference promoter writes);
  - Silver is flattened in Python against upstream's own generated R4 schemas
    (packages/server/src/fhir-schema/r4-core-schemas.json — the ADR-0024 clean-room
    flattener's source of truth, pinned by contracts/) and appended in chunks.

Silver encoding difference vs upstream (deliberate): scalar elements land as native
typed columns; struct/list-valued elements land as JSON text columns. Upstream's
inferred nested-struct Silver is currently unreadable by DuckDB's delta reader
(`void` columns) and unwritable past the V8 cap; JSON-text complex columns give a
deterministic chunk-stable schema that DuckDB reads today. Revisit when upstream
ships explicit Silver schemas.

MPI note: Patient stays the reference promoter's job (deterministic MPI runs there).
This promoter applies the SAME merged→survivor reference rewrite for downstream
types, loaded from gold.patient_merge_history.

Usage:
  python -m fhirhouse_dagster.chunked_promote Observation ExplanationOfBenefit \
      [--base <delta>] [--chunk 20000] [--silver-only]
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fhirhouse_contracts import PathCatalog, SidecarClient
from fhirhouse_contracts.schema import R4_SCHEMAS_JSON

ANCHOR_ID = "__fhirhouse_schema_anchor__"

_SCHEMAS: dict | None = None


def _schemas() -> dict:
    global _SCHEMAS
    if _SCHEMAS is None:
        _SCHEMAS = json.loads(R4_SCHEMAS_JSON.read_text())["schemas"]
    return _SCHEMAS


# ── flattening (port of clean-room-flattener.ts flattenResource) ────────────────

def _flatten_scalar(v, coltype: dict):
    kind = coltype["kind"]
    if kind == "scalar":
        return v
    if kind == "json":
        return json.dumps(v, separators=(",", ":"))
    out = {}
    for f in coltype["fields"]:
        out[f["name"]] = _flatten_value(v.get(f["name"]) if isinstance(v, dict) else None, f)
    return out


def _flatten_value(val, col: dict):
    if val is None:
        return None
    if col.get("list"):
        return [_flatten_scalar(v, col["type"]) for v in val]
    return _flatten_scalar(val, col["type"])


_ARROW_PY = {"bool": bool, "int32": int, "float64": float}


def flatten_resource(resource: dict, cols: list[dict]) -> dict:
    """One Silver row fragment: native scalars; struct/list values as JSON text
    (chunk-stable schema; see module docstring). Every column key always present."""
    row: dict = {}
    for c in cols:
        v = _flatten_value(resource.get(c["name"]), c)
        if v is None:
            row[c["name"]] = None
        elif not c.get("list") and c["type"]["kind"] == "scalar":
            py = _ARROW_PY.get(c["type"]["arrow"], str)
            row[c["name"]] = py(v) if not isinstance(v, py) else v
        elif not c.get("list") and c["type"]["kind"] == "json":
            row[c["name"]] = v  # already JSON text
        else:
            row[c["name"]] = json.dumps(v, separators=(",", ":"))
    return row


def _anchor_row(cols: list[dict], base: dict) -> dict:
    """Synthetic first-chunk row with every column non-null so table creation pins
    real types (an all-null column would freeze as Arrow Null). Deleted post-run."""
    row = dict(base)
    for c in cols:
        if not c.get("list") and c["type"]["kind"] == "scalar":
            row[c["name"]] = {"bool": True, "int32": 0, "float64": 0.0}.get(c["type"]["arrow"], "")
        else:
            row[c["name"]] = "{}"
    return row


# ── survivor-map reference rewrite (mirrors upstream loadSurvivorMap/rewrite) ───

def load_survivor_map(catalog: PathCatalog) -> dict[str, str]:
    from deltalake import DeltaTable

    try:
        rows = DeltaTable(catalog.mpi_path("patient_merge_history")).to_pyarrow_table(
            columns=["surviving_fhir_id", "merged_fhir_id", "unmerged_at"]).to_pylist()
    except Exception:
        return {}
    direct = {r["merged_fhir_id"]: r["surviving_fhir_id"] for r in rows if not r.get("unmerged_at")}
    terminal = {}
    for start in direct:
        cur, seen = start, {start}
        while cur in direct and direct[cur] not in seen:
            cur = direct[cur]
            seen.add(cur)
        terminal[start] = cur
    return terminal


def _rewrite_refs(node, survivor: dict[str, str]) -> None:
    if isinstance(node, list):
        for v in node:
            _rewrite_refs(v, survivor)
    elif isinstance(node, dict):
        ref = node.get("reference")
        if isinstance(ref, str) and "Patient/" in ref:
            i = ref.rfind("Patient/")
            tail = ref[i + 8:]
            pid = tail.split("/", 1)[0]
            if pid in survivor:
                node["reference"] = f"{ref[:i]}Patient/{survivor[pid]}{tail[len(pid):]}"
        for v in node.values():
            _rewrite_refs(v, survivor)


# ── the promoter ────────────────────────────────────────────────────────────────

BRONZE_COLS = ["id", "version_id", "last_updated", "body_json", "identifier_index",
               "search_param_index", "ext_json", "deleted", "is_current",
               "_ingested_at", "_ingest_source"]


def promote_type(
    resource_type: str,
    base: str | None = None,
    sidecar: SidecarClient | None = None,
    chunk: int = 20_000,
    do_gold: bool = True,
    do_silver: bool = True,
) -> dict:
    from deltalake import DeltaTable

    catalog = PathCatalog(base)
    sidecar = sidecar or SidecarClient()
    cols = _schemas().get(resource_type)
    if cols is None:
        raise ValueError(f"unknown resource type {resource_type!r}")
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    dt = DeltaTable(catalog.table_path("bronze", resource_type))

    # pass 1 — current version per id (cheap: two columns only)
    idv = dt.to_pyarrow_table(columns=["id", "version_id"]).to_pylist()
    current: dict[str, int] = {}
    for r in idv:
        if current.get(r["id"], -1) < (r["version_id"] or 0):
            current[r["id"]] = r["version_id"] or 0

    survivor = load_survivor_map(catalog) if resource_type != "Patient" else {}
    gold_path = catalog.table_path("gold", resource_type)
    silver_path = catalog.table_path("silver", resource_type)
    silver_meta = {"silver_status": "pass", "governed_at": now}

    emitted: set[str] = set()
    silver_first = do_silver
    stats = {"resourceType": resource_type, "currentIds": len(current), "gold": 0, "silver": 0, "chunks": 0}

    for batch in dt.to_pyarrow_dataset().to_batches(columns=BRONZE_COLS, batch_size=chunk):
        rows = [r for r in batch.to_pylist()
                if (r["version_id"] or 0) == current.get(r["id"]) and r["id"] not in emitted]
        emitted.update(r["id"] for r in rows)
        if not rows:
            continue
        if survivor:
            for r in rows:
                body = json.loads(r["body_json"])
                _rewrite_refs(body, survivor)
                r["body_json"] = json.dumps(body, separators=(",", ":"))

        if do_gold:
            gold_rows = [{**r, "is_current": True} for r in rows]
            sidecar.merge(gold_path, gold_rows, key="id", schema="bronze")
            stats["gold"] += len(gold_rows)

        if do_silver:
            silver_rows = []
            for r in rows:
                if r["deleted"]:
                    continue
                body = json.loads(r["body_json"])
                silver_rows.append({
                    "silver_id": r["id"], "fhir_id": r["id"],
                    "version_id": int(r["version_id"] or 0),
                    **silver_meta, "deleted": False, "body_json": r["body_json"],
                    **flatten_resource(body, cols),
                })
            if silver_rows:
                if silver_first:
                    anchor = _anchor_row(cols, {
                        "silver_id": ANCHOR_ID, "fhir_id": ANCHOR_ID, "version_id": 0,
                        **silver_meta, "deleted": False, "body_json": "{}"})
                    sidecar.write(silver_path, [anchor] + silver_rows, mode="overwrite")
                    silver_first = False
                else:
                    sidecar.write(silver_path, silver_rows, mode="append")
                stats["silver"] += len(silver_rows)
        stats["chunks"] += 1

    if do_silver and not silver_first:
        sidecar.delete(silver_path, predicate=f"silver_id = '{ANCHOR_ID}'")
    return stats


def main() -> int:
    import argparse
    import time

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("types", nargs="+")
    ap.add_argument("--base", default=None)
    ap.add_argument("--chunk", type=int, default=20_000)
    ap.add_argument("--silver-only", action="store_true")
    args = ap.parse_args()
    for t in args.types:
        t0 = time.time()
        s = promote_type(t, base=args.base, chunk=args.chunk, do_gold=not args.silver_only)
        print(f"{t}: currentIds={s['currentIds']:,} gold={s['gold']:,} "
              f"silver={s['silver']:,} chunks={s['chunks']} in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
