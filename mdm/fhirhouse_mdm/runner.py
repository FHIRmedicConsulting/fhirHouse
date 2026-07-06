"""MDM run entrypoints (called by dagster/ assets or ad hoc).

run_probabilistic — the Stage B lane: read current Patients read-side, score with the
pinned Splink artifact, band + persist (decide.py). Guardrail #1 (deterministic-first)
is enforced here: pairs sharing a business identifier belong to fhirEngine's
deterministic stage (they were already auto-merged or queued at promotion) and are
dropped from the probabilistic lane.

run_pprl — tokenize current Patients into gold.pprl_tokens for every configured
token system.
"""
from __future__ import annotations

from fhirhouse_contracts import PathCatalog, SidecarClient, read_current_resources

from .config import MdmConfig, load_config
from .decide import persist_decisions
from .pprl import generate_tokens
from .splink_model import patient_to_record, predict_pairs


def _records(base: str | None, tier: str = "bronze") -> list[dict]:
    catalog = PathCatalog(base)
    patients = read_current_resources(catalog, tier, "Patient")
    # inactive Patients are merged-away records — never candidates (guardrail table §3.4)
    return [patient_to_record(p) for p in patients if p.get("active") is not False]


def run_probabilistic(
    config: MdmConfig | None = None,
    base: str | None = None,
    tier: str = "bronze",
    sidecar: SidecarClient | None = None,
) -> dict:
    cfg = config or load_config()
    if not cfg.splink.enabled:
        return {"skipped": "splink disabled in config (v2 gate, ADR-0012)"}
    records = _records(base, tier)
    if len(records) < 2:
        return {"skipped": f"{len(records)} candidate patients — nothing to link"}
    by_id = {r["unique_id"]: r for r in records}
    pairs = predict_pairs(records, cfg.splink)

    # guardrail #1: deterministic-first — shared-identifier pairs are deterministic scope
    in_scope = []
    deterministic_scope = 0
    for p in pairs:
        left, right = by_id.get(str(p["unique_id_l"]), {}), by_id.get(str(p["unique_id_r"]), {})
        if set(left.get("identifier_keys") or []) & set(right.get("identifier_keys") or []):
            deterministic_scope += 1
            continue
        in_scope.append(p)

    result = persist_decisions(in_scope, by_id, cfg, sidecar=sidecar, catalog=PathCatalog(base))
    result["deterministic_scope_pairs_dropped"] = deterministic_scope
    result["scored_pairs"] = len(pairs)
    return result


def run_pprl(
    config: MdmConfig | None = None,
    base: str | None = None,
    tier: str = "bronze",
    sidecar: SidecarClient | None = None,
) -> dict:
    cfg = config or load_config()
    if not cfg.pprl_token_systems:
        return {"skipped": "no PPRL token systems configured"}
    records = _records(base, tier)
    rows = generate_tokens(records, cfg.pprl_token_systems, sidecar=sidecar, catalog=PathCatalog(base))
    return {"patients": len(records), "tokens_written": len(rows),
            "systems": [t.name for t in cfg.pprl_token_systems]}
