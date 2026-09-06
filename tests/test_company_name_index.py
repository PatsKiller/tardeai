"""Company names come from the broker feed. Nothing here is invented.

The operator's constraint, and it is correct: do not hand-roll a ticker-to-name
map. The name comes from the SAME authoritative record as the CUSIP — Schwab
`/marketdata/v1/instruments`, already swept to disk:

    "V":   {"description": "VISA INC A",           "identifiers": {"cusip": "92826C839"}}
    "NOC": {"description": "NORTHROP GRUMMAN COR", "identifiers": {"cusip": "666807102"}}

4,997 instruments, 4,997 with a description. The data was on disk and had simply
never been indexed, so "Visa" was unresolvable while "V" resolved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import company_name_index as C  # noqa: E402

SRC = (ROOT / "scripts" / "lib" / "company_name_index.py").read_text(encoding="utf-8")

FEED = {"instruments": {
    "V":   {"description": "VISA INC A", "identifiers": {"cusip": "92826C839"}},
    "NOC": {"description": "NORTHROP GRUMMAN COR", "identifiers": {"cusip": "666807102"}},
    "JPM": {"description": "JPMORGAN CHASE & CO", "identifiers": {"cusip": "46625H100"}},
    "KO":  {"description": "COCA COLA CO", "identifiers": {"cusip": "191216100"}},
    "APLE": {"description": "APPLE HOSPITALITY REIT", "identifiers": {"cusip": "03784Y200"}},
    "AAPL": {"description": "APPLE INC", "identifiers": {"cusip": "037833100"}},
}}


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    """Never depend on which symbols happen to be swept."""
    monkeypatch.setattr(C, "_instruments", lambda: FEED["instruments"])
    C.refresh()
    yield
    C.refresh()


# ── normalisation ──────────────────────────────────────────────────────────

def test_legal_suffixes_and_share_class_are_stripped():
    assert C.normalize_name("VISA INC A") == "VISA"
    assert C.normalize_name("JPMORGAN CHASE & CO") == "JPMORGAN CHASE"


def test_truncated_broker_forms_normalise():
    """`COR` is Schwab's truncation of CORPORATION, not a typo — the field is
    fixed width, and a raw compare fails on exactly the names operators type."""
    assert C.normalize_name("NORTHROP GRUMMAN COR") == "NORTHROP GRUMMAN"


def test_a_suffix_inside_a_name_survives():
    """'CO' in COCA COLA must not be eaten. Suffixes strip from the END only."""
    assert C.normalize_name("COCA COLA CO") == "COCA COLA"
    assert "COCA COLA" in C.normalize_name("COCA COLA CO")


# ── resolution ─────────────────────────────────────────────────────────────

def test_the_operators_word_resolves():
    r = C.resolve_name("Visa")
    assert r["symbol"] == "V"
    assert r["cusip"] == "92826C839"
    assert r["source"] == "schwab_instruments"


def test_case_and_legal_form_do_not_matter():
    for q in ("visa", "VISA INC", "Visa Inc A"):
        assert C.resolve_name(q)["symbol"] == "V"


def test_multiword_names_resolve():
    assert C.resolve_name("Northrop Grumman")["symbol"] == "NOC"
    assert C.resolve_name("JPMorgan Chase")["symbol"] == "JPM"


def test_an_unknown_name_is_unresolved_not_guessed():
    assert C.resolve_name("Nonesuch Holdings") is None


def test_ambiguity_returns_none_rather_than_picking():
    """A wrong symbol on a financial question is worse than no symbol: it attaches
    the operator's intent to the wrong issuer and every join inherits the error."""
    monkey = {"AAA": {"description": "ACME CORP", "identifiers": {"cusip": "1"}},
              "BBB": {"description": "ACME INC", "identifiers": {"cusip": "2"}}}
    import lib.company_name_index as M
    orig = M._instruments
    M._instruments = lambda: monkey
    M.refresh()
    try:
        assert M.resolve_name("Acme") is None
    finally:
        M._instruments = orig
        M.refresh()


def test_a_one_word_query_must_not_swallow_a_longer_company():
    """'Apple' is APPLE INC exactly; it must not collapse to APPLE HOSPITALITY."""
    assert C.resolve_name("Apple")["symbol"] == "AAPL"


def test_too_short_is_not_a_lookup():
    for q in ("", "a", "Co", None):
        assert C.resolve_name(q) is None


# ── it must stay sourced, not invented ─────────────────────────────────────

def test_no_hardcoded_symbol_to_name_mapping():
    """The whole point: if the broker does not carry a name, neither do we."""
    body = SRC.split('"""', 2)[-1]
    for invented in ('"VISA"', "'VISA'", '"AAPL"', "'AAPL'", '"NOC"', "'NOC'"):
        assert invented not in body, f"a company mapping was hardcoded: {invented}"


def test_the_source_is_the_broker_instrument_feed():
    assert "schwab_instrument_evidence" in SRC
    assert C.resolve_name("Visa")["source"] == "schwab_instruments"


def test_no_model_runs_here():
    low = SRC.lower()
    for banned in ("openai", "anthropic", "deepseek", "grok", "prompt", "completion"):
        assert banned not in low
