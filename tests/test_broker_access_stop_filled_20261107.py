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


def _db(positions):
    def q(sql, params=None, fetch="all"):
        assert "FROM positions_current" in sql
        return positions
    return q


def _pos(acct, sym, qty):
    return {"account_key": acct, "symbol": sym, "qty": qty}


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
    assert "position_state" not in rows[0] and rows[0]["message"] == ba.scrub(a["raw_text"], 160) and not calls
