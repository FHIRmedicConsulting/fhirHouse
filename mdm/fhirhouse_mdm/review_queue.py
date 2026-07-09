"""Review-queue TTL / escalation policy (fhirEngine ADR-0012 §5).

Queue-state policy is substrate (FH-0001: computes/persists governed data → OSS);
UIs call it, Dagster schedules it. Defaults per the ADR:

  pending   older than 7 days  → escalated     (senior steward)
  escalated older than 14 days → auto_aged_out (observability flag; strict
                                  deployments may auto-reject instead)

Transitions are append-only rows in the pinned patient_match_review shape, with
the policy actor recorded under evidence_json.decision (system, not an operator).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fhirhouse_contracts import PathCatalog, SidecarClient

PENDING_TTL_DAYS = 7
ESCALATED_TTL_DAYS = 14


def _latest_rows(catalog: PathCatalog) -> list[dict]:
    from deltalake import DeltaTable

    try:
        rows = DeltaTable(catalog.mpi_path("patient_match_review")).to_pyarrow_table().to_pylist()
    except Exception:
        return []
    latest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x.get("created_at") or ""):
        latest[r["candidate_ids"]] = r
    return list(latest.values())


def _transition_row(review: dict, new_status: str, reason: str, now: str) -> dict:
    try:
        evidence = json.loads(review.get("evidence_json") or "{}")
        if not isinstance(evidence, dict):
            evidence = {"candidates_snapshot": evidence}
    except json.JSONDecodeError:
        evidence = {}
    evidence["decision"] = {
        "action": new_status, "decision_action": new_status,
        "reviewer_id": "system:ttl-policy", "decided_at": now, "rationale": reason,
        **({"escalation_role": "senior_steward"} if new_status == "escalated" else {}),
    }
    return {
        "review_id": review.get("review_id") or "",
        "candidate_ids": review["candidate_ids"],
        "reason": review.get("reason") or "",
        "shared_identifiers": review.get("shared_identifiers") or "",
        "evidence_json": json.dumps(evidence, sort_keys=True),
        "suggested_action": review.get("suggested_action") or "",
        "status": new_status,
        "created_at": now,
    }


def age_reviews(
    base: str | None = None,
    sidecar: SidecarClient | None = None,
    pending_ttl_days: int = PENDING_TTL_DAYS,
    escalated_ttl_days: int = ESCALATED_TTL_DAYS,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict:
    """Apply the TTL policy; returns {escalated: [...], aged_out: [...]}."""
    catalog = PathCatalog(base)
    sidecar = sidecar or SidecarClient()
    now_dt = now or datetime.now(timezone.utc)
    now_iso = now_dt.isoformat(timespec="seconds")

    def expired(row: dict, days: int) -> bool:
        try:
            created = datetime.fromisoformat((row.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            return False
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return now_dt - created > timedelta(days=days)

    escalated, aged_out, rows = [], [], []
    for review in _latest_rows(catalog):
        if review.get("status") == "pending" and expired(review, pending_ttl_days):
            rows.append(_transition_row(
                review, "escalated",
                f"TTL: pending > {pending_ttl_days}d — auto-escalated to senior steward", now_iso))
            escalated.append(review["candidate_ids"])
        elif review.get("status") == "escalated" and expired(review, escalated_ttl_days):
            rows.append(_transition_row(
                review, "auto_aged_out",
                f"TTL: escalated > {escalated_ttl_days}d — aged out unresolved", now_iso))
            aged_out.append(review["candidate_ids"])

    if rows and not dry_run:
        sidecar.write(catalog.mpi_path("patient_match_review"), rows, mode="append")
    return {"escalated": escalated, "aged_out": aged_out, "dry_run": dry_run}


def main() -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Apply review-queue TTL policy (ADR-0012 §5)")
    ap.add_argument("--base", default=os.environ.get("FHIRENGINE_DELTA_BASE", "./delta"))
    ap.add_argument("--pending-ttl-days", type=int, default=PENDING_TTL_DAYS)
    ap.add_argument("--escalated-ttl-days", type=int, default=ESCALATED_TTL_DAYS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(age_reviews(base=args.base, pending_ttl_days=args.pending_ttl_days,
                                 escalated_ttl_days=args.escalated_ttl_days,
                                 dry_run=args.dry_run), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
