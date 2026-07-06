"""OpenMetadata binding (FH-0004) — the catalog side of fhirEngine's ADR-0025 seam.

Everything speaks OM's REST API directly (stdlib only): entity registration,
lineage edges, PII classification, and DQ test cases/results. Column metadata comes
from the contracts pin, so the catalog always reflects the pinned FHIR contract.

Unity Catalog alignment (deliberate, FH-0004 §3):
  OM service   fhirhouse deployment      (≈ UC metastore binding)
  OM database  warehouse/catalog name    (= UC catalog)
  OM schema    bronze | silver | gold    (= UC schema; medallion tier)
  OM table     resource / governance     (= UC table)
A Databricks deployment ingests via OM's native Unity Catalog connector; both
worlds land in one catalog with identical shape.

Entrypoint CLI:
  python -m fhirhouse_warehouse_gov.openmetadata --base ~/fhirhouse-demo/delta \
      [--om http://localhost:8585/api/v1] [--service fhirhouse-standalone] \
      [--database fhirhouse_demo] [--dq] [--min-score 0.95]
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

from fhirhouse_contracts.schema import load_pin

TIER_DESCRIPTIONS = {
    "bronze": "raw FHIR landing (append-only, body_json source of truth — ADR-0024 §1)",
    "silver": "flattened + governed (fhirHouse chunked-promoter encoding)",
    "gold": "serving tier (current-version projection + MPI/DQ/PPRL governance tables)",
}
PHI_COLUMNS = {"name", "birthDate", "address", "telecom", "identifier", "body_json",
               "deceasedDateTime", "maritalStatus", "contact", "photo"}
_SCALAR_OM = {"bool": "BOOLEAN", "int32": "INT", "float64": "DOUBLE"}

BRONZE_COLUMNS = [
    {"name": "id", "dataType": "STRING", "description": "FHIR logical id"},
    {"name": "version_id", "dataType": "BIGINT"},
    {"name": "last_updated", "dataType": "STRING"},
    {"name": "body_json", "dataType": "JSON",
     "description": "Full FHIR resource (source of truth, ADR-0024 §1)"},
    {"name": "identifier_index", "dataType": "JSON"},
    {"name": "search_param_index", "dataType": "JSON"},
    {"name": "ext_json", "dataType": "JSON"},
    {"name": "deleted", "dataType": "BOOLEAN"},
    {"name": "is_current", "dataType": "BOOLEAN"},
    {"name": "_ingested_at", "dataType": "STRING"},
    {"name": "_ingest_source", "dataType": "STRING"},
]


class OpenMetadataClient:
    """Thin REST client. Auth: basic login (dev quickstart) or a bot JWT via
    OM_JWT_TOKEN for production deployments."""

    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url or os.environ.get("OM_URL", "http://localhost:8585/api/v1")).rstrip("/")
        self.token = token or os.environ.get("OM_JWT_TOKEN")

    def login(self, email: str | None = None, password: str | None = None) -> None:
        email = email or os.environ.get("OM_EMAIL", "admin@open-metadata.org")
        password = password or os.environ.get("OM_PASSWORD", "admin")
        r = self._req("POST", "/users/login", {
            "email": email, "password": base64.b64encode(password.encode()).decode()})
        self.token = r["accessToken"]

    def _req(self, method: str, path: str, body=None, content_type="application/json"):
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": content_type,
                     **({"Authorization": f"Bearer {self.token}"} if self.token else {})},
            method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"OpenMetadata {method} {path} -> {e.code}: "
                               f"{e.read().decode()[:400]}") from e

    def get(self, path):
        return self._req("GET", path)

    def put(self, path, body):
        return self._req("PUT", path, body)

    def post(self, path, body):
        return self._req("POST", path, body)

    def patch(self, path, ops):
        return self._req("PATCH", path, ops, content_type="application/json-patch+json")


# ── column derivation from the contracts pin ────────────────────────────────────

def silver_columns(resource_type: str, pin: dict) -> list[dict]:
    cols = [
        {"name": "silver_id", "dataType": "STRING"},
        {"name": "fhir_id", "dataType": "STRING", "description": "FHIR logical id (join key)"},
        {"name": "version_id", "dataType": "BIGINT"},
        {"name": "silver_status", "dataType": "STRING"},
        {"name": "governed_at", "dataType": "STRING"},
        {"name": "deleted", "dataType": "BOOLEAN"},
        {"name": "body_json", "dataType": "JSON"},
    ]
    for c in pin["top_level_columns"].get(resource_type, []):
        if c.get("list") or c["kind"] != "scalar":
            dt, note = "JSON", "complex element (JSON-encoded, fhirHouse Silver encoding)"
        else:
            dt, note = _SCALAR_OM.get(c.get("arrow", ""), "STRING"), f"FHIR {c['fhirType']}"
        cols.append({"name": c["name"], "dataType": dt,
                     "description": f"{resource_type}.{c['name']} — {note}"})
    return cols


def _governance_columns(table: str, pin: dict) -> list[dict]:
    for group in ("fhirhouse_tables", "mpi_tables"):
        if table in pin.get(group, {}):
            return [{"name": c, "dataType": "STRING"} for c in pin[group][table]]
    return [{"name": "id", "dataType": "STRING"}]


def _tables_in(base: str, tier: str) -> list[str]:
    d = os.path.join(base, tier)
    if not os.path.isdir(d):
        return []
    return sorted(t for t in os.listdir(d) if os.path.isdir(os.path.join(d, t, "_delta_log")))


# ── registration / lineage / tags / DQ ──────────────────────────────────────────

def register_store(om: OpenMetadataClient, base: str, service: str, database: str,
                   all_types: bool = True) -> dict[str, dict]:
    """Register tier tables; returns fqn -> table entity.

    With `all_types` (default) the FULL pinned R4 contract is registered — all 146
    resource types per tier — because the schema contract exists for every type
    (fhirEngine materializes tables on first write). Types with no data yet are
    marked in the description; physical governance tables are always included."""
    pin = load_pin()
    canonical = {t.lower(): t for t in pin["resource_types"]}
    om.put("/services/databaseServices", {
        "name": service, "serviceType": "CustomDatabase",
        "description": "fhirEngine Delta store governed by fhirHouse",
        "connection": {"config": {"type": "CustomDatabase",
                                  "sourcePythonClass": "fhirhouse_warehouse_gov"}}})
    om.put("/databases", {"name": database, "service": service,
                          "description": "fhirHouse deployment (UC-catalog-equivalent)"})
    entities: dict[str, dict] = {}
    for tier, desc in TIER_DESCRIPTIONS.items():
        om.put("/databaseSchemas", {"name": tier, "database": f"{service}.{database}",
                                    "description": desc})
        physical = set(_tables_in(base, tier))
        names = sorted(physical | set(canonical)) if all_types else sorted(physical)
        for t in names:
            rt = canonical.get(t)
            if tier == "silver" and rt:
                cols = silver_columns(rt, pin)
            elif rt:
                cols = BRONZE_COLUMNS
            else:
                cols = _governance_columns(t, pin)
            landed = "" if t in physical else " — no data landed in this deployment yet"
            entities[f"{service}.{database}.{tier}.{t}"] = om.put("/tables", {
                "name": t, "databaseSchema": f"{service}.{database}.{tier}",
                "columns": cols,
                "description": (f"FHIR {rt}{landed}" if rt
                                else f"fhirHouse governance table{landed}")})
    return entities


def wire_tier_lineage(om: OpenMetadataClient, entities: dict[str, dict],
                      service: str, database: str) -> int:
    edges = 0
    by_fqn = entities
    for fqn, e in list(by_fqn.items()):
        _, _, tier, table = fqn.rsplit(".", 3)
        nxt = {"bronze": "silver", "silver": "gold"}.get(tier)
        if not nxt:
            continue
        to_fqn = f"{service}.{database}.{nxt}.{table}"
        if to_fqn in by_fqn:
            om.put("/lineage", {"edge": {
                "fromEntity": {"id": e["id"], "type": "table"},
                "toEntity": {"id": by_fqn[to_fqn]["id"], "type": "table"},
                "lineageDetails": {"description": "fhirHouse chunked promotion (ADR-0026 external lane)"}}})
            edges += 1
    return edges


def tag_phi_columns(om: OpenMetadataClient, entities: dict[str, dict],
                    tag: str = "PII.Sensitive") -> int:
    tagged = 0
    for fqn, e in entities.items():
        table = om.get(f"/tables/{e['id']}")
        for i, c in enumerate(table["columns"]):
            if c["name"] in PHI_COLUMNS and not c.get("tags"):
                om.patch(f"/tables/{table['id']}", [{
                    "op": "add", "path": f"/columns/{i}/tags",
                    "value": [{"tagFQN": tag, "source": "Classification",
                               "labelType": "Automated", "state": "Confirmed"}]}])
                tagged += 1
    return tagged


def push_dq_run(om: OpenMetadataClient, base: str, service: str, database: str,
                min_score: float = 0.95, run_id: str | None = None) -> int:
    """Push a fhirHouse DQ run (gold/dq_score rows) as OM test cases + results.
    Default: the latest run. Threshold turns scores into pass/fail in the OM UI."""
    from deltalake import DeltaTable  # read-side

    rows = DeltaTable(os.path.join(base, "gold", "dq_score")).to_pyarrow_table().to_pylist()
    if run_id is None:
        run_id = max(rows, key=lambda r: r["computed_at"])["run_id"]
    rows = [r for r in rows if r["run_id"] == run_id and r["score"] is not None]

    om.put("/dataQuality/testDefinitions", {
        "name": "fhirhouseKahnMetric",
        "description": "fhirHouse Kahn-framework DQ metric (FH-0004 §1): "
                       "score = numerator/denominator over the population",
        "entityType": "TABLE", "testPlatforms": ["OpenMetadata"],
        "parameterDefinition": [
            {"name": "dimension", "dataType": "STRING"},
            {"name": "metric", "dataType": "STRING"},
            {"name": "minScore", "dataType": "DOUBLE"}]})

    ts = int(time.time() * 1000)
    pushed = 0
    for r in rows:
        table_fqn = f"{service}.{database}.{r['tier']}.{r['resource_type'].lower()}"
        case = f"kahn_{r['dimension']}_{r['metric']}".replace(":", "_").replace(".", "_")
        try:
            om.put("/dataQuality/testCases", {
                "name": case, "entityLink": f"<#E::table::{table_fqn}>",
                "testDefinition": "fhirhouseKahnMetric",
                "parameterValues": [
                    {"name": "dimension", "value": r["dimension"]},
                    {"name": "metric", "value": r["metric"]},
                    {"name": "minScore", "value": str(min_score)}],
                "description": f"{r['dimension']}: {r['metric']} (dq_version {r['dq_version']})"})
        except RuntimeError:
            continue  # table not registered (type not loaded in this deployment)
        om.post(f"/dataQuality/testCases/testCaseResults/{table_fqn}.{case}", {
            "timestamp": ts,
            "testCaseStatus": "Success" if r["score"] >= min_score else "Failed",
            "result": f"{r['metric']}: {r['numerator']}/{r['denominator']} = {r['score']:.4f}",
            "testResultValue": [{"name": "score", "value": str(round(r["score"], 6))}]})
        pushed += 1
    return pushed


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Register a fhirHouse store in OpenMetadata")
    ap.add_argument("--base", default=os.environ.get("FHIRENGINE_DELTA_BASE", "./delta"))
    ap.add_argument("--om", default=None)
    ap.add_argument("--service", default="fhirhouse-standalone")
    ap.add_argument("--database", default="fhirhouse")
    ap.add_argument("--dq", action="store_true", help="also push the latest DQ run")
    ap.add_argument("--min-score", type=float, default=0.95)
    args = ap.parse_args()

    om = OpenMetadataClient(url=args.om)
    if not om.token:
        om.login()
    entities = register_store(om, args.base, args.service, args.database)
    print(f"[warehouse-gov] registered {len(entities)} tables")
    print(f"[warehouse-gov] {wire_tier_lineage(om, entities, args.service, args.database)} lineage edges")
    print(f"[warehouse-gov] {tag_phi_columns(om, entities)} PHI columns tagged")
    if args.dq:
        print(f"[warehouse-gov] {push_dq_run(om, args.base, args.service, args.database, args.min_score)} "
              "DQ results pushed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
