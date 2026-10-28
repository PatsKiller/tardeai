"""Stop desks (boards 3, 14, 15): stop categories, resting-stop distance/loss and Defense "Your book".

Synthetic fixture tickers and accounts only. Display-only: no broker call, no store write.
"""
from datetime import datetime, timezone

from scripts.lib import cio_truth as truth
from scripts.lib import desks_a as desk

NOW = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
AT = NOW.isoformat()


def _holding(symbol, account, shares, price):
    return {"symbol": symbol, "account": account, "shares": shares, "price": price,
            "market_value": round(shares * price, 2), "day_change": 0, "as_of": AT}


def _stop(symbol, account, price, status, order):
    return {"account": account, "symbol": symbol, "stop_price": price, "status": status,
            "captured_at": AT, "order_id": order, "qty": 1}


def _doc(tmp_path):
    holdings = {"last_repriced": AT, "holdings": [
        _holding("ACTV", "fixture_ira", 10, 100),    # active broker stop
        _holding("PEND", "fixture_ira", 20, 50),     # resting, pending activation
        _holding("FILD", "fixture_roth", 5, 40),     # stop filled, holdings not yet synced
        _holding("UNKN", "fixture_roth", 4, 60),     # stop read without a state
        _holding("PLAN", "fixture_ira", 3, 80),      # planned level only
        _holding("NONE", "fixture_ira", 2, 90),      # no stop at all
        _holding("DUST", "fixture_ira", 1, 5),       # below the counted threshold
    ]}
    broker = [_stop("ACTV", "fixture_ira", 90, "WORKING", "o1"), _stop("PEND", "fixture_ira", 45, "pending_activation", "o2"),
              _stop("FILD", "fixture_roth", 38, "FILLED", "o3"), _stop("UNKN", "fixture_roth", 55, None, "o4")]
    planned = {"PLAN:fixture_ira": {"account": "fixture_ira", "stop": 60, "set_date": "2026-10-01"}}
    return truth.resolve(tmp_path, NOW, inputs={"holdings": holdings, "broker_stops": broker, "planned_stops": planned,
                                                "companies": {}, "policy": {}, "cio_status": {}})


def test_every_counted_position_has_one_stop_category(tmp_path):
    doc = _doc(tmp_path)
    rows = {r["symbol"]: r for r in doc["positions"]["rows"]}
    assert {s: rows[s]["stop_category"] for s in ("ACTV", "PEND", "FILD", "UNKN", "PLAN", "NONE")} == {
        "ACTV": "active", "PEND": "pending_activation", "FILD": "filled", "UNKN": "unknown", "PLAN": "planned", "NONE": "none"}
    assert rows["DUST"]["counted"] is False and all(rows[s]["counted"] for s in ("ACTV", "PEND", "FILD", "UNKN", "PLAN", "NONE"))
    bd = doc["positions"]["stop_breakdown"]
    assert {k: v["count"] for k, v in bd.items()} == {"active": 1, "pending_activation": 1, "filled": 1, "unknown": 1,
                                                      "planned": 1, "none": 1}
    assert bd["planned"]["value_usd"] == 240 and bd["none"]["value_usd"] == 180
    assert sum(v["count"] for v in bd.values()) == doc["stops"]["position_count"]


def test_resting_pending_stop_has_distance_and_loss_but_is_not_protection(tmp_path):
    doc = _doc(tmp_path)
    rows = {r["symbol"]: r for r in doc["positions"]["rows"]}
    pend = rows["PEND"]
    assert pend["broker_protected"] is False and pend["distance_to_stop_pct"] is None and pend["loss_at_stop_usd"] is None
    assert pend["resting_stop_distance_pct"] == 10.0 and pend["loss_at_resting_stop_usd"] == 100.0
    assert rows["ACTV"]["resting_stop_distance_pct"] == 10.0 and rows["ACTV"]["loss_at_resting_stop_usd"] == 100.0
    assert rows["PLAN"]["planned_stop_distance_pct"] == 25.0 and rows["PLAN"]["loss_at_resting_stop_usd"] is None
    for s in ("FILD", "UNKN", "NONE"):
        assert rows[s]["resting_stop_distance_pct"] is None and rows[s]["loss_at_resting_stop_usd"] is None
    pos = doc["positions"]
    assert pos["loss_at_stop_usd"] == 100.0           # active stops only (unchanged rule)
    assert pos["loss_at_resting_stops_usd"] == 200.0  # active + pending, shown beside it
    assert doc["stops"]["active_count"] == 1 and doc["stops"]["pending_count"] == 1


def test_no_broker_table_keeps_breakdown_unknown(tmp_path):
    doc = truth.resolve(tmp_path, NOW, inputs={"holdings": {"last_repriced": AT, "holdings": [_holding("ACTV", "fixture_ira", 10, 100)]},
                                               "broker_stops": None, "planned_stops": {}, "companies": {}, "policy": {}, "cio_status": {}})
    assert doc["positions"]["stop_breakdown"] is None and doc["positions"]["loss_at_resting_stops_usd"] is None


def test_defense_book_uses_the_same_categories_and_links_each_position(tmp_path):
    doc = _doc(tmp_path)
    out = desk.defense_payload(root=tmp_path, now=NOW, truth=doc, states={})
    book = next(p for p in out["tabs"]["your-book"]["panels"] if p["id"] == "book")
    rows = {r["id"]: r for r in book["rows"]}
    assert rows["bk-unprot"]["value"] == "2 (1 planned level only)"
    assert rows["bk-heat"]["value"] == "$420"
    assert rows["bk-pending"]["value"] == "1"
    assert rows["bk-filled"]["value"] == "1 · FILD"
    assert rows["bk-unknown"]["value"] == "1 · UNKN"
    assert rows["bk-PEND-fixture_ira"]["value"].endswith("stop pending activation")
    assert rows["bk-FILD-fixture_roth"]["value"].endswith("stop filled · awaiting holdings sync")
    assert rows["bk-NONE-fixture_ira"]["value"].endswith("no stop")
    assert "bk-DUST-fixture_ira" not in rows
    assert rows["bk-PEND-fixture_ira"]["detail"]["href"] == "/risk?tab=exposure&detail=position:fixture_ira:PEND"
    dist = dict((f["label"], f["value"]) for f in rows["bk-PEND-fixture_ira"]["detail"]["fields"])["Distance to stop"]
    assert dist.startswith("10")


def test_desk_times_are_eastern_and_naive_lock_shows_date_only():
    assert desk._date("2026-10-23T21:55:00+00:00") == "Fri Oct 23 17:55 ET"
    assert desk._date("2026-07-18T22:57") == "2026-07-18"
