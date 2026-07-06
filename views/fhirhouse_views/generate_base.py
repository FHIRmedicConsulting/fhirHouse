"""Generate a base flat SQL-on-FHIR ViewDefinition for EVERY concrete R4 resource.

    python -m fhirhouse_views.generate_base --packages /path/to/fhirPackages

Reads the hl7.fhir.r4.core StructureDefinitions, and for each concrete resource emits
`views/definitions/<resource>.ViewDefinition.json` containing a one-row-per-resource
projection of:

  - getResourceKey()                         -> <resource>_id
  - top-level primitive scalars / arrays     -> typed column / collection column
  - choice elements (value[x], ...)          -> field.ofType(<type>) per primitive + Reference
  - top-level Reference (scalar/array)        -> field.getReferenceKey()
  - scalar CodeableConcept / Coding / Identifier / Quantity / Meta -> convenient sub-columns

Robustness contract (FH-0005): every candidate column is TEST-COMPILED through the
real ViewCompiler; columns the compiler cannot lower are dropped and logged, so the
emitted pack is 100% compilable by construction. Nested/backbone elements and arrays
of complex types are intentionally left to curated `*_flat` views (forEach) — a base
view is flat and universal, not exhaustive.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

from .compiler import CompileError, ViewCompiler

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "views" / "definitions" / "base"

# Source shape the compiler expects (resource JSON + resource_key), used for test-compile.
SRC = "SELECT CAST(body_json AS JSON) AS resource, fhir_id AS resource_key FROM t"

PRIMITIVES = {
    "base64Binary", "boolean", "canonical", "code", "date", "dateTime", "decimal",
    "id", "instant", "integer", "integer64", "markdown", "oid", "positiveInt",
    "string", "time", "unsignedInt", "uri", "url", "uuid",
}
# top-level elements never worth a base column
SKIP_FIELDS = {"id", "meta", "text", "contained", "extension", "modifierExtension"}


def snake(s: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", s)
    return re.sub(r"__+", "_", s).lower()


def load_resource_sds(pkg_dir: pathlib.Path) -> dict[str, dict]:
    """type -> StructureDefinition for concrete (non-abstract, specialization) resources."""
    out: dict[str, dict] = {}
    for f in pkg_dir.glob("StructureDefinition-*.json"):
        try:
            sd = json.loads(f.read_text())
        except Exception:
            continue
        if (sd.get("resourceType") == "StructureDefinition"
                and sd.get("kind") == "resource"
                and not sd.get("abstract", False)
                and sd.get("derivation") == "specialization"):
            out[sd["type"]] = sd
    return out


def top_level_elements(sd: dict) -> list[dict]:
    rtype = sd["type"]
    elems = (sd.get("snapshot") or sd.get("differential") or {}).get("element", [])
    top = []
    for e in elems:
        path = e.get("path", "")
        # exactly one segment below the resource root: "Patient.birthDate"
        if path.count(".") != 1 or not path.startswith(rtype + "."):
            continue
        top.append(e)
    return top


def candidate_columns(rtype: str, elems: list[dict]) -> list[dict]:
    cols: list[dict] = [{"name": f"{snake(rtype)}_id", "path": "getResourceKey()", "type": "id"}]
    seen = {cols[0]["name"]}

    def add(name: str, path: str, typ: str | None = None, collection: bool = False):
        base = name
        i = 2
        while name in seen:
            name = f"{base}_{i}"
            i += 1
        seen.add(name)
        col: dict = {"name": name, "path": path}
        if typ:
            col["type"] = typ
        if collection:
            col["collection"] = True
        cols.append(col)

    for e in elems:
        field = e["path"].split(".", 1)[1]
        raw = field  # may end with [x]
        field = field[:-3] if field.endswith("[x]") else field
        if field in SKIP_FIELDS:
            continue
        is_coll = e.get("max") == "*" or (e.get("max", "1") not in ("0", "1"))
        types = [t.get("code") for t in e.get("type", []) if t.get("code")]
        if not types:
            continue  # contentReference / no type
        is_choice = raw.endswith("[x]") or len(types) > 1
        sfield = snake(field)

        if is_choice:
            for code in types:
                if code in PRIMITIVES:
                    add(f"{sfield}_{snake(code)}", f"{field}.ofType({code})", code)
                elif code == "Reference":
                    add(f"{sfield}_id", f"{field}.ofType(Reference).getReferenceKey()", "id")
                # other complex choice types -> curated views
            continue

        code = types[0]
        if code in PRIMITIVES:
            add(sfield, field, code, collection=is_coll)
        elif code == "Reference":
            if is_coll:
                add(f"{sfield}_ids", f"{field}.getReferenceKey()", "id", collection=True)
            else:
                add(f"{sfield}_id", f"{field}.getReferenceKey()", "id")
                add(f"{sfield}_reference", f"{field}.reference", "string")
        elif code == "Meta":
            add("last_updated", f"{field}.lastUpdated", "instant")
            add("version_id", f"{field}.versionId", "id")
            add("source", f"{field}.source", "uri")
        elif code == "CodeableConcept" and not is_coll:
            add(f"{sfield}_text", f"{field}.text", "string")
            add(f"{sfield}_code", f"{field}.coding.first().code", "code")
            add(f"{sfield}_system", f"{field}.coding.first().system", "uri")
        elif code == "Coding" and not is_coll:
            add(f"{sfield}_code", f"{field}.code", "code")
            add(f"{sfield}_system", f"{field}.system", "uri")
            add(f"{sfield}_display", f"{field}.display", "string")
        elif code == "Identifier" and not is_coll:
            add(f"{sfield}_value", f"{field}.value", "string")
            add(f"{sfield}_system", f"{field}.system", "uri")
        elif code == "Quantity" and not is_coll:
            add(f"{sfield}_value", f"{field}.value", "decimal")
            add(f"{sfield}_unit", f"{field}.unit", "string")
            add(f"{sfield}_code", f"{field}.code", "code")
        # everything else (BackboneElement, HumanName, Address, arrays of complex, ...) -> curated
    return cols


def compiles(rtype: str, column: dict) -> bool:
    view = {"resourceType": "ViewDefinition", "name": "t", "status": "draft",
            "resource": rtype, "select": [{"column": [column]}]}
    try:
        ViewCompiler(view, typed=True).compile(SRC)
        return True
    except (CompileError, Exception):
        return False


def build_view(rtype: str, sd: dict) -> tuple[dict, int]:
    cols = candidate_columns(rtype, top_level_elements(sd))
    kept, dropped = [], 0
    for c in cols:
        if c["path"] == "getResourceKey()" or compiles(rtype, c):
            kept.append(c)
        else:
            dropped += 1
    view = {
        "resourceType": "ViewDefinition",
        "name": snake(rtype),
        "title": f"{rtype} — base flat view (generated)",
        "status": "draft",
        "description": (f"Auto-generated base flat view for {rtype} from "
                        "hl7.fhir.r4.core-4.0.1. One row per resource; top-level scalar/"
                        "primitive/choice/reference elements. Nested & complex-array "
                        "elements are covered by curated *_flat views. Regenerate with "
                        "`python -m fhirhouse_views.generate_base`."),
        "resource": rtype,
        "select": [{"column": kept}],
    }
    # final whole-view compile as a belt-and-suspenders check
    ViewCompiler(view, typed=True).compile(SRC)
    return view, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packages", required=True,
                    help="fhirPackages dir containing hl7.fhir.r4.core-*-package/package")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    pkgs = pathlib.Path(args.packages)
    matches = list(pkgs.glob("hl7.fhir.r4.core*package/package")) or \
        list(pkgs.glob("**/StructureDefinition-Patient.json"))
    if not matches:
        raise SystemExit(f"Could not find R4 core package/ under {pkgs}")
    pkg_dir = matches[0] if matches[0].is_dir() else matches[0].parent
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    sds = load_resource_sds(pkg_dir)
    total_cols = total_drop = 0
    written = 0
    for rtype in sorted(sds):
        view, dropped = build_view(rtype, sds[rtype])
        ncol = len(view["select"][0]["column"])
        total_cols += ncol
        total_drop += dropped
        (out / f"{view['name']}.ViewDefinition.json").write_text(
            json.dumps(view, indent=2) + "\n")
        written += 1
        print(f"[gen] {rtype:<32} {ncol:>3} cols" + (f"  (-{dropped})" if dropped else ""))
    print(f"\n[gen] {written} resource views written to {out}")
    print(f"[gen] {total_cols} columns total; {total_drop} candidate columns dropped as "
          f"non-compilable (fail-loud contract).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
