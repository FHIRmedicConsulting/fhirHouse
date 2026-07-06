"""CI gate over the official SQL-on-FHIR shared test suite (FH-0005 §7).

Every test in expected_pass.json must pass — a regression in the compiler fails CI.
New suite tests that don't pass yet only show up when the manifest is regenerated
(python -m fhirhouse_views.conformance), which is a reviewed change.
"""
import json

from fhirhouse_views.conformance import MANIFEST, run_suite


def test_no_regressions_against_manifest():
    assert MANIFEST.exists(), "run `python -m fhirhouse_views.conformance` to create the manifest"
    expected = set(json.loads(MANIFEST.read_text()))
    results = run_suite()
    passing = {f"{r['file']}::{r['title']}" for r in results if r["status"] == "pass"}
    regressions = expected - passing
    assert not regressions, f"conformance regressions: {sorted(regressions)[:10]}"


def test_full_suite_passes():
    # FH-0005 coverage target: 100% of the shared suite, compiled (no fallback).
    results = run_suite()
    not_passing = [(r["file"], r["title"], r["status"], r["detail"][:80])
                   for r in results if r["status"] != "pass"]
    assert not not_passing, not_passing
