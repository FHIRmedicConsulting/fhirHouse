# FH-0004: Governance, DQ, MDM, and Lineage — Scope and Seams

- Status: **Accepted** (2026-07-06 — catalog = **OpenMetadata**, resolved by spike
  against the live 1,000-patient store; see §4)
- Date: 2026-07-05 (catalog decision 2026-07-06)
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

### 4. Governance / Catalog (`warehouse-gov/`) — **OpenMetadata** (decided)

Integrate a mature OSS catalog rather than build one, bound via fhirEngine's
catalog/governance seam (ADR-0025). **Decision: OpenMetadata**, chosen over DataHub
on three fhirHouse-specific grounds, then validated by spike:

1. **DQ is first-class**: fhirHouse's Kahn metrics map 1:1 onto OM test
   definitions/cases/results — a designed slot, not an adapter (DataHub's
   assertions are integration-oriented).
2. **Local-first survives**: OM = server + Postgres + Elasticsearch; DataHub adds
   Kafka + GMS — too heavy for fhirEngine's laptop-to-server deployment story.
3. **Unity Catalog conceptual alignment** (per Chad, 2026-07-06): OM's hierarchy is
   structurally 1:1 with UC. Convention codified in `fhirhouse_warehouse_gov`:
   *service = deployment · database = UC catalog · schema = medallion tier ·
   table = resource/governance table.* A Databricks deployment ingests via OM's
   native UC connector, so hybrid customers see one catalog with one shape.
   Unity Catalog OSS remains a candidate ADR-0025 *binding* underneath (metastore
   protocol), complementary to OM (governance/discovery UX) — not a competitor.

**Spike evidence** (2026-07-06, OM 1.13.1 quickstart vs the bulk_1k demo store):
76 tables registered UC-style with pin-derived FHIR column metadata, 48 tier-lineage
edges, 119 PHI columns classified (PII.Sensitive), and a real DQ run (155 Kahn
metrics) pushed as test results with OM evaluating pass/fail against a 0.95
threshold. Connector: `warehouse-gov/fhirhouse_warehouse_gov/openmetadata.py`
(REST, stdlib-only; bot-JWT auth for production).

DataHub stays possible at the ADR-0025 seam for customers who already run it —
a services integration, not the shipped default.

## Consequences

- fhirHouse depends on the external HL7 validator (JVM) for L5 — an operational
  dependency to package/document.
- MDM correctness depends on honoring ADR-0012 table contracts exactly; covered by
  `contracts/` drift-tests.

## Open questions

- ~~**OpenMetadata vs DataHub** — resolve with a spike.~~ Resolved: OpenMetadata (§4).
- DQ score schema is pinned (contracts `dq_score`); whether scores gate promotion
  (block vs annotate) remains open — currently annotate-only.
- dbt/Dagster lineage ingestion into OM (manifest-driven) — connector follow-up;
  tier lineage ships now via the REST binding.
