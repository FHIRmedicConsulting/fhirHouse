-- Latest DQ run per (resource_type, tier): the governance dashboard's primary read
-- (consumed by the catalog binding in warehouse-gov/). Source table is written by
-- dq/fhirhouse_dq via the sidecar; shape pinned in contracts/gold_schema.snapshot.json.
with scores as (
    select * from {{ delta_table('gold', 'dq_score') }}
),
latest as (
    select resource_type, tier, max(computed_at) as computed_at
    from scores
    group by 1, 2
)
select s.*
from scores s
join latest l
  on s.resource_type = l.resource_type
 and s.tier = l.tier
 and s.computed_at = l.computed_at
