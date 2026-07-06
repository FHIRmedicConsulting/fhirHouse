# Deep Dive: Robust SQL Views over FHIR — Prior Art and the fhirHouse View Layer

- Date: 2026-07-06
- Author: Chad (with research assist)
- Feeds: `FH-0005` (view-layer ADR), fhirEngine `ADR-0027` (governed views), `FH-0002/0003`
- Status: research note → decision in FH-0005

## 1. The problem

FHIR resources are deeply nested JSON with polymorphic (`value[x]`) elements,
repeating elements (`name`, `address`, `identifier`, `telecom`), references, and
extensions. Analysts want **flat tables**. The whole job of a "view layer" is to
turn nested FHIR into stable, documented, tabular projections that a SQL engine and
BI tools can consume — without every analyst re-learning FHIRPath and re-deriving
the same joins.

There are two things people conflate and shouldn't (fhirEngine ADR-0022/0024 vs
0027):

- **Canonical flattening / storage** — how resources are physically stored columnar
  (fhirEngine's clean-room flattener owns this; it is *not* the view layer).
- **Consumer-facing views** — named, versioned tabular contracts published to
  analysts on top of storage. That is this document.

## 2. Prior art

### 2.1 Microsoft — FHIR Analytics Pipelines *(archived Jan 2025)*

Two tools: **FhirToDataLake** (pull via FHIR API → hierarchical Parquet in ADLS; a
PowerShell script generates **external tables + views in Synapse Serverless SQL**
pointing at the Parquet) and **FhirToCdm** (config-file-driven flatten to Common
Data Model CSV → Synapse dedicated SQL). Views were **T-SQL over a Microsoft-defined
schema**.

Lessons (mostly cautionary):

- The repo is **archived**; Microsoft now points users at **Fabric healthcare data
  solutions** (a Delta lakehouse with bronze/silver/gold + OMOP). The bespoke-schema
  + Synapse-SQL approach was a maintenance dead-end.
- **Engine-locked**: views were Synapse T-SQL. Portability was zero — you couldn't
  lift those views to DuckDB/Spark/BigQuery.
- **Pre-standard**: it predated SQL-on-FHIR v2, so its flattening/view schema was
  proprietary. Anyone adopting it inherited a non-portable contract.
- **Takeaway for fhirHouse:** do **not** bind views to one engine's SQL dialect or a
  bespoke schema. Bind to a portable, standard contract; generate engine SQL from it.

### 2.2 Google — FHIR Data Pipes / Open Health Stack *(active; now OHS Foundation)*

Architecture: **Apache Beam ETL** extracts from any FHIR server → **Parquet-on-FHIR
schema** (a Bunsen/Cerner-derived columnar mapping, documented in `doc/schema.md`) as
the "base warehouse" → a **View Layer** producing flat views two ways:

1. **SQL virtual views** authored outside the pipeline, and
2. **SQL-on-FHIR v2 `ViewDefinition`** resources materialized *inside* the pipeline,
   output to **Parquet or DB tables**.

It ships **predefined views** for common resources (extensible), plus **query-engine
connectors** (Spark SQL / Thrift, single-node or distributed).

Lessons (mostly to emulate):

- **Standard contract**: ViewDefinitions are the portable authoring surface. Right
  call — this is the industry convergence point.
- **Predefined view packs**: ship base views so users get value on day one. Emulate.
- **Two materialization modes** (virtual vs materialized). Emulate.
- **But**: it's **Java/Beam/Spark + Parquet**, and its runtime evaluates FHIRPath
  **per resource** (a Beam `DoFn` applies the view row-by-row). That's portable but
  it does **not** exploit a columnar engine, and Parquet (not Delta) means no ACID /
  no CDF-incremental refresh. That's precisely where fhirHouse's stack differs.

### 2.3 The standard — SQL-on-FHIR v2 (HL7 `ViewDefinition`)

An HL7 IG (STU, CC0). A **`ViewDefinition`** is itself a FHIR resource that defines a
portable tabular projection using **FHIRPath** expressions. Core structure:

- `resource` — the resource type the view runs over (e.g. `Patient`).
- `select[]` — each with `column[]` and optional `forEach` / `forEachOrNull`
  (unnest a collection: inner vs outer-join semantics), nested `select[]`, and
  `unionAll[]` (stack heterogeneous rows).
- `column` — `{ name, path (FHIRPath), type?, collection?, description?, tag? }`.
  `collection: true` yields an array column.
- `where[]` — FHIRPath boolean row filters.
- `constant[]` — named constants referenced as `%name` inside FHIRPath.
- Helper functions: **`getResourceKey()`** and **`getReferenceKey([type])`** produce
  stable join keys (the mechanism that makes cross-view joins work).

Reference implementation `sql-on-fhir.js` (JS) + a **shared JSON test suite** +
interactive playground + an **implementations page** you can register against. The
test suite is the objective definition of "robust" — passing it is the bar.

## 3. Comparison

| Dimension | MS (archived) | Google FHIR Data Pipes | SoF v2 spec | **fhirHouse (proposed)** |
|---|---|---|---|---|
| Authoring contract | Bespoke schema / T-SQL | **ViewDefinition** | **ViewDefinition** | **ViewDefinition** |
| Portability | Engine-locked (Synapse) | High | High (by design) | High (compile per-engine) |
| Runtime | T-SQL over Parquet | Per-resource FHIRPath (Beam) | Reference: per-resource JS | **Compile to native DuckDB SQL** (+ FHIRPath fallback) |
| Storage | Parquet (ADLS) | Parquet | agnostic | **Delta** (ACID, CDF) |
| Compute | Synapse | Beam/Spark, JVM | agnostic | **DuckDB read-side; delta-rs writes** (FH-0003) |
| Incremental refresh | No | Batch reprocess | n/a | **CDF version-windowed** (ADR-0026) |
| Predefined views | Some | **Yes** | n/a | **Yes, US-Core-aligned** |
| Conformance-tested | No | Registered impl | Test suite | **Run the shared suite; register** |
| Status | Dead | Active | STU | greenfield |

## 4. The core decision: **interpret** vs **compile**

Two ways to execute a ViewDefinition:

- **Interpret (per-resource)** — for each resource object, evaluate each column's
  FHIRPath and emit rows. This is what `sql-on-fhir.js` and Google's Beam runner do.
  Simple, spec-faithful, easy to pass the test suite — but it processes JSON
  object-by-object and ignores the columnar engine. Slow at population scale.
- **Compile (set-based)** — translate the ViewDefinition into **one native SQL
  statement** over columnar storage: `forEach` → `UNNEST` + `LATERAL`; `where` →
  `WHERE`; `column` paths → column refs or `json_extract`; `constant` → literals;
  `getResourceKey`/`getReferenceKey` → deterministic key expressions. Fast, uses the
  engine's optimizer, and the output *is* a SQL view/table. Harder, because full
  FHIRPath doesn't all map cleanly to SQL.

fhirEngine ADR-0027 chose the **interpret** path (pure-TS runner, `sof-js` +
`fhirpath` npm) — a reasonable default for a TS server with no columnar engine.
**fhirHouse has DuckDB and Delta (FH-0003)**, so it should take the **compile** path
and treat the TS interpreter as a *conformance oracle / fallback*, not the runtime.

## 5. fhirHouse approach (recommended → FH-0005)

**ViewDefinitions are the contract; a compiler turns them into native DuckDB SQL over
Delta; delta-rs materializes; CDF refreshes incrementally; the HL7 test suite proves
correctness.** Concretely:

1. **Author** views as SoF v2 `ViewDefinition` JSON (versioned governance artifacts
   in `views/definitions/`). This is the portable, engine-neutral public contract —
   the anti-Microsoft lesson.
2. **Compile** each ViewDefinition to a DuckDB `SELECT`:
   - **Fast path** — when a FHIRPath maps to a clean-room-flattened Silver column
     (ADR-0024), reference the column directly (no JSON parsing).
   - **Fallback path** — for arbitrary paths, extract from `body_json` with DuckDB
     JSON functions (`->`, `->>`, `UNNEST(CAST(... AS JSON[]))`).
   - **FHIRPath escape hatch** — for expressions the compiler can't lower (rare
     functions, `memberOf`), call fhirEngine's existing FHIRPath engine
     (`packages/server/src/lib/fhirpath-model.ts`) as a DuckDB UDF or a
     pre-materialized staging column. This is what makes it *robust* rather than
     "works for the easy 80%."
