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
