"""Pinned-contract loader + live-schema extraction (shared by pin_schema.py and drift_test.py).

The pin (`contracts/gold_schema.snapshot.json`) captures everything fhirHouse relies on
from fhirEngine:
  - per-resource flattener schemas (ADR-0022/0024) — full nested shape as a sha256 per
    resource type (drift anywhere, including nested structs, changes the hash) plus the
    top-level column list kept readable for humans and for DQ required/binding checks;
  - the Bronze row schema (sidecar BRONZE_SCHEMA);
  - the Gold MPI table shapes as actually written by upstream's promote.ts, plus the
    fhirHouse-owned tables (pprl_tokens, mpi_decision_log, dq_score) pinned from
    ADR-0012 §2 / FH-0004.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any

CONTRACTS_DIR = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = CONTRACTS_DIR.parent
PIN_PATH = CONTRACTS_DIR / "gold_schema.snapshot.json"

R4_SCHEMAS_JSON = REPO_ROOT / "packages/server/src/fhir-schema/r4-core-schemas.json"
SIDECAR_PY = REPO_ROOT / "packages/server/sidecar/delta_sidecar.py"
PROMOTE_TS = REPO_ROOT / "packages/server/src/repository/promote.ts"

# fhirHouse-owned Gold table shapes (ADR-0012 §2 + FH-0004). These are OUR write
# contract — upstream doesn't implement them, so they are pinned but not drift-checked.
FHIRHOUSE_TABLES: dict[str, list[str]] = {
    "pprl_tokens": [
        "patient_fhir_id", "token_system", "token_value", "token_pipeline_version",
        "generated_at", "deleted",
    ],
    "mpi_decision_log": [
        "decision_id", "run_id", "left_fhir_id", "right_fhir_id", "match_probability",
        "match_weight", "band", "contributions_json", "model_version", "decided_at",
    ],
    "dq_score": [
        "run_id", "computed_at", "tier", "resource_type", "dimension", "metric",
        "numerator", "denominator", "score", "details_json", "dq_version",
    ],
}


def load_pin(path: pathlib.Path = PIN_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


def _hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def extract_flattener_schemas() -> dict[str, Any]:
    """Live per-resource flattener schema from upstream's generated r4-core-schemas.json."""
    doc = json.loads(R4_SCHEMAS_JSON.read_text())
    schemas = doc["schemas"]
    top_level = {
        rt: [
            {k: c[k] for k in ("name", "list", "fhirType", "required", "binding") if k in c}
            | {"kind": c["type"]["kind"]}
            | ({"arrow": c["type"]["arrow"]} if c["type"]["kind"] == "scalar" else {})
            for c in cols
        ]
        for rt, cols in schemas.items()
    }
    return {
        "fhir_version": doc["fhirVersion"],
        "source": doc["source"],
        "resource_types": doc["resourceTypes"],
        "schema_hashes": {rt: _hash(cols) for rt, cols in schemas.items()},
        "top_level_columns": top_level,
    }


def extract_bronze_schema() -> list[dict[str, str]]:
    """Bronze row schema out of the sidecar's BRONZE_SCHEMA literal. Deliberately
    source-parsing: when upstream reshapes Bronze this extraction (or the comparison)
    fails loudly, which is exactly the drift signal we want."""
    src = SIDECAR_PY.read_text()
    m = re.search(r"BRONZE_SCHEMA = pa\.schema\(\[(.*?)\]\)", src, re.DOTALL)
    if not m:
        raise RuntimeError(f"cannot locate BRONZE_SCHEMA in {SIDECAR_PY} — upstream layout changed; review the pin")
    fields = re.findall(r'\(\s*"(\w+)"\s*,\s*pa\.(\w+)', m.group(1))
    if len(fields) < 5:
        raise RuntimeError("BRONZE_SCHEMA extraction produced implausibly few fields; review the pin")
    return [{"name": n, "arrow": t} for n, t in fields]


def extract_mpi_tables() -> dict[str, list[str]]:
    """Column names of the Gold MPI tables as upstream's promote.ts actually writes them."""
    src = PROMOTE_TS.read_text()
    out: dict[str, list[str]] = {}
    for table, terminator in (
        ("patient_link", r'\}\s*;\s*\}\)\s*,\s*"overwrite"'),
        ("patient_merge_history", r'\}\)\)\s*,\s*"append"'),
        ("patient_match_review", r'\}\)\)\s*,\s*"append"'),
    ):
        m = re.search(r'writeMpi\(\s*"' + table + r'"(.*?)(?:' + terminator + r")", src, re.DOTALL)
        if not m:
            raise RuntimeError(f"cannot locate writeMpi(\"{table}\") in {PROMOTE_TS} — upstream changed; review the pin")
        # Strip string/template literals so `"deterministic_rule:shared-identifier"` and
        # ternary arms don't read as keys, then take every `key:` token (several per line).
        block = re.sub(r'`[^`]*`|"[^"]*"', '""', m.group(1))
        cols = list(dict.fromkeys(re.findall(r"(\w+)\s*:", block)))
        if len(cols) < 4:
            raise RuntimeError(f"implausibly few columns extracted for {table}; review the pin")
        out[table] = cols
    return out


def build_snapshot(pinned_at: str) -> dict[str, Any]:
    flat = extract_flattener_schemas()
    return {
        "pinned_at": pinned_at,
        "upstream": "fhirEngine (packages/server) — ADR-0022/0024 flattener, ADR-0012 MPI, sidecar Bronze row",
        **flat,
        "bronze_row_schema": extract_bronze_schema(),
        "mpi_tables": extract_mpi_tables(),
        "fhirhouse_tables": FHIRHOUSE_TABLES,
    }


# ── convenience accessors for DQ (read from the PIN, not live: DQ scores against the
#    contract fhirHouse was built for; drift is the drift test's job) ────────────────

def top_level_columns(resource_type: str, pin: dict | None = None) -> list[dict]:
    return (pin or load_pin())["top_level_columns"][resource_type]

def required_columns(resource_type: str, pin: dict | None = None) -> list[str]:
    return [c["name"] for c in top_level_columns(resource_type, pin) if c.get("required")]
