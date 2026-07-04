# ADR-0036: UDAP B2B Trust — Software Statements & Trusted Dynamic Client Registration (foundation)

- Status: **Accepted** 2026-07-04 (Chad — Scope-1 deferred items; foundation, not the full SSRAA surface)
- Date: 2026-07-04
- Decider(s): Chad
- Session: standalone security hardening (Scope-1 deferred items)
- Related: [ADR-0006](0006-smart-on-fhir-and-udap-security.md) (SMART/UDAP heritage design), [ADR-0030](0030-standalone-security-privacy-consent-enforcement.md), [ADR-0032](0032-production-security-profile.md), `docs/research/2026-07-03-tls-and-cms-compliance-security-deep-dive.md` (gap A3)

## Context

CMS-0057-F's B2B APIs (Provider Access, Payer-to-Payer, Prior Auth) and TEFCA use **UDAP/SSRAA** for
system-to-system trust: a partner proves identity with an **X.509 certificate** chained to a trusted
CA, presents a signed **software statement** to a **Dynamic Client Registration** endpoint, then
authenticates with that certificate. The standalone had SMART Backend Services (`private_key_jwt`)
but no certificate-based trust or DCR — gap **A3** in the security deep-dive.

## Decision

Add a UDAP **foundation** (opt-in `RONIN_UDAP_ENABLED`, `RONIN_UDAP_TRUST_ANCHORS`), in
`src/auth/udap/`, **no new dependency** (Node `crypto.X509Certificate` + existing `jose`):

- **`trust.ts`** — load trust anchors (PEM); `verifyCertChain(x5c, anchors)` validates leaf→…→anchor
  linkage (issuer signature) + validity windows, terminating at a trusted CA.
- **`software-statement.ts`** — `verifySoftwareStatement`: verify the `x5c` chain, verify the JWT under
  the leaf cert key, check `iss === sub` and `aud === registration endpoint`; derive the client's
  token-signing **JWKS from the leaf cert** (UDAP clients authenticate with the same cert).
- **`udap-routes.ts`** — `GET /.well-known/udap` (server metadata) + `POST /udap/register` (Trusted
  DCR). A registered client is stored (`registered-clients.ts`) and resolved by `oauth/clients.ts`, so
  it immediately works at the existing `/oauth/token` via `private_key_jwt` / Backend Services.

## Consequences

- (+) Certificate-rooted B2B trust + DCR — the on-ramp to CMS-0057 B2B / TEFCA; reuses the Backend
  Services token path. Tested against real openssl-minted CA/leaf certs.
- (+) **Revocation implemented** (operator revocation list): `RONIN_UDAP_REVOKED_CERTS` /
  `RONIN_UDAP_REVOKED_CERTS_FILE` (cert SHA-256 fingerprints and/or serials). A revoked cert anywhere
  in a presented chain rejects the whole chain — so a compromised partner cert can be revoked
  immediately, without waiting for expiry. No new dependency.
- (+) **Persistent client registry** — DCR registrations are written through to a durable `udap_client`
  Delta table (`registered-clients.ts` + catalog/warehouse), loaded into the in-memory cache on
  startup, so registrations survive restarts and repopulate a fleet (latest-per-client_id wins).
- (+) **Signed discovery** (`signed_metadata` at `.well-known/udap`) + **tiered OAuth** — `/oauth/authorize`
  accepts a signed **request object (RFC 9101 JAR)** verified against the client's registered key, so the
  authorization request is provably from the client.
- (−) **Not complete SSRAA yet.** Deferred (**OPEN QUESTIONS / follow-ups**):
  - **Live CRL/OCSP fetching** — needs a **new dependency decision** (flag per the component-disclosure
    policy): Node's `crypto` has no CRL/OCSP support. Recommended path: **`pkijs` + `asn1js`** (pure-JS,
    no native build) to download the cert's CRL Distribution Point, parse it, and check the serial —
    CRL first (simpler; no request signing), OCSP (AIA responder) as a follow-up. Both plug into the
    existing revocation seam (`loadRevokedCerts`/`verifyCertChain`). **Meanwhile the static operator
    revocation list is a real revocation control.** Requires Chad's approval of the PKI dep before build.
  - Full RFC 5280 path validation + name-constraints; UDAP **certifications/endorsements**; and
    community/trust-bundle management. Required before production TEFCA use.
