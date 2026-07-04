# Contributing to RoninStandAlone

Thanks for your interest! RoninStandAlone is an open-source (Apache-2.0) FHIR R4 server. It is
**pre-alpha** — expect churn. This guide gets you productive fast.

## Ground rules (important — health data)

- **Never commit PHI.** Use **synthetic data only** (Synthea). Reports, tests, issues, and logs must
  contain no real patient data.
- **Never commit secrets.** Secrets go through a secrets manager / 1Password `op run`; only
  `*.env.op` reference files are tracked. CI runs gitleaks + Trivy.
- **Report vulnerabilities privately** — see [SECURITY.md](SECURITY.md), not a public issue.

## Project layout

- `packages/ronin-server-ts/` — the TypeScript/Hono FHIR server (+ `sidecar/` = the Python
  delta-rs/DataFusion storage sidecar).
- `docs/decisions/` — ADRs (architecture decisions). Significant changes need an ADR.
- `docs/standalone/` — product/deployment/config/security docs. `deploy/` — Docker artifacts.

## Dev setup

Prereqs: Node ≥ 20 (CI uses 22), Python 3.12.

```bash
cd packages/ronin-server-ts
npm ci

# Start the storage sidecar (needed for integration + running the server)
cd sidecar && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
python delta_sidecar.py --port 8077 --base ./.delta &
cd ..

# Run the server
RONIN_DELTA_SIDECAR_URL=http://127.0.0.1:8077 RONIN_DELTA_BASE=./.delta npx tsx src/server.ts
```

## Tests & checks (run before opening a PR)

```bash
# From packages/ronin-server-ts:
npm run typecheck
npm run lint            # eslint --max-warnings 0
npm run test:unit       # fast, no sidecar
npm run test:delta      # integration — needs the sidecar running (RONIN_DELTA_SIDECAR_URL)

# Sidecar (from packages/ronin-server-ts/sidecar):
pytest tests/
```

CI runs all of the above plus a supply-chain scan (npm audit + SBOM + pip-audit + gitleaks + Trivy)
and a server-boot smoke test. PRs must be green.

## Making changes

- **Match the surrounding code** — naming, comment density, and idiom. Keep changes focused.
- **Add tests** for new behavior. Don't weaken existing assertions to make a test pass.
- **Architecture-significant changes need an ADR** (`docs/decisions/NNNN-*.md`, next number, never
  reused) referenced from the PR.
- **No new dependency without disclosure** — add it to the reasoning in your PR; prefer built-ins.
  The security controls ship with zero net-new runtime deps.
- Keep claims **honest** — don't advertise capabilities the code doesn't implement (see `STATUS.md`).

## Commit & PR

- Clear, imperative commit subjects (a `type(scope): summary` convention is used but not enforced).
- Fill in the PR template. Link the issue. Describe testing.
- By contributing you agree your contributions are licensed under **Apache-2.0**. (A formal CLA/DCO
  may be added before GA — see ADR-0023.)

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be respectful.
