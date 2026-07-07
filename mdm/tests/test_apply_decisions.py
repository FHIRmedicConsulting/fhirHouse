"""Decision applier: merge semantics, idempotency, ledger/Provenance shape."""
import json

from fhirhouse_contracts import PathCatalog
from fhirhouse_mdm import apply_decisions as mod


def review_row(status="approved", survivor="a", ids="a,b", reviewer="chad"):
    return {"review_id": "rv1", "candidate_ids": ids, "reason": "probabilistic_review_band",
            "shared_identifiers": "", "suggested_action": "steward_review",
            "status": status, "created_at": "2026-07-07T00:00:00",
            "evidence_json": json.dumps({"decision": {
                "action": "approve_merge", "survivor_fhir_id": survivor,
                "reviewer_id": reviewer, "rationale": "same person",
                "decided_at": "2026-07-07T00:00:00"}})}


def bronze_patient(pid, version=1):
    return {"id": pid, "version_id": version, "last_updated": "t",
            "body_json": json.dumps({"resourceType": "Patient", "id": pid, "active": True}),
            "identifier_index": [], "search_param_index": [], "ext_json": "{}",
            "deleted": False, "is_current": True, "_ingested_at": "t", "_ingest_source": "x"}


class StubSidecar:
    def __init__(self):
        self.writes, self.versions = [], []

    def write(self, path, rows, mode="append", schema="infer"):
        self.writes.append((path, rows, mode))

    def write_version(self, path, row, prev_version_id=None):
        self.versions.append((path, row, prev_version_id))

    def write_bronze_resource(self, path, row):
        self.writes.append((path, [row], "append"))


def run(monkeypatch, reviews, merges=set(), patients=None):
    patients = patients or {"a": bronze_patient("a"), "b": bronze_patient("b")}
    monkeypatch.setattr(mod, "_latest_reviews", lambda c: reviews)
    monkeypatch.setattr(mod, "_active_merges", lambda c: set(merges))
    monkeypatch.setattr(mod, "_current_bronze_patient", lambda c, fid: patients.get(fid))
    sc = StubSidecar()
    res = mod.apply_decisions(base="/x", sidecar=sc)
    return res, sc


def test_approved_merge_applies_everything(monkeypatch):
    res, sc = run(monkeypatch, [review_row()])
    assert res["applied"] == [("a", "b")] and not res["errors"]
    ledger = next(r for p, r, m in sc.writes if "patient_merge_history" in p)[0]
    assert ledger["surviving_fhir_id"] == "a" and ledger["merged_fhir_id"] == "b"
    assert ledger["merge_actor"] == "operator:chad" and "review_approved:rv1" in ledger["merge_reason"]
    assert len(sc.versions) == 2  # merged + survivor new Bronze versions
    merged_body = json.loads(sc.versions[0][1]["body_json"])
    assert merged_body["active"] is False
    assert merged_body["link"][0] == {"other": {"reference": "Patient/a"}, "type": "replaced-by"}
    surv_body = json.loads(sc.versions[1][1]["body_json"])
    assert surv_body["link"][0] == {"other": {"reference": "Patient/b"}, "type": "replaces"}
    assert sc.versions[0][1]["version_id"] == 2 and sc.versions[0][2] == 1
    prov = next(r for p, r, m in sc.writes if p == PathCatalog("/x").table_path("bronze", "Provenance"))[0]
    body = json.loads(prov["body_json"])
    assert body["activity"]["coding"][0]["code"] == "MERGE"
    assert "operator:chad" in body["agent"][0]["who"]["display"]


def test_idempotent_when_already_merged(monkeypatch):
    res, sc = run(monkeypatch, [review_row()], merges={("a", "b")})
    assert res["applied"] == [] and res["skipped_already_merged"] == [("a", "b")]
    assert not sc.writes and not sc.versions


def test_non_merge_decisions_and_pending_ignored(monkeypatch):
    reject = review_row()
    reject["status"] = "rejected"
    pending = review_row(ids="c,d")
    pending["status"] = "pending"
    res, sc = run(monkeypatch, [reject, pending])
    assert res["applied"] == [] and not sc.versions


def test_missing_patient_is_an_error_not_a_crash(monkeypatch):
    res, sc = run(monkeypatch, [review_row(ids="a,zz", survivor="a")],
                  patients={"a": bronze_patient("a")})
    assert res["errors"] and res["errors"][0]["pair"] == ("a", "zz")
    assert not sc.versions


def test_dry_run_writes_nothing(monkeypatch):
    patients = {"a": bronze_patient("a"), "b": bronze_patient("b")}
    monkeypatch.setattr(mod, "_latest_reviews", lambda c: [review_row()])
    monkeypatch.setattr(mod, "_active_merges", lambda c: set())
    monkeypatch.setattr(mod, "_current_bronze_patient", lambda c, fid: patients.get(fid))
    sc = StubSidecar()
    res = mod.apply_decisions(base="/x", sidecar=sc, dry_run=True)
    assert res["applied"] == [("a", "b")] and not sc.writes and not sc.versions
