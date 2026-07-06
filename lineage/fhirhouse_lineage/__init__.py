"""fhirhouse_lineage — clinical provenance bridge + technical lineage surfacing (FH-0004 §3).

`provenance` extends fhirEngine's merge-Provenance pattern (ADR-0012 §5 / promote.ts
writeMergeProvenance) to every fhirHouse governance transform: DQ runs, probabilistic
match decisions, PPRL token generation. Provenance lands in Bronze via the sidecar
like any resource; fhirEngine's promotion serves it from Gold, and reverse-search by
Provenance.target yields a resource's full governance history.

Technical/asset lineage (dbt graph + Dagster asset graph → catalog) is wired in
warehouse-gov/ once FH-0004's catalog choice (OpenMetadata vs DataHub) closes.
"""
from .provenance import build_provenance, write_provenance

__all__ = ["build_provenance", "write_provenance"]
