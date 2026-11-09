"""LQ-20261107-1656/1674 — the full-lifecycle monitor: an ENTERED position keeps being advised.

Fail-before: today's ``evaluate_candidate`` carries an ENTERED row and never moves it, so every test here fails with
``AttributeError: module 'market_event_plan' has no attribute 'evaluate_position'`` against the base module. Pass-after:
the eight scenarios in DESIGN-LQ-20261107-1656 §PROOF, one test each, plus the verdict matrix.

Synthetic only: no live symbol, no live dollar amount, no broker, no credential, no DB. Set
``MARKET_EVENT_PLAN_UNDER_TEST=<path>`` to point the whole file at another copy of the module (used for the
fail-before run).

    MARKET_EVENT_PLAN_UNDER_TEST=/tmp/base_market_event_plan.py pytest \
        tests/test_market_event_lifecycle_20261109.py
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_UNDER = os.environ.get("MARKET_EVENT_PLAN_UNDER_TEST") or str(ROOT / "scripts" / "lib" / "market_event_plan.py")
_spec = importlib.util.spec_from_file_location("market_event_plan_under_test", _UNDER)
mep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mep)

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


def policy(**lifecycle):
    """The plan block's defaults with a test's lifecycle overrides, so a default change cannot silently move a test."""
    lc = dict(mep.DEFAULT_POLICY["lifecycle"])
    lc.update(lifecycle)
    return {**mep.DEFAULT_POLICY, "lifecycle": lc}


def candidate(**over):
    c = {
        "episode_id": "ep-test",
        "symbol": "TSTX",
        "sector": "healthcare",
        "state": "ENTERED",
        "entry_tier": "YELLOW",
        "plan": {"tranche_qty": [30, 30, 40], "tranche_pcts": [30, 30, 40],
                 "invalidation": 90.0, "entry_price": 100.0},
        "fell_for_reason": False,
    }
    c.update(over)
    return c


def holding(**over):
    h = {"account_label": "Acct A", "qty": 30, "avg_cost": 100.0, "stop_state": "WORKING",
         "price": 101.0, "as_of": NOW.isoformat()}
    h.update(over)
    return h


def snapshot(**over):
    s = {"as_of": NOW.isoformat(), "tier": "YELLOW", "last_close": 101.0, "low": 95.0, "sma20": 99.0,
         "rsi14": 55.0, "rs5_loss_sessions": 0, "gain_guardian_state": None,
         "sleeve": {"pct": 10.0, "target": 18.0}}
    s.update(over)
    return s


def cpi(released_minutes_ago=None, **over):
    e = {"kind": "CPI", "at": (NOW - timedelta(hours=1)).isoformat()}
    if released_minutes_ago is not None:
        e["released_at"] = (NOW - timedelta(minutes=released_minutes_ago)).isoformat()
    e.update(over)
    return e


def evaluate(c=None, h=None, events=None, snap=None, pol=None):
    return mep.evaluate_position(c or candidate(), h or holding(), events if events is not None else [cpi(20)],
                                 snap or snapshot(), pol or policy(), now=NOW)


# ---------------------------------------------------------------- 1. CPI pending withholds t2


def test_1_cpi_pending_withholds_the_second_tranche():
    res = evaluate(events=[cpi(None)])
    assert res["stage"] == "ENTERED_T1"
    assert res["gates"]["t2"]["ok"] is False
    assert "event_gate:CPI not released" in res["reasons"]
    assert res["previous_stage"] == "ENTERED"


# ---------------------------------------------------------------- 2. CPI settled, tier unchanged -> ADD_T2_READY


def test_2_cpi_plus_settle_makes_the_second_tranche_ready_and_alerts_once():
    res = evaluate()
    assert res["stage"] == "ADD_T2_READY"
    assert res["gates"]["t2"]["ok"] is True
    assert res["alert"] and res["alert"]["stage"] == "ADD_T2_READY"
    assert res["alert"]["event_id"] == "ep-test:TSTX:Acct A:ADD_T2_READY"
    assert res["alert"]["class"] == "fi_text"
    # the same row evaluated again, now stored at ADD_T2_READY, must not alert a second time
    again = evaluate(c=candidate(stage="ADD_T2_READY"))
    assert again["stage"] == "ADD_T2_READY"
    assert again["alert"] is None


def test_2b_cpi_still_settling_withholds():
    res = evaluate(events=[cpi(5)])
    assert res["stage"] == "ENTERED_T1"
    assert "event_gate:CPI settling (<15 min)" in res["reasons"]


# ---------------------------------------------------------------- 3. the hot print keeps t2 withheld


def test_3_a_hot_print_that_worsens_the_tier_keeps_t2_withheld():
    res = evaluate(c=candidate(entry_tier="GREEN"), snap=snapshot(tier="ORANGE"))
    assert res["stage"] == "ENTERED_T1"
    assert res["gates"]["t2"]["ok"] is False
    assert any("worse than at entry" in r for r in res["reasons"])


# ---------------------------------------------------------------- 4. t3 needs YELLOW-or-better AND the SMA20 reclaim


def test_4_third_tranche_needs_yellow_or_better_and_the_sma20_reclaim():
    ok = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60))
    assert ok["stage"] == "ADD_T3_READY"
    assert ok["gates"]["t3"]["ok"] is True
    under = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60), snap=snapshot(sma20=105.0))
    assert under["stage"] == "HELD_T2"
    assert any("below SMA20" in r for r in under["reasons"])
    hot = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60), snap=snapshot(tier="ORANGE"))
    assert hot["stage"] == "HELD_T2"
    assert any("worse than YELLOW" in r for r in hot["reasons"])


def test_4b_full_when_the_planned_size_is_held():
    res = evaluate(c=candidate(stage="ADD_T3_READY"), h=holding(qty=100))
    assert res["stage"] == "FULL"


# ---------------------------------------------------------------- 5. exit by RS loss; invalidation is terminal


def test_5_rs_loss_for_n_sessions_exits_and_a_break_of_invalidation_is_terminal():
    exit_res = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60), snap=snapshot(rs5_loss_sessions=3))
    assert exit_res["stage"] == "EXIT_READY"
    assert any("rs5 at or below" in r for r in exit_res["reasons"])
    assert exit_res["alert"]["class"] == "fi_text"
    inv = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60), snap=snapshot(last_close=89.0))
    assert inv["stage"] == "INVALIDATED"
    assert any("broke the recorded invalidation" in r for r in inv["reasons"])
    # terminal: the next run cannot resurrect it
    still = evaluate(c=candidate(stage="INVALIDATED"), h=holding(qty=60))
    assert still["stage"] == "INVALIDATED"
    assert still["alert"] is None
    assert any("terminal" in r for r in still["reasons"])


# ---------------------------------------------------------------- 6. stop filled -> STOPPED_OUT and a recovery handoff


def test_6_stop_filled_is_stopped_out_with_a_recovery_handoff_and_no_reentry():
    res = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60, stop_state="FILLED"))
    assert res["stage"] == "STOPPED_OUT"
    assert res["handoff"]["to"] == "recovery_state"
    assert res["handoff"]["kind"] == "stop_out"
    assert res["alert"]["class"] == "fi_text"
    assert any("recovery owns re-entry" in r for r in res["reasons"])
    # no re-entry stage is ever produced here
    assert res["stage"] not in ("ADD_T2_READY", "ADD_T3_READY", "ENTERED_T1")


def test_6b_qty_zero_with_the_working_stop_gone_is_stopped_out():
    res = evaluate(c=candidate(stage="HELD_T2"),
                   h=holding(qty=0, stop_state="MISSING", had_working_stop=True))
    assert res["stage"] == "STOPPED_OUT"


# ---------------------------------------------------------------- 7. sleeve overweight -> TRIM_READY with the band


def test_7_an_overweight_sleeve_trims_with_the_band_range():
    snap = snapshot(sleeve={"pct": 25.0, "target": 18.0, "band_low_frac": 0.05, "band_high_frac": 0.15})
    res = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60), snap=snap)
    assert res["stage"] == "TRIM_READY"
    assert "5-15%" in res["reasons"][0]
    assert res["alert"]["stage"] == "TRIM_READY"


def test_7b_trim_by_gain_and_rsi_needs_the_basis():
    snap = snapshot(last_close=130.0, rsi14=80.0)
    res = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60, avg_cost=100.0), snap=snap)
    assert res["stage"] == "TRIM_READY"
    assert any("gain 30.0%" in r for r in res["reasons"])
    # no basis: the gain leg is unmeasured, never assumed, and the row grades DEGRADED. The stage is the ordinary
    # progression for two held tranches (t3 is open here), not a trim.
    no_basis = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60, avg_cost=None), snap=snap)
    assert no_basis["stage"] == "ADD_T3_READY"
    assert any("no cost basis" in r for r in no_basis["reasons"])
    assert no_basis["verdict"] == "DEGRADED"


# ---------------------------------------------------------------- 8. stale inputs -> UNVERIFIABLE, no advance


def test_8_a_stale_positions_snapshot_is_unverifiable_and_nothing_advances():
    old = (NOW - timedelta(minutes=90)).isoformat()
    res = evaluate(c=candidate(stage="HELD_T2"), h=holding(qty=60, as_of=old))
    assert res["verdict"] == "UNVERIFIABLE"
    assert res["stage"] == "HELD_T2"
    assert any("no stage advances" in r for r in res["reasons"])
    assert res["alert"] is None


def test_8b_a_stale_market_snapshot_is_unverifiable_too():
    old = (NOW - timedelta(minutes=90)).isoformat()
    res = evaluate(snap=snapshot(as_of=old))
    assert res["verdict"] == "UNVERIFIABLE"
    assert res["stage"] == "ENTERED"


# ---------------------------------------------------------------- the verdict matrix


@pytest.mark.parametrize("case,verdict", [
    ("fresh", "OK"),
    ("no_basis", "DEGRADED"),
    ("stale", "UNVERIFIABLE"),
])
def test_9_the_verdict_matrix(case, verdict):
    if case == "fresh":
        res = evaluate()
    elif case == "no_basis":
        res = evaluate(h=holding(avg_cost=None))
    else:
        res = evaluate(h=holding(as_of=(NOW - timedelta(hours=2)).isoformat()))
    assert res["verdict"] == verdict


def test_the_module_is_pure_and_advisory():
    """No broker, no credential, no DB import — the rail is a property of the module's imports."""
    src = Path(_UNDER).read_text(encoding="utf-8")
    for banned in ("import psycopg", "place_order", "requests.post", "from lib import broker"):
        assert banned not in src
    assert mep.evaluate_position(candidate(), holding(), [cpi(20)], snapshot(), policy(), now=NOW)["advisory_only"] is True
