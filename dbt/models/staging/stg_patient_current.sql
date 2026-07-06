-- Current (non-deleted) Bronze Patients with the demographic columns DQ/MDM marts use,
-- extracted from body_json (Bronze is raw landing; flattened columns live in Silver).
with bronze as (
    select * from {{ delta_table('bronze', 'patient') }}
),
current_rows as (
    select *,
           row_number() over (partition by id order by version_id desc) as _rn
    from bronze
)
select
    id                                                       as fhir_id,
    version_id,
    last_updated,
    json_extract_string(body_json, '$.gender')               as gender,
    json_extract_string(body_json, '$.birthDate')            as birth_date,
    json_extract_string(body_json, '$.deceasedDateTime')     as deceased_datetime,
    upper(json_extract_string(body_json, '$.name[0].family')) as family_name,
    upper(json_extract_string(body_json, '$.name[0].given[0]')) as given_name,
    json_extract_string(body_json, '$.address[0].postalCode') as postal_code,
    coalesce(try_cast(json_extract_string(body_json, '$.active') as boolean), true) as active
from current_rows
where _rn = 1 and not coalesce(deleted, false)
