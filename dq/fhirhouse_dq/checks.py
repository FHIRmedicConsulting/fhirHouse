"""Generated-check engine: evaluate a check suite over a resource population.

Checks are data (dq/checks/<domain>/<Type>.checks.json, from generate_checks.py);
this module is the interpreter. Denominator semantics per kind:

  required          resources (or parent instances, for nested paths) — presence
  binding           POPULATED values only (absence is completeness, not conformance)
  format            populated primitive values matching the type's lexical form
  max_cardinality   parent instances where the element is present
  must_support      resources/parent instances — population rate (completeness)
  date_plausible    populated temporal values within [1900-01-01, today + 1y]
  reference_target  populated Reference.reference values pointing at an allowed type;
                    with id_sets also emits an existence (integrity) metric
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .kahn import MetricResult

_DATEISH = re.compile(r"^(\d{4})(-\d{2})?(-\d{2})?([T ].*)?$")
_REF_TYPE = re.compile(r"(?:^|/)([A-Za-z]+)/([A-Za-z0-9\-\.]{1,64})(?:/_history/.*)?$")


def _values(node, segs: list[str]) -> list:
    """FHIRPath-style navigation with list flattening; returns all leaf values."""
    current = [node]
    for seg in segs:
        nxt = []
        for c in current:
            if isinstance(c, list):
                for item in c:
                    v = item.get(seg) if isinstance(item, dict) else None
                    if v is not None:
                        nxt.append(v)
            elif isinstance(c, dict):
                v = c.get(seg)
                if v is not None:
                    nxt.append(v)
        current = nxt
    out = []
    for c in current:  # flatten one trailing list level
        out.extend(c if isinstance(c, list) else [c])
    return out


def _contexts(resources: list[dict], parent: list[str] | None) -> list:
    """Evaluation contexts: whole resources, or every instance of `parent`."""
    if not parent:
        return resources
    ctxs = []
    for r in resources:
        ctxs.extend(v for v in _values(r, parent) if isinstance(v, dict))
    return ctxs


def _present(v) -> bool:
    return v not in (None, "", [], {})


def run_checks(resources: list[dict], checks: list[dict], today: date | None = None,
               id_sets: dict[str, set] | None = None) -> list[MetricResult]:
    today = today or date.today()
    hi = (today + timedelta(days=366)).isoformat()
    out: list[MetricResult] = []

    for c in checks:
        kind, segs = c["kind"], c["path"]
        ctxs = _contexts(resources, c.get("parent"))
        details = {k: c[k] for k in ("description", "source") if k in c}

        if kind in ("required", "must_support"):
            den = len(ctxs)
            num = sum(1 for x in ctxs if any(_present(v) for v in _values(x, segs)))
            dim = "conformance" if kind == "required" else "completeness"
            out.append(MetricResult(dim, c["metric"], num, den, details))

        elif kind == "binding":
            vals = [v for x in ctxs for v in _values(x, segs) if isinstance(v, str)]
            codes = set(c["codes"])
            bad = sorted({v for v in vals if v not in codes})[:5]
            if bad:
                details["examples_bad"] = bad
            out.append(MetricResult("conformance", c["metric"],
                                    sum(1 for v in vals if v in codes), len(vals), details))

        elif kind == "format":
            rex = re.compile(c["regex"])
            vals = [v for x in ctxs for v in _values(x, segs) if isinstance(v, str)]
            out.append(MetricResult("conformance", c["metric"],
                                    sum(1 for v in vals if rex.match(v)), len(vals), details))

        elif kind == "max_cardinality":
            parent_segs, last = segs[:-1], segs[-1]
            holders = _contexts(resources, (c.get("parent") or []) + parent_segs) \
                if parent_segs or c.get("parent") else ctxs
            den = num = 0
            for h in holders:
                raw = h.get(last) if isinstance(h, dict) else None
                if raw is None:
                    continue
                den += 1
                if c["max"] == 1:  # scalar element: ANY array is a shape violation
                    ok = not isinstance(raw, list)
                else:
                    ok = (len(raw) if isinstance(raw, list) else 1) <= c["max"]
                num += ok
            out.append(MetricResult("conformance", c["metric"], num, den, details))

        elif kind == "date_plausible":
            vals = [v for x in ctxs for v in _values(x, segs) if isinstance(v, str)]
            ok = 0
            for v in vals:
                m = _DATEISH.match(v)
                ok += bool(m and "1900" <= m.group(1) and v[:10] <= hi)
            out.append(MetricResult("plausibility", c["metric"], ok, len(vals), details))

        elif kind == "reference_target":
            refs = []
            for x in ctxs:
                for v in _values(x, segs):
                    if isinstance(v, dict) and isinstance(v.get("reference"), str):
                        refs.append(v["reference"])
            targets = set(c["targets"])
            typed = [(m.group(1), m.group(2)) for r in refs if (m := _REF_TYPE.match(r))]
            ok = sum(1 for t, _ in typed if not targets or t in targets)
            out.append(MetricResult("conformance", c["metric"], ok, len(typed), details))
            if id_sets is not None:
                resolvable = [(t, i) for t, i in typed if t in id_sets]
                found = sum(1 for t, i in resolvable if i in id_sets[t])
                out.append(MetricResult("integrity", c["metric"].replace("ref_target", "ref_exists"),
                                        found, len(resolvable), details))

        else:
            raise ValueError(f"unknown check kind {kind!r}")
    return out
