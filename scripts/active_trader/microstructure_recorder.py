#!/usr/bin/env python3
"""Continuous order-book + tape recorder for the momentum-scalp names (operator-approved 2026-10-05).

Why: the alert journal only snapshots the book and tape at each 5-minute decision, so the
operator's XNDU buy at 10:07:09 on 2026-10-05 could only be bracketed by the 10:05 and 10:10
snapshots. Every few seconds this records, per symbol, the moomoo 10-level book, the new prints
since the last poll and the last price, so any trade or alert can be replayed later and the
engine can learn from what the book and tape actually did.

moomoo QUOTE context only (FutuTransport through MomentumAlertSources' MoomooSource). No trade
context, no unlock, no order path. Writes compact JSON lines to
  <active_trader journal dir>/micro/<YYYY-MM-DD>/<SYMBOL>.jsonl
and the live symbol list to <journal dir>/micro/live_symbols.json (the Schwab stream daemon reads it
to subscribe the same names). Self-terminates at the end of its window; kill files:
~/.tradeai/SCALP_ENGINE_DISABLED or <journal dir>/micro/RECORDER_DISABLED.

  python scripts/active_trader/microstructure_recorder.py --dry-run --symbols XNDU,SDEV --max-seconds 60
  python scripts/active_trader/microstructure_recorder.py --apply                 # window from config
  python scripts/active_trader/microstructure_recorder.py --apply --premarket     # premarket window
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from active_trader import momentum_alerts as ma
    from active_trader.momentum_alert_sources import MoomooSource
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader.momentum_alert_sources import MoomooSource

ET = ZoneInfo("America/New_York")
ENGINE_KILL = Path(os.path.expanduser("~/.tradeai/SCALP_ENGINE_DISABLED"))
DIR_SIDE = {"BUY": "B", "SELL": "S"}


@dataclass(frozen=True)
class RecorderConfig:
    """`microstructure_recorder:` in config/scalp_signal_engine.yaml overrides any field."""
    interval_s: float = 5.0
    max_symbols: int = 10
    book_levels: int = 10
    tape_prints: int = 100
    window_et: tuple = ("09:28", "12:00")
    premarket_window_et: tuple = ("06:00", "09:28")   # operator 2026-10-05: from 6am
    universe_refresh_s: float = 300.0
    live_symbols_max_age_s: float = 900.0
    publish_bars: bool = True               # 1-min bars (forming bar included) per symbol, every poll

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "RecorderConfig":
        known = {f.name for f in fields(cls)}
        kw = {k: (tuple(v) if isinstance(v, list) else v) for k, v in (raw or {}).items() if k in known}
        return cls(**kw)


def micro_dir() -> Path:
    return ma.journal_dir() / "micro"


def day_file(day: str, symbol: str, base: Optional[Path] = None) -> Path:
    return (base or micro_dir()) / day / f"{symbol.upper()}.jsonl"


def kill_requested(base: Optional[Path] = None) -> bool:
    return ENGINE_KILL.exists() or ((base or micro_dir()) / "RECORDER_DISABLED").exists()


def _hm(s: str) -> tuple[int, int]:
    h, m = str(s).split(":")
    return int(h), int(m)


def in_window(now: float, window: Iterable[str]) -> bool:
    t = datetime.fromtimestamp(now, ET)
    if t.weekday() >= 5:
        return False
    a, b = list(window)
    return _hm(a) <= (t.hour, t.minute) < _hm(b)


class TapeDedup:
    """moomoo's ticker returns the latest N prints each poll; keep only prints not seen before.
    Prints carry no sequence id, so (time, price, volume, side) is the key."""

    def __init__(self):
        self.seen: dict[str, set] = {}
        self.last_t: dict[str, float] = {}

    def new(self, symbol: str, rows: Iterable[Mapping[str, Any]]) -> list[list]:
        seen = self.seen.setdefault(symbol, set())
        floor = self.last_t.get(symbol, 0.0) - 2.0
        out = []
        for r in rows:
            t = r.get("ts_epoch")
            if t is None or t < floor:
                continue
            key = (round(float(t), 3), r.get("price"), r.get("volume"), r.get("direction"))
            if key in seen:
                continue
            seen.add(key)
            out.append([round(float(t), 3), r.get("price"), r.get("volume"),
                        DIR_SIDE.get(str(r.get("direction")).upper(), "N")])
        if out:
            self.last_t[symbol] = max(x[0] for x in out)
            if len(seen) > 5000:   # keep memory bounded on busy names
                self.seen[symbol] = {k for k in seen if k[0] >= self.last_t[symbol] - 30}
        return out


def snapshot(src, symbol: str, dedup: TapeDedup, *, now: float) -> dict:
    """One compact line. A failed piece is recorded as an error, never guessed."""
    line: dict[str, Any] = {"t": round(now, 3)}
    try:
        b = src.book(symbol, now=now)
        line["b"] = [[p, s] for p, s in (b.get("bids") or [])]
        line["a"] = [[p, s] for p, s in (b.get("asks") or [])]
        line["bt"], line["bs"] = b.get("ts_epoch"), b.get("ts_source")
    except Exception as e:  # noqa: BLE001
        line["book_err"] = type(e).__name__
    try:
        line["k"] = dedup.new(symbol, src.tape(symbol))
    except Exception as e:  # noqa: BLE001
        line["tape_err"] = type(e).__name__
    try:
        line["l"], line["qt"] = src.quote(symbol)
    except Exception as e:  # noqa: BLE001
        line["quote_err"] = type(e).__name__
    return line


def append_line(path: Path, line: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")


def load_snapshots(day: str, symbol: str, *, start: Optional[float] = None, end: Optional[float] = None,
                   base: Optional[Path] = None) -> list[dict]:
    p = day_file(day, symbol, base)
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as fh:
        for raw in fh:
            try:
                s = json.loads(raw)
            except ValueError:
                continue
            t = s.get("t") or 0
            if (start is None or t >= start) and (end is None or t <= end):
                out.append(s)
    return out


def bars_file(day: str, symbol: str, base: Optional[Path] = None) -> Path:
    return (base or micro_dir()) / day / f"{symbol.upper()}.bars.json"


def write_bars(day: str, symbol: str, rows: list[dict], *, now: float, base: Optional[Path] = None) -> None:
    """Atomic overwrite: today's 1-min bars (start-normalized; the last one may be forming). The
    single published source of intraday bars for the Active Trader consumers (operator 2026-10-05:
    the Command Center is the source of truth; processes do not fetch their own data)."""
    p = bars_file(day, symbol, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    start_of_day = datetime.fromisoformat(f"{day}T00:00:00").replace(tzinfo=ET).timestamp()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"t": round(now, 3), "time_basis": "bar_start", "provider": "moomoo",
                               "rows": [r for r in rows if r.get("s", 0) >= start_of_day]},
                              separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def write_live_symbols(symbols: list[str], *, now: float, base: Optional[Path] = None) -> None:
    p = (base or micro_dir()) / "live_symbols.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ts_epoch": now, "symbols": symbols}), encoding="utf-8")
    tmp.replace(p)


def pick_symbols(*, fills_today: list[str], alerted_today: list[str], universe_by_recency: list[str],
                 cap: int) -> list[str]:
    """Your own fills first, then names the engine alerted on today (latest first), then the rest
    of the scalp universe by most recent scan."""
    out: list[str] = []
    for s in [*fills_today, *alerted_today, *universe_by_recency]:
        s = (s or "").upper()
        if s and s not in out:
            out.append(s)
        if len(out) >= cap:
            break
    return out


def _alerted_today(day: str) -> list[str]:
    p = ma.journal_dir() / "momentum_alerts.jsonl"
    if not p.exists():
        return []
    rows = []
    for raw in p.read_text(encoding="utf-8").splitlines()[-2000:]:
        try:
            r = json.loads(raw)
        except ValueError:
            continue
        c = r.get("candidate") or {}
        if c.get("session_date") == day:
            rows.append((r.get("ts_epoch") or 0, c.get("symbol")))
    return [s for _, s in sorted(rows, reverse=True)]


def live_symbols(conn, cfg: Mapping[str, Any], rcfg: RecorderConfig, day: str) -> list[str]:
    import scalp_shadow_logger as L  # the engine's own universe (fail-closed float/price rules)
    try:
        uni = L.resolve_universe(conn, cfg)
    except Exception:  # noqa: BLE001
        uni = []
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass
    ordered = uni
    if uni:
        with conn.cursor() as cur:
            cur.execute("""SELECT symbol FROM scalp_scan_results WHERE symbol = ANY(%s)
                           GROUP BY symbol ORDER BY max(scanned_at) DESC""", (uni,))
            ordered = [r[0] for r in cur.fetchall()]
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT symbol FROM trade_transactions
                       WHERE trade_date = %s AND action IN ('Buy','Sell') AND symbol ~ '^[A-Z]{1,5}$'""", (day,))
        fills = [r[0] for r in cur.fetchall()]
    conn.rollback()
    return pick_symbols(fills_today=fills, alerted_today=_alerted_today(day), universe_by_recency=ordered,
                        cap=int(rcfg.max_symbols))


