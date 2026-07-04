# `@fhirengine/server` — fhirEngine FHIR R4 REST server

The TypeScript/Hono FHIR R4 server on OSS Delta Lake: full REST surface (CRUD, history,
search, batch/transaction, `$everything`, `$export`, `$validate`), validation prior to
Bronze, a local terminology service, and opt-in security controls (SMART auth + Backend
Services + UDAP, hash-chained audit, consent/DS4P enforcement). Storage is delta-rs /
DataFusion via the Python sidecar in [`sidecar/`](sidecar/).

See the [root README](../../README.md) for architecture and quickstart, and
[`STATUS.md`](../../STATUS.md) for what works today.

## Run

```bash
npm run init        # guided setup — writes deploy/.env, prints run + provisioning steps
npm run dev         # tsx watch (needs the sidecar running; see the root quickstart)
```

## Develop

| Command | What |
|---|---|
| `npm run test:unit` | unit tests (no sidecar) |
| `npm run test:delta` | Delta integration tests (needs a running sidecar) |
| `npm run test:coverage` | unit + delta with coverage thresholds |
| `npm run typecheck` / `npm run lint` | static checks |
| `npx tsx scripts/fhirengine-terminology.ts` | provisioning CLI (install-ig, load-terminology, expand-vsac, optimize…) |
| `npx tsx scripts/fhirengine-audit-verify.ts` | verify the tamper-evident audit chain |

Configuration is env-driven — full reference in
[`docs/standalone/configuration.md`](../../docs/standalone/configuration.md) and
[`deploy/.env.example`](../../deploy/.env.example).
