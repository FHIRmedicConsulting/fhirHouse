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

## TODO (Claude Code)
- Splink model + blocking rules; persist m/u contributions to `gold.mpi_decision_log`.
- PPRL pipeline (Datavant/OpenHIE token systems, config-driven).
- All persistence via fhirEngine's delta-rs writer.
