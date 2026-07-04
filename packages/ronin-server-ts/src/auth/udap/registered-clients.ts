/**
 * UDAP dynamically-registered client registry (ADR-0036). Populated by the DCR endpoint and
 * consulted by the OAuth client resolver so a registered client can immediately use the token
 * endpoint (private_key_jwt / Backend Services).
 *
 * Durability: an in-memory Map is the hot cache (keeps `resolveClient` sync + fast); a Delta table
 * (`udap_client`) is the durable backing so registrations survive restarts and repopulate a fleet.
 * The DCR route writes through to both; the server loads the table into the cache on startup.
 */
import type { OAuthClient } from "../oauth/clients.js";
import type { WarehouseRow } from "../../lib/warehouse.js";

const registered = new Map<string, OAuthClient>();

/** Minimal persistence backend (DeltaWarehouse satisfies this; tests inject a fake). */
export interface UdapClientBackend {
  writeUdapClient(row: Record<string, unknown>): Promise<void>;
  registerUdapClients(): void;
  query<T extends WarehouseRow = WarehouseRow>(sql: string, params?: unknown[]): Promise<T[]>;
}

export function registerUdapClient(client: OAuthClient): void {
  registered.set(client.clientId, client);
}

export function getRegisteredClient(clientId: string): OAuthClient | null {
  return registered.get(clientId) ?? null;
}

/** Test helper — clear the in-memory cache. */
export function resetRegisteredClients(): void {
  registered.clear();
}

/** Durably persist a registration (append-only; latest-per-client_id wins on load). */
export async function persistUdapClient(wh: UdapClientBackend, client: OAuthClient, at: string): Promise<void> {
  await wh.writeUdapClient({
    client_id: client.clientId,
    jwks_json: client.jwks ? JSON.stringify(client.jwks) : "",
    redirect_uris_json: client.redirectUris ? JSON.stringify(client.redirectUris) : "",
    registered_at: at,
  });
}

interface StoredUdapClient extends WarehouseRow {
  client_id: string;
  jwks_json: string;
  redirect_uris_json: string;
  registered_at: string;
}

/** Load the durable registry into the in-memory cache (latest per client_id). Returns the count. */
export async function loadRegisteredClients(wh: UdapClientBackend): Promise<number> {
  try {
    wh.registerUdapClients();
    const rows = await wh.query<StoredUdapClient>(
      "SELECT client_id, jwks_json, redirect_uris_json, registered_at FROM udap_client",
    );
    const latest = new Map<string, StoredUdapClient>();
    for (const r of rows) {
      const prev = latest.get(r.client_id);
      if (!prev || String(r.registered_at) > String(prev.registered_at)) latest.set(r.client_id, r);
    }
    registered.clear();
    for (const r of latest.values()) {
      registered.set(r.client_id, {
        clientId: r.client_id,
        type: "confidential",
        jwks: r.jwks_json ? (JSON.parse(r.jwks_json) as OAuthClient["jwks"]) : undefined,
        redirectUris: r.redirect_uris_json ? (JSON.parse(r.redirect_uris_json) as string[]) : undefined,
      });
    }
    return registered.size;
  } catch {
    return 0; // table not provisioned yet → empty registry
  }
}
