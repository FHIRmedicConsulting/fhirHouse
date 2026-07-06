# mdm/ — probabilistic + PPRL master data management

fhirEngine ADR-0012 already implements **deterministic** MPI at promotion. fhirHouse
owns only the deferred lanes:

- **Splink** probabilistic linkage — runs only when deterministic doesn't decide;
  three-band thresholds (auto ≥0.95, review 0.70–0.95, new <0.70) per ADR-0012 §2.
- **PPRL** tokenization for cross-org TEFCA matching → `gold.pprl_tokens`.

Writes into the **existing** Gold MPI tables — do not redefine them:
`gold.patient_link`, `gold.patient_match_review`, `gold.patient_merge_history`,
`gold.pprl_tokens`, `gold.mpi_decision_log`. Every decision writes Provenance
(ADR-0012 §5). HITL review is surfaced via Dagster.

## Implementation (`fhirhouse_mdm/`)

- `guardrails.py` — Python port of upstream's §3.4 hard-deny floors (parity-tested).
- `config.py` — deployment YAML (see `config.example.yml`) with the guardrail floors
  enforced at load (auto ≥0.90 absolute; <0.95 needs acknowledgment; cross-authority
  ≥ auto).
- `splink_model.py` — Splink 4 on DuckDB (FH-0003; no Spark). Offline EM training to
  a staged artifact; production pins the artifact in config (guardrails #6/#7);
  pre-run blocking-pair sanity check (#5).
- `decide.py` — three-band classification (#2/#3/#12, safety-override #4) →
  `patient_match_review` (pending; operator-ack default posture — fhirEngine's
  promoter applies approved merges), `mpi_decision_log` m/u contributions (#9),
  Provenance per decision (#8).
- `pprl.py` — HMAC + CLK token systems, customer-controlled keys from env, rotation
  via pipeline_version → `gold.pprl_tokens`.
- `runner.py` — entrypoints wired to the Dagster assets; enforces
  deterministic-first (#1) by dropping shared-identifier pairs.
