"""PPRL tokenization → gold.pprl_tokens (fhirEngine ADR-0012 §6, v1.x lane).

Two built-in token kinds, config-driven (fhirEngine treats every token as an opaque
identifier value, so providers are pluggable):
  - hmac  — HMAC-SHA256 over normalized demographics; exact-match tokens
    (Datavant-compatible integration pattern: deterministic opaque token per person).
  - clk   — Cryptographic Long-term Key: keyed Bloom filter over field bigrams
    (OpenHIE-style), error-tolerant for dice-coefficient comparison at the QHIN side.

Keys are CUSTOMER-CONTROLLED: read from env at runtime (config names the env var),
never persisted. Rotation = bump pipeline_version; old tokens are marked deleted
after the overlap window (mark_rotated).
"""
from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import unicodedata
from datetime import datetime, timezone

from fhirhouse_contracts import PathCatalog, SidecarClient

from .config import PprlTokenSystem


def _norm(v: str | None) -> str:
    """Aggressive normalization so the same person tokenizes identically across orgs:
    NFKD → ASCII, uppercase, alnum only."""
    if not v:
        return ""
    v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode()
    return "".join(ch for ch in v.upper() if ch.isalnum())


def _record_fields(record: dict, fields: list[str]) -> list[str]:
    return [_norm(record.get(f)) for f in fields]


def hmac_token(record: dict, system: PprlTokenSystem) -> str:
    msg = "|".join(_record_fields(record, system.fields)).encode()
    return hmac_mod.new(system.key(), msg, hashlib.sha256).hexdigest()


def _bigrams(v: str) -> list[str]:
    padded = f"_{v}_"
    return [padded[i:i + 2] for i in range(len(padded) - 1)] if v else []


def clk_token(record: dict, system: PprlTokenSystem) -> str:
    """Keyed CLK: every field bigram sets `clk_hashes` bits chosen by
    HMAC(key, gram|i) mod bits. Base64 of the bit array."""
    bits = bytearray(system.clk_bits // 8)
    key = system.key()
    for field_val in _record_fields(record, system.fields):
        for gram in _bigrams(field_val):
            for i in range(system.clk_hashes):
                digest = hmac_mod.new(key, f"{gram}|{i}".encode(), hashlib.sha256).digest()
                pos = int.from_bytes(digest[:4], "big") % system.clk_bits
                bits[pos // 8] |= 1 << (pos % 8)
    return base64.b64encode(bytes(bits)).decode()


_KINDS = {"hmac": hmac_token, "clk": clk_token}


def generate_tokens(
    records: list[dict],
    systems: list[PprlTokenSystem],
    sidecar: SidecarClient | None = None,
    catalog: PathCatalog | None = None,
    write: bool = True,
) -> list[dict]:
    """Tokenize linkage records (splink_model.patient_to_record shape, `unique_id` =
    patient fhir id) for every configured token system; append to gold.pprl_tokens.
    Row shape is the pinned fhirhouse_tables contract."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for system in systems:
        make = _KINDS.get(system.kind)
        if make is None:
            raise ValueError(f"unknown PPRL token kind {system.kind!r} (expected one of {sorted(_KINDS)})")
        for r in records:
            if not r.get("unique_id"):
                continue
            rows.append({
                "patient_fhir_id": r["unique_id"],
                "token_system": system.name,
                "token_value": make(r, system),
                "token_pipeline_version": system.pipeline_version,
                "generated_at": now,
                "deleted": False,
            })
    if write and rows:
        sidecar = sidecar or SidecarClient()
        catalog = catalog or PathCatalog()
        sidecar.write(catalog.pprl_tokens_path(), rows, mode="append")
    return rows


def mark_rotated(system_name: str, before_pipeline_version: str,
                 sidecar: SidecarClient | None = None, catalog: PathCatalog | None = None) -> dict:
    """After key rotation + QHIN overlap window: flag pre-rotation tokens deleted.
    Uses the sidecar's predicate delete (one writer, one commit)."""
    sidecar = sidecar or SidecarClient()
    catalog = catalog or PathCatalog()
    if "'" in system_name or "'" in before_pipeline_version:
        raise ValueError("token system / pipeline version must not contain quotes")
    return sidecar.delete(
        catalog.pprl_tokens_path(),
        predicate=f"token_system = '{system_name}' AND token_pipeline_version = '{before_pipeline_version}'",
    )
