/**
 * Da Vinci CRD — Coverage Requirements Discovery via CDS Hooks (CMS-0057 prior-auth workflow).
 * A provider EHR calls these at order time to learn coverage requirements (e.g. prior auth needed,
 * documentation required) and is pointed to DTR + the PAS submission endpoint.
 *
 *   GET  /cds-services                       discovery
 *   POST /cds-services/coverage-requirements  order-sign hook → cards
 *
 * SCOPE (first slice): the CDS Hooks protocol + a coverage card are implemented. The actual
 * **coverage rule evaluation is CQL-based** (a large separate component — see the CMS-0057 plan);
 * this returns an informational coverage card and links to DTR / PAS rather than evaluating payer CQL.
 */
import type { Hono } from "hono";
import { uuidv7 } from "../lib/uuid-v7.js";

const SERVICE_ID = "coverage-requirements";

export function mountCdsHooks(app: Hono, baseUrl: string): void {
  // Discovery
  app.get("/cds-services", (c) =>
    c.json({
      services: [
        {
          hook: "order-sign",
          id: SERVICE_ID,
          title: "Coverage Requirements Discovery (CRD)",
          description: "Returns coverage requirements (e.g. prior authorization) for draft orders and links to DTR + the Prior Authorization API.",
          prefetch: { patient: "Patient/{{context.patientId}}" },
        },
      ],
    }),
  );

  // order-sign hook invocation → coverage cards
  app.post(`/cds-services/${SERVICE_ID}`, async (c) => {
    let body: { hook?: string; context?: { patientId?: string; draftOrders?: { entry?: unknown[] } } };
    try { body = await c.req.json(); } catch { return c.json({ error: "invalid CDS Hooks request" }, 400); }
    const orders = body.context?.draftOrders?.entry?.length ?? 0;

    return c.json({
      cards: [
        {
          uuid: uuidv7(),
          summary: orders
            ? "Coverage requirements: prior authorization may be required for one or more orders"
            : "Coverage requirements discovery available",
          indicator: "info",
          detail:
            "Complete required documentation via DTR, then submit the prior-authorization request to the Prior Authorization API (Claim/$submit). Actual coverage rules are payer-specific.",
          source: { label: "RoninStandAlone CRD", url: baseUrl },
          links: [
            { label: "Prior Authorization API (PAS)", url: `${baseUrl}/Claim/$submit`, type: "absolute" },
            { label: "Documentation Templates (DTR)", url: `${baseUrl}/Questionnaire/$questionnaire-package`, type: "absolute" },
          ],
        },
      ],
    });
  });
}
