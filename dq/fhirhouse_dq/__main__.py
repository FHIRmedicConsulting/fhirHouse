"""CLI: run domain DQ suites + profiling over a fhirEngine store.

    python -m fhirhouse_dq --domains clinical provider patient_member \
        [--base <delta>] [--tier bronze] [--no-write] [--no-profile] [--no-integrity]
"""
from __future__ import annotations

import argparse
import os

from .runner import run_domains


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domains", nargs="+", default=["clinical", "provider", "patient_member"])
    ap.add_argument("--base", default=os.environ.get("FHIRENGINE_DELTA_BASE", "./delta"))
    ap.add_argument("--tier", default="bronze")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--no-profile", action="store_true")
    ap.add_argument("--no-integrity", action="store_true")
    args = ap.parse_args()

    res = run_domains(args.domains, base=args.base, tier=args.tier,
                      write=not args.no_write, profile=not args.no_profile,
                      integrity=not args.no_integrity)
    print(f"run {res['run_id']}: {len(res['score_rows'])} score rows, "
          f"{len(res['profile_rows'])} profile rows, skipped={res['skipped']}")
    for key, s in sorted(res["summary"].items()):
        print(f"  {key}: {s['resources']:,} resources, {s['metrics']} metrics, "
              f"{s['imperfect']} imperfect (worst {s['worst']:.3f})")
    imperfect = [r for r in res["score_rows"] if r["score"] is not None and r["score"] < 1.0]
    defects = sorted((r for r in imperfect if r["dimension"] != "completeness"),
                     key=lambda r: r["score"])[:10]
    gaps = sorted((r for r in imperfect if r["metric"].startswith("ms:")),
                  key=lambda r: r["score"])[:10]
    if defects:
        print("worst defects (conformance/plausibility/integrity):")
        for r in defects:
            print(f"  {r['resource_type']}.{r['metric']} [{r['dimension']}] = "
                  f"{r['score']:.4f} ({r['numerator']:,}/{r['denominator']:,})")
    else:
        print("no conformance/plausibility/integrity defects found")
    if gaps:
        print("largest US Core must-support gaps (completeness):")
        for r in gaps:
            print(f"  {r['resource_type']}.{r['metric']} = {r['score']:.4f} "
                  f"({r['numerator']:,}/{r['denominator']:,})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
