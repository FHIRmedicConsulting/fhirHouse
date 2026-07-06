"""Generate domain DQ check suites from the FHIR packages (code-gen, like the view pack).

    python -m fhirhouse_dq.generate_checks

For every resource type in dq/domains.yml, reads the R4 core StructureDefinition
snapshot (+ the mapped US Core profile differential) and emits
dq/checks/<domain>/<Type>.checks.json containing:

  required          base cardinality min>=1 (top-level and one nested level,
                    relative-to-parent semantics)
  binding           required-strength bindings with the code set EXPANDED from the
                    package's ValueSets/CodeSystems (skipped honestly when the set
                    isn't package-expandable — SNOMED/LOINC etc.)
  format            strict lexical form for temporal primitives
  date_plausible    temporal values within [1900, today+1y]
  max_cardinality   scalar elements that must not arrive as arrays
  reference_target  Reference elements checked against their declared target types
                    (+ existence when the runner passes id sets)
  must_support      US Core must-support elements as completeness expectations

Every check is EXECUTED against smoke resources before it is emitted — the suite
is runnable by construction (fail-loud; non-generable checks are counted, not
guessed at).
"""
from __future__ import annotations

import json
import pathlib

import yaml

from .checks import run_checks
from .fhir_packages import PackageIndex

DQ_DIR = pathlib.Path(__file__).resolve().parent.parent
DOMAINS_YML = DQ_DIR / "domains.yml"
CHECKS_OUT = DQ_DIR / "checks"

MAX_DEPTH = 2
SKIP_SEGS = {"extension", "modifierExtension", "contained", "text", "meta", "id",
             "implicitRules", "language"}
TEMPORAL_REGEX = {
    "date": r"^\d{4}(-\d{2}(-\d{2})?)?$",
    "dateTime": r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2}))?)?)?$",
    "instant": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$",
    "time": r"^\d{2}:\d{2}:\d{2}(\.\d+)?$",
}
BINDABLE = {"code", "Coding", "CodeableConcept", "string", "uri"}
_BINDING_SUBPATH = {"Coding": ["code"], "CodeableConcept": ["coding", "code"]}

SMOKE = [{}, {"resourceType": "X", "status": "final", "name": [{"family": "S", "given": ["J"]}],
          "subject": {"reference": "Patient/1"}, "birthDate": "1980-01-01"}]


def _cap(s: str) -> str:
    return s[0].upper() + s[1:]


def _rel_segs(rtype: str, path: str) -> list[str] | None:
    if not path.startswith(rtype + ".") or path == rtype:
        return None
    segs = path[len(rtype) + 1:].split(".")
    if len(segs) > MAX_DEPTH or any(s in SKIP_SEGS for s in segs) or \
            any(s.endswith("[x]") for s in segs[:-1]):
        return None
    return segs


def _split(segs: list[str]) -> tuple[list[str] | None, list[str]]:
    return (segs[:-1] or None, segs) if len(segs) > 1 else (None, segs)


def _target_types(el: dict) -> list[str]:
    out = []
    for t in el.get("type", []):
        if t.get("code") != "Reference":
            continue
        for prof in t.get("targetProfile") or []:
            name = prof.rsplit("/", 1)[-1]
            if name not in ("Resource", "DomainResource"):
                out.append(name)
    return sorted(set(out))


