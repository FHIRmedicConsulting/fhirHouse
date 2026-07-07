"""Apply steward-approved merge decisions from gold.patient_match_review.

Closes the HITL loop (ADR-0012 §5): the stewardship workbench records decisions as
append-only review rows (details under evidence_json.decision); this applier
consumes `approved` + `merged_to:` decisions and makes them real — WITHOUT touching
upstream code or violating append-only Bronze:

  1. gold.patient_merge_history gains the ledger row (merge_actor
     "operator:<reviewer>", splink_score from the review evidence) — the promoters'
     loadSurvivorMap reads this table, so downstream reference rewriting follows
     automatically on the next promotion.
  2. Both patients get NEW BRONZE VERSIONS via the sidecar's atomic version flip:
     merged  -> active=false + link[replaced-by survivor]  (FHIR merge semantics)
     survivor-> link[replaces merged]
  3. A MERGE Provenance (agent operator:<reviewer>) lands in Bronze (ADR-0012 §8).

Idempotent: pairs already active in patient_merge_history are skipped, so re-runs
(and the Dagster asset) converge. approve_distinct / reject / escalate decisions
need no store action — the review row is the record.

    python -m fhirhouse_mdm.apply_decisions [--base <delta>] [--dry-run]
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fhirhouse_contracts import PathCatalog, SidecarClient
from fhirhouse_lineage import build_provenance, write_provenance


def _latest_reviews(catalog: PathCatalog) -> list[dict]:
    from deltalake import DeltaTable

    try:
        rows = DeltaTable(catalog.mpi_path("patient_match_review")).to_pyarrow_table().to_pylist()
    except Exception:
        return []
    latest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x.get("created_at") or ""):
        latest[r["candidate_ids"]] = r
    return list(latest.values())


def _active_merges(catalog: PathCatalog) -> set[tuple[str, str]]:
    from deltalake import DeltaTable

    try:
        rows = DeltaTable(catalog.mpi_path("patient_merge_history")).to_pyarrow_table(
            columns=["surviving_fhir_id", "merged_fhir_id", "unmerged_at"]).to_pylist()
    except Exception:
        return set()
    return {(r["surviving_fhir_id"], r["merged_fhir_id"]) for r in rows if not r.get("unmerged_at")}


def _current_bronze_patient(catalog: PathCatalog, fhir_id: str) -> dict | None:
    from deltalake import DeltaTable

    rows = DeltaTable(catalog.table_path("bronze", "Patient")).to_pyarrow_table().to_pylist()
    best = None
    for r in rows:
        if r["id"] == fhir_id and (best is None or (r["version_id"] or 0) > (best["version_id"] or 0)):
            best = r
    return best


def _new_version(row: dict, body: dict, now: str) -> dict:
    return {**{k: row[k] for k in ("id", "identifier_index", "search_param_index", "ext_json")},
            "version_id": int(row["version_id"] or 0) + 1, "last_updated": now,
            "body_json": json.dumps(body, separators=(",", ":")),
            "deleted": False, "is_current": True,
            "_ingested_at": now, "_ingest_source": "fhirhouse-merge-apply"}


def apply_decisions(base: str | None = None, sidecar: SidecarClient | None = None,
                    dry_run: bool = False) -> dict:
    catalog = PathCatalog(base)
    sidecar = sidecar or SidecarClient()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    applied, skipped, errors = [], [], []
    already = _active_merges(catalog)

    for review in _latest_reviews(catalog):
        if review.get("status") != "approved":
            continue
        try:
            decision = (json.loads(review.get("evidence_json") or "{}") or {}).get("decision") or {}
        except json.JSONDecodeError:
            decision = {}
        if decision.get("action") != "approve_merge" or not decision.get("survivor_fhir_id"):
            continue
        survivor_id = decision["survivor_fhir_id"]
        merged_ids = [i for i in review["candidate_ids"].split(",") if i and i != survivor_id]

        for merged_id in merged_ids:
            if (survivor_id, merged_id) in already:
                skipped.append((survivor_id, merged_id))
                continue
            surv = _current_bronze_patient(catalog, survivor_id)
            merged = _current_bronze_patient(catalog, merged_id)
            if not surv or not merged:
                errors.append({"pair": (survivor_id, merged_id), "error": "patient not in Bronze"})
                continue
            if dry_run:
                applied.append((survivor_id, merged_id))
                continue

            # 1. ledger row — promoters' survivor map reads this (pinned 7-col shape)
            sidecar.write(catalog.mpi_path("patient_merge_history"), [{
                "merge_id": str(uuid.uuid4()),
                "surviving_fhir_id": survivor_id, "merged_fhir_id": merged_id,
                "merged_at": now,
                "merge_reason": f"review_approved:{review.get('review_id')} "
                                f"{decision.get('rationale', '')}".strip(),
                "merge_actor": f"operator:{decision.get('reviewer_id', 'unknown')}",
                "unmerged_at": None}], mode="append")

            # 2. new Bronze versions (atomic current-version flip via the sidecar)
            m_body = json.loads(merged["body_json"])
            m_body["active"] = False
            m_body["link"] = (m_body.get("link") or []) + [
                {"other": {"reference": f"Patient/{survivor_id}"}, "type": "replaced-by"}]
            s_body = json.loads(surv["body_json"])
            s_body["link"] = (s_body.get("link") or []) + [
                {"other": {"reference": f"Patient/{merged_id}"}, "type": "replaces"}]
            for row, body in ((merged, m_body), (surv, s_body)):
                sidecar.write_version(catalog.table_path("bronze", "Patient"),
                                      _new_version(row, body, now),
                                      prev_version_id=int(row["version_id"] or 0))

            # 3. MERGE Provenance, operator agent (ADR-0012 §8)
            prov = build_provenance(
                activity="MERGE",
                targets=[f"Patient/{survivor_id}", f"Patient/{merged_id}"],
                agent_display=f"operator:{decision.get('reviewer_id', 'unknown')} via "
                              "fhirHouse stewardship (review approval)",
                reason=f"review {review.get('review_id')}: {decision.get('rationale', '')}".strip(),
                recorded=now)
            write_provenance(prov, sidecar=sidecar, catalog=catalog, ingest_source="merge-apply")

            already.add((survivor_id, merged_id))
            applied.append((survivor_id, merged_id))

    return {"applied": applied, "skipped_already_merged": skipped, "errors": errors,
            "note": "run promotion (Patient first) to propagate merges to Silver/Gold "
                    "and rewrite downstream references"}


def main() -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Apply approved merge decisions from the review queue")
    ap.add_argument("--base", default=os.environ.get("FHIRENGINE_DELTA_BASE", "./delta"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    res = apply_decisions(base=args.base, dry_run=args.dry_run)
    print(json.dumps(res, indent=1))
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
