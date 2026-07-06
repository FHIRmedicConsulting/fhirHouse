"""Per-deployment MDM configuration (fhirEngine ADR-0012 §4 configuration shape) with
guardrail validation — the "enforce via deployment config validation" half of the
twelve guardrails. Loading a config that violates a floor raises; there is no
override switch below the floors.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

import yaml

AUTO_THRESHOLD_FLOOR = 0.90  # guardrail #2: below 0.90 not permitted, full stop
AUTO_THRESHOLD_DEFAULT = 0.95
REVIEW_THRESHOLD_DEFAULT = 0.70
CROSS_AUTHORITY_DEFAULT = 0.97  # guardrail #12

DEFAULT_BLOCKING_RULES = [  # guardrail #5: candidate pairs must stay tractable
    "l.birth_date = r.birth_date",
    "l.family_name = r.family_name AND substr(l.given_name,1,1) = substr(r.given_name,1,1)",
    "l.postal_code = r.postal_code AND l.family_name = r.family_name",
]


class ConfigError(ValueError):
    pass


@dataclass
class SplinkConfig:
    enabled: bool = False
    model_artifact: str = "mdm/models/splink_model.json"
    model_version: str = "unversioned"  # guardrail #6: pin explicitly in deployment config
    auto_match_threshold: float = AUTO_THRESHOLD_DEFAULT
    review_threshold: float = REVIEW_THRESHOLD_DEFAULT
    cross_assigning_authority_threshold: float = CROSS_AUTHORITY_DEFAULT
    acknowledge_loosened_auto_threshold: bool = False  # required for 0.90 ≤ auto < 0.95
    blocking_rules: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKING_RULES))
    max_estimated_pairs: int = 25_000_000  # guardrail #5 pre-run sanity abort
    deceased_window_days: int = 14

    def validate(self) -> None:
        if self.auto_match_threshold < AUTO_THRESHOLD_FLOOR:
            raise ConfigError(f"auto_match_threshold {self.auto_match_threshold} below the "
                              f"{AUTO_THRESHOLD_FLOOR} floor (ADR-0012 guardrail #2) — not permitted")
        if self.auto_match_threshold < AUTO_THRESHOLD_DEFAULT and not self.acknowledge_loosened_auto_threshold:
            raise ConfigError("auto_match_threshold below 0.95 requires "
                              "acknowledge_loosened_auto_threshold: true (ADR-0012 guardrail #2)")
        if not (0 < self.review_threshold < self.auto_match_threshold):
            raise ConfigError("review_threshold must sit below auto_match_threshold (guardrail #3)")
        if self.cross_assigning_authority_threshold < self.auto_match_threshold:
            raise ConfigError("cross_assigning_authority_threshold must be >= auto_match_threshold "
                              "(guardrail #12: cross-system matches are riskier)")
        if not self.blocking_rules:
            raise ConfigError("at least one blocking rule is required (guardrail #5)")


@dataclass
class PprlTokenSystem:
    name: str                      # e.g. "hmac-sha256:v1" or "clk:openhie"
    kind: str                      # "hmac" | "clk"
    key_env: str                   # env var holding the customer-controlled key (never in config)
    pipeline_version: str = "1"
    fields: list[str] = field(default_factory=lambda: ["family_name", "given_name", "birth_date", "gender"])
    clk_bits: int = 1024
    clk_hashes: int = 20

    def key(self) -> bytes:
        v = os.environ.get(self.key_env, "")
        if not v:
            raise ConfigError(f"PPRL key env var {self.key_env} is unset — keys are "
                              "customer-controlled and never stored in config (ADR-0012 §6)")
        return v.encode()


@dataclass
class MdmConfig:
    splink: SplinkConfig = field(default_factory=SplinkConfig)
    pprl_token_systems: list[PprlTokenSystem] = field(default_factory=list)

    def validate(self) -> None:
        self.splink.validate()
        if len({t.name for t in self.pprl_token_systems}) != len(self.pprl_token_systems):
            raise ConfigError("duplicate PPRL token_system names")


def load_config(path: str | pathlib.Path | None = None) -> MdmConfig:
    path = pathlib.Path(path or os.environ.get("FHIRHOUSE_MDM_CONFIG", "mdm/config.yml"))
    doc = yaml.safe_load(path.read_text()) or {}
    cfg = MdmConfig(
        splink=SplinkConfig(**(doc.get("splink") or {})),
        pprl_token_systems=[PprlTokenSystem(**t) for t in (doc.get("pprl") or {}).get("token_systems", [])],
    )
    cfg.validate()
    return cfg
