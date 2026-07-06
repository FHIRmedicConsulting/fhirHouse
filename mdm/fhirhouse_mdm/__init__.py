"""fhirhouse_mdm — the probabilistic (Splink) + PPRL lanes fhirEngine ADR-0012 deferred.

Deterministic MPI already runs at promotion inside fhirEngine (packages/server/src/
repository/mpi.ts); this package adds Stage B. It writes ONLY into the existing Gold
MPI table contract (patient_link / patient_match_review / patient_merge_history pinned
from upstream, pprl_tokens / mpi_decision_log pinned by fhirHouse) via the sidecar.

Default posture (ADR-0012 §5 bulk-dedup + open question #4): probabilistic outcomes —
including the auto band — land in `gold.patient_match_review` for operator
acknowledgment; fhirEngine's promoter applies approved merges. fhirHouse never merges.
"""
from .config import MdmConfig, load_config
from .guardrails import guardrail, normalize_identifier

__all__ = ["MdmConfig", "load_config", "guardrail", "normalize_identifier"]
