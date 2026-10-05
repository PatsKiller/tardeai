"""Active Trader alert sync (operator 2026-10-05, XNDU: "the optimum time to get in was 10 a.m. We
need to synchronize and coordinate"; "even something getting ready to fire — a minute may be too
long"; HARD RULE: "the source of truth should be the Command Center for all data … each individual
process should not be going out looking for its own data sources").

Replays today's XNDU 1-min bars (Alpaca IEX fixture) through the sub-minute loop, the shared
state-aware throttle, the chase guard and the buy-zone watch. Intrabar prices follow the documented
path in fast_trigger_loop.intrabar_path (no tick history). Fakes only: no OpenD, no DB, no Telegram.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import fast_trigger_loop as ftl  # noqa: E402
from active_trader import momentum_alerts as ma  # noqa: E402
from lib.data_broker import microstructure as store  # noqa: E402

ET = ZoneInfo("America/New_York")
CFG = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text(encoding="utf-8"))
FIX = json.loads((ROOT / "tests" / "fixtures" / "active_trader" / "xndu_20261005_1m_iex.json").read_text())
BARS = FIX["bars"]


def ep(hms: str) -> float:
    h, m, s = (int(x) for x in hms.split(":"))
    return datetime(2026, 10, 5, h, m, s, tzinfo=ET).timestamp()


def at(row) -> str:
    return datetime.fromtimestamp(row["ts_epoch"], ET).strftime("%H:%M:%S")


@pytest.fixture(autouse=True)
def _dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACTIVE_TRADER_ALERTS_DIR", str(tmp_path / "at"))
    return tmp_path / "at"


BOOK = lambda s: {"bids": [[100.0 - i * 0.01, 5000] for i in range(10)],  # noqa: E731
                  "asks": [[100.01 + i * 0.01, 2000] for i in range(10)], "ts_epoch": 1e12, "ts_source": "test"}
TAPE = lambda s: [{"ts_epoch": 1e12, "price": 100.0, "volume": 100, "direction": "BUY"}] * 50  # noqa: E731


def pass5_0955():
    """The real 5-min pass at 09:55:11: the 09:51 fire, entry 4.375, stop floored to the minimum
    distance (1 % of price → R 0.04375), last 4.43 from the live quote."""
    entry, r = 4.375, 0.04375
    return ep("09:55:11"), ma.Candidate(symbol="XNDU", lane="BELOW", ign=18.4, fsm_state="IMPULSE",
                                        last=4.43, entry_ref=entry, stop_ref=round(entry - r, 5),
                                        quote_ts_epoch=ep("09:55:07"), fire_ts_epoch=ep("09:51:00"),
                                        session_date="2026-10-05")


def run_replay(sent=None):
    calls = sent if sent is not None else []
    return ftl.replay(BARS, engine_cfg=CFG, acfg=ma.AlertConfig(mode="send"),
                      fcfg=ftl.FastLoopConfig.from_mapping(CFG.get("active_trader_fast_loop")), symbol="XNDU",
                      book_fn=BOOK, tape_fn=TAPE, extra_passes=[pass5_0955()], end=ep("10:12:00"),
                      send_fn=lambda **kw: calls.append(kw) or {"sent": True})


def test_xndu_replay_timeline():
    rows = [r for r in run_replay() if r["verdict"] == ma.ALERT]
    tl = [(at(r), r["kind"]) for r in rows]
    kinds = [k for _, k in tl]
    # APPROACHING before each fire
    assert any(k == ma.APPROACHING and t < "09:51:00" for t, k in tl)
    assert any(k == ma.APPROACHING and "09:59:00" <= t < "10:05:00" for t, k in tl)
    # the 09:51 fire is alerted inside its own bar (live: 09:55:11)
    trig1 = next(r for r in rows if r["kind"] == ma.TRIGGERED)
    assert "09:51:00" <= at(trig1) < "09:52:05" and trig1["candidate"]["intrabar"]
    assert trig1["latency"]["event"] == "break_print" and trig1["latency"]["latency_s"] <= 60
    # 09:55:11: last 4.43 vs entry 4.375 is EXTENDED with a buy zone, not TIME TO BUY
    ext = next(r for r in rows if r["kind"] == ma.EXTENDED)
    assert "09:55:00" <= at(ext) <= "09:55:11" and ext["candidate"]["zone_low"] < 4.40 <= ext["candidate"]["zone_high"] + 0.01
    assert "don't chase" in ext["message"]["title"]
    # the pullback into the zone at 09:59–10:00 is alerted, not swallowed by a cooldown
    pz = next(r for r in rows if r["kind"] == ma.PULLBACK_ZONE)
    assert "09:59:00" <= at(pz) <= "10:00:59" and 4.38 <= pz["candidate"]["last"] <= 4.40
    # the 10:05 fire inside its bar (live: 10:10:15, vetoed)
    assert any(k == ma.TRIGGERED and "10:05:00" <= t < "10:06:05" for t, k in tl)
    # no exact repeats
    keys = [(r["kind"], r["level_key"]) for r in rows]
    assert len(keys) == len(set(keys)), keys
    assert kinds.count(ma.EXTENDED) == 1 and kinds.count(ma.PULLBACK_ZONE) == 1


def test_messages_keep_the_editor_exemption_header():
    sent = []
    run_replay(sent)
    assert sent and all(m["title"].startswith(ma.AT_SCALP_ALERT_HEADER) for m in sent)
    assert all(ma.NOT_AN_ORDER in m["body"] for m in sent)
    assert any("APPROACHING" in m["title"] for m in sent) and any("intrabar" in m["title"] for m in sent)


def test_5min_pass_does_not_repeat_a_fire_the_fast_loop_alerted(_dir):
    run_replay()
    n = len((_dir / "momentum_alerts.jsonl").read_text().splitlines())
    # 10:10:15 pass re-sees the 10:05 fire with last 4.475 vs entry 4.485 → same fire, same kind
    c = ma.Candidate(symbol="XNDU", lane="BELOW", ign=21.6, fsm_state="PULLBACK", last=4.475, entry_ref=4.485,
                     stop_ref=4.4401, quote_ts_epoch=ep("10:10:13"), fire_ts_epoch=ep("10:05:00"),
                     session_date="2026-10-05")
    rows = ma.evaluate_pass([c], cfg=ma.AlertConfig(), now=ep("10:10:15"), fetch_primary_book=BOOK,
                            fetch_primary_tape=TAPE)
    assert rows == [] and len((_dir / "momentum_alerts.jsonl").read_text().splitlines()) == n


def test_state_aware_throttle_allows_new_levels_and_upgrades():
    th = ma.Throttle({}, ma.AlertConfig())
    th.record("XNDU", ma.ARMED, ep("09:50:13"), "entry:4.32")
    assert th.check("XNDU", ma.ARMED, ep("10:00:22"), "entry:4.38") is None        # new level (was COOLDOWN)
    assert th.check("XNDU", ma.TRIGGERED, ep("09:55:11"), "fire:1") is None        # upgrade
    assert th.check("XNDU", ma.ARMED, ep("09:55:11"), "entry:4.32") == "DUPLICATE"
    assert ma.Throttle({}, ma.AlertConfig(max_alerts_per_hour=0)).check("A", ma.ARMED, 0, "x") == "RATE_LIMIT"


def test_intrabar_trigger_that_fails_at_the_close_is_cancelled():
    st, fcfg = ftl.SymbolState(), ftl.FastLoopConfig()
    i = next(k for k, b in enumerate(BARS) if b["t"] == ep("09:51:00"))
    closed, bar = BARS[:i], dict(BARS[i])
    forming = {**bar, "c": bar["h"], "v": bar["v"]}
    c1 = ftl.step("XNDU", closed, forming, now=bar["t"] + 50, last=bar["h"], quote_ts=bar["t"] + 50, ticks=[],
                  engine_cfg=CFG, fcfg=fcfg, state=st, zones={})
    assert [c.kind_hint for c in c1] == [ma.TRIGGERED] and c1[0].intrabar
    failed = {**bar, "c": bar["l"] - 0.05, "l": bar["l"] - 0.05, "v": 10}   # closed weak, no volume
    c2 = ftl.step("XNDU", [*closed, failed], None, now=bar["t"] + 61, last=failed["c"], quote_ts=bar["t"] + 61,
                  ticks=[], engine_cfg=CFG, fcfg=fcfg, state=st, zones={})
    assert [c.kind_hint for c in c2] == [ma.TRIGGER_CANCELLED]


def test_latency_is_journaled():
    rows = [r for r in run_replay() if r["verdict"] == ma.ALERT and r["kind"] == ma.TRIGGERED]
    assert rows and all(r["latency"]["latency_s"] is not None for r in rows)
    lat = [r["latency"]["latency_s"] for r in rows]
    assert max(lat) <= 60, lat


# ── HARD RULE: the fast loop reads only the Command Center store ─────────────────

PROVIDER_MODULES = ("futu", "moomoo", "alpaca", "alpaca_trade_api", "schwab", "schwab_transport", "requests",
                    "httpx", "urllib3", "aiohttp", "yfinance", "active_trader.momentum_alert_sources",
                    "scalp_shadow_logger", "symbol_volume_profile_builder")


@pytest.mark.parametrize("rel", ["scripts/active_trader/fast_trigger_loop.py", "scripts/lib/data_broker/microstructure.py"])
def test_consumer_imports_no_provider_client(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module)
    bad = [m for m in names for p in PROVIDER_MODULES if m == p or m.startswith(p + ".") or m.endswith("." + p)]
    assert not bad, bad


def test_importing_the_fast_loop_loads_no_provider_module():
    code = ("import sys; sys.path.insert(0, 'scripts'); import active_trader.fast_trigger_loop; "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('futu','moomoo','alpaca','alpaca_trade_api',"
            "'schwab','requests','httpx','aiohttp','yfinance') or m.endswith('momentum_alert_sources') "
            "or m == 'scalp_shadow_logger']; print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_store_fails_closed_when_stale(_dir):
    day, now = "2026-10-05", ep("10:00:00")
    d = _dir / "micro" / day
    d.mkdir(parents=True)
    (d / "XNDU.jsonl").write_text(json.dumps({"t": now - 40, "b": [[4.39, 100]], "a": [[4.40, 100]], "l": 4.39,
                                              "qt": now - 40, "k": []}) + "\n")
    (d / "XNDU.bars.json").write_text(json.dumps({"t": now - 40, "rows": [{"s": now - 120, "o": 1, "h": 1, "l": 1,
                                                                            "c": 1, "v": 1}]}))
    assert store.book(day, "XNDU", now=now, max_age_s=15) is None
    assert store.quote(day, "XNDU", now=now, max_age_s=15) == (None, None)
    env = store.bars(day, "XNDU", now=now, max_age_s=15)
    assert env["status"] == "stale" and env["closed"] == [] and env["age_s"] == 40
    fresh = store.bars(day, "XNDU", now=now - 30, max_age_s=15)
    assert fresh["status"] == "ok" and len(fresh["closed"]) == 1


def test_on_tick_skips_stale_symbols_and_never_alerts(_dir):
    tick = ftl.ticker(CFG, send_fn=lambda **kw: pytest.fail("must not send on stale data"))
    res = tick(ep("10:00:00"), ["XNDU"])
    assert res["stale"] and res["stale"][0]["symbol"] == "XNDU" and res["rows"] == 0


def test_intrabar_path_assumption_is_documented_and_bounded():
    pts = ftl.intrabar_path({"o": 4.40, "h": 4.42, "l": 4.38, "c": 4.41, "v": 1200}, 12)
    assert pts[-1] == (60.0, 4.41, 1200.0)
    assert min(p for _, p, _ in pts) >= 4.38 and max(p for _, p, _ in pts) <= 4.42
    assert "ASSUMPTION" in ftl.intrabar_path.__doc__


# ── API + recorder hand-off ───────────────────────────────────────────────────

def test_api_carries_sync_fields_and_latency_percentiles(_dir):
    from active_trader import momentum_alerts_api as api
    rows = run_replay()
    alert_rows = [r for r in rows if r["verdict"] == ma.ALERT]
    s = api.latency_summary(alert_rows)
    assert s["all"]["n"] >= 3 and s["source:fast"]["p50_s"] is not None and s["all"]["p90_s"] >= s["all"]["p50_s"]
    trig = next(r for r in alert_rows if r["kind"] == ma.TRIGGERED)
    v = api._compact(trig, None)
    assert v["source"] == "fast" and v["intrabar"] and v["latency"]["event"] == "break_print"
    assert v["latency"]["event_at"].startswith("2026-10-05T09:51")
    ext = api._compact(next(r for r in alert_rows if r["kind"] == ma.EXTENDED), None)
    assert ext["zone"]["low"] < ext["zone"]["high"]


class _FakeProducer:
    """Recorder source (the ONLY place provider data enters): book, prints, last, 1-min bars."""

    def __init__(self, bars, now_fn):
        self.bars, self.now_fn = bars, now_fn

    def book(self, symbol, now=None):
        return {"bids": [[4.39, 9000]], "asks": [[4.40, 3000]], "ts_epoch": self.now_fn(), "ts_source": "test"}

    def tape(self, symbol):
        return [{"ts_epoch": self.now_fn() - 1, "price": 4.40, "volume": 300, "direction": "BUY"}]

    def quote(self, symbol):
        return 4.40, self.now_fn() - 1

    def bars_1m(self, symbol):
        return [{"s": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
                for b in self.bars if b["t"] <= self.now_fn()]


def test_recorder_publishes_and_fast_loop_consumes_on_the_same_tick(_dir):
    from active_trader import microstructure_recorder as rec
    clock = [ep("10:00:20")]
    src = _FakeProducer(BARS, lambda: clock[0])
    got = []
    tick = ftl.ticker(CFG, send_fn=lambda **kw: got.append(kw) or {"sent": True})

    def on_tick(now, symbols):
        got.append(tick(now, symbols))

    rcfg = rec.RecorderConfig(interval_s=5.0)
    rec.run(rcfg=rcfg, symbols_fn=lambda: ["XNDU"], src=src, now_fn=lambda: clock[0],
            sleep_fn=lambda s: clock.__setitem__(0, clock[0] + 5.0), window=("09:30", "12:00"),
            max_seconds=6, on_tick=on_tick, out=lambda *a: None)
    assert (_dir / "micro" / "2026-10-05" / "XNDU.bars.json").exists()
    results = [g for g in got if isinstance(g, dict) and "candidates" in g]
    assert results and not results[0]["stale"]
    sent = [g for g in got if isinstance(g, dict) and "title" in g]
    assert any("APPROACHING" in m["title"] for m in sent)   # 10:00:20 at 4.40 under the 4.405 break
