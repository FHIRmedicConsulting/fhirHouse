# FH-0005: SQL-on-FHIR v2 View Layer — Compile to DuckDB over Delta

- Status: **Proposed** (2026-07-06)
- Date: 2026-07-06
- Decider(s): Chad
- Extends/refines: fhirEngine **ADR-0027** (governed views — execution model changed from interpret to compile)
- Related: FH-0002 (topology), FH-0003 (DuckDB read-side / delta-rs writer), FH-0001 (open-core), fhirEngine ADR-0024 (flattener), ADR-0026 (CDF), ADR-0017 (terminology)
- Backing analysis: `docs/research/2026-07-06-sql-on-fhir-view-layer.md`

## Context

fhirHouse needs robust, portable SQL views over FHIR. Prior art: Microsoft's FHIR
Analytics Pipelines is **archived** and was engine-locked (Synapse T-SQL over a
bespoke schema) — a cautionary tale. Google's FHIR Data Pipes is active and
standard-based (**SQL-on-FHIR v2 `ViewDefinition`**, predefined view packs) but is
Java/Beam/Spark + Parquet and evaluates FHIRPath per-resource. The HL7 SoF v2 spec is
the industry convergence point and the one fhirEngine ADR-0027 already adopted.

ADR-0027 chose a **pure-TS interpreter** (`sof-js` + `fhirpath` npm) running FHIRPath
per resource. fhirHouse's stack (DuckDB read-side + Delta + delta-rs writer, FH-0003)
makes a **compile-to-SQL** execution model both possible and preferable.

## Decision

### 1. ViewDefinition is the contract

Views are authored as SoF v2 `ViewDefinition` JSON, versioned in `views/definitions/`.
This is the portable, engine-neutral public contract. No engine-specific view SQL is a
source artifact (anti-Microsoft lesson).

### 2. Execution = compile to native DuckDB SQL (not interpret)

A compiler lowers each ViewDefinition to one DuckDB `SELECT`:

- **Fast path**: FHIRPath → clean-room-flattened Silver columns (ADR-0024) where the
  path maps to one.
- **Fallback path**: `body_json` via DuckDB JSON functions for arbitrary paths.
- **FHIRPath escape hatch**: expressions the compiler can't lower call fhirEngine's
  FHIRPath engine (`fhirpath-model.ts`) as a UDF / pre-materialized column. Never
  silently drop or mis-project — **fail loud or fall back**.

The ADR-0027 TS interpreter is retained as a **conformance oracle and fallback**, not
the runtime.

### 3. Materialization

delta-rs writes materialized view tables to Gold (DuckDB computes, delta-rs writes —
FH-0003 §2); refresh is **CDF version-windowed** with full-rebuild backstop (ADR-0026).
Alternatively expose on-the-fly DuckDB/DataFusion views (freshness vs cost, per view).

### 4. Topology (FH-0002)

Medallion: materialize to Delta Gold. Single-store: read-only engine views, no
materialization.

### 5. dbt integration

Each compiled view is a dbt-duckdb model (dbt macro compiles the ViewDefinition), so
materialization, tests, and lineage come from dbt. SoF v2 = published contract; dbt =
build tool (FH-0003 §4).

### 6. View packs + open-core (FH-0001 b)

Ship US-Core-aligned base view packs. Compiler + base packs are **OSS**; curated
quality-measure / registry / de-identified packs are the **commercial** surface
(aligns with ADR-0027 §4).

### 7. Conformance is the definition of "robust"

Run the `sql-on-fhir.js` **shared JSON test suite** in CI; publish a report; register
on the SoF implementations page. Coverage target: 100% of the shared suite; compile
(not fallback) at least the full US Core base view set.

## Consequences

- A FHIRPath→SQL compiler is real, non-trivial engineering; the robustness taxonomy
  (research note §6) is the test matrix.
- Two FHIRPath implementations coexist (compiler lowering + TS oracle) — they must
  agree; the shared test suite enforces it.
- Portability is preserved: the ViewDefinition runs on any conformant engine; fhirHouse
  just compiles it to a fast one.

## Open questions

- Compile-coverage vs engine-fallback boundary (measure on the suite).
- Materialized vs virtual per view pack.
- Governance metadata location: ViewDefinition `tag` vs catalog (FH-0004).
- SoF v2 version pinning + re-conformance on spec bumps.
