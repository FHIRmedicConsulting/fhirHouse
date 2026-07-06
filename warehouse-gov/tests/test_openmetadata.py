"""OM binding: UC-aligned naming + pin-derived columns (no server needed)."""
from fhirhouse_contracts.schema import load_pin
from fhirhouse_warehouse_gov.openmetadata import (
    BRONZE_COLUMNS,
    PHI_COLUMNS,
    _governance_columns,
    silver_columns,
)


def test_silver_columns_pin_driven():
    pin = load_pin()
    cols = silver_columns("Patient", pin)
    by_name = {c["name"]: c for c in cols}
    assert by_name["fhir_id"]["dataType"] == "STRING"
    assert by_name["gender"]["dataType"] == "STRING" and "FHIR code" in by_name["gender"]["description"]
    assert by_name["deceasedBoolean"]["dataType"] == "BOOLEAN"
    assert by_name["name"]["dataType"] == "JSON"  # complex element -> JSON-encoded
    assert by_name["multipleBirthInteger"]["dataType"] == "INT"


def test_bronze_columns_match_pinned_row_schema():
    pin = load_pin()
    assert [c["name"] for c in BRONZE_COLUMNS] == [f["name"] for f in pin["bronze_row_schema"]]


def test_governance_columns_from_pin():
    pin = load_pin()
    assert [c["name"] for c in _governance_columns("pprl_tokens", pin)] == \
        pin["fhirhouse_tables"]["pprl_tokens"]
    assert [c["name"] for c in _governance_columns("patient_link", pin)] == \
        pin["mpi_tables"]["patient_link"]


def test_phi_column_set_covers_core_demographics():
    assert {"name", "birthDate", "address", "identifier", "body_json"} <= PHI_COLUMNS
