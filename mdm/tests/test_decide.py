"""Three-band classification + persistence into the pinned MPI contract."""
import json

from fhirhouse_contracts import PathCatalog
from fhirhouse_contracts.schema import FHIRHOUSE_TABLES, load_pin
from fhirhouse_mdm.config import MdmConfig
from fhirhouse_mdm.decide import (
    BAND_AUTO,
    BAND_DENIED,
    BAND_NEW,
    BAND_REVIEW,
    classify_pair,
    persist_decisions,
)

SSN = "http://hl7.org/fhir/sid/us-ssn"
CFG = MdmConfig()


def rec(uid, systems=("http://a.org/mrn",), keys=None, **kw):
    return {
        "unique_id": uid, "given_name": "JO", "family_name": "SMITH", "birth_date": "1980-01-15",
        "gender": "male", "postal_code": "12345",
        "identifier_systems": list(systems),
        "identifier_keys": keys or [f"{systems[0]}|{uid}"],
        "active": True, "deceased_datetime": None, **kw,
    }


def pair(lid, rid, p, **cols):
    return {"unique_id_l": lid, "unique_id_r": rid, "match_probability": p, "match_weight": 9.9,
            "gamma_given_name": 2, "bf_given_name": 40.0, **cols}


def test_bands():
    a, b = rec("a"), rec("b")
    assert classify_pair(pair("a", "b", 0.99), a, b, CFG)[0] == BAND_AUTO
    assert classify_pair(pair("a", "b", 0.80), a, b, CFG)[0] == BAND_REVIEW
    assert classify_pair(pair("a", "b", 0.10), a, b, CFG)[0] == BAND_NEW


def test_cross_authority_needs_tighter_threshold():
    a, b = rec("a", systems=("http://a.org/mrn",)), rec("b", systems=("http://b.org/mrn",))
    band, _ = classify_pair(pair("a", "b", 0.96), a, b, CFG)  # ≥0.95 but <0.97 across authorities
    assert band == BAND_REVIEW
    band, _ = classify_pair(pair("a", "b", 0.98), a, b, CFG)
    assert band == BAND_AUTO


def test_hard_deny_beats_high_score():
    a = rec("a", keys=[f"{SSN}|111111111"])
    b = rec("b", keys=[f"{SSN}|222222222"])
    band, flag = classify_pair(pair("a", "b", 0.999), a, b, CFG)
    assert band == BAND_DENIED and flag == "conflicting_authoritative_identifier"


def test_safety_override_routes_high_score_to_review():
    a, b = rec("a"), rec("b", gender="female")
    band, flag = classify_pair(pair("a", "b", 0.99), a, b, CFG)
    assert band == BAND_REVIEW and flag == "safety_override:sex_mismatch"


class StubSidecar:
    def __init__(self):
        self.writes = []

    def write(self, table_path, rows, mode="append", schema="infer"):
        self.writes.append((table_path, rows, mode))
        return {"written": len(rows)}

    def query(self, sql, tables):
        return []  # no pre-existing reviews

    def write_bronze_resource(self, table_path, row):
        self.writes.append((table_path, [row], "append"))
        return {"written": 1}


def test_persist_matches_pinned_contracts():
    sidecar = StubSidecar()
    records = {"a": rec("a"), "b": rec("b"), "c": rec("c"), "d": rec("d")}
    pairs = [pair("a", "b", 0.99), pair("c", "d", 0.80), pair("a", "d", 0.20)]
    out = persist_decisions(pairs, records, CFG, sidecar=sidecar, catalog=PathCatalog("/x"), run_id="run1")

    assert out["counts"][BAND_AUTO] == 1 and out["counts"][BAND_REVIEW] == 1 and out["counts"][BAND_NEW] == 1
    assert out["queued_reviews"] == 2  # auto band queues too: operator-ack default posture

    by_path = {}
    for path, rows, _ in sidecar.writes:
        by_path.setdefault(path, []).extend(rows)

    pin = load_pin()
    review_rows = by_path["/x/gold/patient_match_review"]
    assert all(set(r) == set(pin["mpi_tables"]["patient_match_review"]) for r in review_rows)
    assert {r["suggested_action"] for r in review_rows} == {"approve_merge", "steward_review"}
    assert all(json.loads(r["evidence_json"])["bulk_dedup_run_id"] == "run1" for r in review_rows)

    log_rows = by_path["/x/gold/mpi_decision_log"]
    assert len(log_rows) == 3  # every scored pair logged, including the 'new' band
    assert all(set(r) == set(FHIRHOUSE_TABLES["mpi_decision_log"]) for r in log_rows)
    assert json.loads(log_rows[0]["contributions_json"])["bf_given_name"] == 40.0

    prov_rows = by_path["/x/bronze/provenance"]
    assert len(prov_rows) == 2  # one Provenance per queued review decision
    body = json.loads(prov_rows[0]["body_json"])
    assert body["resourceType"] == "Provenance"
    assert body["activity"]["coding"][0]["code"] == "MATCH"


def test_rerun_does_not_duplicate_pending_reviews():
    sidecar = StubSidecar()
    sidecar.query = lambda sql, tables: [{"candidate_ids": "a,b"}]
    records = {"a": rec("a"), "b": rec("b")}
    out = persist_decisions([pair("a", "b", 0.99)], records, CFG, sidecar=sidecar, catalog=PathCatalog("/x"))
    assert out["queued_reviews"] == 0
    assert not any("patient_match_review" in p for p, _, _ in sidecar.writes)
