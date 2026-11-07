"""portfolio_analyzer must survive a holding whose ``asset_type`` is null.

The holdings store carries ``asset_type: null`` for rows a broker sync could not
classify, and ``dict.get("asset_type", "")`` does NOT substitute for a
present-but-None value. ``_get_sector`` called ``.upper()`` on that None and
raised ``AttributeError: 'NoneType' object has no attribute 'upper'``, which
killed the portfolio-maintenance daily/weekly/monthly cadence at stage
[2/10] Analytics (live receipt 2026-11-06T12:30:09Z, overall_status=degraded).

Synthetic fixtures only: no live store, no broker, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from portfolio_analyzer import (  # noqa: E402
    _get_sector,
    analyze_concentration,
    compute_etf_lookathrough,
)


def _holdings():
    """One classified row, one null asset_type, one cash row — the live shape."""
    return [
        {"symbol": "V", "market_value": 30000.0, "asset_type": "Stock"},
        {"symbol": "ZZQQ", "market_value": 10000.0, "asset_type": None},
        {"symbol": "CASH", "market_value": 5000.0, "asset_type": None, "is_cash": True},
    ]


@pytest.mark.parametrize("symbol,expected", [("ZZQQ", "Other"), ("CASH", "Cash")])
def test_get_sector_tolerates_null_asset_type(symbol, expected):
    assert _get_sector(symbol, None) == expected


def test_get_sector_tolerates_missing_asset_type():
    assert _get_sector("ZZQQ", "") == "Other"
    assert _get_sector("ZZQQ") == "Other"


def test_get_sector_still_classifies_known_types():
    assert _get_sector("ZZQQ", "ETF") == "ETF/Fund"
    assert _get_sector("ZZQQ", "Mutual Fund") == "ETF/Fund"
    assert _get_sector("ZZQQ", "Bond") == "Bonds"
    assert _get_sector("V", None) == "Financials"


def test_analyze_concentration_survives_null_asset_type():
    result = analyze_concentration(_holdings(), {})
    sectors = {f["sector"] for f in result["sector_concentration"]}
    # The null-typed row is classified, not dropped and not a crash.
    assert "Other" in sectors


def test_etf_lookthrough_survives_null_asset_type():
    exposure = compute_etf_lookathrough(_holdings(), {})
    assert exposure.get("Other", 0) == pytest.approx(10000.0)
