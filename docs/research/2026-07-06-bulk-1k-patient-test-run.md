# 1,000-Patient End-to-End Test Run — full stack over Synthea bulk_1k

- Date: 2026-07-06
- Corpus: Synthea `bulk_1k` (1,127 patient bundles + 2 seed bundles, **1,828,315
  resources**, 24 resource types, ~4.8 GB JSON)
- Stack: fhirEngine sidecar + server (medallion mode) on `~/fhirhouse-demo/delta`;
  every fhirHouse lane exercised over real data.

## What ran, with numbers

| Stage | Result | Time |
|---|---|---|
| Bronze bulk load (batched sidecar appends; urn:uuid + conditional refs resolved) | 1,828,315 resources, **0 unresolved refs** | **91 s** (~20k res/s) |
| Promotion (`fhirengine-promote`, per type) | 19/24 types → Silver+Gold (442k Silver rows); +3 types Gold-only; Patient MPI ran (5,182 `patient_link` rows, 0 dupes in Synthea) | seconds–10 s per type |
| DQ (Kahn) over Patient/Encounter/Condition/MedRequest/**Observation (771k)** | 155 metric rows → `gold/dq_score`; Synthea scores ~1.0 across dimensions | **20 s** |
| Splink (trained on the real 1,127) + banding | 1 candidate pair scored → **hard-deny (SSN conflict) correctly blocked**, logged to `mpi_decision_log`, nothing queued | ~2 s + 1.2 s train |
| PPRL | 2,254 tokens (hmac + CLK) → `gold/pprl_tokens` | 0.7 s |
| SoF compiled views over Gold | patient_demographics 1,127 · condition_flat 50,651 · encounter_flat 76,192 · medication_request_flat 110,470; cross-view joins work | ms–5 s |
| dbt | `stg_patient_current`, `dq_score_latest` built; views persisted into `fhirhouse.duckdb` | — |
| FHIR API (medallion, serving Gold) | `GET /Patient/{id}` and `/Condition/{id}` → 200 in ~250 ms | — |

## Findings (each one actionable)

1. **The batch Bronze lane is fast**: ~20k resources/s through the sidecar vs the
   transaction-bundle path that couldn't finish one bundle in 10 min. Until
   upstream ships `$import` (ADR-0011 §3a), a loader like this is the bulk story —
   candidate for promotion into `contracts/`/`dq/` tooling proper.
2. **The reference promoter's hard limit is V8's ~512 MB string cap**, hit twice:
   reading Bronze (`/query` returns one giant JSON body — Observation 771k rows ≈
   1.1 GB fails, EOB ≈ 650 MB fails) and writing Silver (one `/write` request —
   Claim/DiagnosticReport/DocumentReference got Gold but not Silver).
   **FIXED same day** by fhirHouse's chunked external promoter
   (`dagster/fhirhouse_dagster/chunked_promote.py` — ADR-0026's external-promoter
   lane): Bronze read READ-SIDE in record batches, Gold MERGE + Silver flatten in
   bounded sidecar chunks. Observation: 771,510 rows → Gold+Silver in **97 s**;
   all 24 types now fully promoted (Silver = 1,828,315 rows, Bronze parity).
3. **Silver's inferred Arrow schema breaks DuckDB's delta reader**: all-null
   nested fields become `void` columns; delta-kernel rejects the table
   (`Unsupported Delta table type: 'void'`) while Python delta-rs reads it fine.
   Upstream already notes "explicit-schema is the follow-up" in promote.ts.
   **Addressed** by the chunked promoter's Silver encoding (native scalar columns
   + JSON-text complex columns, schema-anchored first chunk): after rebuilding all
   24 Silver tables with it, **every Silver table is DuckDB-readable** and the SoF
   views (incl. `observation_flat`, 774,146 rows) run over Silver as designed.
   Deliberate divergence from upstream's nested-struct Silver — revisit when
   upstream ships explicit Silver schemas.
4. **Guardrails proved themselves on real data**: the only probabilistic candidate
   pair in 634k comparisons was killed by the SSN hard-deny floor — exactly the
   ADR-0012 §3.4 behavior, with the m/u evidence in `gold.mpi_decision_log`.
5. Loader leaves `search_param_index` empty → REST search/$everything degraded on
   this store (reads by id are fine). A production loader must extract search
   params (or promotion should backfill them).

## Where things live (left running)

- Delta store: `~/fhirhouse-demo/delta` (bronze/silver/gold + governance tables)
- Sidecar: `127.0.0.1:8087` · FHIR API (medallion): `127.0.0.1:3200`
- Splink model: `~/fhirhouse-demo/splink_model.json`
- Queryable views: `fhirhouse.duckdb` at the repo root (`duckdb fhirhouse.duckdb`)
