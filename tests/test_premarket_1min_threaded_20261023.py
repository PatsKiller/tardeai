"""Premarket 1-minute cadence, threaded lifecycle and scalp focus list (operator 2026-10-23).

Operator decisions (verbatim):
- "I agree for every minute, because on manually, I do a 1 minute candle check."
- "And this should just be critiqued at least the top 20 that's it. We don't need everything, but we should have a
  mechanism that's bringing stuff in and out of the top 20. Or the top 30 or whatever."

Covers:
- cadence: the loop ticks once per minute, settle_s after the boundary, on the CLOSED candle (the forming bar is
  never used); the legacy pass keeps its 5-minute grid; an overrunning tick skips minutes, never overlaps; the
  window end stops the loop; a second run finds the run lock held and exits (no overlap).
- lifecycle threading: WATCH -> APPROACHING -> ARMED -> TRIGGERED -> EXTENDED -> PULLBACK_ZONE -> STAND DOWN, one
  ledger row per state CHANGE (same state never re-sent), live replies go to the thread root, a hard cap per
  symbol per hour, a failed threaded send falls back to the legacy transport.
- every message carries the shared "Driven by / Ready / Missing" block (momentum_setup_evidence.evidence_block).
- rollout: shadow leaves the legacy send untouched and sends nothing new; live replaces the throttled send; legacy
  runs nothing new.
- focus list: size cap, hysteresis without flapping, no eviction while ARMED / TRIGGERED, every entry and exit
  recorded with a reason, critique (Hermes scalp research) only for focus names when the list is fresh.
- the comparison report and the operator crontab packet (preview, exact-text match, backup, captured-file verify
  against a fake crontab that dies on SIGPIPE like the real one).

Hermetic: fake clock, fake recorder snapshots, fake bars, tmp stores, injected senders. No moomoo, DB, Telegram,
network, live crontab or broker.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import momentum_alerts as ma  # noqa: E402
from active_trader import premarket_watch as pw  # noqa: E402
from lib import momentum_setup_evidence as mse  # noqa: E402
from lib import scalp_focus as sf  # noqa: E402
from lib import unified_momentum_alert as um  # noqa: E402

ET = ZoneInfo("America/New_York")
DAY = "2026-10-23"


def ts(hm: str, sec: int = 0) -> float:
    h, m = hm.split(":")
    return datetime(2026, 10, 23, int(h), int(m), sec, tzinfo=ET).timestamp()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    monkeypatch.setenv("SCALP_FOCUS_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("UNIFIED_MOMENTUM_ALERT_LEDGER", str(tmp_path / "runtime" / "unified.jsonl"))
    (tmp_path / "at").mkdir()
    (tmp_path / "runtime").mkdir()


# ── fakes ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _bar(t, o, h, low, c, v):
    return {"s": t, "o": o, "h": h, "l": low, "c": c, "v": v}


def base_bars():
    """06:00-07:49: a slow climb 2.20 -> 2.60 on 10k/min, one 06:30 spike to 3.00 (the PM high to break)."""
    out = []
    for i in range(110):
        t = ts("06:00") + 60 * i
        c = round(2.20 + 0.40 * i / 109, 4)
        h = 3.00 if i == 30 else c + 0.01
        out.append(_bar(t, c - 0.005, h, c - 0.01, c, 10_000))
    for i in range(110, 120):          # 07:50-07:59 at 2.65
        out.append(_bar(ts("06:00") + 60 * i, 2.645, 2.66, 2.64, 2.65, 10_000))
    return out


class FakeData:
    """PremarketMoomoo stand-in: bars include a FORMING bar the 1-min path must ignore."""

    def __init__(self, bars_by_sym, snap=None):
        self.bars_by_sym = bars_by_sym
        self.snap = snap or {}
        self.book_calls: list[str] = []

    def snapshot(self, syms):
        return {s: self.snap.get(s, {"prev_close": 2.00, "float_mm": 5.0, "pre_price": 2.65, "pre_volume": 1.2e6})
                for s in syms}

    def bars_start(self, sym):
        rows = list(self.bars_by_sym.get(sym, []))
        if rows:   # a forming bar far above everything: if it were used, every state would be TRIGGERED/EXTENDED
            t = rows[-1]["s"] + 60
            rows.append(_bar(t, 9.0, 9.9, 9.0, 9.9, 999_999))
        return rows

    def book(self, sym, now):
        self.book_calls.append(sym)
        return {"bids": [(2.60, 5000)] * 5, "asks": [(2.61, 2000)] * 5, "ts_epoch": now}

    def tape(self, sym):
        return []


class FakeRecorder:
    """The recorder store: a fresh book and a buying tape for every symbol; bars not published (None)."""

    def bars(self, day, sym, *, boundary, now, max_age_s):
        return None

    def book(self, day, sym, *, now, max_age_s):
        return {"bids": [[2.60, 5000]] * 5, "asks": [[2.61, 2000]] * 5, "ts_epoch": now - 2, "ts_source": "store"}

    def tape(self, day, sym, *, now):
        return [{"ts_epoch": now - 3, "price": 2.61, "volume": 700, "direction": "BUY"},
                {"ts_epoch": now - 2, "price": 2.60, "volume": 300, "direction": "SELL"}]


def run_tick(tmp_path, data, boundary, *, cfg=None, fcfg=None, pool=None, ledger=None, send=None,
             unified_mode="shadow", fallback=None):
    cfg = cfg or pw.PremarketConfig()
    return pw.evaluate_1m(pool or [{"symbol": "AAA", "float_mm": 5.0, "rvol": 12.0}], data=data, cfg=cfg,
                          fcfg=fcfg or sf.FocusConfig(), boundary=boundary, now=boundary + 6, day=DAY, persist=True,
                          recorder=FakeRecorder(), evidence_loader=None, unified_mode=unified_mode, ledger=ledger,
                          send=send, fallback_send=fallback, catalyst_lookup=lambda s, d: {},
                          lifecycle_path=tmp_path / "life.json", focus_path=tmp_path / "focus.json",
                          focus_events_path=tmp_path / "focus_events.jsonl", journal_path=tmp_path / "pm1m.jsonl")


SCRIPT = [  # (boundary, bar appended for the minute that just closed, expected state)
    ("08:00", None, "WATCH"),
    ("08:01", (2.90, 2.94, 2.89, 2.93, 12_000), "APPROACHING"),
    ("08:02", (2.93, 2.99, 2.93, 2.985, 15_000), "ARMED"),
    ("08:03", (2.98, 3.06, 2.98, 3.05, 30_000), "TRIGGERED"),
    ("08:04", (3.05, 3.21, 3.05, 3.20, 20_000), "EXTENDED"),
    ("08:05", (3.10, 3.10, 3.02, 3.03, 15_000), "PULLBACK_ZONE"),
    ("08:06", (3.03, 3.05, 3.02, 3.04, 12_000), "PULLBACK_ZONE"),
    ("08:07", (3.00, 3.00, 2.20, 2.25, 40_000), "PULLBACK_ZONE"),
    ("08:08", (2.25, 2.26, 2.20, 2.22, 40_000), "STAND_DOWN"),
]


def play(tmp_path, *, cfg=None, ledger=None, send=None, unified_mode="shadow", fallback=None, upto=None):
    bars = base_bars()
    data = FakeData({"AAA": bars})
    results = []
    for hm, bar, _ in SCRIPT[:upto]:
        if bar:
            bars.append(_bar(ts(hm) - 60, *bar))
        results.append(run_tick(tmp_path, data, ts(hm), cfg=cfg, ledger=ledger, send=send,
                                unified_mode=unified_mode, fallback=fallback))
    return results, data


# ── cadence: alignment, loop, no overlap ───────────────────────────────────────────────────────────────────────

def test_ticks_align_to_candle_closes():
    assert pw.minute_boundary(ts("08:04", 59)) == ts("08:04")
    assert pw.next_tick(ts("08:04", 10), 6) == ts("08:05", 6)
    assert pw.next_tick(ts("08:05", 2), 6) == ts("08:05", 6)
    rows = pw.closed_bars([_bar(ts("08:03"), 1, 1, 1, 1, 1), _bar(ts("08:04"), 2, 2, 2, 2, 2)],
                          boundary=ts("08:05"), day=DAY)
    assert [r["t"] for r in rows] == [ts("08:03"), ts("08:04")]
    forming = pw.closed_bars([_bar(ts("08:05"), 2, 2, 2, 2, 2)], boundary=ts("08:05"), day=DAY)
    assert forming == []                                      # the 08:05 bar closes at 08:06
    rth = pw.closed_bars([_bar(ts("09:30"), 2, 2, 2, 2, 2)], boundary=ts("09:35"), day=DAY)
    assert rth == []                                          # premarket only


class Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def sleep(self, s):
        assert s >= 0
        self.t += s


def test_loop_ticks_every_minute_on_the_closed_candle_and_keeps_the_legacy_grid():
    clk, seen = Clock(ts("07:58", 30)), []

    def tick(boundary, now, legacy_due):
        seen.append((boundary, now, legacy_due))
        clk.t += 4                                            # a 4-second tick

    stats = pw.run_loop(tick, cfg=pw.PremarketConfig(), now_fn=clk.now, sleep_fn=clk.sleep, max_ticks=8)
    bounds = [b for b, _, _ in seen]
    assert bounds == [ts("07:59") + 60 * i for i in range(8)]
    assert all(now == b + 6 for b, now, _ in seen)            # settle_s after the boundary
    assert [d for b, _, d in seen if d] == [True, True]       # 08:00 and 08:05 only
    assert [datetime.fromtimestamp(b, ET).strftime("%H:%M") for b, _, d in seen if d] == ["08:00", "08:05"]
    assert stats["skipped_minutes"] == 0 and stats["stopped"] == "max_ticks"


def test_an_overrunning_tick_skips_minutes_and_never_overlaps():
    clk, seen = Clock(ts("08:00", 1)), []

    def tick(boundary, now, legacy_due):
        seen.append(boundary)
        if len(seen) == 2:
            clk.t += 130                                      # this minute's work took 2 min 10 s

    stats = pw.run_loop(tick, cfg=pw.PremarketConfig(), now_fn=clk.now, sleep_fn=clk.sleep, max_ticks=4)
    assert seen == sorted(set(seen))                          # strictly increasing: one tick at a time
    assert stats["skipped_minutes"] == 2
    assert seen[2] - seen[1] == 180


def test_loop_stops_at_window_end_and_on_the_kill_file():
    clk, seen = Clock(ts("09:28", 30)), []
    stats = pw.run_loop(lambda b, n, d: seen.append(b), cfg=pw.PremarketConfig(), now_fn=clk.now,
                        sleep_fn=clk.sleep, max_ticks=20)
    assert [datetime.fromtimestamp(b, ET).strftime("%H:%M") for b in seen] == ["09:29", "09:30"]
    assert stats["stopped"] == "window_closed"
    stats = pw.run_loop(lambda b, n, d: seen.append(b), cfg=pw.PremarketConfig(), now_fn=clk.now,
                        sleep_fn=clk.sleep, stop_fn=lambda: True)
    assert stats["stopped"] == "kill_file"


def test_a_second_run_finds_the_lock_held_and_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pw, "in_window", lambda *a, **k: True)
    monkeypatch.setattr(pw, "_run", lambda *a, **k: pytest.fail("must not run while another run holds the lock"))
    held = pw.RunLock(ma.journal_dir() / pw.RUN_LOCK_FILE)
    assert held.acquire()
    try:
        assert pw.main(["--apply", "--loop", "--symbols", "AAA"]) == 0
    finally:
        held.release()
    assert "SKIPPED_ALREADY_RUNNING" in capsys.readouterr().out
    again = pw.RunLock(ma.journal_dir() / pw.RUN_LOCK_FILE)
    assert again.acquire()
    again.release()


# ── lifecycle threading ────────────────────────────────────────────────────────────────────────────────────────

def test_lifecycle_threads_state_changes_once_each_on_closed_candles(tmp_path):
    ledger = um.Ledger(tmp_path / "ledger.jsonl")
    results, _ = play(tmp_path, ledger=ledger)
    got = [r["rows"][0]["state"] for r in results]
    assert got == [s for _, _, s in SCRIPT]
    rows = [r for r in ledger.rows(DAY) if r.get("origin") == pw.ORIGIN_1M]
    assert [r["state"] for r in rows] == ["WATCH", "APPROACHING", "ARMED", "TRIGGERED", "EXTENDED", "PULLBACK_ZONE",
                                          "STAND_DOWN"]
    # 08:06/08:07 repeat PULLBACK_ZONE: never re-sent. STAND DOWN is the 7th in the hour (cap 6) and still goes:
    # a correction of an alert already sent is never capped.
    assert all(r["action"] == "SHADOW_LOGGED" for r in rows)
    assert len({r["thread_key"] for r in rows}) == 1 and rows[0]["is_root"]
    assert all(r["would_reply_to"] == rows[0]["row_id"] for r in rows[1:])
    trig = next(r for r in results[3]["rows"])
    assert trig["features"]["prior_high"] == 3.00 and trig["candle_at"] == "08:02"   # the CLOSED 08:02 candle


def test_stand_down_after_closes_below_vwap(tmp_path):
    ledger = um.Ledger(tmp_path / "ledger.jsonl")
    cfg = pw.PremarketConfig(max_msgs_per_symbol_hour=10)
    results, _ = play(tmp_path, cfg=cfg, ledger=ledger)
    assert results[-1]["rows"][0]["state"] == "STAND_DOWN"
    assert "below PM VWAP" in results[-1]["rows"][0]["why"]
    states = [r["state"] for r in ledger.rows(DAY) if r.get("action") == "SHADOW_LOGGED"]
    assert states[-1] == "STAND_DOWN"


def test_pre_trigger_states_only_escalate():
    cfg = pw.PremarketConfig()
    feat = {"status": "OK", "last": 2.80, "prior_high": 3.0, "pm_high": 3.0, "dist_to_high_pct": 7.0,
            "vol_accel": 1.0, "below_vwap_bars": 0, "above_vwap": True, "candle_green": True, "gap_pct": 40}
    state, why, _ = pw.classify(feat, {"verdict": ma.ALERT, "veto_reasons": []}, {"state": "ARMED"}, cfg=cfg)
    assert state == "ARMED" and why.startswith("holding ARMED")
    state, _, _ = pw.classify(feat, {"verdict": ma.VETO, "veto_reasons": ["SPREAD_WIDE"]}, {"state": "ARMED"},
                              cfg=cfg)
    assert state == "ARMED"                                    # a soft veto for one minute is not a stand-down
    state, _, _ = pw.classify(feat, {"verdict": ma.VETO, "veto_reasons": ["GAP_SMALL"]}, {"state": "ARMED"},
                              cfg=cfg)
    assert state == "STAND_DOWN"


def test_hourly_cap_holds_the_fourth_message(tmp_path):
    ledger = um.Ledger(tmp_path / "ledger.jsonl")
    cfg = pw.PremarketConfig(max_msgs_per_symbol_hour=3)
    results, _ = play(tmp_path, cfg=cfg, ledger=ledger, upto=5)
    acts = [(r["state"], r["action"]) for r in ledger.rows(DAY)]
    assert acts[:3] == [("WATCH", "SHADOW_LOGGED"), ("APPROACHING", "SHADOW_LOGGED"), ("ARMED", "SHADOW_LOGGED")]
    assert acts[3] == ("TRIGGERED", "CAPPED_PER_HOUR")
    assert sum(1 for _, a in acts if a in um.EMITTED_ACTIONS) == 3


def test_every_message_carries_driven_by_ready_missing(tmp_path):
    ledger = um.Ledger(tmp_path / "ledger.jsonl")
    play(tmp_path, ledger=ledger, upto=4)
    for r in ledger.rows(DAY):
        lines = r["text"].splitlines()
        assert any(x.startswith("Driven by: ") for x in lines)
        assert any(x.startswith("Ready: ") for x in lines)
        assert any(x.startswith("Missing: ") for x in lines)
        assert lines[-1] == um.ADVISORY_LINE
    trig = [r for r in ledger.rows(DAY) if r["state"] == "TRIGGERED"][0]["text"]
    assert "RVOL 12.0x (scan)" in trig and "Book bid/ask" in trig and "Momentum evidence" in trig


def test_evidence_block_is_the_single_definition():
    ev = {"pillars": [{"id": "price", "label": "Price", "status": "PASSED", "value": 3.1},
                      {"id": "rvol", "label": "RVOL", "status": "PASSED", "value": 14},
                      {"id": "catalyst", "label": "Verified catalyst", "status": "UNKNOWN", "value": None}],
          "catalyst": {"text": None}, "passed_count": 2}
    b = mse.evidence_block(ev, extra_facts=[{"id": "tape", "label": "Tape buys", "status": "PASSED",
                                             "detail": "70%", "driver": True}])
    assert b["schema"] == "MomentumEvidenceBlock@v1"
    assert b["driven_by"] == ["RVOL 14x", "Tape buys 70%"]
    assert b["ready"] == ["Price 3.1", "RVOL 14x", "Tape buys 70%"]
    assert b["missing"] == ["Verified catalyst unknown"]
    assert mse.format_evidence_block(None).splitlines()[0] == "Driven by: —"


# ── rollout: shadow / live / legacy ────────────────────────────────────────────────────────────────────────────

def test_shadow_sends_nothing_new(tmp_path):
    sent = []
    ledger = um.Ledger(tmp_path / "ledger.jsonl")
    cfg = pw.PremarketConfig(mode="send", cadence_mode="shadow")
    play(tmp_path, cfg=cfg, ledger=ledger, send=lambda *a, **k: sent.append(a) or {}, upto=4)
    assert sent == []
    assert {r["mode"] for r in ledger.rows(DAY)} == {"shadow"}


def test_live_threads_replies_to_the_root(tmp_path):
    sent = []

    def send(text, *, priority, dedupe_minutes, reply_to, symbol):
        sent.append({"text": text, "priority": priority, "reply_to": reply_to})
        return {"accepted": True, "message_ids_by_chat": {"chat": str(100 + len(sent))}}

    ledger = um.Ledger(tmp_path / "ledger.jsonl")
    cfg = pw.PremarketConfig(mode="send", cadence_mode="live")
    play(tmp_path, cfg=cfg, ledger=ledger, send=send, upto=4)
    assert [s["reply_to"] for s in sent] == [None, {"chat": "101"}, {"chat": "101"}, {"chat": "101"}]
    assert {s["priority"] for s in sent} == {"P1"}            # 06:00-07:00 is inside the quiet hold: P1
    assert [r["action"] for r in ledger.rows(DAY)] == ["SENT"] * 4


def test_live_falls_back_to_the_legacy_transport_when_the_threaded_send_fails(tmp_path):
    fallback = []

    def broken(*a, **k):
        raise RuntimeError("gateway down")

    cfg = pw.PremarketConfig(mode="send", cadence_mode="live")
    results, _ = play(tmp_path, cfg=cfg, ledger=um.Ledger(tmp_path / "l.jsonl"), send=broken, upto=1,
                      fallback=lambda **k: fallback.append(k) or {"sent": True})
    assert results[0]["rows"][0]["action"] == "SEND_FAILED"
    assert fallback and fallback[0]["title"].startswith(ma.AT_SCALP_ALERT_HEADER)
    assert "WATCH" in fallback[0]["title"]


def test_cadence_plan():
    assert pw._cadence(pw.PremarketConfig(cadence_mode="legacy"), "shadow")["new_path"] is False
    sh = pw._cadence(pw.PremarketConfig(mode="send", cadence_mode="shadow"), "shadow")
    assert sh["legacy_sends"] and sh["emit_mode"] == "shadow"
    lv = pw._cadence(pw.PremarketConfig(mode="send", cadence_mode="live"), "shadow")
    assert lv["legacy_sends"] is False and lv["emit_mode"] == "live"
    assert pw._cadence(pw.PremarketConfig(mode="shadow", cadence_mode="live"), "shadow")["emit_mode"] == "shadow"
    off = pw._cadence(pw.PremarketConfig(mode="send", cadence_mode="live"), "off")
    assert off["emit"] is False and off["legacy_sends"] is True   # global unified kill switch: old path sends
    with pytest.raises(ValueError):
        pw.PremarketConfig.from_mapping({"cadence_mode": "fast"})


def _drive_run(monkeypatch, cadence):
    calls = {"legacy": [], "new": 0}

    def fake_eval(universe, **kw):
        calls["legacy"].append(kw.get("send_fn"))
        return []

    def fake_1m(pool, **kw):
        calls["new"] += 1
        return {"rows": [], "events": [], "focus": {"members": {}}, "plan": {}}

    class NoData:
        def close(self):
            pass

    monkeypatch.setattr(pw, "evaluate", fake_eval)
    monkeypatch.setattr(pw, "evaluate_1m", fake_1m)
    monkeypatch.setattr(pw, "PremarketMoomoo", lambda **k: NoData())
    monkeypatch.setattr(um, "resolve_mode", lambda *a, **k: "shadow")
    args = types.SimpleNamespace(apply=True, loop=False, as_of=None, symbols="AAA", max_ticks=None)
    cfg = pw.PremarketConfig(mode="send", cadence_mode=cadence)
    pw._run(args, cfg, now=ts("08:05", 1), day=DAY, as_of="08:05")
    return calls


def test_shadow_keeps_the_legacy_send_and_live_replaces_it(monkeypatch):
    legacy = _drive_run(monkeypatch, "legacy")
    assert legacy["legacy"] == [ma.telegram_send] and legacy["new"] == 0
    shadow = _drive_run(monkeypatch, "shadow")
    assert shadow["legacy"] == [ma.telegram_send] and shadow["new"] == 1
    live = _drive_run(monkeypatch, "live")
    assert live["legacy"] == [None] and live["new"] == 1          # journaled, not sent: the thread replaces it


# ── focus list ─────────────────────────────────────────────────────────────────────────────────────────────────

def ranked(order, feats=None):
    return [{"symbol": s, "rank": i, "score": 1.0 / i, "features": (feats or {}).get(s, {"rvol": 10, "change_pct": 20})}
            for i, s in enumerate(order, 1)]


def test_focus_size_cap_and_entry_reasons():
    cfg = sf.FocusConfig(size=3)
    st, ev = sf.update(None, ranked(list("ABCDEF"), {"A": {"rvol": 14, "change_pct": 22}}), now=ts("08:00"), cfg=cfg)
    assert sorted(st["members"]) == ["A", "B", "C"] and len(st["members"]) <= cfg.n
    assert ev[0]["event"] == "ENTER" and ev[0]["reason"] == "entered: RVOL 14x, +22%, rank 1"
    with pytest.raises(ValueError):
        sf.FocusConfig.from_mapping({"size": 31})
    assert sf.FocusConfig(size=99).n == sf.HARD_MAX


def test_focus_hysteresis_no_flapping_at_the_boundary():
    cfg = sf.FocusConfig(size=3, exit_minutes=5)
    st, _ = sf.update(None, ranked(list("ABCD")), now=ts("08:00"), cfg=cfg)
    events = []
    for i in range(10):                                         # C and D trade places at rank 3/4 every minute
        order = list("ABCD") if i % 2 else list("ABDC")
        st, ev = sf.update(st, ranked(order), now=ts("08:01") + 60 * i, cfg=cfg)
        events += ev
    assert events == [] and sorted(st["members"]) == ["A", "B", "C"]


def test_focus_leaves_after_m_minutes_below_exit_rank_with_reason():
    # displacement off (margin 30) so only the exit rule moves B; exit rank ceil(1.5 x 3) = 5
    cfg = sf.FocusConfig(size=3, exit_minutes=3, displace_margin_mult=10)
    st, _ = sf.update(None, ranked(list("ABCDEF")), now=ts("08:00"), cfg=cfg)
    order = list("ACDEFB")                                      # B falls to rank 6
    fade = {"B": {"above_vwap": False}}
    for i in range(2):
        st, ev = sf.update(st, ranked(order, fade), now=ts("08:01") + 60 * i, cfg=cfg)
        assert "B" in st["members"] and ev == []                # D waits: the list is full
    st, ev = sf.update(st, ranked(order, fade), now=ts("08:03"), cfg=cfg)
    assert [(e["event"], e["symbol"]) for e in ev] == [("LEAVE", "B"), ("ENTER", "D")]
    assert ev[0]["reason"] == "left: faded below VWAP, rank 6 for 3 min"


def test_focus_never_evicts_armed_or_triggered():
    cfg = sf.FocusConfig(size=2, exit_minutes=1)
    st, _ = sf.update(None, ranked(list("ABC")), now=ts("08:00"), cfg=cfg)
    for i in range(5):
        st, ev = sf.update(st, ranked(list("CDEFAB")), now=ts("08:01") + 60 * i, cfg=cfg,
                           states={"A": "ARMED", "B": "TRIGGERED"}, invalidated={"B": "price out of band"})
        assert sorted(st["members"]) == ["A", "B"]
        assert not [e for e in ev if e["event"] in ("LEAVE", "ENTER")]
    st, ev = sf.update(st, ranked(list("CDEFAB")), now=ts("08:10"), cfg=cfg, states={"A": "STAND_DOWN"})
    assert "A" not in st["members"] and any(e["reason"].startswith("left: stand-down") for e in ev)


def test_focus_full_list_displaces_only_a_clearly_weaker_member():
    cfg = sf.FocusConfig(size=4, exit_minutes=10)              # margin ceil(0.5 x 4) = 2, exit rank 6
    st, _ = sf.update(None, ranked(list("ABCDEFG")), now=ts("08:00"), cfg=cfg)
    st, ev = sf.update(st, ranked(list("ABCEDFG")), now=ts("08:01"), cfg=cfg)
    assert ev == []                                             # E at 4 vs D at 5: margin 1, E waits
    st, ev = sf.update(st, ranked(list("GABCEFD")), now=ts("08:02"), cfg=cfg)
    assert [(e["event"], e["symbol"]) for e in ev] == [("LEAVE", "D"), ("ENTER", "G")]
    assert ev[0]["reason"] == "left: displaced by G (rank 1) at rank 7"


def test_focus_store_round_trip_and_reader(tmp_path):
    st, ev = sf.update(None, ranked(list("AB")), now=ts("08:00"), cfg=sf.FocusConfig(size=2))
    sf.save(st, ev, day=DAY)
    view = sf.read_focus(now=ts("08:01"))
    assert view["status"] == "ok" and view["symbols"] == ["A", "B"]
    assert sf.read_focus(now=ts("08:10"))["status"] == "stale"
    assert [e["symbol"] for e in sf.recent_events(day=DAY)] == ["A", "B"]


def test_evaluate_1m_ranks_the_pool_and_keeps_the_top_n(tmp_path):
    pool = [{"symbol": s, "float_mm": 5.0, "rvol": r} for s, r in (("AAA", 40), ("BBB", 2), ("CCC", 9), ("BIG", 50))]
    data = FakeData({s: base_bars() for s in ("AAA", "BBB", "CCC", "BIG")},
                    snap={"BIG": {"prev_close": 2.0, "float_mm": 80.0, "pre_price": 2.6, "pre_volume": 1e6}})
    pool[3]["float_mm"] = 80.0
    res = run_tick(tmp_path, data, ts("08:00"), fcfg=sf.FocusConfig(size=2), pool=pool)
    assert sorted(res["focus"]["members"]) == ["AAA", "CCC"]   # BIG fails the float rule; BBB ranks third
    assert {r["symbol"] for r in res["rows"]} == {"AAA", "CCC"}
    focus = json.loads((tmp_path / "focus.json").read_text())
    assert focus["schema"] == sf.SCHEMA and focus["size"] == 2 and focus["pool_size"] == 3
    assert all(m["reason"].startswith("entered: ") for m in focus["members"].values())


# ── critique only for focus names ──────────────────────────────────────────────────────────────────────────────

def test_restrict_to_focus_and_fail_soft():
    fresh = {"status": "ok", "symbols": ["AAA", "CCC"]}
    kept, rep = sf.restrict_to_focus(["AAA", "BBB", {"symbol": "CCC"}], focus=fresh)
    assert kept == ["AAA", {"symbol": "CCC"}] and rep["dropped"] == ["BBB"] and rep["applied"]
    kept, rep = sf.restrict_to_focus(["AAA", "BBB"], focus={"status": "stale", "symbols": ["AAA"]})
    assert kept == ["AAA", "BBB"] and rep["applied"] is False
    kept, _ = sf.restrict_to_focus(["AAA", "BBB"], focus=fresh, cfg=sf.FocusConfig(critique_gate="all"))
    assert kept == ["AAA", "BBB"]


def test_hermes_scalp_research_runs_only_for_focus_names(tmp_path, monkeypatch):
    import hermes_momentum_catalyst_researcher as H

    st, ev = sf.update(None, ranked(["AAA", "CCC"]), now=datetime.now(ET).timestamp(), cfg=sf.FocusConfig(size=2))
    sf.save(st, ev, day=DAY)
    researched = []
    monkeypatch.setattr(H, "_hot_research_on", lambda: False)
    monkeypatch.setattr(H, "get_scalp_candidates", lambda **k: ["AAA", "BBB", "CCC", "DDD"])
    monkeypatch.setattr(H, "active_trader_hot_symbols", lambda **k: [])
    monkeypatch.setattr(H, "run", lambda cands, **k: researched.extend(cands) or [])
    from lib import hermes_catalyst_store as store
    monkeypatch.setattr(store, "day_file", lambda d: tmp_path / "cat.jsonl")
    monkeypatch.setattr(store, "legacy_day_file", lambda d, root: tmp_path / "cat_legacy.jsonl")
    out = H._execute(types.SimpleNamespace(source="scalp", max_tickers=5, apply=False, on_list_advance=False))
    assert researched == ["AAA", "CCC"]
    assert out["focus_gate_applied"] is True and out["focus_gate_skipped"] == 2


# ── comparison report ──────────────────────────────────────────────────────────────────────────────────────────

def test_comparison_report_lists_latency_gained(tmp_path):
    import premarket_cadence_compare as C

    journal = tmp_path / "j.jsonl"
    journal.write_text("\n".join(json.dumps(r) for r in [
        {"kind": "PREMARKET_WATCH", "verdict": "ALERT", "sent": True, "ts_epoch": ts("08:05"),
         "candidate": {"symbol": "AAA", "session_date": DAY}},
        {"kind": "PREMARKET_WATCH", "verdict": "VETO", "ts_epoch": ts("08:00"),
         "candidate": {"symbol": "AAA", "session_date": DAY}}]) + "\n")
    ledger = um.Ledger(tmp_path / "ledger.jsonl")
    play(tmp_path, ledger=ledger, upto=4)
    focus_events = tmp_path / "focus_events.jsonl"
    rep = C.compare(DAY, journal=journal, ledger=ledger.path, focus_events=focus_events)
    row = rep["rows"][0]
    assert row["symbol"] == "AAA" and row["old_first"] == "08:05" and row["new_first"] == "08:00"
    assert row["latency_gained_min"] == 5.0 and row["new_messages"] == 4 and row["old_alerts"] == 1
    assert row["focus"][0].startswith("08:00 entered: ")
    assert "AAA" in C.render(rep)


# ── operator crontab packet ────────────────────────────────────────────────────────────────────────────────────

PKT = ROOT / "docs" / "ops" / "packets" / "premarket-1min-20261023" / "install.sh"
OLD_PM = ("*/5 6-9 * * 1-5 cd $PROJ && flock -n /tmp/at_premarket.lock timeout 240 $PY "
          "scripts/active_trader/premarket_watch.py --apply >> logs/at_premarket_watch.log 2>&1")
OLD_FV = ("*/5 6-11 * * 1-5 cd $PROJ && flock -n /tmp/tradeai_finviz_momentum_scalp.lock timeout 280 env "
          "MOMENTUM_SCALP_OUTER_DEADLINE_S=260 $PY scripts/run_finviz_momentum_scalp_scan.py --window early --apply "
          "--refresh-if-older-min 15 --sync-signals --generate-proposals --run-validation-fast-path >> "
          "logs/finviz_momentum_scalp_scan.log 2>&1")
FAKE = r'''#!{py}
import signal, sys
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
state = {state!r}
if sys.argv[1:] == ["-l"]:
    data = open(state, "rb").read()
    for i in range(0, len(data), 4096):
        sys.stdout.buffer.write(data[i:i + 4096]); sys.stdout.buffer.flush()
elif sys.argv[1:] == ["-"]:
    open(state, "wb").write(sys.stdin.buffer.read())
else:
    sys.exit(2)
'''


def _packet(tmp_path, content, *args, answer="APPLY\n"):
    state = tmp_path / "crontab.state"
    state.write_text(content)
    fake = tmp_path / "crontab"
    fake.write_text(FAKE.format(py=sys.executable, state=str(state)))
    fake.chmod(0o755)
    host = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
    import getpass
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "CRONTAB_BIN": str(fake), "EXPECT_HOST": host,
           "EXPECT_USER": getpass.getuser(), "PROJ_OVERRIDE": str(ROOT), "FORCE_IN_WINDOW": "1", "LC_ALL": "C"}
    (tmp_path / "home").mkdir(exist_ok=True)
    p = subprocess.run(["bash", str(PKT), *args], input=answer, capture_output=True, text=True, env=env, timeout=120)
    return p, state


def _crontab_text():
    pad = "\n".join(["# padding line so the crontab is as large as the operator's ----------------------"] * 3000)
    return f"PROJ={ROOT}\nPY={sys.executable}\n{OLD_FV}\n{pad}\n{OLD_PM}\n"


def test_packet_preview_changes_nothing(tmp_path):
    p, state = _packet(tmp_path, _crontab_text(), "--preview")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "PREVIEW ONLY" in p.stdout and state.read_text() == _crontab_text()
    assert "--refresh-if-older-min 5" in p.stdout and "--apply --loop" in p.stdout
    assert list((tmp_path / "home" / ".cache").glob("crontab.bak-*"))


def test_packet_apply_verifies_from_a_captured_file_and_is_idempotent(tmp_path):
    p, state = _packet(tmp_path, _crontab_text())
    assert p.returncode == 0, p.stdout + p.stderr
    assert "VERIFIED: 2 edit(s)" in p.stdout and "FAILED" not in p.stdout
    lines = state.read_text().splitlines()
    assert OLD_PM not in lines and OLD_FV not in lines
    assert OLD_PM.replace("timeout 240", "timeout 13200").replace("--apply >>", "--apply --loop >>") in lines
    assert sum("run_finviz_momentum_scalp_scan.py --window early" in x for x in lines) == 2
    backup = list((tmp_path / "home" / ".cache").glob("crontab.bak-*"))[0]
    assert backup.read_text() == _crontab_text()
    p2, state2 = _packet(tmp_path, state.read_text())
    assert p2.returncode == 0 and "already applied" in p2.stderr + p2.stdout


def test_packet_refuses_when_the_exact_text_is_not_found(tmp_path):
    p, state = _packet(tmp_path, _crontab_text().replace("timeout 240", "timeout 250"))
    assert p.returncode != 0 and "REFUSED" in p.stdout + p.stderr
    assert "timeout 250" in state.read_text()


def test_packet_never_pipes_crontab_into_an_early_exit_reader():
    text = PKT.read_text()
    assert "crontab -l |" not in text and '"$CRONTAB_BIN" -l |' not in text
    assert "set -euo pipefail" in text


def test_registry_rows_carry_the_pending_packet():
    rows = {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}
    pm = rows["active-trader-premarket-watch"]
    assert pm["pending_change"]["packet"] == "docs/ops/packets/premarket-1min-20261023/install.sh"
    assert pm["scheduler"]["match"] in pm["pending_change"]["command_text"]
    fv = rows["finviz-momentum-scalp-early-lane"]
    assert all(fv["scheduler"]["match"] in line for line in fv["pending_change"]["lines"])
    pkt = PKT.read_text()
    assert all(line in pkt for line in fv["pending_change"]["lines"])
    assert pm["pending_change"]["command_text"] in pkt


def test_no_broker_reach():
    for path in ("scripts/lib/scalp_focus.py", "scripts/premarket_cadence_compare.py"):
        src = (ROOT / path).read_text()
        for word in ("place_order", "trade_ctx", "OpenSecTradeContext", "unlock_trade", "submit_order"):
            assert word not in src
    src = (ROOT / "scripts/active_trader/premarket_watch.py").read_text()
    assert "place_order" not in src and "unlock_trade" not in src and "TradeContext" not in src


def test_a_fading_watch_is_dropped_quietly_and_a_stand_down_cools_off():
    """Replay 2026-10-23 (read-only, 14 recorder names): names oscillating around PM VWAP chattered WATCH <-> STAND
    DOWN (36 messages); a plain WATCH that fades is now dropped without a message and a STAND DOWN holds for
    reopen_after_min (15 messages)."""
    cfg = pw.PremarketConfig()
    faded = {"status": "OK", "last": 2.3, "prior_high": 3.0, "pm_high": 3.0, "below_vwap_bars": 2,
             "above_vwap": False, "boundary_epoch": ts("08:00")}
    veto = {"verdict": ma.VETO, "veto_reasons": ["BELOW_PM_VWAP"]}
    state, why, mem = pw.classify(faded, veto, {"state": "WATCH", "emitted_state": "WATCH"}, cfg=cfg)
    assert state is None and why.startswith("watch dropped") and mem == {"emitted_state": "WATCH"}
    state, _, mem = pw.classify(faded, veto, {"state": "APPROACHING"}, cfg=cfg)
    assert state == "STAND_DOWN" and mem["stood_down_at"] == ts("08:00")
    ok = {"verdict": ma.ALERT, "veto_reasons": []}
    back = {"status": "OK", "last": 2.8, "prior_high": 3.0, "pm_high": 3.0, "dist_to_high_pct": 7.0,
            "below_vwap_bars": 0, "above_vwap": True, "vol_accel": 1.0, "gap_pct": 40}
    state, why, _ = pw.classify({**back, "boundary_epoch": ts("08:05")}, ok, mem, cfg=cfg)
    assert state == "STAND_DOWN" and why == "cooling off after stand-down"
    state, _, _ = pw.classify({**back, "boundary_epoch": ts("08:10")}, ok, mem, cfg=cfg)
    assert state == "WATCH"


def test_a_stood_down_name_does_not_re_enter_the_focus_list_while_cooling_off(tmp_path):
    life = tmp_path / "life.json"
    pw.save_lifecycle(life, DAY, {"AAA": {"state": "STAND_DOWN", "stood_down_at": ts("07:58")}})
    data = FakeData({"AAA": base_bars()})
    res = run_tick(tmp_path, data, ts("08:00"))
    assert res["focus"]["members"] == {}
    res = run_tick(tmp_path, data, ts("08:09"))
    assert "AAA" in res["focus"]["members"]
