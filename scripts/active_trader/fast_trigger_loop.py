#!/usr/bin/env python3
"""Sub-minute alert sync for the momentum-scalp engine (operator 2026-10-05).

Why: on 2026-10-05 XNDU's entry trigger fired on the 09:51 bar but the 5-minute engine pass only
alerted at 09:55:11, with price already 2.5 % past entry; a flat 15-minute cooldown then hid the
10:00 heads-up at the 4.38–4.40 pullback the operator called the optimum entry. "We need to
synchronize and coordinate." This loop evaluates the hot names every recorder tick (~5 s):

  APPROACHING        the trigger state machine is ARMED and price is within reach of the break
                     level (prior bar high) — "about to fire"
  TRIGGERED intrabar the FORMING bar meets every trigger condition (break, close in the top third,
                     volume) — provisional, confirmed or cancelled at the bar close
  TRIGGER_CANCELLED  a provisional TRIGGERED that did not hold at the close
  EXTENDED / PULLBACK_ZONE   chase guard + buy-zone watch (momentum_alerts.apply_chase_guard)

DATA (operator hard rule 2026-10-05): this module is a pure CONSUMER of the Command Center store.
It reads the microstructure recorder's published book / prints / last / 1-min bars only through
lib.data_broker.microstructure and opens no provider connection of its own. A store older than
the freshness contract (`max_store_age_s`) fails closed: the symbol is skipped and marked stale.

Runs inside the recorder process on its tick (no extra daemon, no extra subscription); `--replay`
replays a 1-min bar fixture with a documented intrabar path for tests and audits. ALERTS ONLY —
no order path, no broker session, no trade context.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from active_trader import momentum_alerts as ma
    from lib.data_broker import microstructure as store
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma
    from scripts.lib.data_broker import microstructure as store
import scalp_trigger_engine as trig  # noqa: E402  (pure state machine)
from scalp_min_stop import apply_min_stop  # noqa: E402  (pure)

ET = ZoneInfo("America/New_York")
HEARTBEAT_FILE = "momentum_alerts_fastloop_heartbeat.json"
KILL_FILE = "FAST_LOOP_DISABLED"


@dataclass(frozen=True)
class FastLoopConfig:
    """`active_trader_fast_loop:` in config/scalp_signal_engine.yaml overrides any field.
    Mode (shadow/send) follows `active_trader_alerts.mode`."""
    enabled: bool = True
    window_et: tuple = ("09:30", "11:55")    # the RTH engine window; premarket is premarket_watch
    session_open_et: str = "09:30"
    max_symbols: int = 10
    max_store_age_s: float = 15.0            # freshness contract on the recorder store
    near_trigger_pct: float = 0.5            # APPROACHING: within this % below the break level ...
    near_trigger_ticks: int = 3              # ... or within this many ticks
    tick_size: float = 0.01
    approach_states: tuple = ("ARMED",)
    min_closed_bars: int = 5
    extended_watch_min: float = 15.0         # after a fire, watch this long for a run past entry (EXTENDED)

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "FastLoopConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in (raw or {}).items() if k in known})


@dataclass
class SymbolState:
    """Per-symbol memory between ticks (in-process; the throttle file guards against repeats
    across restarts and across the 5-min pass)."""
    alerted_fires: set = field(default_factory=set)       # fire bar starts already alerted
    provisional: dict = field(default_factory=dict)       # fire bar start -> intrabar alert info
    break_seen: dict = field(default_factory=dict)        # forming bar start -> first break print ts
    fires: dict = field(default_factory=dict)             # alerted fire start -> {entry, stop, at}


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def in_window(now: float, window: Sequence[str]) -> bool:
    t = datetime.fromtimestamp(now, ET)
    return _hm(window[0]) <= (t.hour, t.minute) < _hm(window[1])


def session_open_epoch(now: float, cfg: FastLoopConfig) -> float:
    d = datetime.fromtimestamp(now, ET)
    h, m = _hm(cfg.session_open_et)
    return d.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()


def _first_break(ticks: Sequence[Mapping[str, Any]], level: float, since: float, until: float) -> Optional[float]:
    for t in ticks:
        ts, px = t.get("ts_epoch"), t.get("price")
        if ts is not None and px is not None and since <= ts <= until and float(px) > level:
            return float(ts)
    return None


def _fire_at(result: dict, idx: int) -> Optional[dict]:
    for ev in result.get("events") or []:
        if ev.get("fire_idx") == idx and ev.get("outcome") == trig.TRIGGERED:
            return ev
    return None


def _floored(ev_entry: float, ev_stop: float, atr: Optional[float], spread_bps: Optional[float],
             engine_cfg: Mapping[str, Any]) -> tuple[float, float]:
    ms = apply_min_stop(round(ev_entry, 4), round(ev_stop, 4), atr, spread_bps, dict(engine_cfg))
    return round(ms["entry"], 4), round(ms["stop"], 4)


def step(symbol: str, closed: Sequence[Mapping[str, Any]], forming: Optional[Mapping[str, Any]], *,
         now: float, last: Optional[float], quote_ts: Optional[float], ticks: Sequence[Mapping[str, Any]],
         engine_cfg: Mapping[str, Any], fcfg: FastLoopConfig, state: SymbolState,
         zones: Mapping[str, Any], spread_bps: Optional[float] = None, day: Optional[str] = None) -> list:
    """Pure: one evaluation of one symbol. Returns momentum_alerts.Candidate objects (kinds set via
    kind_hint) for evaluate_pass to decide, throttle, journal and send."""
    out: list = []
    if len(closed) < fcfg.min_closed_bars:
        return out
    tr_closed = trig.run_trigger_engine(list(closed), engine_cfg)
    fin = tr_closed.get("final") or {}
    prev_high = fin.get("prev_high")

    def cand(kind: str, **kw):
        base = dict(symbol=symbol, lane="FAST", ign=0.0, fsm_state=str(fin.get("state") or "IDLE"),
                    last=last, quote_ts_epoch=quote_ts, session_date=day, kind_hint=kind, source="fast")
        base.update(kw)
        return ma.Candidate(**base)

    # 1) provisional intrabar alerts whose bar has now closed: confirm or cancel
    last_closed_start = closed[-1]["t"]
    for bar_start, prov in list(state.provisional.items()):
        if last_closed_start < bar_start:
            continue
        idx = next((i for i, b in enumerate(closed) if b["t"] == bar_start), None)
        if idx is not None and _fire_at(tr_closed, idx):
            state.alerted_fires.add(bar_start)
            state.fires[bar_start] = {"entry": prov.get("entry"), "stop": prov.get("stop"), "at": now}
        else:
            out.append(cand(ma.TRIGGER_CANCELLED, fire_ts_epoch=bar_start, entry_ref=prov.get("entry"),
                            stop_ref=prov.get("stop"), break_level=prov.get("break_level"),
                            level_key=f"fire:{int(bar_start)}"))
        del state.provisional[bar_start]

    # 2) a fire on the bar that just closed and was not alerted intrabar
    ev = _fire_at(tr_closed, len(closed) - 1)
    if ev and last_closed_start not in state.alerted_fires:
        entry, stop = _floored(ev["entry"], ev["stop"], fin.get("atr"), spread_bps, engine_cfg)
        out.append(cand(ma.TRIGGERED, fire_ts_epoch=last_closed_start, entry_ref=entry, stop_ref=stop,
                        break_level=closed[-2]["h"] if len(closed) > 1 else None))
        state.alerted_fires.add(last_closed_start)
        state.fires[last_closed_start] = {"entry": entry, "stop": stop, "at": now}

    # 2b) a recent fire that price has since run away from → EXTENDED (+ buy zone) through the
    #     chase guard in evaluate_pass; if not extended it is the same TRIGGERED and is skipped there
    for fstart_, f in list(state.fires.items()):
        if now - f["at"] > fcfg.extended_watch_min * 60:
            del state.fires[fstart_]
        elif last is not None and f.get("entry") is not None and last > f["entry"]:
            out.append(cand(ma.TRIGGERED, fire_ts_epoch=fstart_, entry_ref=f["entry"], stop_ref=f["stop"],
                            break_ts_epoch=now))   # if it becomes EXTENDED: detected this tick

    if forming is None:
        return out
    fstart = forming["t"]
    # first print through the break level in the forming bar (market time) — for the latency proof
    if prev_high is not None and fstart not in state.break_seen:
        bt = _first_break(ticks, prev_high, fstart, now)
        if bt is None and last is not None and last > prev_high:
            bt = now
        if bt is not None:
            state.break_seen[fstart] = bt
    for k in [k for k in state.break_seen if k < fstart - 600]:
        del state.break_seen[k]

    # 3) intrabar: the forming bar meets every trigger condition right now
    if fstart not in state.alerted_fires and fstart not in state.provisional:
        tr_f = trig.run_trigger_engine([*closed, dict(forming)], engine_cfg)
        evf = _fire_at(tr_f, len(closed))
        if evf:
            entry, stop = _floored(evf["entry"], evf["stop"], fin.get("atr"), spread_bps, engine_cfg)
            out.append(cand(ma.TRIGGERED, fire_ts_epoch=fstart, entry_ref=entry, stop_ref=stop, intrabar=True,
                            break_level=prev_high, break_ts_epoch=state.break_seen.get(fstart)))
            state.provisional[fstart] = {"entry": entry, "stop": stop, "break_level": prev_high, "at": now}
            state.fires[fstart] = {"entry": entry, "stop": stop, "at": now}
            return out

    # 4) APPROACHING: armed and within reach of the break level, not yet through it
    if (str(fin.get("state")) in fcfg.approach_states and prev_high is not None and last is not None
            and last <= prev_high):
        reach = max(prev_high * fcfg.near_trigger_pct / 100.0, fcfg.near_trigger_ticks * fcfg.tick_size)
        if prev_high - last <= reach:
            entry = round(prev_high + float(engine_cfg["trigger"]["entry_offset"]), 4)
            pb = fin.get("pullback_low")
            raw_stop = (pb - float(engine_cfg["trigger"]["stop_offset"])) if pb is not None else None
            stop = None
            if raw_stop is not None:
                entry, stop = _floored(entry, raw_stop, fin.get("atr"), spread_bps, engine_cfg)
            leg = fin.get("leg_high")
            out.append(cand(ma.APPROACHING, entry_ref=entry, stop_ref=stop, break_level=prev_high,
                            level_key=f"leg:{leg:.4f}" if leg is not None else f"break:{prev_high:.4f}"))

    # 5) buy-zone watch armed by an EXTENDED alert
    z = zones.get(symbol)
    if z and last is not None and z["low"] <= last <= z["high"]:
        since = max(z.get("armed_epoch") or 0, now - 60)
        entered = next((float(t["ts_epoch"]) for t in ticks if t.get("ts_epoch") is not None and t.get("price")
                        is not None and since <= t["ts_epoch"] <= now and z["low"] <= float(t["price"]) <= z["high"]),
                       now)
        out.append(cand(ma.PULLBACK_ZONE, break_ts_epoch=entered, entry_ref=z.get("entry"), stop_ref=z.get("stop"),
                        fire_ts_epoch=z.get("fire_ts_epoch"), zone_low=z["low"], zone_high=z["high"],
                        level_key=f"zone:{z['low']:.4f}-{z['high']:.4f}"))
    return out


def _spread_bps(book: Optional[Mapping[str, Any]]) -> Optional[float]:
    try:
        b, a = float(book["bids"][0][0]), float(book["asks"][0][0])
        return (a - b) / ((a + b) / 2) * 1e4 if a > b > 0 else None
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def ticker(cfg: Mapping[str, Any], *, base: Optional[Path] = None, send_fn=None,
           now_fn: Callable[[], float] = time.time) -> Optional[Callable]:
    """on_tick(now, symbols) for the microstructure recorder. None when disabled."""
    fcfg = FastLoopConfig.from_mapping(cfg.get("active_trader_fast_loop"))
    if not fcfg.enabled:
        return None
    acfg = ma.AlertConfig.from_mapping(cfg.get("active_trader_alerts"))
    states: dict[str, SymbolState] = {}
    if send_fn is None and acfg.mode == "send":
        send_fn = ma.telegram_send

    def on_tick(now: float, symbols: Sequence[str]) -> dict:
        if not in_window(now, fcfg.window_et) or (ma.journal_dir() / KILL_FILE).exists():
            return {"skipped": "window_or_kill"}
        day = datetime.fromtimestamp(now, ET).date().isoformat()
        open_ep = session_open_epoch(now, fcfg)
        zones = ma.active_zones(now)
        cands, stale = [], []
        for sym in list(symbols)[: fcfg.max_symbols]:
            bars_env = store.bars(day, sym, now=now, max_age_s=fcfg.max_store_age_s, base=base)
            last, qt = store.quote(day, sym, now=now, max_age_s=fcfg.max_store_age_s, base=base)
            if bars_env["status"] != "ok" or last is None:
                stale.append({"symbol": sym, "bars": bars_env["status"], "age_s": bars_env.get("age_s")})
                continue
            closed = [b for b in bars_env["closed"] if b["t"] >= open_ep]
            forming = bars_env["forming"] if (bars_env["forming"] or {}).get("t", 0) >= open_ep else None
            bk = store.book(day, sym, now=now, max_age_s=fcfg.max_store_age_s, base=base)
            cands += step(sym, closed, forming, now=now, last=last, quote_ts=qt,
                          ticks=store.tape(day, sym, now=now, lookback_s=120, base=base),
                          engine_cfg=cfg, fcfg=fcfg, state=states.setdefault(sym, SymbolState()),
                          zones=zones, spread_bps=_spread_bps(bk), day=day)
        rows = []
        if cands:
            rows = ma.evaluate_pass(
                cands, cfg=acfg, now=now,
                fetch_primary_book=lambda s: store.book(day, s, now=now, max_age_s=fcfg.max_store_age_s, base=base),
                fetch_primary_tape=lambda s: store.tape(day, s, now=now, lookback_s=300, max_prints=acfg.tape_prints,
                                                        base=base),
                send_fn=send_fn, run_id=f"fast:{day}:{int(now)}")
        res = {"ts_epoch": now, "symbols": len(symbols), "candidates": len(cands), "rows": len(rows),
               "alerts": sum(1 for r in rows if r["verdict"] == ma.ALERT), "stale": stale,
               "latencies_s": [r["latency"].get("latency_s") for r in rows if r.get("latency")]}
        _heartbeat(res)
        return res
    return on_tick


def _heartbeat(res: Mapping[str, Any]) -> None:
    try:
        p = ma.journal_dir() / HEARTBEAT_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(res, default=str), encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001
        pass


# ── replay (tests / audits): documented intrabar path from 1-min OHLC ──────────

def intrabar_path(bar: Mapping[str, Any], steps: int) -> list[tuple[float, float, float]]:
    """ASSUMPTION (no tick history): inside a minute price travels open→low→high→close on an up
    bar (close ≥ open) and open→high→low→close on a down bar, linearly, with volume accruing
    evenly. Returns [(seconds_into_bar, price, cumulative_volume)] at `steps` evenly spaced points
    (the last is the close at 60 s)."""
    o, h, l, c, v = (float(bar[k]) for k in ("o", "h", "l", "c", "v"))
    pts = [o, l, h, c] if c >= o else [o, h, l, c]
    out = []
    for i in range(1, steps + 1):
        f = i / steps
        seg = min(int(f * 3), 2)
        local = f * 3 - seg
        px = pts[seg] + (pts[seg + 1] - pts[seg]) * local
        out.append((60.0 * f, round(px, 4), v * f))
    return out


def replay(bars: Sequence[Mapping[str, Any]], *, engine_cfg: Mapping[str, Any], acfg: "ma.AlertConfig",
           fcfg: FastLoopConfig, symbol: str, eval_s: float = 5.0, start: Optional[float] = None,
           end: Optional[float] = None, book_fn=None, tape_fn=None, extra_passes: Sequence = (),
           send_fn=None) -> list[dict]:
    """Drive step() + evaluate_pass() over a bar fixture at eval_s resolution (persisting to the
    test journal dir). extra_passes: [(epoch, Candidate)] injected 5-min-pass candidates, so the
    shared throttle / chase guard / zone hand-off are exercised exactly as live."""
    st = SymbolState()
    day = datetime.fromtimestamp(bars[0]["t"], ET).date().isoformat()
    rows: list[dict] = []
    injected = sorted(extra_passes, key=lambda x: x[0])
    for i, bar in enumerate(bars):
        if start is not None and bar["t"] < start:
            continue
        if end is not None and bar["t"] > end:
            break
        closed = list(bars[:i])
        h = l = None
        for secs, px, cv in intrabar_path(bar, int(60 / eval_s)):
            now = bar["t"] + secs + (0.0 if secs < 60 else 0.5)
            while injected and injected[0][0] <= now:
                ep, c5 = injected.pop(0)
                rows += ma.evaluate_pass([c5], cfg=acfg, now=ep, fetch_primary_book=book_fn,
                                         fetch_primary_tape=tape_fn, send_fn=send_fn, run_id=f"pass5:{int(ep)}")
            h = px if h is None else max(h, px)
            l = px if l is None else min(l, px)
            if secs >= 60:   # bar closed: evaluate the closed set (confirmations)
                cs, fm = [*closed, dict(bar)], None
            else:
                cs, fm = closed, {"t": bar["t"], "o": bar["o"], "h": h, "l": l, "c": px, "v": cv}
            ticks = [{"ts_epoch": now, "price": px, "volume": 100, "direction": "BUY"}]
            cands = step(symbol, cs, fm, now=now, last=px, quote_ts=now, ticks=ticks, engine_cfg=engine_cfg,
                         fcfg=fcfg, state=st, zones=ma.active_zones(now), day=day)
            if cands:
                rows += ma.evaluate_pass(cands, cfg=acfg, now=now, fetch_primary_book=book_fn,
                                         fetch_primary_tape=tape_fn, send_fn=send_fn, run_id=f"fast:{int(now)}")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replay", help="bar fixture JSON (list of {t,o,h,l,c,v}) — prints the alert timeline")
    ap.add_argument("--symbol", default="XNDU")
    a = ap.parse_args(argv)
    if not a.replay:
        print("runs inside microstructure_recorder.py (on_tick); use --replay FILE for an audit")
        return 0
    import os
    import tempfile
    import yaml
    os.environ.setdefault("ACTIVE_TRADER_ALERTS_DIR", tempfile.mkdtemp(prefix="fastloop_replay_"))
    cfg = yaml.safe_load((ROOT / "config" / "scalp_signal_engine.yaml").read_text(encoding="utf-8"))
    bars = json.loads(Path(a.replay).read_text(encoding="utf-8"))
    bars = bars.get("bars", bars) if isinstance(bars, dict) else bars
    # replay evidence: a supportive, always-fresh book and buy-side tape, so the timeline shows what
    # the TRIGGER logic would have sent (live, the recorder's real book and prints decide)
    good_book = lambda s: {"bids": [[100.0 - i * 0.01, 5000] for i in range(10)],  # noqa: E731
                           "asks": [[100.01 + i * 0.01, 2000] for i in range(10)],
                           "ts_epoch": 1e12, "ts_source": "replay"}
    good_tape = lambda s: [{"ts_epoch": 1e12, "price": 100.0, "volume": 100, "direction": "BUY"}] * 50  # noqa: E731
    rows = replay(bars, engine_cfg=cfg, acfg=ma.AlertConfig(), fcfg=FastLoopConfig.from_mapping(
        cfg.get("active_trader_fast_loop")), symbol=a.symbol, book_fn=good_book, tape_fn=good_tape)
    for r in rows:
        print(json.dumps({"at": datetime.fromtimestamp(r["ts_epoch"], ET).strftime("%H:%M:%S"),
                          "kind": r["kind"], "verdict": r["verdict"], "last": r["candidate"]["last"],
                          "entry": r["candidate"]["entry_ref"], "latency": r.get("latency")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
