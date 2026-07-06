"""Contract drift-test: fail when fhirEngine's Gold/flattener/Bronze/MPI shapes drift
from the pinned snapshot (contracts/gold_schema.snapshot.json).

Exit non-zero on drift so CI blocks; a reviewed `python contracts/pin_schema.py` bumps
the pin. `pinned_at` is metadata, not compared. The fhirHouse-owned tables
(pprl_tokens / mpi_decision_log / dq_score) are pinned for consumers but have no live
upstream counterpart, so they are compared against the constants in
fhirhouse_contracts.schema (guarding OUR writers against accidental reshaping).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fhirhouse_contracts.schema import (  # noqa: E402
    FHIRHOUSE_TABLES,
    PIN_PATH,
    extract_bronze_schema,
    extract_flattener_schemas,
    extract_mpi_tables,
    load_pin,
)


def diff_keys(pinned: dict, live: dict, label: str, failures: list[str]) -> None:
    for k in sorted(set(pinned) | set(live)):
        if k not in live:
            failures.append(f"{label}: '{k}' pinned but missing upstream")
        elif k not in pinned:
            failures.append(f"{label}: '{k}' new upstream, not pinned")
        elif pinned[k] != live[k]:
            failures.append(f"{label}: '{k}' drifted")


def main() -> int:
    if not PIN_PATH.exists():
        print(f"[drift-test] no pin at {PIN_PATH.name}; run `python contracts/pin_schema.py`. FAIL.")
        return 1
    pin = load_pin()
    failures: list[str] = []

    flat = extract_flattener_schemas()
    for field in ("fhir_version", "source", "resource_types"):
        if pin[field] != flat[field]:
            failures.append(f"{field} drifted: pinned {pin[field]!r:.80} != live {flat[field]!r:.80}")
    diff_keys(pin["schema_hashes"], flat["schema_hashes"], "flattener schema", failures)

    if pin["bronze_row_schema"] != extract_bronze_schema():
        failures.append("bronze_row_schema drifted (sidecar BRONZE_SCHEMA)")

    diff_keys(pin["mpi_tables"], extract_mpi_tables(), "MPI table", failures)
    diff_keys(pin["fhirhouse_tables"], FHIRHOUSE_TABLES, "fhirHouse table", failures)

    if failures:
        print(f"[drift-test] FAIL — {len(failures)} drift(s) from {PIN_PATH.name}:")
        for f in failures:
            print(f"  - {f}")
        print("Review the change, adapt fhirHouse if needed, then re-pin: python contracts/pin_schema.py")
        return 1
    print(f"[drift-test] OK: upstream matches pin ({len(pin['schema_hashes'])} resource schemas, "
          f"{len(pin['mpi_tables'])} MPI tables, Bronze row schema).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
