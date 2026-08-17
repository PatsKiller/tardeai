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


def test_factor_similarity_shared():
    a = {"size": {"loading": 1.0, "source": "verified_regression"}}
    b = {"size": {"loading": 1.0, "source": "verified_regression"}}
    r = factor_similarity(a, b)
    assert r["cosine_similarity"] == 1.0


def test_factor_similarity_unsourced_is_unavailable():
    a = {"size": {"loading": 1.0}}  # no source
    b = {"size": {"loading": 1.0}}
    r = factor_similarity(a, b)
    assert r["state"] == UNAVAILABLE


def test_overlap_report_has_transparent_components():
    a = {
        "holdings": [{"symbol": "AAPL", "weight": 1.0}],
        "returns": [1, 2, 3],
        "sectors": {"tech": 1.0},
        "factors": {"size": {"loading": 1.0, "source": "verified_regression"}},
    }
    b = {
        "holdings": [{"symbol": "AAPL", "weight": 1.0}],
        "returns": [1, 2, 3],
        "sectors": {"tech": 1.0},
        "factors": {"size": {"loading": 1.0, "source": "verified_regression"}},
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


def test_provider_provenanced_inputs_propagate_fact():
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
    assert r.facts
    fact = r.facts[0]
    assert fact.key == "holdings_jaccard"
    assert fact.source_type == "APPROVED_MARKET_DATA"
    assert fact.as_of == "2024-06-01"
    assert fact.quality == "MEDIUM"
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
