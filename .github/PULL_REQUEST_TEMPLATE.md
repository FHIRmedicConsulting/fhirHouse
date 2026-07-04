<!-- Thanks for contributing! Keep changes focused. -->

## What & why

<!-- What does this change and why? Link the issue: Closes #… -->

## How tested

<!-- Commands run + result. e.g. npm run typecheck/lint/test:unit, sidecar pytest, test:delta -->

## Checklist

- [ ] `npm run typecheck` + `npm run lint` pass
- [ ] `npm run test:unit` passes; new/changed behavior has tests
- [ ] Integration (`npm run test:delta`) / sidecar `pytest tests/` run if the change touches storage
- [ ] **No PHI** and **no secrets** in code, tests, fixtures, or logs (synthetic data only)
- [ ] No new dependency, or it's justified above (prefer built-ins)
- [ ] Architecture-significant? An ADR is added/updated and referenced
- [ ] Docs/`STATUS.md` updated; claims kept honest (no advertising unimplemented behavior)
