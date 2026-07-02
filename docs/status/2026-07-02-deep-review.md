# Deep review — 2026-07-02

Four independent code-grounded reviews (REST/search, validation/terminology, storage/durability,
security/prod). Purpose: an honest "where are we + what next + % done", correcting session-note
optimism. Each dimension scored against its **full** production/(g)(10) surface, not "does it run".

## Scores

| Dimension | % | One-line |
|---|---|---|
| FHIR REST + search + operations | **72%** | Strong CRUD/history/conditional/transactions/search; `$export` is a dev stub, no PATCH, no composite search, CapabilityStatement inaccurate |
| Storage / durability / perf / topology | **55%** | Correct single-store write/read + real serialization + atomic `is_current`; version TOCTOU, medallion unwired, no schema migration, object-store gaps |
| Validation / terminology / conformance | **45%** | Solid structural/cardinality/enum + 3-state terminology; profiles register but don't enforce (top-level only), thin CodeableConcept bindings, tx endpoints thin |
| Security / production-readiness | **35%** | Good building blocks but **compartment isolation is dead code**, no SMART auth server, no TLS, no CI, lint stub |

**Weighted overall (REST 30% · Validation 25% · Storage 20% · Security 25%): ≈ 52%.**

Two ways to read it:
- **As a working dev FHIR server** (writes/reads/validates data, clean, 240 tests green): ~75%.
- **As a production, ONC (g)(10)-certifiable, HIPAA-technical-safeguards server** (the stated goal): **~50%.**

## Correctness bugs found (not just "incomplete")
1. **Patient-compartment enforcement is computed then discarded** — `auth-middleware.ts:106-114`
   drops the `enforce()` result; `data-filter.ts` is imported by nothing; no route re-scopes to the
   launch patient. → When auth is ON, a `patient/*.rs` token authorizes the *type* but not the
   *patient* → cross-patient exposure. (Auth is opt-in/default-off, so not exploitable in dev, but
   the ADR-0030 "consent/compartment complete" claim is wrong.) **Fix first.**
2. **Version-number TOCTOU** — `delta-resource-repository.ts` `currentRow()` (read) runs *before*
   the per-table write chain, so two concurrent updates to the same id both read version N and
   write N+1 (duplicate version + misfired demote). Priority-#3 serialized writes, not the
   read-modify-write.
3. **CapabilityStatement is inaccurate** — advertises *less* than exists (only `identifier`
   searchParam; `conditionalCreate/Update:false`, `conditionalDelete:not-supported`, omits
   `$export`/`$everything`/history-type/system) while the code supports them. Inferno reads this.

## Recalibration of prior "done" claims
- "Security/consent COMPLETE (ADR-0030)" → enforcement scaffold real, but compartment data-path
  unwired + no auth server. **Not complete.**
- "Terminology server done" → endpoints exist + work for simple cases, but lack filtered/paged
  `$expand`, batch validate-code, inline-VS, `$subsumes`/`$translate` — thin for a real tx client.
- "Priority #3 concurrency done" → cross-table conflicts handled; same-id read-modify-write not.
- Medallion topology: `RONIN_STORAGE_MODE` only moves terminology paths; `promote.ts` is dead code;
  only single-store is real.

## What to do next (recommended sequence)
1. **Fix compartment/query-restriction enforcement** (wire `enforce()` → `data-filter` into reads)
   + a cross-patient test. Security correctness.
2. **Fix version TOCTOU** (compute+write version inside the per-table serialization, or a
   version-assigning MERGE) + a same-id concurrency test.
3. **Make CapabilityStatement accurate** (declare real search params, conditional ops,
   `$export`/`$everything`, history levels) — cheap, high-leverage for Inferno.
4. **SMART authorization server** (`/authorize`, `/token`, PKCE, `id_token`, `.well-known/jwks.json`)
   — unblocks OAuth-gated (g)(10) + makes discovery non-placeholder. Biggest single unlock.
5. **Profile/IG enforcement depth** (nested required elements, slicing max/closed, derived
   validators) + CodeableConcept binding coverage.
6. **`$export` production-grade** (persisted async bulk data) for (g)(10) multi-patient.
7. **Production hardening**: TLS/proxy story, CI + real ESLint, Docker non-root + HEALTHCHECK,
   sanitize 500 `err.message`, audit write-failure handling.
8. **Broaden tx endpoints** (filter/paging/batch/inline) — pairs with #5, enables Inferno-via-our-tx.
9. **Search completeness**: composite params, `_include:iterate`, multi-field/numeric `_sort`, fix
   chained/`_has` 1000-row silent truncation, guard `_revinclude` type.
10. **Decide medallion**: wire single↔medallion read path + `is_current` schema migration, or
    explicitly defer and document single-store as the supported topology.
