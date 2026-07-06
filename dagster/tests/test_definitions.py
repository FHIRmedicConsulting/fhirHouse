"""Dagster definitions load + wiring sanity."""
from dagster import AssetKey

from fhirhouse_dagster.definitions import defs


def test_definitions_load_and_assets_present():
    keys = {spec.key for assets_def in defs.assets for spec in assets_def.specs}
    assert {AssetKey("gold_promoted"), AssetKey("dq_scores"),
            AssetKey("splink_matches"), AssetKey("pprl_tokens")} <= keys


def test_governance_assets_depend_on_promotion():
    by_key = {spec.key: spec for assets_def in defs.assets for spec in assets_def.specs}
    for name in ("dq_scores", "splink_matches", "pprl_tokens"):
        deps = {d.asset_key for d in by_key[AssetKey(name)].deps}
        assert AssetKey("gold_promoted") in deps


def test_hitl_sensor_registered():
    assert defs.sensors and any(s.name == "hitl_review_sensor" for s in defs.sensors)
    assert any(j.name == "notify_stewards_job" for j in defs.jobs)
