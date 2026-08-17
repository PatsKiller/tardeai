"""Factor / overlap intelligence tests."""
from __future__ import annotations

from financial_senses.factor_exposure import (
    UNAVAILABLE,
    factor_similarity,
    holdings_overlap,
    overlap_report,
    return_correlation,
    sector_overlap,
)


def test_holdings_overlap_identical():
    a = [{"symbol": "AAPL", "weight": 0.6}, {"symbol": "MSFT", "weight": 0.4}]
    b = [{"symbol": "AAPL", "weight": 0.5}, {"symbol": "MSFT", "weight": 0.5}]
    r = holdings_overlap(a, b)
    assert r["jaccard"] == 1.0
    assert r["overlap_by_weight"] == 0.9


def test_holdings_overlap_disjoint():
    a = [{"symbol": "AAPL", "weight": 1.0}]
    b = [{"symbol": "TSLA", "weight": 1.0}]
    r = holdings_overlap(a, b)
    assert r["jaccard"] == 0.0


def test_return_correlation_perfect():
    r = return_correlation([1, 2, 3, 4], [2, 4, 6, 8])
    assert r["correlation"] == 1.0


def test_return_correlation_insufficient_history():
    r = return_correlation([1], [2])
    assert r["state"] == UNAVAILABLE


def test_sector_overlap():
    r = sector_overlap({"tech": 0.7, "fin": 0.3}, {"tech": 0.5, "energy": 0.5})
    assert r["overlap_by_weight"] == 0.5
    assert r["common_sectors"] == ["tech"]


def _loading(loading=1.0, source="verified_regression", quality="HIGH"):
    """A fully-specified factor loading per the module's governed contract."""
    return {
        "loading": loading,
        "source": source,
        "method": "ols",
        "window": "3y",
        "as_of": "2024-06-01",
        "quality": quality,
    }


def test_factor_similarity_shared():
    a = {"size": _loading()}
    b = {"size": _loading()}
    r = factor_similarity(a, b)
    assert r["cosine_similarity"] == 1.0


def test_factor_similarity_unsourced_is_unavailable():
    a = {"size": {"loading": 1.0}}  # no source
    b = {"size": {"loading": 1.0}}
    r = factor_similarity(a, b)
    assert r["state"] == UNAVAILABLE


def test_factor_similarity_missing_metadata_is_unavailable():
    # source + loading alone is NOT a governed loading: method/window/as_of/
    # quality are required and their absence must be UNAVAILABLE, not fabricated.
    a = {"size": {"loading": 1.0, "source": "verified_regression"}}
    b = {"size": {"loading": 1.0, "source": "verified_regression"}}
    r = factor_similarity(a, b)
    assert r["state"] == UNAVAILABLE
    assert r["cosine_similarity"] is None


def test_factor_similarity_invalid_quality_is_unavailable():
    a = {"size": _loading(quality="NOT_A_GRADE")}
    b = {"size": _loading()}
    r = factor_similarity(a, b)
    assert r["state"] == UNAVAILABLE


def test_overlap_report_has_transparent_components():
    a = {
        "holdings": [{"symbol": "AAPL", "weight": 1.0}],
        "returns": [1, 2, 3],
        "sectors": {"tech": 1.0},
        "factors": {"size": _loading()},
    }
    b = {
        "holdings": [{"symbol": "AAPL", "weight": 1.0}],
        "returns": [1, 2, 3],
        "sectors": {"tech": 1.0},
        "factors": {"size": _loading()},
    }
    r = overlap_report(a, b)
    assert set(r.keys()) == {
        "holdings_overlap",
        "return_correlation",
        "sector_overlap",
        "factor_similarity",
    }


def test_holdings_overlap_missing_both_unavailable():
    r = holdings_overlap(None, None)
    assert r["state"] == UNAVAILABLE
    assert "jaccard" not in r


def test_holdings_overlap_missing_one_side_unavailable():
    r = holdings_overlap([{"symbol": "AAPL", "weight": 1.0}], None)
    assert r["state"] == UNAVAILABLE
    assert "jaccard" not in r


def test_holdings_overlap_empty_list_unavailable():
    r = holdings_overlap([], [])
    assert r["state"] == UNAVAILABLE


