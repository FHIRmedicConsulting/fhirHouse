/**
 * CMS-0057 Patient Access — CARIN BB / PDex ExplanationOfBenefit surface. Proves the claims data is
 * fully retrievable by a patient app: EOB served as an R4 resource, searchable by patient / type /
 * service-date, joinable via _include, and swept into Patient/$everything (compartment membership).
 * Sidecar-gated. Synthetic data only.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";

const SIDECAR = process.env.RONIN_DELTA_SIDECAR_URL;
const BASE = process.env.RONIN_DELTA_BASE ?? "./.delta-test";

describe.skipIf(!SIDECAR)("EOB Patient Access (CARIN BB / PDex)", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: `${BASE}-eob-${Date.now()}` }) : (null as unknown as DeltaWarehouse);
  const app = SIDECAR ? createDeltaApp({ warehouse: wh, baseUrl: "http://test" }) : (null as unknown as ReturnType<typeof createDeltaApp>);
  const post = (p: string, b: unknown) => app.fetch(new Request(`http://test${p}`, { method: "POST", headers: { "Content-Type": "application/fhir+json" }, body: JSON.stringify(b) }));
  const get = (p: string) => app.fetch(new Request(`http://test${p}`));
  const PT = "eob-pt";

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    await post("/Patient", { resourceType: "Patient", id: PT, name: [{ family: "Beneficiary" }] });
    await post("/Coverage", { resourceType: "Coverage", id: "eob-cov", status: "active", beneficiary: { reference: `Patient/${PT}` }, payor: [{ display: "Acme Health" }] });
    await post("/ExplanationOfBenefit", {
      resourceType: "ExplanationOfBenefit", id: "eob-1", status: "active", use: "claim", outcome: "complete", created: "2024-03-20",
      type: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/claim-type", code: "professional" }] },
      patient: { reference: `Patient/${PT}` },
      insurer: { display: "Acme Health" }, provider: { display: "Dr. Synthetic" },
      insurance: [{ focal: true, coverage: { reference: "Coverage/eob-cov" } }],
      billablePeriod: { start: "2024-03-01", end: "2024-03-31" },
      item: [{ sequence: 1, servicedDate: "2024-03-15", productOrService: { text: "office visit" } }],
    });
    // A second EOB of a different type / date to prove filtering discriminates.
    await post("/ExplanationOfBenefit", {
      resourceType: "ExplanationOfBenefit", id: "eob-2", status: "active", use: "claim", outcome: "complete", created: "2023-01-06",
      type: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/claim-type", code: "pharmacy" }] },
      patient: { reference: `Patient/${PT}` }, insurer: { display: "Acme Health" }, provider: { display: "Pharmacy" },
      insurance: [{ focal: true, coverage: { reference: "Coverage/eob-cov" } }],
      billablePeriod: { start: "2023-01-05", end: "2023-01-05" },
    });
  });

  it("EOB is searchable by patient (Patient Access base query)", async () => {
    const b = await (await get(`/ExplanationOfBenefit?patient=${PT}`)).json();
    expect(b.total).toBe(2);
    expect(b.entry.every((e: { resource: { resourceType: string } }) => e.resource.resourceType === "ExplanationOfBenefit")).toBe(true);
  });

  it("EOB is searchable by CARIN 'type' (claim category)", async () => {
    const b = await (await get(`/ExplanationOfBenefit?patient=${PT}&type=professional`)).json();
    expect(b.total).toBe(1);
    expect(b.entry[0].resource.id).toBe("eob-1");
  });

  it("EOB is searchable by CARIN 'service-date' range", async () => {
    const b = await (await get(`/ExplanationOfBenefit?patient=${PT}&service-date=ge2024-01-01`)).json();
    expect(b.total).toBe(1);
    expect(b.entry[0].resource.id).toBe("eob-1");
  });

  it("_include pulls the referenced Coverage alongside the EOB", async () => {
    const b = await (await get(`/ExplanationOfBenefit?patient=${PT}&_id=eob-1&_include=ExplanationOfBenefit:coverage`)).json();
    const types = b.entry.map((e: { resource: { resourceType: string } }) => e.resource.resourceType).sort();
    expect(types).toContain("Coverage");
    expect(types).toContain("ExplanationOfBenefit");
  });

  it("Patient/$everything sweeps the EOBs + Coverage (compartment membership)", async () => {
    const b = await (await get(`/Patient/${PT}/$everything`)).json();
    const byType = (t: string) => b.entry.filter((e: { resource: { resourceType: string } }) => e.resource.resourceType === t).length;
    expect(byType("ExplanationOfBenefit")).toBe(2);
    expect(byType("Coverage")).toBe(1);
    expect(byType("Patient")).toBe(1);
  });

  it("CapabilityStatement advertises EOB type + service-date", async () => {
    const cs = await (await get("/metadata")).json();
    const eob = cs.rest[0].resource.find((r: { type: string }) => r.type === "ExplanationOfBenefit");
    const params = eob.searchParam.map((s: { name: string }) => s.name);
    expect(params).toContain("type");
    expect(params).toContain("service-date");
  });
});
