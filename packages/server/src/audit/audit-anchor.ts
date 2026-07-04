/**
 * External audit-chain anchoring (ADR-0035 follow-up). The hash chain (audit-integrity.ts) is
 * tamper-EVIDENT, but an attacker with full store access could rewrite the ENTIRE chain (recomputing
 * every hash) and hide edits. Anchoring closes that: periodically publish a signed snapshot of the
 * chain tip ({count, tip-hash, timestamp}) to an EXTERNAL, append-only sink (a second trust domain /
 * WORM logger). A rewritten or truncated chain then no longer matches the anchored history, and
 * forging past anchors needs the signing key the external sink holds a copy of.
 *
 *   FHIRENGINE_AUDIT_ANCHOR_WEBHOOK        POST each anchor here (the external immutable sink)
 *   FHIRENGINE_AUDIT_ANCHOR_KEY            PEM (PKCS8) private key → anchors are signed (JWS); optional
 *   FHIRENGINE_AUDIT_ANCHOR_INTERVAL_MIN   periodic anchoring interval (opt-in; off if unset)
 *
 * No new dependency (Node crypto + the existing `jose`).
 */
import { SignJWT, importPKCS8 } from "jose";
import { AUDIT_GENESIS, type AuditBackend, type AuditRow } from "./audit-integrity.js";

export interface AuditAnchor {
  count: number;   // number of records in the chain at anchor time
  tip: string;     // hash of the last record (AUDIT_GENESIS if empty)
  at: string;      // ISO timestamp
  jws?: string;    // detached signature over {count, tip, at} when a key is configured
}

/** Reconstruct chain order by following prev_hash → hash links from genesis. [] if empty/broken. */
export async function chainOrder(wh: AuditBackend): Promise<Array<AuditRow & { hash: string; prev_hash: string }>> {
  wh.registerAudit();
  const rows = await wh.query<AuditRow & { hash: string; prev_hash: string }>(
    "SELECT id, hash, prev_hash FROM audit_event",
  );
  const byPrev = new Map(rows.map((r) => [r.prev_hash, r]));
  const ordered: Array<AuditRow & { hash: string; prev_hash: string }> = [];
  const seen = new Set<string>();
  let cur = byPrev.get(AUDIT_GENESIS);
  while (cur && !seen.has(cur.hash)) {
    ordered.push(cur);
    seen.add(cur.hash);
    cur = byPrev.get(cur.hash);
  }
  return ordered;
}

/** Load the anchor signing key from FHIRENGINE_AUDIT_ANCHOR_KEY (PEM PKCS8), or null. */
async function anchorKey(env: NodeJS.ProcessEnv): Promise<Awaited<ReturnType<typeof importPKCS8>> | null> {
  const pem = env.FHIRENGINE_AUDIT_ANCHOR_KEY;
  if (!pem) return null;
  try { return await importPKCS8(pem, "RS256"); } catch { return null; }
}

/** Compute the current anchor (optionally signed). */
export async function computeAnchor(wh: AuditBackend, at: string, env: NodeJS.ProcessEnv = process.env): Promise<AuditAnchor> {
  const ordered = await chainOrder(wh);
  const tip = ordered.length ? ordered[ordered.length - 1]!.hash : AUDIT_GENESIS;
  const anchor: AuditAnchor = { count: ordered.length, tip, at };
  const key = await anchorKey(env);
  if (key) {
    anchor.jws = await new SignJWT({ count: anchor.count, tip: anchor.tip, at: anchor.at })
      .setProtectedHeader({ alg: "RS256", typ: "audit-anchor" })
      .setIssuedAt().sign(key);
  }
  return anchor;
}

export interface AnchorVerification { ok: boolean; reason?: string }

/**
 * Verify the current chain is consistent with a previously-published anchor. Detects a chain that was
 * truncated below the anchored count, or rewritten so the record at the anchored position no longer
 * hashes to the anchored tip.
 */
export async function verifyAgainstAnchor(wh: AuditBackend, anchor: AuditAnchor): Promise<AnchorVerification> {
  const ordered = await chainOrder(wh);
  if (ordered.length < anchor.count) {
    return { ok: false, reason: `chain truncated below anchored count (${ordered.length} < ${anchor.count})` };
  }
  const tipAtAnchor = anchor.count === 0 ? AUDIT_GENESIS : ordered[anchor.count - 1]?.hash;
  if (tipAtAnchor !== anchor.tip) {
    return { ok: false, reason: "chain history diverges from the anchored tip (rewritten)" };
  }
  return { ok: true };
}

/** Publish an anchor to the external sink (webhook). No-op if none configured. */
export async function publishAnchor(anchor: AuditAnchor, env: NodeJS.ProcessEnv = process.env): Promise<void> {
  const url = env.FHIRENGINE_AUDIT_ANCHOR_WEBHOOK;
  if (!url) return;
  await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(anchor) });
}

export interface AnchorLogger { info: (o: unknown, m?: string) => void; error: (o: unknown, m?: string) => void }

/**
 * Opt-in periodic anchoring: compute + publish an anchor every FHIRENGINE_AUDIT_ANCHOR_INTERVAL_MIN.
 * Returns a stop() (or null if disabled). Failures are logged, never thrown.
 */
export function startAuditAnchorScheduler(wh: AuditBackend, log?: AnchorLogger, env: NodeJS.ProcessEnv = process.env): (() => void) | null {
  const minutes = Number(env.FHIRENGINE_AUDIT_ANCHOR_INTERVAL_MIN);
  if (!Number.isFinite(minutes) || minutes <= 0) return null;
  let running = false;
  const tick = async (): Promise<void> => {
    if (running) return;
    running = true;
    try {
      const anchor = await computeAnchor(wh, new Date().toISOString(), env);
      await publishAnchor(anchor, env);
      log?.info({ count: anchor.count, signed: Boolean(anchor.jws) }, "audit chain anchored");
    } catch (err) {
      log?.error({ err }, "audit anchoring failed");
    } finally {
      running = false;
    }
  };
  const handle = setInterval(() => void tick(), minutes * 60_000);
  handle.unref?.();
  return () => clearInterval(handle);
}
