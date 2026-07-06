"""Execute compiled views: in-memory over resource lists (conformance/tests) or over
fhirEngine's Delta tiers (production reads — read-side DuckDB per FH-0003).
"""
from __future__ import annotations

import json

from .compiler import MACROS, ViewCompiler


def connect(con=None):
    """A DuckDB connection with the SoF macros installed."""
    import duckdb

    con = con or duckdb.connect()
    for m in MACROS:
        con.execute(m)
    return con


def _parse_cell(cell):
    # fidelity mode returns JSON text per column; parse back to typed values
    return None if cell is None else json.loads(cell)


def run_view(view: dict, resources: list[dict], con=None) -> tuple[list[str], list[dict]]:
    """Run a ViewDefinition over in-memory resources. Returns (column_names, rows)."""
    con = connect(con)
    rtype = view.get("resource")
    matching = [r for r in resources if r.get("resourceType") == rtype]
    con.execute("CREATE OR REPLACE TEMP TABLE __sof_resources(body VARCHAR)")
    if matching:
        con.executemany("INSERT INTO __sof_resources VALUES (?)",
                        [(json.dumps(r),) for r in matching])
    source_sql = ("SELECT CAST(body AS JSON) AS resource, "
                  "json_extract_string(CAST(body AS JSON), '$.id') AS resource_key "
                  "FROM __sof_resources")
    compiled = ViewCompiler(view).compile(source_sql)
    cur = con.execute(compiled.sql)
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, (_parse_cell(c) for c in rec))) for rec in cur.fetchall()]
    return names, rows


def delta_source_sql(base: str, resource_type: str, tier: str = "silver") -> str:
    """Source subquery over a fhirEngine tier table (PathCatalog binding; Silver keeps
    body_json + fhir_id and `deleted` per upstream promote.ts)."""
    key = "fhir_id" if tier == "silver" else "id"
    path = f"{base.rstrip('/')}/{tier}/{resource_type.lower()}"
    return (f"SELECT CAST(body_json AS JSON) AS resource, {key} AS resource_key "
            f"FROM delta_scan('{path}') WHERE NOT coalesce(deleted, FALSE)")


def run_view_delta(view: dict, base: str, tier: str = "silver", con=None,
                   typed: bool = True) -> tuple[list[str], list]:
    """Run a ViewDefinition over a Delta tier. Typed mode: native SQL types for BI.
    Materialization to Gold stays with delta-rs — hand these rows to the sidecar."""
    con = connect(con)
    con.execute("INSTALL delta; LOAD delta;")
    compiled = ViewCompiler(view, typed=typed).compile(
        delta_source_sql(base, view["resource"], tier))
    cur = con.execute(compiled.sql)
    return [d[0] for d in cur.description], cur.fetchall()
