/**
 * Security profile + fail-closed startup validation (ADR-0032, Proposed).
 *
 * The server ships with all PHI controls (auth, audit, consent) opt-in and OFF — correct for
 * synthetic dev/conformance. That is dangerous as a *production* default: nothing stops an
 * operator from exposing PHI with the gate off. This module makes the posture explicit and
 * *fails closed*: when `FHIRENGINE_SECURITY_PROFILE=production`, the server REFUSES TO BOOT unless
 * the required controls are on.
 *
 *   FHIRENGINE_SECURITY_PROFILE = dev (default) | production
 *   FHIRENGINE_TLS_TERMINATED_AT_PROXY = true    operator attests TLS is terminated upstream
 *                                           (satisfies the transmission-security requirement
 *                                            when FHIRENGINE_TLS_CERT/KEY are not set on this process)
 *
 * Maps to HIPAA §164.312 (access control, audit, transmission security) + NIST SP 800-53
 * (AC/AU/SC families). Dev profile only warns; it never blocks.
 */
import { authEnabled } from "../auth/configure.js";
import { auditEnabled } from "../audit/configure.js";
import { consentEnabled } from "../auth/consent-enforce.js";
import { oauthEnabled } from "../auth/oauth/oauth-routes.js";

export type SecurityProfile = "dev" | "production";

export function securityProfile(env: NodeJS.ProcessEnv = process.env): SecurityProfile {
  return env.FHIRENGINE_SECURITY_PROFILE === "production" ? "production" : "dev";
}

export interface PostureInput {
  /** Whether the in-process HTTPS listener is configured (from buildTlsConfig().enabled). */
  tlsInProcess: boolean;
}

export interface PostureResult {
  profile: SecurityProfile;
  ok: boolean;
  errors: string[];
  warnings: string[];
}

/**
 * Evaluate the security posture for the active profile.
 * - production: unmet MUSTs become `errors` (→ server should refuse to boot).
 * - dev: everything is advisory (`warnings`); `ok` is always true.
 */
export function evaluateSecurityPosture(input: PostureInput): PostureResult {
  const env = process.env;
  const profile = securityProfile(env);
  const errors: string[] = [];
  const warnings: string[] = [];

  const tlsSatisfied = input.tlsInProcess || env.FHIRENGINE_TLS_TERMINATED_AT_PROXY === "true";
  const oauthOn = oauthEnabled();
  const ephemeralOauthKeys = oauthOn && !(env.FHIRENGINE_OAUTH_PRIVATE_KEY && env.FHIRENGINE_OAUTH_PUBLIC_KEY);

  // Each check: (unmet?, message). In production unmet → error; in dev → warning.
  const checks: Array<{ unmet: boolean; msg: string; hardEvenInDev?: boolean }> = [
    { unmet: !authEnabled(), msg: "authentication is disabled (set FHIRENGINE_AUTH_ENABLED=true) — §164.312(a)(d)" },
    { unmet: !auditEnabled(), msg: "audit logging is disabled (set FHIRENGINE_AUDIT_ENABLED=true) — §164.312(b)" },
    { unmet: !tlsSatisfied, msg: "no transport security: set FHIRENGINE_TLS_CERT/KEY, or FHIRENGINE_TLS_TERMINATED_AT_PROXY=true if a proxy terminates TLS — §164.312(e)" },
    { unmet: ephemeralOauthKeys, msg: "OAuth server uses EPHEMERAL signing keys (rotate on restart, invalidating live tokens): set FHIRENGINE_OAUTH_PRIVATE_KEY/PUBLIC_KEY" },
    // Consent is deployment-dependent (not every server segments on consent) → advisory even in prod.
    { unmet: !consentEnabled(), msg: "consent enforcement is off (FHIRENGINE_CONSENT_ENFORCEMENT) — required if serving data subject to consent/DS4P/42 CFR Part 2", hardEvenInDev: false },
  ];

  const advisoryOnly = new Set([
    "consent enforcement is off (FHIRENGINE_CONSENT_ENFORCEMENT) — required if serving data subject to consent/DS4P/42 CFR Part 2",
  ]);

  for (const c of checks) {
    if (!c.unmet) continue;
    if (profile === "production" && !advisoryOnly.has(c.msg)) errors.push(c.msg);
    else warnings.push(c.msg);
  }

  return { profile, ok: errors.length === 0, errors, warnings };
}
