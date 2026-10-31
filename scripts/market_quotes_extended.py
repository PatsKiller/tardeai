#!/usr/bin/env python3
"""Extended-session quotes for the Market Risk Engine (DSN-20261031-market-risk-engine P1-T4).

One Alpaca request per run (15-minute IEX bars over the last ``lookback_hours``) through the same credentials the
quote ingest already uses (``external_market_data_ingest._alpaca_creds``). For every symbol whose newest bar lies
OUTSIDE the regular session, one row goes to ``market_quotes`` through the single writer
(``lib.writers.market_quotes_writer.write_market_quotes``) with ``source = 'alpaca_ext'``:

* ``price``      = that bar's close,
* ``prev_close`` = the last REGULAR-session close at or before it (the close of the 15:45 ET bar),
* ``fetched_at`` = the bar's end (start + 15 min) -- the instant the print was knowable, never earlier.

Rows already written (same symbol, source, fetched_at) are skipped, so a run with no new extended bar writes nothing.
The engine's ``PgReader.quotes`` labels ``alpaca_ext`` rows ``premarket`` / ``afterhours``; ``categories/extended_hours``
reads only those. Default is a dry run (prints what it would write, writes nothing); ``--apply`` writes.
``--bars-json FILE`` replays a saved bars response instead of calling Alpaca (tests and proofs).
AUTHORITY: READ_ONLY_ADVISORY. Never touches a broker account or an order route (market data only).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ET = ZoneInfo("America/New_York")
CONFIG_PATH = ROOT / "config" / "market_quotes_extended.json"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("schema") != "MarketQuotesExtended@v1":
        raise ValueError(f"{path}: expected schema MarketQuotesExtended@v1")
    return cfg


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _bar_start(b: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(b["t"]).replace("Z", "+00:00")).astimezone(ET)


def session_of(start_et: datetime, cfg: dict[str, Any]) -> str:
    """premarket / regular / afterhours for a bar starting at ``start_et``."""
    t = start_et.timetz().replace(tzinfo=None)
    if t < _hhmm(cfg["regular_open_et"]):
        return "premarket"
    if t >= _hhmm(cfg["regular_close_et"]):
        return "afterhours"
    return "regular"


def rows_from_bars(
    bars: dict[str, list[dict[str, Any]]], cfg: dict[str, Any], *, now: datetime
) -> list[dict[str, Any]]:
    """The newest extended-session bar per symbol, with the regular close before it. Bars not yet complete at
    ``now`` are ignored (a bar is knowable at start + timeframe)."""
    step = timedelta(minutes=int(str(cfg.get("bar_timeframe", "15Min")).rstrip("Min")))
    close_bar = _hhmm(cfg["regular_close_bar_et"])
    out: list[dict[str, Any]] = []
    for sym, series in sorted((bars or {}).items()):
        done = [b for b in series if _bar_start(b) + step <= now]
        if not done:
            continue
        last = max(done, key=_bar_start)
        start = _bar_start(last)
        sess = session_of(start, cfg)
        if sess == "regular":
            continue
        regular_closes = [
            b for b in done if _bar_start(b).timetz().replace(tzinfo=None) == close_bar and _bar_start(b) < start
        ]
        if not regular_closes:
            continue  # no regular close inside the window: refuse rather than guess a reference
        ref = max(regular_closes, key=_bar_start)
        price, prev = float(last["c"]), float(ref["c"])
        if price <= 0 or prev <= 0:
            continue
        out.append(
            {
                "symbol": sym,
                "price": price,
                "prev_close": prev,
                "day_change_pct": round(100.0 * (price - prev) / prev, 4),
                "volume": int(last.get("v") or 0),
                "fetched_at": (start + step).astimezone(timezone.utc),
                "_session": sess,
                "_reference_bar": _bar_start(ref).isoformat(),
            }
        )
    return out


def fetch_bars(cfg: dict[str, Any], *, now: datetime) -> dict[str, list[dict[str, Any]]]:
    import requests

    import external_market_data_ingest as ingest

    key, sec = ingest._alpaca_creds()
    if not (key and sec):
        raise RuntimeError("alpaca credentials unavailable to the quote ingest (no request sent)")
    params = {
        "symbols": ",".join(cfg["symbols"]),
        "timeframe": cfg.get("bar_timeframe", "15Min"),
        "start": (now - timedelta(hours=float(cfg.get("lookback_hours", 40)))).astimezone(timezone.utc).isoformat(),
        "end": now.astimezone(timezone.utc).isoformat(),
        "feed": cfg.get("feed", "iex"),
        "limit": 10000,
    }
    r = requests.get(BARS_URL, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"alpaca bars HTTP {r.status_code}")
    return (r.json() or {}).get("bars") or {}


def _already_written(cur: Any, rows: list[dict[str, Any]], source: str) -> set[tuple[str, str]]:
    if not rows:
        return set()
    cur.execute(
        "SELECT symbol, fetched_at FROM market_quotes WHERE source = %s AND symbol = ANY(%s) AND fetched_at >= %s",
        [source, [r["symbol"] for r in rows], min(r["fetched_at"] for r in rows)],
    )
    return {(s, f.astimezone(timezone.utc).isoformat()) for s, f in cur.fetchall()}


def run(
    *,
    apply: bool,
    bars_json: str | None = None,
    now: datetime | None = None,
    cfg: dict[str, Any] | None = None,
    conn: Any = None,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    bars = json.loads(Path(bars_json).read_text())["bars"] if bars_json else fetch_bars(cfg, now=now)
    rows = rows_from_bars(bars, cfg, now=now)
    out: dict[str, Any] = {
        "now": now.isoformat(),
        "apply": apply,
        "candidates": len(rows),
        "written": 0,
        "skipped": 0,
        "rows": [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()} for r in rows],
    }
    if not apply or not rows:
        return out
    from lib.writers.market_quotes_writer import write_market_quotes

    own = conn is None
    if own:
        import external_market_data_ingest as ingest

        conn = ingest._get_conn()
    try:
        cur = conn.cursor()
        seen = _already_written(cur, rows, cfg["source_tag"])
        fresh = [r for r in rows if (r["symbol"], r["fetched_at"].isoformat()) not in seen]
        out["skipped"] = len(rows) - len(fresh)
        clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in fresh]
        if clean:
            rc = write_market_quotes(cur, clean, source=cfg["source_tag"])
            out["written"] = int(rc.rows_accepted)
            out["rejected"] = list(getattr(rc, "rejected", []) or [])
        conn.commit()
    finally:
        if own:
            conn.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write to market_quotes (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--bars-json", help="replay a saved Alpaca bars response instead of calling Alpaca")
    ap.add_argument("--now", help="evaluation instant (ISO-8601); default now")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else None
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    out = run(apply=bool(a.apply) and not a.dry_run, bars_json=a.bars_json, now=now)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
