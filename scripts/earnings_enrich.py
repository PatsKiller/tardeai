#!/usr/bin/env python3
"""Earnings enrichment (operator 2026-06-21): next earnings date + last-quarter beat/miss for held stocks.

Adds to symbol_profiles: next_earnings_date, last_earnings_date, last_eps_estimate, last_eps_actual,
last_eps_surprise_pct (and earnings_updated_at). Source: yfinance get_earnings_dates() — the most recent
PAST row with a reported EPS is last quarter (beat = surprise >= 0); the nearest FUTURE row is the next
report. Stocks only (ETFs/funds have no per-issuer earnings). Read-only to the broker.

  python3 scripts/earnings_enrich.py            # held stocks
  python3 scripts/earnings_enrich.py --symbols NOC,LMT
  python3 scripts/earnings_enrich.py --dry-run     # (= --dry) fetch + compute, write nothing

Refactor wave 2 (cron -> n8n, 2026-10-10; cron:L551):
- The per-run ``ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS`` (ensure_columns, run even on
  --dry, and committed) is gone: it took an ACCESS EXCLUSIVE lock every run and contended with the
  06:35-06:45 symbol_profiles writers (2 LockNotAvailable in logs/earnings_enrich.log). The DDL lives
  in migrations/2026_10_10_symbol_profiles_earnings_cols.sql; the script only CHECKS the columns
  (information_schema SELECT) and exits 2 naming the migration if any is missing.
- ``--dry`` (and its alias ``--dry-run``) runs on a READ ONLY session and never reaches
  ``write_earnings``/commit; it still asks yfinance (free, read-only) so the report shows real values.
- holdings.json is read from the SERVED state dir (persistent root first).
- A real run writes data/runtime/earnings_enrich_last.json (LaneRunReceipt@v1, ok_at only on success)
  and exits 1 when it had symbols and every yfinance fetch raised. Provider "no dates" is a finding.
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = Path(HERE).parent
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lib.writers.symbol_profiles_writer import EARNINGS_UNKNOWN, earnings_state_for, write_earnings  # noqa: E402


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


REQUIRED_COLUMNS = ("next_earnings_date", "last_earnings_date", "last_eps_estimate", "last_eps_actual",
                    "last_eps_surprise_pct", "earnings_updated_at")
MIGRATION = "migrations/2026_10_10_symbol_profiles_earnings_cols.sql"
RECEIPT_NAME = "earnings_enrich"


class MissingColumns(RuntimeError):
    pass


def check_columns(cur) -> None:
    """Read-only schema check (was per-run DDL). Raises MissingColumns naming the migration."""
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'symbol_profiles' AND column_name = ANY(%s)""", (list(REQUIRED_COLUMNS),))
    have = {r[0] for r in cur.fetchall()}
    missing = [c for c in REQUIRED_COLUMNS if c not in have]
    if missing:
        raise MissingColumns(f"symbol_profiles is missing {missing}; apply {MIGRATION}")


def _holdings_path() -> Path:
    """The SERVED holdings.json (persistent root first), not a checkout copy (AGENTS.md §9.4)."""
    try:
        from lib.persistent_state_root import portfolio_state_write_targets

        return portfolio_state_write_targets(PROJ)[0] / "holdings.json"
    except Exception:  # noqa: BLE001 -- resolution layer unavailable: the code tree (old behaviour)
        return PROJ / "data" / "portfolios" / "state" / "holdings.json"


def _held_stock_symbols():
    try:
        h = json.loads(_holdings_path().read_text())
        rows = h.get("holdings") if isinstance(h, dict) else h
        syms = {(r.get("symbol") or "").upper() for r in rows if isinstance(r, dict) and r.get("symbol")}
    except Exception:
        syms = set()
    syms.discard("CASH"); syms.discard("")
    cur = _conn().cursor()
    cur.execute("""SELECT upper(symbol) FROM symbol_profiles
                   WHERE (instrument_type='stock' OR instrument_type IS NULL) AND upper(symbol) = ANY(%s)
                     AND symbol ~ '^[A-Z]{1,5}$'""", (sorted(syms),))
    return sorted({r[0] for r in cur.fetchall()})


def _watchlist_top_symbols(n: int):
    """Hermes-top-N watchlist stocks — the set the watch page actually renders (card layer
    shows 'Next earnings <date>' from symbol_profiles.next_earnings_date)."""
    cur = _conn().cursor()
    cur.execute("""SELECT DISTINCT upper(symbol) FROM watchlist_items
                   WHERE status IN ('active','researched')
                     AND hermes_rank IS NOT NULL AND hermes_rank <= %s
                     AND symbol ~ '^[A-Z]{1,5}$'""", (n,))
    return sorted({r[0] for r in cur.fetchall()})


def _needs_refresh(symbols, stale_days: int):
    """Earnings dates move rarely — only refetch rows that are missing, stale, or past-dated."""
    if not symbols:
        return []
    cur = _conn().cursor()
    cur.execute("""SELECT upper(symbol) FROM symbol_profiles
                   WHERE upper(symbol) = ANY(%s)
                     AND earnings_updated_at IS NOT NULL
                     AND earnings_updated_at > NOW() - (%s || ' days')::interval
                     AND (next_earnings_date IS NULL OR next_earnings_date >= CURRENT_DATE)""",
                (symbols, str(stale_days)))
    fresh = {r[0] for r in cur.fetchall()}
    return [s for s in symbols if s not in fresh]


def _fnum(v):
    try:
        f = float(v)
        return None if f != f else round(f, 4)   # NaN guard
    except Exception:
        return None


