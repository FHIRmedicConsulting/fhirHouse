# FH-0001: fhirHouse Vision, Scope, and Open-Core Stance

- Status: **Proposed** (open-core stance b is the working default; Chad to confirm a vs b)
- Date: 2026-07-05
- Decider(s): Chad
- Related: fhirEngine ADR-0008 (vision/scope), ADR-0023 (open-core), ADR-0027 (governed views)

## Context

fhirEngine is an OSS Delta-native FHIR R4 server, mature on its single-store
topology. Its ADR-0023 defines an **open-core** model and ADR-0027 §4 explicitly
earmarks the **Data Governance / Data Quality modules** as the natural home for the
*commercial paid surfaces*. fhirHouse proposes to build governance, DQ scoring,
profiling, lineage, and probabilistic MDM — i.e. the services those ADRs earmarked
for monetization — as an OSS project. That is a strategic collision that must be
resolved before scoping the repo, because it determines what is even allowed in it.

## Decision

### 1. Purpose

fhirHouse is the **medallion build-out and governance layer** for fhirEngine. It
provides, over fhirEngine's Delta tables: data governance, data-quality scoring,
data profiling, full data lineage, and the probabilistic + PPRL MDM lane that
fhirEngine ADR-0012 deferred as "external-pipeline scope."

### 2. Open-core stance — **(b) OSS substrate, commercial UX on top** (working default)

fhirHouse open-sources the **engines**: DQ scoring, lineage plumbing, data
profiling, and the Splink/PPRL MDM pipeline. The **commercial** surfaces remain:
curated SoF-v2 view-packs, the governance/stewardship UI, and managed hosting.

Rationale: (b) is the **reversible** choice. More can always be open-sourced later;
published code cannot be re-closed. It keeps fhirEngine's open-core thesis
(ADR-0023) intact while still delivering a usable OSS substrate.

**Alternative (a) — deliberate reversal:** governance + DQ go fully OSS; monetize
via hosting/support and the proprietary Ronin/Databricks sibling. If Chad selects
(a), only this ADR and the "commercial" carve-outs change; nothing downstream is
structurally affected.

### 3. Non-goals

- Not a second FHIR server; fhirHouse does not fork the REST/auth surface for its
  own use — it consumes fhirEngine's.
- Not a new EMPI; deterministic MPI already exists (ADR-0012). fhirHouse adds only
  the deferred probabilistic + PPRL lanes.
- Not a second write path; delta-rs remains the sole writer (FH-0003).

## Consequences

- Repo contents are gated by the stance above: engines in-repo, UX/view-packs out.
- If (a) is chosen, revise §2 and the commercial carve-outs; re-tag affected modules.

## Open questions

- **Chad: confirm (a) or (b).**
- Naming/positioning vs the proprietary Ronin/Databricks sibling (ADR-0028).
