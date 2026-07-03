/**
 * Token minting + PKCE for the SMART auth server. Access + id tokens are RS256 JWTs signed
 * with the server key (keys.ts); the auth gate verifies them via the same key (local strategy)
 * or the published JWKS. Claims match what jwks-auth reads (sub/scope/client_id/patient/fhirUser).
 */
import { SignJWT } from "jose";
import { createHash, timingSafeEqual } from "node:crypto";
import { keyMaterial, OAUTH_ALG } from "./keys.js";

export interface AccessTokenClaims {
  sub: string;
  scope: string;
  clientId: string;
  iss: string;
  aud: string;          // the FHIR base URL (SMART: access token audience = the resource server)
  patient?: string;
  encounter?: string;
  fhirUser?: string;
  ttlSeconds?: number;
}

export function signAccessToken(c: AccessTokenClaims): Promise<string> {
  const payload: Record<string, unknown> = { scope: c.scope, client_id: c.clientId };
  if (c.patient) payload.patient = c.patient;
  if (c.encounter) payload.encounter = c.encounter;
  if (c.fhirUser) payload.fhirUser = c.fhirUser;
  return signWithSub(payload, c.sub, c.iss, c.aud, c.ttlSeconds ?? 3600);
}

/** OIDC id_token — audience is the CLIENT, not the FHIR server. */
export function signIdToken(opts: { sub: string; iss: string; clientId: string; fhirUser?: string; nonce?: string; ttlSeconds?: number }): Promise<string> {
  const payload: Record<string, unknown> = {};
  if (opts.fhirUser) payload.fhirUser = opts.fhirUser;
  if (opts.nonce) payload.nonce = opts.nonce;
  payload.profile = opts.fhirUser; // SMART: profile claim mirrors fhirUser
  return signWithSub(payload, opts.sub, opts.iss, opts.clientId, opts.ttlSeconds ?? 3600);
}

async function signWithSub(payload: Record<string, unknown>, sub: string, iss: string, aud: string, ttlSeconds: number): Promise<string> {
  const { privateKey, kid } = await keyMaterial();
  return new SignJWT({ ...payload, sub })
    .setProtectedHeader({ alg: OAUTH_ALG, kid, typ: "JWT" })
    .setSubject(sub)
    .setIssuedAt()
    .setIssuer(iss)
    .setAudience(aud)
    .setExpirationTime(`${ttlSeconds}s`)
    .sign(privateKey);
}

/** PKCE verification (RFC 7636). S256 = base64url(sha256(verifier)) === challenge; plain = equal. */
export function verifyPkce(verifier: string | undefined, challenge: string | undefined, method: string | undefined): boolean {
  if (!challenge) return true; // no PKCE was requested at /authorize
  if (!verifier) return false;
  const computed = (method ?? "plain") === "S256"
    ? createHash("sha256").update(verifier).digest("base64url")
    : verifier;
  const a = Buffer.from(computed), b = Buffer.from(challenge);
  return a.length === b.length && timingSafeEqual(a, b);
}
