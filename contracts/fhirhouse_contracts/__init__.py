"""fhirhouse_contracts — the pinned seam between fhirHouse and fhirEngine.

Everything fhirHouse knows about fhirEngine's shapes and services lives here:
  - `sidecar`  — HTTP client for fhirEngine's delta-rs sidecar (the SOLE Delta writer,
    FH-0003 / fhirEngine ADR-0026 §5). fhirHouse never writes Delta directly.
  - `catalog`  — Python mirror of fhirEngine's PathCatalog (ADR-0025) path binding.
  - `schema`   — loader for the pinned Gold/flattener/MPI schema snapshot
    (`contracts/gold_schema.snapshot.json`) drift-tested by `contracts/drift_test.py`.
"""
from .catalog import PathCatalog
from .reads import read_current_resources
from .schema import load_pin, required_columns, top_level_columns
from .sidecar import SidecarClient

__all__ = ["PathCatalog", "SidecarClient", "load_pin", "read_current_resources",
           "required_columns", "top_level_columns"]
