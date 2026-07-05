# Deployment topology — single store vs medallion

Design note (session 032, 2026-06-28). Companion to the `storage-topology` memory and
the pending ratifying ADR. Source diagram: `RoninDepoyment .svg` / `.json` (repo root,
Lucidchart export) — two install-time deployment options.

## Option A — Single store (DEV default)

```
FHIR via API  ┐
NDJSON Bulk   ┼─►  fhirEngine  ─►  Single Delta Store
              ┘         ◄── "API Data" (reads served from the same store)
```

Everything off **one Delta store** — operational + transactional + (when wired) the
flattened search columns. No tier separation, no promotion, no enterprise-analytics feed.

## Option B — Medallion

```
FHIR via API ┐
NDJSON Bulk  ┼─► fhirEngine ─► Bronze ─► Silver ─► Gold
Document ────┘        ◄── "API Data" (reads served from Gold)
                                     Silver ─► Enterprise Analytics Silver ─► (out)
```

Bronze (raw landing) → Silver (flattened + governed) → **Gold (operational/transactional —
the API reads/writes here)**. Silver feeds an external **Enterprise Analytics** consumer.

## Decisions captured

- **Single store is the dev default**; medallion is an install-time option. Config
  `FHIRENGINE_STORAGE_MODE = single | medallion` (switch still to wire).
- **Gold is the operational/transactional store in medallion** (confirmed by the diagram's
  `fhirEngine ↔ Gold` "API Data" edge).
- **Flattening is topology-independent.** Per-resource search needs flattened, queryable
  columns; in **single store those columns live in the one store** (it already carries
  `body_json` + a materialized `identifier_index` — richer search just materializes more
  columns there), and in **medallion they live in Silver**. *Nothing about per-resource
  search forces medallion.* (Corrects an earlier slip that said search "needs Silver
  columns" while we are on single store.)
- **Out of scope:** "Enterprise Analytics Silver" is the **separate** governance/analytics
  app. fhirEngine provides the Bronze/Silver/Gold plumbing only; data
  governance/quality/promotion criteria live in that other app.

## Consistency decision (medallion) — RESOLVED 2026-07-04, affects medallion only

**Decided (operator decision; supersedes the earlier synchronous-Gold-write proposal):**
in medallion the API writes **Bronze only** (the write domain: ingest, version chain,
optimistic locking, conditional-write uniqueness); **external orchestration**
(Dagster / Databricks / cron — fhirEngine never promotes on its own) moves
Bronze→Silver→Gold; the API **serves current-state reads and searches from Gold**.
Consequences, by design:

- **Eventual consistency**: a just-ingested resource is not readable/searchable until
  promoted (404 before, served after). Deletes 410 only once the tombstone promotes.
- **history/vread stay on Bronze** — it is the version log; Gold is current-version only.
- Gold rows carry the full Bronze row shape (body + search/identifier indexes), so the
  search engine runs unchanged against Gold.
- Bronze + Silver tables are created with `delta.enableChangeDataFeed=true` so external
  promoters can read incremental changes (`load_cdf`, ADR-0026); the in-repo
  `fhirengine-promote` CLI is the idempotent full-rebuild reference implementation.

Single store (`FHIRENGINE_STORAGE_MODE=single`, the default) is unaffected: writes and
reads share Bronze — read-after-write holds. Choose **single** for transactional FHIR API
semantics; choose **medallion** when an enterprise pipeline owns curation and the API
serves the governed Gold projection.

## Open questions (unanswered — do not assume)

1. ~~Process-block label "Ronin"~~ — RESOLVED (2026-07-04): the standalone diagrams read
   "fhirEngine" (the source Lucidchart export predates the rename).
2. "Document" input (medallion only, via "API Calls") — FHIR Document Bundle /
   `DocumentReference`, or an external doc source? Intentionally absent from single store?
3. "Enterprise Analytics Silver" — a separate copy fed from Silver, or a read of our Silver?

## Target-state note

The diagram shows **NDJSON Bulk FHIR** (both options) and **Document** (medallion) as
inputs. Today we have API CRUD + batch/transaction; **bulk/NDJSON ingest is not yet built**
— the diagram is target-state.
