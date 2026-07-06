# CLAUDE.md — fhirHouse

Working context for Claude Code (and humans) on this repo. Read this first.

## What fhirHouse is

fhirHouse is the **medallion build-out and governance layer** over
[fhirEngine](https://github.com/FHIRmedicConsulting/fhirEngine) — an OSS,
Delta-native FHIR R4 server. fhirEngine today is mature on its **single-store**
topology; its **medallion** topology (Bronze→Silver→Gold promotion, fhirEngine
ADR-0026) is sketched and only partially implemented. fhirHouse fleshes out the
medallion path and adds the services it needs: **data governance, data-quality
scoring, profiling, and full data lineage**, plus the probabilistic/PPRL MDM lane
that fhirEngine ADR-0012 explicitly deferred as "external-pipeline scope."

fhirHouse is a **fork** of fhirEngine: it carries fhirEngine's code (so CI/CD and
future upstream improvements flow in via the `upstream` remote) and adds all
fhirHouse work in **new top-level directories** that never touch `packages/server`,
keeping `git merge upstream/main` conflict-free.

## Locked decisions (design session 2026-07-05)

1. **Medallion-first.** Governance/DQ/MDM/lineage attach to the Bronze→Silver→Gold
   **promotion seam** (fhirEngine ADR-0026), which only exists in medallion mode.
   Single-store deployments get an **observability-only** subset — read-only DQ
   profiling, conformance reporting, lineage/catalog — because there is no
   promotion tier to govern. Full governance ⇒ medallion. See `FH-0002`.
2. **Open-core stance (b): OSS substrate, commercial UX on top.** fhirHouse
   open-sources the *engines* — DQ scoring, lineage plumbing, profiling, MDM
   pipeline. Curated view-packs, governance UI, and stewardship UX stay
   commercial. This is the *reversible* default (fhirEngine ADR-0023/0027 had
   earmarked Governance+DQ as the paid modules). Revisit in `FH-0001` if the
   strategy flips to fully-OSS. **Chad to confirm (a) vs (b).**
3. **Compute engine: DuckDB read-side only; delta-rs is the sole writer.** DuckDB +
   dbt run SQL/DQ/transform logic over Delta; results are persisted by fhirEngine's
   existing **delta-rs** writer (honors ADR-0026 §5 — one writer per table). This
   narrowly amends ADR-0026 §1 ("no second query engine") to allow DuckDB as a
   *read-side* analytical engine. See `FH-0003`.
4. **dbt vs SoF-v2 split.** dbt-duckdb owns **internal** transforms + DQ-test
   models. SoF-v2 ViewDefinitions (fhirEngine ADR-0027) remain the **externally
   published** governed-view contract. dbt builds; SoF-v2 defines the public shape.
5. **MDM = Splink + PPRL only.** fhirEngine ADR-0012 already implements
   deterministic MPI at promotion (`gold.patient_link` / `patient_match_review` /
   `patient_merge_history` + merge Provenance + survivor reference-rewrite).
   fhirHouse adds the deferred **probabilistic (Splink)** and **PPRL** lanes,
   writing into those *existing* Gold tables. Do **not** reinvent the EMPI or the
   table schemas.
6. **Orchestration: Dagster wraps, does not replace.** fhirEngine's delta-rs
   poll-loop promoter (ADR-0026 §6) keeps running. Dagster orchestrates the heavier
   fhirHouse assets (DQ runs, Splink, PPRL, backfills, HITL review) with asset
   lineage.

## Invariants (do not break)

- **Additive-only over upstream.** All fhirHouse code lives in `warehouse-gov/`,
  `dbt/`, `dagster/`, `mdm/`, `dq/`, `lineage/`, `contracts/`, `views/`, and
  `docs/decisions/FH-*` (+ `docs/research/` notes dated by fhirHouse sessions).
  Never edit files owned by fhirEngine `upstream` — it breaks conflict-free merges.
- **delta-rs is the only writer.** Nothing in fhirHouse writes Delta directly; hand
  result sets to fhirEngine's writer/sidecar.
- **Honor the Gold contract.** MDM/cleaning output must land in fhirEngine's
  clean-room flattener columnar layout as valid FHIR (ADR-0022/0024). `contracts/`
  pins that schema and CI drift-tests it.

## Module map

| Dir | Purpose | Extends |
|-----|---------|---------|
| `contracts/` | Pinned fhirEngine Gold/flattener schema + drift-test (the concrete "CI/CD pulls from fhirEngine") | ADR-0022/0024 |
| `dbt/` | dbt-duckdb project: staging over Bronze/Silver, DQ-test models; delta-rs persists | ADR-0026/0027 |
| `dagster/` | Assets orchestrating DQ, Splink, PPRL, backfills, HITL; wraps the promoter | ADR-0026 §6 |
| `mdm/` | Splink probabilistic + PPRL → existing MPI Gold tables | ADR-0012 (deferred lane) |
| `dq/` | DQ scoring: Kahn dimensions + IG conformance via HL7 validator (the L5 gap fhirEngine names) | ADR-0015 validation |
| `lineage/` | Technical lineage (dbt/Dagster asset graph) + FHIR Provenance bridge + catalog binding | ADR-0025 |
| `warehouse-gov/` | Catalog/governance binding — OpenMetadata, UC-aligned naming (FH-0004) | ADR-0025 |
| `views/` | SQL-on-FHIR v2 ViewDefinitions + FHIRPath→DuckDB compiler (FH-0005; the published governed-view contract) | ADR-0027 |

## Backlog for Claude Code

Done (commit `f42e252`, 2026-07-06): fork bootstrap · `contracts/` pin +
`drift_test.py` + `fhirhouse_contracts` seam package · `dq/` Kahn scoring + HL7
validator wrapper · `mdm/` Splink-on-DuckDB + guardrails + PPRL · `dagster/` assets
+ HITL sensor · `lineage/` Provenance bridge · dbt staging/marts · CI (drift test,
pytest, dbt parse, ruff). Run tests with `.venv/bin/pytest`; re-pin after upstream
merges with `python contracts/pin_schema.py`.

Remaining:

1. Add an `origin` remote and push (`gh repo create <you>/fhirHouse --private
   --source=. --remote=origin --push`).
2. `views/`: grow the base view pack (coverage, procedure, immunization, ...) and
   add `memberOf()` terminology filters via fhirEngine's terminology service
   (ADR-0017). The compiler itself is DONE (FH-0005 Accepted): 144/144 on the
   official shared suite, fully compiled; regenerate models with
   `python -m fhirhouse_views.dbt_gen`, conformance with
   `python -m fhirhouse_views.conformance`.
3. `warehouse-gov/`: DONE for v0 — FH-0004 resolved as OpenMetadata (UC-aligned
   naming; spike-validated; `fhirhouse_warehouse_gov.openmetadata` CLI). Remaining:
   dbt/Dagster manifest-driven lineage ingestion into OM; glossary seeding.
4. Close open decisions: FH-0001 (open-core a/b) — the last one.

## fhirEngine ADRs to read (in `docs/decisions/` after bootstrap)

ADR-0011 write contract · ADR-0012 MPI · ADR-0022/0024 flattening & storage ·
ADR-0023 open-core · ADR-0026 medallion promotion · ADR-0027 SoF-v2 governed views.
