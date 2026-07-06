"""PPRL tokenization: determinism, key handling, normalization tolerance."""
import pytest

from fhirhouse_mdm.config import ConfigError, PprlTokenSystem
from fhirhouse_mdm.pprl import clk_token, generate_tokens, hmac_token

REC = {"unique_id": "p1", "given_name": "José", "family_name": "GARCÍA", "birth_date": "1980-01-15", "gender": "male"}


def hmac_sys(monkeypatch, key="k1"):
    monkeypatch.setenv("TEST_PPRL_KEY", key)
    return PprlTokenSystem(name="hmac-sha256:v1", kind="hmac", key_env="TEST_PPRL_KEY")


def test_hmac_deterministic_and_normalized(monkeypatch):
    s = hmac_sys(monkeypatch)
    ascii_rec = dict(REC, given_name="JOSE", family_name="garcia")
    assert hmac_token(REC, s) == hmac_token(ascii_rec, s)  # NFKD + case fold


def test_key_rotation_changes_tokens(monkeypatch):
    t1 = hmac_token(REC, hmac_sys(monkeypatch, "k1"))
    t2 = hmac_token(REC, hmac_sys(monkeypatch, "k2"))
    assert t1 != t2


def test_missing_key_env_raises(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    s = PprlTokenSystem(name="x", kind="hmac", key_env="NOPE_KEY")
    with pytest.raises(ConfigError, match="customer-controlled"):
        hmac_token(REC, s)


def test_clk_similarity_property(monkeypatch):
    monkeypatch.setenv("TEST_PPRL_KEY", "k")
    s = PprlTokenSystem(name="clk:openhie", kind="clk", key_env="TEST_PPRL_KEY",
                        fields=["family_name", "given_name", "birth_date"])
    import base64

    def bits(rec):
        raw = base64.b64decode(clk_token(rec, s))
        return {i for i, byte in enumerate(raw) for b in range(8) if byte & (1 << b)}

    same = bits(REC)
    typo = bits(dict(REC, family_name="GARCIA"))     # normalization-equal → identical
    other = bits(dict(REC, family_name="NGUYEN", given_name="THI", birth_date="1990-09-09"))
    assert same == typo
    # Dice coefficient: near-duplicate must dwarf a different person
    near = bits(dict(REC, given_name="JOSEF"))       # one-letter drift
    dice = lambda a, b: 2 * len(a & b) / (len(a) + len(b))  # noqa: E731
    assert dice(same, near) > dice(same, other)


def test_generate_tokens_rows_match_pin(monkeypatch):
    from fhirhouse_contracts.schema import FHIRHOUSE_TABLES

    s = hmac_sys(monkeypatch)
    rows = generate_tokens([REC, {"unique_id": None}], [s], write=False)
    assert len(rows) == 1  # record without an id is skipped
    assert set(rows[0]) == set(FHIRHOUSE_TABLES["pprl_tokens"])
    assert rows[0]["deleted"] is False and rows[0]["token_system"] == "hmac-sha256:v1"
