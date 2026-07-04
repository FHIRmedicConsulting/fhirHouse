/**
 * Search completeness (#9): numeric _sort (cast, not string), _include:iterate (transitive),
 * and a _revinclude type guard (no crash on a bogus/non-core source type). Sidecar-gated.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test";

describe.skipIf(!SIDECAR)("search completeness", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE }) : (null as unknown as DeltaWarehouse);
  const app = SIDECAR ? createDeltaApp({ warehouse: wh, baseUrl: "http://test" }) : (null as unknown as ReturnType<typeof createDeltaApp>);
  const ts = Date.now();
  const numCode = `num-${ts}`, P = `sc-p-${ts}`, E = `sc-e-${ts}`, O = `sc-o-${ts}`;
  const post = (p: string, b: unknown) => app.fetch(new Request(`http://test${p}`, { method: "POST", headers: { "Content-Type": "application/fhir+json" }, body: JSON.stringify(b) }));
  const get = (p: string) => app.fetch(new Request(`http://test${p}`));

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    // numeric sort: 3 Observations sharing a code, valueQuantity 2 / 10 / 9
    for (const v of [2, 10, 9]) {
      await post("/Observation", { resourceType: "Observation", status: "final", code: { coding: [{ system: "http://ex", code: numCode }] }, valueQuantity: { value: v, unit: "x" } });
    }
    // include chain: Observation -> encounter -> Encounter -> patient -> Patient
    await post("/Patient", { resourceType: "Patient", id: P });
    await post("/Encounter", { resourceType: "Encounter", id: E, status: "finished", class: { code: "AMB" }, subject: { reference: `Patient/${P}` } });
    await post("/Observation", { resourceType: "Observation", id: O, status: "final", code: { text: "c" }, subject: { reference: `Patient/${P}` }, encounter: { reference: `Encounter/${E}` } });
  });

  it("numeric _sort orders by value, not string (10 > 9 > 2)", async () => {
    const b = await (await get(`/Observation?code=${encodeURIComponent("http://ex|" + numCode)}&_sort=value-quantity`)).json();
    const vals = b.entry.map((e: any) => e.resource.valueQuantity.value);
    expect(vals).toEqual([2, 9, 10]); // ascending numeric (string sort would give [10, 2, 9])
    const desc = await (await get(`/Observation?code=${encodeURIComponent("http://ex|" + numCode)}&_sort=-value-quantity`)).json();
    expect(desc.entry.map((e: any) => e.resource.valueQuantity.value)).toEqual([10, 9, 2]);
  });

  it("_include:iterate follows includes transitively (Observation → Encounter → Patient)", async () => {
    const b = await (await get(`/Observation?_id=${O}&_include=Observation:encounter&_include:iterate=Encounter:patient`)).json();
    const types = b.entry.map((e: any) => e.resource.resourceType);
    expect(types).toContain("Observation"); // match
    expect(types).toContain("Encounter");   // direct include
    expect(types).toContain("Patient");     // transitive include (iterate)
    const inc = b.entry.filter((e: any) => e.search?.mode === "include").map((e: any) => e.resource.id);
    expect(inc).toEqual(expect.arrayContaining([E, P]));
  });

  it("_revinclude with a bogus/non-core source type does not crash", async () => {
    const r = await get(`/Observation?_id=${O}&_revinclude=NotAType:target`);
    expect(r.status).toBe(200);
    expect((await r.json()).total).toBe(1); // just the match, no crash
  });

  it("unsupported params (composite/unknown) are lenient-ignored by default, 400 under Prefer: handling=strict", async () => {
    const strictHdr = { headers: { Prefer: "handling=strict" } };
    // Composite param (not applied by this engine): lenient ignores it, strict rejects it.
    const compLenient = await get(`/Observation?_id=${O}&code-value-quantity=${encodeURIComponent("http://ex|c$5")}`);
    expect(compLenient.status).toBe(200); // FHIR default lenient: ignore, don't silently mislead-then-500
    const compStrict = await app.fetch(new Request(`http://test/Observation?_id=${O}&code-value-quantity=x`, strictHdr));
    expect(compStrict.status).toBe(400);
    const oo = await compStrict.json();
    expect(oo.resourceType).toBe("OperationOutcome");
    expect(JSON.stringify(oo)).toMatch(/code-value-quantity/);
    // Multi-field _sort: only the first field is applied → 400 under strict so the client knows.
    const sortStrict = await app.fetch(new Request(`http://test/Observation?_id=${O}&_sort=status,value-quantity`, strictHdr));
    expect(sortStrict.status).toBe(400);
  });
});
