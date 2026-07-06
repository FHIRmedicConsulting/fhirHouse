# views/ — SQL-on-FHIR v2 view layer

The governed, portable view layer for fhirHouse. See
`../docs/decisions/FH-0005-sql-on-fhir-view-layer.md` and the backing analysis
`../docs/research/2026-07-06-sql-on-fhir-view-layer.md`.

## Model

- `definitions/*.ViewDefinition.json` — HL7 **SQL-on-FHIR v2 ViewDefinition** JSON.
  This is the **contract**: portable, versioned, engine-neutral. The only source
  artifact. (No engine-specific view SQL is hand-written — the anti-Microsoft lesson.)
- `compiled/*.duckdb.sql` — **generated** illustration of what the compiler lowers a
  ViewDefinition into (native DuckDB SQL). Not hand-maintained.

## Execution (FH-0005)

Compile ViewDefinition → one DuckDB `SELECT`:
- **fast path** — FHIRPath that maps to a clean-room-flattened Silver column (ADR-0024)
  references the column directly;
- **fallback** — arbitrary paths extract from `body_json` with DuckDB JSON functions;
- **escape hatch** — expressions the compiler can't lower call fhirEngine's FHIRPath
  engine (`packages/server/src/lib/fhirpath-model.ts`). Never silently drop — fail
  loud or fall back.

delta-rs materializes results to Gold (DuckDB computes, delta-rs writes — FH-0003);
CDF version-windowed refresh (ADR-0026). Single-store: read-only engine views only.

## Robustness bar — met

Correctness is defined by the official **shared JSON test suite**, vendored under
`conformance/suite/` and run in CI (`views/tests/test_conformance.py`). Current
status: **144/144 pass, fully compiled, zero interpreter fallbacks** — see
`conformance/REPORT.md`. `conformance/expected_pass.json` is the regression gate;
regenerate both with `python -m fhirhouse_views.conformance`.

## Implementation (`fhirhouse_views/`)

- `fhirpath.py` — restricted FHIRPath parser (the SoF subset; anything else fails loud).
- `compiler.py` — ViewDefinition → one DuckDB SELECT. Collections are `JSON[]` with
  FHIRPath flattening (`sof_*` macros); `forEach`/`forEachOrNull` → LATERAL unnest
  with iteration ordinals (`%rowIndex`); `unionAll` → LATERAL union; `repeat` →
  depth-first bounded unroll; boundary functions dispatch on the FHIR model type
  from `contracts/gold_schema.snapshot.json`. Fidelity mode (JSON-exact, for the
  suite) and typed mode (native casts, for dbt/BI).
- `runner.py` — execute over in-memory resources or a Delta tier (read-side DuckDB).
- `conformance.py` — suite runner + report + CI manifest.
- `dbt_gen.py` — regenerates `dbt/models/views/*.sql` and `compiled/*.duckdb.sql`
  from `definitions/`; the SoF macros install via dbt's on-run-start hook.

## Remaining

- Grow the base pack (coverage, procedure, immunization, allergy_intolerance, ...).
- `memberOf()` terminology filters via fhirEngine's terminology service (ADR-0017).
- Register on the SoF implementations page once the repo is public.
