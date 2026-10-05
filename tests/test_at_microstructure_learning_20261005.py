"""Active Trader microstructure recorder, signals, trade replay, exit watch and learning memory
(operator-approved 2026-10-05: "go back and let me know what was volume and what was on the order
book at the time"; "is any of this persisted in memory when it works so we learn").

Fakes only: no OpenD, no database, no Telegram, no Schwab token store.
"""
from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import microstructure_signals as msig  # noqa: E402
from active_trader import microstructure_recorder as rec  # noqa: E402
from active_trader import trade_replay as tr  # noqa: E402
from active_trader import trade_learning as tl  # noqa: E402
from active_trader import signal_calibration as sc  # noqa: E402
from active_trader import exit_watch as ew  # noqa: E402

T = 1_791_209_229.0          # 2026-10-05 10:07:09 ET — the operator's XNDU buy
CFG = msig.SignalConfig()


@pytest.fixture(autouse=True)
def _journal_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    monkeypatch.setattr(rec, "ENGINE_KILL", tmp_path / "no_such_kill_file")
    return tmp_path / "at"


def snap(t, bids, asks, ticks=(), last=None):
    return {"t": t, "b": [list(x) for x in bids], "a": [list(x) for x in asks], "k": [list(k) for k in ticks], "l": last}


def bars(vols, closes=None, start=T - 600):
    closes = closes or [4.4 + 0.01 * i for i in range(len(vols))]
    return [{"t": start + 60 * i, "o": c - 0.005, "h": c + 0.01, "l": c - 0.01, "c": c, "v": v} for i, (v, c) in enumerate(zip(vols, closes))]


# ── signals ──────────────────────────────────────────────────────────────────

def test_book_pull_matches_xndu_both_sides_pulled():
    s0 = snap(T - 60, [(4.46, 45658)], [(4.47, 35217)])
    s1 = snap(T, [(4.47, 10329)], [(4.48, 10779)])
    sig = msig.book_pull([s0, s1], T, CFG)
    assert sig["on"] is True and sig["value"] == {"bid_pct": -77.4, "ask_pct": -69.4}


def test_supply_thinning_and_not_enough_data_is_none():
    s0 = snap(T - 50, [(4.46, 1000)], [(4.47, 5000), (4.48, 5000)])
    s1 = snap(T, [(4.46, 1000)], [(4.47, 1000), (4.48, 2000)])
    assert msig.supply_thinning([s0, s1], T, CFG)["on"] is True
    assert msig.supply_thinning([s1], T, CFG)["on"] is None          # never a pass or a fail without data


def test_ask_refill_flags_hidden_seller():
    s0 = snap(T - 50, [(4.46, 1000)], [(4.47, 500)])
    s1 = snap(T - 25, [(4.46, 1000)], [(4.47, 500)], ticks=[(T - 30, 4.47, 600, "B")])
    s2 = snap(T, [(4.46, 1000)], [(4.47, 480)], ticks=[(T - 10, 4.47, 700, "B")])
    sig = msig.ask_refill([s0, s1, s2], T, CFG)
    assert sig["on"] is True and sig["bought_at_ask"] == 1300
    moved = snap(T, [(4.47, 1000)], [(4.48, 480)], ticks=[(T - 10, 4.48, 700, "B")])
    assert msig.ask_refill([s0, moved], T, CFG)["on"] is False       # ask lifted = supply cleared


def test_volume_acceleration_high_break_vwap():
    b = bars([1000, 1100, 900, 1000, 1000, 4500], closes=[4.40, 4.41, 4.42, 4.43, 4.44, 4.50])
    acc = msig.volume_acceleration(b, CFG)
    assert acc["on"] is True and acc["value"] == 4.5
    assert msig.high_break(b, CFG)["on"] is True
    assert msig.high_break(b, CFG, premarket_high=4.60)["on"] is False
    vd = msig.vwap_distance(b, 4.80, CFG)
    assert vd["on"] is True and vd["value"] > 3


