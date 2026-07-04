/**
 * UDAP tiered OAuth — signed authorization request (RFC 9101 JAR). A client passes a `request` JWT
 * signed by its registered key; the AS verifies it and honors its claims over the query params.
 */
import { describe, it, expect, beforeAll, afterEach } from "vitest";
import { Hono } from "hono";
import { generateKeyPair, exportJWK, calculateJwkThumbprint, SignJWT } from "jose";
import { oauthRoutes } from "../../src/auth/oauth/oauth-routes.js";
import { resetKeys } from "../../src/auth/oauth/keys.js";

const BASE = "http://fhirengine.test";
const CID = "https://app.example/fhir";
const REDIRECT = "https://app.example/cb";

let priv: Awaited<ReturnType<typeof generateKeyPair>>["privateKey"];
let kid: string;

const signedRequest = async (over: { key?: typeof priv } = {}) =>
  new SignJWT({ response_type: "code", client_id: CID, redirect_uri: REDIRECT, scope: "system/*.rs", state: "xyz", aud: BASE })
    .setProtectedHeader({ alg: "RS256", kid })
    .setIssuer(CID).setSubject(CID).setIssuedAt().setExpirationTime("5m")
    .sign(over.key ?? priv);

beforeAll(async () => {
  const kp = await generateKeyPair("RS256", { extractable: true });
  priv = kp.privateKey;
  const jwk = await exportJWK(kp.publicKey);
  kid = await calculateJwkThumbprint(jwk);
  resetKeys();
  process.env.FHIRENGINE_OAUTH_CLIENTS = JSON.stringify([{ clientId: CID, type: "confidential", jwks: { keys: [{ ...jwk, kid, alg: "RS256", use: "sig" }] } }]);
});
afterEach(() => { /* keep FHIRENGINE_OAUTH_CLIENTS for the suite */ });

describe("signed authorization request (RFC 9101)", () => {
  const app = () => { const a = new Hono(); a.route("/", oauthRoutes(BASE)); return a; };

  it("honors a validly-signed request object → redirects with a code", async () => {
    const req = await signedRequest();
    const res = await app().request(`/oauth/authorize?client_id=${encodeURIComponent(CID)}&request=${encodeURIComponent(req)}`);
    expect(res.status).toBe(302);
    const loc = new URL(res.headers.get("Location")!);
    expect(loc.origin + loc.pathname).toBe(REDIRECT);
    expect(loc.searchParams.get("code")).toBeTruthy();
    expect(loc.searchParams.get("state")).toBe("xyz");
  });

  it("rejects a request object signed by the WRONG key (400)", async () => {
    const otherKey = (await generateKeyPair("RS256", { extractable: true })).privateKey;
    const req = await signedRequest({ key: otherKey });
    const res = await app().request(`/oauth/authorize?client_id=${encodeURIComponent(CID)}&request=${encodeURIComponent(req)}`);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("invalid_request");
  });

  it("rejects a signed request for an unregistered client (400)", async () => {
    const req = await signedRequest();
    const res = await app().request(`/oauth/authorize?client_id=${encodeURIComponent("https://unknown/x")}&request=${encodeURIComponent(req)}`);
    expect(res.status).toBe(400);
  });
});
