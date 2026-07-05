/**
 * MPI / dedup ENFORCED at promotion (ADR-0012 v1 deterministic, in the medallion path):
 * duplicate Patients (shared MRN) merge at Bronze→Silver/Gold; the survivor is the golden
 * record (absorbs the merged identifiers for search); the merged record stays readable by
 * id with a replaced-by link but is excluded from search; downstream references
 * (Observation.subject) are rewritten to the survivor; MPI tables + merge Provenance land.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { DeltaResourceRepository } from "../../src/repository/delta-resource-repository.js";
import { promote, loadSurvivorMap } from "../../src/repository/promote.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = `${process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test"}-mpi-${Date.now()}`;
const MRN = "urn:oid:1.2.840.114350.99";

describe.skipIf(!SIDECAR)("MPI dedup enforced in Silver/Gold promotion", () => {
  const wh = SIDECAR
    ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE, storageMode: "medallion" })
    : (null as unknown as DeltaWarehouse);
  const patients = () => new DeltaResourceRepository(wh, "Patient");
  const obs = () => new DeltaResourceRepository(wh, "Observation");
  const run = `mpi${Date.now()}`;
  const OLD = `${run}-old`;   // earlier duplicate (merged away)
  const NEW = `${run}-new`;   // later duplicate (survivor)
  const OTHER = `${run}-other`;

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error(`sidecar not reachable at ${SIDECAR}`);
    const mk = (id: string, mrn: string, gender: string) => ({
      resourceType: "Patient", id, gender,
      identifier: [{ system: MRN, value: mrn }],
    });
    await patients().create(mk(OLD, "MRN-DUP", "female") as never);
    await new Promise((r) => setTimeout(r, 25)); // distinct last_updated → NEW survives
    await patients().create(mk(NEW, "MRN-DUP", "female") as never);
    await patients().create(mk(OTHER, "MRN-OTHER", "male") as never);
    await obs().create({
      resourceType: "Observation", id: `${run}-obs`, status: "final",
      code: { text: "hr" }, subject: { reference: `Patient/${OLD}` },
    } as never);
    // Patient first (produces the merge map), then Observation with the map — as the CLI does.
    await promote(wh, "Patient");
    await promote(wh, "Observation", { survivorOf: await loadSurvivorMap(wh) });
  }, 60_000);

  it("duplicates merged: survivor serves; search returns ONE golden record", async () => {
    const s = await patients().searchByParams({
      conds: [{ code: "identifier", system: MRN, value: "MRN-DUP" }] as never, count: 10, offset: 0,
    });
    expect(s.total).toBe(1);
    expect((s.resources[0] as { id?: string }).id).toBe(NEW);
    const links = (s.resources[0] as { link?: Array<{ type: string }> }).link ?? [];
    expect(links.some((l) => l.type === "replaces")).toBe(true);
  });

  it("merged record: readable by id with replaced-by link, excluded from bare search", async () => {
    const merged = (await patients().read(OLD)) as { active?: boolean; link?: Array<{ type: string; other: { reference: string } }> };
    expect(merged.active).toBe(false);
    expect(merged.link?.[0]).toMatchObject({ type: "replaced-by", other: { reference: `Patient/${NEW}` } });
    const all = await patients().searchByParams({ conds: [], count: 100, offset: 0 });
    const ids = all.resources.map((r) => (r as { id?: string }).id);
    expect(ids).toContain(NEW);
    expect(ids).toContain(OTHER);
    expect(ids).not.toContain(OLD);
  });

  it("downstream references rewritten: Observation.subject points at the survivor", async () => {
    const o = (await obs().read(`${run}-obs`)) as { subject?: { reference?: string } };
    expect(o.subject?.reference).toBe(`Patient/${NEW}`);
    // and the search index followed: compartment search by survivor finds it
    const byRef = await obs().findReferencing(["subject"], `Patient/${NEW}`);
    expect(byRef.map((r) => (r as { id?: string }).id)).toContain(`${run}-obs`);
  });

  it("MPI tables landed in Gold: patient_link resolves both MRNs to the survivor; merge history recorded", async () => {
    wh.registerMpi("patient_link");
    const links = await wh.query<{ identifier_value: string; fhir_id: string }>(
      "SELECT identifier_value, fhir_id FROM patient_link WHERE identifier_value = ?", ["MRN-DUP"]);
    expect(links).toEqual([expect.objectContaining({ fhir_id: NEW })]);
    wh.registerMpi("patient_merge_history");
    const hist = await wh.query<{ surviving_fhir_id: string; merged_fhir_id: string; merge_actor: string }>(
      "SELECT surviving_fhir_id, merged_fhir_id, merge_actor FROM patient_merge_history WHERE merged_fhir_id = ?", [OLD]);
    expect(hist).toEqual([expect.objectContaining({ surviving_fhir_id: NEW, merge_actor: "system" })]);
  });

  it("merge Provenance recorded (ADR-0012 §8) and re-promotion is idempotent", async () => {
    const prov = new DeltaResourceRepository(wh, "Provenance");
    await promote(wh, "Provenance");
    const targets = await prov.findReferencing(["target"], `Patient/${NEW}`);
    expect(targets.length).toBeGreaterThanOrEqual(1);
    // Re-run the whole promotion: same outcome, no duplicate history rows.
    await promote(wh, "Patient");
    wh.registerMpi("patient_merge_history");
    const hist = await wh.query<{ n: number }>(
      "SELECT count(*) AS n FROM patient_merge_history WHERE merged_fhir_id = ?", [OLD]);
    expect(Number(hist[0].n)).toBe(1);
  });
});
