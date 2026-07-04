/**
 * Additive profile search parameters — search params defined by IGs (not R4 Core) that the generic
 * engine can serve because their FHIRPath expressions resolve to primitives/tokens the index already
 * handles. Merged on top of the R4 Core registry by `searchParamsFor`.
 *
 * Currently: **CARIN Blue Button** ExplanationOfBenefit params needed by the CMS-0057 Patient Access
 * API — `type` (claim category) and `service-date`. R4 Core defines `use`/`created` but not these.
 * `service-date` is indexed from date PRIMITIVES (`billablePeriod.start`, `item.servicedDate`,
 * `item.servicedPeriod.start`) so range queries (ge/le/gt/lt) work with the existing date matcher; it
 * is therefore **service-start-based** (full Period-overlap semantics are a follow-up).
 *
 * These are always-on: they are plain EOB search params that work regardless of whether the CARIN BB
 * IG is installed. Profile *conformance* (validating against the CARIN profiles) still requires IG
 * install (L5). Nothing here invents a param the engine can't actually evaluate.
 */
import type { SearchParamDef } from "./r4-search-params.js";

export const PROFILE_SEARCH_PARAMS: Record<string, Record<string, SearchParamDef>> = {
  ExplanationOfBenefit: {
    type: { type: "token", expression: "ExplanationOfBenefit.type" },
    "service-date": {
      type: "date",
      expression: "ExplanationOfBenefit.billablePeriod.start | ExplanationOfBenefit.item.servicedDate | ExplanationOfBenefit.item.servicedPeriod.start",
    },
  },
};