3. **Materialize** via delta-rs (DuckDB computes, delta-rs writes — FH-0003) into
   Delta view tables in Gold; **or** expose as DuckDB/DataFusion views for ad hoc.
   Refresh incrementally with **CDF version windows** (ADR-0026), full-rebuild as the
   backstop.
4. **dbt integration** — each compiled view is a dbt-duckdb model (a dbt macro
   compiles the ViewDefinition), so materialization strategy, tests, and lineage come
   from dbt for free (FH-0003 §4). SoF v2 remains the *published* contract; dbt is the
   *build tool*.
5. **View packs** — ship US-Core-aligned base views (`patient_demographics`,
   `observation_flat`, `condition`, `encounter`, `coverage`, `medication_request`,
   `procedure`, …), mirroring Google's predefined views and fhirEngine's US Core
   focus. **Open-core (FH-0001 b):** the compiler + base packs are OSS; curated
   quality-measure / registry / de-identified view packs are the commercial surface
   (aligns with fhirEngine ADR-0027 §4).
6. **Conformance** — run the `sql-on-fhir.js` **shared JSON test suite** against the
   compiler in CI; publish a test report; register on the implementations page. This
   is the objective "robust" bar and the marketing proof.

## 6. Robustness taxonomy — the cases that break naïve view generators

