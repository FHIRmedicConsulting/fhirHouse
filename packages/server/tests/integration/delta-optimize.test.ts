/**
 * Store maintenance (Priority #1): Delta OPTIMIZE + Z-ORDER + VACUUM across the whole store.
 * Append-per-write makes many small files; optimize-all compacts them, clusters Bronze by `id`
 * (data skipping for id-keyed access), and vacuum reclaims tombstoned files — while every table
 * stays queryable. Gated on the sidecar.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test";

describe.skipIf(!SIDECAR)("store maintenance — optimize + vacuum", () => {
  const ts = Date.now();
  // Own, freshly-isolated base so file counts reflect only this test's writes (not a warm/shared
  // store already compacted by a prior run) — the source of the old flakiness.
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: `${BASE}-opt-${ts}` }) : (null as unknown as DeltaWarehouse);
  const app = SIDECAR ? createDeltaApp({ warehouse: wh, baseUrl: "http://test" }) : (null as unknown as ReturnType<typeof createDeltaApp>);
  const req = (m: string, p: string, b?: unknown) =>
    app.fetch(new Request(`http://test${p}`, { method: m, headers: { "Content-Type": "application/fhir+json" }, body: b ? JSON.stringify(b) : undefined }));

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    // 25 separate creates → 25 small Bronze files (append-per-write)
    for (let i = 0; i < 25; i++) {
      await req("POST", "/Patient", { resourceType: "Patient", id: `opt${ts}-${i}`, name: [{ family: `O${i}` }] });
    }
  });

  it("optimize-all clusters Bronze by id + preserves data (safe compaction)", async () => {
    const report: any = await wh.optimizeAll({ vacuum: false });
    expect(report.tables_optimized).toBeGreaterThanOrEqual(1);
    const patient = report.results["bronze/patient"];
    expect(patient).toBeTruthy();
    // Behavioral invariants (not a brittle absolute file count — the current-version MERGE write
    // path coalesces, so the count depends on the write path, not on optimize):
    expect(patient.files_after).toBeLessThanOrEqual(patient.files_before); // compaction never increases files
    expect(patient.zorder).toEqual(["id"]);                                // clustered by id
    expect((await (await req("GET", `/Patient?_count=100`)).json()).total).toBe(25); // no data lost
    // (Actual small-file → fewer-files compaction is unit-tested at the sidecar layer, where the
    //  append path can be controlled: sidecar/tests/test_delta_sidecar.py::test_optimize_compacts.)
  });

  it("--no-zorder falls back to plain compaction (no clustering)", async () => {
    // create a couple more small files first so there is something to compact
    for (let i = 100; i < 104; i++) await req("POST", "/Patient", { resourceType: "Patient", id: `opt${ts}-${i}` });
    const report: any = await wh.optimizeAll({ vacuum: false, zorder: false });
    expect(report.results["bronze/patient"].zorder).toBeNull(); // plain compact, no z-order
  });

  it("the table is still fully queryable after optimize", async () => {
    const b = await (await req("GET", `/Patient?_id=opt${ts}-7`)).json();
    expect(b.total).toBe(1);
    expect(b.entry[0].resource.id).toBe(`opt${ts}-7`);
  });

  it("vacuum (force, retention 0) reclaims the now-unreferenced pre-compaction files", async () => {
    const report: any = await wh.optimizeAll({ vacuum: true, retentionHours: 0, force: true });
    const patient = report.results["bronze/patient"];
    expect(patient.vacuumed_files).toBeGreaterThanOrEqual(1); // old small files physically removed
    // still queryable after vacuum
    expect((await (await req("GET", `/Patient?_id=opt${ts}-3`)).json()).total).toBe(1);
  });
});
