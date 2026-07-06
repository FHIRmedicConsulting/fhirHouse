# FH-0002: Topology Support — Medallion-First, Single-Store Observability-Only

- Status: **Accepted** (2026-07-05)
- Date: 2026-07-05
- Decider(s): Chad
- Related: fhirEngine ADR-0010 (storage shape), ADR-0026 (medallion promotion), ADR-0012 (MPI at promotion)

## Context

fhirEngine supports two install-time storage topologies
(`FHIRENGINE_STORAGE_MODE`):

- **single** — one Delta store, read-after-write; the API writes and serves the
  same store. No promotion tiers.
- **medallion** — Bronze→Silver→Gold; the API ingests to Bronze and serves from
  Gold; an external promoter moves data between tiers (ADR-0026).

fhirHouse's governance, DQ-at-promotion, and MDM-at-promotion all need a
**promotion seam** to attach to. That seam exists only in medallion. Chad's design
intent ("same Gold the API serves") also only has a referent in medallion, where a
distinct Gold tier exists.

## Decision

### 1. Medallion is the first-class target

fhirHouse's full feature set — DQ scoring, Splink/PPRL MDM, cleaning, lineage
capture, governed marts — runs on the Bronze→Silver→Gold promotion path. Cleaned
and mastered data lands in the Gold tables the FHIR API serves, honoring the
fhirEngine flattener Gold contract (ADR-0022/0024; see `contracts/`).

### 2. Single-store gets an observability-only subset

With no promotion tier to govern, fhirHouse runs **read-only** against a single
store: DQ profiling, IG-conformance reporting, data profiling, and lineage/catalog
population. It performs **no mutation, no golden-record rewrite**. Adopting full
governance in a single-store deployment means migrating to medallion.

### 3. One codebase, capability-gated by topology

Modules detect topology and expose only the supported surface; the observability
subset is a strict subset of the medallion feature set (no separate code path for
the read-only features).

## Consequences

- Docs and onboarding must state the single-store limitation plainly (not a
  degraded-but-equivalent mode — a strict read-only subset).
- Any feature that mutates data is medallion-gated at the module boundary.

## Open questions

- Whether to offer a guided single→medallion migration as a fhirHouse capability.
