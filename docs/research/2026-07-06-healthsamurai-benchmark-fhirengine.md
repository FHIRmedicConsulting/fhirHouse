# Running the Health Samurai FHIR Server Performance Benchmark against fhirEngine

- Date: 2026-07-06
- Tool: [HealthSamurai/fhir-server-performance-benchmark](https://github.com/HealthSamurai/fhir-server-performance-benchmark)
  (k6 suites: crud / import / search; normally run against Aidbox, HAPI, Medplum,
  MS FHIR on an 8-CPU/24–30 GB-per-server rig)
- Target: fhirEngine standalone, single-store topology, dev profile (auth/audit/TLS
  off), `tsx` runtime, one delta-rs sidecar — on a MacBook Pro (arm64). k6 v2.1.0
  native (no Docker NAT).

**Caveat up front:** numbers here are NOT comparable to the published Aidbox/HAPI
reports (different hardware, no server tuning, dev runtime). What they measure is
fhirEngine's *shape*: correctness under the suites and where its Delta-native
architecture saturates.

## Results

### CRUD (create→read→update→delete across 9 resource types)

| Load | Checks pass | Throughput | http_req_duration |
|---|---|---|---|
| 2 VUs (smoke) | **100%** | ~26 checks/s | fast (ms-range) |
| 10 VUs, 90s | **100%** | ~10 req/s | med 392 ms · p95 3.7 s |
| 30 VUs, 90s | **100%** | ~11.5 req/s | med 394 ms · p95 12.9 s |
| 100 VUs, 90s | 96.2% | ~15.6 req/s | med 348 ms · p95 43 s |
| 300 VUs, 5 m (official config) | 66.2% | ~10 req/s | med 20 s · p90 60 s (timeouts) |

Reading: **correctness is clean** (every CRUD interaction the suite checks passes),
and **write throughput ceilings at ~10–15 req/s regardless of concurrency** — the
signature of the one-writer-per-table delta-rs invariant (ADR-0026 §5): every write
is a serialized Delta commit through one Python sidecar process. Latency absorbs
added concurrency (medians stay ~350–400 ms while tails blow out), and past ~30
concurrent writers the queue exceeds timeouts. The official 300-VU config is sized
for Postgres connection pools; a Delta-commit-per-write engine plays a different game.

### Bulk import (Synthea transaction bundles)

- fhirEngine correctly **rejects** patient bundles whose conditional references
  (`Practitioner?identifier=…`) aren't yet resolvable — validation atomicity works.
- Pre-validating a 250-entry bundle took ~18 s; the 1,675-entry
  `hospitalInformation.json` seed was still processing after **10+ minutes**
  (sidecar pinned at ~185% CPU, 45 CPU-min) before we killed it. Per-entry
  conditional-reference resolution + one Delta commit per entry makes the
  transaction path unusable for Synthea-scale bulk.
- **This is the wrong lane, not a missing capability**: fhirEngine's designed bulk
  path is async NDJSON `$import` (ADR-0011 §3a), which this suite doesn't exercise.
  A useful follow-up: measure `$import` on the same corpus.

### Search (string/date/token/quantity/composite/reference/modifiers/prefixes)

- **100% of 620 search checks pass** (30 VUs, 60 s; small post-CRUD corpus).
- But ~6.9 req/s and median **4.3 s per search at 30 VUs** even on a tiny store —
  reads queue behind the same single sidecar (`/query` → DataFusion per request).
  Single-request search latency floor was ~210 ms.

## Takeaways for fhirEngine/fhirHouse

1. **Conformance over the suite's surface is excellent** — nothing functional
   failed at sane concurrency, including full cross-type transaction bundles with
   urn:uuid rewriting (which upstream shipped beyond ADR-0011 v1's promise).
2. **The sidecar is the universal bottleneck** (writes AND reads). Scale paths, in
   likely order of leverage: table-sharded sidecar workers (ADR-0026 §6 already
   sketches this, one-writer-per-table preserved), a read-only sidecar pool or
   in-process read engine for search/read traffic, and batching multiple bundle
   entries into one Delta commit for the transaction path.
3. **Bulk loads must route through `$import`**, never transaction bundles.
4. Benchmarking methodology note: to reproduce, `runner.sh` and the full Docker
   stack aren't needed — k6 natively + `BASE_URL` at the server is sufficient
   (wrappers used here live in the session scratchpad; the suite is unmodified).
