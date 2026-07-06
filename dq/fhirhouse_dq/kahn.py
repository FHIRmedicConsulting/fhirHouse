"""Kahn-dimension DQ metrics (Kahn et al. 2016 harmonized DQ framework).

Population-level scoring over parsed FHIR resources of one type:
  - conformance   — values conform to the pinned contract: required elements present,
    required-binding coded elements populated, date/dateTime lexical form valid.
  - completeness  — population rate of each top-level column in the pinned flattener
    schema (the columns Silver/Gold analytics actually see).
  - plausibility  — believability rules (temporal ordering, value ranges), a
    per-resource-type registry extendable per deployment.

Pure functions — no I/O; `runner.py` feeds rows and persists scores.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from fhirhouse_contracts.schema import load_pin

DQ_VERSION = "0.1.0"

# FHIR lexical forms (R4 datatypes page) — L1-ish, but scored over the population.
_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_DATETIME_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2}))?)?)?$")

# Small closed R4 code sets checked inline (full terminology validation is the HL7
# validator's job — see validator.py; these catch the cheap obvious miscodes).
_INLINE_CODESETS = {
    "http://hl7.org/fhir/ValueSet/administrative-gender": {"male", "female", "other", "unknown"},
    "http://hl7.org/fhir/ValueSet/observation-status": {
        "registered", "preliminary", "final", "amended", "corrected",
        "cancelled", "entered-in-error", "unknown"},
}


@dataclass
class MetricResult:
    dimension: str  # conformance | completeness | plausibility
    metric: str
    numerator: int
    denominator: int
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float | None:
        return None if self.denominator == 0 else self.numerator / self.denominator


def _present(v: Any) -> bool:
    return v is not None and v != [] and v != {} and v != ""


# ── plausibility rule registry: name -> (applies(r) -> bool, ok(r) -> bool) ─────────
def _birth(r: dict) -> str | None:
    return r.get("birthDate")

def _deceased(r: dict) -> str | None:
    v = r.get("deceasedDateTime")
    return v if isinstance(v, str) else None

PLAUSIBILITY_RULES: dict[str, dict[str, tuple[Callable[[dict], bool], Callable[[dict, date], bool]]]] = {
    "Patient": {
        "birthdate_not_future": (
            lambda r: isinstance(_birth(r), str) and bool(_DATE_RE.match(_birth(r))),
            lambda r, today: _birth(r)[:10] <= today.isoformat(),
        ),
        "age_at_most_120": (
            lambda r: isinstance(_birth(r), str) and bool(_DATE_RE.match(_birth(r))),
            lambda r, today: int(_birth(r)[:4]) >= today.year - 120,
        ),
        "deceased_after_birth": (
            lambda r: isinstance(_birth(r), str) and _deceased(r) is not None,
            lambda r, today: _deceased(r)[:10] >= _birth(r)[:10],
        ),
    },
    "Observation": {
        "effective_not_future": (
            lambda r: isinstance(r.get("effectiveDateTime"), str),
            lambda r, today: r["effectiveDateTime"][:10] <= today.isoformat(),
        ),
    },
}


def score_resources(
    resource_type: str,
    resources: list[dict],
    pin: dict | None = None,
    today: date | None = None,
) -> list[MetricResult]:
    pin = pin or load_pin()
    today = today or datetime.now(timezone.utc).date()
    cols = pin["top_level_columns"].get(resource_type, [])
    n = len(resources)
    out: list[MetricResult] = []

    # completeness — population rate per pinned top-level column (skip primitive-extension
    # shadow columns `_x`; they're representation, not content).
    for c in cols:
        name = c["name"]
        if name.startswith("_"):
            continue
        out.append(MetricResult(
            "completeness", f"populated:{name}",
            sum(1 for r in resources if _present(r.get(name))), n,
            {"fhirType": c["fhirType"]},
        ))

    # conformance — required elements (base cardinality min>=1 from the pin).
    required = [c["name"] for c in cols if c.get("required") and not c["name"].startswith("_")]
    if required:
        out.append(MetricResult(
            "conformance", "required_elements_present",
            sum(1 for r in resources if all(_present(r.get(q)) for q in required)), n,
            {"required": required},
        ))

    # conformance — required-binding code columns: populated values fall in the inline
    # code set when we have it (full binding validation is L5 / validator.py).
    for c in cols:
        vs, name = c.get("binding"), c["name"]
        codeset = _INLINE_CODESETS.get(vs) if vs else None
        if not codeset or c["fhirType"] != "code":
            continue
        populated = [r for r in resources if isinstance(r.get(name), str)]
        out.append(MetricResult(
            "conformance", f"code_in_valueset:{name}",
            sum(1 for r in populated if r[name] in codeset), len(populated),
            {"valueSet": vs},
        ))

    # conformance — date/dateTime lexical form on populated scalar date columns.
    for c in cols:
        if c["fhirType"] not in ("date", "dateTime", "instant") or c.get("list") or c["name"].startswith("_"):
            continue
        name = c["name"]
        populated = [r for r in resources if isinstance(r.get(name), str)]
        if not populated:
            continue
        rex = _DATE_RE if c["fhirType"] == "date" else _DATETIME_RE
        out.append(MetricResult(
            "conformance", f"date_lexical_form:{name}",
            sum(1 for r in populated if rex.match(r[name])), len(populated),
        ))

    # plausibility — registry rules; denominator = resources the rule applies to.
    for rule_name, (applies, ok) in PLAUSIBILITY_RULES.get(resource_type, {}).items():
        applicable = [r for r in resources if applies(r)]
        out.append(MetricResult(
            "plausibility", rule_name,
            sum(1 for r in applicable if ok(r, today)), len(applicable),
        ))

    return out
