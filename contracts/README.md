# contracts/ — fhirEngine Gold/flattener contract pin

fhirHouse must land MDM/cleaning output in fhirEngine's clean-room flattener
columnar Gold layout as valid FHIR (fhirEngine ADR-0022/0024). This directory
**pins** that contract and **drift-tests** it in CI — the concrete meaning of
"CI/CD pulls from fhirEngine."

## Layout

- `gold_schema.snapshot.json` — the pin: all 146 R4 flattener schemas (full nested
  shape as sha256 per type + readable top-level columns), the sidecar Bronze row
  schema, the Gold MPI table shapes as promote.ts writes them, and the
  fhirHouse-owned Gold tables (`pprl_tokens`, `mpi_decision_log`, `dq_score`).
- `drift_test.py` — compares live upstream against the pin; non-zero on drift (CI
  blocks). Re-pin after a reviewed upstream merge: `python contracts/pin_schema.py`.
- `fhirhouse_contracts/` — the Python seam every fhirHouse module uses:
  `SidecarClient` (fhirEngine's delta-rs writer — the ONLY write path),
  `PathCatalog` (mirror of upstream's ADR-0025 path binding), pinned-schema loaders,
  and read-side helpers.
