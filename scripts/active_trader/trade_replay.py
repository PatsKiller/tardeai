#!/usr/bin/env python3
"""Replay your trades against the book, tape and volume at the moment you traded (operator 2026-10-05:
"go back and let me know what was volume and what was on the order book at the time").

For every round trip (momentum_alerts_api.attribute_fills on your broker fills), at the buy and at
the sell:
  book    — the recorder's moomoo snapshot at/before the fill ("exact", within exact_max_s) or, when
            the recorder was not running, the alert-journal snapshots just before and after the fill
            ("bracketed", e.g. XNDU 2026-10-05 10:07:09 between the 10:05:16 and 10:10:15 decisions)
  tape    — buy share of the last prints before the fill (recorder or journal)
  volume  — the fill minute's volume and the prior-5-minute average (moomoo tape if recorded,
            else Alpaca IEX minute bars, which only see a slice of consolidated volume — labelled)
  schwab  — the nearest Schwab NASDAQ_BOOK row at/before the fill, when that symbol was streamed
  signals — entry/exit microstructure signals at that moment (recorder data only)

Writes <journal dir>/replays/<day>.jsonl (derived, regenerated each run) and learning records.
SELECT only on the database; trade_lesson_memory rows are written only with --apply.

  python scripts/active_trader/trade_replay.py --day 2026-10-05            # dry run, prints replays
  python scripts/active_trader/trade_replay.py --day 2026-10-05 --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from active_trader import momentum_alerts as ma
    from active_trader import momentum_alerts_api as api
    from active_trader import momentum_alert_scoring as ms
    from active_trader import microstructure_signals as msig
    from active_trader import microstructure_recorder as rec
    from active_trader import trade_learning as tl
except ModuleNotFoundError:  # pragma: no cover
    from scripts.active_trader import momentum_alerts as ma
    from scripts.active_trader import momentum_alerts_api as api
    from scripts.active_trader import momentum_alert_scoring as ms
    from scripts.active_trader import microstructure_signals as msig
    from scripts.active_trader import microstructure_recorder as rec
    from scripts.active_trader import trade_learning as tl

ET = ZoneInfo("America/New_York")
CONTRACT = "active-trader-trade-replay-v1"
EXACT_MAX_S = 10.0          # a recorder snapshot this close before the fill counts as "exact"
BRACKET_MAX_S = 15 * 60     # journal snapshots further than this from the fill are not used
TAPE_LOOKBACK_S = 300


def _et(ts: Optional[float]) -> Optional[str]:
    return None if ts is None else datetime.fromtimestamp(ts, ET).isoformat(timespec="seconds")


def _bar_epoch(b: Mapping[str, Any]) -> Optional[float]:
    return msig._epoch(b.get("t"))


def volume_at(bars: list[dict], ts: float, *, source: str) -> Optional[dict]:
    m0 = int(ts // 60) * 60
    seq = sorted(((e, b) for e, b in ((_bar_epoch(b), b) for b in bars) if e is not None), key=lambda x: x[0])
    cur = [b for e, b in seq if int(e // 60) * 60 == m0]
    prior = [b for e, b in seq if m0 - 5 * 60 <= e < m0]
    if not cur and not prior:
        return None
    pv = [float(b.get("v") or 0) for b in prior]
    return {"source": source, "minute": _et(m0), "minute_volume": float(cur[0].get("v") or 0) if cur else None,
            "minute_bar": {k: cur[0].get(k) for k in ("o", "h", "l", "c", "v")} if cur else None,
            "prior5": pv, "prior5_avg": round(sum(pv) / len(pv), 1) if pv else None}


def _book_summary(snap_or_l2: Mapping[str, Any], *, near_pct: float) -> Optional[dict]:
    if "b" in snap_or_l2 or "a" in snap_or_l2:
        st = msig.book_stats(snap_or_l2, near_pct=near_pct)
        if not st:
            return None
        st["levels"] = min(len(snap_or_l2.get("b") or []), len(snap_or_l2.get("a") or []))
        st["top_bids"] = (snap_or_l2.get("b") or [])[:3]
        st["top_asks"] = (snap_or_l2.get("a") or [])[:3]
        return st
    sup = snap_or_l2.get("supply") or {}
    return {"best_bid": snap_or_l2.get("best_bid"), "best_ask": snap_or_l2.get("best_ask"),
            "bid_depth": snap_or_l2.get("bid_depth"), "ask_depth": snap_or_l2.get("ask_depth"),
            "depth_ratio": snap_or_l2.get("depth_ratio"), "spread_bps": snap_or_l2.get("spread_bps"),
            "levels": snap_or_l2.get("levels"), "ask_inside": sup.get("ask_size_inside"),
            "ask_near": sup.get("ask_shares_near")}


def point(symbol: str, ts: float, *, day: str, snaps: list[dict], journal: list[dict], iex_bars: list[dict],
          schwab_row: Optional[dict], scfg: msig.SignalConfig, side: str) -> dict:
    before = [s for s in snaps if (s.get("t") or 0) <= ts]
    out: dict[str, Any] = {"at": _et(ts), "ts_epoch": ts}
    if before and ts - before[-1]["t"] <= EXACT_MAX_S and (before[-1].get("b") or before[-1].get("a")):
        s = before[-1]
        out["evidence"] = "exact"
        out["book_age_s"] = round(ts - s["t"], 1)
        out["book"] = _book_summary(s, near_pct=scfg.near_pct)
        tk = [k for k in msig.ticks(x for x in before if x["t"] >= ts - TAPE_LOOKBACK_S)][-scfg.tape_prints:]
        b = sum(v for _, _, v, d in tk if d == "B")
        sl = sum(v for _, _, v, d in tk if d == "S")
        out["tape"] = {"source": "moomoo", "prints": len(tk), "buy_volume": b, "sell_volume": sl,
                       "buy_ratio": round(b / (b + sl), 3) if b + sl else None}
        mbars = msig.bars_from_ticks(msig.ticks(x for x in snaps if ts - 6 * 60 <= x["t"] <= ts + 60))
        out["volume"] = volume_at(mbars, ts, source="moomoo_tape (recorder coverage)") or \
            volume_at(iex_bars, ts, source="alpaca_iex (partial volume)")
        closed = [b for b in mbars if b["t"] + 60 <= ts]
        fn = msig.entry_signals if side == "buy" else msig.exit_signals
        kw = {"schwab_row": schwab_row} if side == "buy" else {}
        out["signals"] = fn([x for x in before if x["t"] >= ts - 15 * 60], closed or iex_bars, now=ts, cfg=scfg, **kw)
    else:
        rows = sorted((r for r in journal if (r.get("candidate") or {}).get("symbol") == symbol
                       and abs((r.get("ts_epoch") or 0) - ts) <= BRACKET_MAX_S), key=lambda r: r["ts_epoch"])
        pre = [r for r in rows if r["ts_epoch"] <= ts][-1:]
        post = [r for r in rows if r["ts_epoch"] > ts][:1]
        out["evidence"] = "bracketed" if (pre or post) else "none"
        out["bracket"] = [{"at": _et(r["ts_epoch"]), "seconds_from_fill": round(r["ts_epoch"] - ts),
                           "decision": f"{r.get('kind')} {r.get('verdict')}", "book": _book_summary(r.get("l2") or {}, near_pct=scfg.near_pct),
                           "tape": {k: (r.get("tape") or {}).get(k) for k in ("buy_ratio", "prints", "buy_volume", "sell_volume")} if r.get("tape") else None}
                          for r in pre + post]
        if pre and post:
            b0, b1 = (pre[0].get("l2") or {}), (post[0].get("l2") or {})
            def chg(k):
                x, y = b0.get(k), b1.get(k)
                return round((y / x - 1) * 100, 1) if x and y is not None else None
            out["bracket_change"] = {"bid_depth_pct": chg("bid_depth"), "ask_depth_pct": chg("ask_depth")}
        out["book"] = out["bracket"][0]["book"] if out["bracket"] else None
        out["volume"] = volume_at(iex_bars, ts, source="alpaca_iex (partial volume)")
    if schwab_row:
        out["schwab"] = {"at": _et(schwab_row.get("ts_epoch")), "best_bid": schwab_row.get("best_bid"),
                         "best_ask": schwab_row.get("best_ask"), "bid_depth": schwab_row.get("bid_depth"),
                         "ask_depth": schwab_row.get("ask_depth"),
                         "ask_inside_mm": ((schwab_row.get("ask_levels") or [{}])[0] or {}).get("mm_count")}
    return out


def schwab_row_at(conn, symbol: str, ts: float, *, max_age_s: float = 120.0) -> Optional[dict]:
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT best_bid, best_ask, bid_depth, ask_depth, bid_levels, ask_levels,
                                  extract(epoch from captured_at)
                           FROM schwab_stream_book WHERE symbol=%s
                             AND captured_at <= to_timestamp(%s) AND captured_at >= to_timestamp(%s)
                           ORDER BY captured_at DESC LIMIT 1""", (symbol, ts, ts - max_age_s))
            r = cur.fetchone()
        conn.rollback()
    except Exception:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
    if not r:
        return None
    f = lambda v: float(v) if v is not None else None  # noqa: E731
    return {"best_bid": f(r[0]), "best_ask": f(r[1]), "bid_depth": f(r[2]), "ask_depth": f(r[3]),
            "bid_levels": r[4], "ask_levels": r[5], "ts_epoch": f(r[6])}


