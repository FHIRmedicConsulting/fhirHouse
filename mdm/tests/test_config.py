"""Threshold-floor enforcement (ADR-0012 guardrails #2/#3/#12) at config load."""
import pytest

from fhirhouse_mdm.config import ConfigError, MdmConfig, SplinkConfig


def test_defaults_validate():
    MdmConfig().validate()


def test_auto_threshold_floor_is_absolute():
    with pytest.raises(ConfigError, match="floor"):
        SplinkConfig(auto_match_threshold=0.85, acknowledge_loosened_auto_threshold=True).validate()


def test_loosening_below_default_requires_acknowledgment():
    with pytest.raises(ConfigError, match="acknowledge"):
        SplinkConfig(auto_match_threshold=0.92).validate()
    SplinkConfig(auto_match_threshold=0.92, acknowledge_loosened_auto_threshold=True,
                 cross_assigning_authority_threshold=0.97).validate()


def test_review_must_sit_below_auto():
    with pytest.raises(ConfigError, match="review_threshold"):
        SplinkConfig(review_threshold=0.96).validate()


def test_cross_authority_tighter_than_auto():
    with pytest.raises(ConfigError, match="cross_assigning_authority"):
        SplinkConfig(cross_assigning_authority_threshold=0.94).validate()


def test_blocking_rules_required():
    with pytest.raises(ConfigError, match="blocking"):
        SplinkConfig(blocking_rules=[]).validate()


def test_example_config_loads(tmp_path, monkeypatch):
    import pathlib
    import shutil

    example = pathlib.Path(__file__).resolve().parents[1] / "config.example.yml"
    cfg_file = tmp_path / "config.yml"
    shutil.copy(example, cfg_file)
    from fhirhouse_mdm.config import load_config

    cfg = load_config(cfg_file)
    assert cfg.splink.enabled and cfg.splink.auto_match_threshold == 0.95
    assert {t.kind for t in cfg.pprl_token_systems} == {"hmac", "clk"}