This is the checklist the compiler and its test coverage must hit. Each maps to a
concrete FHIRPath/SoF construct.

| Hard case | FHIR/FHIRPath shape | Compiler handling |
|---|---|---|
| **Choice types** `value[x]` | `value.ofType(Quantity).value` | `ofType()` selects the concrete flattened column / `body_json ->> '$.valueQuantity.value'` |
| **Repeating elements** | `name`, `address`, `identifier`, `telecom` | `forEach`/`forEachOrNull` → `UNNEST` + inner/outer `LATERAL` |
| **Collection columns** | `name.given` (array) | `collection:true` → DuckDB `VARCHAR[]` via `CAST(... AS VARCHAR[])` |
| **References → keys** | `subject.getReferenceKey(Patient)` | parse `Patient/123` → `123`; type-filtered join key |
| **Resource keys** | `getResourceKey()` | stable id expression aligned to the Delta partition key |
| **Extensions** | `extension.where(url=%u).value.ofType(...)` | `where` on `url` + typed value extraction from the extension array |
| **Nested unnest** | `forEach: contact` then nested `select` | correlated `LATERAL` chains |
| **Heterogeneous rows** | `unionAll` | `UNION ALL` of compiled sub-selects with a common column set |
| **Null / empty semantics** | `forEach` vs `forEachOrNull` | `CROSS`/inner vs `LEFT` join — different row counts; test both |
| **Terminology filters** | `where(code.memberOf(%vs))` | call fhirEngine terminology `$validate-code` / value-set expansion (ADR-0017) |
| **Primitive extensions** | `_birthDate.extension...` | sibling `_element` handling in the JSON model |
| **Type coercion** | FHIRPath date/dateTime/decimal | explicit `CAST`; preserve precision; UTC normalization |
| **Determinism** | stable output for joins/diffs | ordered keys; no reliance on JSON member order |

If the compiler can't lower one of these, it must fall back to the FHIRPath engine
rather than silently drop or mis-project — **fail loud or fall back, never guess.**

## 7. Worked example

See `views/definitions/patient_demographics.ViewDefinition.json` and its illustrative
compile target `views/compiled/patient_demographics.duckdb.sql`, plus
`views/definitions/observation_flat.ViewDefinition.json` (demonstrates
`getReferenceKey`, `ofType(Quantity)`, and `forEach code.coding`). The Patient view
exercises `forEachOrNull` (official name, home address, MRN identifier), a collection
column (`given`), and a choice type (`deceased[x]`).

## 8. Topology behavior (FH-0002)

- **Medallion** — views **materialize** to Delta in Gold via delta-rs; CDF-incremental
  refresh; served to BI. Full feature set.
- **Single store** — views are **read-only DuckDB/DataFusion views** over the single
  store; no materialization, no delta-rs writes. Observability subset only.

## 9. Open questions

- Materialized-Delta vs on-the-fly engine views per consumer (freshness vs cost) —
  ADR-0027's open question; decide per view pack.
- How much FHIRPath to compile vs push to the engine fallback — measure against the
  test suite; set a coverage target (e.g. 100% of the shared suite, compile ≥ the US
  Core view set).
- Whether view-pack governance metadata (owner, PHI class, refresh SLA) lives in the
  ViewDefinition `tag`/extensions or the catalog (warehouse-gov / FH-0004).
- SoF v2 version pinning (v2.0.0 vs the moving `latest`) and re-running conformance on
  spec bumps.

## 10. References

- Microsoft FHIR Analytics Pipelines (archived): https://github.com/microsoft/FHIR-Analytics-Pipelines
- Google/OHS FHIR Data Pipes: https://github.com/ohs-foundation/fhir-data-pipes ·
  overview https://developers.google.com/open-health-stack/fhir-analytics ·
  view layer https://developers.google.com/open-health-stack/fhir-analytics/view-layer ·
  Parquet-on-FHIR https://developers.google.com/open-health-stack/fhir-analytics/parquet-on-fhir
- SQL-on-FHIR v2 IG: https://sql-on-fhir.org/ig/latest/ · source https://github.com/HL7/sql-on-fhir ·
  reference impl + test suite https://github.com/FHIR/sql-on-fhir.js
- fhirEngine ADR-0027 (governed views), ADR-0024 (flattener), ADR-0026 (promotion/CDF).
