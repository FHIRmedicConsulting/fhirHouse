/**
 * Medallion serving semantics (FHIRENGINE_STORAGE_MODE=medallion):
 *   - API writes land in BRONZE (the write domain / version chain).
 *   - Reads + searches serve from GOLD — populated ONLY by promotion (external
 *     orchestration in production; promote() here). A just-ingested resource is
 *     NOT servable until promoted (eventual consistency by design).
 *   - history/vread stay on Bronze (the version log; Gold is current-version only).
 * Single-store behavior is covered by every other integration suite.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { DeltaResourceRepository } from "../../src/repository/delta-resource-repository.js";
import { promote } from "../../src/repository/promote.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = `${process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test"}-medallion-${Date.now()}`;

describe.skipIf(!SIDECAR)("Medallion mode — Bronze ingest, Gold serving", () => {
  const wh = SIDECAR
    ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE, storageMode: "medallion" })
    : (null as unknown as DeltaWarehouse);
  const repo = () => new DeltaResourceRepository(wh, "Patient");
  const id = `med-${Date.now()}`;

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error(`sidecar not reachable at ${SIDECAR}`);
  });

  afterAll(() => { delete process.env.FHIRENGINE_STORAGE_MODE; });

  it("ingest lands in Bronze but is NOT served before promotion", async () => {
    await repo().create({ resourceType: "Patient", id, gender: "female" } as never);
    // Write domain sees it (version chain exists) …
    const hist = await repo().history(id);
    expect(hist.length).toBe(1);
    // … but the serve tier (Gold) doesn't, until promotion runs.
    await expect(repo().read(id)).rejects.toMatchObject({ status: 404 });
    const s = await repo().searchByParams({ conds: [], count: 10, offset: 0 });
    expect(s.total).toBe(0);
  });

  it("after promotion, Gold serves read + search", async () => {
    const r = await promote(wh, "Patient");
    expect(r.gold).toBeGreaterThanOrEqual(1);
    const got = await repo().read(id);
    expect(got.id).toBe(id);
    const s = await repo().searchByParams({ conds: [], count: 10, offset: 0 });
    expect(s.total).toBe(1);
  });

  it("updates version in Bronze; Gold serves the OLD version until re-promoted", async () => {
    await repo().update(id, { resourceType: "Patient", id, gender: "male" } as never, null);
    const before = await repo().read(id);
    expect((before as { gender?: string }).gender).toBe("female"); // stale by design
    await promote(wh, "Patient");
    const after = await repo().read(id);
    expect((after as { gender?: string }).gender).toBe("male");
    // history reflects both versions (Bronze version log)
    expect((await repo().history(id)).length).toBe(2);
  });

  it("delete tombstones propagate through promotion (410 from Gold)", async () => {
    await repo().delete(id);
    await promote(wh, "Patient");
    await expect(repo().read(id)).rejects.toMatchObject({ status: 410 });
    const s = await repo().searchByParams({ conds: [], count: 10, offset: 0 });
    expect(s.total).toBe(0);
  });
});
