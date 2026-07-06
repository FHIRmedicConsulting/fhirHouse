"""Contract pin + extraction + catalog tests."""
import pathlib
import subprocess
import sys

from fhirhouse_contracts import PathCatalog, load_pin
from fhirhouse_contracts.schema import (
    FHIRHOUSE_TABLES,
    extract_bronze_schema,
    extract_flattener_schemas,
    extract_mpi_tables,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_drift_test_passes_against_current_upstream():
    proc = subprocess.run([sys.executable, str(REPO / "contracts/drift_test.py")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_pin_covers_all_146_r4_types():
    pin = load_pin()
    assert len(pin["resource_types"]) == 146
    assert set(pin["schema_hashes"]) == set(pin["resource_types"])
    assert pin["fhir_version"] == "4.0.1"


def test_mpi_extraction_matches_adr_0012_shapes():
    tables = extract_mpi_tables()
    assert tables["patient_link"] == [
        "identifier_system", "identifier_value", "resource_type",
        "fhir_id", "is_active", "decision_path", "assigned_at"]
    assert "candidate_ids" in tables["patient_match_review"]
    assert "status" in tables["patient_match_review"]
    assert {"surviving_fhir_id", "merged_fhir_id", "unmerged_at"} <= set(tables["patient_merge_history"])


def test_bronze_schema_extraction():
    names = [f["name"] for f in extract_bronze_schema()]
    assert names[:4] == ["id", "version_id", "last_updated", "body_json"]
    assert "is_current" in names


def test_flattener_extraction_top_level_patient():
    flat = extract_flattener_schemas()
    patient_cols = {c["name"] for c in flat["top_level_columns"]["Patient"]}
    assert {"identifier", "name", "gender", "birthDate"} <= patient_cols


def test_fhirhouse_table_shapes_are_pinned():
    pin = load_pin()
    assert pin["fhirhouse_tables"] == FHIRHOUSE_TABLES
    assert "token_pipeline_version" in FHIRHOUSE_TABLES["pprl_tokens"]
    assert "contributions_json" in FHIRHOUSE_TABLES["mpi_decision_log"]


def test_catalog_paths_mirror_upstream():
    c = PathCatalog("/data/delta")
    assert c.table_path("bronze", "Patient") == "/data/delta/bronze/patient"
    assert c.table_name("bronze", "Patient") == "patient"
    assert c.table_name("silver", "Patient") == "patient_silver"
    assert c.mpi_path("patient_link") == "/data/delta/gold/patient_link"
    assert c.dq_score_path() == "/data/delta/gold/dq_score"
