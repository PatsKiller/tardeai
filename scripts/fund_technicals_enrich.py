#!/usr/bin/env python3
"""Fund technicals enrichment (operator 2026-06-21): RSI + week/month/YTD perf for MUTUAL FUNDS.

Finviz (the source of the card's RSI/W/M/YTD strip) does NOT cover mutual funds — FCNTX, AMANX, etc. come
back all-null, so their strip shows "—". Mutual funds DO have daily NAV history in yfinance, so this computes
RSI(14), perf_week, perf_month, perf_ytd, sma50 from that history and stores them in symbol_profiles. The
finviz-strip-map endpoint falls back to these when the Finviz value is null (survives Finviz rebuilds).

Targets held instrument_type='fund' symbols (or --symbols). Read-only to the broker.

Refactor wave 1 (2026-10-10):
- The per-run ``ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS`` is gone. It took an ACCESS
  EXCLUSIVE lock on every run and collided with the concurrent symbol_profiles writers at 06:3x-06:4x
  (9 LockNotAvailable failures vs 2 successes in logs/fund_technicals.log; 10-09 06:38 died on the
  ALTER). The DDL now lives in migrations/2026_10_10_symbol_profiles_fund_technicals_cols.sql; the
  script only CHECKS the columns (information_schema SELECT) and exits 2 naming the migration if any
  is missing.
- ``--dry`` (and its new alias ``--dry-run``) computes everything on a READ ONLY session and never
  reaches upsert/commit. Before this change ``--dry`` still ran the ALTER + commit.
- A real run writes data/runtime/fund_technicals_enrich_last.json (LaneRunReceipt@v1, ok_at only on
  success) and exits 1 when no symbol produced technicals (every fetch failed).
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

from lib.writers.symbol_profiles_writer import upsert_profile  # noqa: E402


def _conn():
    from db_adapter import _get_conn

    return _get_conn()


REQUIRED_COLUMNS = ("rsi14", "perf_week_pct", "perf_month_pct", "sma50_pct", "technicals_updated_at")
MIGRATION = "migrations/2026_10_10_symbol_profiles_fund_technicals_cols.sql"
RECEIPT_NAME = "fund_technicals_enrich"


class MissingColumns(RuntimeError):
    pass


def check_columns(cur) -> None:
    """Read-only schema check (was a per-run ALTER TABLE). Raises MissingColumns naming the migration."""
    cur.execute(
        """SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'symbol_profiles' AND column_name = ANY(%s)""",
        (list(REQUIRED_COLUMNS),),
    )
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


def _held_fund_symbols():
    try:
        h = json.loads(_holdings_path().read_text())
        rows = h.get("holdings") if isinstance(h, dict) else h
        syms = {(r.get("symbol") or "").upper() for r in rows if isinstance(r, dict) and r.get("symbol")}
    except Exception:
        syms = set()
    syms.discard("CASH")
    syms.discard("")
    cur = _conn().cursor()
    cur.execute(
        "SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('fund','mutual_fund') AND upper(symbol)=ANY(%s)",
        (sorted(syms),),
    )
    return sorted({r[0] for r in cur.fetchall()})


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    # Wilder smoothing
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - (100 / (1 + rs)), 2)


def run(symbols=None, apply=True):
    conn = _conn()
    if not apply:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # dry run: the server refuses any write (AGENTS.md §6)
    cur = conn.cursor()
    check_columns(cur)
    syms = symbols or _held_fund_symbols()
    import yfinance as yf, datetime as _dt, time as _t

    done, out = 0, []
    for s in syms:
        try:
            h = yf.Ticker(s).history(period="1y", auto_adjust=False)
        except Exception as e:
            out.append({"symbol": s, "error": str(e)[:60]})
            continue
        if h is None or len(h) < 30:
            out.append({"symbol": s, "error": "insufficient history"})
            continue
        closes = [float(x) for x in h["Close"].tolist() if x == x]
        dates = list(h.index)
        last = closes[-1]

        def perf(n):
            return (
                round((last - closes[-1 - n]) / closes[-1 - n] * 100, 2) if len(closes) > n and closes[-1 - n] else None
            )

        pw = perf(5)
        pm = perf(21)
        # YTD from the first close of the current year
        yr = dates[-1].year
        ytd = None
        for i, dt in enumerate(dates):
            if dt.year == yr:
                if closes[i]:
                    ytd = round((last - closes[i]) / closes[i] * 100, 2)
                break
        sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
        sma50_pct = round((last - sma50) / sma50 * 100, 2) if sma50 else None
        rsi = _rsi(closes)
        rec = {
            "symbol": s,
            "rsi14": rsi,
            "perf_week_pct": pw,
            "perf_month_pct": pm,
            "perf_ytd_pct": ytd,
            "sma50_pct": sma50_pct,
        }
        out.append(rec)
        if apply:
            # ytd_return_pct: a None keeps the value etf_performance_enrich wrote (COALESCE) — same as before.
            rcpt = upsert_profile(
                cur,
                s,
                {
                    "rsi14": rsi,
                    "perf_week_pct": pw,
                    "perf_month_pct": pm,
                    "ytd_return_pct": ytd,
                    "sma50_pct": sma50_pct,
                },
                source="fund_technicals_enrich",
                keep_existing_if_null=("ytd_return_pct",),
            )
            done += rcpt.rows_written
            if rcpt.rejected:
                rec["rejected"] = rcpt.rejected[0]["reason"]
        _t.sleep(0.5)
    computed = sum(1 for r in out if "error" not in r)
    if apply:
        conn.commit()
    else:
        conn.rollback()
        return {
            "ok": True,
            "mode": "dry_run",
            "symbols": len(syms),
            "computed": computed,
            "would_write": {"table": "symbol_profiles", "rows": computed},
            "results": out,
        }
    # Findings are not failure; but a run that had symbols and computed none (every fetch failed) did no work.
    return {"ok": not syms or computed > 0, "symbols": len(syms), "updated": done, "computed": computed, "results": out}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument(
        "--dry", "--dry-run", dest="dry", action="store_true", help="compute on a read-only session; never upsert"
    )
    a = ap.parse_args(argv)
    syms = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else None
    if a.dry:
        try:
            print(json.dumps(run(symbols=syms, apply=False), indent=2, default=str))
        except MissingColumns as exc:
            print(json.dumps({"ok": False, "mode": "dry_run", "error": str(exc)}))
            return 2
        return 0
    from lib.lane_last_receipt import now_iso, write_receipt

    started_at = now_iso()
    try:
        res = run(symbols=syms, apply=True)
    except MissingColumns as exc:
        write_receipt(RECEIPT_NAME, ok=False, started_at=started_at, error=type(exc).__name__)
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    except Exception as exc:
        write_receipt(RECEIPT_NAME, ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    print(json.dumps(res, indent=2, default=str))
    write_receipt(
        RECEIPT_NAME,
        ok=bool(res["ok"]),
        started_at=started_at,
        error=None if res["ok"] else "no symbol produced technicals",
        summary={k: res[k] for k in ("symbols", "updated", "computed")},
    )
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
