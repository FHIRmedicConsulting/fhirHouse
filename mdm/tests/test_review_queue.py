"""TTL/escalation aging policy (ADR-0012 §5)."""
import json
from datetime import datetime, timezone

from fhirhouse_contracts.schema import load_pin
from fhirhouse_mdm import review_queue as rq

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)


def row(cid, status, created_at, review_id="rv1"):
    return {"review_id": review_id, "candidate_ids": cid, "reason": "probabilistic_review_band",
            "shared_identifiers": "", "evidence_json": "{}",
            "suggested_action": "steward_review", "status": status, "created_at": created_at}


class Stub:
    def __init__(self):
        self.writes = []

    def write(self, path, rows, mode="append", schema="infer"):
        self.writes.append((path, rows, mode))


def run(monkeypatch, rows, **kw):
    monkeypatch.setattr(rq, "_latest_rows", lambda catalog: rows)
    stub = Stub()
    out = rq.age_reviews(base="/x", sidecar=stub, now=NOW, **kw)
    return out, stub


def test_pending_past_ttl_escalates(monkeypatch):
    out, stub = run(monkeypatch, [row("a,b", "pending", "2026-06-25T00:00:00+00:00")])
    assert out["escalated"] == ["a,b"] and not out["aged_out"]
    written = stub.writes[0][1][0]
    assert written["status"] == "escalated"
    assert set(written) == set(load_pin()["mpi_tables"]["patient_match_review"])
    decision = json.loads(written["evidence_json"])["decision"]
    assert decision["reviewer_id"] == "system:ttl-policy"
    assert decision["escalation_role"] == "senior_steward"


def test_fresh_pending_untouched(monkeypatch):
    out, stub = run(monkeypatch, [row("a,b", "pending", "2026-07-05T00:00:00+00:00")])
    assert out == {"escalated": [], "aged_out": [], "dry_run": False} and not stub.writes


def test_escalated_past_ttl_ages_out(monkeypatch):
    out, stub = run(monkeypatch, [row("a,b", "escalated", "2026-06-20T00:00:00+00:00")])
    assert out["aged_out"] == ["a,b"]
    assert stub.writes[0][1][0]["status"] == "auto_aged_out"


def test_decided_reviews_never_aged(monkeypatch):
    out, stub = run(monkeypatch, [row("a,b", "approved", "2026-01-01T00:00:00+00:00"),
                                  row("c,d", "rejected", "2026-01-01T00:00:00+00:00")])
    assert not out["escalated"] and not out["aged_out"] and not stub.writes


def test_dry_run_writes_nothing(monkeypatch):
    out, stub = run(monkeypatch, [row("a,b", "pending", "2026-06-01T00:00:00+00:00")], dry_run=True)
    assert out["escalated"] == ["a,b"] and not stub.writes


def test_configurable_ttls(monkeypatch):
    out, _ = run(monkeypatch, [row("a,b", "pending", "2026-07-06T00:00:00+00:00")],
                 pending_ttl_days=0)
    assert out["escalated"] == ["a,b"]
