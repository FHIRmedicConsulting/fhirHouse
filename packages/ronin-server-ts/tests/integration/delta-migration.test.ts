/**
 * is_current schema migration (#10): a Bronze table populated before is_current existed lacks the
 * column, so `WHERE is_current` search breaks. migrateIsCurrent backfills it (max version per id =
 * current). Own base — writes a raw "legacy" table. Sidecar-gated.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";

const SIDECAR = process.env.RONIN_DELTA_SIDECAR_URL;
const ts = Date.now();
const BASE = `${process.env.RONIN_DELTA_BASE ?? "./.delta-test"}-migrate-${ts}`;
const ID = `mig-${ts}`;

describe.skipIf(!SIDECAR)("is_current schema migration", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE }) : (null as unknown as DeltaWarehouse);
  const legacyRow = (v: number) => ({
    id: ID, version_id: v, last_updated: `2026-01-0${v}T00:00:00Z`,
    body_json: JSON.stringify({ resourceType: "Basic", id: ID }),
    identifier_index: [], search_param_index: [], ext_json: "{}", deleted: false,
    _ingested_at: "2026-01-01T00:00:00Z", _ingest_source: "legacy-test",
    // NOTE: no is_current — simulates a pre-migration table.
  });

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    // schema:"infer" so the written table has exactly these columns (no is_current).
    await wh.writeTier("bronze", "Basic", [legacyRow(1), legacyRow(2)], "infer");
  });

  it("a pre-migration table lacks is_current (search would break)", async () => {
    await expect(wh.query("SELECT is_current FROM basic LIMIT 1")).rejects.toThrow();
  });

  it("migrateIsCurrent backfills the column (max version per id = current)", async () => {
    const r: any = await wh.migrateIsCurrent("Basic");
    expect(r.migrated).toBe(true);
    expect(r.rows).toBe(2);
    const rows = await wh.query<{ version_id: number; is_current: boolean }>(
      "SELECT version_id, is_current FROM basic ORDER BY version_id",
    );
    expect(rows.map((x) => [Number(x.version_id), x.is_current])).toEqual([[1, false], [2, true]]);
    const cur = await wh.query<{ n: number }>("SELECT count(*) AS n FROM basic WHERE is_current");
    expect(Number(cur[0]!.n)).toBe(1);
  });

  it("migration is idempotent (already-migrated → no-op)", async () => {
    const r: any = await wh.migrateIsCurrent("Basic");
    expect(r.migrated).toBe(false);
    expect(r.already).toBe(true);
  });
});
