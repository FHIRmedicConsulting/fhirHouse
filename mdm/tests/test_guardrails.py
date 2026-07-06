"""Hard-deny guardrail parity with upstream mpi.ts (ADR-0012 §3.4)."""
from fhirhouse_mdm.guardrails import guardrail, identifier_keys, normalize_identifier

SSN = "http://hl7.org/fhir/sid/us-ssn"


def test_normalize_canonicalizes_system_and_ssn():
    assert normalize_identifier("HTTP://Hospital.ORG/mrn/", "  123  45 ") == "http://hospital.org/mrn|123 45"
    assert normalize_identifier(SSN, "123-45-6789") == f"{SSN}|123456789"
    assert normalize_identifier("urn:oid:1.2.3/", "x") == "urn:oid:1.2.3|x"
    assert normalize_identifier("sys", "") is None


def test_ssn_conflict_is_hard_distinct():
    a = {"identifier": [{"system": SSN, "value": "111-11-1111"}]}
    b = {"identifier": [{"system": SSN, "value": "222-22-2222"}]}
    assert guardrail(a, b) == "distinct"


def test_sex_mismatch_blocks_but_unknown_passes():
    assert guardrail({"gender": "male"}, {"gender": "female"}) == "sex_mismatch"
    assert guardrail({"gender": "unknown"}, {"gender": "female"}) is None


def test_death_date_window():
    a = {"deceasedDateTime": "2020-01-01T00:00:00Z"}
    b = {"deceasedDateTime": "2020-03-01T00:00:00Z"}
    assert guardrail(a, b) == "date_of_death_mismatch"
    assert guardrail(a, {"deceasedDateTime": "2020-01-10T00:00:00Z"}) is None
    assert guardrail(a, b, deceased_window_days=90) is None  # window is configurable; the floor is not


def test_inactive_candidate_skipped():
    assert guardrail({"active": False}, {}) == "inactive_candidate"


def test_identifier_keys_dedupe():
    body = {"identifier": [{"system": "s", "value": "1"}, {"system": "s", "value": "1"}]}
    assert identifier_keys(body) == ["s|1"]
