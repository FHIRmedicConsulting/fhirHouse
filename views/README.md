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

## Robustness bar

Correctness is defined by the HL7 **`sql-on-fhir.js` shared JSON test suite** — run it
in CI, publish the report, register on the implementations page. Coverage target: 100%
of the suite; compile (not fallback) at least the full US Core base view set.

## TODO (Claude Code)
1. Implement the FHIRPath→DuckDB compiler (start with the taxonomy in the research
   note §6: choice types, forEach/forEachOrNull, collections, getResourceKey/
   getReferenceKey, extensions, unionAll, terminology filters).
2. Wire the `sql-on-fhir.js` test suite into CI.
3. Author the US Core base view pack (`condition`, `encounter`, `coverage`,
   `medication_request`, `procedure`, ...); the two here are seeds.
4. dbt macro that emits a dbt-duckdb model from a ViewDefinition.
