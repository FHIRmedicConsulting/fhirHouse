# dq/ — data-quality scoring engine

Does **not** re-do fhirEngine's pre-Bronze L1–L4 validation. Scores the gaps
fhirEngine names (FH-0004 §1):

- **L5 IG/profile conformance** via the external HL7 Java validator (closed/max
  slices, discriminators, must-support).
- **Cross-record DQ** on the **Kahn framework**: conformance, completeness,
  plausibility — scored over populations, not single resources.

Runs Bronze→Silver in medallion; read-only pass in single-store (FH-0002). Emits a
versioned DQ score table consumed by the catalog.

## TODO (Claude Code)
- Package/invoke the HL7 validator (JVM dependency).
- Define the Kahn-dimension metric set + DQ score schema.
- Decide whether scores block or annotate promotion (open question, FH-0004).
