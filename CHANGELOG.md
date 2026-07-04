# Changelog

All notable changes to RoninStandAlone are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses
[Semantic Versioning](https://semver.org/) and is **pre-alpha** (`0.x` — anything may change).

## [Unreleased]

### Added
- **FHIR R4 REST surface** — CRUD, history (instance/type/system), vread, CapabilityStatement,
  `$validate`, `$everything`, `$export` (async), batch/transaction, conditional create/update/delete,
  and rich search (token/string/date/number/quantity/uri/reference incl. bare-id, modifiers, chaining,
  `_has`, `_include`/`_revinclude` incl. `:iterate`, `_sort`/`_summary`/`_elements`, paging, POST `_search`).
- **Validation prior to Bronze** — structural + cardinality + choice-type + terminology bindings
  (3-state) + L4 FHIRPath invariants (top-level/one-level, R4-model-aware) + installed-profile
  required elements/bindings + slicing (first cut).
- **Terminology server** — local `$validate-code` / `$expand` / `$lookup` + `TerminologyCapabilities`;
  IG install + operator-supplied SNOMED/LOINC/RxNorm loaders + VSAC pull-once.
- **Security infrastructure** (ADR-0031..0036) — hardened TLS (NIST SP 800-52r2, cert hot-reload),
  fail-closed **production security profile**, HTTP hardening (security headers, enforced CORS,
  pluggable rate limiting, body limits), **tamper-evident (hash-chained) audit** + `ronin-audit-verify`,
  SMART auth server + Backend Services + **UDAP B2B trust foundation**, and SBOM + npm-audit +
  pip-audit + gitleaks + Trivy in CI.
- **Ops** — `/health` (liveness) + `/ready` (readiness), graceful SIGTERM/SIGINT shutdown,
  secure-by-default Docker Compose + production overlay, complete config reference.
- Sidecar pytest suite; server-boot smoke test in CI.

### Known limitations (pre-alpha)
- Not ONC (g)(10)-certified — individual US Core groups pass in Inferno; full suite not run end-to-end.
- Single-store serving only (medallion Gold read-path WIP); object-store restart-registration is local-FS only.
- Composite/special search params + multi-field `_sort` are rejected under `Prefer: handling=strict`
  (not implemented as filters). L5 profile/IG conformance is partial (external HL7 validator is authoritative).
- UDAP is a foundation (no revocation/CRL-OCSP, tiered OAuth, or persistent registry yet).

[Unreleased]: https://github.com/419onscene/RoninStandAlone/commits/main
