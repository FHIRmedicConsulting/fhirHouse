/**
 * FHIR terminology *operation* endpoints ($validate-code / $expand / $lookup) — exposing the
 * local Delta terminology store as a tx server. Seeds a tiny CodeSystem/ValueSet then exercises
 * the endpoints. Sidecar-gated.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";
import { loadTerminologyResources } from "../../src/terminology/terminology-loader.js";

const SIDECAR = process.env.RONIN_DELTA_SIDECAR_URL;
const BASE = process.env.RONIN_DELTA_BASE ?? "./.delta-test";
// Unique per run so this test is hermetic against other terminology tests sharing the base.
const CS = `http://example.org/cs-${Date.now()}`;
const VS = `http://example.org/vs-${Date.now()}`;

describe.skipIf(!SIDECAR)("terminology operation endpoints", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE }) : (null as unknown as DeltaWarehouse);
  const app = SIDECAR ? createDeltaApp({ warehouse: wh, baseUrl: "http://test" }) : (null as unknown as ReturnType<typeof createDeltaApp>);
  const get = async (p: string) => { const r = await app.fetch(new Request(`http://test${p}`)); return { status: r.status, body: await r.json() }; };
  const val = (params: any[], name: string) => params.find((x) => x.name === name);

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    // Seed via the real loader so the terminology-table schema matches the other terminology tests
    // sharing this base (raw minimal rows would corrupt the shared schema).
    await loadTerminologyResources(wh, [
      { resourceType: "CodeSystem", url: CS, version: "1.0.0", content: "complete", concept: [{ code: "A", display: "Alpha" }] },
      { resourceType: "ValueSet", url: VS, version: "1.0.0", compose: { include: [{ system: CS, concept: [{ code: "A", display: "Alpha" }] }] } },
    ]);
  });

  it("CodeSystem/$validate-code: valid code → result true + display", async () => {
    const { status, body } = await get(`/CodeSystem/$validate-code?url=${encodeURIComponent(CS)}&code=A`);
    expect(status).toBe(200);
    expect(val(body.parameter, "result").valueBoolean).toBe(true);
    expect(val(body.parameter, "display").valueString).toBe("Alpha");
  });

  it("CodeSystem/$validate-code: code not in a LOADED system → result false + error issue", async () => {
    const { body } = await get(`/CodeSystem/$validate-code?url=${encodeURIComponent(CS)}&code=NOPE`);
    expect(val(body.parameter, "result").valueBoolean).toBe(false);
    expect(val(body.parameter, "issues").resource.issue[0].severity).toBe("error");
  });

  it("ValueSet/$validate-code: member code → true; unknown ValueSet → warning issue", async () => {
    const ok = await get(`/ValueSet/$validate-code?url=${encodeURIComponent(VS)}&system=${encodeURIComponent(CS)}&code=A`);
    expect(val(ok.body.parameter, "result").valueBoolean).toBe(true);
    const unknown = await get(`/ValueSet/$validate-code?url=${encodeURIComponent("http://example.org/not-loaded")}&code=X`);
    expect(val(unknown.body.parameter, "result").valueBoolean).toBe(false);
    expect(val(unknown.body.parameter, "issues").resource.issue[0].severity).toBe("warning"); // can't validate ≠ invalid
  });

  it("ValueSet/$expand returns the expansion contents", async () => {
    const { body } = await get(`/ValueSet/$expand?url=${encodeURIComponent(VS)}`);
    expect(body.resourceType).toBe("ValueSet");
    expect(body.expansion.contains).toContainEqual({ system: CS, code: "A", display: "Alpha" });
  });

  it("CodeSystem/$lookup returns the display", async () => {
    const { status, body } = await get(`/CodeSystem/$lookup?system=${encodeURIComponent(CS)}&code=A`);
    expect(status).toBe(200);
    expect(val(body.parameter, "display").valueString).toBe("Alpha");
  });

  it("/metadata advertises the terminology operations", async () => {
    const meta = (await get(`/metadata`)).body;
    const vs = meta.rest[0].resource.find((r: any) => r.type === "ValueSet");
    expect(vs.operation.map((o: any) => o.name)).toEqual(expect.arrayContaining(["expand", "validate-code"]));
  });
});
