"""(Re)generate contracts/gold_schema.snapshot.json from the current upstream checkout.

Run after a reviewed `git merge upstream/main` when drift_test.py reports drift:
    python contracts/pin_schema.py
Commit the regenerated pin together with any fhirHouse code changes the drift demands.
"""
from __future__ import annotations

import datetime
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from fhirhouse_contracts.schema import PIN_PATH, build_snapshot  # noqa: E402


def main() -> int:
    snap = build_snapshot(pinned_at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    PIN_PATH.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    print(f"[pin] wrote {PIN_PATH} ({len(snap['resource_types'])} resource types, "
          f"{len(snap['mpi_tables'])} upstream MPI tables, {len(snap['fhirhouse_tables'])} fhirHouse tables)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