def core_checks(pkgs: PackageIndex, rtype: str) -> tuple[list[dict], dict]:
    sd = pkgs.structure_definition(rtype)
    checks: list[dict] = []
    dropped = {"binding_unexpandable": 0}
    seen_metrics: set[str] = set()

    def add(check: dict) -> None:
        base = check["metric"]
        i = 2
        while check["metric"] in seen_metrics:
            check["metric"] = f"{base}_{i}"
            i += 1
        seen_metrics.add(check["metric"])
        checks.append(check)

    for el in sd["snapshot"]["element"]:
        segs = _rel_segs(rtype, el["path"])
        if segs is None or el.get("contentReference"):
            continue
        types = el.get("type") or []
        is_choice = segs[-1].endswith("[x]")
        variants = ([(segs[:-1] + [segs[-1][:-3] + _cap(t["code"])], t["code"]) for t in types]
                    if is_choice else [(segs, types[0]["code"] if types else None)])
        dotted = ".".join(segs)
        src = "hl7.fhir.r4.core#4.0.1"

        # required (skip choice — "one of" semantics need a choice-level check)
        if (el.get("min") or 0) >= 1 and not is_choice and types:
            parent, path = _split(segs)
            add({"kind": "required", "path": path[-1:] if parent else path, "parent": parent,
                 "metric": f"required:{dotted}", "source": src,
                 "description": f"{el['path']} has base cardinality min>=1"})

        for vsegs, tcode in variants:
            vdotted = ".".join(vsegs)
            if tcode in TEMPORAL_REGEX:
                parent, _ = _split(vsegs)
                path = vsegs[-1:] if parent else vsegs
                add({"kind": "format", "path": path, "parent": parent, "regex": TEMPORAL_REGEX[tcode],
                     "metric": f"format:{vdotted}", "source": src,
                     "description": f"{tcode} lexical form"})
                add({"kind": "date_plausible", "path": path, "parent": parent,
                     "metric": f"date_range:{vdotted}", "source": src,
                     "description": "temporal value within [1900, today+1y]"})
            if tcode == "Reference":
                targets = _target_types(el)
                if targets:
                    parent, _ = _split(vsegs)
                    add({"kind": "reference_target", "path": vsegs[-1:] if parent else vsegs,
                         "parent": parent, "targets": targets,
                         "metric": f"ref_target:{vdotted}", "source": src,
                         "description": f"reference points at {'/'.join(targets[:4])}"})

        # required bindings — expand from the package or skip honestly
        binding = el.get("binding") or {}
        if binding.get("strength") == "required" and binding.get("valueSet") and not is_choice \
                and types and types[0]["code"] in BINDABLE:
            codes = pkgs.expand_valueset(binding["valueSet"].split("|")[0])
            if codes is None:
                dropped["binding_unexpandable"] += 1
            else:
                sub = _BINDING_SUBPATH.get(types[0]["code"], [])
                parent, path = _split(segs)
                add({"kind": "binding", "path": (path[-1:] if parent else path) + sub,
                     "parent": parent, "codes": sorted(codes),
                     "metric": f"binding:{dotted}", "source": binding["valueSet"].split("|")[0],
                     "description": f"required binding ({len(codes)} codes)"})

        # scalar elements (incl. each choice variant) must not arrive as arrays
        if el.get("max") == "1" and len(segs) == 1 and types:
            for vsegs, _ in variants:
                add({"kind": "max_cardinality", "path": vsegs, "max": 1,
                     "metric": f"max_card:{'.'.join(vsegs)}", "source": src,
                     "description": "scalar element (max=1) must not be an array"})

    return checks, dropped


def us_core_checks(pkgs: PackageIndex, rtype: str, profile_id: str) -> list[dict]:
    sd = pkgs.structure_definition(profile_id)
    if not sd:
        return []
    checks = []
    seen = set()
    for el in (sd.get("differential") or {}).get("element", []):
        if not el.get("mustSupport"):
            continue
        segs = _rel_segs(rtype, el["path"].split(":")[0])  # strip slice names
        if segs is None:
            continue
        variants = ([segs[:-1] + [segs[-1][:-3] + _cap(t["code"])] for t in el.get("type", [])]
                    if segs[-1].endswith("[x]") else [segs])
        for vsegs in variants:
            dotted = ".".join(vsegs)
            if dotted in seen:
                continue
            seen.add(dotted)
            parent, path = _split(vsegs)
            checks.append({"kind": "must_support", "path": path[-1:] if parent else path,
                           "parent": parent, "metric": f"ms:{dotted}", "source": profile_id,
                           "description": f"US Core must-support ({profile_id})"})
    return checks


def main() -> int:
    pkgs = PackageIndex()
    domains = yaml.safe_load(DOMAINS_YML.read_text())["domains"]
    total = 0
    for domain, types in domains.items():
        out_dir = CHECKS_OUT / domain
        out_dir.mkdir(parents=True, exist_ok=True)
        for rtype, cfg in types.items():
            checks, dropped = core_checks(pkgs, rtype)
            checks += us_core_checks(pkgs, rtype, (cfg or {}).get("us_core", "")) if cfg else []
            run_checks(SMOKE, checks)  # every emitted check must execute
            suite = {"resourceType": rtype, "domain": domain,
                     "generated_from": ["hl7.fhir.r4.core#4.0.1", "hl7.fhir.us.core#6.1.0"],
                     "regenerate": "python -m fhirhouse_dq.generate_checks",
                     "dropped": dropped, "checks": checks}
            (out_dir / f"{rtype}.checks.json").write_text(json.dumps(suite, indent=1) + "\n")
            kinds = {}
            for c in checks:
                kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
            print(f"[gen] {domain}/{rtype}: {len(checks)} checks {kinds} "
                  f"(skipped {dropped['binding_unexpandable']} unexpandable bindings)", flush=True)
            total += len(checks)
    print(f"[gen] total {total} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
