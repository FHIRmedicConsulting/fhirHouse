"""fhirHouse Dagster definitions (skeleton).

Assets wrap fhirEngine's delta-rs promotion loop and add governance/DQ/MDM stages.
delta-rs remains the sole writer (FH-0003); assets compute with DuckDB and hand
results to fhirEngine's writer.
"""
from dagster import Definitions

# TODO: define assets (dq_scores, splink_matches, pprl_tokens, silver_governed,
# gold_promoted) and a HITL sensor over gold.patient_match_review.
defs = Definitions(assets=[])