def run(*, rcfg: RecorderConfig, symbols_fn: Callable[[], list[str]], src, now_fn=time.time,
        sleep_fn=time.sleep, window: Iterable[str], max_seconds: Optional[float] = None,
        dry_run: bool = False, base: Optional[Path] = None, on_tick: Optional[Callable] = None,
        out=print) -> dict:
    started = now_fn()
    dedup = TapeDedup()
    stats = {"polls": 0, "lines": 0, "errors": 0, "symbols": [], "stopped": None}
    symbols: list[str] = []
    last_refresh = -1e18
    while True:
        now = now_fn()
        if kill_requested(base):
            stats["stopped"] = "kill_file"; break
        if max_seconds is not None and now - started >= max_seconds:
            stats["stopped"] = "max_seconds"; break
        if max_seconds is None and not in_window(now, window):
            stats["stopped"] = "window_closed"; break
        if now - last_refresh >= rcfg.universe_refresh_s:
            try:
                symbols = symbols_fn()
            except Exception as e:  # noqa: BLE001
                out(f"[recorder] symbol refresh failed: {type(e).__name__}: {e}")
            last_refresh = now
            stats["symbols"] = list(symbols)
            if not dry_run:
                write_live_symbols(symbols, now=now, base=base)
            out(f"[recorder] symbols: {symbols}")
        day = datetime.fromtimestamp(now, ET).date().isoformat()
        for sym in symbols:
            line = snapshot(src, sym, dedup, now=now_fn())
            stats["lines"] += 1
            stats["errors"] += sum(1 for k in ("book_err", "tape_err", "quote_err") if k in line)
            if dry_run:
                out(json.dumps({"symbol": sym, "t": line["t"], "bid": (line.get("b") or [[None]])[0],
                                "ask": (line.get("a") or [[None]])[0], "levels": len(line.get("a") or []),
                                "new_prints": len(line.get("k") or []), "last": line.get("l"),
                                **{k: line[k] for k in ("book_err", "tape_err", "quote_err") if k in line}}))
            else:
                append_line(day_file(day, sym, base), line)
            if rcfg.publish_bars and hasattr(src, "bars_1m"):
                try:
                    rows = src.bars_1m(sym)
                    if not dry_run:
                        write_bars(day, sym, rows, now=now_fn(), base=base)
                    stats["bars"] = stats.get("bars", 0) + 1
                except Exception as e:  # noqa: BLE001 — bars are a separate product; never stop recording
                    stats["errors"] += 1
                    out(f"[recorder] bars {sym}: {type(e).__name__}: {str(e)[:80]}")
        stats["polls"] += 1
        if on_tick is not None:
            try:
                on_tick(now, symbols)
            except Exception as e:  # noqa: BLE001 — exit watch never stops recording
                out(f"[recorder] on_tick failed: {type(e).__name__}: {e}")
        spent = now_fn() - now
        sleep_fn(max(0.0, rcfg.interval_s - spent))
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write recorder files (default: dry run)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--premarket", action="store_true")
    ap.add_argument("--no-exit-watch", action="store_true")
    a = ap.parse_args(argv)
    dry = a.dry_run or not a.apply
    import scalp_shadow_logger as L
    cfg = L.load_config()
    rcfg = RecorderConfig.from_mapping(cfg.get("microstructure_recorder"))
    window = rcfg.premarket_window_et if a.premarket else rcfg.window_et
    if a.max_seconds is None and not in_window(time.time(), window):
        print(f"[recorder] outside window {window} ET — nothing to do"); return 0
    if a.symbols:
        fixed = [s.strip().upper() for s in a.symbols.split(",") if s.strip()][: int(rcfg.max_symbols)]
        symbols_fn = lambda: fixed  # noqa: E731
        conn = None
    else:
        from db_adapter import get_connection
        conn = get_connection()
        day = datetime.now(ET).date().isoformat()
        symbols_fn = lambda: live_symbols(conn, cfg, rcfg, day)  # noqa: E731
    acfg = ma.AlertConfig.from_mapping(cfg.get("active_trader_alerts"))
    src = MoomooSource(levels=rcfg.book_levels, prints=rcfg.tape_prints)
    on_tick = None
    if not a.no_exit_watch and not dry:
        try:
            from active_trader import exit_watch as ew
        except ModuleNotFoundError:  # pragma: no cover
            from scripts.active_trader import exit_watch as ew
        ticks = [ew.ticker(cfg, conn_fn=(lambda: conn), alert_cfg=acfg)]
        # Sub-minute alert sync (2026-10-05): the fast trigger loop is a pure CONSUMER of what this
        # recorder just published; it runs on the same tick, so no second process or subscription.
        try:
            from active_trader import fast_trigger_loop as ftl
        except ModuleNotFoundError:  # pragma: no cover
            from scripts.active_trader import fast_trigger_loop as ftl
        fl = ftl.ticker(cfg, base=None)
        if fl is not None:
            ticks.append(fl)

        def on_tick(now, symbols, _ticks=ticks):
            for t in _ticks:
                try:
                    t(now, symbols)
                except Exception as e:  # noqa: BLE001 — one consumer never stops the others
                    print(f"[recorder] tick consumer failed: {type(e).__name__}: {e}")
    try:
        stats = run(rcfg=rcfg, symbols_fn=symbols_fn, src=src, window=window, max_seconds=a.max_seconds,
                    dry_run=dry, on_tick=on_tick)
    finally:
        src.close()
    print(json.dumps({"recorder": stats, "dry_run": dry}))
    if not dry and conn is not None:
        try:   # end of window: build replays + learning records for today (best effort)
            from active_trader import trade_replay as tr
            print(json.dumps({"replay": tr.run_day(datetime.now(ET).date().isoformat(), conn=conn, apply=True)},
                             default=str)[:2000])
        except Exception as e:  # noqa: BLE001
            print(f"[recorder] end-of-window replay failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
