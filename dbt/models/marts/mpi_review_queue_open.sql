-- Open HITL review queue (deterministic multi-match from fhirEngine + fhirHouse
-- probabilistic bands). Status transitions are new rows (ADR-0012 §2): a review is
-- open only if its LATEST row is still pending.
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
