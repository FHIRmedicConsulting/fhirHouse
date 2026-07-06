"""FHIR package cache access: StructureDefinitions, ValueSet expansion, CodeSystems.

Reads the operator's local FHIR package cache (~/.fhir/packages — the same cache
fhirEngine's flattener uses). ValueSet expansion is package-local and honest about
its limits: compose includes with explicit concepts or complete CodeSystems expand;
filters, intensional rules, and non-local systems (SNOMED/LOINC/RxNorm — operator-
licensed, never redistributed) return None and the generator skips the check
(fail-loud contract: no check is better than a wrong check).
"""
from __future__ import annotations

import json
import os
import pathlib
from functools import lru_cache

DEFAULT_PACKAGES = ("hl7.fhir.r4.core#4.0.1", "hl7.fhir.us.core#6.1.0")


class PackageIndex:
    def __init__(self, cache_dir: str | None = None, packages: tuple[str, ...] = DEFAULT_PACKAGES):
        root = pathlib.Path(cache_dir or os.environ.get(
            "FHIR_PACKAGE_CACHE", os.path.expanduser("~/.fhir/packages")))
        self.dirs = [root / p / "package" for p in packages if (root / p / "package").is_dir()]
        if not self.dirs:
            raise FileNotFoundError(f"no FHIR packages found under {root} (looked for {packages})")
        self._url_index: dict[str, pathlib.Path] | None = None

    # ── resource lookup ─────────────────────────────────────────────────────────

    def _load(self, path: pathlib.Path) -> dict:
        return json.loads(path.read_text())

    def by_filename(self, kind: str, ident: str) -> dict | None:
        for d in self.dirs:
            p = d / f"{kind}-{ident}.json"
            if p.exists():
                return self._load(p)
        return None

    def by_url(self, kind: str, url: str) -> dict | None:
        """Resolve a canonical url. Filename heuristic first (last url segment),
        full-scan index as fallback (built once)."""
        url = url.split("|")[0]
        doc = self.by_filename(kind, url.rsplit("/", 1)[-1])
        if doc is not None and doc.get("url") == url:
            return doc
        if self._url_index is None:
            self._url_index = {}
            for d in self.dirs:
                for p in d.glob(f"{kind}-*.json"):
                    try:
                        u = json.loads(p.read_text()).get("url")
                    except (json.JSONDecodeError, OSError):
                        continue
                    if u:
                        self._url_index.setdefault(f"{kind}|{u}", p)
        p = self._url_index.get(f"{kind}|{url}")
        return self._load(p) if p else None

    def structure_definition(self, type_or_id: str) -> dict | None:
        return self.by_filename("StructureDefinition", type_or_id)

    # ── ValueSet expansion (package-local, extensional-only) ────────────────────

    def _codesystem_codes(self, system_url: str) -> set[str] | None:
        cs = self.by_url("CodeSystem", system_url)
        if not cs or cs.get("content") != "complete":
            return None

        def walk(concepts: list) -> set[str]:
            out = set()
            for c in concepts or []:
                if c.get("code"):
                    out.add(c["code"])
                out |= walk(c.get("concept") or [])
            return out
        return walk(cs.get("concept") or [])

    @lru_cache(maxsize=None)
    def expand_valueset(self, url: str, max_size: int = 2000) -> frozenset[str] | None:
        """Expanded code set for a ValueSet canonical, or None when not honestly
        expandable in-package (filters, missing/partial CodeSystems, too large)."""
        vs = self.by_url("ValueSet", url)
        if not vs:
            return None
        compose = vs.get("compose") or {}

        def resolve(clause: dict) -> set[str] | None:
            if clause.get("filter"):
                return None  # intensional — needs a terminology server
            if clause.get("valueSet"):
                acc: set[str] = set()
                for sub in clause["valueSet"]:
                    sub_codes = self.expand_valueset(sub, max_size)
                    if sub_codes is None:
                        return None
                    acc |= sub_codes
                return acc
            if clause.get("concept"):
                return {c["code"] for c in clause["concept"] if c.get("code")}
            if clause.get("system"):
                return self._codesystem_codes(clause["system"])
            return None

        codes: set[str] = set()
        for inc in compose.get("include") or []:
            got = resolve(inc)
            if got is None:
                return None
            codes |= got
        for exc in compose.get("exclude") or []:
            got = resolve(exc)
            if got is None:
                return None
            codes -= got
        if not codes or len(codes) > max_size:
            return None
        return frozenset(codes)