def test_exit_signals():
    tk = [(T - i, 4.4, 100, "S" if i % 4 else "B") for i in range(40)]
    assert msig.tape_flip([snap(T, [], [], ticks=tk)], CFG)["on"] is True
    b = bars([100] * 10 + [900])
    b[-1].update(o=4.50, c=4.51, h=4.70, l=4.49)
    assert msig.volume_climax(b, CFG)["on"] is True
    assert msig.close_below_prior_low([{"l": 4.5, "c": 4.6}, {"l": 4.4, "c": 4.45}])["on"] is True
    up = [{"t": T - 120, "c": 4.6, "v": 100, "vw": 4.5}, {"t": T - 60, "c": 4.4, "v": 100, "vw": 4.45}]
    assert msig.vwap_loss(up)["on"] is True
    w0 = snap(T - 50, [(4.46, 100)], [(4.47, 100), (4.48, 100), (4.49, 100)])
    w1 = snap(T, [(4.46, 100)], [(4.47, 100), (4.48, 9000), (4.49, 100)])
    wall = msig.ask_wall([w0, w1], T, CFG)
    assert wall["on"] is True and wall["price"] == 4.48


def test_schwab_mm_stack_and_missing_book():
    row = {"ask_levels": [{"price": 4.48, "size": 3000, "mm_count": 5}], "bid_levels": [{"price": 4.47, "size": 800, "mm_count": 1}]}
    assert msig.schwab_book(row, CFG)["on"] is True
    assert msig.schwab_book(None, CFG)["status"] == "NO_BOOK" and msig.schwab_book(None, CFG)["on"] is None


def test_bars_from_ticks():
    b = msig.bars_from_ticks([(T, 4.4, 100, "B"), (T + 10, 4.5, 200, "B"), (T + 61, 4.45, 50, "S")])
    assert len(b) == 2 and b[0]["v"] == 300 and b[0]["h"] == 4.5 and b[0]["vw"] == pytest.approx((440 + 900) / 300)


# ── recorder ─────────────────────────────────────────────────────────────────

class FakeSrc:
    def __init__(self):
        self.n = 0

    def book(self, s, now=None):
        return {"bids": [(4.46, 1000)], "asks": [(4.47, 500)], "ts_epoch": now, "ts_source": "fetch"}

    def tape(self, s):
        self.n += 1
        return [{"ts_epoch": T + i, "price": 4.47, "volume": 100, "direction": "BUY"} for i in range(self.n)]

    def quote(self, s):
        return 4.47, T


def _clock(start=T):
    t = {"now": start}
    return (lambda: t["now"]), (lambda s: t.__setitem__("now", t["now"] + max(s, 0.001)))


def test_recorder_writes_compact_lines_dedups_tape_and_publishes_live_symbols(_journal_dir):
    now_fn, sleep_fn = _clock()
    st = rec.run(rcfg=rec.RecorderConfig(interval_s=5), symbols_fn=lambda: ["XNDU"], src=FakeSrc(), now_fn=now_fn,
                 sleep_fn=sleep_fn, window=("00:00", "23:59"), max_seconds=14, out=lambda *_: None)
    assert st["polls"] == 3 and st["errors"] == 0 and st["stopped"] == "max_seconds"
    lines = rec.load_snapshots("2026-10-05", "XNDU")
    assert len(lines) == 3 and lines[0]["a"] == [[4.47, 500]]
    assert [len(x["k"]) for x in lines] == [1, 1, 1]             # each poll only adds the new print
    live = json.loads((_journal_dir / "micro" / "live_symbols.json").read_text())
    assert live["symbols"] == ["XNDU"]


def test_recorder_dry_run_writes_nothing_and_kill_file_stops(_journal_dir):
    now_fn, sleep_fn = _clock()
    out = []
    rec.run(rcfg=rec.RecorderConfig(), symbols_fn=lambda: ["XNDU"], src=FakeSrc(), now_fn=now_fn, sleep_fn=sleep_fn,
            window=("00:00", "23:59"), max_seconds=6, dry_run=True, out=out.append)
    assert not (_journal_dir / "micro").exists() and any('"symbol": "XNDU"' in o for o in out)
    (_journal_dir / "micro").mkdir(parents=True)
    (_journal_dir / "micro" / "RECORDER_DISABLED").write_text("")
    st = rec.run(rcfg=rec.RecorderConfig(), symbols_fn=lambda: ["XNDU"], src=FakeSrc(), now_fn=now_fn, sleep_fn=sleep_fn,
                 window=("00:00", "23:59"), max_seconds=60, out=lambda *_: None)
    assert st["stopped"] == "kill_file" and st["polls"] == 0


