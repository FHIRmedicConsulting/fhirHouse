"""Hard-deny guardrails (fhirEngine ADR-0012 §3.4) — Python port of the safety floors
in upstream's mpi.ts, applied at the PROBABILISTIC stage too (guardrail #4: a
high-scoring Splink pair that violates a floor is routed to review, never auto).

Keep behavior in lockstep with packages/server/src/repository/mpi.ts — these are the
same floors both stages share. Floors are NOT configurable off; only parameters
(deceased window days) are configurable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"


def normalize_identifier(system: Any, value: Any) -> str | None:
    """Canonical `system|value` key (ADR-0012 §3): lowercase scheme+host, strip trailing
    slash; SSN values collapsed to digits. Mirrors mpi.ts normalizeIdentifier."""
    if not isinstance(value, str) or not value.strip():
        return None
    sys_ = system.strip() if isinstance(system, str) else ""
    parts = urlsplit(sys_)
    if parts.scheme and parts.netloc:
        sys_ = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))
        sys_ = sys_.rstrip("/")
    else:
        sys_ = sys_.rstrip("/")  # urn:oid:… and friends — trim only
    val = " ".join(value.strip().split())
    if sys_ == SSN_SYSTEM:
        val = "".join(ch for ch in val if ch.isdigit())
    return f"{sys_}|{val}"


def identifier_keys(body: dict) -> list[str]:
    out: list[str] = []
    for ident in body.get("identifier") or []:
        k = normalize_identifier((ident or {}).get("system"), (ident or {}).get("value"))
        if k and k not in out:
            out.append(k)
    return out


def identifier_systems(body: dict) -> set[str]:
    return {k.split("|", 1)[0] for k in identifier_keys(body)}


def ssn_of(body: dict) -> str | None:
    for k in identifier_keys(body):
        if k.startswith(f"{SSN_SYSTEM}|"):
            return k
    return None


def _parse_dt(v: str) -> datetime | None:
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def guardrail(a: dict, b: dict, deceased_window_days: int = 14) -> str | None:
    """Blocking reason for a candidate pair of Patient bodies, "distinct" for the
    hard-distinct SSN conflict, or None (pair may auto-match)."""
    sa, sb = ssn_of(a), ssn_of(b)
    if sa and sb and sa != sb:
        return "distinct"  # conflicting authoritative identifier → never match
    ga, gb = a.get("gender"), b.get("gender")
    if ga and gb and ga != gb and ga != "unknown" and gb != "unknown":
        return "sex_mismatch"
    da, db = a.get("deceasedDateTime"), b.get("deceasedDateTime")
    if isinstance(da, str) and isinstance(db, str):
        ta, tb = _parse_dt(da), _parse_dt(db)
        if ta and tb and abs((ta - tb).total_seconds()) > deceased_window_days * 86_400:
            return "date_of_death_mismatch"
    if a.get("active") is False or b.get("active") is False:
        return "inactive_candidate"
    return None
