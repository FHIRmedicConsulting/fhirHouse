/**
 * Da Vinci PAS Claim/$submit + $inquire (CMS-0057 Prior Authorization API). FHIR-native submit records
 * a ClaimResponse; inquire returns it by patient / preAuthRef. Sidecar-gated. (Adjudication is a stub.)
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";

const SIDECAR = process.env.RONIN_DELTA_SIDECAR_URL;
const BASE = process.env.RONIN_DELTA_BASE ?? "./.delta-test";

describe.skipIf(!SIDECAR)("Claim/$submit + $inquire (PAS)", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: `${BASE}-pas-${Date.now()}` }) : (null as unknown as DeltaWarehouse);
  const app = SIDECAR ? createDeltaApp({ warehouse: wh, baseUrl: "http://test" }) : (null as unknown as ReturnType<typeof createDeltaApp>);
  const post = (p: string, b: unknown) => app.fetch(new Request(`http://test${p}`, { method: "POST", headers: { "Content-Type": "application/fhir+json" }, body: JSON.stringify(b) }));
  const PT = "Patient/pas-p1";
  let preAuthRef: string;

  const submit = (claim: Record<string, unknown>) =>
    post("/Claim/$submit", { resourceType: "Bundle", type: "collection", entry: [{ resource: { resourceType: "Claim", ...claim } }] });

  beforeAll(async () => { if (SIDECAR && !(await wh.health())) throw new Error("sidecar down"); });

  it("$submit records a ClaimResponse (complete + preAuthRef) for a preauthorization Claim", async () => {
    const res = await submit({ use: "preauthorization", patient: { reference: PT }, item: [{ sequence: 1 }] });
    expect(res.status).toBe(200);
    const bundle = await res.json();
    expect(bundle.resourceType).toBe("Bundle");
    const cr = bundle.entry[0].resource;
    expect(cr.resourceType).toBe("ClaimResponse");
    expect(cr.use).toBe("preauthorization");
    expect(cr.outcome).toBe("complete");
    expect(cr.preAuthRef).toMatch(/^PA-/);
    preAuthRef = cr.preAuthRef;
  });

  it("$submit rejects a non-preauthorization Claim (400)", async () => {
    const res = await submit({ use: "claim", patient: { reference: PT } });
    expect(res.status).toBe(400);
  });

  it("$inquire by patient returns the prior-auth ClaimResponse(s)", async () => {
    const res = await post("/Claim/$inquire", { resourceType: "Bundle", type: "collection", entry: [{ resource: { resourceType: "Claim", use: "preauthorization", patient: { reference: PT } } }] });
    expect(res.status).toBe(200);
    const bundle = await res.json();
    expect(bundle.entry.length).toBeGreaterThanOrEqual(1);
    expect(bundle.entry.every((e: { resource: { resourceType: string; use: string } }) => e.resource.resourceType === "ClaimResponse" && e.resource.use === "preauthorization")).toBe(true);
  });

  it("$inquire by preAuthRef (Parameters) returns the matching ClaimResponse", async () => {
    const res = await post("/Claim/$inquire", { resourceType: "Parameters", parameter: [{ name: "preAuthRef", valueString: preAuthRef }] });
    expect(res.status).toBe(200);
    const bundle = await res.json();
    expect(bundle.entry.some((e: { resource: { preAuthRef?: string } }) => e.resource.preAuthRef === preAuthRef)).toBe(true);
  });

  it("$submit rejects a non-Bundle body (400)", async () => {
    const res = await post("/Claim/$submit", { resourceType: "Claim", use: "preauthorization" });
    expect(res.status).toBe(400);
  });
});
