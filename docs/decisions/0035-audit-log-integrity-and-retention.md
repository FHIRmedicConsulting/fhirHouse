# ADR-0035: Audit-Log Integrity (tamper-evidence) & Retention

- Status: **Accepted** 2026-07-04 (Chad — security-infrastructure build; "each item has what it needs")
- Date: 2026-07-04
- Decider(s): Chad
- Session: standalone security hardening (Scope-1 deferred items)
- Related: [ADR-0016](0016-audit-and-access-transparency.md) (audit & access transparency), [ADR-0030](0030-standalone-security-privacy-consent-enforcement.md) (enforcement), [ADR-0010](0010-storage-shape.md) (integrity/provenance), [[phi-security-standards]]

## Context

HIPAA §164.312(b) (audit controls) + (c)(1) (integrity) require that audit records be trustworthy —
you must be able to detect if the audit trail was altered or truncated. In the heritage Databricks
product this leaned on **Unity Catalog RBAC + table history**, which **does not exist** in the OSS-Delta
standalone. The delta audit sink (ADR-0030 #2) writes append-only AuditEvents but had **no
tamper-evidence**: a writer with store access could edit or delete rows undetected.

The server cannot *prevent* tampering by someone with storage access (that needs external
WORM/object-lock or an external notary/signing service) — but it **can** make tampering
**detectable**, which is the achievable and standard server-side control.

## Decision

Add a **hash chain** over the audit store (`src/audit/audit-integrity.ts`):

- Each record carries `prev_hash` + `hash = SHA-256(prev_hash + canonical-content)`. `AuditChain`
  assigns them and **serializes** hash-assignment + durable write so concurrent audit writes form one
  linear chain; the chain tip re-seeds from the newest stored record on restart. `lastHash` advances
  only after a successful write.
- **`verifyAuditChain(wh)`** re-derives every record's hash and checks the links — detecting (a)
  content edits (hash mismatch), (b) deleted records (dangling `prev_hash` / missing genesis), and
  (c) forks/resets (>1 genesis). Exposed as the **`ronin-audit-verify`** operator CLI (read-only).
- **Retention:** the audit store is **append-only and never rewritten** by the app; store maintenance
  (OPTIMIZE/VACUUM) only compacts files and reclaims tombstones of *superseded* versions — it does not
  delete audit records. `RONIN_AUDIT_RETENTION_DAYS` (documented default 2190 = 6 years) is the
  operator-facing minimum-retention knob; enforcing hard WORM/object-lock is a deployment concern.

## Consequences

- (+) Tamper-**evidence** with no new dependency (Node `crypto`); unit-tested (edit/delete/fork/restart).
  Gives the standalone its own §164.312(b)(c) integrity story independent of Databricks UC.
- (+) Verifiable on demand (`ronin-audit-verify`) — supports incident response / audit review.
- (+) **External anchoring implemented** (`src/audit/audit-anchor.ts`): an opt-in scheduler
  (`RONIN_AUDIT_ANCHOR_INTERVAL_MIN`) publishes a **signed** chain-tip snapshot `{count, tip, at}`
  (`RONIN_AUDIT_ANCHOR_KEY`) to an external append-only sink (`RONIN_AUDIT_ANCHOR_WEBHOOK`).
  `verifyAgainstAnchor` then detects a chain that was **truncated** or **fully rewritten** — the case
  the hash chain alone cannot catch (a rewritten chain is internally consistent). This addresses the
  former "tamper-proof needs external anchoring" gap. Signing + external immutability mean forging past
  anchors needs the key the external sink holds.
- (−) Residual: the external sink's immutability/WORM guarantees + long-term anchor storage are an
  **operator/deployment** responsibility; live CRL/OCSP-style automated anchor verification tooling is
  a follow-up.
- (−) Schema: fresh audit tables get `prev_hash`/`hash` from the first write; **pre-existing** audit
  tables need a one-time schema add before they chain (dev stores are disposable — not an issue for
  Alpha). Continuous external anchoring + WORM object-lock are the post-Alpha hardening steps.
