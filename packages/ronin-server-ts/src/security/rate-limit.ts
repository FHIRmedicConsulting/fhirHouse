/**
 * In-memory fixed-window rate limiter (ADR-0033, Proposed) — DoS / abuse protection at the
 * HTTP tier. Keyed by authenticated client_id when present, else client IP. Emits standard
 * `RateLimit-*` + `Retry-After` headers and a 429 OperationOutcome when exceeded.
 *
 * Scope note: this is a SINGLE-NODE limiter (per-process counters). A multi-node deployment
 * needs a shared store (e.g. Redis) or limiting at the ingress/LB — documented as a follow-up.
 * That is fine for Alpha (single-node) and as a per-instance backstop behind an LB.
 */
import type { MiddlewareHandler } from "hono";

export interface RateLimitOptions {
  /** Max requests per window per client. */
  limit: number;
  /** Window length in milliseconds. */
  windowMs: number;
  /** Clock injection for tests. */
  now?: () => number;
}

interface Counter {
  count: number;
  resetAt: number;
}

/** Client key: prefer the authenticated client_id (set by the auth gate), else the peer IP. */
function clientKey(c: Parameters<MiddlewareHandler>[0]): string {
  const auth = c.get("auth") as { clientId?: string } | undefined;
  if (auth?.clientId) return `cid:${auth.clientId}`;
  const fwd = c.req.header("x-forwarded-for");
  const ip = fwd ? fwd.split(",")[0]!.trim() : c.req.header("x-real-ip") ?? "unknown";
  return `ip:${ip}`;
}

/**
 * Build a rate-limit middleware. The returned handler carries a `.store` for test inspection
 * and a `.sweep()` to evict expired counters (called opportunistically).
 */
export function rateLimit(opts: RateLimitOptions): MiddlewareHandler & { store: Map<string, Counter>; sweep: () => void } {
  const now = opts.now ?? Date.now;
  const store = new Map<string, Counter>();

  const sweep = () => {
    const t = now();
    for (const [k, v] of store) if (v.resetAt <= t) store.delete(k);
  };

  const mw: MiddlewareHandler = async (c, next) => {
    const t = now();
    const key = clientKey(c);
    let entry = store.get(key);
    if (!entry || entry.resetAt <= t) {
      entry = { count: 0, resetAt: t + opts.windowMs };
      store.set(key, entry);
      if (store.size > 10_000) sweep(); // bound memory under key churn
    }
    entry.count += 1;

    const remaining = Math.max(0, opts.limit - entry.count);
    const resetSecs = Math.max(0, Math.ceil((entry.resetAt - t) / 1000));
    c.header("RateLimit-Limit", String(opts.limit));
    c.header("RateLimit-Remaining", String(remaining));
    c.header("RateLimit-Reset", String(resetSecs));

    if (entry.count > opts.limit) {
      c.header("Retry-After", String(resetSecs));
      return c.json(
        {
          resourceType: "OperationOutcome",
          issue: [{ severity: "error", code: "throttled", diagnostics: "Rate limit exceeded. Retry later." }],
        },
        429,
      );
    }
    await next();
    return;
  };

  return Object.assign(mw, { store, sweep });
}
