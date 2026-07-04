/**
 * SMART authorization server end-to-end (ADR-0006 / ADR-0030): authorize → code → token → use.
 * Proves the loop closes — the token WE issue is verified by OUR gate (local strategy) and drives
 * the patient-compartment enforcement from #1. Also covers PKCE, refresh, id_token, JWKS. Sidecar-gated.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { createHash, randomBytes } from "node:crypto";
import { decodeJwt } from "jose";
import { DeltaWarehouse } from "../../src/lib/delta-warehouse.js";
import { createDeltaApp } from "../../src/app.js";
import { resetKeys } from "../../src/auth/oauth/keys.js";

const SIDECAR = process.env.FHIRENGINE_DELTA_SIDECAR_URL;
const BASE = process.env.FHIRENGINE_DELTA_BASE ?? "./.delta-test";
const URLBASE = "http://ronin.test";
const REDIRECT = "http://app.example/cb";

describe.skipIf(!SIDECAR)("SMART authorization server (end-to-end)", () => {
  const wh = SIDECAR ? new DeltaWarehouse({ sidecarUrl: SIDECAR, base: BASE }) : (null as unknown as DeltaWarehouse);
  const ts = Date.now();
  const P1 = `sa-p1-${ts}`, P2 = `sa-p2-${ts}`;
  let app: ReturnType<typeof createDeltaApp>;
  let obs2Id = "";
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  const f = (p: string, init?: RequestInit) => app.fetch(new Request(`${URLBASE}${p}`, init));

  beforeAll(async () => {
    if (!SIDECAR) return;
    if (!(await wh.health())) throw new Error("sidecar down");
    delete process.env.FHIRENGINE_AUTH_ENABLED; delete process.env.FHIRENGINE_OAUTH_ENABLED;
    const open = createDeltaApp({ warehouse: wh, baseUrl: URLBASE });
    const post = (p: string, b: unknown) => open.fetch(new Request(`${URLBASE}${p}`, { method: "POST", headers: { "Content-Type": "application/fhir+json" }, body: JSON.stringify(b) }));
    await post("/Patient", { resourceType: "Patient", id: P1 });
    await post("/Patient", { resourceType: "Patient", id: P2 });
    await post("/Observation", { resourceType: "Observation", status: "final", code: { text: "x" }, subject: { reference: `Patient/${P1}` } });
    obs2Id = (await (await post("/Observation", { resourceType: "Observation", status: "final", code: { text: "x" }, subject: { reference: `Patient/${P2}` } })).json()).id;
    // now enable the auth server + gate (local strategy verifies our own tokens)
    resetKeys();
    process.env.FHIRENGINE_OAUTH_ENABLED = "true";
    process.env.FHIRENGINE_AUTH_ENABLED = "true";
    process.env.FHIRENGINE_AUTH_STRATEGY = "local";
    process.env.FHIRENGINE_OAUTH_DEFAULT_PATIENT = P1;
    app = createDeltaApp({ warehouse: wh, baseUrl: URLBASE });
  });
  afterAll(() => { for (const k of ["FHIRENGINE_OAUTH_ENABLED", "FHIRENGINE_AUTH_ENABLED", "FHIRENGINE_AUTH_STRATEGY", "FHIRENGINE_OAUTH_DEFAULT_PATIENT"]) delete process.env[k]; });

  const authorize = async () => {
    const scope = "launch/patient openid fhirUser offline_access patient/*.rs";
    const qs = new URLSearchParams({ response_type: "code", client_id: "inferno", redirect_uri: REDIRECT, scope, aud: URLBASE, state: "xyz", code_challenge: challenge, code_challenge_method: "S256" });
    const r = await f(`/oauth/authorize?${qs.toString()}`);
    expect(r.status).toBe(302);
    const loc = new URL(r.headers.get("Location")!);
    expect(loc.searchParams.get("state")).toBe("xyz");
    return loc.searchParams.get("code")!;
  };
  const token = (params: Record<string, string>) =>
    f(`/oauth/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(params).toString() });

  it("authorize → token: issues a PKCE-bound access + id + refresh token with launch/patient", async () => {
    const code = await authorize();
    const r = await token({ grant_type: "authorization_code", code, redirect_uri: REDIRECT, client_id: "inferno", code_verifier: verifier });
    const t = await r.json();
    expect(r.status).toBe(200);
    expect(t.token_type).toBe("Bearer");
    expect(t.patient).toBe(P1);
    expect(t.id_token).toBeTruthy();       // openid
    expect(t.refresh_token).toBeTruthy();  // offline_access
    expect(decodeJwt(t.access_token).patient).toBe(P1); // launch context in the JWT
  });

  it("the issued token is accepted by our gate + enforces the patient compartment", async () => {
    const code = await authorize();
    const t = await (await token({ grant_type: "authorization_code", code, redirect_uri: REDIRECT, client_id: "inferno", code_verifier: verifier })).json();
    const bearer = { Authorization: `Bearer ${t.access_token}` };
    expect((await f(`/Observation`, { headers: bearer }) .then((r) => r.json())).total).toBe(1); // only P1
    expect((await f(`/Patient/${P1}`, { headers: bearer })).status).toBe(200);
    expect((await f(`/Patient/${P2}`, { headers: bearer })).status).toBe(404); // other patient hidden
    expect((await f(`/Observation/${obs2Id}`, { headers: bearer })).status).toBe(404);
  });

  it("PKCE mismatch is rejected (invalid_grant)", async () => {
    const code = await authorize();
    const r = await token({ grant_type: "authorization_code", code, redirect_uri: REDIRECT, client_id: "inferno", code_verifier: "wrong-verifier" });
    expect(r.status).toBe(400);
    expect((await r.json()).error).toBe("invalid_grant");
  });

  it("refresh_token yields a new access token", async () => {
    const code = await authorize();
    const t = await (await token({ grant_type: "authorization_code", code, redirect_uri: REDIRECT, client_id: "inferno", code_verifier: verifier })).json();
    const r = await token({ grant_type: "refresh_token", refresh_token: t.refresh_token, client_id: "inferno" });
    expect(r.status).toBe(200);
    expect((await r.json()).access_token).toBeTruthy();
  });

  it("publishes JWKS + discovery points at real endpoints", async () => {
    const jwks = await (await f(`/.well-known/jwks.json`)).json();
    expect(jwks.keys[0].kid).toBeTruthy();
    const disc = await (await f(`/.well-known/smart-configuration`)).json();
    expect(disc.authorization_endpoint).toBe(`${URLBASE}/oauth/authorize`);
    expect(disc.token_endpoint).toBe(`${URLBASE}/oauth/token`);
  });
});