def test_pick_symbols_order_and_cap():
    assert rec.pick_symbols(fills_today=["xndu"], alerted_today=["CHPT", "XNDU"], universe_by_recency=["SDEV", "AAA", "BBB"],
                            cap=3) == ["XNDU", "CHPT", "SDEV"]


def test_no_trade_context_or_order_path_in_new_modules():
    banned = {"place_order", "modify_order", "cancel_order", "unlock_trade", "OpenSecTradeContext", "MoomooTradeReader",
              "request_history_kline"}
    for name in ("microstructure_recorder", "microstructure_signals", "trade_replay", "trade_learning",
                 "signal_calibration", "exit_watch"):
        tree = ast.parse((ROOT / "scripts" / "active_trader" / f"{name}.py").read_text())
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
               {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not (used & banned), (name, used & banned)


# ── alert evidence ───────────────────────────────────────────────────────────

def test_signals_attach_to_decisions_without_changing_the_verdict(_journal_dir):
    c = ma.Candidate(symbol="XNDU", lane="BELOW", ign=10, fsm_state="ARMED", last=4.47, entry_ref=4.46, stop_ref=4.40,
                     quote_ts_epoch=T - 1, session_date="2026-10-05")
    book = {"bids": [(4.46, 5000)] * 10, "asks": [(4.47, 2000)] * 10, "ts_epoch": T - 1}
    kw = dict(cfg=ma.AlertConfig(), now=T, fetch_primary_book=lambda s: book, persist=False)
    plain = ma.evaluate_pass([c], **kw)[0]
    withsig = ma.evaluate_pass([c], fetch_signals=lambda s: {"status": "OK", "book_pull": {"on": True}}, **kw)[0]
    assert plain["verdict"] == withsig["verdict"] and withsig["signals"]["book_pull"]["on"] is True
    broken = ma.evaluate_pass([c], fetch_signals=lambda s: 1 / 0, **kw)[0]
    assert broken["signals"] is None and broken["verdict"] == plain["verdict"]


# ── replay ───────────────────────────────────────────────────────────────────

def _jrow(ts, kind, verdict, bid, ask, tape=None):
    return {"contract": ma.CONTRACT, "ts_epoch": ts, "kind": kind, "verdict": verdict,
            "candidate": {"symbol": "XNDU", "session_date": "2026-10-05"},
            "l2": {"best_bid": 4.46, "best_ask": 4.47, "bid_depth": bid, "ask_depth": ask, "levels": 10}, "tape": tape or {}}


def test_bracketed_replay_of_the_xndu_buy():
    journal = [_jrow(T - 113, "ARMED", "ALERT", 45658, 35217), _jrow(T + 186, "TRIGGERED", "VETO", 10329, 10779, {"buy_ratio": 0.998, "prints": 50})]
    iex = [{"t": T - 309 + 60 * i, "v": v, "o": 4.4, "h": 4.5, "l": 4.4, "c": 4.45} for i, v in enumerate([1105, 424, 873, 2006, 4503, 1000])]
    p = tr.point("XNDU", T, day="2026-10-05", snaps=[], journal=journal, iex_bars=iex, schwab_row=None, scfg=CFG, side="buy")
    assert p["evidence"] == "bracketed" and [b["seconds_from_fill"] for b in p["bracket"]] == [-113, 186]
    assert p["bracket_change"] == {"bid_depth_pct": -77.4, "ask_depth_pct": -69.4}
    assert p["volume"]["minute_volume"] == 1000 and p["volume"]["prior5_avg"] == 1782.2
    assert "partial" in p["volume"]["source"]


def test_exact_replay_uses_recorder_snapshot_tape_and_signals():
    snaps = [snap(T - 30, [(4.46, 4000)], [(4.47, 3000)], ticks=[(T - 31, 4.47, 300, "B")]),
             snap(T - 3, [(4.46, 900)], [(4.47, 800)], ticks=[(T - 4, 4.47, 100, "S")])]
    srow = {"best_bid": 4.46, "best_ask": 4.47, "bid_depth": 900, "ask_depth": 3000, "ask_levels": [{"mm_count": 5}], "ts_epoch": T - 2}
    p = tr.point("XNDU", T, day="2026-10-05", snaps=snaps, journal=[], iex_bars=[], schwab_row=srow, scfg=CFG, side="buy")
    assert p["evidence"] == "exact" and p["book_age_s"] == 3.0 and p["book"]["ask_inside"] == 800
    assert p["tape"]["buy_ratio"] == 0.75 and p["schwab"]["ask_inside_mm"] == 5
    assert p["signals"]["book_pull"]["on"] is True                  # 4000→900 bid, 3000→800 ask


# ── learning ─────────────────────────────────────────────────────────────────

TRIP = {"symbol": "XNDU", "qty": 100.0, "buy_ts": T, "buy_at": "2026-10-05T10:07:09-04:00", "buy_price": 4.48,
        "sell_at": "2026-10-05T10:08:15-04:00", "sell_price": 4.49, "pnl": 1.0, "held_s": 66, "source": "active_trader",
        "alert": {"id": "a1", "kind": "ARMED", "ask_at_alert": 4.47, "lag_s": 113}}


def test_trip_and_decision_records_append_once(_journal_dir):
    rp = {"buy": {"evidence": "bracketed", "book": {"bid_depth": 45658, "ask_depth": 35217}, "signals": {}}}
    r = tl.trip_record(TRIP, rp, "2026-10-05")
    assert r["type"] == "trip" and r["at_buy"]["evidence"] == "bracketed"
    assert tl.trip_record({**TRIP, "sell_at": None}, rp, "2026-10-05") is None     # open trips are not lessons yet
    row = {"kind": "ARMED", "verdict": "ALERT", "ts_epoch": T, "candidate": {"symbol": "XNDU", "session_date": "2026-10-05"},
           "l2": {"depth_ratio": 1.3, "spread_bps": 22}, "signals": {"status": "OK", "book_pull": {"on": True}, "high_break": {"on": False}}}
    d = tl.decision_record(row, {"status": "SCORED", "decision_id": "d1", "outcome": {"result": "SAME_BAR", "best_exit": {"pct": 1.2}}})
    assert d["outcome"]["result"] == "STOPPED" and d["signals"] == {"book_pull": True, "high_break": False}
    assert tl.append_new([r, d]) == 2 and tl.append_new([r, d]) == 0 and len(tl.read_records()) == 2


def test_lesson_row_is_deterministic_and_dry_run_touches_no_db():
    rp = {"buy": {"evidence": "bracketed", "book": {"bid_depth": 45658, "ask_depth": 35217, "ask_inside": None},
                  "bracket_change": {"bid_depth_pct": -77.4, "ask_depth_pct": -69.4},
                  "volume": {"minute_volume": 1000, "prior5_avg": 1782.2, "source": "alpaca_iex"}}}
    a, b = tl.lesson_row(TRIP, rp, trade_id=451468), tl.lesson_row(TRIP, rp, trade_id=451468)
    assert a == b and a["lesson_category"] == "active_trader_scalp" and "-77%" in a["improved_lesson"]
    assert "None" not in a["improved_lesson"]
    assert tl.insert_lessons(None, [a], apply=False) == {"applied": False, "would_write": [a]}


def test_lesson_insert_is_idempotent_sql():
    seen = []

    class Cur:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            seen.append(sql)

    class Conn:
        def cursor(self):
            return Cur()

        def commit(self):
            seen.append("COMMIT")
    res = tl.insert_lessons(Conn(), [tl.lesson_row(TRIP, None, trade_id=1)], apply=True)
    assert res == {"applied": True, "inserted": 1} and "ON CONFLICT" in seen[0] and seen[-1] == "COMMIT"


def _dec(i, worked, pull):
    return {"type": "decision", "session_date": f"2026-10-{1 + i % 5:02d}", "signals": {"book_pull": pull},
            "features": {"depth_ratio": 1.6 if worked else 0.9, "spread_bps": 20, "buy_ratio": None, "risk_pct": 1.0},
            "outcome": {"result": "WORKED" if worked else "STOPPED", "best_exit_pct": 1.0, "rule_exit_pct": 0.5 if worked else -0.5}}


def test_calibration_insufficient_sample_then_proposals_only():
    few = [_dec(i, True, False) for i in range(5)]
    assert sc.calibrate(few, sessions=20, min_sample=30, min_bucket=8, min_edge=0.15)["status"] == "insufficient sample"
    recs = [_dec(i, False, True) for i in range(15)] + [_dec(i, True, False) for i in range(15)]
    rep = sc.calibrate(recs, sessions=20, min_sample=30, min_bucket=8, min_edge=0.15)
    kinds = {(p["type"], p.get("signal") or p.get("feature")) for p in rep["proposals"]}
    assert ("veto", "book_pull") in kinds and ("threshold", "depth_ratio") in kinds
    assert all(p["status"].startswith("PROPOSED") for p in rep["proposals"])


# ── exit watch ───────────────────────────────────────────────────────────────

def test_exit_watch_shadow_journals_and_send_mode_sends_with_header(_journal_dir):
    pos = {"symbol": "XNDU", "qty": 100, "buy_price": 4.48, "buy_ts": T}
    tk = [(T - i, 4.45, 100, "S") for i in range(40)]
    snaps = [snap(T - 5, [(4.44, 100)], [(4.45, 100)], ticks=tk, last=4.45)]
    sent = []
    shadow = ew.ExitWatcher(ecfg=ew.ExitWatchConfig(), scfg=CFG, positions_fn=lambda: [pos], snaps_fn=lambda s: snaps,
                            send_fn=lambda **k: sent.append(k) or {"sent": True})
    rows = shadow(T)
    assert rows and "tape_flip" in rows[0]["fired"] and rows[0]["sent"] is False and not sent
    assert shadow(T + 10) == []                                   # eval_s throttles evaluation
    live = ew.ExitWatcher(ecfg=ew.ExitWatchConfig(mode="send"), scfg=CFG, positions_fn=lambda: [pos],
                          snaps_fn=lambda s: snaps, send_fn=lambda **k: sent.append(k) or {"sent": True})
    r = live(T)[0]
    assert r["sent"] is True and sent[0]["title"].startswith(ma.AT_SCALP_ALERT_HEADER)
    assert ma.NOT_AN_ORDER in sent[0]["body"]
    assert live(T + 61)[0]["verdict"] == "VETO"                    # cooldown per position
    assert len(ew.read_rows("2026-10-05")) == 3


def test_open_tagged_positions_only():
    trips = [TRIP, {**TRIP, "sell_at": None}, {**TRIP, "sell_at": None, "source": "untagged"}]
    assert len(ew.open_tagged_positions(trips)) == 1
    with pytest.raises(ValueError):
        ew.ExitWatchConfig.from_mapping({"mode": "live"})


# ── Schwab stream daemon: scalp names subscribed ─────────────────────────────

def test_stream_daemon_reads_scalp_symbols_and_adds_subscriptions(tmp_path):
    import schwab_stream_daemon as d
    p = tmp_path / "live_symbols.json"
    p.write_text(json.dumps({"ts_epoch": 1000.0, "symbols": ["XNDU", "SDEV", "bad-1"]}))
    assert d._scalp_symbols(10, now=1100.0, path=p, max_age_s=900) == ["XNDU", "SDEV"]
    assert d._scalp_symbols(10, now=5000.0, path=p, max_age_s=900) == []          # stale file contributes nothing
    assert d._union(["AAPL", "XNDU"], ["XNDU", "SDEV"]) == ["AAPL", "XNDU", "SDEV"]
    calls = []

    class SC:
        async def level_one_equity_add(self, s):
            calls.append(("l1_add", s))

        async def nasdaq_book_add(self, s):
            calls.append(("book_add", s))

        async def nasdaq_book_subs(self, s):  # would REPLACE the set — must never be used for adds
            calls.append(("book_subs", s))
    asyncio.run(d._add_subscriptions(SC(), ["SDEV"]))
    assert calls == [("l1_add", ["SDEV"]), ("book_add", ["SDEV"])]


# ── API ──────────────────────────────────────────────────────────────────────

def test_feed_exposes_replays_exit_watch_and_learning(_journal_dir):
    from active_trader import momentum_alerts_api as api
    tr.write_replays("2026-10-05", [{"symbol": "XNDU", "buy_ts": T, "qty": 100.0, "buy": {"evidence": "bracketed"}}])
    assert api._with_replays([dict(TRIP)], tr.read_replays("2026-10-05"))[0]["replay"]["buy"]["evidence"] == "bracketed"
    tl.append_new([{"id": "decision:x", "type": "decision", "session_date": "2026-10-05"}])
    block = api._learning_block("2026-10-05")
    assert block["learning"]["decisions"] == 1 and block["learning"]["status"] == "insufficient sample"
    snap_ = api.alerts_snapshot(session_date="2026-10-05", now=T)
    assert "exit_watch" in snap_ and snap_["learning"]["decisions"] == 1
