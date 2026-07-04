# CMS-0057-F B2B APIs — Implementation Plan (Da Vinci)

_Foundation/roadmap for the CMS Interoperability & Prior Authorization final rule (**CMS-0057-F**)
B2B API surface. Unlike the security-infrastructure work (ADR-0031..0036, all shipped), this is a
**multi-week functional program** across several Da Vinci IGs. This doc is the grounded plan:
what each API needs, what already exists, and the sequence. It is a plan, not shipped code._

> Compliance dates (verify against the current rule text): the CMS-0057 **API requirements are
> generally effective January 1, 2027** for impacted payers (Patient Access, Provider Access,
> Payer-to-Payer, and the Prior Authorization API), with Prior-Auth decision-timeline provisions
> phasing in 2026. Treat dates as **OPEN — confirm before committing schedule.**

## What we already have (reusable substrate)

| Capability | Status | Feeds |
|---|---|---|
| FHIR R4 REST + rich search + history | ✅ | every API |
| Bulk Data `$export` (async, group/system) | ✅ | Provider Access, Payer-to-Payer |
| SMART Backend Services (`client_credentials`+`private_key_jwt`) | ✅ | all B2B auth |
| **UDAP** cert trust + DCR (foundation) | ✅ (ADR-0036) | B2B/TEFCA trust |
| Consent enforcement + DS4P labels/obligations | ✅ (ADR-0030) | opt-in/opt-out gating |
| Audit + accounting-of-disclosures (hash-chained) | ✅ (ADR-0016/0035) | disclosure tracking |
| US Core 6.1.0 profiles + terminology + validation (L1–L3) | ✅ | data conformance |
| Profile/IG install (`ig-loader`) | ✅ | installing Da Vinci IGs |

So the B2B **plumbing** largely exists. The gaps are the **Da Vinci IGs**, a few **operations**, and
the **authorization semantics** (attribution, opt-out/opt-in consent) specific to each API.

## The four APIs → IGs → work

### 1. Patient Access API — *mostly done*
- **IGs:** US Core, SMART App Launch, Da Vinci **PDex** (payer data). USCDI via US Core.
- **Have:** SMART auth, US Core read/search, `$export`. **Gap:** PDex profiles install + provenance
  for payer-sourced data; formulary (PDex-Drug) and EOB (C4BB `ExplanationOfBenefit`) if payer-scoped.
- **Effort:** small–medium (install IGs + EOB/coverage surface).

### 2. Provider Access API — *auth semantics are the work*
- **IGs:** Da Vinci **PDex**, US Core, Bulk Data.
- **Have:** Backend Services, `$export`, consent. **Gap:** **attribution** (which patients a provider
  is authorized for → a Group per provider/panel), **patient opt-OUT** consent default (data flows
  unless the patient opts out), and provider-directory validation.
- **Build:** attribution Group management + `Patient.$export` scoped to the attributed Group + an
  opt-out `Consent` check in the export path (reuse `consent-enforce`). **Effort:** medium.

### 3. Payer-to-Payer API — *`$member-match` + opt-in*
- **IGs:** Da Vinci **HRex** (`$member-match`), **PDex**, US Core.
- **Have:** search, Backend Services, UDAP. **Gap:** **`Patient/$member-match`** (HRex) — match an
  incoming member (coverage + demographics) to a local patient; **patient opt-IN** consent default;
  bulk pull of the matched member's data.
- **Build:** `$member-match` operation (identifier + coverage + name/DOB/gender matching over the MPI;
  the heritage `$match` logic is a starting point), opt-in `Consent` gate, then `$export` for the
  matched patient. **Effort:** medium (member-match is the bounded, high-value first slice).

### 4. Prior Authorization API (PAS/CRD/DTR) — *largest*
- **IGs:** Da Vinci **PAS** (`Claim/$submit`, `Claim/$inquire` via X12 278), **CRD** (coverage
  requirements via CDS Hooks), **DTR** (documentation templates via CQL/Questionnaire).
- **Have:** transaction/bundle, validation. **Gap:** PAS operations + X12 278 mapping, CRD **CDS
  Hooks** service endpoints, DTR Questionnaire/CQL execution. This is the heaviest surface (CDS Hooks
  + CQL engine + X12).
- **Effort:** large; sequence last. CQL/CDS-Hooks may warrant a dedicated component decision.

## Cross-cutting prerequisites

- **L5 profile validation** for the Da Vinci profiles (the `PROFILE_VALIDATORS` hook) — needed so
  submitted PAS/PDex resources are conformance-checked. Ties to the validation roadmap.
- **Da Vinci IG install** into the conformance/terminology store (`ig-loader` + `pullIgVsacValueSets`).
- **UDAP hardening** (revocation, tiered OAuth — ADR-0036 follow-ups) before real-partner B2B.

## Recommended sequence (smallest-valuable-first)

1. Install Da Vinci IGs (PDex/HRex first) — unblocks profiles + value sets. *(small)*
2. **`Patient/$member-match`** (HRex) + opt-in consent — the bounded Payer-to-Payer core, testable
   against Synthea. *(medium — good first build)*
3. Provider Access attribution Group + opt-out consent + scoped `$export`. *(medium)*
4. Patient Access PDex/EOB surface. *(small–medium)*
5. Prior Auth (PAS → CRD → DTR) — its own epic; likely a dedicated ADR for CDS Hooks + CQL. *(large)*

Each step is independently shippable and rides the existing auth/export/consent/audit substrate.

## Decisions needed before building (OPEN QUESTIONS)

- Which APIs are in scope for RoninStandAlone vs. the separate governance/ELT app? (Payer-specific
  APIs may not belong in a self-hostable FHIR server.)
- CDS Hooks + a CQL engine are large new components — **needs a component-disclosure/ADR** before PAS.
- Confirm the CMS-0057 compliance dates and which **actor** RoninStandAlone plays (provider-side vs.
  payer-side changes the API set).
