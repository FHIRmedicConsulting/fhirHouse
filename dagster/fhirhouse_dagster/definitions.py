"""fhirHouse Dagster definitions — orchestration that WRAPS fhirEngine, never replaces it
(fhirEngine ADR-0026 §6: the delta-rs promoter stays authoritative; FH decision #6).

Assets:
  gold_promoted   — wraps the reference promoter CLI (`fhirengine-promote --all`);
                    fhirEngine performs promotion + deterministic MPI, we get lineage.
  dq_scores       — Kahn + L5 scoring → gold/dq_score (annotates, does not block —
                    FH-0004 open question; flip by gating downstream assets on it).
  splink_matches  — probabilistic Stage B → review queue + decision log + Provenance.
  pprl_tokens     — PPRL tokenization → gold/pprl_tokens.

Sensor:
  hitl_review_sensor — watches gold.patient_match_review for new PENDING rows (both
  deterministic multi-match from fhirEngine and our probabilistic bands) and launches
  `notify_stewards_job` per batch. Steward decisions are new review rows (ADR-0012 §5);
  fhirEngine's promoter applies approved merges on its next run.

Environment: FHIRENGINE_DELTA_BASE, FHIRENGINE_DELTA_SIDECAR_URL,
FHIRHOUSE_PROMOTE_CMD, FHIRHOUSE_DQ_TYPES, FHIRHOUSE_MDM_CONFIG.
"""
import json
import os
import shlex
import subprocess

from dagster import (
    AssetExecutionContext,
    Definitions,
    Field,
    MetadataValue,
    OpExecutionContext,
    RunRequest,
    ScheduleDefinition,
    SensorEvaluationContext,
    SkipReason,
    asset,
    job,
    op,
    sensor,
)

DEFAULT_PROMOTE_CMD = "npx tsx packages/server/scripts/fhirengine-promote.ts --all"
DEFAULT_DQ_TYPES = "Patient,Observation,Condition,Encounter"


def _delta_base() -> str:
    return os.environ.get("FHIRENGINE_DELTA_BASE", "./delta")


@asset(group_name="promotion", description="Apply steward-APPROVED merge decisions from "
       "gold.patient_match_review before promotion: merge_history ledger + new Bronze "
       "versions + MERGE Provenance (fhirhouse_mdm.apply_decisions). Idempotent.")
def review_decisions_applied(context: AssetExecutionContext) -> None:
    from fhirhouse_mdm.apply_decisions import apply_decisions

    result = apply_decisions(base=_delta_base())
    if result["errors"]:
        raise RuntimeError(f"decision application errors: {result['errors']}")
    context.add_output_metadata({
        "applied": MetadataValue.json(result["applied"]),
        "skipped_already_merged": len(result["skipped_already_merged"])})


@asset(deps=[review_decisions_applied], group_name="promotion",
       description="Bronze→Silver+Gold. Patient goes through "
       "fhirEngine's reference promoter (deterministic MPI runs there, ADR-0012); every "
       "other Bronze type through fhirHouse's chunked external promoter (no V8 size cap).")
def gold_promoted(context: AssetExecutionContext) -> None:
    from fhirhouse_contracts.schema import load_pin

    from .chunked_promote import promote_type

    base = _delta_base()
    # 1. Patient via the reference CLI — MPI (dedup/links/review queue) lives upstream.
    cmd = os.environ.get("FHIRHOUSE_PROMOTE_CMD", DEFAULT_PROMOTE_CMD.replace("--all", "Patient"))
    context.log.info(f"reference promoter (Patient/MPI): {cmd}")
    proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=3600)
    context.log.info(proc.stderr[-2000:])
    if proc.returncode != 0:
        raise RuntimeError(f"fhirengine-promote Patient failed ({proc.returncode}): {proc.stderr[-1000:]}")

    # 2. Every other Bronze table via the chunked promoter (survivor map applied).
    canonical = {t.lower(): t for t in load_pin()["resource_types"]}
    bronze_dir = os.path.join(base, "bronze")
    types = sorted(
        canonical[t] for t in (os.listdir(bronze_dir) if os.path.isdir(bronze_dir) else [])
        if t in canonical and t != "patient"
        and os.path.isdir(os.path.join(bronze_dir, t, "_delta_log")))
    results = []
    for t in types:
        stats = promote_type(t, base=base)
        context.log.info(f"chunked-promoted {t}: {stats}")
        results.append(stats)
    context.add_output_metadata({
        "promoted_types": len(results) + 1,
        "gold_rows": sum(r["gold"] for r in results),
        "silver_rows": sum(r["silver"] for r in results),
        "results": MetadataValue.json(results),
    })


@asset(deps=[gold_promoted], group_name="governance",
       description="Kahn-dimension DQ scoring (+ optional L5 IG conformance) → gold/dq_score.")
