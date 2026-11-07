"""LQ-20261107-72 ASSET_TYPE_FILL."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import portfolio_analyzer as pa  # noqa: E402
import positions_sync as ps  # noqa: E402


def _plan():
    rows = lambda: [{"symbol": "SCHG", "asset_type": None}, {"symbol": "PFE", "asset_type": None},
                    {"symbol": "AMANX", "asset_type": None}, {"symbol": "ZZZZ", "asset_type": None},
                    {"symbol": "CASH", "asset_type": "CASH"}, {"symbol": "NVDA", "asset_type": "EQUITY"}]
    return {"snapshots": rows(), "current": rows()}


def test_fill_uses_held_classification_and_leaves_unknown_null():
    plan = _plan()
    n = ps.fill_missing_asset_type(plan, {"SCHG": "etf", "PFE": "stock", "AMANX": "mutual_fund"})
    got = {r["symbol"]: r["asset_type"] for r in plan["current"]}
    assert got == {"SCHG": "ETF", "PFE": "EQUITY", "AMANX": "MUTUAL_FUND", "ZZZZ": None,
                   "CASH": "CASH", "NVDA": "EQUITY"}
    assert n == 3
    assert {r["symbol"]: r["asset_type"] for r in plan["snapshots"]}["SCHG"] == "ETF"


def test_broker_value_is_never_overwritten():
    plan = {"snapshots": [], "current": [{"symbol": "SCHG", "asset_type": "EQUITY"}]}
    ps.fill_missing_asset_type(plan, {"SCHG": "etf"})
    assert plan["current"][0]["asset_type"] == "EQUITY"


def test_get_sector_survives_none_asset_type():
    # old: AttributeError 'NoneType' object has no attribute 'upper'
    assert pa._get_sector("ZZZZ", None) == "Other"
    assert pa._get_sector("SCHG", None) in ("ETF/Fund", "Technology", "Other")


def test_analyze_concentration_with_null_asset_types():
    holdings = [{"symbol": "ZZZZ", "asset_type": None, "market_value": 1000.0},
                {"symbol": "YYYY", "asset_type": None, "market_value": 500.0, "is_fund": False}]
    pa.compute_etf_lookathrough(holdings, {})
    assert pa.analyze_concentration(holdings, {}) is not None
