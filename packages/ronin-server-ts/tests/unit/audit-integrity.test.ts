/**
 * Audit hash-chain tamper-evidence (ADR-0035): append links records; verify detects content
 * tampering, deletion, and forks. Uses an in-memory fake backend (no sidecar).
 */
import { describe, it, expect } from "vitest";
import {
  AuditChain, verifyAuditChain, auditHash, AUDIT_GENESIS,
  type AuditBackend, type AuditRow,
} from "../../src/audit/audit-integrity.js";

class FakeAudit implements AuditBackend {
  rows: AuditRow[] = [];
  async writeAudit(row: AuditRow): Promise<void> { this.rows.push({ ...row }); }
  registerAudit(): void { /* no-op */ }
  async query<T>(sql: string): Promise<T[]> {
    if (/LIMIT 1/.test(sql)) {
      const sorted = [...this.rows].sort(
        (a, b) => String(b.recorded).localeCompare(String(a.recorded)) || String(b.id).localeCompare(String(a.id)),
      );
      return (sorted.length ? [{ hash: sorted[0]!.hash }] : []) as T[];
    }
    return this.rows.map((r) => ({ ...r })) as T[];
  }
}

const mkRow = (i: number): AuditRow => ({
  id: `evt-${i}`, recorded: `2026-07-04T00:00:0${i}Z`, action: "R", outcome: "0",
  subtype: "read", agent_who: "Practitioner/x", entity_ref: `Patient/p${i}`, patient: `p${i}`,
  body_json: JSON.stringify({ resourceType: "AuditEvent", id: `evt-${i}` }),
});

describe("audit hash chain", () => {
  it("auditHash is deterministic and prev-sensitive", () => {
    const r = mkRow(1);
    expect(auditHash(AUDIT_GENESIS, r)).toBe(auditHash(AUDIT_GENESIS, r));
    expect(auditHash(AUDIT_GENESIS, r)).not.toBe(auditHash("ff".repeat(32), r));
  });

  it("links records: first is genesis, each points at the previous", async () => {
    const wh = new FakeAudit();
    const chain = new AuditChain(wh);
    for (let i = 0; i < 3; i++) await chain.append(mkRow(i));
    expect(wh.rows).toHaveLength(3);
    expect(wh.rows[0]!.prev_hash).toBe(AUDIT_GENESIS);
    expect(wh.rows[1]!.prev_hash).toBe(wh.rows[0]!.hash);
    expect(wh.rows[2]!.prev_hash).toBe(wh.rows[1]!.hash);
    const v = await verifyAuditChain(wh);
    expect(v).toMatchObject({ ok: true, total: 3, issues: [] });
  });

  it("detects content tampering", async () => {
    const wh = new FakeAudit();
    const chain = new AuditChain(wh);
    for (let i = 0; i < 3; i++) await chain.append(mkRow(i));
    (wh.rows[1] as AuditRow).body_json = JSON.stringify({ resourceType: "AuditEvent", id: "evt-1", tampered: true });
    const v = await verifyAuditChain(wh);
    expect(v.ok).toBe(false);
    expect(v.issues.join(" ")).toMatch(/content hash mismatch/);
  });

  it("detects a deleted record (broken prev link)", async () => {
    const wh = new FakeAudit();
    const chain = new AuditChain(wh);
    for (let i = 0; i < 3; i++) await chain.append(mkRow(i));
    wh.rows.splice(1, 1); // delete the middle record
    const v = await verifyAuditChain(wh);
    expect(v.ok).toBe(false);
    expect(v.issues.join(" ")).toMatch(/prev_hash missing/);
  });

  it("detects deletion of the genesis (head) record", async () => {
    const wh = new FakeAudit();
    const chain = new AuditChain(wh);
    for (let i = 0; i < 3; i++) await chain.append(mkRow(i));
    wh.rows.shift(); // remove genesis
    const v = await verifyAuditChain(wh);
    expect(v.ok).toBe(false);
    expect(v.issues.join(" ")).toMatch(/no genesis|prev_hash missing/);
  });

  it("resumes the chain across a restart (re-seeds from the stored tip)", async () => {
    const wh = new FakeAudit();
    await new AuditChain(wh).append(mkRow(0));
    await new AuditChain(wh).append(mkRow(1)); // fresh chain instance, same store
    expect(wh.rows[1]!.prev_hash).toBe(wh.rows[0]!.hash); // continued, not a new genesis
    expect((await verifyAuditChain(wh)).ok).toBe(true);
  });
});
