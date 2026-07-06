# fhirHouse

**The governance, data-quality, and MDM layer for [fhirEngine](https://github.com/FHIRmedicConsulting/fhirEngine)'s medallion lakehouse.**

fhirHouse leverages fhirEngine's Delta tables to provide the services a production
FHIR data platform needs beyond storage and REST: **data governance, data-quality
scoring, profiling, and full data lineage**, plus **probabilistic + PPRL master
data management**.

fhirHouse is a fork of fhirEngine (Apache-2.0). It carries fhirEngine's code and
adds its own services in new top-level directories, pulling upstream improvements
via the `upstream` remote. See `CLAUDE.md` for the full working context and
decision record, and `docs/decisions/FH-*` for the fhirHouse ADRs.

## Where fhirHouse attaches

fhirEngine ships two storage topologies. fhirHouse treats them differently:

- **Medallion (Bronze→Silver→Gold)** — first-class. fhirHouse's governance, DQ,
  MDM, and lineage run on the **promotion seam** (fhirEngine ADR-0026): DQ scoring
  and Splink/PPRL matching execute Bronze→Silver→Gold, and cleaned/mastered data
  lands in the Gold tables the FHIR API serves.
- **Single store** — observability-only. No promotion tier exists to govern, so
  fhirHouse runs read-only: DQ profiling, conformance reporting, lineage and
  catalog. Adopting full governance means adopting medallion.

## Architecture (one paragraph)

DuckDB is the **read-side** analytical/DQ engine over fhirEngine's Delta tables;
**delta-rs remains the sole writer** (fhirEngine ADR-0026 §5). dbt-duckdb expresses
internal transforms and DQ tests; results are persisted through fhirEngine's writer.
Dagster orchestrates the heavier assets (DQ runs, Splink, PPRL, backfills,
human-in-the-loop review) and wraps — does not replace — fhirEngine's delta-rs
promotion loop. SQL-on-FHIR v2 ViewDefinitions (fhirEngine ADR-0027) remain the
externally published governed-view contract; dbt builds them.

## Status

Pre-scaffold. Foundational ADRs and module skeletons are in place; see
`CLAUDE.md` → "Backlog for Claude Code" for the build order. Run
`./bootstrap-fork.sh` on the host to establish the git fork.

## License & open-core boundary

Apache-2.0 (inherited from fhirEngine) — and this repo stays purely Apache-2.0
(FH-0001): every engine, table contract, CLI, and the base view pack is and remains
OSS, with a no-crippleware guarantee (full governance is always possible OSS-only).
Commercial surfaces (stewardship workbench, governance console, curated view packs,
managed hosting) live in a separate repo and integrate through the published
contracts. Licensed terminologies (SNOMED CT / LOINC / RxNorm) remain
operator-supplied and are never redistributed.
