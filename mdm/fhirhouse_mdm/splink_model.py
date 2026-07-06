"""Splink probabilistic linkage on the DuckDB backend (fhirEngine ADR-0012 §4).

DuckDB is fhirHouse's read-side engine (FH-0003), and Splink 4 runs natively on it —
no Spark needed in the fhirEngine topology (the ADR's PySpark shape is the
Databricks/Ronin lane). Splink imports are function-local so the rest of the MDM
package (guardrails, bands, PPRL) works without the heavy dependency.

Model lifecycle honors guardrails #6/#7: `train_model` runs OFFLINE and writes a
versioned JSON artifact to a STAGING path; production runs load the artifact pinned
in deployment config, and cutover is an explicit operator config change.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from .config import SplinkConfig
from .guardrails import identifier_keys, identifier_systems

# Splink pair-count sanity (guardrail #5): estimated from blocking before predict.


def patient_to_record(patient: dict) -> dict[str, Any]:
    """Flatten a FHIR Patient body into the linkage feature record."""
    name0 = (patient.get("name") or [{}])[0] or {}
    addr0 = (patient.get("address") or [{}])[0] or {}
    phones = [t.get("value") for t in patient.get("telecom") or []
              if (t or {}).get("system") == "phone" and t.get("value")]
    given = (name0.get("given") or [None])[0]
    return {
        "unique_id": patient.get("id"),
        "given_name": (given or "").strip().upper() or None,
        "family_name": (name0.get("family") or "").strip().upper() or None,
        "birth_date": patient.get("birthDate"),
        "gender": patient.get("gender"),
        "postal_code": (addr0.get("postalCode") or "").strip().upper() or None,
        "phone": "".join(ch for ch in (phones[0] if phones else "") if ch.isdigit()) or None,
        # not linkage features — carried for guardrails / cross-authority banding:
        "identifier_keys": identifier_keys(patient),
        "identifier_systems": sorted(identifier_systems(patient)),
        "deceased_datetime": patient.get("deceasedDateTime") if isinstance(patient.get("deceasedDateTime"), str) else None,
        "active": patient.get("active", True),
    }


_FEATURE_COLS = ["unique_id", "given_name", "family_name", "birth_date", "gender", "postal_code", "phone"]


def _settings(cfg: SplinkConfig):
    import splink.comparison_library as cl
    from splink import SettingsCreator, block_on  # noqa: F401  (block_on available for rule authors)

    return SettingsCreator(
        link_type="dedupe_only",
        blocking_rules_to_generate_predictions=list(cfg.blocking_rules),
        comparisons=[
            cl.NameComparison("given_name"),
            cl.NameComparison("family_name"),
            cl.DateOfBirthComparison("birth_date", input_is_string=True),
            cl.ExactMatch("gender"),
            cl.PostcodeComparison("postal_code"),
            cl.LevenshteinAtThresholds("phone", 2),
        ],
        retain_intermediate_calculation_columns=True,  # per-attribute Bayes factors → mpi_decision_log
    )


def _frame(records: list[dict]):
    import pandas as pd

    df = pd.DataFrame([{k: r.get(k) for k in _FEATURE_COLS} for r in records])
    # every feature is textual; an all-null column must not be inferred numeric
    # (DuckDB comparisons like levenshtein() bind VARCHAR)
    return df.astype({c: "string" for c in _FEATURE_COLS if c != "unique_id"})


def train_model(records: list[dict], cfg: SplinkConfig, staging_path: str | None = None,
                deterministic_rules: list[str] | None = None) -> str:
    """Offline EM fit (guardrail #7). Writes the model JSON to `<artifact>.staging.json`
    (or staging_path) — production cutover is the operator flipping `model_artifact`
    in deployment config after review."""
    from splink import DuckDBAPI, Linker

    linker = Linker(_frame(records), _settings(cfg), db_api=DuckDBAPI())
    det = deterministic_rules or ["l.birth_date = r.birth_date AND l.family_name = r.family_name"]
    linker.training.estimate_probability_two_random_records_match(det, recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=min(cfg.max_estimated_pairs, 1_000_000))
    for rule in cfg.blocking_rules[:2]:
        linker.training.estimate_parameters_using_expectation_maximisation(rule)
    out = pathlib.Path(staging_path or (cfg.model_artifact + ".staging.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    linker.misc.save_model_to_json(str(out), overwrite=True)
    return str(out)


def predict_pairs(records: list[dict], cfg: SplinkConfig) -> list[dict]:
    """Score candidate pairs with the PINNED model artifact. Returns rows with
    unique_id_l/r, match_probability, match_weight, and the per-comparison gamma_*/
    bf_* columns (fed to gold.mpi_decision_log per guardrail #9)."""
    from splink import DuckDBAPI, Linker

    artifact = pathlib.Path(cfg.model_artifact)
    if not artifact.exists():
        raise FileNotFoundError(
            f"Splink model artifact {artifact} not found — train offline first "
            "(train_model) and pin the reviewed artifact in config (ADR-0012 guardrails #6/#7)")
    settings = json.loads(artifact.read_text())
    settings["blocking_rules_to_generate_predictions"] = list(cfg.blocking_rules)
    linker = Linker(_frame(records), settings, db_api=DuckDBAPI())

    # guardrail #5: pre-run sanity check — abort if blocking yields an intractable pair count
    n_pairs = _estimated_pairs(_frame(records), cfg)
    if n_pairs > cfg.max_estimated_pairs:
        raise RuntimeError(f"blocking rules produce ~{n_pairs} candidate pairs "
                           f"(> max_estimated_pairs {cfg.max_estimated_pairs}) — tighten blocking (guardrail #5)")

    df = linker.inference.predict(threshold_match_probability=cfg.review_threshold).as_pandas_dataframe()
    return df.to_dict("records")


def _estimated_pairs(frame, cfg: SplinkConfig) -> int:
    try:
        from splink import DuckDBAPI
        from splink.blocking_analysis import count_comparisons_from_blocking_rule

        total = 0
        for br in cfg.blocking_rules:
            res = count_comparisons_from_blocking_rule(
                table_or_tables=frame, blocking_rule=br, link_type="dedupe_only", db_api=DuckDBAPI(),
            )
            total += int(res.get("number_of_comparisons_to_be_scored_post_filter_conditions_sql", 0) or
                         res.get("number_of_comparisons_to_be_scored_post_filter_conditions", 0))
        return total
    except Exception:
        return 0  # estimator API unavailable → don't block the run on the estimate
