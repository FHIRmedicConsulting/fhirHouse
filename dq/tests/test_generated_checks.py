"""Package loader, generated suites, check engine, profiler."""
import json
import pathlib
from datetime import date

import pytest

from fhirhouse_dq.checks import _values, run_checks
from fhirhouse_dq.fhir_packages import PackageIndex
from fhirhouse_dq.profiler import profile_resources

CHECKS_DIR = pathlib.Path(__file__).resolve().parents[1] / "checks"
TODAY = date(2026, 7, 6)


@pytest.fixture(scope="module")
def pkgs():
    try:
        return PackageIndex()
    except FileNotFoundError:
        pytest.skip("no local FHIR package cache")


def test_valueset_expansion(pkgs):
    codes = pkgs.expand_valueset("http://hl7.org/fhir/ValueSet/administrative-gender")
    assert codes == frozenset({"male", "female", "other", "unknown"})
    # intensional/filter valuesets refuse honestly
    assert pkgs.expand_valueset("http://hl7.org/fhir/ValueSet/condition-code") is None


def test_generated_suites_exist_and_are_runnable():
    suites = list(CHECKS_DIR.glob("*/*.checks.json"))
    assert len(suites) == 15  # 3 domains, 15 types
    for f in suites:
        suite = json.loads(f.read_text())
        assert suite["checks"], f.name
        run_checks([{}], suite["checks"])  # every committed check must execute


def test_path_navigation_flattens():
    r = {"name": [{"given": ["A", "B"]}, {"given": ["C"]}]}
    assert _values(r, ["name", "given"]) == ["A", "B", "C"]


PATIENTS = [
    {"resourceType": "Patient", "id": "ok", "gender": "male", "birthDate": "1980-01-15",
     "name": [{"family": "S"}], "managingOrganization": {"reference": "Organization/org1"}},
    {"resourceType": "Patient", "id": "bad", "gender": "banana", "birthDate": "1830-01-01",
     "deceasedDateTime": ["not-a-scalar"],  # array where scalar expected
     "managingOrganization": {"reference": "Device/nope"}},
]


def _suite(rtype="Patient", domain="patient_member"):
    return json.loads((CHECKS_DIR / domain / f"{rtype}.checks.json").read_text())


def _metric(results, name):
    return next(m for m in results if m.metric == name)


def test_binding_format_range_and_shape_checks_catch_bad_patient():
    res = run_checks(PATIENTS, _suite()["checks"], today=TODAY)
    b = _metric(res, "binding:gender")
    assert (b.numerator, b.denominator) == (1, 2) and "banana" in b.details["examples_bad"]
    rng = _metric(res, "date_range:birthDate")
    assert (rng.numerator, rng.denominator) == (1, 2)  # 1830 is implausible
    card = _metric(res, "max_card:deceasedDateTime")
    assert (card.numerator, card.denominator) == (0, 1)  # array where max=1


def test_reference_target_and_existence():
    res = run_checks(PATIENTS, _suite()["checks"], today=TODAY,
                     id_sets={"Organization": {"org1"}, "Device": {"nope"}})
    tgt = _metric(res, "ref_target:managingOrganization")
    assert (tgt.numerator, tgt.denominator) == (1, 2)  # Device/nope is a wrong type
    ex = _metric(res, "ref_exists:managingOrganization")
    assert ex.denominator == 2 and ex.numerator == 2  # both ids exist in their tables


def test_must_support_completeness():
    res = run_checks(PATIENTS, _suite()["checks"], today=TODAY)
    ms = [m for m in res if m.metric.startswith("ms:")]
    assert ms and all(m.dimension == "completeness" for m in ms)
    name_ms = _metric(res, "ms:name")
    assert (name_ms.numerator, name_ms.denominator) == (1, 2)


def test_profiler_rows_pin_shape():
    from fhirhouse_contracts.schema import FHIRHOUSE_TABLES

    rows = profile_resources("Patient", PATIENTS, "r1", "2026-07-06T00:00:00Z")
    assert rows and all(set(r) == set(FHIRHOUSE_TABLES["dq_profile"]) for r in rows)
    count = next(r for r in rows if r["subject"] == "_resource" and r["stat"] == "count")
    assert count["value_num"] == 2.0
    gender_top = [r for r in rows if r["subject"] == "gender" and r["stat"].startswith("top_")]
    assert {r["value_text"] for r in gender_top} == {"male", "banana"}
    bd = [r for r in rows if r["subject"] == "birthDate"]
    assert {r["stat"] for r in bd} >= {"populated_pct", "min", "max"}
