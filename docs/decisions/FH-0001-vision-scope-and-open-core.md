# FH-0001: fhirHouse Vision, Scope, and Open-Core Stance

- Status: **Accepted** (2026-07-06 — Chad confirmed **(b)**; boundary rule, carve-out
  table, and guarantees ratified in §2)
- Date: 2026-07-05 (stance confirmed 2026-07-06)
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

### 2. Open-core stance — **(b) OSS substrate, commercial UX on top** (CONFIRMED)

**The boundary rule** (buyer-based open core, applied per feature):

> If it **computes or persists** governed data → OSS.
> If it **renders, workflow-ifies, or curates** for a paying role → commercial.

| OSS forever (this repo, Apache-2.0) | Commercial (separate private repo/product) |
|---|---|
| All engines: DQ scoring, Splink/PPRL MDM, SoF-v2 view compiler, chunked promoter, Provenance bridge | **Stewardship workbench** — HITL UI over `patient_match_review` (side-by-side evidence, bulk approve, escalation, TTL queues — the UI ADR-0012 deferred to v2.x) |
| Every table contract + the contracts pin (the integration interface) | **Governance console** — DQ trending, threshold management, attestation / compliance report packs |
| CLIs, Dagster assets, OpenMetadata binding, the 146-view base pack | **Curated view packs** — HEDIS/eCQM quality measures, registries, de-identification |
| Docs, conformance suite, ADRs | Enterprise glue: SSO/RBAC, managed hosting, SLAs, support |

**Three guarantees** (binding on future scope decisions):

1. **No crippleware.** A complete governance deployment must always be possible
   OSS-only: stewards can work the review queue via SQL/API, DQ dashboards ship
   free through the OpenMetadata binding. Commercial products win by being
   better (healthcare-specific workflow), never by the OSS being lamed.
2. **Boundary is repo-level, not license-level.** This repo is purely Apache-2.0
   (it carries fhirEngine's license); no BSL/ELv2 files in-tree, ever. Commercial
   code lives in a separate private repo and integrates through the published
   table contracts — `contracts/gold_schema.snapshot.json` is its interface.
3. **DCO, no CLA.** This repo is never relicensed, so contributors keep their
   rights; lowest-friction contribution posture.

Rationale: (b) matches where healthcare buyers spend (stewardship/compliance
workflow, not algorithms — the Verato/NextGate lesson), matches the ecosystem
fhirHouse joined (OpenMetadata/Collate, DataHub/Acryl, Databricks/UC OSS), and is
the reversible choice — more can be open-sourced later; published code cannot be
re-closed. fhirEngine ADR-0023's paid-module earmark moves up-stack accordingly:
the *engines* it earmarked are OSS here; the paid surface is the workflow layer.

**Alternative (a) — fully OSS** was considered and declined 2026-07-06: it
optimizes for category dominance over a fundable product; monetization degrades
to services. Revisit only if strategy shifts from product to standards-flag.

### 3. Non-goals

- Not a second FHIR server; fhirHouse does not fork the REST/auth surface for its
  own use — it consumes fhirEngine's.
- Not a new EMPI; deterministic MPI already exists (ADR-0012). fhirHouse adds only
  the deferred probabilistic + PPRL lanes.
- Not a second write path; delta-rs remains the sole writer (FH-0003).

## Consequences

- Repo contents are gated by the boundary rule: engines/contracts/CLIs in-repo,
  workflow UX and curated packs out.
- The commercial repo consumes this one through the pinned contracts; drift tests
  protect that interface in both directions.
- Trademark "fhirHouse" (name/logo) should be registered — the license shares the
  code, not the brand.

## Open questions

- ~~Chad: confirm (a) or (b).~~ Confirmed (b), 2026-07-06.
- Naming/positioning vs the proprietary Ronin/Databricks sibling (ADR-0028).
