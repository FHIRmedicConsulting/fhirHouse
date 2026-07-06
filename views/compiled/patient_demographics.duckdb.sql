-- GENERATED (illustrative) from views/definitions/patient_demographics.ViewDefinition.json
-- Target: DuckDB, reading fhirHouse Silver Patient (Delta) via the body_json fallback path.
-- The compiler PREFERS clean-room-flattened columns (ADR-0024) when a FHIRPath maps to one;
-- the JSON extraction below is shown for illustration. delta-rs materializes the result to
-- gold.view_patient_demographics (FH-0003 / FH-0005). Do not hand-edit; regenerate.

WITH src AS (
    SELECT fhir_id, body_json
    -- PathCatalog binding (contracts/fhirhouse_contracts/catalog.py): <base>/silver/<type.lower()>
    FROM delta_scan('${DELTA_BASE}/silver/patient')
    WHERE NOT coalesce(deleted, FALSE)  -- Silver tombstone column is `deleted` (promote.ts)
      -- where: active = true or active.empty()
      AND (CAST(body_json ->> '$.active' AS BOOLEAN) = TRUE OR body_json ->> '$.active' IS NULL)
)
SELECT
    src.fhir_id                                               AS patient_id,          -- getResourceKey()
    CAST(src.body_json ->> '$.active'         AS BOOLEAN)     AS active,
    src.body_json ->> '$.gender'                              AS gender,
    CAST(src.body_json ->> '$.birthDate'      AS DATE)        AS birth_date,
    CAST(src.body_json ->> '$.deceasedBoolean'  AS BOOLEAN)   AS deceased_boolean,    -- deceased.ofType(boolean)
    CAST(src.body_json ->> '$.deceasedDateTime' AS TIMESTAMP) AS deceased_datetime,   -- deceased.ofType(dateTime)
    official_name.value ->> '$.family'                        AS family_name,
    CAST(official_name.value -> '$.given'     AS VARCHAR[])   AS given_names,         -- collection:true
    home_address.value ->> '$.postalCode'                     AS postal_code,
    home_address.value ->> '$.state'                          AS state,
    mrn_identifier.value ->> '$.value'                        AS mrn
FROM src
-- forEachOrNull: name.where(use = 'official').first()  -> LEFT (outer) join + LIMIT 1
LEFT JOIN LATERAL (
    SELECT n.value
    FROM UNNEST(CAST(src.body_json -> '$.name' AS JSON[])) AS n(value)
    WHERE n.value ->> '$.use' = 'official'
    LIMIT 1
) AS official_name ON TRUE
-- forEachOrNull: address.where(use = 'home').first()
LEFT JOIN LATERAL (
    SELECT a.value
    FROM UNNEST(CAST(src.body_json -> '$.address' AS JSON[])) AS a(value)
    WHERE a.value ->> '$.use' = 'home'
    LIMIT 1
) AS home_address ON TRUE
-- forEachOrNull: identifier.where(system = %mrn_system).first()   (%mrn_system constant inlined)
LEFT JOIN LATERAL (
    SELECT i.value
    FROM UNNEST(CAST(src.body_json -> '$.identifier' AS JSON[])) AS i(value)
    WHERE i.value ->> '$.system' = 'http://hospital.example.org/mrn'
    LIMIT 1
) AS mrn_identifier ON TRUE;
