/**
 * Live OCSP revocation (ADR-0036, RFC 6960): OcspRevocationChecker queries a responder and rejects a
 * revoked cert; verifySoftwareStatement enforces it. Uses a real openssl CA + offline OCSP responses.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync as read } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { X509Certificate } from "node:crypto";
import { SignJWT, importPKCS8 } from "jose";
import { OcspRevocationChecker } from "../../src/auth/udap/ocsp.js";
import { verifySoftwareStatement } from "../../src/auth/udap/software-statement.js";

const REG = "http://fhirengine.test/udap/register";
const CID = "https://client.example/fhir";
const OCSP_URL = "http://ocsp.test";

let ok = true;
let dir: string;
let caCert: X509Certificate, leaf1: X509Certificate, leaf2: X509Certificate;
let leaf1Key: string, leaf1Der: string;
let resp1: Uint8Array, resp2: Uint8Array;

beforeAll(() => {
  try {
    dir = mkdtempSync(join(tmpdir(), "fhirengine-ocsp-"));
    const p = (f: string) => join(dir, f);
    const ossl = (...a: string[]) => execFileSync("openssl", a, { cwd: dir });
    ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.crt", "-days", "5", "-subj", "/CN=fhirEngine OCSP Test CA");
    writeFileSync(p("index.txt"), ""); writeFileSync(p("serial"), "1000\n"); writeFileSync(p("crlnumber"), "1000\n");
    writeFileSync(p("openssl.cnf"),
      "[ca]\ndefault_ca=CA_default\n[CA_default]\ndatabase=./index.txt\nnew_certs_dir=.\ncertificate=./ca.crt\n" +
      "private_key=./ca.key\nserial=./serial\ncrlnumber=./crlnumber\ndefault_md=sha256\ndefault_days=3\n" +
      "default_crl_days=5\npolicy=policy_any\n[policy_any]\ncommonName=supplied\n");
    for (const n of ["1", "2"]) {
      ossl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", `leaf${n}.key`, "-out", `leaf${n}.csr`, "-subj", `/CN=leaf${n}`);
      ossl("ca", "-batch", "-config", "openssl.cnf", "-in", `leaf${n}.csr`, "-out", `leaf${n}.crt`);
    }
    ossl("ca", "-batch", "-config", "openssl.cnf", "-revoke", "leaf1.crt"); // revoke leaf1
    // Offline OCSP responses (signed by the CA): leaf1 = revoked, leaf2 = good.
    const mkResp = (n: string) => { ossl("ocsp", "-index", "index.txt", "-CA", "ca.crt", "-rsigner", "ca.crt", "-rkey", "ca.key", "-issuer", "ca.crt", "-cert", `leaf${n}.crt`, "-respout", `resp${n}.der`); return new Uint8Array(read(p(`resp${n}.der`))); };
    resp1 = mkResp("1"); resp2 = mkResp("2");
    caCert = new X509Certificate(read(p("ca.crt"), "utf8"));
    leaf1 = new X509Certificate(read(p("leaf1.crt"), "utf8"));
    leaf2 = new X509Certificate(read(p("leaf2.crt"), "utf8"));
    leaf1Key = read(p("leaf1.key"), "utf8");
    leaf1Der = Buffer.from(execFileSync("openssl", ["x509", "-in", "leaf1.crt", "-outform", "DER"], { cwd: dir })).toString("base64");
  } catch { ok = false; }
});
afterAll(() => { delete process.env.FHIRENGINE_UDAP_OCSP_URLS; delete process.env.FHIRENGINE_UDAP_OCSP_HARD_FAIL; delete process.env.FHIRENGINE_UDAP_OCSP_CHECK; });

const checker = (fetch: () => Promise<Uint8Array>, env: Record<string, string> = {}) =>
  new OcspRevocationChecker(async () => fetch().then((b) => b), { FHIRENGINE_UDAP_OCSP_URLS: OCSP_URL, ...env } as NodeJS.ProcessEnv);

describe.skipIf(!ok)("live OCSP revocation", () => {
  it("flags a revoked cert and clears a good one (signed OCSP response verified vs the CA)", async () => {
    expect((await checker(async () => resp1).isRevoked(leaf1, caCert)).revoked).toBe(true);
    expect((await checker(async () => resp2).isRevoked(leaf2, caCert)).revoked).toBe(false);
  });

  it("soft-fails when the responder is unreachable (not revoked)", async () => {
    const c = checker(async () => { throw new Error("down"); });
    expect((await c.isRevoked(leaf1, caCert)).revoked).toBe(false);
  });

  it("hard-fail rejects when the responder is unreachable", async () => {
    const c = checker(async () => { throw new Error("down"); }, { FHIRENGINE_UDAP_OCSP_HARD_FAIL: "true" });
    expect((await c.isRevoked(leaf1, caCert)).revoked).toBe(true);
  });

  it("verifySoftwareStatement rejects a software statement from an OCSP-revoked cert", async () => {
    const key = await importPKCS8(leaf1Key, "RS256");
    const jwt = await new SignJWT({ client_name: "x", grant_types: ["client_credentials"] })
      .setProtectedHeader({ alg: "RS256", x5c: [leaf1Der] })
      .setIssuer(CID).setSubject(CID).setAudience(REG).setIssuedAt().setJti("j1").setExpirationTime("5m").sign(key);
    await expect(
      verifySoftwareStatement(jwt, { audience: REG, anchors: [caCert], ocspChecker: checker(async () => resp1) }),
    ).rejects.toThrow(/revoked/i);
  });
});
