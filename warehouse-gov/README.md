# warehouse-gov/ — catalog & governance binding

Integrate a mature OSS catalog (not build one), bound via fhirEngine's
catalog/governance seam (ADR-0025).

- **Candidate: OpenMetadata** — native profiler + DQ tests + glossary fit the DQ
  scope.
- **Alternative: DataHub** — stronger discovery/lineage at scale.

**Decision deferred** pending a short spike (FH-0004 open question). This module
owns the connectors, glossary/ownership metadata, and DQ/lineage surfacing.
