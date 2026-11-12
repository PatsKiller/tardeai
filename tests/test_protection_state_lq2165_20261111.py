"""LQ-20261107-2165 (Portfolio G1): the backend emits one protection_state per holdings row.

Synthetic fixtures only. PROTECTED | GAP | UNKNOWN | EXEMPT, each with reason, source and as_of.
"""
from datetime import datetime, timezone

import pytest

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 11, 11, 23, 0, tzinfo=timezone.utc)
CAPTURED = "2026-11-11T22:55:00+00:00"
SCHWAB, MOOMOO = "schwab_synth_taxable", "moomoo_synth"


def stop_row(account=SCHWAB, symbol="SYNA", status="pending_activation", captured=CAPTURED, price=90.0):
    return {"account": account, "symbol": symbol, "order_id": f"o-{symbol}", "order_type": "STOP",
            "stop_price": price, "qty": 10, "status": status, "captured_at": captured}


def hold(account, symbol, value, **extra):
    return {"account": account, "symbol": symbol, "shares": 10, "price": value / 10, "market_value": value,
            "day_change": 0, **extra}


def resolve(holdings, stops, tmp_path):
    return truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"as_of": NOW.isoformat(), "generated_at": NOW.isoformat(), "holdings": holdings},
        "broker_stops": stops, "stop_fills": {}, "companies": {}, "policy": {}, "planned_stops": {}, "cio_status": {}})


def by_symbol(document):
    return {r["symbol"]: r for r in document["stops"]["rows"]}


def test_pending_activation_resting_gtc_is_protected(tmp_path):
    row = by_symbol(resolve([hold(SCHWAB, "SYNA", 5000)], [stop_row()], tmp_path))["SYNA"]
    assert row["protection_state"] == "PROTECTED"
    p = row["protection"]
    assert p["counted"] is True and p["source"] == "broker_resting" and p["as_of"] and "pending" in p["reason"].lower()


def test_active_stop_is_protected(tmp_path):
    row = by_symbol(resolve([hold(SCHWAB, "SYNA", 5000)], [stop_row(status="working")], tmp_path))["SYNA"]
    assert row["protection_state"] == "PROTECTED"


def test_broker_with_no_stop_read_source_is_unknown_not_a_gap(tmp_path):
    row = by_symbol(resolve([hold(MOOMOO, "SYNB", 5000)], [stop_row()], tmp_path))["SYNB"]
    assert row["protection_state"] == "UNKNOWN"
    assert row["protection"]["cause"] == "No Stop Read"
    assert row["protection"]["state"] != "GAP"


def test_unreadable_store_is_unknown(tmp_path):
    row = by_symbol(resolve([hold(SCHWAB, "SYNA", 5000)], None, tmp_path))["SYNA"]
    assert row["protection_state"] == "UNKNOWN"
    assert row["protection"]["cause"] == "Stop Read Failed"


def test_stale_observation_is_unknown_not_protected(tmp_path):
    row = by_symbol(resolve([hold(SCHWAB, "SYNA", 5000)], [stop_row(captured="2026-10-20T14:00:00+00:00")], tmp_path))["SYNA"]
    assert row["protection_state"] == "UNKNOWN"
    assert row["protection"]["cause"] == "Stop State Unproven"


def test_good_read_and_no_stop_is_gap(tmp_path):
    document = resolve([hold(SCHWAB, "SYNA", 5000), hold(SCHWAB, "SYNC", 5000)], [stop_row()], tmp_path)
    assert by_symbol(document)["SYNC"]["protection_state"] == "GAP"
    assert by_symbol(document)["SYNA"]["protection_state"] == "PROTECTED"


@pytest.mark.parametrize("symbol,extra,kind", [
    ("CASH", {"is_cash": True}, "cash"),
    ("SPAXX", {}, "cash"),  # portfolio_positions.is_cash already treats the Fidelity core fund as cash
    ("SWVXX", {}, "money-market fund"),
    ("SYNM", {"asset_type": "Money Market Fund"}, "money-market fund"),
    ("SYNS", {"industry": "Sweep vehicle"}, "sweep vehicle"),
])
def test_cash_mmf_and_sweep_are_exempt(symbol, extra, kind):
    out = truth.protection_for({"account_id": SCHWAB, "symbol": symbol, "market_value": 5000, "stop_state": "none",
                                "stop_source": "none", **extra}, broker_available=True)
    assert out["protection_state"] == "EXEMPT" and kind in out["protection"]["reason"]


@pytest.mark.parametrize("extra", [{"asset_type": "ETF"}, {"asset_type": "Closed-End Fund"},
                                   {"asset_type": "Mutual Fund"}, {"asset_type": "Equity"}])
def test_etf_cef_mutual_fund_and_stock_are_never_exempt(extra):
    out = truth.protection_for({"account_id": SCHWAB, "symbol": "SYNX", "market_value": 5000, "stop_state": "none",
                                "stop_source": "none", **extra}, broker_available=True)
    assert out["protection_state"] == "GAP"


def test_under_100_dollars_is_listed_with_its_state_but_not_counted(tmp_path):
    row = by_symbol(resolve([hold(SCHWAB, "SYND", 60)], [stop_row()], tmp_path))["SYND"]
    assert row["protection_state"] == "GAP"
    assert row["protection"]["counted"] is False


def test_holdings_payload_rows_carry_the_state_including_cash(tmp_path):
    document = resolve([hold(SCHWAB, "SYNA", 5000), hold(SCHWAB, "CASH", 900, is_cash=True)], [stop_row()], tmp_path)
    out = truth.holdings_payload({"holdings": []}, document=document)
    states = {r["symbol"]: r["protection_state"] for r in out["holdings"]}
    assert states == {"SYNA": "PROTECTED", "CASH": "EXEMPT"}
