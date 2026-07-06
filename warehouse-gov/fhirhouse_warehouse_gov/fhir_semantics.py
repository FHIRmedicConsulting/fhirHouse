"""FHIR R4 StructureDefinition semantics → the catalog (FH-0004 follow-on).

Three layers, all sourced from the operator's FHIR package cache (the same
StructureDefinitions the flattener, DQ generator, and view pack build from):

  1. Descriptions — every registered resource table gets the SD's resource
     description; every Silver column that maps to a top-level element gets the
     element's `short` documentation (real HL7 text, not our type notes).
  2. Glossary — a "FHIR-R4" glossary: one term per cataloged resource type
     (spec link included) and child terms per top-level element for the
     governance-domain types; terms are attached to their tables as glossary tags.
  3. Domains — Clinical / Provider / Patient-Member (from dq/domains.yml) plus
     Data Governance become OpenMetadata Domains, with tables assigned.

    python -m fhirhouse_warehouse_gov.fhir_semantics --base ~/fhirhouse-demo/delta \
        [--service fhirhouse-standalone] [--database fhirhouse_demo]
"""
from __future__ import annotations

import json

import yaml

from fhirhouse_contracts.schema import load_pin
from fhirhouse_dq.fhir_packages import PackageIndex
from fhirhouse_dq.generate_checks import DOMAINS_YML

from .openmetadata import OpenMetadataClient

GLOSSARY = "FHIR-R4"
GOVERNANCE_TABLES = {"dq_score", "dq_profile", "patient_link", "patient_match_review",
                     "patient_merge_history", "pprl_tokens", "mpi_decision_log"}
_MAXLEN = 950  # keep catalog descriptions readable


def _clip(s: str | None) -> str:
    s = (s or "").strip()
    return s if len(s) <= _MAXLEN else s[:_MAXLEN - 1] + "…"


def _spec_url(rtype: str) -> str:
    return f"https://hl7.org/fhir/R4/{rtype.lower()}.html"


def element_docs(pkgs: PackageIndex, rtype: str) -> dict[str, str]:
    """top-level element name (incl. concrete choice variants) -> HL7 `short` doc."""
    sd = pkgs.structure_definition(rtype)
    if not sd:
        return {}
    docs: dict[str, str] = {}
    for el in sd["snapshot"]["element"]:
        path = el.get("path", "")
        if not path.startswith(rtype + ".") or path.count(".") != 1:
            continue
        name = path.split(".", 1)[1]
        short = el.get("short") or ""
        if not short:
            continue
        if name.endswith("[x]"):
            base = name[:-3]
            for t in el.get("type", []):
                code = t.get("code", "")
                docs[base + code[0].upper() + code[1:]] = _clip(f"{short} ({code})")
        else:
            docs[name] = _clip(short)
    return docs


def resource_description(pkgs: PackageIndex, rtype: str) -> str:
    sd = pkgs.structure_definition(rtype) or {}
    text = sd.get("description") or ""
    for el in sd.get("snapshot", {}).get("element", [])[:1]:
        text = text or el.get("definition") or el.get("short") or ""
    return _clip(f"**FHIR R4 {rtype}** — {text}\n\nSpec: {_spec_url(rtype)}")


# ── catalog operations ──────────────────────────────────────────────────────────

def _catalog_tables(om: OpenMetadataClient, service: str, database: str) -> list[dict]:
    out, after = [], None
    while True:
        page = om.get(f"/tables?database={service}.{database}&fields=columns,tags,domains"
                      f"&limit=100" + (f"&after={after}" if after else ""))
        out += page.get("data", [])
        after = page.get("paging", {}).get("after")
        if not after:
            return out


def enrich_descriptions(om: OpenMetadataClient, tables: list[dict],
                        pkgs: PackageIndex, canonical: dict[str, str]) -> dict:
    enriched_tables = enriched_cols = 0
    for t in tables:
        rtype = canonical.get(t["name"])
        if not rtype:
            continue
        ops = [{"op": "add" if not t.get("description") else "replace",
                "path": "/description", "value": resource_description(pkgs, rtype)}]
        tier = t["fullyQualifiedName"].rsplit(".", 2)[-2]
        if tier == "silver":
            docs = element_docs(pkgs, rtype)
            for i, col in enumerate(t.get("columns", [])):
                short = docs.get(col["name"])
                if short:
                    ops.append({"op": "add" if not col.get("description") else "replace",
                                "path": f"/columns/{i}/description",
                                "value": f"{short} — FHIR `{rtype}.{col['name']}`"})
                    enriched_cols += 1
        om.patch(f"/tables/{t['id']}", ops)
        enriched_tables += 1
    return {"tables": enriched_tables, "columns": enriched_cols}


