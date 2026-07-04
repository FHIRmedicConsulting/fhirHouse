/**
 * Transaction conditional references (`Type?identifier=sys|val` → literal `Type/<id>`) + `ifNoneExist`
 * conditional create. Surfaced by Synthea (Encounter → `Practitioner?identifier=us-npi|…`). A persisted
 * reference must be literal; unresolvable conditional refs reject the transaction. Sidecar-gated.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test";

describe.skipIf(!SIDECAR)("transaction conditional references + ifNoneExist", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE }) : (null as unknown as DeltaWarehouse);
  const app = SIDECAR ? createDeltaApp({ warehouse: wh, baseUrl: "http://test" }) : (null as unknown as ReturnType<typeof createDeltaApp>);
  const sys = "http://example.org/npi";
  const npi = `NPI-${Date.now()}`;
  const post = (p: string, b: unknown) => app.fetch(new Request(`http://test${p}`, { method: "POST", headers: { "Content-Type": "application/fhir+json" }, body: JSON.stringify(b) }));
  const tx = (entry: unknown[]) => post("/", { resourceType: "Bundle", type: "transaction", entry });

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    await post("/Practitioner", { resourceType: "Practitioner", identifier: [{ system: sys, value: npi }] });
  });

  it("resolves a conditional reference to a literal Type/id against a server resource", async () => {
    const resp = await (await tx([{
      request: { method: "POST", url: "Observation" },
      resource: { resourceType: "Observation", status: "final", code: { text: "t" },
        performer: [{ reference: `Practitioner?identifier=${sys}|${npi}` }] },
    }])).json();
    const obs = resp.entry[0].resource;
    expect(resp.entry[0].response.status).toBe("201");
    expect(obs.performer[0].reference).toMatch(/^Practitioner\/.+/); // resolved to literal, not the query
  });

  it("ifNoneExist skips creating a duplicate and returns the existing resource", async () => {
    const resp = await (await tx([{
      request: { method: "POST", url: "Practitioner", ifNoneExist: `identifier=${sys}|${npi}` },
      resource: { resourceType: "Practitioner", identifier: [{ system: sys, value: npi }] },
    }])).json();
    expect(resp.entry[0].response.status).toBe("200"); // matched existing, not created
    const count = (await (await app.fetch(new Request(`http://test/Practitioner?identifier=${sys}|${npi}`))).json()).total;
    expect(count).toBe(1); // no duplicate
  });

  it("rejects a transaction with an unresolvable conditional reference (422)", async () => {
    const res = await tx([{
      request: { method: "POST", url: "Observation" },
      resource: { resourceType: "Observation", status: "final", code: { text: "t" },
        performer: [{ reference: `Practitioner?identifier=${sys}|does-not-exist` }] },
    }]);
    expect(res.status).toBe(422);
    expect((await res.json()).issue[0].diagnostics).toMatch(/unresolved conditional reference/i);
  });
});
