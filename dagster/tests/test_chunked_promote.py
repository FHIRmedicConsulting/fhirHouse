"""Chunked promoter: flatten-port fidelity, schema anchor, survivor rewrite."""
from fhirhouse_dagster.chunked_promote import (
    ANCHOR_ID,
    _anchor_row,
    _rewrite_refs,
    _schemas,
    flatten_resource,
)

PATIENT = {
    "resourceType": "Patient", "id": "p1", "active": True, "gender": "male",
    "birthDate": "1980-01-15", "multipleBirthInteger": 2,
    "name": [{"use": "official", "family": "Smith", "given": ["Jo", "Q"]}],
    "identifier": [{"system": "http://a.org/mrn", "value": "A1"}],
}


def test_flatten_scalars_native_and_complex_as_json():
    import json

    cols = _schemas()["Patient"]
    row = flatten_resource(PATIENT, cols)
    assert row["gender"] == "male" and row["birthDate"] == "1980-01-15"
    assert row["active"] is True
    assert row["multipleBirthInteger"] == 2
    name = json.loads(row["name"])          # list/struct columns are JSON text
    assert name[0]["family"] == "Smith" and name[0]["given"] == ["Jo", "Q"]
    assert row["deceasedBoolean"] is None   # every schema column present, absent -> None
    assert set(c["name"] for c in cols) <= set(row)


def test_anchor_row_pins_every_column_non_null():
    cols = _schemas()["Observation"]
    row = _anchor_row(cols, {"silver_id": ANCHOR_ID})
    assert row["silver_id"] == ANCHOR_ID
    assert all(row[c["name"]] is not None for c in cols)
    # scalar anchors are typed; complex anchors are JSON text
    bools = [c["name"] for c in cols if not c.get("list")
             and c["type"]["kind"] == "scalar" and c["type"]["arrow"] == "bool"]
    assert all(row[b] is True for b in bools)


def test_survivor_reference_rewrite_exact_token():
    body = {
        "subject": {"reference": "Patient/dup1"},
        "note": [{"authorReference": {"reference": "Patient/dup12"}}],  # must NOT match dup1
        "performer": [{"reference": "https://x.org/fhir/Patient/dup1/_history/2"}],
    }
    _rewrite_refs(body, {"dup1": "gold1"})
    assert body["subject"]["reference"] == "Patient/gold1"
    assert body["note"][0]["authorReference"]["reference"] == "Patient/dup12"
    assert body["performer"][0]["reference"] == "https://x.org/fhir/Patient/gold1/_history/2"
