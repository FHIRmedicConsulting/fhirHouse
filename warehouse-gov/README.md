# warehouse-gov/ — catalog & governance binding

**Catalog: OpenMetadata** (FH-0004, decided 2026-07-06 by spike against the live
1,000-patient store). Bound via fhirEngine's catalog/governance seam (ADR-0025),
with Unity-Catalog-aligned naming so Databricks (UC-native) and standalone
deployments present one governance shape:

    OM service  = deployment            (≈ UC metastore binding)
    OM database = warehouse name        (= UC catalog)
    OM schema   = bronze|silver|gold    (= UC schema; medallion tier)
    OM table    = resource / governance (= UC table)

## Implementation (`fhirhouse_warehouse_gov/`)

`openmetadata.py` — stdlib REST binding (bot-JWT for production):
- `register_store` — every tier table, with FHIR column metadata derived from the
  contracts pin (scalars typed; complex elements JSON per the Silver encoding)
- `wire_tier_lineage` — bronze→silver→gold edges (chunked-promotion lane)
- `tag_phi_columns` — PII.Sensitive classification on demographic/body columns
- `push_dq_run` — a fhirHouse DQ run (gold/dq_score) as native OM test
  cases/results; OM evaluates pass/fail against `--min-score`

```bash
# OM quickstart (docker) on :8585, then:
python -m fhirhouse_warehouse_gov.openmetadata \
    --base ~/fhirhouse-demo/delta --database fhirhouse_demo --dq
```

Follow-ups: dbt/Dagster lineage ingestion (manifest-driven), glossary seeding
(FHIR resource-type glossary from the pin), DataHub integration remains possible
at the ADR-0025 seam for customers who already run one.
