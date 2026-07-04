/**
 * UDAP client registry — durable Delta persistence (ADR-0036). Verifies the new udap_client table
 * (catalog path + warehouse write/query) round-trips a registration through real delta-rs, and that
 * latest-per-client_id wins on reload. Sidecar-gated.
 */
import { describe, it, expect, beforeAll } from "vitest";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import {
  persistUdapClient, loadRegisteredClients, getRegisteredClient, resetRegisteredClients,
} from "../../src/auth/udap/registered-clients.js";
import type { OAuthClient } from "../../src/auth/oauth/clients.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test";

describe.skipIf(!SIDECAR)("udap client registry (delta persistence)", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: `${BASE}-udap-${Date.now()}` }) : (null as unknown as DeltaWarehouse);
  const CID = "https://client.example/fhir";
  const mk = (kid: string): OAuthClient => ({ clientId: CID, type: "confidential", jwks: { keys: [{ kty: "RSA", kid, use: "sig" }] }, redirectUris: ["https://client.example/cb"] });

  beforeAll(async () => { if (SIDECAR && !(await wh.health())) throw new Error("sidecar down"); });

  it("persists a registration to Delta and reloads it into the cache", async () => {
    resetRegisteredClients();
    await persistUdapClient(wh, mk("k1"), "2026-07-04T00:00:00Z");
    resetRegisteredClients();                       // simulate restart (cache cleared)
    expect(getRegisteredClient(CID)).toBeNull();
    expect(await loadRegisteredClients(wh)).toBe(1); // reloaded from Delta
    const got = getRegisteredClient(CID);
    expect((got?.jwks?.keys[0] as { kid: string }).kid).toBe("k1");
    expect(got?.redirectUris).toEqual(["https://client.example/cb"]);
  });

  it("latest-per-client_id wins on re-registration", async () => {
    await persistUdapClient(wh, mk("k2"), "2026-07-04T01:00:00Z"); // newer
    resetRegisteredClients();
    expect(await loadRegisteredClients(wh)).toBe(1); // still one client, not two
    expect((getRegisteredClient(CID)?.jwks?.keys[0] as { kid: string }).kid).toBe("k2");
  });
});
