# `@fhirengine/server` — Ronin FHIR R4 REST server (TypeScript interactive tier)

The interactive read/write tier per [ADR-0011](../../docs/decisions/0011-write-contract.md). Runs as a Databricks App per [ADR-0013](../../docs/decisions/0013-deployment-posture.md). Talks to the medallion via Databricks SQL warehouses per [ADR-0010](../../docs/decisions/0010-storage-shape.md).

**Status:** v0.1.0 — v1 vertical slice. Patient resource only. Auth/audit/consent/search-beyond-identifier deferred to follow-up builds.

## What this slice proves

- The Hono-on-Databricks-Apps deployment model works end-to-end.
- The Bronze→Gold medallion separation is real (two tables; UUID v7 mint at write; current-version projection at read).
- The FHIR REST surface (POST/GET/PUT/DELETE/search) is conformant for one resource — scales to N resources without redesign.
- Vitest covers the unit + integration paths against an in-memory warehouse.

## What it does

| Endpoint | Behavior |
|---|---|
| `GET /health` | Liveness probe |
| `GET /.well-known/smart-configuration` | SMART discovery (per ADR-0006) |
| `GET /metadata` | CapabilityStatement asserting Patient (per ADR-0014 §10) |
| `POST /Patient` | Create; mints UUID v7 fhir_id; writes Bronze + Gold |
| `POST /Patient` + `If-None-Exist: identifier=...` | Conditional create |
| `GET /Patient/{id}` | Read current version from Gold |
| `PUT /Patient/{id}` + `If-Match: W/"N"` | Update with optimistic concurrency |
| `DELETE /Patient/{id}` | Soft delete (removes from Gold; Bronze history preserved) |
| `GET /Patient?identifier=system\|value` | Search |

All errors emit `OperationOutcome` per FHIR R4. Status mapping per [`docs/reference/api-reference.md`](../../docs/reference/api-reference.md).

## What it doesn't do yet

- **Auth.** No SMART scope check, no UDAP, no token introspection. Every request is treated as authorized. The five-point enforcement chain ([ADR-0006 §5](../../docs/decisions/0006-smart-on-fhir-and-udap-security.md)) is the next build.
- **Consent gate.** Per [ADR-0018 §5](../../docs/decisions/0018-patient-portal-consent-and-read-time-filter.md), point 5 of the enforcement chain.
- **Audit.** Five surfaces per [ADR-0016](../../docs/decisions/0016-audit-and-access-transparency.md) — none captured yet.
- **Other resources.** Patient only. Coverage / Observation / Encounter follow.
- **DLT promotion.** Bronze→Gold is synchronous in the same write today. v1.x moves it to the `silver_to_gold_blessing` pipeline per [ADR-0019 §5](../../docs/decisions/0019-storage-and-pipeline-operations.md).
- **Search beyond identifier.** Layer 4c materialization + the broader search routing per [ADR-0005](../../docs/decisions/0005-search-execution-model.md) — comes when other resources land.
- **Bulk Data `$export` / `$import`.** Python bulk-ingest tier is a separate package.

## Layout

```
src/
├── server.ts              # entry: load config, wire warehouse + repo + Hono, listen
├── app.ts                 # Hono composition
├── config.ts              # env → Config
├── lib/
│   ├── fhir-types.ts      # hand-rolled R4 types (Patient + common datatypes)
│   ├── uuid-v7.ts         # UUID v7 mint
│   ├── warehouse.ts       # Warehouse interface + InMemory + Databricks impls
│   └── errors.ts          # FhirError + OperationOutcome helpers
├── repository/
│   ├── schemas.ts         # Zod schemas (REST-boundary validation)
│   └── patient-repository.ts
└── routes/
    ├── health.ts
    ├── smart-config.ts
    ├── metadata.ts
    └── patient.ts

sql/
├── bronze/patient_r4.sql
├── gold/patient_r4_current.sql
└── pipelines/promote_patient_to_gold.sql

tests/
├── unit/
│   ├── uuid-v7.test.ts
│   └── patient-repository.test.ts
└── integration/
    └── patient-flow.test.ts

databricks/
├── databricks.yml         # DAB bundle definition
├── resources/
│   ├── app.yml            # Databricks App
│   └── schemas.yml        # UC schema declarations
└── app/
    └── app.yml            # App command + env
```

## Local dev

```bash
npm install
npm run typecheck
npm run test
npm run dev                # starts on :3000 with in-memory warehouse
```

Smoke test:

```bash
curl http://localhost:3000/health
curl http://localhost:3000/metadata | jq .fhirVersion
curl -X POST http://localhost:3000/Patient \
  -H 'Content-Type: application/fhir+json' \
  -d '{"resourceType":"Patient","name":[{"family":"Doe","given":["John"]}],"gender":"male","birthDate":"1985-01-15","identifier":[{"system":"http://hospital.org/mrn","value":"MRN-12345"}]}'
```

In-memory mode is automatic in `NODE_ENV=test` or when the Databricks env vars aren't set. To force in-memory in dev: `FHIRENGINE_WAREHOUSE_MODE=in-memory npm run dev`.

## Deploy to Databricks

```bash
cd databricks/
databricks bundle validate
databricks bundle deploy --target dev
databricks apps start ronin
```

Tables must exist before the app reads/writes. Apply DDL once via:

```bash
databricks sql query --warehouse-id <id> --file ../sql/bronze/patient_r4.sql
databricks sql query --warehouse-id <id> --file ../sql/gold/patient_r4_current.sql
```

Future iterations fold this into `scripts/ronin-install.sh` per [ADR-0021 §1](../../docs/decisions/0021-install-audit-and-runbooks.md).

## Configuration

Environment variables (see [`docs/reference/deployment-variables.md`](../../docs/reference/deployment-variables.md) for the full list):

| Variable | Default | Notes |
|---|---|---|
| `DATABRICKS_APP_PORT` / `PORT` | `3000` | Server port |
| `FHIRENGINE_PUBLIC_URL` | `http://localhost:3000` | For absolute Bundle references |
| `FHIRENGINE_CATALOG` | `ronin` | UC catalog |
| `FHIRENGINE_DEPLOYMENT_NAME` | `ronin-dev` | Operator-facing label |
| `FHIRENGINE_WAREHOUSE_MODE` | (unset) | `in-memory` forces stub warehouse |
| `DATABRICKS_HOST` | (none) | Workspace host (Apps inject) |
| `DATABRICKS_WAREHOUSE_HTTP_PATH` | (none) | Warehouse HTTP path |
| `DATABRICKS_TOKEN` / `DATABRICKS_CLIENT_SECRET` | (none) | Auth |
| `FHIRENGINE_LOG_LEVEL` | `info` | pino log level |

## Tests

```bash
npm run test           # all
npm run test:unit      # unit only
npm run test:integration
```

Coverage report via `npm run test -- --coverage`.

## Next builds

In rough priority order:

1. **SMART auth middleware** — RFC-7662 token introspection + scope canonicalization (ADR-0006 §5 points 1–4).
2. **Additional resources** — Coverage, Observation, Encounter. Generalize `PatientRepository` into a parameterized `ResourceRepository`.
3. **`AuditEvent` capture middleware** — write to `gold.audit_event_r4_current` per ADR-0016 §1.
4. **Consent gate** — point 5 of the enforcement chain per ADR-0018 §5.
5. **Patient/$everything** — uses the Patient compartment per ADR-0021 §7.
6. **Bulk Data `$export`** — together with the Python bulk-ingest tier.
