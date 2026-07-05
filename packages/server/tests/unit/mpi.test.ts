/**
 * Deterministic MPI (ADR-0012 v1): identifier normalization, candidate components,
 * hard-deny guardrails (§3.4 safety floors), survivor selection, reference rewrite.
 */
import { describe, it, expect } from "vitest";
import { normalizeIdentifier, resolveIdentities, guardrail, rewriteReferences, type MpiPatientRow } from "../../src/repository/mpi.js";

const SSN = "http://hl7.org/fhir/sid/us-ssn";
const MRN = "urn:oid:1.2.840.114350";

const patient = (id: string, updated: string, body: Record<string, unknown>): MpiPatientRow => ({
  id, last_updated: updated, body: { resourceType: "Patient", id, ...body },
});
const withMrn = (id: string, updated: string, mrn: string, extra: Record<string, unknown> = {}) =>
  patient(id, updated, { identifier: [{ system: MRN, value: mrn }], ...extra });

describe("normalizeIdentifier", () => {
  it("canonicalizes URL systems and trims values", () => {
    expect(normalizeIdentifier("HTTP://Hospital.ORG/mrn/", " 123 ")).toBe("http://hospital.org/mrn|123");
  });
  it("collapses SSN formatting", () => {
    expect(normalizeIdentifier(SSN, "123-45-6789")).toBe(`${SSN}|123456789`);
  });
  it("null on empty value", () => {
    expect(normalizeIdentifier(MRN, "  ")).toBeNull();
  });
});

describe("resolveIdentities — deterministic dedup", () => {
  it("two patients sharing an MRN auto-merge; latest write survives", () => {
    const r = resolveIdentities([withMrn("a", "2026-01-01T00:00:00Z", "M1"), withMrn("b", "2026-02-01T00:00:00Z", "M1")]);
    expect(r.merges).toEqual([expect.objectContaining({ survivorId: "b", mergedId: "a" })]);
    expect(r.survivorOf.get("a")).toBe("b");
    expect(r.links.get(`${MRN}|M1`)).toBe("b");
  });

  it("distinct identifiers → no merge, links point at each record", () => {
    const r = resolveIdentities([withMrn("a", "2026-01-01T00:00:00Z", "M1"), withMrn("b", "2026-01-01T00:00:00Z", "M2")]);
    expect(r.merges).toHaveLength(0);
    expect(r.reviews).toHaveLength(0);
    expect(r.links.get(`${MRN}|M1`)).toBe("a");
    expect(r.links.get(`${MRN}|M2`)).toBe("b");
  });

  it("multi-match (3+ candidates) goes to review, never auto-merged (ADR §1)", () => {
    const r = resolveIdentities([
      withMrn("a", "1", "M1"), withMrn("b", "2", "M1"), withMrn("c", "3", "M1"),
    ]);
    expect(r.merges).toHaveLength(0);
    expect(r.reviews).toEqual([expect.objectContaining({ reason: "multi_match", ids: expect.arrayContaining(["a", "b", "c"]) })]);
  });

  it("sex mismatch guardrail blocks the merge → review", () => {
    const r = resolveIdentities([
      withMrn("a", "1", "M1", { gender: "female" }),
      withMrn("b", "2", "M1", { gender: "male" }),
    ]);
    expect(r.merges).toHaveLength(0);
    expect(r.reviews[0]).toMatchObject({ reason: "sex_mismatch" });
  });

  it("conflicting SSNs are HARD DISTINCT — no merge, no review (auto-create per ADR)", () => {
    const r = resolveIdentities([
      withMrn("a", "1", "M1", { identifier: [{ system: MRN, value: "M1" }, { system: SSN, value: "111-11-1111" }] }),
      withMrn("b", "2", "M1", { identifier: [{ system: MRN, value: "M1" }, { system: SSN, value: "222-22-2222" }] }),
    ]);
    expect(r.merges).toHaveLength(0);
    expect(r.reviews).toHaveLength(0);
  });

  it("date-of-death mismatch beyond the window → review", () => {
    const r = resolveIdentities([
      withMrn("a", "1", "M1", { deceasedDateTime: "2026-01-01" }),
      withMrn("b", "2", "M1", { deceasedDateTime: "2026-03-01" }),
    ]);
    expect(r.reviews[0]).toMatchObject({ reason: "date_of_death_mismatch" });
  });

  it("inactive (merged-away) patients are not candidates", () => {
    const r = resolveIdentities([withMrn("a", "1", "M1", { active: false }), withMrn("b", "2", "M1")]);
    expect(r.merges).toHaveLength(0);
    expect(r.reviews).toHaveLength(0);
  });

  it("gender unknown does not trip the sex guardrail", () => {
    expect(guardrail(
      withMrn("a", "1", "M1", { gender: "unknown" }),
      withMrn("b", "2", "M1", { gender: "female" }),
    )).toBeNull();
  });
});

describe("rewriteReferences", () => {
  it("rewrites merged Patient references to the survivor", () => {
    const body = JSON.stringify({ subject: { reference: "Patient/old" }, performer: [{ reference: "Patient/other" }] });
    const out = rewriteReferences(body, new Map([["old", "new"]]));
    expect(JSON.parse(out).subject.reference).toBe("Patient/new");
    expect(JSON.parse(out).performer[0].reference).toBe("Patient/other");
  });
});
