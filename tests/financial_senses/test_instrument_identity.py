"""Instrument identity tests — fail-closed ambiguity, no guessing."""
from __future__ import annotations

from financial_senses.identity import (
    ID_BB_GLOBAL,
    IDENTITY_AMBIGUOUS,
    IDENTITY_CONFLICT,
    IDENTITY_NOT_FOUND,
    IDENTITY_RESOLVED,
    InstrumentIdentity,
    OpenFigiProvider,
    build_mapping_jobs,
    cross_validate_identities,
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


def _job(identifier, id_value, candidates, warning=None, error=None):
    return {
        "identifier": identifier,
        "id_type": {"ticker": "TICKER", "cusip": "ID_CUSIP", "isin": "ID_ISIN", "figi": ID_BB_GLOBAL}.get(identifier),
        "id_value": id_value,
        "candidates": candidates,
        "warning": warning,
        "error": error,
    }


def test_build_mapping_jobs_figi_uses_bb_global():
    jobs = build_mapping_jobs({"figi": "BBG000B9XRY4"})
    assert jobs == [{"idType": ID_BB_GLOBAL, "idValue": "BBG000B9XRY4"}]
    assert ID_BB_GLOBAL == "ID_BB_GLOBAL"


def test_build_mapping_jobs_forwards_narrowing_fields():
    jobs = build_mapping_jobs({"ticker": "AAPL", "exchange": "XNAS", "security_type": "Common Stock"})
    assert jobs[0]["idType"] == "TICKER"
    assert jobs[0]["exchCode"] == "XNAS"
    assert jobs[0]["securityType"] == "Common Stock"


def test_cross_validate_matching_ticker_and_cusip_resolves():
    aapl = _cand("AAPL", "BBG000B9XRY4")
    jobs = [
        _job("ticker", "AAPL", [aapl]),
        _job("cusip", "037833100", [aapl]),
    ]
    ident, notes = cross_validate_identities(jobs, {"ticker": "AAPL", "cusip": "037833100"})
    assert ident.identity_status == IDENTITY_RESOLVED
    assert ident.figi == "BBG000B9XRY4"
    # CUSIP is an asserted input, not an OpenFIGI return.
    assert ident.cusip == "037833100"


def test_cross_validate_conflicting_ticker_and_cusip():
    aapl = _cand("AAPL", "BBG000B9XRY4")
    msft = _cand("MSFT", "BBG000BPH459")
    jobs = [
        _job("ticker", "AAPL", [aapl]),
        _job("cusip", "594918104", [msft]),  # MSFT CUSIP
    ]
    ident, notes = cross_validate_identities(jobs, {"ticker": "AAPL", "cusip": "594918104"})
    assert ident.identity_status == IDENTITY_CONFLICT


def test_cross_validate_two_exchanges_ambiguous():
    aapl_nasdaq = _cand("AAPL", "F1", exchange="XNAS")
    aapl_other = _cand("AAPL", "F2", exchange="XETR")
    jobs = [_job("ticker", "AAPL", [aapl_nasdaq, aapl_other])]
    ident, notes = cross_validate_identities(jobs, {"ticker": "AAPL"})
    assert ident.identity_status == IDENTITY_AMBIGUOUS


def test_cross_validate_explicit_figi_resolves():
    aapl = _cand("AAPL", "BBG000B9XRY4")
    jobs = [_job("figi", "BBG000B9XRY4", [aapl])]
    ident, notes = cross_validate_identities(jobs, {"figi": "BBG000B9XRY4"})
    assert ident.identity_status == IDENTITY_RESOLVED
    assert ident.figi == "BBG000B9XRY4"


def test_cross_validate_unavailable_identifier_notes_partial():
    from financial_senses.identity import IDENTITY_UNVERIFIED

    aapl = _cand("AAPL", "BBG000B9XRY4")
    jobs = [
        _job("ticker", "AAPL", [aapl]),
        _job("cusip", "NOPE", []),  # CUSIP not found
    ]
    ident, notes = cross_validate_identities(jobs, {"ticker": "AAPL", "cusip": "NOPE"})
    # A non-resolving asserted identifier must never yield a clean RESOLVED.
    assert ident.identity_status == IDENTITY_UNVERIFIED
    assert any("cusip" in n for n in notes)


def test_cross_validate_warning_job_not_silently_dropped():
    from financial_senses.identity import IDENTITY_UNVERIFIED

    aapl = _cand("AAPL", "BBG000B9XRY4")
    jobs = [
        _job("ticker", "AAPL", [aapl]),
        _job("cusip", "NOPE", [], warning="No identifier found."),
    ]
    ident, notes = cross_validate_identities(jobs, {"ticker": "AAPL", "cusip": "NOPE"})
    assert ident.identity_status == IDENTITY_UNVERIFIED
    assert any("No identifier found." in n for n in notes)


def test_cross_validate_error_job_not_silently_dropped():
    from financial_senses.identity import IDENTITY_UNVERIFIED

    aapl = _cand("AAPL", "BBG000B9XRY4")
    jobs = [
        _job("ticker", "AAPL", [aapl]),
        _job("cusip", "NOPE", [], error="API rate limit exceeded"),
    ]
    ident, notes = cross_validate_identities(jobs, {"ticker": "AAPL", "cusip": "NOPE"})
    assert ident.identity_status == IDENTITY_UNVERIFIED
    assert any("rate limit" in n for n in notes)


def test_cross_validate_all_jobs_no_result_not_found():
    jobs = [
        _job("ticker", "NOPE", []),
        _job("cusip", "NOPE2", []),
    ]
    ident, notes = cross_validate_identities(jobs, {"ticker": "NOPE", "cusip": "NOPE2"})
    assert ident.identity_status == IDENTITY_NOT_FOUND


def test_provider_conflicting_identifiers_status_conflict():
    aapl = _cand("AAPL", "BBG000B9XRY4")
    msft = _cand("MSFT", "BBG000BPH459")

    def resolver(query):
        return [
            _job("ticker", "AAPL", [aapl]),
            _job("cusip", "594918104", [msft]),
        ]

    p = OpenFigiProvider(resolver=resolver)
    r = p.query("identity.resolve", {"ticker": "AAPL", "cusip": "594918104"})
    assert r.status == "CONFLICT"
    assert r.data["identity"]["identity_status"] == IDENTITY_CONFLICT


def test_provider_matching_identifiers_resolved():
    aapl = _cand("AAPL", "BBG000B9XRY4")

    def resolver(query):
        return [
            _job("ticker", "AAPL", [aapl]),
            _job("cusip", "037833100", [aapl]),
        ]

    p = OpenFigiProvider(resolver=resolver)
    r = p.query("identity.resolve", {"ticker": "AAPL", "cusip": "037833100"})
    assert r.status == "OK"
    assert r.data["identity"]["figi"] == "BBG000B9XRY4"


def test_provider_preserves_job_warning():
    aapl = _cand("AAPL", "BBG000B9XRY4")

    def resolver(query):
        return [_job("ticker", "AAPL", [aapl], warning="ambiguous request")]

    p = OpenFigiProvider(resolver=resolver)
    r = p.query("identity.resolve", {"ticker": "AAPL"})
    # A warning diagnostic is preserved verbatim and surfaced as a warning.
    assert any("ambiguous request" in w for w in r.warnings)
    assert r.data["job_dispositions"][0]["warning"] == "ambiguous request"


def test_provider_warning_job_unverified_not_clean_ok():
    aapl = _cand("AAPL", "BBG000B9XRY4")

    def resolver(query):
        return [
            _job("ticker", "AAPL", [aapl]),
            _job("cusip", "NOPE", [], warning="No identifier found."),
        ]

    p = OpenFigiProvider(resolver=resolver)
    r = p.query("identity.resolve", {"ticker": "AAPL", "cusip": "NOPE"})
    # Not a clean OK: the unresolved CUSIP makes the identity UNVERIFIED.
    assert r.status == "PARTIAL"
    assert r.data["identity"]["identity_status"] == "UNVERIFIED_IDENTIFIER"
    assert any("No identifier found." in w for w in r.warnings)


def test_provider_error_job_unverified_not_clean_ok():
    aapl = _cand("AAPL", "BBG000B9XRY4")

    def resolver(query):
        return [
            _job("ticker", "AAPL", [aapl]),
            _job("cusip", "NOPE", [], error="upstream timeout"),
        ]

    p = OpenFigiProvider(resolver=resolver)
    r = p.query("identity.resolve", {"ticker": "AAPL", "cusip": "NOPE"})
    assert r.status == "PARTIAL"
    assert r.data["identity"]["identity_status"] == "UNVERIFIED_IDENTIFIER"
    assert any("upstream timeout" in w for w in r.warnings)


def test_provider_matching_identifiers_still_resolved():
    aapl = _cand("AAPL", "BBG000B9XRY4")

    def resolver(query):
        return [
            _job("ticker", "AAPL", [aapl]),
            _job("cusip", "037833100", [aapl]),
        ]

    p = OpenFigiProvider(resolver=resolver)
    r = p.query("identity.resolve", {"ticker": "AAPL", "cusip": "037833100"})
    assert r.status == "OK"
    assert r.data["identity"]["identity_status"] == "RESOLVED"
