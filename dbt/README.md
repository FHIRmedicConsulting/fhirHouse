# dbt/ — dbt-duckdb transforms + DQ-test models

DuckDB is the **read-side** engine (FH-0003); dbt-duckdb expresses **internal**
transforms and DQ-test models over fhirEngine's Delta tables. dbt/DuckDB never
write Delta — results are handed to fhirEngine's delta-rs writer.

- `models/staging/` — read/flatten Bronze/Silver via DuckDB (delta read + json).
- `models/marts/` — DQ inputs and internal marts; SoF-v2 ViewDefinitions
  (fhirEngine ADR-0027) remain the *published* contract, materialized here.

Set up: copy `profiles.example.yml` to `~/.dbt/profiles.yml` and point it at the
Delta root. `dbt parse` in CI.
