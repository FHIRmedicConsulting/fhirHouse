/**
 * Da Vinci DTR Questionnaire/$questionnaire-package (CMS-0057). Seeds a Questionnaire (with a
 * cqf-library ref + an answerValueSet), a Library, and a ValueSet, then packages by canonical and
 * expects all three in the returned Bundle. Sidecar-gated. (CQL population is NOT performed.)
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";

const SIDECAR = process.env.RONIN_DELTA_SIDECAR_URL;
const BASE = process.env.RONIN_DELTA_BASE ?? "./.delta-test";

describe.skipIf(!SIDECAR)("Questionnaire/$questionnaire-package (DTR)", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: `${BASE}-dtr-${Date.now()}` }) : (null as unknown as DeltaWarehouse);
  const app = SIDECAR ? createDeltaApp({ warehouse: wh, baseUrl: "http://test" }) : (null as unknown as ReturnType<typeof createDeltaApp>);
  const Q_URL = "http://ex/Questionnaire/dtr-1";
  const LIB_URL = "http://ex/Library/dtr-cql";
  const VS_URL = "http://ex/ValueSet/dtr-answers";

  const post = (path: string, body: unknown) => app.fetch(new Request(`http://test/${path}`, { method: "POST", headers: { "Content-Type": "application/fhir+json" }, body: JSON.stringify(body) }));
  const pkg = (body: unknown) => post("Questionnaire/$questionnaire-package", body);

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    await post("Library", { resourceType: "Library", id: "dtr-cql", url: LIB_URL, status: "active", type: { coding: [{ code: "logic-library" }] } });
    await post("ValueSet", { resourceType: "ValueSet", id: "dtr-answers", url: VS_URL, status: "active" });
    await post("Questionnaire", {
      resourceType: "Questionnaire", id: "dtr-1", url: Q_URL, status: "active",
      extension: [{ url: "http://hl7.org/fhir/StructureDefinition/cqf-library", valueCanonical: LIB_URL }],
      item: [{ linkId: "1", type: "choice", answerValueSet: VS_URL }],
    });
  });

  it("packages the Questionnaire with its Library + ValueSet dependencies", async () => {
    const res = await pkg({ resourceType: "Parameters", parameter: [{ name: "questionnaire", valueCanonical: Q_URL }] });
    expect(res.status).toBe(200);
    const bundle = await res.json();
    expect(bundle.resourceType).toBe("Bundle");
    const types = bundle.entry.map((e: { resource: { resourceType: string } }) => e.resource.resourceType).sort();
    expect(types).toEqual(["Library", "Questionnaire", "ValueSet"]);
  });

  it("404 when no Questionnaire matches the canonical", async () => {
    const res = await pkg({ resourceType: "Parameters", parameter: [{ name: "questionnaire", valueCanonical: "http://ex/Questionnaire/nope" }] });
    expect(res.status).toBe(404);
  });

  it("400 when the 'questionnaire' parameter is missing", async () => {
    const res = await pkg({ resourceType: "Parameters", parameter: [] });
    expect(res.status).toBe(400);
  });

  it("400 when the body is not a Parameters resource", async () => {
    const res = await pkg({ resourceType: "Questionnaire" });
    expect(res.status).toBe(400);
  });
});
