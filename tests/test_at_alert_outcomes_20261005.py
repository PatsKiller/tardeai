"""Active Trader alert audit (operator 2026-10-05: "is it 100% accurate?").

The audit found the page overstated results: XNDU's 09:55 time-to-buy was scored from the
trigger's fire price ($4.375) while you could only pay $4.43, and moves that hit the stop before
+1R counted as hits. Two heads-ups went out with price already through the stop. And the
operator's own XNDU scalp was not tagged to the alert that preceded it.

These tests pin the fixes: outcome scoring from the price you could pay, stop-first is a miss,
best and rule exits, the below-stop veto, supply evidence, fill attribution, and v1→v2 re-score.
Fakes only: no network, no database, no Telegram.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import momentum_alert_scoring as ms  # noqa: E402
from active_trader import momentum_alerts_api as api  # noqa: E402

T0 = 1_791_208_511.0          # 2026-10-05 09:55:11 ET (the XNDU time-to-buy)


@pytest.fixture(autouse=True)
def _journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    return tmp_path / "at"


def bar(i, o, h, l, c, start=T0 + 49):
    return {"t": datetime.fromtimestamp(start + 60 * i, timezone.utc).isoformat(), "o": o, "h": h, "l": l, "c": c}


def row(*, last=4.43, entry=4.375, stop=4.359, ask=4.43, kind="TRIGGERED", verdict="ALERT", ts=T0, sent=True):
    return {"contract": ma.CONTRACT, "run_id": "r", "kind": kind, "verdict": verdict, "ts_epoch": ts, "sent": sent,
            "r_dollars": entry - stop, "veto_reasons": [],
            "candidate": {"symbol": "XNDU", "last": last, "entry_ref": entry, "stop_ref": stop,
                          "session_date": "2026-10-05"},
            "l2": {"best_ask": ask, "best_bid": ask - 0.01}}


def test_outcome_is_measured_from_the_price_you_could_pay_not_the_fire_price():
    # high 4.43+0.04: +2.7R from the old 4.375 fire price, but only +0.6R of the real 7.1c risk
    bars = [bar(0, 4.43, 4.47, 4.40, 4.45), bar(1, 4.45, 4.46, 4.38, 4.38)]
    s = ms.score_row(row(), bars)
    o = s["outcome"]
    assert o["fill"] == 4.43 and o["fill_source"] == "ask"
    assert o["risk"] == pytest.approx(0.071, abs=1e-6)
    assert o["result"] == ms.NO_TOUCH                      # never reached +1R, never hit the stop
    assert s["windows"]["1m"]["mfe_r"] > 1                  # the legacy window still says "hit" — that was the bug
    assert o["best_exit"]["price"] == 4.47 and o["best_exit"]["min_after"] == pytest.approx(0.8, abs=0.1)
    assert o["rule_exit"]["reason"] == "closed below prior bar low" and o["rule_exit"]["price"] == 4.38


def test_stop_first_is_a_miss_and_same_bar_counts_as_stopped():
    stop_first = [bar(0, 4.43, 4.44, 4.35, 4.36), bar(1, 4.36, 4.60, 4.36, 4.58)]
    assert ms.score_row(row(), stop_first)["outcome"]["result"] == ms.STOPPED
    both = [bar(0, 4.43, 4.60, 4.35, 4.50)]
    assert ms.score_row(row(), both)["outcome"]["result"] == ms.SAME_BAR
    summary = ms.outcome_summary([ms.score_row(row(), both)])
    assert summary["TRIGGERED:ALERT"]["STOPPED"] == 1 and summary["TRIGGERED:ALERT"]["worked_rate"] == 0.0


def test_target_before_stop_is_worked():
    bars = [bar(0, 4.43, 4.51, 4.42, 4.50)]
    o = ms.score_row(row(), bars)["outcome"]
    assert o["result"] == ms.WORKED and o["first_touch_epoch"] is not None


def test_alert_already_through_its_stop_is_flagged():
    o = ms.score_row(row(last=4.46, ask=4.46, entry=4.485, stop=4.466), [bar(0, 4.46, 4.5, 4.44, 4.45)])["outcome"]
    assert o["result"] == ms.AT_OR_BELOW_STOP and o["risk"] < 0


def test_bars_before_the_alert_never_leak_in():
    early = bar(-3, 4.0, 9.0, 1.0, 4.0)
    o = ms.score_row(row(), [early, bar(0, 4.43, 4.45, 4.42, 4.44)])["outcome"]
    assert o["best_exit"]["price"] == 4.45 and o["horizon_bars"] == 1


def test_decide_vetoes_price_at_or_below_stop():
    c = ma.Candidate(symbol="CHPT", lane="BELOW", ign=10, fsm_state="ARMED", last=8.975, entry_ref=9.035,
                     stop_ref=8.992, quote_ts_epoch=T0 - 2, session_date="2026-10-05")
    l2 = {"ok": True, "reasons": [], "depth_ratio": 1.7}
    d = ma.decide(c, ma.ARMED, l2, {}, now=T0, cfg=ma.AlertConfig())
    assert d["verdict"] == ma.VETO and "PRICE_AT_OR_BELOW_STOP" in d["veto_reasons"]
    ok = ma.decide(ma.Candidate(**{**c.__dict__, "last": 9.05}), ma.ARMED, l2, {}, now=T0, cfg=ma.AlertConfig())
    assert "PRICE_AT_OR_BELOW_STOP" not in ok["veto_reasons"]


def test_supply_evidence_reports_inside_ask_near_supply_and_wall():
    b = {"bids": [(4.46 - i * 0.01, 1000) for i in range(10)],
         "asks": [(4.47, 300), (4.48, 500), (4.49, 9000)] + [(4.50 + i * 0.01, 800) for i in range(7)],
         "ts_epoch": T0 - 1}
    ev = ma.l2_evidence(b, now=T0, cfg=ma.AlertConfig(), source="moomoo")
    s = ev["supply"]
    assert s["ask_size_inside"] == 300 and s["bid_size_inside"] == 1000
    assert s["ask_wall_price"] == 4.49 and s["ask_wall_size"] == 9000
    assert s["ask_levels_near"] == 5                      # 4.47..4.51 within 1% of 4.47
    assert ev["ok"]                                       # observation only — no new gate


def test_fill_attribution_tags_trade_after_a_sent_alert():
    decisions = [{"id": "a1", "symbol": "XNDU", "kind": "ARMED", "sent": True, "ts_epoch": T0 + 605,
                  "at": "2026-10-05T10:05:16-04:00", "last": 4.46, "stop": 4.359, "l2": {"best_ask": 4.47}},
                 {"id": "v1", "symbol": "XNDU", "kind": "TRIGGERED", "sent": False, "ts_epoch": T0 + 904}]
    fills = [{"ts_epoch": T0 + 718, "account": "ira", "symbol": "XNDU", "side": "Buy", "qty": 100, "price": 4.48},
             {"ts_epoch": T0 + 784, "account": "ira", "symbol": "XNDU", "side": "Sell", "qty": 100, "price": 4.49},
             {"ts_epoch": T0 + 9000, "account": "ira", "symbol": "XNDU", "side": "Buy", "qty": 10, "price": 4.5}]
    trips = api.attribute_fills(fills, decisions)
    first = trips[0]
    assert first["source"] == "active_trader" and first["alert"]["id"] == "a1" and first["alert"]["lag_s"] == 113
    assert first["pnl"] == pytest.approx(1.0) and first["held_s"] == 66
    assert first["alert"]["ask_at_alert"] == 4.47
    assert trips[1]["source"] == "untagged" and trips[1]["sell_at"] is None   # open, too late for any alert


def test_operator_fills_is_a_read_only_select():
    seen = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            seen.append(sql)

        def fetchall(self):
            return []

    class Conn:
        def cursor(self):
            return Cur()
    assert api.operator_fills("2026-10-05", {"XNDU"}, conn=Conn()) == []
    assert seen and seen[0].lstrip().upper().startswith("SELECT") and "trade_transactions" in seen[0]
    assert api.operator_fills("2026-10-05", set(), conn=Conn()) == []


def test_v1_rows_are_rescored_once_under_v2(_journal_dir):
    _journal_dir.mkdir(parents=True)
    r = row(ts=T0)
    (_journal_dir / "momentum_alerts.jsonl").write_text(json.dumps(r) + "\n")
    did = ms.decision_id(r)
    (_journal_dir / "momentum_alerts_scored.jsonl").write_text(
        json.dumps({"contract": "active-trader-momentum-alert-score-v1", "decision_id": did, "status": "SCORED"}) + "\n")
    fn = lambda s, d: [bar(0, 4.43, 4.51, 4.42, 4.5)]  # noqa: E731
    new = ms.score_pending(fn, now=T0 + 40 * 60)
    assert len(new) == 1 and new[0]["contract"] == ms.CONTRACT and new[0]["outcome"]["result"] == ms.WORKED
    assert ms.score_pending(fn, now=T0 + 50 * 60) == []
