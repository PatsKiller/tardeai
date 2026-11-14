"""OBS-R1 (operator, live Chrome 2026-11-14): the resting-stop scenario on the Risk loss card.

The card said "Loss if every resting stop fills $14,793 · 0 active, 8 pending activation · active stops
only Not available". Two different measures were spliced into one line, the scenario was summed over the
HELD quantity (V 100.7963) rather than the quantity the broker order COVERS (V 100), and "pending
activation" was named without the broker order state that explains it.

This file pins the producer half: the scenario is over the covered quantity of each resting order, the
active-stop figure keeps its own (held) basis unchanged, and the raw broker order states are published so
the page can explain "pending activation". Synthetic fixtures only; no broker, database or provider calls.
"""
from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
AT = NOW.isoformat()


def _holding(symbol, account, shares, price):
    return {"symbol": symbol, "account": account, "shares": shares, "price": price,
            "market_value": round(shares * price, 2), "day_change": 0, "as_of": AT}


def _broker_stop(symbol, account, stop_price, status, order, qty):
    row = {"account": account, "symbol": symbol, "stop_price": stop_price, "status": status,
           "captured_at": AT, "order_id": order}
    if qty is not None:
        row["qty"] = qty
    return row


def _resolve(tmp_path, holdings, broker):
    return truth.resolve(tmp_path, NOW, inputs={
        "holdings": {"last_repriced": AT, "holdings": holdings},
        "broker_stops": broker, "planned_stops": {}, "companies": {}, "policy": {}, "cio_status": {}})


def test_the_scenario_uses_the_covered_order_quantity_not_the_held_quantity(tmp_path):
    """V holds 100.7963 at 425.76; the broker order covers 100. The scenario must be (425.76-406.94)*100."""
    doc = _resolve(tmp_path,
                   [_holding("V", "fixture_rollover_ira", 100.7963, 425.76)],
                   [_broker_stop("V", "fixture_rollover_ira", 406.94, "pending_activation", "o-v", 100.0)])
    row = doc["positions"]["rows"][0]
    assert row["stop_category"] == "pending_activation"
    assert row["resting_loss_qty"] == 100.0                    # covered, not 100.7963 held
    assert row["loss_at_resting_stop_usd"] == 1882.0           # (425.76 - 406.94) * 100
    assert row["resting_coverage_shortfall_qty"] == 0.7963     # the part of the holding no order covers
    assert doc["positions"]["loss_at_resting_stops_usd"] == 1882.0
    cov = doc["positions"]["resting_loss_coverage"]
    assert cov["basis"].startswith("covered quantity")
    assert cov["shortfalls"] == [{"symbol": "V", "account_id": "fixture_rollover_ira",
                                  "held": 100.7963, "covered": 100.0, "shortfall": 0.7963}]
    assert cov["qty_not_published"] == []


def test_an_over_covering_order_is_capped_at_the_held_quantity(tmp_path):
    doc = _resolve(tmp_path,
                   [_holding("BIG", "fixture_ira", 10, 50)],
                   [_broker_stop("BIG", "fixture_ira", 40, "pending_activation", "o-big", 500.0)])
    row = doc["positions"]["rows"][0]
    assert row["resting_loss_qty"] == 10                        # a stop cannot sell more than is held
    assert row["loss_at_resting_stop_usd"] == 100.0
    assert row["resting_coverage_shortfall_qty"] is None
    assert doc["positions"]["resting_loss_coverage"]["shortfalls"] == []


def test_an_order_without_a_published_quantity_falls_back_and_says_so(tmp_path):
    doc = _resolve(tmp_path,
                   [_holding("NOQ", "fixture_ira", 7, 30)],
                   [_broker_stop("NOQ", "fixture_ira", 25, "pending_activation", "o-noq", None)])
    row = doc["positions"]["rows"][0]
    assert row["resting_loss_qty"] == 7                         # held is the only quantity published
    assert row["loss_at_resting_stop_usd"] == 35.0
    cov = doc["positions"]["resting_loss_coverage"]
    assert cov["qty_not_published"] == ["NOQ"]                  # the basis for this row is stated, not assumed
    assert cov["shortfalls"] == []


def test_the_active_stop_figure_keeps_its_own_basis_and_the_counts_do_not_move(tmp_path):
    """Operator: the 8+1+2 counts and the active-stop figure are correct; OBS-R1 must not change them."""
    doc = _resolve(tmp_path,
                   [_holding("ARMD", "fixture_ira", 10, 100)],
                   [_broker_stop("ARMD", "fixture_ira", 90, "WORKING", "o-armd", 5.0)])
    row = doc["positions"]["rows"][0]
    assert row["stop_category"] == "active"
    assert row["loss_at_stop_usd"] == 100.0                     # held 10 * (100-90): unchanged rule
    assert doc["positions"]["loss_at_stop_usd"] == 100.0
    assert doc["stops"]["active_count"] == 1 and doc["stops"]["pending_count"] == 0


def test_pending_activation_publishes_the_broker_order_state_that_explains_it(tmp_path):
    doc = _resolve(tmp_path,
                   [_holding("SCHW", "fixture_ira", 10, 100), _holding("MAPPED", "fixture_ira", 5, 40)],
                   [_broker_stop("SCHW", "fixture_ira", 90, "AWAITING_STOP_CONDITION", "o-schw", 10.0),
                    _broker_stop("MAPPED", "fixture_ira", 38, "AWAITING_PARENT_ORDER", "o-map", 5.0)])
    assert doc["stops"]["pending_count"] == 2
    states = {s["status"]: s["count"] for s in doc["stops"]["pending_broker_states"]}
    assert states == {"AWAITING_STOP_CONDITION": 1, "AWAITING_PARENT_ORDER": 1}
    # the display state is still the mapped one the counts use
    assert {r["stop_state"] for r in doc["positions"]["rows"]} == {"pending_activation"}


def test_no_pending_row_publishes_an_empty_state_list_not_a_zero(tmp_path):
    doc = _resolve(tmp_path,
                   [_holding("ARMD", "fixture_ira", 10, 100)],
                   [_broker_stop("ARMD", "fixture_ira", 90, "WORKING", "o-armd", 10.0)])
    assert doc["stops"]["pending_broker_states"] == []
