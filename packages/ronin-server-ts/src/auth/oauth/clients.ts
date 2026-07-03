/**
 * OAuth client registry for the SMART auth server.
 *
 * `RONIN_OAUTH_CLIENTS` = JSON array of clients (production). When unset, dev-permissive mode:
 * any client_id is accepted as a public client (PKCE required), trusting the request redirect_uri.
 * Set the registry for production to lock down clients + redirect URIs.
 */
export interface OAuthClient {
  clientId: string;
  redirectUris?: string[];
  type?: "public" | "confidential";
  secret?: string;   // confidential symmetric (client_secret)
  jwksUri?: string;  // confidential asymmetric (backend services private_key_jwt) — future
}

function registry(): OAuthClient[] | null {
  const raw = process.env.RONIN_OAUTH_CLIENTS;
  if (!raw) return null;
  try { return JSON.parse(raw) as OAuthClient[]; } catch { return null; }
}

/** Resolve a client, or null if a registry is configured and the id is unknown. */
export function resolveClient(clientId: string): OAuthClient | null {
  const reg = registry();
  if (!reg) return { clientId, type: "public" }; // dev: accept any public client (+PKCE enforced)
  return reg.find((c) => c.clientId === clientId) ?? null;
}

export function redirectAllowed(client: OAuthClient, uri: string): boolean {
  if (!client.redirectUris?.length) return true; // dev: trust the request's redirect_uri
  return client.redirectUris.includes(uri);
}
