/**
 * HTTP-tier hardening (ADR-0033, Proposed) — mounted at the very top of the app so it applies
 * to every request, including auth denials. Composes:
 *   1. Security response headers (HSTS, nosniff, frame-ancestors none, strict CSP for a JSON API,
 *      Referrer-Policy, Cache-Control: no-store so PHI is never cached).
 *   2. CORS — actually ENFORCED from an allowlist (the CapabilityStatement previously advertised
 *      `cors:true` without enforcing anything).
 *   3. Body size limit (reject oversized payloads → 413).
 *   4. Rate limiting (DoS/abuse) — see rate-limit.ts.
 *
 * Defaults are non-breaking for dev/tests: headers always on (harmless), CORS permissive unless
 * an allowlist is configured, rate-limit + strict CORS engage in the `production` profile or when
 * explicitly enabled. Maps to HIPAA §164.312 + NIST SP 800-53 SC/AC + OWASP API hardening.
 */
import type { Hono } from "hono";
import { secureHeaders } from "hono/secure-headers";
import { cors } from "hono/cors";
import { bodyLimit } from "hono/body-limit";
import { rateLimit } from "./rate-limit.js";
import type { SecurityProfile } from "./profile.js";

export interface HardeningOptions {
  profile: SecurityProfile;
  env?: NodeJS.ProcessEnv;
}

const DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024; // 10 MiB — generous for FHIR transaction bundles
const DEFAULT_RATE_LIMIT_RPM = 600; // per client per minute (production default)

export function mountHttpHardening(app: Hono, opts: HardeningOptions): void {
  const env = opts.env ?? process.env;
  const isProd = opts.profile === "production";

  // 1) Security headers — strict for a machine-facing FHIR JSON API.
  app.use(
    "*",
    secureHeaders({
      strictTransportSecurity: "max-age=31536000; includeSubDomains",
      xContentTypeOptions: "nosniff",
      xFrameOptions: "DENY",
      referrerPolicy: "no-referrer",
      // JSON API serves no browser-executable content; lock it all down.
      contentSecurityPolicy: { defaultSrc: ["'none'"], frameAncestors: ["'none'"] },
      crossOriginOpenerPolicy: "same-origin",
      crossOriginResourcePolicy: "same-site",
      xPermittedCrossDomainPolicies: "none",
      // X-Powered-By is not set by Hono; nothing to strip.
    }),
  );

  // PHI must never be cached by intermediaries/browsers (§164.312(e); NIST SP 800-66r2).
  app.use("*", async (c, next) => {
    await next();
    c.header("Cache-Control", "no-store");
    c.header("Pragma", "no-cache");
  });

  // 2) CORS — enforce an allowlist when configured. In production with no allowlist, do NOT emit
  //    CORS headers (browsers then block cross-origin, i.e. same-origin only). In dev, be permissive.
  const origins = (env.RONIN_CORS_ORIGINS ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  if (origins.length) {
    app.use("*", cors({
      origin: origins,
      allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
      allowHeaders: ["Authorization", "Content-Type", "Accept", "If-Match", "If-None-Exist", "Prefer"],
      exposeHeaders: ["ETag", "Location", "Content-Location"],
      maxAge: 600,
      credentials: true,
    }));
  } else if (!isProd) {
    app.use("*", cors({ origin: "*", allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"] }));
  }
  // (production + no allowlist → no CORS middleware → cross-origin browser requests are blocked.)

  // 3) Body size limit.
  const maxBody = Number(env.RONIN_MAX_BODY_BYTES) || DEFAULT_MAX_BODY_BYTES;
  app.use("*", bodyLimit({
    maxSize: maxBody,
    onError: (c) =>
      c.json({ resourceType: "OperationOutcome", issue: [{ severity: "error", code: "too-costly", diagnostics: "Request body too large" }] }, 413),
  }));

  // 4) Rate limiting — on in production, or when explicitly enabled; off in dev by default so
  //    high-volume conformance/test runs aren't throttled.
  const rlEnabled = env.RONIN_RATE_LIMIT_ENABLED === "true" || (isProd && env.RONIN_RATE_LIMIT_ENABLED !== "false");
  if (rlEnabled) {
    const rpm = Number(env.RONIN_RATE_LIMIT_RPM) || DEFAULT_RATE_LIMIT_RPM;
    app.use("*", rateLimit({ limit: rpm, windowMs: 60_000 }));
  }
}
