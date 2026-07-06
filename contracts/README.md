# contracts/ — fhirEngine Gold/flattener contract pin

fhirHouse must land MDM/cleaning output in fhirEngine's clean-room flattener
columnar Gold layout as valid FHIR (fhirEngine ADR-0022/0024). This directory
**pins** that contract and **drift-tests** it in CI — the concrete meaning of
"CI/CD pulls from fhirEngine."

## TODO (Claude Code)
1. Extract the canonical Gold/flattener schema from upstream:
   `packages/server/src/fhir-schema/clean-room-flattener.ts` and the generated R4
   schemas (`scripts/generate-r4-schemas.ts` output). Serialize to
   `gold_schema.snapshot.json` (per-resource column names + types + partitioning).
2. Also pin the MPI table schemas from ADR-0012 §2 (`patient_link`,
   `patient_match_review`, `patient_merge_history`, `pprl_tokens`,
   `mpi_decision_log`).
3. `drift_test.py` compares the live upstream schema against the pin and fails on
   drift, prompting a reviewed pin bump.
