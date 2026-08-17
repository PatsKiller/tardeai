"""Instrument identity tests — fail-closed ambiguity, no guessing."""
from __future__ import annotations

from financial_senses.identity import (
    IDENTITY_AMBIGUOUS,
    IDENTITY_CONFLICT,
    IDENTITY_NOT_FOUND,
    IDENTITY_RESOLVED,
    InstrumentIdentity,
    normalize_ticker,
    resolve_identity,
)


def _cand(ticker, figi, exchange=None, security_type="Common Stock"):
    return {
        "figi": figi,
        "ticker": ticker,
        "name": f"{ticker} Inc.",
        "exchange": exchange or "NASDAQ",
        "security_type": security_type,
        "currency": "USD",
    }


def test_normalize_ticker_share_class():
    assert normalize_ticker("BRK.B") == "BRK/B"
    assert normalize_ticker("BRK-B") == "BRK/B"
    assert normalize_ticker("brk/b") == "BRK/B"


def test_goog_and_googl_remain_distinct():
    assert normalize_ticker("GOOG") != normalize_ticker("GOOGL")


def test_single_candidate_resolves():
    ident = resolve_identity([_cand("AAPL", "BBG000B9XRY4")], {"ticker": "AAPL"})
    assert ident.identity_status == IDENTITY_RESOLVED
    assert ident.figi == "BBG000B9XRY4"


def test_multiple_candidates_ambiguous():
    ident = resolve_identity(
        [_cand("ABC", "F1"), _cand("ABC", "F2")], {"ticker": "ABC"}
    )
    assert ident.identity_status == IDENTITY_AMBIGUOUS


def test_exchange_narrows_ambiguity():
    ident = resolve_identity(
        [_cand("ABC", "F1", exchange="NASDAQ"), _cand("ABC", "F2", exchange="NYSE")],
        {"ticker": "ABC", "exchange": "NYSE"},
    )
    assert ident.identity_status == IDENTITY_RESOLVED
    assert ident.figi == "F2"


def test_security_type_narrows():
    ident = resolve_identity(
        [_cand("ABC", "F1", security_type="Common Stock"), _cand("ABC", "F2", security_type="ADR")],
        {"ticker": "ABC", "security_type": "ADR"},
    )
    assert ident.figi == "F2"


def test_no_candidates_not_found():
    ident = resolve_identity([], {"ticker": "NOPE"})
    assert ident.identity_status == IDENTITY_NOT_FOUND


def test_conflict_with_existing_canonical():
    existing = {"figi": "CANONICAL_FIGI"}
    ident = resolve_identity([_cand("AAPL", "DIFFERENT")], {"ticker": "AAPL"}, existing=existing)
    assert ident.identity_status == IDENTITY_CONFLICT


def test_compose_with_existing_canonical_match():
    existing = {"figi": "BBG000B9XRY4"}
    ident = resolve_identity([_cand("AAPL", "BBG000B9XRY4")], {"ticker": "AAPL"}, existing=existing)
    assert ident.identity_status == IDENTITY_RESOLVED
    assert "canonical_internal" in ident.source_refs


def test_identity_to_dict_roundtrip():
    ident = resolve_identity([_cand("AAPL", "BBG000B9XRY4")], {"ticker": "AAPL"})
    d = ident.to_dict()
    assert d["identity_status"] == IDENTITY_RESOLVED
    assert d["figi"] == "BBG000B9XRY4"
