"""Robustness-taxonomy unit tests (research note §6) beyond the shared suite,
plus typed-mode rendering and fail-loud boundaries."""
import pytest

from fhirhouse_views.compiler import CompileError, ViewCompiler
from fhirhouse_views.runner import connect, run_view

PATIENTS = [
    {"resourceType": "Patient", "id": "p1", "gender": "male", "birthDate": "1980-01-15",
     "deceasedBoolean": False,
     "name": [{"use": "official", "family": "Smith", "given": ["Jo", "Q"]},
              {"use": "maiden", "family": "Jones"}],
     "identifier": [{"system": "http://a.org/mrn", "value": "A1"}],
     "extension": [{"url": "http://x.org/level", "valueCode": "gold"}]},
    {"resourceType": "Patient", "id": "p2", "gender": "female"},
]
OBS = [{"resourceType": "Observation", "id": "o1", "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
        "subject": {"reference": "Patient/p1"},
        "valueQuantity": {"value": 72.5, "unit": "bpm"}}]


def view(select, **kw):
    return {"resource": kw.pop("resource", "Patient"), "select": select, **kw}


def test_choice_type_and_reference_key():
    v = view([{"column": [
        {"name": "id", "path": "getResourceKey()"},
        {"name": "pid", "path": "subject.getReferenceKey(Patient)"},
        {"name": "wrong", "path": "subject.getReferenceKey(Device)"},
        {"name": "val", "path": "value.ofType(Quantity).value", "type": "decimal"},
    ]}], resource="Observation")
    _, rows = run_view(v, OBS)
    assert rows == [{"id": "o1", "pid": "p1", "wrong": None, "val": 72.5}]


def test_where_filter_and_collection_column():
    v = view([{"column": [
        {"name": "official_family", "path": "name.where(use = 'official').family"},
        {"name": "givens", "path": "name.first().given", "collection": True},
    ]}], where=[{"path": "gender = 'male'"}])
    _, rows = run_view(v, PATIENTS)
    assert rows == [{"official_family": "Smith", "givens": ["Jo", "Q"]}]


def test_extension_sugar():
    v = view([{"column": [
        {"name": "level", "path": "extension('http://x.org/level').value.ofType(code).first()"}]}])
    _, rows = run_view(v, PATIENTS)
    assert {r["level"] for r in rows} == {"gold", None}


def test_foreach_vs_foreachornull_row_counts():
    inner = view([{"forEach": "name", "column": [{"name": "family", "path": "family"}]}])
    outer = view([{"forEachOrNull": "name", "column": [{"name": "family", "path": "family"}]}])
    assert len(run_view(inner, PATIENTS)[1]) == 2      # p2 (no names) dropped
    assert len(run_view(outer, PATIENTS)[1]) == 3      # p2 kept with NULL


def test_multiple_values_without_collection_flag_errors():
    v = view([{"column": [{"name": "given", "path": "name.first().given"}]}])
    with pytest.raises(Exception, match="collection"):
        run_view(v, PATIENTS)


def test_unsupported_function_fails_loud():
    with pytest.raises(CompileError, match="unsupported"):
        ViewCompiler(view([{"column": [{"name": "x", "path": "name.resolve()"}]}])).compile("SELECT 1")


def test_typed_mode_casts():
    v = view([{"column": [
        {"name": "birth_date", "path": "birthDate", "type": "date"},
        {"name": "deceased", "path": "deceased.ofType(boolean)", "type": "boolean"},
    ]}])
    compiled = ViewCompiler(v, typed=True).compile("SELECT 1 AS resource, '' AS resource_key")
    assert "AS DATE" in compiled.sql and "AS BOOLEAN" in compiled.sql


def test_validation_errors():
    with pytest.raises(CompileError):
        ViewCompiler({})
    with pytest.raises(CompileError):
        ViewCompiler({"resource": "Patient", "select": []})
    with pytest.raises(CompileError):
        ViewCompiler(view([{"column": [{"name": "x", "path": "@@bad@@"}]}])).compile("SELECT 1")


def test_constants_and_boolean_logic():
    v = view(
        [{"column": [{"name": "id", "path": "id"}]}],
        constant=[{"name": "g", "valueCode": "male"}],
        where=[{"path": "gender = %g and deceased.ofType(boolean) = false"}],
    )
    _, rows = run_view(v, PATIENTS)
    assert rows == [{"id": "p1"}]


def test_sof_macros_are_idempotent():
    con = connect()
    connect(con)  # CREATE OR REPLACE — safe to run twice on one connection
