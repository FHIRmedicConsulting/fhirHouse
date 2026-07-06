# FH-0004: Governance, DQ, MDM, and Lineage — Scope and Seams

- Status: **Proposed** (catalog choice open; DQ/MDM/lineage scope accepted)
- Date: 2026-07-05
- Decider(s): Chad
- Related: fhirEngine ADR-0012 (MPI), ADR-0015 (validation), ADR-0025 (catalog/governance binding seam), ADR-0026 (promotion), ADR-0027 (SoF-v2)

## Context

fhirEngine already provides, pre-Bronze: structural + cardinality + terminology-
binding + L4 FHIRPath validation with dead-lettering (ADR-0015), and deterministic
MPI at promotion (ADR-0012). fhirEngine names its own gaps: **no full L5 IG
conformance** ("the authoritative profile verdict is the external HL7 validator")
and probabilistic/PPRL MDM deferred as "external-pipeline scope." fhirHouse fills
those gaps and adds scoring, profiling, lineage, and catalog binding — without
re-implementing what already exists.

## Decision

### 1. Data Quality (`dq/`)

- **Do not** re-do L1–L4 (fhirEngine owns it). fhirHouse scores what fhirEngine
  does not:
  - **L5 IG/profile conformance** via the external HL7 Java validator (closed/max
    slices, discriminators, must-support).
  - **Cross-record DQ** on the **Kahn framework** dimensions: *conformance,
    completeness, plausibility*, scored over populations, not single resources.
- DQ runs as a Bronze→Silver stage in medallion; as a read-only pass in single-store.
- Emits a versioned DQ score table (design in module README) consumed by the catalog.

### 2. MDM (`mdm/`)

- fhirHouse owns only the deferred lanes from ADR-0012: **Splink** (probabilistic)
  and **PPRL** (tokenization).
- Writes into the **existing** Gold MPI tables: `gold.patient_link`,
  `gold.patient_match_review`, `gold.patient_merge_history`, `gold.pprl_tokens`,
  `gold.mpi_decision_log`. Honors the two-stage flow (deterministic decides first;
  probabilistic only when deterministic doesn't) and the three-band thresholds
  (ADR-0012 §1–2). HITL review is surfaced via Dagster over `patient_match_review`.

### 3. Lineage (`lineage/`)

Two distinct things, both delivered:

- **Technical/asset lineage** — dbt model graph + Dagster asset graph (free from
  the tools), surfaced to the catalog.
- **Clinical provenance** — a bridge that emits/updates FHIR **Provenance**
  resources for governance transforms (MDM merges already write merge Provenance
  per ADR-0012 §5; extend the pattern to DQ/cleaning steps). Ties to fhirEngine's
  hash-chained audit (ADR-0016/0035).

### 4. Governance / Catalog (`warehouse-gov/`)

Integrate a mature OSS catalog rather than build one, bound via fhirEngine's
catalog/governance seam (ADR-0025). **Candidate: OpenMetadata** (native profiler +
DQ tests + glossary fit the DQ scope) vs **DataHub** (stronger discovery/lineage at
scale). **Decision deferred pending a short spike.**

## Consequences

- fhirHouse depends on the external HL7 validator (JVM) for L5 — an operational
  dependency to package/document.
- MDM correctness depends on honoring ADR-0012 table contracts exactly; covered by
  `contracts/` drift-tests.

## Open questions

- **OpenMetadata vs DataHub** — resolve with a spike.
- DQ score schema + how scores gate promotion (block vs annotate).
