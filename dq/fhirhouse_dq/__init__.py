"""fhirhouse_dq — data-quality scoring over fhirEngine's medallion tiers (FH-0004 §1).

Kahn-framework dimensions (conformance / completeness / plausibility) scored over
populations, plus L5 IG conformance via the external HL7 Java validator. Does NOT
re-do fhirEngine's pre-Bronze L1–L4 validation.

Reads are read-side delta-rs (FH-0003); the only writes go through fhirEngine's
sidecar into `gold/dq_score` (see fhirhouse_contracts.schema.FHIRHOUSE_TABLES).
"""
from .kahn import DQ_VERSION, MetricResult, score_resources
from .runner import run_dq

__all__ = ["DQ_VERSION", "MetricResult", "score_resources", "run_dq"]
