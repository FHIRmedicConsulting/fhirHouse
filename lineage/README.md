# lineage/ — technical lineage + clinical provenance

Two distinct deliverables (FH-0004 §3):

- **Technical/asset lineage** — dbt model graph + Dagster asset graph, surfaced to
  the catalog.
- **Clinical provenance** — a bridge emitting/updating FHIR **Provenance**
  resources for governance transforms (extends the ADR-0012 §5 merge-Provenance
  pattern to DQ/cleaning), tied to fhirEngine's hash-chained audit (ADR-0016/0035).

## TODO (Claude Code)
- Wire dbt + Dagster lineage ingestion into the chosen catalog (see warehouse-gov).
- Implement the Provenance bridge; write via fhirEngine's writer.
