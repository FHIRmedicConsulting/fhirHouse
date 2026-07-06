"""Contract drift-test: fail when fhirEngine's Gold/flattener schema drifts from
the pinned snapshot. Stub — wire the real extraction per contracts/README.md.

Exit non-zero on drift so CI blocks. Intended to run against the `upstream`
checkout after bootstrap-fork.sh.
"""
from __future__ import annotations
import json
import pathlib
import sys

PIN = pathlib.Path(__file__).parent / "gold_schema.snapshot.json"


def load_pinned() -> dict:
    if not PIN.exists():
        print(f"[drift-test] no pin yet at {PIN.name}; create it (see README). SKIP.")
        sys.exit(0)
    return json.loads(PIN.read_text())


def extract_live_schema() -> dict:
    # TODO: derive from upstream clean-room-flattener.ts + generated R4 schemas.
    raise NotImplementedError("Implement live-schema extraction from upstream.")


def main() -> int:
    pinned = load_pinned()
    live = extract_live_schema()
    if pinned != live:
        print("[drift-test] FAIL: fhirEngine Gold schema drifted from pin.")
        return 1
    print("[drift-test] OK: Gold schema matches pin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
