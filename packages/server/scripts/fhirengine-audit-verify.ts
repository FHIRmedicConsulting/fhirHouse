/**
 * fhirengine-audit-verify — verify the tamper-evidence of the AuditEvent hash chain (ADR-0035).
 * Reports whether the audit log has been edited, had records deleted, or forked. Read-only.
 *
 * Usage:
 *   FHIRENGINE_DELTA_SIDECAR_URL=... FHIRENGINE_DELTA_BASE=... npx tsx scripts/fhirengine-audit-verify.ts
 * Exit code 0 = intact, 1 = tampering detected / error.
 */
import { DeltaWarehouse } from "../src/lib/delta-warehouse.js";
import { verifyAuditChain } from "../src/audit/audit-integrity.js";

async function main(): Promise<void> {
  const wh = new DeltaWarehouse({
    sidecarUrl: process.env.FHIRENGINE_DELTA_SIDECAR_URL ?? "http://127.0.0.1:8077",
    base: process.env.FHIRENGINE_DELTA_BASE ?? "./delta",
  });
  if (!(await wh.health())) throw new Error("delta sidecar not reachable (set FHIRENGINE_DELTA_SIDECAR_URL)");

  const result = await verifyAuditChain(wh);
  if (result.ok) {
    console.log(`audit chain OK — ${result.total} record(s), chain intact`);
    return;
  }
  console.error(`audit chain FAILED — ${result.total} record(s), ${result.issues.length} issue(s):`);
  for (const i of result.issues) console.error(`  - ${i}`);
  process.exit(1);
}

main().catch((err) => {
  console.error("audit verify error:", err instanceof Error ? err.message : err);
  process.exit(1);
});
