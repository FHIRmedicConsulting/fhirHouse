# fhirEngine — Configuration Reference

All configuration is via environment variables (12-factor). The guided setup
(`cd packages/server && npm run init`) walks through the common path and writes `deploy/.env`;
or copy `deploy/.env.example` → `deploy/.env` and edit by hand. Secrets: inject via your
orchestrator / 1Password `op run` — never commit a real `.env`.

**Legend:** _req(prod)_ = required to boot under `FHIRENGINE_SECURITY_PROFILE=production` (fail-closed,
ADR-0032). Related: the security runbook (`security-hardening-and-deployment.md`).

## Storage

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_DELTA_BASE` | `./.delta` (`/data/delta` in Docker) | Delta root — local path **or** object-store URI (`s3://…`, `gs://…`, `az://…`). The server + sidecar must agree. |
| `FHIRENGINE_STORAGE_MODE` | `single` | `single` (writes+reads share Bronze; read-after-write) or `medallion` (API ingests to Bronze, SERVES from Gold; external orchestration promotes Bronze→Silver→Gold — eventual consistency; history/vread stay on Bronze; `fhirengine-promote` is the reference promoter). |
| `FHIRENGINE_DELTA_SIDECAR_URL` | `http://127.0.0.1:8077` | URL of the delta-rs sidecar (server → sidecar). |

**Object-store credentials** (only when `FHIRENGINE_DELTA_BASE` is a cloud URI): `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_S3_ALLOW_UNSAFE_RENAME` (true on native AWS S3 — single
writer, ADR-0026), `GOOGLE_SERVICE_ACCOUNT`, `AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_STORAGE_ACCOUNT_KEY`.

## Server

| Var | Default | Description |
|---|---|---|
| `PORT` / `FHIRENGINE_PORT` | `3000` | Listen port (`FHIRENGINE_PORT` maps the host port in compose). |
| `FHIRENGINE_PUBLIC_URL` | `http://localhost:<port>` | Externally-reachable base URL — used in FHIR links/pagination. Set to the real hostname behind a proxy. |
| `FHIRENGINE_LOG_LEVEL` | `info` | pino log level. |
| `FHIRENGINE_MIGRATE_IS_CURRENT` | off | One-time `is_current` backfill on upgrade (set `true` once). |

## Validation

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_VALIDATION_PROFILES` | — | Conformance-profile requirement for incoming resources. Empty = validate against the installed FHIR version only (structure, invariants, base bindings); `meta.profile` claims are stored, not enforced. Comma-separated entries: an installed IG package id (`hl7.fhir.us.core` — enforce its profile per resource type), a profile canonical URL, or `declared` (enforce each resource's `meta.profile` claims). Requires the referenced IG to be installed (`fhirengine-terminology install-ig`). |

## Security profile & transport (ADR-0031/0032)

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_SECURITY_PROFILE` | `dev` | `dev` (warns, synthetic-only) or `production` (fail-closed). |
| `FHIRENGINE_TLS_CERT` / `FHIRENGINE_TLS_KEY` | — | PEM paths → hardened in-process HTTPS (SP 800-52r2). _req(prod)_ unless proxy-terminated. Hot-reloaded on change. |
| `FHIRENGINE_TLS_TERMINATED_AT_PROXY` | — | `true` attests a proxy/LB terminates TLS. _req(prod)_ if not running in-process TLS. |
| `FHIRENGINE_TLS_CIPHERS` | NIST SP 800-52r2 list | Advanced: override the TLS 1.2 cipher allow-list. |

## Authentication (ADR-0030)

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_AUTH_ENABLED` | off | Enable the SMART/JWT gate. **_req(prod)_.** |
| `FHIRENGINE_AUTH_STRATEGY` | `jwks` | `jwks` \| `oidc` \| `local` (verify our own OAuth server) \| `stub` (tests). |
| `FHIRENGINE_JWKS_URI` | — | jwks strategy: the IdP JWKS URL. |
| `FHIRENGINE_JWT_PUBLIC_KEY` / `FHIRENGINE_JWT_ISSUER` / `FHIRENGINE_JWT_AUDIENCE` / `FHIRENGINE_JWT_ALG` | — | Static-key JWT validation params. |
| `FHIRENGINE_OIDC_DISCOVERY` | — | oidc strategy: issuer discovery URL. |
| `FHIRENGINE_SMART_VERSIONS` | all | Active SMART grammars (e.g. `2.0.0,2.2.0`). |
| `FHIRENGINE_SMART_AUTHORIZE_URL` / `FHIRENGINE_SMART_TOKEN_URL` | — | Advertised in `.well-known/smart-configuration` if using an external AS. |

## SMART authorization server (optional)

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_OAUTH_ENABLED` | off | Run `/oauth/authorize` + `/oauth/token` + JWKS. |
| `FHIRENGINE_OAUTH_PRIVATE_KEY` / `FHIRENGINE_OAUTH_PUBLIC_KEY` | ephemeral | Static signing keys (PEM). **_req(prod)_ when OAuth enabled** (ephemeral keys rotate on restart). |
| `FHIRENGINE_OAUTH_CLIENTS` | dev-open | JSON array of registered clients (locks client_id + redirect_uris). |
| `FHIRENGINE_OAUTH_DEFAULT_PATIENT` / `FHIRENGINE_OAUTH_DEFAULT_USER` | — | Dev auto-approve launch context. |

