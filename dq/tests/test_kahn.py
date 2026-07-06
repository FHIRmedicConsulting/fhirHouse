"""Kahn-dimension scoring tests over synthetic populations."""
from datetime import date

from fhirhouse_dq.kahn import score_resources
from fhirhouse_dq.validator import issue_counts, l5_conformance_metric

TODAY = date(2026, 7, 6)

PATIENTS = [
    {"resourceType": "Patient", "id": "a", "gender": "male", "birthDate": "1980-01-15",
     "name": [{"family": "Smith", "given": ["Jo"]}]},
    {"resourceType": "Patient", "id": "b", "gender": "banana", "birthDate": "2999-01-01"},  # bad code + future
    {"resourceType": "Patient", "id": "c", "birthDate": "1890-01-01"},                       # >120y, no gender
    {"resourceType": "Patient", "id": "d", "gender": "female", "birthDate": "1970-02-30x"},  # bad lexical form
]


def _metric(metrics, dimension, name):
    return next(m for m in metrics if m.dimension == dimension and m.metric == name)


def test_completeness_population_rates():
    metrics = score_resources("Patient", PATIENTS, today=TODAY)
    gender = _metric(metrics, "completeness", "populated:gender")
    assert (gender.numerator, gender.denominator) == (3, 4)
    name = _metric(metrics, "completeness", "populated:name")
    assert (name.numerator, name.denominator) == (1, 4)


def test_conformance_gender_valueset():
    metrics = score_resources("Patient", PATIENTS, today=TODAY)
    m = _metric(metrics, "conformance", "code_in_valueset:gender")
    assert (m.numerator, m.denominator) == (2, 3)  # 'banana' fails; unpopulated excluded


def test_conformance_date_lexical_form():
    metrics = score_resources("Patient", PATIENTS, today=TODAY)
    m = _metric(metrics, "conformance", "date_lexical_form:birthDate")
    assert (m.numerator, m.denominator) == (3, 4)  # "1970-02-30x" fails the regex


def test_plausibility_rules():
    metrics = score_resources("Patient", PATIENTS, today=TODAY)
    future = _metric(metrics, "plausibility", "birthdate_not_future")
    assert (future.numerator, future.denominator) == (2, 3)  # b future; d not applicable (bad form)
    age = _metric(metrics, "plausibility", "age_at_most_120")
    assert age.numerator == 2 and age.denominator == 3  # c is 136


def test_observation_required_elements_and_plausibility():
    obs = [
        {"resourceType": "Observation", "id": "1", "status": "final", "code": {"text": "hr"},
         "effectiveDateTime": "2026-01-01"},
        {"resourceType": "Observation", "id": "2", "code": {"text": "hr"},
         "effectiveDateTime": "2999-01-01"},  # missing status + future
    ]
    metrics = score_resources("Observation", obs, today=TODAY)
    req = _metric(metrics, "conformance", "required_elements_present")
    assert (req.numerator, req.denominator) == (1, 2)
    eff = _metric(metrics, "plausibility", "effective_not_future")
    assert (eff.numerator, eff.denominator) == (1, 2)


def test_l5_metric_from_operation_outcomes():
    outcomes = [
        {"resourceType": "OperationOutcome", "issue": [{"severity": "warning"}]},
        {"resourceType": "OperationOutcome", "issue": [{"severity": "error"}, {"severity": "warning"}]},
    ]
    assert issue_counts(outcomes[1]) == {"fatal": 0, "error": 1, "warning": 1, "information": 0}
    m = l5_conformance_metric("Patient", outcomes, ["hl7.fhir.us.core#6.1.0"])
    assert (m.numerator, m.denominator, m.score) == (1, 2, 0.5)
    assert m.details["issue_totals"]["warning"] == 2
