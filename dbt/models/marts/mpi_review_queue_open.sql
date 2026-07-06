-- Open HITL review queue (deterministic multi-match from fhirEngine + fhirHouse
-- probabilistic bands). Status transitions are new rows (ADR-0012 §2): a review is
-- open only if its LATEST row is still pending.
-- The table only exists once a first review has been queued — degrade to an empty
-- relation (not an error) before then, so a healthy zero-dupe deployment builds.
{% set review_path = env_var("FHIRHOUSE_DELTA_BASE", "./delta") ~ "/gold/patient_match_review" %}
{% set table_exists = false %}
{% if execute %}
  {% set probe = run_query("SELECT count(*) AS n FROM glob('" ~ review_path ~ "/_delta_log/*')") %}
  {% set table_exists = probe.columns[0][0] > 0 %}
{% endif %}

{% if table_exists %}
with reviews as (
    select * from {{ delta_table('gold', 'patient_match_review') }}
),
latest as (
    select *,
           row_number() over (partition by candidate_ids order by created_at desc) as _rn
    from reviews
)
select review_id, candidate_ids, reason, shared_identifiers, suggested_action, status, created_at
from latest
where _rn = 1 and status = 'pending'
{% else %}
select
    cast(null as varchar) as review_id,
    cast(null as varchar) as candidate_ids,
    cast(null as varchar) as reason,
    cast(null as varchar) as shared_identifiers,
    cast(null as varchar) as suggested_action,
    cast(null as varchar) as status,
    cast(null as varchar) as created_at
where false
{% endif %}
