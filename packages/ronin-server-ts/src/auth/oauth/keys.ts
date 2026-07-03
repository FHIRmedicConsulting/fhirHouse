/**
 * Signing keys for the SMART authorization server (ADR-0006 / ADR-0030).
 *
 * One RS256 keypair signs the access + id tokens; the public half is published at
 * `/.well-known/jwks.json` so clients (and our own auth gate, via the `local` strategy)
 * can verify them. Loaded from `RONIN_OAUTH_PRIVATE_KEY` (PKCS8 PEM) + `RONIN_OAUTH_PUBLIC_KEY`
 * (SPKI PEM) when BOTH are set, else an ephemeral keypair is generated at startup — fine for
 * dev/single-process; a persisted key is required for multi-instance / restart-stable tokens.
 */
import { generateKeyPair, importPKCS8, importSPKI, exportJWK, calculateJwkThumbprint } from "jose";

export const OAUTH_ALG = "RS256";

// jose v6 dropped the `KeyLike` export; derive the key type from the import functions.
type CryptoKeyLike = Awaited<ReturnType<typeof importPKCS8>>;

interface KeyMaterial {
  privateKey: CryptoKeyLike;
  publicKey: CryptoKeyLike;
  publicJwk: Record<string, unknown>; // includes kid/alg/use
  kid: string;
}

let cache: Promise<KeyMaterial> | null = null;

async function build(): Promise<KeyMaterial> {
  let privateKey: CryptoKeyLike, publicKey: CryptoKeyLike;
  const priv = process.env.RONIN_OAUTH_PRIVATE_KEY, pub = process.env.RONIN_OAUTH_PUBLIC_KEY;
  if (priv && pub) {
    privateKey = await importPKCS8(priv, OAUTH_ALG);
    publicKey = await importSPKI(pub, OAUTH_ALG);
  } else {
    const kp = await generateKeyPair(OAUTH_ALG, { extractable: true });
    privateKey = kp.privateKey;
    publicKey = kp.publicKey;
  }
  const jwk = await exportJWK(publicKey);
  const kid = await calculateJwkThumbprint(jwk);
  const publicJwk = { ...jwk, kid, alg: OAUTH_ALG, use: "sig" };
  return { privateKey, publicKey, publicJwk, kid };
}

export function keyMaterial(): Promise<KeyMaterial> {
  if (!cache) cache = build();
  return cache;
}

/** The public verification key (for the in-process `local` auth strategy). */
export async function verifyKey(): Promise<CryptoKeyLike> {
  return (await keyMaterial()).publicKey;
}

/** JWKS document for `/.well-known/jwks.json`. */
export async function publicJwks(): Promise<{ keys: Record<string, unknown>[] }> {
  return { keys: [(await keyMaterial()).publicJwk] };
}

/** Reset the cached key (tests / rotation). */
export function resetKeys(): void { cache = null; }
