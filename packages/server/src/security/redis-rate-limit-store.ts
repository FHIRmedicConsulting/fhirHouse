/**
 * Redis-backed rate-limit store (ADR-0033 follow-up) — makes rate limits consistent across
 * instances behind a load balancer (the in-process MemoryRateLimitStore is per-node).
 *
 * NO forced dependency: this takes an injected Redis-eval client (a tiny interface `ioredis` and
 * `node-redis` both satisfy). Single-node deployments never load Redis. The server wires this only
 * when `FHIRENGINE_RATE_LIMIT_STORE=redis` + `FHIRENGINE_REDIS_URL` (see server.ts, which lazy-imports the
 * client). Fully unit-testable with a fake client.
 *
 * Fixed-window via an atomic Lua script (INCR + PEXPIRE-on-first-hit) — no INCR/EXPIRE race.
 */
import type { RateLimitStore, RateLimitState } from "./rate-limit.js";

/** The minimal Redis surface this store needs (ioredis: `eval(script, numKeys, ...args)`). */
export interface RedisEvalClient {
  eval(script: string, numKeys: number, ...args: Array<string | number>): Promise<unknown>;
}

const FIXED_WINDOW_LUA =
  "local c = redis.call('INCR', KEYS[1]) " +
  "if c == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end " +
  "return {c, redis.call('PTTL', KEYS[1])}";

export class RedisRateLimitStore implements RateLimitStore {
  constructor(private readonly redis: RedisEvalClient, private readonly prefix = "fhirengine:rl:") {}

  async hit(key: string, windowMs: number, now: number): Promise<RateLimitState> {
    const res = (await this.redis.eval(FIXED_WINDOW_LUA, 1, this.prefix + key, windowMs)) as [number, number];
    const count = Number(res[0]);
    const ttl = Number(res[1]);
    return { count, resetAt: now + (ttl > 0 ? ttl : windowMs) };
  }
}
