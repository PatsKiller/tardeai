"""Risk snapshot follows live holdings, not the pre-market risk_management.json (operator 2026-10-24: the Risk page
showed NAVN after it was sold, ZQBL 600 sh vs 700 held, ZQAR missing). Broker resting stops win over planned stops."""
import json
import os
import time

import pytest

from scripts.lib.data_broker import risk_snapshot as rs


def _write(path, doc, mtime):
    path.write_text(json.dumps(doc))
    os.utime(path, (mtime, mtime))


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "STATE_DIR", tmp_path)
    now = time.time()
    _write(tmp_path / "risk_management.json", {"positions": [
        {"symbol": "NAVN", "account": "schwab_rollover_ira", "price": 27.05, "market_value": 40575.0, "stop_price": 24.31},
        {"symbol": "ZQBL", "account": "schwab_rollover_ira", "price": 146.03, "market_value": 262854.0}]}, now - 36000)
    _write(tmp_path / "holdings.json", {"portfolio_totals": {"total_value": 150000.0}, "holdings": [
        {"symbol": "ZQBL", "account": "schwab_rollover_ira", "price": 147.72, "shares": 2100, "market_value": 310212.0},
        {"symbol": "ZQAR", "account": "schwab_rollover_ira", "price": 7.77, "shares": 3000, "market_value": 23310.0},
        {"symbol": "ZQCE", "account": "schwab_roth", "price": 408.0, "shares": 391.4955, "market_value": 159730.2},
        {"symbol": "ZQAF", "account": "schwab_roth", "price": 1.0, "shares": 15000, "market_value": 15000.0, "is_cash": True}]}, now - 60)
    _write(tmp_path / "stops.json", {}, now - 60)
    return tmp_path


def test_positions_follow_live_holdings_and_broker_stops(state, monkeypatch):
    broker = [
        {"account": "schwab_rollover_ira", "symbol": "ZQAR", "stop_price": 7.07, "captured_at": "2026-10-23T20:55Z", "status": "pending_activation"},
        {"account": "schwab_roth_ira", "symbol": "ZQCE", "stop_price": 399.82, "captured_at": "2026-10-23T20:55Z", "status": "WORKING"}]
    def query(sql, params=None, **kw):
        return broker if "FROM stop_last_known" in sql else []
    snap = rs.build_risk_snapshot(db_query=query)
    assert snap["positions_basis"] == "holdings_live" and snap["errors"] == []
    pos = {(p["symbol"], p["account"]): p for p in snap["positions"]}
    assert ("NAVN", "schwab_rollover_ira") not in pos            # sold: gone with live holdings
    assert pos[("ZQBL", "schwab_rollover_ira")]["shares"] == 2100  # live quantity, not 1800
    assert pos[("ZQAR", "schwab_rollover_ira")]["stop_price"] == 7.07
    assert pos[("ZQAR", "schwab_rollover_ira")]["stop_source"] == "broker_resting"
    assert pos[("ZQAR", "schwab_rollover_ira")]["stop_state"] == "pending_activation"
    assert pos[("ZQAR", "schwab_rollover_ira")]["broker_protected"] is False
    assert pos[("ZQCE", "schwab_roth")]["stop_price"] == 399.82       # roth alias joins the broker store
    assert pos[("ZQBL", "schwab_rollover_ira")]["stop_price"] is None


def test_falls_back_to_stored_file_when_holdings_are_older(state):
    os.utime(state / "holdings.json", (time.time() - 90000, time.time() - 90000))
    snap = rs.build_risk_snapshot()
    assert snap["positions_basis"] == "risk_management_file"
    assert {p["symbol"] for p in snap["positions"]} == {"NAVN", "ZQBL"}
