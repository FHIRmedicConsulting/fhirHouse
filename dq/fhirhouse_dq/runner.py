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


# ── domain runs: generated check suites + profiling + reference integrity ───────

def _load_suites(domains: list[str]) -> dict[str, list[tuple[str, dict]]]:
    """domain -> [(resource_type, suite), ...] from dq/checks/<domain>/*.checks.json."""
    import pathlib

    checks_dir = pathlib.Path(__file__).resolve().parent.parent / "checks"
    out: dict[str, list[tuple[str, dict]]] = {}
    for d in domains:
        ddir = checks_dir / d
        if not ddir.is_dir():
            raise FileNotFoundError(f"no generated checks for domain {d!r} — run "
                                    "`python -m fhirhouse_dq.generate_checks`")
        suites = [json.loads(f.read_text()) for f in sorted(ddir.glob("*.checks.json"))]
        out[d] = [(s["resourceType"], s) for s in suites]
    return out


def _id_sets(catalog: PathCatalog, tier: str, types: set[str]) -> dict[str, set]:
    """id sets per referenced type (cheap: id column only) for existence checks."""
    from deltalake import DeltaTable

    out: dict[str, set] = {}
    for t in types:
        try:
            tbl = DeltaTable(catalog.table_path(tier, t)).to_pyarrow_table(columns=["id"])
            out[t] = set(tbl.column("id").to_pylist())
        except Exception:
            continue  # type not in this deployment — existence checks skip it
    return out


def run_domains(
    domains: list[str],
    base: str | None = None,
    tier: str = "bronze",
    sidecar: SidecarClient | None = None,
    write: bool = True,
    profile: bool = True,
    integrity: bool = True,
    kahn: bool = True,
) -> dict:
    """Run the generated per-domain check suites (+ Kahn baseline + profiling +
    reference-existence integrity) over `tier`. Appends to gold/dq_score and
    gold/dq_profile via the sidecar."""
    from .checks import run_checks
    from .profiler import profile_resources

    catalog = PathCatalog(base)
    sidecar = sidecar or SidecarClient()
    pin = load_pin()
    run_id = str(uuid.uuid4())
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    suites = _load_suites(domains)

    ref_types: set[str] = set()
    if integrity:
        for pairs in suites.values():
            for _, suite in pairs:
                for c in suite["checks"]:
                    if c["kind"] == "reference_target":
                        ref_types.update(c["targets"])
    id_sets = _id_sets(catalog, tier, ref_types) if integrity else None

    score_rows: list[dict] = []
    profile_rows: list[dict] = []
    skipped: dict[str, str] = {}
    summary: dict[str, dict] = {}
    for domain, pairs in suites.items():
        for rtype, suite in pairs:
            try:
                resources = read_current_resources(catalog, tier, rtype)
            except Exception as e:
                skipped[f"{domain}/{rtype}"] = f"{type(e).__name__}"
                continue
            metrics = run_checks(resources, suite["checks"], id_sets=id_sets)
            if kahn:
                metrics += score_resources(rtype, resources, pin=pin)
            for m in metrics:
                m.details["domain"] = domain
            score_rows += metrics_to_rows(rtype, tier, metrics, run_id, computed_at)
            if profile:
                profile_rows += profile_resources(rtype, resources, run_id, computed_at, tier, pin)
            failing = [m for m in metrics if m.score is not None and m.score < 1.0]
            summary[f"{domain}/{rtype}"] = {
                "resources": len(resources), "metrics": len(metrics),
                "imperfect": len(failing),
                "worst": min((m.score for m in failing), default=1.0)}

    if write and score_rows:
        sidecar.write(catalog.dq_score_path(), score_rows, mode="append", schema="infer")
    if write and profile_rows:
        sidecar.write(catalog.dq_profile_path(), profile_rows, mode="append", schema="infer")
    return {"run_id": run_id, "score_rows": score_rows, "profile_rows": profile_rows,
            "skipped": skipped, "summary": summary}
