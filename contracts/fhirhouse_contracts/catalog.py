"""Python mirror of fhirEngine's PathCatalog (packages/server/src/lib/catalog.ts).

Path-based binding: `<base>/<tier>/<resourceType.lower()>`; MPI tables under
`<base>/gold/<table>` (ADR-0012 §2 — all MPI tables live in Gold). Keep in lockstep
with the TS source; the drift test pins the MPI table shapes, not these paths, so a
path change upstream must be mirrored here by hand.
"""
from __future__ import annotations

import os

Tier = str  # "bronze" | "silver" | "gold"

#: fhirHouse-owned Gold tables (writing anywhere else in Gold is fhirEngine's job).
FHIRHOUSE_GOLD_TABLES = ("dq_score", "pprl_tokens", "mpi_decision_log", "patient_match_review")


class PathCatalog:
    def __init__(self, base: str | None = None):
        self.base = (base or os.environ.get("FHIRENGINE_DELTA_BASE", "./delta")).rstrip("/")

    def table_path(self, tier: Tier, resource_type: str) -> str:
        return f"{self.base}/{tier}/{resource_type.lower()}"

    def table_name(self, tier: Tier, resource_type: str) -> str:
        rt = resource_type.lower()
        return rt if tier == "bronze" else f"{rt}_{tier}"

    def mpi_path(self, table: str) -> str:
        return f"{self.base}/gold/{table}"

    # fhirHouse result tables ride the same Gold prefix as the MPI set: operational
    # governance data, one storage substrate, discoverable by the same catalog binding.
    def dq_score_path(self) -> str:
        return f"{self.base}/gold/dq_score"

    def pprl_tokens_path(self) -> str:
        return f"{self.base}/gold/pprl_tokens"

    def mpi_decision_log_path(self) -> str:
        return f"{self.base}/gold/mpi_decision_log"
