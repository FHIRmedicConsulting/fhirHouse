# fhirHouse ADR Index

fhirHouse decisions carry an `FH-` prefix to coexist with fhirEngine's `NNNN-`
ADRs (0001–0036) in the same `docs/decisions/` directory after the fork bootstrap.

| ADR | Title | Status |
|-----|-------|--------|
| FH-0001 | Vision, Scope, and Open-Core Stance | Accepted (stance b: OSS substrate, commercial UX) |
| FH-0002 | Topology Support — Medallion-First | Accepted |
| FH-0003 | Compute Engine — DuckDB Read-Side, delta-rs Sole Writer | Accepted |
| FH-0004 | Governance, DQ, MDM, and Lineage — Scope and Seams | Accepted (catalog = OpenMetadata, UC-aligned) |
| FH-0005 | SQL-on-FHIR v2 View Layer — Compile to DuckDB over Delta | Accepted (144/144 shared suite) |

Research notes live in `../research/`. See `../../CLAUDE.md` for working context.