def _extract(ed):
    """From a yfinance earnings_dates DataFrame (index=Timestamp, cols: 'EPS Estimate','Reported EPS',
    'Surprise(%)'), return (next_date, last_date, est, actual, surprise_pct)."""
    import datetime as _dt
    next_d = last = est = act = sur = None
    try:
        rows = []
        for idx, row in ed.iterrows():
            d = idx.date() if hasattr(idx, "date") else None
            rows.append((d, _fnum(row.get("EPS Estimate")), _fnum(row.get("Reported EPS")), _fnum(row.get("Surprise(%)"))))
        today = _dt.date.today()
        # next = earliest future date with no reported EPS
        futures = sorted([r for r in rows if r[0] and r[0] >= today], key=lambda r: r[0])
        for r in futures:
            if r[2] is None:
                next_d = r[0]; break
        # last = most recent past date that HAS a reported EPS
        pasts = sorted([r for r in rows if r[0] and r[0] < today and r[2] is not None], key=lambda r: r[0], reverse=True)
        if pasts:
            last, est, act, sur = pasts[0]
    except Exception:
        pass
    return next_d, last, est, act, sur


def run(symbols=None, apply=True, watchlist_top=200, stale_days=3):
    """Default scope = held stocks + Hermes-top-N watchlist (card layer needs next_earnings_date
    on the symbols operators actually view — was held-only, leaving 181/200 cards without a date).
    Staleness filter keeps the daily yfinance call count near the churn, not the universe."""
    conn = _conn()
    if not apply:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
    check_columns(conn.cursor())
    if symbols:
        syms = symbols
    else:
        syms = sorted(set(_held_stock_symbols()) | set(_watchlist_top_symbols(watchlist_top)))
        skipped = len(syms)
        syms = _needs_refresh(syms, stale_days)
        skipped -= len(syms)
        if skipped:
            print(f"  [earnings] {skipped} symbols fresh (<{stale_days}d) — skipped")
    if not apply:
        conn.rollback()  # end the read transaction before the slow fetch loop (idle-in-transaction timeout)
    import yfinance as yf, time as _t
    cur = conn.cursor()
    done, out = 0, []
    for s in syms:
        try:
            ed = yf.Ticker(s).get_earnings_dates(limit=12)
        except Exception as e:
            out.append({"symbol": s, "error": str(e)[:60]}); continue
        if ed is None or len(ed) == 0:
            # Provider did not answer: UNKNOWN. Nothing is written (the write module refuses UNKNOWN),
            # so the row stays stale/never-enriched and earnings_provider reads it as UNKNOWN -> gates fail closed.
            out.append({"symbol": s, "error": "no earnings_dates", "earnings_state": EARNINGS_UNKNOWN}); continue
        nd, ld, est, act, sur = _extract(ed)
        state = earnings_state_for(nd, provider_answered=True)   # SCHEDULED if a date, else NONE_SCHEDULED
        rec = {"symbol": s, "earnings_state": state, "next_earnings_date": str(nd) if nd else None,
               "last_earnings_date": str(ld) if ld else None, "last_eps_estimate": est,
               "last_eps_actual": act, "last_eps_surprise_pct": sur,
               "beat": (None if sur is None else sur >= 0)}
        out.append(rec)
        if apply:
            rcpt = write_earnings(cur, s, state=state, next_earnings_date=nd, last_earnings_date=ld,
                                  last_eps_estimate=est, last_eps_actual=act, last_eps_surprise_pct=sur)
            done += rcpt.rows_written
            if rcpt.rejected:
                rec["rejected"] = rcpt.rejected[0]["reason"]
        _t.sleep(0.5)
    fetch_errors = sum(1 for r in out if "error" in r and r.get("earnings_state") != EARNINGS_UNKNOWN)
    if not apply:
        conn.rollback()
        return {"ok": True, "mode": "dry_run", "symbols": len(syms),
                "would_write": {"table": "symbol_profiles", "rows": sum(1 for r in out if "error" not in r)},
                "results": out}
    conn.commit()
    # Findings are not failure; a run whose every fetch raised did no work.
    return {"ok": not syms or fetch_errors < len(syms), "symbols": len(syms), "updated": done,
            "fetch_errors": fetch_errors, "results": out}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--dry", "--dry-run", dest="dry", action="store_true",
                    help="read-only session; fetch + compute, never write")
    ap.add_argument("--watchlist-top", type=int, default=200, help="include Hermes top-N watchlist symbols (0 = held only)")
    ap.add_argument("--stale-days", type=int, default=3, help="skip symbols refreshed within N days")
    a = ap.parse_args(argv)
    syms = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else None
    kw = dict(symbols=syms, watchlist_top=a.watchlist_top, stale_days=a.stale_days)
    if a.dry:
        try:
            print(json.dumps(run(apply=False, **kw), indent=2, default=str))
        except MissingColumns as exc:
            print(json.dumps({"ok": False, "mode": "dry_run", "error": str(exc)}))
            return 2
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started_at = now_iso()
    try:
        res = run(apply=True, **kw)
    except MissingColumns as exc:
        write_receipt(RECEIPT_NAME, ok=False, started_at=started_at, error=str(exc))
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    except Exception as exc:
        write_receipt(RECEIPT_NAME, ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    print(json.dumps(res, indent=2, default=str))
    write_receipt(RECEIPT_NAME, ok=res["ok"], started_at=started_at,
                  summary={"symbols": res["symbols"], "updated": res["updated"], "fetch_errors": res["fetch_errors"]},
                  error=None if res["ok"] else f"every fetch failed ({res['fetch_errors']}/{res['symbols']})")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
