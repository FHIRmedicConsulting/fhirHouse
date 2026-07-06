# lineage/ — technical lineage + clinical provenance

Two distinct deliverables (FH-0004 §3):

- **Technical/asset lineage** — dbt model graph + Dagster asset graph, surfaced to
  the catalog.
- **Clinical provenance** — a bridge emitting/updating FHIR **Provenance**
  resources for governance transforms (extends the ADR-0012 §5 merge-Provenance
  pattern to DQ/cleaning), tied to fhirEngine's hash-chained audit (ADR-0016/0035).

## Implementation (`fhirhouse_lineage/`)

- `provenance.py` — the clinical Provenance bridge: `build_provenance` +
  `write_provenance` land Bronze-shaped Provenance rows via the sidecar (mirrors
  upstream's merge-Provenance pattern); used by mdm/ per probabilistic decision.
- Technical lineage (dbt + Dagster asset graph → catalog) is blocked on FH-0004's
  OpenMetadata-vs-DataHub choice; connectors will live in warehouse-gov/.