def dq_scores(context: AssetExecutionContext) -> None:
    from fhirhouse_dq import run_dq

    types = [t.strip() for t in os.environ.get("FHIRHOUSE_DQ_TYPES", DEFAULT_DQ_TYPES).split(",") if t.strip()]
    result = run_dq(types, base=_delta_base(), l5=bool(os.environ.get("FHIRHOUSE_VALIDATOR_JAR")))
    scores = {f"{r['resource_type']}:{r['metric']}": r["score"]
              for r in result["rows"] if r["dimension"] != "completeness" and r["score"] is not None}
    context.add_output_metadata({
        "run_id": result["run_id"],
        "metric_rows": len(result["rows"]),
        "skipped": MetadataValue.json(result["skipped"]),
        "scores": MetadataValue.json(scores),
    })


@asset(deps=[gold_promoted], group_name="governance",
       description="Splink probabilistic Stage B (ADR-0012 §4, twelve guardrails) → "
                   "patient_match_review + mpi_decision_log + Provenance.")
def splink_matches(context: AssetExecutionContext) -> None:
    from fhirhouse_mdm.runner import run_probabilistic

    result = run_probabilistic(base=_delta_base())
    context.add_output_metadata({k: MetadataValue.json(v) if isinstance(v, (dict, list)) else v
                                 for k, v in result.items()})


@asset(deps=[gold_promoted], group_name="governance",
       description="PPRL tokenization (ADR-0012 §6) → gold/pprl_tokens.")
def pprl_tokens(context: AssetExecutionContext) -> None:
    from fhirhouse_mdm.runner import run_pprl

    result = run_pprl(base=_delta_base())
    context.add_output_metadata({k: MetadataValue.json(v) if isinstance(v, (dict, list)) else v
                                 for k, v in result.items()})


@op(config_schema={"reviews_json": Field(str, default_value="[]")})
def notify_stewards(context: OpExecutionContext) -> None:
    """Surface pending HITL reviews. v1 = log + optional webhook (FHIRHOUSE_HITL_WEBHOOK);
    the stewardship UI itself is commercial scope (FH-0001 stance b)."""
    reviews = json.loads(context.op_config["reviews_json"])
    context.log.warning(f"{len(reviews)} pending patient_match_review item(s) need stewardship")
    for r in reviews:
        context.log.info(f"  review {r.get('review_id')}: {r.get('reason')} candidates={r.get('candidate_ids')}")
    hook = os.environ.get("FHIRHOUSE_HITL_WEBHOOK")
    if hook and reviews:
        import urllib.request

        req = urllib.request.Request(hook, data=json.dumps({"pending_reviews": reviews}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()


@job
def notify_stewards_job():
    notify_stewards()


@op
def age_review_queue(context: OpExecutionContext) -> None:
    """Apply the ADR-0012 §5 TTL policy (pending>7d → escalated; escalated>14d →
    aged out)."""
    from fhirhouse_mdm.review_queue import age_reviews

    result = age_reviews(base=_delta_base())
    context.log.info(f"aged review queue: {result}")


@job
def age_review_queue_job():
    age_review_queue()


age_review_queue_schedule = ScheduleDefinition(
    job=age_review_queue_job, cron_schedule="0 6 * * *",
    description="Daily review-queue TTL aging (ADR-0012 §5).")


@sensor(job=notify_stewards_job, minimum_interval_seconds=60,
        description="HITL: new pending rows in gold.patient_match_review → notify_stewards_job.")
def hitl_review_sensor(context: SensorEvaluationContext):
    from deltalake import DeltaTable  # read-side only

    path = f"{_delta_base()}/gold/patient_match_review"
    try:
        rows = DeltaTable(path).to_pyarrow_table().to_pylist()
    except Exception:
        return SkipReason(f"no review table yet at {path}")
    cursor = context.cursor or ""
    pending = sorted(
        (r for r in rows if r.get("status") == "pending" and (r.get("created_at") or "") > cursor),
        key=lambda r: r.get("created_at") or "",
    )
    if not pending:
        return SkipReason("no new pending reviews")
    newest = pending[-1]["created_at"]
    context.update_cursor(newest)
    payload = [{k: r.get(k) for k in ("review_id", "reason", "candidate_ids", "suggested_action", "created_at")}
               for r in pending]
    return RunRequest(
        run_key=f"hitl-{newest}-{len(pending)}",
        run_config={"ops": {"notify_stewards": {"config": {"reviews_json": json.dumps(payload)}}}},
    )


defs = Definitions(
    assets=[review_decisions_applied, gold_promoted, dq_scores, splink_matches, pprl_tokens],
    jobs=[notify_stewards_job, age_review_queue_job],
    schedules=[age_review_queue_schedule],
    sensors=[hitl_review_sensor],
)
