/**
 * Da Vinci PAS — Prior Authorization Support (CMS-0057 Prior Authorization API). FHIR-native
 * `Claim/$submit` + `Claim/$inquire`. A submitter POSTs a Bundle containing a Claim
 * (use=preauthorization); we record a ClaimResponse and return it in a Bundle. `$inquire` returns the
 * stored ClaimResponse(s) for a patient / preAuthRef.
 *
 *   POST /Claim/$submit   in: Bundle{ Claim(use=preauthorization), … } → out: Bundle{ ClaimResponse }
 *   POST /Claim/$inquire  in: Bundle{ Claim } | Parameters → out: Bundle{ ClaimResponse… }
 *
 * SCOPE (first slice): fhirEngine performs **no adjudication** — a real payer's decision comes from
 * its Utilization Management system, and the PAS *gateway* converts FHIR ⇄ **X12 278** (a large,
 * separate component — see the CMS-0057 plan). So `$submit` returns a **PENDED** ClaimResponse
 * (`outcome: queued`, review-action `pended`, NO `preAuthRef`): the request is received + queued,
 * NOT authorized. This is deliberate so a partner's integration engine can never machine-read a
 * fabricated approval. Grant/deny + a real preAuthRef require a UM/X12-278 backend.
 */
import type { Hono } from "hono";
import { DeltaResourceRepository } from "../repository/delta-resource-repository.js";
import type { DeltaWarehouse } from "../lib/delta-warehouse.js";
import type { SearchCondition } from "../repository/delta-resource-repository.js";
import type { Resource as FhirResource } from "@fhirengine/fhir-types";
import { operationOutcome as oo } from "../lib/errors.js";
import { uuidv7 } from "../lib/uuid-v7.js";

interface Ref { reference?: string }
interface Claim { resourceType: string; use?: string; patient?: Ref; type?: unknown; insurer?: unknown; id?: string; identifier?: Array<{ system?: string; value?: string }>; item?: Array<{ sequence?: number }> }
interface Bundle { resourceType: string; entry?: Array<{ resource?: Record<string, unknown> }> }

const firstOf = (bundle: Bundle, rt: string): Record<string, unknown> | undefined =>
  bundle.entry?.map((e) => e.resource).find((r) => r?.resourceType === rt);


const collection = (resources: unknown[]) => ({ resourceType: "Bundle", type: "collection", entry: resources.map((r) => ({ resource: r })) });

export function mountPriorAuth(app: Hono, wh: DeltaWarehouse, baseUrl: string): void {
  const repo = (rt: string) => new DeltaResourceRepository(wh, rt);

  app.post("/Claim/$submit", async (c) => {
    let body: Bundle;
    try { body = await c.req.json(); } catch { return c.json(oo("invalid", "request body must be a Bundle"), 400); }
    if (body?.resourceType !== "Bundle") return c.json(oo("invalid", "expected a Bundle"), 400);
    const claim = firstOf(body, "Claim") as Claim | undefined;
    if (!claim) return c.json(oo("required", "the submission Bundle must contain a Claim"), 400);
    if (claim.use !== "preauthorization") return c.json(oo("invalid", "Claim.use must be 'preauthorization' for prior authorization"), 400);

    // Tracking id for $inquire correlation — NOT a preAuthRef (no authorization is granted).
    const trackingId = `TRK-${uuidv7().slice(0, 13)}`;
    const claimResponse = {
      resourceType: "ClaimResponse",
      status: "active",
      type: claim.type ?? { coding: [{ system: "http://terminology.hl7.org/CodeSystem/claim-type", code: "professional" }] },
      use: "preauthorization",
      patient: claim.patient,
      created: new Date().toISOString(),
      insurer: claim.insurer ?? { display: "fhirEngine (no adjudication)" },
      ...(claim.id ? { request: { reference: `Claim/${claim.id}` } } : {}),
      // PENDED, not decided (see header): outcome=queued, review-action pended, NO preAuthRef.
      // fhirEngine does not adjudicate — a machine MUST NOT read this as an approval.
      outcome: "queued",
      disposition: "Pended — received and queued for utilization-management review. No authorization has been granted (fhirEngine performs no adjudication; connect a UM / X12-278 gateway).",
      identifier: [{ system: `${baseUrl}/fhir/prior-auth-tracking`, value: trackingId }],
      item: (claim.item ?? []).map((it) => ({
        itemSequence: it.sequence ?? 1,
        // Da Vinci PAS review-action: pended (A4) — no decision made.
        adjudication: [{
          category: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/adjudication", code: "submitted" }] },
          extension: [{
            url: "http://hl7.org/fhir/us/davinci-pas/StructureDefinition/extension-reviewAction",
            extension: [{ url: "number", valueCodeableConcept: { coding: [{ system: "https://codesystem.x12.org/005010/306", code: "A4", display: "Pended" }] } }],
          }],
        }],
      })),
    };
    const stored = await repo("ClaimResponse").create(claimResponse as unknown as FhirResource);
    return c.json(collection([stored]));
  });

  app.post("/Claim/$inquire", async (c) => {
    let body: Bundle | { resourceType?: string; parameter?: Array<{ name?: string; valueString?: string; resource?: Record<string, unknown> }> };
    try { body = await c.req.json(); } catch { return c.json(oo("invalid", "request body must be a Bundle or Parameters"), 400); }

    const conds: SearchCondition[] = [];
    let patientRef: string | undefined;
    if (body?.resourceType === "Bundle") {
      const claim = firstOf(body as Bundle, "Claim") as Claim | undefined;
      patientRef = claim?.patient?.reference;
      const id = claim?.identifier?.[0]?.value;
      if (id) conds.push({ code: "identifier", type: "token", value: id });
    } else if (body?.resourceType === "Parameters") {
      const params = (body as { parameter?: Array<{ name?: string; valueString?: string }> }).parameter ?? [];
      patientRef = params.find((p) => p.name === "patient")?.valueString;
      const ref = params.find((p) => p.name === "preAuthRef")?.valueString;
      if (ref) conds.push({ code: "identifier", type: "token", value: ref });
    } else {
      return c.json(oo("invalid", "expected a Bundle or Parameters"), 400);
    }
    if (patientRef) conds.push({ code: "patient", type: "reference", value: patientRef });
    if (!conds.length) return c.json(oo("required", "provide a patient reference or a preAuthRef/identifier to inquire"), 400);

    const r = await repo("ClaimResponse").searchByParams({ conds, count: 50, offset: 0 });
    return c.json(collection(r.resources.filter((cr) => (cr as { use?: string }).use === "preauthorization")));
  });
}
