/**
 * SMART Backend Services (client_credentials + private_key_jwt). A registered asymmetric client
 * signs a JWT assertion; the token endpoint verifies it against the client's JWKS and issues a
 * SYSTEM-scoped token (no patient context) — which, per #1, reads across ALL patients. Sidecar-gated.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { generateKeyPair, exportJWK, calculateJwkThumbprint, SignJWT } from "jose";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";
import { resetKeys } from "../../src/auth/oauth/keys.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test";
const URLBASE = "http://fhirengine.test";
const CID = `svc-${Date.now()}`;

describe.skipIf(!SIDECAR)("SMART Backend Services (client_credentials + private_key_jwt)", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE }) : (null as unknown as DeltaWarehouse);
  const ts = Date.now();
  const P1 = `bs-p1-${ts}`, P2 = `bs-p2-${ts}`;
  let app: ReturnType<typeof createDeltaApp>;
  let privateKey: any, kid: string;
  const f = (p: string, init?: RequestInit) => app.fetch(new Request(`${URLBASE}${p}`, init));

  const assertion = async (over?: { jti?: string; key?: any }) =>
    new SignJWT({}).setProtectedHeader({ alg: "RS256", kid })
      .setIssuer(CID).setSubject(CID).setAudience(`${URLBASE}/oauth/token`)
      .setJti(over?.jti ?? `jti-${Math.random()}`).setIssuedAt().setExpirationTime("5m")
      .sign(over?.key ?? privateKey);
  const tokenReq = (a: string, scope = "system/*.rs") =>
    f(`/oauth/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "client_credentials", client_assertion_type: "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", client_assertion: a, scope }).toString() });

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    const kp = await generateKeyPair("RS256", { extractable: true });
    privateKey = kp.privateKey;
    const jwk = await exportJWK(kp.publicKey);
    kid = await calculateJwkThumbprint(jwk);
    // seed two patients with auth OFF
    delete process.env.FHIRENGINE_AUTH_ENABLED; delete process.env.FHIRENGINE_OAUTH_ENABLED;
    const open = createDeltaApp({ warehouse: wh, baseUrl: URLBASE });
    for (const id of [P1, P2]) await open.fetch(new Request(`${URLBASE}/Patient`, { method: "POST", headers: { "Content-Type": "application/fhir+json" }, body: JSON.stringify({ resourceType: "Patient", id }) }));
    // register the backend-services client (asymmetric, inline JWKS) + enable auth server + gate
    resetKeys();
    process.env.FHIRENGINE_OAUTH_CLIENTS = JSON.stringify([{ clientId: CID, type: "confidential", jwks: { keys: [{ ...jwk, kid, alg: "RS256", use: "sig" }] } }]);
    process.env.FHIRENGINE_OAUTH_ENABLED = "true";
    process.env.FHIRENGINE_AUTH_ENABLED = "true";
    process.env.FHIRENGINE_AUTH_STRATEGY = "local";
    app = createDeltaApp({ warehouse: wh, baseUrl: URLBASE });
  });
  afterAll(() => { for (const k of ["FHIRENGINE_OAUTH_CLIENTS", "FHIRENGINE_OAUTH_ENABLED", "FHIRENGINE_AUTH_ENABLED", "FHIRENGINE_AUTH_STRATEGY"]) delete process.env[k]; });

  it("issues a system-scoped token for a valid client assertion (no patient context)", async () => {
    const r = await tokenReq(await assertion());
    const t = await r.json();
    expect(r.status).toBe(200);
    expect(t.token_type).toBe("Bearer");
    expect(t.access_token).toBeTruthy();
    expect(t.patient).toBeUndefined(); // system scope — no launch patient
  });

  it("the system token reads ACROSS patients (no compartment restriction)", async () => {
    const t = await (await tokenReq(await assertion())).json();
    const bearer = { Authorization: `Bearer ${t.access_token}` };
    const pats = await (await f(`/Patient`, { headers: bearer })).json();
    const ids = pats.entry.map((e: any) => e.resource.id);
    expect(ids).toEqual(expect.arrayContaining([P1, P2]));               // both, unlike a patient token
    expect((await f(`/Patient/${P2}`, { headers: bearer })).status).toBe(200); // any patient readable
  });

  it("rejects a replayed jti and a wrong-key assertion", async () => {
    const a = await assertion({ jti: `once-${ts}` });
    expect((await tokenReq(a)).status).toBe(200);          // first use ok
    expect((await tokenReq(a)).status).toBe(401);          // replay → rejected
    const otherKey = (await generateKeyPair("RS256", { extractable: true })).privateKey;
    expect((await tokenReq(await assertion({ key: otherKey }))).status).toBe(401); // bad signature
  });
});
