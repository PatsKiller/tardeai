"""2026-09-15: catalyst_symbol_impact had 0 rows ever; the writer fills it deterministically."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _w():
    spec = importlib.util.spec_from_file_location("csi_writer_t", ROOT / "scripts" / "catalyst_symbol_impact_writer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_direction_from_catalyst_type():
    w = _w()
    assert w.expected_direction("analyst_upgrade") == "UP"
    assert w.expected_direction("earnings_miss") == "DOWN"
    assert w.expected_direction("other") == "NEUTRAL"
    assert w.expected_direction(None) == "NEUTRAL"


def test_portfolio_weights_sum_to_100_and_merge_lots():
    w = _w()
    weights = w.portfolio_weights({"positions": [
        {"symbol": "rtx", "market_value": 3000}, {"symbol": "RTX", "market_value": 1000},
        {"symbol": "LMT", "market_value": 4000}, {"symbol": "CASH", "market_value": 0}]})
    assert weights == {"RTX": 50.0, "LMT": 50.0}


def test_current_holdings_file_shape_and_cash_skipped():
    w = _w()
    weights = w.portfolio_weights({"holdings": [
        {"symbol": "RTX", "market_value": 750, "is_cash": False},
        {"symbol": "SWVXX", "market_value": 9000, "is_cash": True},
        {"symbol": "LMT", "market_value": 250}]})
    assert weights == {"RTX": 75.0, "LMT": 25.0}


def test_bad_holdings_shape_is_empty_not_an_error():
    w = _w()
    assert w.portfolio_weights({}) == {} and w.portfolio_weights({"positions": "x"}) == {}


def test_default_is_dry_run_and_insert_is_idempotent():
    src = (ROOT / "scripts" / "catalyst_symbol_impact_writer.py").read_text(encoding="utf-8")
    assert 'ap.add_argument("--apply", action="store_true")' in src
    assert "NOT EXISTS (SELECT 1 FROM catalyst_symbol_impact csi" in src
    assert "conn.rollback()" in src
