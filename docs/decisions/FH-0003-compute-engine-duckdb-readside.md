# FH-0003: Compute Engine — DuckDB Read-Side, delta-rs Sole Writer

- Status: **Accepted** (2026-07-05) — narrowly amends fhirEngine ADR-0026 §1 for fhirHouse
- Date: 2026-07-05
- Decider(s): Chad
- Related: fhirEngine ADR-0026 (one engine; one writer per table), ADR-0022 (delta-rs single writer), ADR-0024 (flattener), ADR-0027 (SoF-v2 views)

## Context

fhirEngine ADR-0026 §1 ratifies "**one engine** — the delta-rs/DataFusion engine
does all writes, all promotion, and serves reads. No Spark, no DLT, **no second
query engine**," and §5 the invariant "**one writer per Delta table**." fhirHouse
wants DuckDB + dbt for SQL/DQ/transform ergonomics (dbt-duckdb is mature; there is
no comparable DataFusion dbt adapter). Chad's framing: "DuckDB = the
Databricks-equivalent; DuckDB queries, fhirEngine's writers write the data."

DuckDB's Delta support is **read-only** (delta-kernel based); it cannot write Delta.
This is compatible with — in fact reinforces — the sole-writer invariant.

## Decision

### 1. DuckDB is a read-side analytical / DQ engine only

DuckDB reads fhirEngine's Delta tables (Bronze/Silver/Gold) to run SQL checks, DQ
scoring, profiling, and dbt-expressed transforms. It **never writes Delta**.

### 2. delta-rs remains the sole writer

All persistence goes through fhirEngine's existing delta-rs writer / Python sidecar.
fhirHouse hands it result sets (Arrow / Parquet / row batches); the writer performs
the MERGE-keyed-on-FHIR-id commit. ADR-0026 §5 (one writer per table) is preserved
exactly.

### 3. Narrow amendment to ADR-0026 §1

fhirHouse permits DuckDB as a **second, read-only query engine** alongside
DataFusion. The prohibition on a second *write/promotion* engine stands: there is
still exactly one writer (delta-rs) and one promotion mechanism (ADR-0026's CDF
loop). This amendment is fhirHouse-scoped and does not change fhirEngine core.

### 4. dbt vs SoF-v2 boundary

dbt-duckdb owns **internal** transforms and DQ-test models. SoF-v2 ViewDefinitions
(ADR-0027) remain the **externally published** governed-view contract. dbt may
materialize SoF-v2 views, but the ViewDefinition remains the authoritative public
tabular shape.

## Consequences

- Two read engines (DataFusion in the server, DuckDB in fhirHouse) — accept the
  operational cost for dbt ergonomics.
- The DuckDB→delta-rs handoff is a defined interface; keep it thin and typed.
- If dbt gains a production-grade DataFusion adapter, revisit whether DuckDB is
  still warranted.

## Open questions

- Exact handoff format (Arrow IPC vs Parquet staging) — decide with the sidecar API.
