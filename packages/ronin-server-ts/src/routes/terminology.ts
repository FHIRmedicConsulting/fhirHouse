/**
 * FHIR terminology *operation* endpoints — exposing the local Delta-backed terminology store
 * (the same `validateCode` used internally for L3 binding validation) as a real terminology
 * server, so external clients — including the HL7 validator Inferno drives — can use THIS
 * server for `$validate-code` / `$expand` / `$lookup` instead of a remote tx server.
 *
 *   POST|GET /ValueSet/$validate-code    (url = ValueSet, + code/system or coding)
 *   POST|GET /CodeSystem/$validate-code  (url|system = CodeSystem, + code or coding)
 *   POST|GET /ValueSet/$expand           (url = ValueSet)
 *   POST|GET /CodeSystem/$lookup         (system + code or coding)
 *
 * These MUST be mounted before the generic `/:resourceType/:id` routes.
 */
import { Hono } from "hono";
import type { DeltaWarehouse } from "../lib/delta-warehouse.js";
import { validateCode } from "../terminology/validate-code.js";

/** Read operation params from the query string and/or a POST `Parameters` body (coding too). */
async function readParams(c: any): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (const [k, v] of new URL(c.req.url).searchParams) out[k] = v;
  if (c.req.method === "POST") {
    const body = await c.req.json().catch(() => null);
    if (body?.resourceType === "Parameters") {
      for (const p of body.parameter ?? []) {
        if (p.valueUri != null) out[p.name] = p.valueUri;
        else if (p.valueString != null) out[p.name] = p.valueString;
        else if (p.valueCode != null) out[p.name] = p.valueCode;
        else if (p.valueBoolean != null) out[p.name] = String(p.valueBoolean);
        else if (p.valueCoding) { out.system = p.valueCoding.system ?? out.system; out.code = p.valueCoding.code ?? out.code; if (p.valueCoding.display) out.display = p.valueCoding.display; }
      }
    } else if (body?.resourceType === "ValueSet" && body.url) {
      out.url = body.url; // inline ValueSet → validate against its canonical (if loaded)
    }
  }
  return out;
}

const param = (name: string, value: unknown, kind = "valueString") =>
  value === undefined || value === null ? [] : [{ name, [kind]: value }];

/** OperationOutcome carried in the `issues` param — severity drives how the validator reports it. */
function issues(severity: "error" | "warning", code: string, text: string) {
  return { name: "issues", resource: { resourceType: "OperationOutcome", issue: [{ severity, code, details: { text } }] } };
}

export function terminologyRoutes(wh: DeltaWarehouse): Hono {
  const app = new Hono();

  const doValidateCode = (kind: "valueSet" | "codeSystem") => async (c: any) => {
    const p = await readParams(c);
    const code = p.code;
    const target = p.url ?? (kind === "codeSystem" ? p.system : undefined);
    if (!code || !target) {
      return c.json({ resourceType: "Parameters", parameter: [{ name: "result", valueBoolean: false }, ...param("message", `${kind} $validate-code requires url${kind === "codeSystem" ? "|system" : ""} + code`)] }, 400);
    }
    const r = await validateCode(wh, kind === "valueSet" ? { code, valueSet: target, system: p.system } : { code, system: target });
    const parameter: any[] = [{ name: "result", valueBoolean: r.result }];
    if (r.display) parameter.push({ name: "display", valueString: r.display });
    if (p.system) parameter.push({ name: "system", valueUri: p.system });
    parameter.push({ name: "code", valueCode: code });
    if (r.message) parameter.push({ name: "message", valueString: r.message });
    // 3-state → issue severity: invalid = error; unknown (not loaded) = warning (can't validate).
    if (r.status === "invalid") parameter.push(issues("error", "code-invalid", r.message ?? "invalid code"));
    else if (r.status === "unknown") parameter.push(issues("warning", "not-found", r.message ?? "not validated"));
    return c.json({ resourceType: "Parameters", parameter });
  };

  app.get("/ValueSet/$validate-code", doValidateCode("valueSet"));
  app.post("/ValueSet/$validate-code", doValidateCode("valueSet"));
  app.get("/CodeSystem/$validate-code", doValidateCode("codeSystem"));
  app.post("/CodeSystem/$validate-code", doValidateCode("codeSystem"));

  const doExpand = async (c: any) => {
    const p = await readParams(c);
    if (!p.url) return c.json({ resourceType: "OperationOutcome", issue: [{ severity: "error", code: "required", details: { text: "$expand requires url" } }] }, 400);
    const count = Math.max(0, Math.min(Number(p.count ?? "1000"), 5000));
    wh.registerTerminology("valueset_expansion");
    const rows = await wh.query<{ system: string; code: string; display: string | null }>(
      `SELECT system, code, display FROM valueset_expansion WHERE valueset = ? LIMIT ${count}`, [p.url],
    );
    return c.json({
      resourceType: "ValueSet", url: p.url, status: "active",
      expansion: {
        timestamp: new Date().toISOString(), total: rows.length,
        contains: rows.map((r) => ({ system: r.system, code: r.code, ...(r.display ? { display: r.display } : {}) })),
      },
    });
  };
  app.get("/ValueSet/$expand", doExpand);
  app.post("/ValueSet/$expand", doExpand);

  const doLookup = async (c: any) => {
    const p = await readParams(c);
    if (!p.system || !p.code) return c.json({ resourceType: "OperationOutcome", issue: [{ severity: "error", code: "required", details: { text: "$lookup requires system + code" } }] }, 400);
    wh.registerTerminology("codesystem_concept");
    const hit = await wh.query<{ display: string | null }>(
      "SELECT display FROM codesystem_concept WHERE system = ? AND code = ? LIMIT 1", [p.system, p.code],
    );
    if (!hit.length) return c.json({ resourceType: "Parameters", parameter: [...param("message", `code '${p.code}' not found in ${p.system}`), issues("error", "not-found", "code not found")] }, 404);
    return c.json({ resourceType: "Parameters", parameter: [...param("name", p.system, "valueString"), ...param("display", hit[0].display ?? "", "valueString")] });
  };
  app.get("/CodeSystem/$lookup", doLookup);
  app.post("/CodeSystem/$lookup", doLookup);

  return app;
}
