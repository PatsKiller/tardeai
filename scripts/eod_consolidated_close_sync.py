#!/usr/bin/env python3
"""Replace IEX-derived daily closes with the consolidated close when they disagree.

WHY
---
``ticker_prices`` closes with ``source='market_quotes'`` come from Alpaca's free
IEX feed: the last print on ONE exchange, not the consolidated tape. For liquid
names that is the close; for thin names it is not. Litmus 2026-09-14 against
Yahoo Finance (session 09-11): 88 of 118 sampled quote-derived closes within
1%, 30 off by more than 1%, 6 off by more than 10% (ADTX 0.0093 vs 0.0070, MNSX
24.36 vs 20.63, EQS 1.085 vs 0.98). RSI, SMA and every support/resistance level
built on those series inherited the error. Operator decision the same day:
closes should come from a consolidated end-of-day source.

Operator price rule 2026-11-07: never yfinance. The consolidated close is
Alpaca's SIP daily bar (the consolidated tape, the ``bars`` grant in
``config/data_source_authority.json``), read through the existing
``market_data_snapshot_loader.fetch_alpaca_daily_bars`` -- the same path the
market-reference-bars lane uses, with its SIP-delay clamp. No new network
source. Rows this lane wrote earlier as ``yfinance_eod`` (and any ``yfinance``
row for the session) are replaced by the Alpaca close whenever one exists,
whatever the deviation, because their source is forbidden (LQ-20261107-455).

WHAT
----
For one completed session: read that session's ``market_quotes``-derived closes,
fetch Alpaca's SIP daily close for the same symbols, and plan a replacement for
each close more than TOLERANCE away. ``--apply``
writes the plan through the one ticker_prices write module
(``lib.writers.ticker_prices_writer``) with ``source='alpaca_eod'`` and
overwrite-on-conflict; without it nothing is written. A replacement larger than
MAX_REPLACEMENT is NOT applied -- that is a quarantine question, not a sync -- and
is listed in the receipt.

    python scripts/eod_consolidated_close_sync.py                 # dry run: plan + receipt path, no writes
    python scripts/eod_consolidated_close_sync.py --apply
    python scripts/eod_consolidated_close_sync.py --session 2026-09-11

A symbol Alpaca has no bar for keeps its stored close and counts as
``no_reference``; there is no fallback to another provider.

AUTHORITY: READ_ONLY_ADVISORY (market data only). MBI = 0. No broker, no model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCHEMA = "EodConsolidatedCloseSync@v1"
RECEIPT = PROJECT_ROOT / "data" / "runtime" / "eod_consolidated_close_sync_last_run.json"
SOURCE = "alpaca_eod"
#: rows written from a source the operator price rule forbids (2026-11-07): replaced by the Alpaca close at ANY
#: deviation, so the session never keeps a yfinance close the Alpaca tape can answer for (LQ-20261107-455)
FORBIDDEN_SOURCES = ("yfinance_eod", "yfinance")
REPLACEABLE_SOURCES = ("market_quotes", *FORBIDDEN_SOURCES)
TOLERANCE = 0.01          # closer than 1% is the same close
MAX_REPLACEMENT = 0.50    # a >50% disagreement is not synced; it is reported for quarantine review
ET = ZoneInfo("America/New_York")
NO_CONSUMER_REASON = "scheduled data-hygiene lane; the receipt is its output, ticker_prices its store"


def plan_replacements(stored: Iterable[tuple[str, str, float]], reference: dict[str, Optional[float]]) -> dict:
    """Pure. stored = (symbol, source, close); reference = {symbol: consolidated close}."""
    replace: list[dict] = []
    held_back: list[dict] = []
    unchanged = no_reference = 0
    for sym, src, close in stored:
        ref = reference.get(sym)
        if src not in REPLACEABLE_SOURCES:
            continue
        if not ref or ref <= 0 or close is None:
            no_reference += 1
            continue
        dev = abs(float(close) - ref) / ref
        if dev <= TOLERANCE and src not in FORBIDDEN_SOURCES:
            unchanged += 1
            continue
        row = {"symbol": sym, "stored": float(close), "consolidated": round(float(ref), 6),
               "deviation_pct": round(dev * 100, 2), "stored_source": src}
        (held_back if dev > MAX_REPLACEMENT else replace).append(row)
    return {"replace": replace, "held_back": held_back, "unchanged": unchanged, "no_reference": no_reference}


def _setting(key: str, default: str = "") -> str:
    val = os.getenv(key, "")
    if val:
        return val
    try:
        for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return default


def _connect(*, read_only: bool):
    import psycopg2  # noqa: PLC0415

    return psycopg2.connect(host=_setting("DB_HOST", "localhost"), dbname=_setting("DB_NAME", "trade_ai"),
                            user=_setting("DB_USER", "trade_ai"), password=_setting("DB_PASSWORD"),
                            options="-c default_transaction_read_only=on" if read_only else None,
                            connect_timeout=5)


def default_session(now: Optional[datetime] = None) -> date:
    """Today after 16:30 ET on a weekday; otherwise the previous weekday."""
    n = (now or datetime.now(timezone.utc)).astimezone(ET)
    d = n.date()
    if d.weekday() < 5 and (n.hour, n.minute) >= (16, 30):
        return d
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _alpaca_closes(symbols: list[str], session: date, *, fetch=None,
                   today: Optional[date] = None) -> dict[str, Optional[float]]:
    """Alpaca SIP daily close of ``session`` per symbol; None when Alpaca has no bar for that session.

    ``fetch(symbol, days)`` defaults to ``market_data_snapshot_loader.fetch_alpaca_daily_bars``, which keys each bar
    by its ET session (``bar_time`` = midnight America/New_York) and ends the window before the SIP delay."""
    if fetch is None:
        import market_data_snapshot_loader as mdl  # noqa: PLC0415 -- network path, imported only when it runs

        fetch = mdl.fetch_alpaca_daily_bars
    days = max(5, ((today or datetime.now(ET).date()) - session).days + 5)
    out: dict[str, Optional[float]] = {}
    for sym in symbols:
        close = None
        for b in fetch(sym, days) or []:
            bt = b.get("bar_time")
            d = bt.astimezone(ET).date() if isinstance(bt, datetime) else bt
            if d == session and b.get("close") is not None:
                close = float(b["close"])
        out[sym] = close
    return out


def _execute() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="write the replacements (default: dry run)")
    ap.add_argument("--session", help="YYYY-MM-DD (default: today after 16:30 ET, else previous weekday)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-backfill", action="store_true",
                    help="permit --apply for a session other than the default one")
    args = ap.parse_args()
    session = date.fromisoformat(args.session) if args.session else default_session()
    if args.apply and session != default_session() and not args.allow_backfill:
        # Alpaca's daily bars are split-adjusted (adjustment=split). On the evening of the session
        # nothing has been adjusted yet; days later a reverse split would rewrite an
        # old close into a different scale from the rest of the series (dry run for
        # 09-11 on 09-14 held back GAUZ 0.3597 vs 7.80, FAIR 0.535 vs 4.00).
        print(f"REFUSED: --apply for {session} is a backfill (default session is {default_session()}); "
              "re-run with --allow-backfill after reviewing the dry run", file=sys.stderr)
        return 2
    try:
        conn = _connect(read_only=True)
        cur = conn.cursor()
        cur.execute("SELECT symbol, source, close_price FROM ticker_prices WHERE price_date = %s "
                    "AND source = ANY(%s) AND symbol ~ '^[A-Z]{1,5}$' AND close_price > 0",
                    (session, list(REPLACEABLE_SOURCES)))
        stored = [(str(s), str(src), float(c)) for s, src, c in cur.fetchall()]
        conn.close()
        reference = _alpaca_closes(sorted({s for s, _, _ in stored}), session) if stored else {}
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    plan = plan_replacements(stored, reference)
    written = rejected = 0
    if args.apply and plan["replace"]:
        from lib.writers.ticker_prices_writer import write_ticker_prices  # noqa: PLC0415

        conn = _connect(read_only=False)
        try:
            cur = conn.cursor()
            rc = write_ticker_prices(cur, [{"symbol": r["symbol"], "price_date": session,
                                            "close_price": r["consolidated"]} for r in plan["replace"]],
                                     source=SOURCE, on_conflict="overwrite", round_to=None, stamp_created_at=True)
            conn.commit()
            written, rejected = rc.rows_accepted, len(rc.rows_rejected)
        finally:
            conn.close()
    report = {"schema": SCHEMA, "ran_at": datetime.now(timezone.utc).isoformat(), "session": session.isoformat(),
              "mode": "apply" if args.apply else "dry_run", "stored_rows": len(stored),
              "reference_source": "alpaca_sip_daily_bar", "written_source": SOURCE,
              "replace": len(plan["replace"]), "held_back": plan["held_back"], "unchanged": plan["unchanged"],
              "no_reference": plan["no_reference"], "written": written, "rejected": rejected,
              "largest_replacements": sorted(plan["replace"], key=lambda r: -r["deviation_pct"])[:20],
              "authority": "READ_ONLY_ADVISORY"}
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"EOD consolidated close sync — session {session} — {report['mode']}")
        print(f"  stored={len(stored)} unchanged={plan['unchanged']} replace={len(plan['replace'])} "
              f"held_back={len(plan['held_back'])} no_reference={plan['no_reference']} written={written}")
        for r in report["largest_replacements"][:8]:
            print(f"  {r['symbol']:6} {r['stored']:>12} -> {r['consolidated']:<12} ({r['deviation_pct']}%)")
        for r in plan["held_back"][:5]:
            print(f"  HELD BACK {r['symbol']} {r['stored']} vs {r['consolidated']} ({r['deviation_pct']}%) — quarantine review")
    if args.apply:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0


def main(argv=None) -> int:
    """Strict offline inspection before the legacy business execution path."""
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="write the replacements (default: dry run)")
    ap.add_argument("--session", help="YYYY-MM-DD (default: today after 16:30 ET, else previous weekday)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-backfill", action="store_true",
                    help="permit --apply for a session other than the default one")
    ap.add_argument("--dry-run", action="store_true", help="offline source plan")
    args = ap.parse_args(argv)
    lane = "eod-consolidated-close-sync"
    if args.dry_run:
        print(f"DRY-RUN {lane}: would compare session closes and propose approved consolidated replacements; no prices, provider or writes; options={vars(args)}; inputs NOT_MEASURED")
        return 0
    try:
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    except ImportError:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    previous = sys.argv
    sys.argv = [previous[0], *argv]
    try:
        result = _execute()
        rc = int(result) if isinstance(result, int) else 0
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="eod_consolidated_close_sync.py", summary={"completed": rc == 0})
        raise
    except Exception as exc:
        write_lane_receipt(lane, ok=False, exit_code=1, started_at=started, script="eod_consolidated_close_sync.py", error=type(exc).__name__)
        raise
    finally:
        sys.argv = previous
    write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="eod_consolidated_close_sync.py", summary={"completed": rc == 0})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
