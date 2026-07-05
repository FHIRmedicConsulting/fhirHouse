/**
 * Structural validation: unknown/extra-element rejection (validation hardening). Previously the
 * validator only checked schema elements and never the resource's own keys, so typo'd/garbage
 * elements passed clean — the single biggest "invalid resources pass" hole.
 */
import { describe, it, expect } from "vitest";
import { validateStructuralOnly } from "../../../src/validation/validation-chain.js";

const msgs = (r: { issues: { message: string }[] }) => r.issues.map((i) => i.message).join(" | ");

describe("structural validation — unknown-element rejection", () => {
  it("rejects a garbage element", () => {
    const r = validateStructuralOnly({ resourceType: "Patient", gender: "female", notARealField: "x" });
    expect(r.valid).toBe(false);
    expect(msgs(r)).toContain("unknown element 'notARealField'");
  });

  it("rejects a typo'd element (deceasedBolean → deceasedBoolean)", () => {
    const r = validateStructuralOnly({ resourceType: "Patient", deceasedBolean: true });
    expect(r.valid).toBe(false);
    expect(msgs(r)).toContain("unknown element 'deceasedBolean'");
  });

  it("accepts FHIR base elements the columnar schema drops (meta/text/extension/contained)", () => {
    const r = validateStructuralOnly({
      resourceType: "Patient",
      meta: { profile: ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"] },
      text: { status: "generated", div: "<div/>" },
      extension: [{ url: "http://x", valueString: "y" }],
      contained: [{ resourceType: "Organization", id: "o1" }],
      gender: "female",
    });
    expect(r.valid, msgs(r)).toBe(true);
  });

  it("accepts a primitive-extension sibling (_birthDate for birthDate)", () => {
    const r = validateStructuralOnly({
      resourceType: "Patient",
      birthDate: "1990-01-01",
      _birthDate: { extension: [{ url: "http://x", valueCode: "y" }] },
    });
    expect(r.valid, msgs(r)).toBe(true);
  });

  it("rejects a valid-looking but wrong choice-type name (valueString on a non-choice)", () => {
    // Observation.value[x] is a real choice; `valueStrng` (typo) is not a column → rejected.
    const r = validateStructuralOnly({ resourceType: "Observation", status: "final", code: { text: "x" }, valueStrng: "typo" });
    expect(r.valid).toBe(false);
    expect(msgs(r)).toContain("valueStrng");
  });
});
