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

- `kahn.py` — pure metric functions driven by the pinned flattener schema
  (completeness per column, required-element/binding/date-form conformance,
  plausibility rule registry). Row shape pinned in contracts (`dq_score`).
- `validator.py` — HL7 validator_cli wrapper for L5 (operator supplies the jar via
  `FHIRHOUSE_VALIDATOR_JAR`); emits the same MetricResult stream.
- `runner.py` — reads a tier read-side (delta-rs), scores, appends to
  `gold/dq_score` via the sidecar. Called by the `dq_scores` Dagster asset.

Open (FH-0004): scores currently **annotate** promotion; blocking would be a gate in
the orchestrator reading `dq_score`.
