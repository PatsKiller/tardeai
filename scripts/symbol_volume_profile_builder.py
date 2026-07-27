#!/usr/bin/env python3
"""M3-S1 — per-symbol intraday volume-profile builder (Momentum Scalp Signal Engine).

Builds/refreshes the trailing-N-session MEDIAN cumulative volume at each minute of the regular
session, per symbol, from Alpaca minute bars. This is the denominator for time-of-day relative
volume (RVOL_tod = CumVol(t) / median_Nd(CumVol at same minute-of-session t)) — the §3.1 fix for
scan-time RVOL being arithmetically wrong intraday.

SHADOW / read-model only. Writes ONLY to `symbol_volume_profile`. Does NOT import or touch
paper_trade_proposals, any Alpaca order path, the classifier, or momentum_scalp. Market-data GETs
only (historical bars). No orders, no proposals, no execution.

Feed note: the LIVE RVOL_tod path must read bars from the SAME feed the profile was built from
(stored per-row as `feed`), or the ratio is biased (IEX numerator vs SIP denominator ≈ 0.03×).

Usage:
  # spot-build + print curves (verification)
  python scripts/symbol_volume_profile_builder.py --symbols AAPL,SOFI,PLTR --verify --apply
  # full universe refresh (nightly)
  python scripts/symbol_volume_profile_builder.py --from-scalp-universe --apply
  # dry run (no DB writes)
  python scripts/symbol_volume_profile_builder.py --symbols AAPL --dry-run --verify
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import requests
import yaml

_REPO = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO / "config" / "scalp_signal_engine.yaml"


# ─────────────────────────── pure core (no I/O — unit-tested) ────────────────────────────

def minute_of_session(bar_dt_local: datetime, open_hhmm: str = "09:30") -> int:
    """Minute index within the regular session for a tz-aware LOCAL (exchange-tz) datetime.
    09:30 → 0, 15:59 → 389. Returns -1 if outside the regular session (pre/post market)."""
    oh, om = (int(x) for x in open_hhmm.split(":"))
    idx = (bar_dt_local.hour * 60 + bar_dt_local.minute) - (oh * 60 + om)
    return idx


def session_cum_incr(minute_vol: Mapping[int, float], n_minutes: int = 390) -> tuple[list[float], list[float]]:
    """Given {minute_of_session: volume} for ONE session, return (cumulative, incremental) arrays
    of length n_minutes. Missing minutes contribute 0 incremental and carry the running cumulative
    forward. Pure and deterministic."""
    cum: list[float] = [0.0] * n_minutes
    incr: list[float] = [0.0] * n_minutes
    running = 0.0
    for m in range(n_minutes):
        v = float(minute_vol.get(m, 0.0) or 0.0)
        running += v
        cum[m] = running
        incr[m] = v
    return cum, incr


def median_profile(
    sessions_cum: Sequence[Sequence[float]],
    sessions_incr: Sequence[Sequence[float]],
) -> tuple[list[float], list[float]]:
    """Per-minute median across sessions. Both inputs are lists of equal-length per-session arrays.
    Returns (median_cumulative, median_incremental). Pure."""
    if not sessions_cum:
        return [], []
    n = len(sessions_cum[0])
    med_cum = [statistics.median([s[m] for s in sessions_cum]) for m in range(n)]
    med_incr = [statistics.median([s[m] for s in sessions_incr]) for m in range(n)]
    return med_cum, med_incr


def build_profile_from_sessions(
    per_session_minute_vol: Sequence[Mapping[int, float]],
    n_minutes: int = 390,
) -> tuple[list[float], list[float]]:
    """Full pure pipeline: list of per-session {minute: volume} → (median_cum, median_incr)."""
    cums, incrs = [], []
    for mv in per_session_minute_vol:
        c, i = session_cum_incr(mv, n_minutes)
        cums.append(c)
        incrs.append(i)
    return median_profile(cums, incrs)


# ─────────────────────────── config / I/O ───────────────────────────

def load_config(path: Path = _CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _alpaca_keys() -> tuple[str, str]:
    """Read Alpaca market-data keys from env (never printed). Paper keys preferred."""
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_REPO / ".env"))
    except Exception:
        pass
    key = os.environ.get("ALPACA_PAPER_API_KEY") or os.environ.get("ALPACA_API_KEY") or ""
    sec = os.environ.get("ALPACA_PAPER_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY") or ""
    if not key or not sec:
        raise RuntimeError("Alpaca market-data keys not found in env (ALPACA_PAPER_API_KEY/SECRET)")
    return key, sec


def fetch_minute_bars(symbol: str, cfg: dict, days: int) -> list[dict]:
    """GET historical 1-minute bars for `symbol` over the trailing `days`, following pagination.
    Read-only market data. Returns raw Alpaca bar dicts ({t,o,h,l,c,v,...})."""
    key, sec = _alpaca_keys()
    h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}
    data = cfg["data"]
    url = data["bars_endpoint"].format(symbol=symbol)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    params = {
        "timeframe": data.get("timeframe", "1Min"),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 10000,
        "feed": data.get("feed", "sip"),
        "adjustment": data.get("adjustment", "raw"),
    }
    out: list[dict] = []
    token = None
    for _ in range(200):  # hard page cap (safety)
        p = dict(params)
        if token:
            p["page_token"] = token
        r = requests.get(url, headers=h, params=p, timeout=45)
        if r.status_code != 200:
            raise RuntimeError(f"Alpaca bars {symbol}: HTTP {r.status_code} {r.text[:160]}")
        j = r.json()
        out.extend(j.get("bars") or [])
        token = j.get("next_page_token")
        if not token:
            break
    return out


def bars_to_sessions(bars: Iterable[dict], cfg: dict) -> dict[str, dict[int, float]]:
    """Group raw bars into {session_date_str: {minute_of_session: volume}} for the regular session
    only (pre/post-market bars dropped). Timestamps converted to the exchange tz."""
    sess = cfg["session"]
    tz = ZoneInfo(sess.get("tz", "America/New_York"))
    open_hhmm = sess.get("regular_open", "09:30")
    n_minutes = int(sess.get("regular_minutes", 390))
    by_session: dict[str, dict[int, float]] = defaultdict(dict)
    for b in bars:
        ts = b.get("t")
        if not ts:
            continue
        dt_utc = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(tz)
        m = minute_of_session(dt_local, open_hhmm)
        if m < 0 or m >= n_minutes:
            continue  # extended-hours bar — excluded from the regular-session profile
        day = dt_local.date().isoformat()
        by_session[day][m] = by_session[day].get(m, 0.0) + float(b.get("v", 0) or 0)
    return by_session


def select_complete_sessions(
    by_session: Mapping[str, Mapping[int, float]], cfg: dict
) -> list[dict[int, float]]:
    """Keep SPAN-complete sessions (printed at/after require_close_minute, with >= min_session_prints
    traded minutes) and return the most recent lookback_sessions. Span-based so sparse micro-float
    names still qualify — density is not the completeness signal, coverage of the day is."""
    vp = cfg["volume_profile"]
    min_prints = int(vp.get("min_session_prints", 30))
    close_minute = int(vp.get("require_close_minute", 375))
    lookback = int(vp.get("lookback_sessions", 20))
    complete = [
        (d, mv) for d, mv in by_session.items()
        if mv and len(mv) >= min_prints and max(mv.keys()) >= close_minute
    ]
    complete.sort(key=lambda kv: kv[0])           # chronological
    recent = complete[-lookback:]                 # most recent N
    return [mv for _, mv in recent]


def build_symbol(symbol: str, cfg: dict) -> dict | None:
    """Fetch + build one symbol's profile. Returns a result dict or None if skipped (too few
    sessions). Never writes."""
    vp = cfg["volume_profile"]
    n_minutes = int(cfg["session"].get("regular_minutes", 390))
    days = int(vp.get("backfill_days", 40))
    min_sessions = int(vp.get("min_sessions", 15))
    bars = fetch_minute_bars(symbol, cfg, days)
    sessions = select_complete_sessions(bars_to_sessions(bars, cfg), cfg)
    n = len(sessions)
    if n < min_sessions:
        return {"symbol": symbol, "skipped": True, "n_sessions": n, "reason": f"only {n} < {min_sessions} sessions"}
    med_cum, med_incr = build_profile_from_sessions(sessions, n_minutes)
    return {
        "symbol": symbol, "skipped": False, "n_sessions": n,
        "median_cum": med_cum, "median_incr": med_incr,
        "feed": cfg["data"].get("feed", "sip"),
        "lookback_sessions": int(vp.get("lookback_sessions", 20)),
        "session_window": vp.get("session_window", "regular"),
    }


# ─────────────────────────── persistence ───────────────────────────

def ensure_schema(conn) -> None:
    sql = (_REPO / "migrations" / "2026-07-27_scalp_volume_profile.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def upsert_profile(conn, res: dict) -> int:
    rows = 0
    with conn.cursor() as cur:
        for m in range(len(res["median_cum"])):
            cur.execute(
                """
                INSERT INTO symbol_volume_profile
                    (symbol, session_window, minute_of_session, median_cum_volume,
                     median_incr_volume, n_sessions, feed, lookback_sessions, built_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                ON CONFLICT (symbol, session_window, feed, minute_of_session)
                DO UPDATE SET median_cum_volume = EXCLUDED.median_cum_volume,
                              median_incr_volume = EXCLUDED.median_incr_volume,
                              n_sessions = EXCLUDED.n_sessions,
                              lookback_sessions = EXCLUDED.lookback_sessions,
                              built_at = now()
                """,
                [res["symbol"], res["session_window"], m, res["median_cum"][m],
                 res["median_incr"][m], res["n_sessions"], res["feed"], res["lookback_sessions"]],
            )
            rows += 1
    conn.commit()
    return rows


def resolve_universe(conn, cfg: dict) -> list[str]:
    u = cfg["universe"]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT {u['symbol_column']}
            FROM {u['source_table']}
            WHERE {u['time_column']} > now() - interval '{int(u['lookback_days'])} days'
              AND ({u['float_column']} IS NULL OR {u['float_column']} <= %s)
              AND {u['symbol_column']} IS NOT NULL
            ORDER BY 1
            """,
            [float(u["float_mm_max"])],
        )
        return [r[0] for r in cur.fetchall()]


