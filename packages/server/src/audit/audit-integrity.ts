/**
 * Audit-log tamper-evidence (ADR-0035) — a hash chain over the append-only AuditEvent store.
 *
 * Each record carries `prev_hash` (the hash of the previous record) and `hash = SHA-256(prev_hash +
 * content)`. Any edit to a record's content breaks its own hash; deleting a record breaks the next
 * record's `prev_hash` link; re-ordering/forking yields >1 genesis. `verifyAuditChain` detects all
 * three. This gives the standalone build its own integrity story (HIPAA §164.312(b) audit controls +
 * (c)(1) integrity) instead of relying on the heritage Databricks Unity Catalog RBAC, which does not
 * exist here.
 *
 * The chain does not *prevent* tampering (that needs external WORM storage / signing) — it makes
 * tampering **detectable**, which is the achievable server-side guarantee for Alpha.
 */
import { createHash } from "node:crypto";
import type { WarehouseRow } from "../lib/warehouse.js";

/** Head-of-chain sentinel (the first record's prev_hash). */
export const AUDIT_GENESIS = "0".repeat(64);

/** Fields hashed into the chain (everything meaningful; `body_json` is the full AuditEvent). */
const CONTENT_FIELDS = [
  "id", "recorded", "action", "outcome", "subtype", "agent_who", "entity_ref", "patient", "body_json",
] as const;

export type AuditRow = Record<string, unknown>;

/** Stable serialization of a record's content (excludes prev_hash/hash). */
export function auditContentString(row: AuditRow): string {
  return CONTENT_FIELDS.map((f) => `${f}=${row[f] ?? ""}`).join("\n");
}

/** hash = SHA-256(prev_hash + "\n" + content). */
export function auditHash(prevHash: string, row: AuditRow): string {
  return createHash("sha256").update(`${prevHash}\n${auditContentString(row)}`).digest("hex");
}

/** Minimal backend the chain needs (DeltaWarehouse satisfies this; tests inject a fake). */
export interface AuditBackend {
  writeAudit(row: AuditRow): Promise<void>;
  registerAudit(): void;
  query<T extends WarehouseRow = WarehouseRow>(sql: string, params?: unknown[]): Promise<T[]>;
}

/**
 * Serializes hash assignment + durable write so concurrent audit writes form a single linear chain.
 * `lastHash` advances **only after** a successful write (a failed write is not in the chain).
 */
export class AuditChain {
  private lastHash: string | null = null; // null = not yet seeded from the store
  private tail: Promise<unknown> = Promise.resolve();

  constructor(private readonly wh: AuditBackend) {}

  append(row: AuditRow): Promise<void> {
    const run = this.tail.then(async () => {
      if (this.lastHash === null) this.lastHash = await this.loadTip();
      const prev = this.lastHash;
      row.prev_hash = prev;
      row.hash = auditHash(prev, row);
      await this.wh.writeAudit(row);
      this.lastHash = row.hash as string; // durable → advance
    });
    // Keep the serialization chain alive even if one write rejects; the caller still sees the error.
    this.tail = run.catch(() => undefined);
    return run;
  }

  /** Seed from the newest persisted record's hash (chain survives restarts), else genesis. */
  private async loadTip(): Promise<string> {
    try {
      this.wh.registerAudit();
      const rows = await this.wh.query<{ hash: string }>(
        "SELECT hash FROM audit_event ORDER BY recorded DESC, id DESC LIMIT 1",
      );
      return rows[0]?.hash || AUDIT_GENESIS;
    } catch {
      return AUDIT_GENESIS; // fresh store or no hash column yet
    }
  }
}

export interface ChainVerification {
  ok: boolean;
  total: number;
  issues: string[];
}

/**
 * Verify the whole audit chain. Detects: (a) content tampering (recomputed hash ≠ stored hash),
 * (b) deletion (a record's prev_hash points at no existing record; or the genesis was removed),
 * (c) fork/reset (more than one genesis record).
 */
export async function verifyAuditChain(wh: AuditBackend): Promise<ChainVerification> {
  wh.registerAudit();
  const rows = await wh.query<AuditRow & { prev_hash: string; hash: string }>(
    "SELECT id, recorded, action, outcome, subtype, agent_who, entity_ref, patient, body_json, prev_hash, hash FROM audit_event",
  );
  const issues: string[] = [];
  const hashes = new Set(rows.map((r) => r.hash));
  let genesis = 0;

  for (const r of rows) {
    if (auditHash(r.prev_hash, r) !== r.hash) issues.push(`record ${r.id}: content hash mismatch (tampered or corrupted)`);
    if (r.prev_hash === AUDIT_GENESIS) genesis += 1;
    else if (!hashes.has(r.prev_hash)) issues.push(`record ${r.id}: prev_hash missing (a prior record was deleted)`);
  }
  if (rows.length > 0 && genesis === 0) issues.push("no genesis record — the head of the chain was deleted");
  if (genesis > 1) issues.push(`multiple genesis records (${genesis}) — chain fork or reset`);

  return { ok: issues.length === 0, total: rows.length, issues };
}
