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


# --- LQ-20261107-1689: a just-bought ETF the history store never saw -----------------------
class _Cur:
    """A cursor whose two reads answer from fixed tables; it records every statement and bind it was asked."""

    def __init__(self, profiles, history):
        self.profiles, self.history, self.sql, self.binds = profiles, history, [], []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.binds.append(tuple(params[0]) if params else ())
        self._rows = self.profiles if "symbol_profiles" in sql else self.history

    def fetchall(self):
        return list(self._rows)


def test_a_new_etfs_quote_type_fills_it_when_the_history_has_never_seen_it():
    # The live case: XLV bought 2026-11-09, asset_intelligence_history has no XLV row at all, but
    # symbol_profiles carries yfinance's quote_type=ETF. Before this the class was absent and the row stayed NULL.
    cur = _Cur(profiles=[("XLV", "ETF")], history=[])
    assert ps.load_asset_classes(cur, ["XLV"]) == {"XLV": "etf"}
    plan = {"snapshots": [], "current": [{"symbol": "XLV", "asset_type": None}]}
    assert ps.fill_missing_asset_type(plan, {"XLV": "etf"}) == 1
    assert plan["current"][0]["asset_type"] == "ETF"


def test_history_is_the_fallback_for_symbols_the_profile_does_not_type():
    cur = _Cur(profiles=[("PFE", None)], history=[("PFE", "stock")])
    assert ps.load_asset_classes(cur, ["PFE", "XLV"]) == {"PFE": "stock"}
    # The history read is asked only for what the profile could not answer, never for the whole list.
    assert cur.binds[1] == ("PFE", "XLV")


def test_an_unmapped_quote_type_stays_unknown():
    # INDEX/CURRENCY/NULL are not position classes: no entry, so the position stays NULL rather than guessed.
    cur = _Cur(profiles=[("SPX", "INDEX"), ("EURUSD", "CURRENCY")], history=[])
    assert ps.load_asset_classes(cur, ["SPX", "EURUSD", "ZZZZ"]) == {}
    assert cur.binds[1] == ("EURUSD", "SPX", "ZZZZ") and cur.history == []  # the history had nothing either