def test_sector_overlap_missing_unavailable():
    r = sector_overlap(None, {"tech": 0.5})
    assert r["state"] == UNAVAILABLE
    assert "overlap_by_weight" not in r


def test_provider_raw_inputs_not_promoted_to_fact():
    from financial_senses.factor_exposure import FactorOverlapProvider

    p = FactorOverlapProvider()
    r = p.query("factor.overlap", {
        "instrument_a": {"holdings": [{"symbol": "AAPL", "weight": 0.1}]},
        "instrument_b": {"holdings": [{"symbol": "AAPL", "weight": 0.08}]},
    })
    # Unsourced caller inputs must NOT become an APPROVED_MARKET_DATA FACT.
    assert not r.facts
    assert r.estimates
    assert r.estimates[0].source_type == "MODEL_INFERENCE"
    assert r.validate() == []


def test_provider_self_asserted_metadata_cannot_mint_fact():
    # A caller can label holdings APPROVED_MARKET_DATA and add as_of/quality, but
    # bare asserted metadata is not demonstrated provenance and must NOT cross the
    # ModelEstimate -> Fact boundary.
    from financial_senses.factor_exposure import FactorOverlapProvider

    p = FactorOverlapProvider()
    r = p.query("factor.overlap", {
        "instrument_a": {
            "holdings": [{"symbol": "AAPL", "weight": 0.1}],
            "source_type": "APPROVED_MARKET_DATA",
            "as_of": "2024-06-01",
            "quality": "MEDIUM",
        },
        "instrument_b": {
            "holdings": [{"symbol": "AAPL", "weight": 0.08}],
            "source_type": "APPROVED_MARKET_DATA",
            "as_of": "2024-06-01",
            "quality": "MEDIUM",
        },
    })
    assert not r.facts
    assert r.estimates
    assert r.validate() == []


def test_provider_validated_upstream_provenance_propagates_fact():
    from financial_senses.factor_exposure import FactorOverlapProvider

    prov = {
        "source_type": "APPROVED_MARKET_DATA",
        "source_ids": ["sec_13f_table", "canonical_holdings_v2"],
        "as_of": "2024-06-01",
        "quality": "MEDIUM",
        "authority": "READ_ONLY_ADVISORY",
    }
    p = FactorOverlapProvider()
    r = p.query("factor.overlap", {
        "instrument_a": {"holdings": [{"symbol": "AAPL", "weight": 0.1}], "provenance": prov},
        "instrument_b": {"holdings": [{"symbol": "AAPL", "weight": 0.08}], "provenance": prov},
    })
    assert r.facts
    fact = r.facts[0]
    assert fact.key == "holdings_jaccard"
    assert fact.source_type == "APPROVED_MARKET_DATA"
    assert fact.as_of == "2024-06-01"
    assert fact.quality == "MEDIUM"
    assert "sec_13f_table" in fact.source_ids
    assert r.validate() == []


def test_provider_incomplete_provenance_not_promoted():
    # A provenance envelope missing immutable source_ids must not mint a Fact.
    from financial_senses.factor_exposure import FactorOverlapProvider

    prov = {
        "source_type": "APPROVED_MARKET_DATA",
        "as_of": "2024-06-01",
        "quality": "MEDIUM",
        "authority": "READ_ONLY_ADVISORY",
        # source_ids intentionally absent
    }
    p = FactorOverlapProvider()
    r = p.query("factor.overlap", {
        "instrument_a": {"holdings": [{"symbol": "AAPL", "weight": 0.1}], "provenance": prov},
        "instrument_b": {"holdings": [{"symbol": "AAPL", "weight": 0.08}], "provenance": prov},
    })
    assert not r.facts
    assert r.estimates
    assert r.validate() == []


def test_provider_missing_holdings_partial_not_fact():
    from financial_senses.factor_exposure import FactorOverlapProvider

    p = FactorOverlapProvider()
    r = p.query("factor.overlap", {
        "instrument_a": {"holdings": None},
        "instrument_b": {"holdings": None},
    })
    assert r.status == "PARTIAL"
    assert not r.facts
    assert r.validate() == []
