# dagster/ — orchestration (wraps, does not replace)

Dagster orchestrates fhirHouse's heavier assets (DQ runs, Splink, PPRL, backfills,
HITL review) with asset lineage. fhirEngine's delta-rs poll-loop promoter
(ADR-0026 §6) keeps running; Dagster **wraps** it, it does not become the promoter.

## TODO (Claude Code)
- Define assets: `dq_scores`, `splink_matches`, `pprl_tokens`, `silver_governed`,
  `gold_promoted` (wrapping `fhirengine-promote`).
- Add a **sensor** over `gold.patient_match_review` to route HITL items.
- Emit asset lineage to the catalog (see `lineage/`).
