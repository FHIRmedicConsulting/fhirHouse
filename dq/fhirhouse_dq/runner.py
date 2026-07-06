"""DQ run orchestration: read a tier read-side, score, persist to gold/dq_score.

Reads use read-side delta-rs (`deltalake.DeltaTable` — never writes); persistence is
handed to fhirEngine's sidecar (the sole writer, FH-0003). In medallion mode this runs
on the promotion seam (score Bronze-current before/alongside promotion); in
single-store mode it is the read-only observability pass (FH-0002) — same code, the
operator just points it at the one store.

Scores currently ANNOTATE promotion (they do not block it) — FH-0004's open question;
a blocking policy would be enforced by the orchestrator (dagster/) reading dq_score.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fhirhouse_contracts import PathCatalog, SidecarClient, read_current_resources
from fhirhouse_contracts.schema import load_pin

from .kahn import DQ_VERSION, MetricResult, score_resources
from .validator import ValidatorUnavailable, l5_conformance_metric, validate_resources


def metrics_to_rows(
    resource_type: str, tier: str, metrics: list[MetricResult], run_id: str, computed_at: str,
) -> list[dict]:
    """Shape MetricResults into the pinned gold/dq_score contract
    (fhirhouse_contracts.schema.FHIRHOUSE_TABLES['dq_score'])."""
    return [
        {
            "run_id": run_id,
            "computed_at": computed_at,
            "tier": tier,
            "resource_type": resource_type,
            "dimension": m.dimension,
            "metric": m.metric,
            "numerator": m.numerator,
            "denominator": m.denominator,
            "score": m.score,
            "details_json": json.dumps(m.details, sort_keys=True),
            "dq_version": DQ_VERSION,
        }
        for m in metrics
    ]


def run_dq(
    resource_types: list[str],
    base: str | None = None,
    tier: str = "bronze",
    sidecar: SidecarClient | None = None,
    write: bool = True,
    l5: bool = False,
    l5_igs: list[str] | None = None,
    l5_sample: int = 100,
) -> dict:
    """Score `resource_types` from `tier`; append rows to gold/dq_score via the sidecar.
    Returns {run_id, rows, skipped} — `rows` for inspection/orchestrator metadata."""
    catalog = PathCatalog(base)
    sidecar = sidecar or SidecarClient()
    pin = load_pin()
    run_id = str(uuid.uuid4())
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_rows: list[dict] = []
    skipped: dict[str, str] = {}

    for rt in resource_types:
        try:
            resources = read_current_resources(catalog, tier, rt)
        except Exception as e:  # table absent in this deployment → skip, keep the run going
            skipped[rt] = f"{type(e).__name__}: {e}"
            continue
        metrics = score_resources(rt, resources, pin=pin)
        if l5 and resources:
            try:
                outcomes = validate_resources(resources[:l5_sample], igs=l5_igs)
                metrics.append(l5_conformance_metric(rt, outcomes, l5_igs))
            except ValidatorUnavailable as e:
                skipped[f"{rt}:l5"] = str(e)
        all_rows.extend(metrics_to_rows(rt, tier, metrics, run_id, computed_at))

    if write and all_rows:
        sidecar.write(catalog.dq_score_path(), all_rows, mode="append", schema="infer")
    return {"run_id": run_id, "rows": all_rows, "skipped": skipped}
