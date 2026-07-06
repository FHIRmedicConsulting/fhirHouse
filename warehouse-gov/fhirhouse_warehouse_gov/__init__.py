"""fhirhouse_warehouse_gov — catalog & governance binding (FH-0004: OpenMetadata).

Registers fhirEngine's Delta store in OpenMetadata with Unity-Catalog-aligned
three-level naming, pushes fhirHouse DQ runs as native test results, wires tier
lineage, and applies PHI classifications. Validated against a live 1,000-patient
store (spike 2026-07-06; see docs/decisions/FH-0004).

UC mapping:  OM service = deployment · database = UC catalog · schema = medallion
tier (bronze/silver/gold) · table = resource/governance table.
"""
from .openmetadata import OpenMetadataClient, push_dq_run, register_store, tag_phi_columns, wire_tier_lineage

__all__ = ["OpenMetadataClient", "register_store", "push_dq_run", "tag_phi_columns", "wire_tier_lineage"]
