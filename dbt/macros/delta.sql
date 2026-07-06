{# Read-side Delta access (FH-0003): DuckDB's delta extension scans fhirEngine's tables
   in place. FHIRHOUSE_DELTA_BASE must match fhirEngine's FHIRENGINE_DELTA_BASE. #}
{% macro delta_table(tier, table) -%}
delta_scan('{{ env_var("FHIRHOUSE_DELTA_BASE", "./delta") }}/{{ tier }}/{{ table }}')
{%- endmacro %}
