# dagster/ — orchestration (wraps, does not replace)

Dagster orchestrates fhirHouse's heavier assets (DQ runs, Splink, PPRL, backfills,
HITL review) with asset lineage. fhirEngine's delta-rs poll-loop promoter
(ADR-0026 §6) keeps running; Dagster **wraps** it, it does not become the promoter.

## Implementation (`fhirhouse_dagster/definitions.py`)

- Assets: `gold_promoted` (wraps `fhirengine-promote --all`; Silver+Gold+deterministic
  MPI happen inside fhirEngine) → `dq_scores`, `splink_matches`, `pprl_tokens`.
- Sensor: `hitl_review_sensor` watches `gold.patient_match_review` for new pending
  rows → `notify_stewards_job` (log + optional `FHIRHOUSE_HITL_WEBHOOK`).
- Run: `dagster dev -m fhirhouse_dagster.definitions` with `FHIRENGINE_DELTA_BASE`,
  `FHIRENGINE_DELTA_SIDECAR_URL` (and optionally `FHIRHOUSE_PROMOTE_CMD`,
  `FHIRHOUSE_DQ_TYPES`, `FHIRHOUSE_MDM_CONFIG`, `FHIRHOUSE_VALIDATOR_JAR`) set.
- Catalog lineage emission lands with the FH-0004 catalog choice (warehouse-gov/).
