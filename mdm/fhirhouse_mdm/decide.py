"""Three-band decisioning over Splink scores + persistence into the Gold MPI contract.

Flow (ADR-0012 §1 Stage B, batch/bulk-dedup form):
  scored pair → hard-deny guardrails (§3.4; #4: applied post-Splink)
             → band: auto (≥ auto threshold; cross-authority threshold when the pair
               shares no assigning authority, #12) | review (≥ review threshold) | new
             → persist:
                 gold.patient_match_review  — one row per auto/review pair, PENDING.
                   Default posture = operator acknowledgment before any merge (ADR
                   open question #4): even auto-band pairs await steward approval;
                   fhirEngine's promoter applies approved merges. suggested_action
                   distinguishes the bands for bulk approval.
                 gold.mpi_decision_log      — per-pair m/u evidence (gamma_*/bf_*), #9.
                 Provenance (Bronze)        — audit per decision, #8.
Rows match the pinned contracts exactly (contracts/gold_schema.snapshot.json).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fhirhouse_contracts import PathCatalog, SidecarClient
from fhirhouse_lineage import build_provenance, write_provenance

from .config import MdmConfig
from .guardrails import guardrail

BAND_AUTO = "auto_match"
BAND_REVIEW = "review"
BAND_NEW = "new"
BAND_DENIED = "hard_deny"


def classify_pair(pair: dict, left: dict, right: dict, cfg: MdmConfig) -> tuple[str, str | None]:
    """(band, guardrail_reason). `left`/`right` are linkage records from
    splink_model.patient_to_record (carry identifier_systems); `pair` has
    match_probability."""
    s = cfg.splink
    score = float(pair["match_probability"])
    block = guardrail(_as_body(left), _as_body(right), s.deceased_window_days)
    if block == "distinct":
        return BAND_DENIED, "conflicting_authoritative_identifier"
    # cross-assigning-authority pairs need the tighter threshold (guardrail #12)
    shared_authority = bool(set(left.get("identifier_systems") or []) & set(right.get("identifier_systems") or []))
    auto_threshold = s.auto_match_threshold if shared_authority else s.cross_assigning_authority_threshold
    if score >= auto_threshold:
        if block:  # high score but safety floor violated → review, flagged (guardrail #4)
            return BAND_REVIEW, f"safety_override:{block}"
        return BAND_AUTO, None
    if score >= s.review_threshold:
        return BAND_REVIEW, block
    return BAND_NEW, block


def _as_body(record: dict) -> dict:
    """Rebuild the minimal Patient-body view the guardrails inspect from a linkage record."""
    return {
        "gender": record.get("gender"),
        "deceasedDateTime": record.get("deceased_datetime"),
        "active": record.get("active", True),
        "identifier": [
            {"system": k.split("|", 1)[0], "value": k.split("|", 1)[1]}
            for k in record.get("identifier_keys") or []
        ],
    }


def _evidence(rec: dict) -> dict:
    return {k: rec.get(k) for k in ("unique_id", "given_name", "family_name", "birth_date", "gender", "postal_code")}


def persist_decisions(
    pairs: list[dict],
    records_by_id: dict[str, dict],
    cfg: MdmConfig,
    sidecar: SidecarClient | None = None,
    catalog: PathCatalog | None = None,
    run_id: str | None = None,
    write_provenance_rows: bool = True,
) -> dict:
    """Classify every scored pair and persist review-queue rows, decision-log rows, and
    Provenance. Returns band counts + the run id."""
    sidecar = sidecar or SidecarClient()
    catalog = catalog or PathCatalog()
    run_id = run_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    s = cfg.splink

    review_rows: list[dict] = []
    log_rows: list[dict] = []
    counts = {BAND_AUTO: 0, BAND_REVIEW: 0, BAND_NEW: 0, BAND_DENIED: 0}

    for p in pairs:
        lid, rid = str(p["unique_id_l"]), str(p["unique_id_r"])
        left, right = records_by_id.get(lid, {}), records_by_id.get(rid, {})
        band, flag = classify_pair(p, left, right, cfg)
        counts[band] += 1

        # per-attribute m/u evidence: Splink's gamma_ (comparison level) and bf_ (Bayes
        # factor) columns are exactly the guardrail-#9 contribution breakdown.
        contributions = {k: v for k, v in p.items() if k.startswith(("gamma_", "bf_"))}
        log_rows.append({
            "decision_id": str(uuid.uuid4()),
            "run_id": run_id,
            "left_fhir_id": lid,
            "right_fhir_id": rid,
            "match_probability": float(p["match_probability"]),
            "match_weight": float(p.get("match_weight", 0.0)),
            "band": band if not flag else f"{band}:{flag}",
            "contributions_json": json.dumps(contributions, sort_keys=True, default=str),
            "model_version": s.model_version,
            "decided_at": now,
        })

        if band in (BAND_AUTO, BAND_REVIEW):
            review_rows.append({
                "review_id": str(uuid.uuid4()),
                "candidate_ids": ",".join(sorted([lid, rid])),
                "reason": flag or ("probabilistic_auto_band" if band == BAND_AUTO else "probabilistic_review_band"),
                "shared_identifiers": ", ".join(
                    sorted(set(left.get("identifier_keys") or []) & set(right.get("identifier_keys") or []))),
                "evidence_json": json.dumps({
                    "bulk_dedup_run_id": run_id,
                    "match_probability": float(p["match_probability"]),
                    "model_version": s.model_version,
                    "candidates": [_evidence(left), _evidence(right)],
                }, sort_keys=True),
                "suggested_action": "approve_merge" if band == BAND_AUTO else "steward_review",
                "status": "pending",
                "created_at": now,
            })

    # Dedup against reviews already queued (mirror promote.ts semantics: steward
    # decision rows are never touched; re-runs don't duplicate pending pairs).
    if review_rows:
        try:
            existing = {
                r["candidate_ids"]
                for r in sidecar.query(
                    "SELECT candidate_ids FROM patient_match_review",
                    {"patient_match_review": catalog.mpi_path("patient_match_review")})
            }
        except Exception:
            existing = set()  # first run — table doesn't exist yet
        review_rows = [r for r in review_rows if r["candidate_ids"] not in existing]
        if review_rows:
            sidecar.write(catalog.mpi_path("patient_match_review"), review_rows, mode="append")

    if log_rows:
        sidecar.write(catalog.mpi_decision_log_path(), log_rows, mode="append")

    if write_provenance_rows:
        for r in review_rows:  # audit Provenance per queued decision (guardrail #8)
            ids = r["candidate_ids"].split(",")
            prov = build_provenance(
                activity="MATCH",
                targets=[f"Patient/{i}" for i in ids],
                agent_display=f"fhirhouse-mdm splink (model {s.model_version})",
                reason=f"{r['reason']} p={json.loads(r['evidence_json'])['match_probability']:.4f} "
                       f"run={run_id} review={r['review_id']}",
                recorded=now,
            )
            write_provenance(prov, sidecar=sidecar, catalog=catalog, ingest_source="mdm-splink")

    return {"run_id": run_id, "counts": counts, "queued_reviews": len(review_rows), "decision_log_rows": len(log_rows)}
