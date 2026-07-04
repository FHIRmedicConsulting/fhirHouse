/**
 * Liveness vs readiness (#7): /health is liveness (always ok), /ready reflects sidecar reachability
 * (503 until reachable) so an orchestrator/LB doesn't route writes that would 5xx.
 */
import { describe, it, expect } from "vitest";
import { createDeltaApp } from "../../src/app.js";
import type { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";

const appWith = (health: () => Promise<boolean>) =>
  createDeltaApp({ warehouse: { health } as unknown as DeltaWarehouse, baseUrl: "http://test" });

describe("health vs readiness", () => {
  it("/health is liveness — 200 even when the sidecar is down", async () => {
    const app = appWith(async () => false);
    const res = await app.request("/health");
    expect(res.status).toBe(200);
    expect((await res.json()).status).toBe("ok");
  });

  it("/ready is 200 when the sidecar is reachable", async () => {
    const res = await appWith(async () => true).request("/ready");
    expect(res.status).toBe(200);
    expect((await res.json()).status).toBe("ready");
  });

  it("/ready is 503 when the sidecar is unreachable (or health throws)", async () => {
    expect((await appWith(async () => false).request("/ready")).status).toBe(503);
    expect((await appWith(async () => { throw new Error("down"); }).request("/ready")).status).toBe(503);
  });
});
