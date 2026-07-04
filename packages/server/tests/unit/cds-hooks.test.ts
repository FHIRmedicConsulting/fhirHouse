/**
 * Da Vinci CRD — CDS Hooks discovery + coverage-requirements service (CMS-0057). Stateless
 * (no warehouse), so a plain Hono app under test.
 */
import { describe, it, expect } from "vitest";
import { Hono } from "hono";
import { mountCdsHooks } from "../../src/routes/cds-hooks.js";

const app = new Hono();
mountCdsHooks(app, "http://ex");
const get = (p: string) => app.fetch(new Request(`http://ex${p}`));
const post = (p: string, b: unknown) => app.fetch(new Request(`http://ex${p}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }));

describe("CDS Hooks (CRD)", () => {
  it("discovery lists the order-sign coverage-requirements service", async () => {
    const body = await (await get("/cds-services")).json();
    expect(body.services).toHaveLength(1);
    expect(body.services[0]).toMatchObject({ hook: "order-sign", id: "coverage-requirements" });
    expect(body.services[0].prefetch).toBeTruthy();
  });

  it("order-sign invocation returns an info card with DTR + PAS links", async () => {
    const res = await post("/cds-services/coverage-requirements", {
      hook: "order-sign", hookInstance: "h1", context: { patientId: "p1", draftOrders: { entry: [{ resource: {} }] } },
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.cards).toHaveLength(1);
    const card = body.cards[0];
    expect(card.indicator).toBe("info");
    expect(card.summary).toMatch(/prior authorization/i);
    expect(card.links.map((l: { url: string }) => l.url)).toEqual(
      expect.arrayContaining(["http://ex/Claim/$submit", "http://ex/Questionnaire/$questionnaire-package"]),
    );
    expect(card.uuid).toBeTruthy();
  });

  it("invocation without draft orders still returns a card", async () => {
    const body = await (await post("/cds-services/coverage-requirements", { hook: "order-sign", context: { patientId: "p1" } })).json();
    expect(body.cards).toHaveLength(1);
  });

  it("rejects an invalid (non-JSON) request body (400)", async () => {
    const res = await app.fetch(new Request("http://ex/cds-services/coverage-requirements", { method: "POST", headers: { "Content-Type": "application/json" }, body: "not json" }));
    expect(res.status).toBe(400);
  });
});
