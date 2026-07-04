/**
 * Audit hash-chain tamper-evidence (ADR-0035): append links records; verify detects content
 * tampering, deletion, and forks. Uses an in-memory fake backend (no sidecar).
 */
import { describe, it, expect } from "vitest";
import { generateKeyPair, exportPKCS8 } from "jose";
import {
  AuditChain, verifyAuditChain, auditHash, AUDIT_GENESIS,
  type AuditBackend, type AuditRow,
} from "../../src/audit/audit-integrity.js";
import { computeAnchor, verifyAgainstAnchor } from "../../src/audit/audit-anchor.js";

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

const mkRow = (i: number, over: Partial<AuditRow> = {}): AuditRow => ({
  id: `evt-${i}`, recorded: `2026-07-04T00:00:0${i}Z`, action: "R", outcome: "0",
  subtype: "read", agent_who: "Practitioner/x", entity_ref: `Patient/p${i}`, patient: `p${i}`,
  body_json: JSON.stringify({ resourceType: "AuditEvent", id: `evt-${i}` }),
  ...over,
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

describe("external audit anchoring", () => {
  const build = async (n: number) => {
    const wh = new FakeAudit();
    const chain = new AuditChain(wh);
    for (let i = 0; i < n; i++) await chain.append(mkRow(i));
    return wh;
  };

  it("an anchor matches the current chain", async () => {
    const wh = await build(4);
    const anchor = await computeAnchor(wh, "2026-07-04T00:00:00Z");
    expect(anchor.count).toBe(4);
    expect(anchor.tip).toBe(wh.rows[3]!.hash);
    expect((await verifyAgainstAnchor(wh, anchor)).ok).toBe(true);
  });

  it("detects truncation below the anchored count", async () => {
    const wh = await build(4);
    const anchor = await computeAnchor(wh, "t");
    wh.rows.pop(); // records deleted after anchoring
    const v = await verifyAgainstAnchor(wh, anchor);
    expect(v.ok).toBe(false);
    expect(v.reason).toMatch(/truncated/);
  });

  it("detects a FULL rewrite (internally-consistent chain that diverges from the anchor)", async () => {
    const wh = await build(4);
    const anchor = await computeAnchor(wh, "t");
    // Attacker rewrites the whole chain, altering record 1 and recomputing every hash:
    wh.rows = [];
    const chain = new AuditChain(wh);
    for (let i = 0; i < 4; i++) await chain.append(mkRow(i, i === 1 ? { body_json: '{"tampered":true}' } : {}));
    expect((await verifyAuditChain(wh)).ok).toBe(true);          // internally consistent — hash chain alone can't tell
    expect((await verifyAgainstAnchor(wh, anchor)).ok).toBe(false); // ...but the external anchor catches it
  });

  it("signs the anchor when a key is configured", async () => {
    const wh = await build(2);
    expect((await computeAnchor(wh, "t", {})).jws).toBeUndefined(); // no key → unsigned
    const kp = await generateKeyPair("RS256", { extractable: true });
    const env = { FHIRENGINE_AUDIT_ANCHOR_KEY: await exportPKCS8(kp.privateKey) } as unknown as NodeJS.ProcessEnv;
    const signed = await computeAnchor(wh, "t", env);
    expect(typeof signed.jws).toBe("string"); // JWS over {count, tip, at}
  });
});
