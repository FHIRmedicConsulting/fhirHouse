{# SQL-on-FHIR helper macros (FH-0005) — the DuckDB functions every generated view
   model in models/views/ depends on. Installed by the on-run-start hook in
   dbt_project.yml. Definitions mirror fhirhouse_views.compiler.MACROS. #}
{% macro create_sof_macros() %}
  {% if execute %}
    {% do run_query("CREATE OR REPLACE MACRO sof_wrap(j) AS CASE WHEN j IS NULL THEN CAST([] AS JSON[]) WHEN json_type(j) = 'ARRAY' THEN CAST(j AS JSON[]) ELSE [j] END") %}
    {% do run_query("CREATE OR REPLACE MACRO sof_get(coll, key) AS flatten(list_transform(coll, jx -> sof_wrap(json_extract(jx, key))))") %}
    {% do run_query("CREATE OR REPLACE MACRO sof_one(coll) AS CASE WHEN coll IS NULL OR len(coll) = 0 THEN NULL WHEN len(coll) = 1 THEN coll[1] ELSE error('SoF: column value is a collection; declare collection: true') END") %}
    {% do run_query("CREATE OR REPLACE MACRO sof_text(coll) AS json_extract_string(sof_one(coll), '$')") %}
    {% do run_query("CREATE OR REPLACE MACRO sof_bool(coll) AS CAST(sof_text(coll) AS BOOLEAN)") %}
    {% do run_query("CREATE OR REPLACE MACRO sof_num(coll) AS CAST(sof_text(coll) AS DOUBLE)") %}
    {% do run_query("CREATE OR REPLACE MACRO sof_where(coll) AS CASE WHEN coll IS NULL OR len(coll) = 0 THEN false WHEN json_type(sof_one(coll)) = 'BOOLEAN' THEN sof_bool(coll) ELSE error('SoF: where clause must evaluate to boolean') END") %}
  {% endif %}
{% endmacro %}
