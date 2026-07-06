# dq/ — data-quality scoring engine

Does **not** re-do fhirEngine's pre-Bronze L1–L4 validation. Scores the gaps
fhirEngine names (FH-0004 §1):

- **L5 IG/profile conformance** via the external HL7 Java validator (closed/max
  slices, discriminators, must-support).
- **Cross-record DQ** on the **Kahn framework**: conformance, completeness,
  plausibility — scored over populations, not single resources.

Runs Bronze→Silver in medallion; read-only pass in single-store (FH-0002). Emits a
versioned DQ score table consumed by the catalog.

## Implementation (`fhirhouse_dq/`)

**Generated domain suites** (the main engine — code-gen from the FHIR packages,
mirroring the view pack's test-everything contract):

- `domains.yml` — Clinical / Provider / Patient-Member → resource types + the US
  Core profile driving each type's completeness expectations.
- `fhir_packages.py` — local package cache access with honest ValueSet expansion
  (extensional + complete CodeSystems only; SNOMED/LOINC-style sets return None
  and the check is skipped, never guessed).
- `generate_checks.py` — emits `dq/checks/<domain>/<Type>.checks.json`: required
  elements, terminology-expanded required bindings, temporal lexical form + range
  plausibility, scalar-shape guards (array-where-max=1), reference target-type +
  existence checks, US Core must-support completeness. Every check is executed
  before emission. Regenerate: `python -m fhirhouse_dq.generate_checks`.
- `checks.py` — the suite interpreter (honest denominators per check kind;
  dimensions: conformance / completeness / plausibility / integrity).
- `profiler.py` — statistical profiles → `gold/dq_profile` (pinned shape): row
  counts, id-duplication, per-element population, top-k code frequencies, temporal
  min/max, Quantity numeric stats (min/max/mean/p50/p95, top unit).
- `runner.py` `run_domains()` + CLI `python -m fhirhouse_dq --domains ...` —
  reads a tier once per type, runs suites + Kahn baseline + profiling +
  cross-table reference existence, appends to `gold/dq_score` + `gold/dq_profile`.

**Baseline / L5:**

- `kahn.py` — pin-driven baseline metrics (per-column completeness, date forms,
  curated plausibility registry).
- `validator.py` — HL7 validator_cli wrapper for L5 (`FHIRHOUSE_VALIDATOR_JAR`).

Open (FH-0004): scores **annotate** promotion (blocking = orchestrator gate);
profile push to OpenMetadata's profiler API is the warehouse-gov follow-up.
