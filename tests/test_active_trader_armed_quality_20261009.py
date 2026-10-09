"""Active Trader ARMED quality, stand-down, Trade-AI link, recorder reconnect (operator 2026-10-09: "check active
trader not working keeps giving this alert is it wired correctly for scalps along with tradeai?").

Evidence: all 19 ARMED alerts ever sent came from the trigger state machine alone (lane BELOW, setup n/a) and 1 of
19 fired; the ARMED line printed last price / last − ATR ("entry 4.05 · stop 4.01 · R 0.04"); dedupe keyed on the
last price; no stand-down; the "Trade-AI" pill was the sender, not a verdict; the CIO swing R:R sat beside the scalp R;
the recorder's single connection died mid-window. Fakes only: no broker, no network, no database.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_alert_pass as mp  # noqa: E402
from active_trader import momentum_alerts as ma  # noqa: E402

NOW = 1_791_900_000.0
CFG = ma.AlertConfig(mode="send")
L2_OK = {"ok": True, "reasons": [], "depth_ratio": 1.7, "source": "moomoo", "levels": 10, "age_s": 3}
TRIG = {"entry_offset": 0.02, "stop_offset": 0.02}


def armed(**k):
    base = dict(symbol="XNDU", lane="BELOW", ign=1.2, fsm_state="ARMED", last=4.05, entry_ref=4.17, stop_ref=4.00,
                rvol=2.0, armed_bars=4, leg_high=4.40, quote_ts_epoch=NOW - 3)
    base.update(k)
    return ma.Candidate(**base)


def test_fsm_only_armed_needs_rvol_r_and_freshness():
    assert ma.decide(armed(), ma.ARMED, L2_OK, {}, now=NOW, cfg=CFG)["verdict"] == ma.ALERT
    d = ma.decide(armed(rvol=0.55, entry_ref=4.05, stop_ref=4.01, armed_bars=30), ma.ARMED, L2_OK, {}, now=NOW, cfg=CFG)
    assert d["verdict"] == ma.VETO
    assert {"ARMED_LOW_RVOL", "ARMED_R_TOO_SMALL", "ARMED_STALE"} <= set(d["veto_reasons"])


def test_ignition_lane_armed_is_not_held_to_the_fsm_floor():
    d = ma.decide(armed(lane="IGN_75", rvol=0.5, entry_ref=4.05, stop_ref=4.01), ma.ARMED, L2_OK, {}, now=NOW, cfg=CFG)
    assert not any(r.startswith("ARMED_") for r in d["veto_reasons"])


def test_trade_ai_avoid_blocks_headsups_only():
    avoid = {"decision": "AVOID", "not_tradeable": True, "scanned_at": "2026-10-09T07:01:00"}
    assert "TRADE_AI_AVOID" in ma.decide(armed(trade_ai=avoid), ma.ARMED, L2_OK, {}, now=NOW, cfg=CFG)["veto_reasons"]
    wait = {"decision": "WAIT", "not_tradeable": True}
    assert ma.decide(armed(trade_ai=wait), ma.ARMED, L2_OK, {}, now=NOW, cfg=CFG)["verdict"] == ma.ALERT
    trig = armed(fsm_state="IDLE", fire_ts_epoch=NOW - 60, trade_ai=avoid)
    tape = {"ok": True, "reasons": [], "buy_ratio": 0.7}
    assert not any(r.startswith("TRADE_AI") for r in ma.decide(trig, ma.TRIGGERED, L2_OK, tape, now=NOW, cfg=CFG)["veto_reasons"])


def test_message_states_break_level_and_trade_ai_verdict():
    c = armed(break_level=4.15, trade_ai={"decision": "WAIT", "not_tradeable": True, "scanned_at": "2026-10-09T07:01:22"})
    title, body = ma.build_message(c, ma.ARMED, L2_OK, {}, {"quote_age_s": 3})
    assert "trigger above 4.15, now 4.05" in title
    assert "entry 4.17 · stop 4.00 · R 0.17" in body
    assert "Trade-AI today: WAIT 07:01 · not tradeable" in body
    assert "Trade-AI: no scan today" in ma.build_message(armed(), ma.ARMED, L2_OK, {}, {})[1]


def test_armed_levels_come_from_the_state_machine():
    lv = mp.armed_levels({"prev_high": 4.15, "pullback_low": 4.02, "leg_high": 4.40, "armed_bars": 3}, TRIG)
    assert lv["entry_ref"] == 4.17 and lv["stop_ref"] == 4.0 and lv["break_level"] == 4.15 and lv["armed_bars"] == 3
    assert "entry_ref" not in mp.armed_levels({"prev_high": 4.0, "pullback_low": 4.1}, TRIG)   # inverted → none
    rows = [{"symbol": "XNDU", "lane": "BELOW", "ign": 1.2, "entry_ref": 4.05, "stop_ref": 4.01, "rvol_tod": 2.0}]
    [c] = mp.build_candidates(rows, [], {"XNDU": "ARMED"}, day="2026-10-09",
                              trigger_info={"XNDU": {"prev_high": 4.15, "pullback_low": 4.02, "leg_high": 4.4,
                                                     "armed_bars": 3}},
                              trig_cfg=TRIG, trade_ai={"XNDU": {"decision": "WAIT"}})
    assert (c.entry_ref, c.stop_ref, c.break_level, c.leg_high) == (4.17, 4.0, 4.15, 4.4)
    assert c.trade_ai == {"decision": "WAIT"}
    # a fire still wins over the ARMED levels
    [f] = mp.build_candidates(rows, [{"symbol": "XNDU", "entry": 4.2, "stop": 4.1, "fire_minute": 5, "fire_ts": NOW}],
                              {"XNDU": "ARMED"}, day="2026-10-09",
                              trigger_info={"XNDU": {"prev_high": 4.15, "pullback_low": 4.02, "leg_high": 4.4}},
                              trig_cfg=TRIG)
    assert (f.entry_ref, f.stop_ref) == (4.2, 4.1)


def test_dedupe_is_per_setup_leg_not_per_cent():
    assert ma.level_key(armed(last=4.05), ma.ARMED) == ma.level_key(armed(last=4.06, entry_ref=4.18), ma.ARMED) == "leg:4.4000"


def _state(key_ts):
    return {"last": key_ts}


def test_stand_down_after_a_sent_armed_goes_stale_or_breaks():
    key = "XNDU:ARMED:leg:4.4000"
    stale = mp.stand_down_candidates(_state({key: NOW - 600}), {"XNDU": "ARMED"},
                                     {"XNDU": {"leg_high": 4.4, "armed_bars": 25}}, set(), now=NOW, cfg=CFG, day="d")
    assert len(stale) == 1 and stale[0].kind_hint == ma.STAND_DOWN and "stale" in stale[0].stand_down_reason
    broke = mp.stand_down_candidates(_state({key: NOW - 600}), {"XNDU": "IDLE"}, {"XNDU": {}}, set(), now=NOW, cfg=CFG,
                                     day="d")
    assert len(broke) == 1 and "broke down" in broke[0].stand_down_reason
    # still live, already stood down, fired, too old, or not scored this pass → nothing
    assert not mp.stand_down_candidates(_state({key: NOW - 600}), {"XNDU": "ARMED"},
                                        {"XNDU": {"leg_high": 4.4, "armed_bars": 5}}, set(), now=NOW, cfg=CFG, day="d")
    assert not mp.stand_down_candidates(_state({key: NOW - 600, "XNDU:STAND_DOWN:leg:4.4000": NOW - 60}),
                                        {"XNDU": "IDLE"}, {}, set(), now=NOW, cfg=CFG, day="d")
    assert not mp.stand_down_candidates(_state({key: NOW - 600}), {"XNDU": "IDLE"}, {}, {"XNDU"}, now=NOW, cfg=CFG, day="d")
    assert not mp.stand_down_candidates(_state({key: NOW - 3 * 3600}), {"XNDU": "IDLE"}, {}, set(), now=NOW, cfg=CFG,
                                        day="d")
    assert not mp.stand_down_candidates(_state({key: NOW - 600}), {}, {}, set(), now=NOW, cfg=CFG, day="d")


def test_stand_down_is_sent_without_a_book_and_never_vetoed(tmp_path):
    c = ma.Candidate(symbol="XNDU", lane="", ign=0.0, kind_hint=ma.STAND_DOWN, level_key="leg:4.4000",
                     stand_down_reason="the setup went stale — no break after 25 min")
    sent, books = [], []
    rows = ma.evaluate_pass([c], cfg=CFG, now=NOW, fetch_primary_book=lambda s: books.append(s),
                            send_fn=lambda **k: sent.append(k) or {"sent": True},
                            journal_path=tmp_path / "j.jsonl", throttle_path=tmp_path / "t.json",
                            zones_file=tmp_path / "z.json")
    assert rows[0]["verdict"] == ma.ALERT and rows[0]["sent"] and not books
    assert sent[0]["alert_type"] == "at_scalp_stand_down" and "STAND DOWN · XNDU" in sent[0]["title"]


def test_cio_line_is_labelled_swing_view_on_scalp_alerts():
    from scripts.lib import opportunity_alert as oa

    assert "active_trader_scalp_alert" in oa.SWING_VIEW_CLASSES
    src = (ROOT / "scripts/lib/opportunity_alert.py").read_text(encoding="utf-8")
    assert 'CIO swing view (not this scalp):' in src


def test_logger_passes_trigger_info_and_recorder_reconnects():
    lg = (ROOT / "scripts/scalp_shadow_logger.py").read_text(encoding="utf-8")
    assert 'trigger_info[a["_symbol"]] = {**(tr.get("final") or {}), "armed_bars": _armed_bars}' in lg
    assert "trigger_info=trigger_info)" in lg
    rec = (ROOT / "scripts/active_trader/microstructure_recorder.py").read_text(encoding="utf-8")
    assert "def live_conn()" in rec and "conn_fn=(live_conn" in rec and "conn=live_conn()" in rec


def test_live_conn_reopens_a_closed_connection(monkeypatch):
    import types

    from active_trader import microstructure_recorder as mr

    class Conn:
        def __init__(self, closed=0):
            self.closed = closed

        def cursor(self):
            c = self

            class Cur:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def execute(self, q):
                    if c.closed:
                        raise RuntimeError("connection already closed")
            return Cur()

        def close(self):
            self.closed = 1

    made = []
    monkeypatch.setitem(sys.modules, "db_adapter",
                        types.SimpleNamespace(get_connection=lambda: made.append(Conn()) or made[-1]))
    mr._CONN["conn"] = None
    a = mr.live_conn()
    assert mr.live_conn() is a and len(made) == 1          # healthy: reused
    a.closed = 1
    b = mr.live_conn()
    assert b is not a and len(made) == 2                   # closed: reopened