## UDAP B2B trust (ADR-0036; opt-in)

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_UDAP_ENABLED` | off | Enable `.well-known/udap` + trusted DCR (`/udap/register`). |
| `FHIRENGINE_UDAP_TRUST_ANCHORS` | — | Comma-separated PEM paths of trusted CA anchors. |
| `FHIRENGINE_UDAP_REVOKED_CERTS` | — | Revoked cert SHA-256 fingerprints and/or serials (comma-separated) — rejected even if trusted + unexpired. |
| `FHIRENGINE_UDAP_REVOKED_CERTS_FILE` | — | ...or a file of them (one per line, `#` comments). |
| `FHIRENGINE_UDAP_SERVER_KEY` / `FHIRENGINE_UDAP_SERVER_CERT` | — | PEM key + cert chain to emit signed `signed_metadata` at `.well-known/udap`. |
| `FHIRENGINE_UDAP_CRL_CHECK` | off | Enable live CRL revocation (downloads + signature-verifies the CRL, checks the serial). |
| `FHIRENGINE_UDAP_CRL_URLS` | cert CDP | Extra/override CRL URLs (comma-separated). |
| `FHIRENGINE_UDAP_CRL_HARD_FAIL` | soft-fail | `true` = reject when a CRL can't be fetched/verified. |
| `FHIRENGINE_UDAP_OCSP_CHECK` | off | Enable live OCSP revocation (RFC 6960; queries the responder, verifies the signed response). |
| `FHIRENGINE_UDAP_OCSP_URLS` | cert AIA | Extra/override OCSP responder URLs (comma-separated). |
| `FHIRENGINE_UDAP_OCSP_HARD_FAIL` | soft-fail | `true` = reject when the OCSP responder is unreachable. |
| `FHIRENGINE_UDAP_STRICT_PATH` | on | RFC 5280 path validation (basic constraints, key usage, name constraints); `false` to disable. |

## Audit, consent & HTTP hardening (ADR-0030/0033/0035)

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_AUDIT_ENABLED` | off | Capture (hash-chained) AuditEvents. **_req(prod)_.** |
| `FHIRENGINE_AUDIT_ANCHOR_INTERVAL_MIN` | off | Publish signed audit chain-tip anchors every N min (external tamper detection). |
| `FHIRENGINE_AUDIT_ANCHOR_WEBHOOK` | — | External append-only sink URL to POST anchors to. |
| `FHIRENGINE_AUDIT_ANCHOR_KEY` | — | PEM (PKCS8) key to sign anchors (optional). |
| `FHIRENGINE_CONSENT_ENFORCEMENT` | off | Enforce consent/DS4P at read time (advisory in prod). |
| `FHIRENGINE_CORS_ORIGINS` | dev: `*` / prod: none | Comma-separated allowlist; prod + empty ⇒ same-origin only. |
| `FHIRENGINE_RATE_LIMIT_ENABLED` | prod on / dev off | Per-client rate limiting. |
| `FHIRENGINE_RATE_LIMIT_RPM` | `600` | Requests per client per minute. |
| `FHIRENGINE_RATE_LIMIT_STORE` | per-node | `redis` for shared limits across instances (lazy-loads `ioredis` — `npm i ioredis`). |
| `FHIRENGINE_REDIS_URL` | — | `redis://…` when `FHIRENGINE_RATE_LIMIT_STORE=redis`. |
| `FHIRENGINE_MAX_BODY_BYTES` | `10485760` | Request body cap (10 MiB) → 413. |

## Maintenance & misc

| Var | Default | Description |
|---|---|---|
| `FHIRENGINE_MAINTENANCE_INTERVAL_MIN` | off | OPTIMIZE interval (empty = off). |
| `FHIRENGINE_VACUUM_ENABLED` / `FHIRENGINE_VACUUM_RETENTION_HOURS` | off | VACUUM during maintenance + its retention window. |
| `FHIRENGINE_EXPORT_DIR` | temp | Directory for async `$export` NDJSON output. |
| `FHIRENGINE_QUARANTINE_ON_UNKNOWN` / `FHIRENGINE_DISABLE_AUTO_RECONCILE` | off | Quarantine-on-unknown-terminology + auto-reconcile toggle. |
| `FHIRENGINE_SERVER_DEVICE_ID` / `FHIRENGINE_INLINE_LABEL_URL` / `FHIRENGINE_AUDIT_DEBUG` | — | AuditEvent source device id · inline-label extension URL · verbose audit logging. |