def replay_trips(trips: list[dict], *, day: str, journal: list[dict], bars_fn: Callable[[str], list],
                 snaps_fn: Callable[[str], list], schwab_fn: Callable[[str, float], Optional[dict]],
                 scfg: msig.SignalConfig) -> list[dict]:
    out = []
    cache: dict[str, tuple] = {}
    for t in trips:
        sym = t["symbol"]
        if sym not in cache:
            try:
                bars = bars_fn(sym) or []
            except Exception:  # noqa: BLE001
                bars = []
            cache[sym] = (bars, snaps_fn(sym))
        bars, snaps = cache[sym]
        rp = {"contract": CONTRACT, "symbol": sym, "buy_ts": t.get("buy_ts"), "qty": t.get("qty"),
              "source": t.get("source"), "alert": t.get("alert")}
        if t.get("buy_ts"):
            rp["buy"] = point(sym, t["buy_ts"], day=day, snaps=snaps, journal=journal, iex_bars=bars,
                              schwab_row=schwab_fn(sym, t["buy_ts"]), scfg=scfg, side="buy")
        sell_ts = msig._epoch(t.get("sell_at")) if t.get("sell_at") else None
        if sell_ts:
            rp["sell"] = point(sym, sell_ts, day=day, snaps=snaps, journal=journal, iex_bars=bars,
                               schwab_row=schwab_fn(sym, sell_ts), scfg=scfg, side="sell")
        out.append(rp)
    return out


