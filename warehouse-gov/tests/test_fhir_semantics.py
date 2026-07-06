"""SD-derived semantics: element docs, choice variants, resource descriptions."""
import pytest

from fhirhouse_warehouse_gov.fhir_semantics import (
    GOVERNANCE_TABLES,
    _clip,
    element_docs,
    resource_description,
)


@pytest.fixture(scope="module")
def pkgs():
    from fhirhouse_dq.fhir_packages import PackageIndex

    try:
        return PackageIndex()
    except FileNotFoundError:
        pytest.skip("no local FHIR package cache")


def test_element_docs_real_hl7_text(pkgs):
    docs = element_docs(pkgs, "Patient")
    assert docs["birthDate"] == "The date of birth for the individual"
    assert "gender" in docs and "name" in docs


def test_choice_variants_get_concrete_docs(pkgs):
    docs = element_docs(pkgs, "Patient")
    assert "deceasedBoolean" in docs and "deceasedDateTime" in docs
    assert docs["deceasedDateTime"].endswith("(dateTime)")
    assert "deceased[x]" not in docs


def test_resource_description_includes_spec_link(pkgs):
    d = resource_description(pkgs, "Observation")
    assert d.startswith("**FHIR R4 Observation**")
    assert "https://hl7.org/fhir/R4/observation.html" in d


def test_clip_caps_length():
    assert len(_clip("x" * 5000)) <= 950
    assert _clip("  ok  ") == "ok"


def test_governance_tables_cover_pinned_set():
    from fhirhouse_contracts.schema import load_pin

    pin = load_pin()
    assert set(pin["fhirhouse_tables"]) | set(pin["mpi_tables"]) <= GOVERNANCE_TABLES
