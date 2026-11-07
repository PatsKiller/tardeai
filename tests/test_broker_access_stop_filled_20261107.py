"""LQ-20261107-203: a 'stop FILLED' line on /v3/system/broker-access states the account's current position.
Synthetic accounts/symbols/quantities only."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.data_broker import broker_access as ba  # noqa: E402

T = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)


def _alert(i, sym, acct, order, cond="TRIGGERED", minute=0):
    return {"id": i, "created_at": T.replace(minute=minute), "symbol": sym, "severity": "urgent",
            "raw_text": f"[stop-health] {cond} · {sym}@{acct} · [{acct}] stop FILLED (#{order}) — position may be flat; review.",
            "lifecycle_state": "active", "parsed_payload": {"condition": cond, "account": acct, "order_id": order}}


def _db(positions, stored=None):
    """Fake for the two reads: positions_current (current qty) and stop_last_known (stored order status)."""
    def q(sql, params=None, fetch="all"):
        if "FROM stop_last_known" in sql:
            return stored
        assert "FROM positions_current" in sql
        return positions
    return q


def _pos(acct, sym, qty):
    return {"account_key": acct, "symbol": sym, "qty": qty}


def _stored(acct, order, status):
    return [{"account": acct, "order_id": order, "status": status, "captured_at": T}]


def test_position_state_thresholds():
    assert [ba.position_state(x) for x in (0, None, "x", 0.4, 1, 100)] == ["flat", "unknown", "unknown", "fractional", "held", "held"]


def test_a_fill_that_left_a_fractional_remainder_says_so():
    rows = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")], _db([_pos("acct_one", "AAA", 0.5)]))
    assert rows[0]["position_state"] == "fractional" and "0.5 sh remain" in rows[0]["message"]


def test_the_match_is_by_account_not_symbol_alone():
    # same symbol is held in a DIFFERENT account; this account is flat.
    rows = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")], _db([_pos("acct_two", "AAA", 100.0)]))
    assert rows[0]["position_state"] == "flat" and rows[0]["position_qty_now"] == 0.0
    assert "now flat" in rows[0]["message"]


def test_a_whole_share_remainder_is_called_held():
    rows = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")], _db([_pos("acct_one", "AAA", 12.0)]))
    assert rows[0]["position_state"] == "held" and "still held in this account" in rows[0]["message"]


def test_hourly_repeats_of_one_fill_collapse_to_one_row():
    alerts = [_alert(3, "AAA", "acct_one", "9001", minute=40), _alert(2, "AAA", "acct_one", "9001", minute=30),
              _alert(1, "AAA", "acct_one", "9001", minute=20), _alert(4, "AAA", "acct_one", "9002", minute=10)]
    rows = ba._stop_alert_rows(alerts, _db([]))
    assert [(r["id"], r["repeat_count"]) for r in rows] == [(3, 3), (4, 1)]
    assert rows[0]["first_at"].endswith("15:20:00+00:00")


def test_an_unreadable_positions_table_is_unknown_not_flat():
    def down(sql, params=None, fetch="all"):
        return None
    rows = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")], down)
    assert rows[0]["position_state"] == "unknown" and rows[0]["position_qty_now"] is None


def test_non_fill_alerts_are_untouched_and_no_positions_query_runs():
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append(sql)
        return []
    a = _alert(1, "AAA", "acct_one", "9001", cond="NEAR_TRIGGER")
    rows = ba._stop_alert_rows([a], q)
    assert "position_state" not in rows[0] and rows[0]["message"] == ba.scrub(a["raw_text"], 160)
    assert not [sql for sql in calls if "positions_current" in sql]


# ── LQ-20261107-220: the row follows the stored order status, not the alert's history ─────────────
def test_a_fill_alert_whose_order_the_store_records_replaced_stops_claiming_a_fill():
    rows = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")],
                               _db([_pos("acct_one", "AAA", 12.0)], _stored("acct_one", "9001", "replaced")))
    r = rows[0]
    assert r["stored_status"] == "replaced" and r["stored_status_source"] == "recorded"
    assert r["alert_claim"] == "stale"
    assert "stop FILLED" not in r["message"] and "did not fill" in r["message"]
    assert "recorded as replaced" in r["message"] and "12 sh still held" in r["message"]


def test_an_order_still_resting_in_the_store_is_not_reported_as_filled():
    rows = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")],
                               _db([_pos("acct_one", "AAA", 0.0)], _stored("acct_one", "9001", "working")))
    r = rows[0]
    assert r["alert_claim"] == "stale" and "still working" in r["message"]
    assert "stop FILLED" not in r["message"] and "now flat" in r["message"]


def test_a_store_confirmed_fill_keeps_the_fill_and_states_the_held_position():
    rows = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")],
                               _db([_pos("acct_one", "AAA", 0.5)], _stored("acct_one", "9001", "filled")))
    r = rows[0]
    assert r["stored_status"] == "filled" and r["alert_claim"] == "confirmed"
    assert "stop FILLED" in r["message"] and "0.5 sh remain" in r["message"]
    # the unread hedge and the read position never sit in one line contradicting each other
    assert "position may be flat" not in r["message"]


def test_an_unreadable_store_invents_no_status_and_no_fill_verdict():
    def down(sql, params=None, fetch="all"):
        raise RuntimeError("db down")
    a = _alert(1, "AAA", "acct_one", "9001")
    r = ba._stop_alert_rows([a], down)[0]
    assert r["stored_status"] is None and r["stored_status_source"] == "unavailable"
    assert "stop FILLED" in r["message"] and "did not fill" not in r["message"]
    assert "position may be flat" not in r["message"] and "current position unknown" in r["message"]


def test_a_not_in_read_row_is_unconfirmed_never_a_did_not_fill():
    # a failed broker read marks EVERY stored row not_in_read; that is not evidence about the order.
    r = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")],
                            _db([], _stored("acct_one", "9001", "not_in_read")))[0]
    assert r["alert_claim"] == "unconfirmed" and "not_in_read" in r["message"]
    assert "did not fill" not in r["message"]


def test_a_store_with_no_row_for_the_order_says_the_fill_is_unconfirmed():
    r = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")], _db([], []))[0]
    assert r["stored_status_source"] == "absent" and r["alert_claim"] == "unconfirmed"
    assert "unconfirmed" in r["message"] and "stop FILLED" not in r["message"]


def test_the_stored_status_lookup_is_keyed_by_account_not_order_id_alone():
    # the SAME order id is stored under another account as filled; this account has no row.
    r = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001")],
                            _db([], _stored("acct_two", "9001", "filled")))[0]
    assert r["stored_status"] is None and r["stored_status_source"] == "absent"


def test_a_proximity_alert_on_an_order_that_already_filled_is_no_longer_about_to_fire():
    r = ba._stop_alert_rows([_alert(1, "AAA", "acct_one", "9001", cond="NEAR_TRIGGER")],
                            _db([], _stored("acct_one", "9001", "filled")))[0]
    assert r["alert_claim"] == "stale" and "records order #9001 as filled" in r["message"]
    assert "no longer a resting stop" in r["message"]


def test_a_non_fill_alert_on_a_retired_order_says_it_is_no_longer_resting():
    a = _alert(1, "AAA", "acct_one", "9001", cond="NEAR_TRIGGER")
    rows = ba._stop_alert_rows([a], _db([], _stored("acct_one", "9001", "cancelled")))
    r = rows[0]
    assert r["alert_claim"] == "stale" and "records order #9001 as cancelled" in r["message"]
    assert "no longer a resting stop" in r["message"] and "about to fire" not in r["message"]


def test_rows_without_an_account_or_order_never_guess():
    a = {"id": 1, "created_at": T, "symbol": "AAA", "severity": "urgent", "raw_text": "synthetic",
         "lifecycle_state": "active", "parsed_payload": {"condition": "TRIGGERED", "order_id": "9001"}}
    r = ba._stop_alert_rows([a], _db([], _stored(None, "9001", "replaced")))[0]
    assert r["stored_status_source"] == "unavailable" and r["alert_claim"] == "current"