def replays_path(day: str, base: Optional[Path] = None) -> Path:
    return (base or ma.journal_dir()) / "replays" / f"{day}.jsonl"


def read_replays(day: str, base: Optional[Path] = None) -> list[dict]:
    p = replays_path(day, base)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_replays(day: str, replays: list[dict], base: Optional[Path] = None) -> Path:
    p = replays_path(day, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, default=str, sort_keys=True) + "\n" for r in replays), encoding="utf-8")
    tmp.replace(p)
    return p


def _journal_day(day: str) -> list[dict]:
    p = ma.journal_dir() / "momentum_alerts.jsonl"
    rows = []
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(raw)
            except ValueError:
                continue
            if r.get("contract") == ma.CONTRACT and (r.get("candidate") or {}).get("session_date") == day:
                rows.append(r)
    return rows


def run_day(day: str, *, conn, apply: bool, cfg: Optional[Mapping[str, Any]] = None,
            bars_fn: Optional[Callable[[str], list]] = None) -> dict:
    import scalp_shadow_logger as L
    cfg = cfg or L.load_config()
    scfg = msig.SignalConfig.from_mapping(cfg.get("microstructure_signals"))
    journal = _journal_day(day)
    scored = {s.get("decision_id"): s for s in api._rows(ma.journal_dir() / "momentum_alerts_scored.jsonl")}
    compact = [api._compact(r, scored.get(ms.decision_id(r))) for r in journal]
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT symbol FROM trade_transactions WHERE trade_date=%s AND action IN ('Buy','Sell')""", (day,))
        syms = {r[0] for r in cur.fetchall() if r[0] and r[0].isalpha()}
    conn.rollback()
    fills = api.operator_fills(day, syms, conn=conn)
    trips = api.attribute_fills(fills, compact)
    if bars_fn is None:
        fetch_days = (_date.today() - _date.fromisoformat(day)).days + 3
        bars_fn = lambda s: L.session_rth_bars(s, cfg, day, fetch_days)  # noqa: E731
    replays = replay_trips(trips, day=day, journal=journal, bars_fn=bars_fn,
                           snaps_fn=lambda s: rec.load_snapshots(day, s),
                           schwab_fn=lambda s, ts: schwab_row_at(conn, s, ts), scfg=scfg)
    by_key = {(r["symbol"], r.get("buy_ts"), r.get("qty")): r for r in replays}
    records = [x for x in (tl.trip_record(t, by_key.get((t["symbol"], t.get("buy_ts"), t.get("qty"))), day) for t in trips) if x]
    records += [x for x in (tl.decision_record(r, scored.get(ms.decision_id(r)) or {}) for r in journal) if x]
    lessons = [tl.lesson_row(t, by_key.get((t["symbol"], t.get("buy_ts"), t.get("qty"))),
                             trade_id=tl.closed_trade_id(conn, t))
               for t in trips if t.get("sell_at") and t.get("source") == "active_trader"]
    result = {"day": day, "trips": len(trips), "replays": len(replays), "learning_records": len(records),
              "lessons": len(lessons), "apply": apply}
    if apply:
        write_replays(day, replays)
        result["learning_appended"] = tl.append_new(records)
        result["lesson_insert"] = tl.insert_lessons(conn, lessons, apply=True)
    else:
        result["replays_preview"] = replays
        result["lessons_preview"] = lessons
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--day", default=datetime.now(ET).date().isoformat())
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    from db_adapter import get_connection
    conn = get_connection()
    print(json.dumps(run_day(a.day, conn=conn, apply=a.apply), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
