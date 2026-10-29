"""Home Protection stop clock (operator phone, 2026-10-25). Synthetic data only.

* The stop clock was min(stop_captured_at) over every row, including a planned stops.json level from months
  earlier, so Home said the stops were half a year old while the broker read was two days old.
* A stale read never produced a gap unless the broker table was missing.
* A broker stop that FILLED while the position is still in holdings (the sale is not yet in the holdings sync) was
  shown as "No active broker stop observed".
"""

from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

CONTRACT = {"open_h": 0.25, "closed_h": 72.0}
SUNDAY = datetime(2031, 3, 9, 18, 0, tzinfo=timezone.utc)      # Sun 14:00 ET
TUESDAY = datetime(2031, 3, 11, 15, 0, tzinfo=timezone.utc)    # Tue 11:00 ET, session open
FRIDAY_READ = "2031-03-07T20:55:00-05:00"                      # Fri 20:55 ET


def _resolve(now, broker, planned=None, contract=CONTRACT, tmp=None):
    holdings = {"last_repriced": FRIDAY_READ, "portfolio_totals": {"total_value": 1200, "day_change": 0}, "holdings": [
        {"symbol": s, "account": "schwab_roth", "shares": 10, "price": px, "market_value": px * 10, "day_change": 0,
         "as_of": FRIDAY_READ} for s, px in (("AAA", 50.0), ("BBB", 40.0), ("CCC", 30.0))]}
    inputs = {"holdings": holdings, "broker_stops": broker, "planned_stops": planned or {}, "companies": {},
              "policy": {}, "cio_status": {}}
    if contract is not None:
        inputs["stop_freshness"] = contract
    return truth.resolve(tmp, now, inputs=inputs)


def _broker(at=FRIDAY_READ):
    return [
        {"account": "schwab_roth", "symbol": "AAA", "order_id": "1", "stop_price": 45.0, "qty": 10, "status": "WORKING", "captured_at": at},
        {"account": "schwab_roth", "symbol": "BBB", "order_id": "2", "stop_price": 41.0, "qty": 10, "status": "FILLED", "captured_at": at},
    ]


def _stops(doc):
    return doc["stops"]


def test_clock_uses_broker_reads_not_planned_levels(tmp_path):
    planned = {"CCC:acct_a": {"account": "schwab_roth", "stop_price": 25.0, "set_date": "2030-09-01"}}
    stops = _stops(_resolve(SUNDAY, _broker(), planned, tmp=tmp_path))
    # Fri 20:55 ET broker read, not the planned 2030-09-01 level
    assert truth._timestamp(stops["as_of"]) == datetime(2031, 3, 8, 1, 55, tzinfo=timezone.utc)
    assert stops["last_broker_read_label"] == "Fri Mar 7 20:55 ET"


def test_weekend_read_within_the_closed_window_is_not_stale(tmp_path):
    stops = _stops(_resolve(SUNDAY, _broker(), tmp=tmp_path))
    assert stops["stale"] is False and stops["gap"] is None
    assert stops["stale_after_hours"] == 72.0


def test_stale_read_keeps_counts_and_names_their_age(tmp_path):
    stops = _stops(_resolve(TUESDAY, _broker(), tmp=tmp_path))
    assert stops["stale"] is True
    assert stops["gap"]["reason"] == "Stop data is 85 h old — counts from the last broker stop read on Fri Mar 7 20:55 ET."
    assert stops["active_count"] == 1 and stops["filled_count"] == 1  # counts are kept, labelled by the gap


def test_filled_stop_still_in_holdings_is_awaiting_holdings_sync(tmp_path):
    doc = _resolve(SUNDAY, _broker(), tmp=tmp_path)
    rows = _stops(doc)["filled_awaiting_sync"]
    assert [(r["symbol"], r["reason"]) for r in rows] == [("BBB", "stop filled · awaiting holdings sync")]
    reasons = {i["title"].split(" ")[0]: i["why"] for i in doc["do_now"]["items"]}
    assert reasons["BBB"] == "Stop filled · awaiting holdings sync"
    assert reasons["CCC"] == "No active broker stop observed"


def test_no_broker_table_keeps_the_existing_gap_and_unknown_counts(tmp_path):
    stops = _stops(_resolve(SUNDAY, None, tmp=tmp_path))
    assert stops["gap"]["reason"] == "persisted broker stop observations unavailable"
    assert stops["active_count"] is None and stops["filled_awaiting_sync"] == []


def test_missing_threshold_is_a_gap_not_a_guess(tmp_path):
    stops = _stops(_resolve(SUNDAY, _broker(), contract=None, tmp=tmp_path))
    # contract=None in inputs falls back to the registry; a registry without the domain must be a gap
    assert truth.stop_freshness_contract(registry_path=truth.Path("/nonexistent/registry.json")) is None
    assert stops["stale_after_hours"] == 72.0  # the committed registry declares broker_stops closed = 72 h


def test_committed_registry_declares_the_broker_stop_contract():
    assert truth.stop_freshness_contract() == {"open_h": 0.25, "closed_h": 72.0}
