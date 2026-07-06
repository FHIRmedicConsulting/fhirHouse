"""Statistical profiling over a resource population → gold/dq_profile rows.

Long-format stats (pinned shape, contracts FHIRHOUSE_TABLES['dq_profile']):
  resource level : count, distinct_ids, duplicate_id_pct
  per element    : populated_pct; top-5 value frequencies for small coded scalars;
                   min/max for temporals; numeric stats (min/max/mean/p50/p95) for
                   Quantity values

Element inventory comes from the contracts pin (the flattener's top-level columns),
so profiles line up with the columns analysts see in Silver and in the catalog.
"""
from __future__ import annotations

import statistics
from collections import Counter

from fhirhouse_contracts.schema import load_pin

TOP_K = 5


def _rows_for(run_id: str, computed_at: str, tier: str, rtype: str,
              subject: str, stats: dict[str, tuple[float | None, str | None]]) -> list[dict]:
    from .kahn import DQ_VERSION

    return [{"run_id": run_id, "computed_at": computed_at, "tier": tier,
             "resource_type": rtype, "subject": subject, "stat": stat,
             "value_num": num, "value_text": text, "dq_version": DQ_VERSION}
            for stat, (num, text) in stats.items()]


def profile_resources(resource_type: str, resources: list[dict], run_id: str,
                      computed_at: str, tier: str = "bronze", pin: dict | None = None) -> list[dict]:
    pin = pin or load_pin()
    n = len(resources)
    out: list[dict] = []
    ids = [r.get("id") for r in resources if r.get("id")]
    distinct = len(set(ids))
    out += _rows_for(run_id, computed_at, tier, resource_type, "_resource", {
        "count": (float(n), None),
        "distinct_ids": (float(distinct), None),
        "duplicate_id_pct": ((1 - distinct / len(ids)) * 100 if ids else 0.0, None),
    })

    for col in pin["top_level_columns"].get(resource_type, []):
        name = col["name"]
        if name.startswith("_"):
            continue
        vals = [r.get(name) for r in resources]
        present = [v for v in vals if v not in (None, "", [], {})]
        stats: dict[str, tuple[float | None, str | None]] = {
            "populated_pct": (100.0 * len(present) / n if n else 0.0, None)}
        if not present:
            out += _rows_for(run_id, computed_at, tier, resource_type, name, stats)
            continue

        if col["kind"] == "scalar" and col["fhirType"] in ("code", "boolean"):
            top = Counter(str(v) for v in present).most_common(TOP_K)
            for i, (val, cnt) in enumerate(top, 1):
                stats[f"top_{i}"] = (float(cnt), val)
        elif col["kind"] == "scalar" and col["fhirType"] in ("date", "dateTime", "instant"):
            svals = sorted(str(v) for v in present)
            stats["min"] = (None, svals[0])
            stats["max"] = (None, svals[-1])
        elif col["fhirType"] == "Quantity" and not col.get("list"):
            nums = [v.get("value") for v in present
                    if isinstance(v, dict) and isinstance(v.get("value"), (int, float))]
            if nums:
                nums.sort()
                stats.update({
                    "num_min": (float(nums[0]), None), "num_max": (float(nums[-1]), None),
                    "num_mean": (float(statistics.fmean(nums)), None),
                    "num_p50": (float(nums[len(nums) // 2]), None),
                    "num_p95": (float(nums[int(len(nums) * 0.95) - 1]), None),
                })
                units = Counter(v.get("unit") or v.get("code") for v in present
                                if isinstance(v, dict)).most_common(1)
                if units and units[0][0]:
                    stats["top_unit"] = (float(units[0][1]), str(units[0][0]))
        out += _rows_for(run_id, computed_at, tier, resource_type, name, stats)
    return out