def build_glossary(om: OpenMetadataClient, pkgs: PackageIndex, tables: list[dict],
                   canonical: dict[str, str], element_terms_for: set[str]) -> dict:
    om.put("/glossaries", {
        "name": GLOSSARY, "displayName": "FHIR R4",
        "description": "HL7 FHIR R4 (4.0.1) resource and element definitions, generated "
                       "from hl7.fhir.r4.core StructureDefinitions. Regenerate: "
                       "`python -m fhirhouse_warehouse_gov.fhir_semantics`."})
    rtypes = sorted({canonical[t["name"]] for t in tables if t["name"] in canonical})
    terms = elements = 0
    for rtype in rtypes:
        om.put("/glossaryTerms", {
            "glossary": GLOSSARY, "name": rtype,
            "description": resource_description(pkgs, rtype),
            "references": [{"name": "HL7 R4 spec", "endpoint": _spec_url(rtype)}]})
        terms += 1
        if rtype in element_terms_for:
            for el, short in sorted(element_docs(pkgs, rtype).items()):
                # term names are glossary-unique (not per-parent): prefix with the type
                om.put("/glossaryTerms", {
                    "glossary": GLOSSARY, "parent": f"{GLOSSARY}.{rtype}",
                    "name": f"{rtype}-{el}", "displayName": el,
                    "description": _clip(f"{short}\n\n`{rtype}.{el}`")})
                elements += 1

    tagged = 0  # attach each table to its resource-type term
    for t in tables:
        rtype = canonical.get(t["name"])
        if not rtype:
            continue
        fqn = f"{GLOSSARY}.{rtype}"
        if any(tag.get("tagFQN") == fqn for tag in t.get("tags") or []):
            continue
        om.patch(f"/tables/{t['id']}", [{
            "op": "add", "path": "/tags/-",
            "value": {"tagFQN": fqn, "source": "Glossary",
                      "labelType": "Automated", "state": "Confirmed"}}])
        tagged += 1
    return {"resource_terms": terms, "element_terms": elements, "tables_tagged": tagged}


def create_domains(om: OpenMetadataClient, tables: list[dict], canonical: dict[str, str]) -> dict:
    cfg = yaml.safe_load(DOMAINS_YML.read_text())["domains"]
    display = {"patient_member": "Patient / Member", "provider": "Provider", "clinical": "Clinical"}
    type_to_domain: dict[str, str] = {}
    domain_ids: dict[str, str] = {}
    for dom, types in cfg.items():
        name = display.get(dom, dom.title())
        d = om.put("/domains", {
            "name": name.replace(" / ", "-").replace(" ", "-"), "displayName": name,
            "domainType": "Source-aligned",
            "description": f"fhirHouse governance domain (dq/domains.yml): "
                           f"{', '.join(types)}."})
        domain_ids[dom] = d["id"]
        for rtype in types:
            type_to_domain[rtype] = d["id"]
    g = om.put("/domains", {
        "name": "Data-Governance", "displayName": "Data Governance",
        "domainType": "Aggregate",
        "description": "fhirHouse governance outputs: DQ scores/profiles, MPI link/"
                       "review/merge tables, PPRL tokens."})

    assigned = 0
    for t in tables:
        rtype = canonical.get(t["name"])
        dom_id = type_to_domain.get(rtype) if rtype else (
            g["id"] if t["name"] in GOVERNANCE_TABLES else None)
        if not dom_id or any(d.get("id") == dom_id for d in t.get("domains") or []):
            continue
        om.patch(f"/tables/{t['id']}", [{
            "op": "add", "path": "/domains/-", "value": {"id": dom_id, "type": "domain"}}])
        assigned += 1
    return {"domains": len(domain_ids) + 1, "tables_assigned": assigned}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="FHIR R4 semantics -> OpenMetadata")
    ap.add_argument("--om", default=None)
    ap.add_argument("--service", default="fhirhouse-standalone")
    ap.add_argument("--database", default="fhirhouse_demo")
    args = ap.parse_args()

    om = OpenMetadataClient(url=args.om)
    if not om.token:
        om.login()
    pkgs = PackageIndex()
    pin = load_pin()
    canonical = {t.lower(): t for t in pin["resource_types"]}
    element_terms_for = set()
    for types in yaml.safe_load(DOMAINS_YML.read_text())["domains"].values():
        element_terms_for |= set(types)

    tables = _catalog_tables(om, args.service, args.database)
    print(f"[semantics] {len(tables)} tables in catalog")
    print(f"[semantics] descriptions: {json.dumps(enrich_descriptions(om, tables, pkgs, canonical))}")
    print(f"[semantics] glossary:     {json.dumps(build_glossary(om, pkgs, tables, canonical, element_terms_for))}")
    print(f"[semantics] domains:      {json.dumps(create_domains(om, tables, canonical))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