# ─────────────────────────── G2.2 freshness contract ───────────────────────────

def trading_sessions_between(built_at: "datetime", now: "datetime") -> int:
    """Approximate trading sessions elapsed between two datetimes = weekday count in (built_at, now].
    Ignores market holidays (acceptable for a small freshness window; errs toward MORE stale)."""
    from datetime import timedelta as _td
    if built_at is None or now is None:
        return 10 ** 6
    d0 = built_at.date()
    d1 = now.date()
    if d1 <= d0:
        return 0
    n = 0
    d = d0
    while d < d1:
        d = d + _td(days=1)
        if d.weekday() < 5:  # Mon-Fri
            n += 1
    return n


class ProfileUnavailable(Exception):
    """Raised/signalled when a profile denominator must NOT be consumed (stale or under-populated)."""


def get_profile_denominator(conn, symbol: str, minute: int, cfg: dict, now=None,
                            raise_on_refuse: bool = False):
    """THE accessor S3 calls for an RVOL_tod denominator. Returns
    (median_cum_volume, meta_dict) or (None, meta_dict) — and it REFUSES (returns None, or raises
    ProfileUnavailable when raise_on_refuse) rather than hand back a poisoned number when:
      * the symbol/minute has no profile row, OR
      * n_sessions < volume_profile.min_sessions, OR
      * the profile was built more than volume_profile.max_profile_age_sessions trading sessions ago.
    Structurally impossible to consume a stale/thin denominator silently."""
    from datetime import datetime as _dt, timezone as _tz
    vp = cfg["volume_profile"]
    feed = cfg["data"]["feed"]
    min_sessions = int(vp.get("min_sessions", 15))
    max_age = int(vp.get("max_profile_age_sessions", 3))
    if now is None:
        now = _dt.now(_tz.utc)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT median_cum_volume, n_sessions, built_at FROM symbol_volume_profile
               WHERE symbol=%s AND session_window='regular' AND feed=%s AND minute_of_session=%s""",
            [symbol, feed, minute])
        r = cur.fetchone()
    meta = {"symbol": symbol, "minute": minute, "feed": feed}
    if not r or r[0] is None:
        meta["reason"] = "absent"
        if raise_on_refuse:
            raise ProfileUnavailable(f"{symbol}@{minute}: no profile row")
        return None, meta
    median_cum, n_sessions, built_at = float(r[0]), int(r[1]), r[2]
    age = trading_sessions_between(built_at, now)
    meta.update({"n_sessions": n_sessions, "age_sessions": age, "built_at": built_at})
    if n_sessions < min_sessions:
        meta["reason"] = f"under_populated({n_sessions}<{min_sessions})"
        if raise_on_refuse:
            raise ProfileUnavailable(meta["reason"])
        return None, meta
    if age > max_age:
        meta["reason"] = f"stale({age}>{max_age} sessions)"
        if raise_on_refuse:
            raise ProfileUnavailable(meta["reason"])
        return None, meta
    meta["reason"] = "ok"
    return median_cum, meta


# ─────────────────────────── verification / CLI ───────────────────────────

def print_curve(res: dict, step: int = 30) -> None:
    cum, incr = res["median_cum"], res["median_incr"]
    n = len(cum)
    mono = all(cum[i] <= cum[i + 1] + 1e-9 for i in range(n - 1))
    open_incr = statistics.mean(incr[:30]) if n >= 30 else 0
    mid_incr = statistics.mean(incr[180:210]) if n >= 210 else 0
    close_incr = statistics.mean(incr[-30:]) if n >= 30 else 0
    u_shaped = open_incr > mid_incr and close_incr > mid_incr
    print(f"\n  ── {res['symbol']}  (n_sessions={res['n_sessions']}, feed={res['feed']}) ──")
    print(f"     cumulative monotonic non-decreasing: {mono}")
    print(f"     incremental U-shape (open>{mid_incr:,.0f}<close): open={open_incr:,.0f} mid={mid_incr:,.0f} close={close_incr:,.0f} → {u_shaped}")
    print(f"     {'min':>5} {'clock':>6} {'median_cum':>14} {'median_incr':>12}")
    open_h, open_m = 9, 30
    for m in range(0, n, step):
        tot = open_m + m
        clock = f"{open_h + tot // 60:02d}:{tot % 60:02d}"
        print(f"     {m:>5} {clock:>6} {cum[m]:>14,.0f} {incr[m]:>12,.0f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="M3-S1 volume-profile builder (shadow/read-only)")
    ap.add_argument("--symbols", help="comma-separated symbols")
    ap.add_argument("--from-scalp-universe", action="store_true", help="build the config universe")
    ap.add_argument("--apply", action="store_true", help="write to symbol_volume_profile")
    ap.add_argument("--dry-run", action="store_true", help="compute only, no DB writes")
    ap.add_argument("--verify", action="store_true", help="print profile curves for built symbols")
    ap.add_argument("--config", default=str(_CONFIG_PATH))
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config))
    try:
        from db_adapter import get_connection  # when run as scripts/<file>.py
    except ModuleNotFoundError:
        from scripts.db_adapter import get_connection  # when imported as scripts.<module>
    conn = get_connection()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.from_scalp_universe:
        symbols = resolve_universe(conn, cfg)
        print(f"universe: {len(symbols)} symbols (float_mm<={cfg['universe']['float_mm_max']})")
    else:
        ap.error("provide --symbols or --from-scalp-universe")
        return 2

    if args.apply:
        ensure_schema(conn)

    built = skipped = written = 0
    results = []
    for sym in symbols:
        try:
            res = build_symbol(sym, cfg)
        except Exception as e:
            print(f"  {sym}: ERROR {e}")
            continue
        if res is None or res.get("skipped"):
            skipped += 1
            print(f"  {sym}: SKIP ({res.get('reason') if res else 'no data'})")
            continue
        built += 1
        results.append(res)
        if args.apply and not args.dry_run:
            written += upsert_profile(conn, res)
        print(f"  {sym}: built ({res['n_sessions']} sessions){' → wrote '+str(len(res['median_cum']))+' rows' if (args.apply and not args.dry_run) else ''}")

    if args.verify:
        for res in results[:3]:
            print_curve(res)

    print(f"\nsummary: built={built} skipped={skipped} rows_written={written} "
          f"apply={args.apply and not args.dry_run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
