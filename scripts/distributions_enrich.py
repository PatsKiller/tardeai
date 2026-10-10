#!/usr/bin/env python3
"""Fund/ETF distribution enrichment (operator 2026-06-21): the fund analog of the earnings line.

Funds/ETFs don't have EPS earnings — they have DISTRIBUTIONS (dividend / cap-gains payouts). yfinance's
forward ex-date is unreliable, but its distribution HISTORY is solid, so we show the real LAST distribution,
infer the cadence (JEPI monthly, SCHD quarterly, FCNTX annual…), estimate the NEXT date from that cadence
(clearly marked est), and total the trailing-12-month payout. Stored in symbol_profiles, surfaced on cards.

Held funds/ETFs (or --symbols). Read-only to the broker.

n8n refactor (2026-10-10, wave 1):
- ``--dry-run`` (``--dry`` kept as an alias) computes every row from yfinance and prints it, and never
  reaches a write: no DDL, no upsert, no commit, no receipt (AGENTS.md §6). It used to run the ALTER TABLE
  in ``ensure_columns()`` first, so the "dry" run took an ACCESS EXCLUSIVE lock on symbol_profiles.
- ``ensure_columns()`` now checks information_schema first and issues the ALTER only when a column is
  missing. ALTER ... ADD COLUMN IF NOT EXISTS still needs the table lock on every run, which is the
  ``LockNotAvailable`` failure in distributions_enrich.log (7 failures vs 6 successes). Moving the DDL to a
  migration is a follow-up.
- A real run writes ``<state_root>/data/runtime/distributions_enrich_last.json`` (LaneRunReceipt@v1,
  ``ok_at`` on success). Exit 1 when every symbol failed to fetch (the source was down, nothing was
  enriched); per-symbol errors alongside successes are findings.
- holdings.json resolves on the persistent (served) state root, not the release checkout.
"""
from __future__ import annotations

import os
import sys
import json
import datetime as dt
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = Path(HERE).parent
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lib.writers.symbol_profiles_writer import upsert_profile  # noqa: E402


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


DIST_COLUMNS = ("last_distribution_date", "last_distribution_amount", "distribution_cadence",
                "next_distribution_est", "ttm_distribution_amount", "distributions_updated_at")


def missing_columns(cur) -> list[str]:
    """DIST_COLUMNS not yet on symbol_profiles (a catalog read; takes no table lock)."""
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='symbol_profiles' "
                "AND column_name = ANY(%s)", (list(DIST_COLUMNS),))
    have = {r[0] for r in cur.fetchall()}
    return [c for c in DIST_COLUMNS if c not in have]


def ensure_columns():
    cur = _conn().cursor()
    if not missing_columns(cur):
        cur.connection.rollback()
        return
    cur.execute("""ALTER TABLE symbol_profiles
        ADD COLUMN IF NOT EXISTS last_distribution_date date,
        ADD COLUMN IF NOT EXISTS last_distribution_amount numeric,
        ADD COLUMN IF NOT EXISTS distribution_cadence text,
        ADD COLUMN IF NOT EXISTS next_distribution_est date,
        ADD COLUMN IF NOT EXISTS ttm_distribution_amount numeric,
        ADD COLUMN IF NOT EXISTS distributions_updated_at timestamptz""")
    cur.connection.commit()


def _held_fund_etf_symbols():
    try:
        h = json.loads((_state_dir() / "holdings.json").read_text())
        rows = h.get("holdings") if isinstance(h, dict) else h
        syms = {(r.get("symbol") or "").upper() for r in rows if isinstance(r, dict) and r.get("symbol")}
    except Exception:
        syms = set()
    syms.discard("CASH"); syms.discard("")
    cur = _conn().cursor()
    cur.execute("SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('fund','etf','mutual_fund','inverse_etf') AND upper(symbol)=ANY(%s)",
                (sorted(syms),))
    return sorted({r[0] for r in cur.fetchall()})


def _state_dir() -> Path:
    try:
        from lib.persistent_state_root import resolve_durable_dir
        return resolve_durable_dir("data/portfolios/state", PROJ)
    except Exception:  # noqa: BLE001
        return PROJ / "data" / "portfolios" / "state"


def _cadence(days):
    """Map a median inter-distribution gap (days) to a label + canonical interval days."""
    if days <= 0:
        return None, None
    if days <= 45:
        return "monthly", 30
    if days <= 135:
        return "quarterly", 91
    if days <= 270:
        return "semi-annual", 182
    return "annual", 365


def run(symbols=None, apply=True):
    if apply:
        ensure_columns()  # DDL only on a real run; a dry run never reaches it
    syms = symbols or _held_fund_etf_symbols()
    import yfinance as yf, time as _t
    conn = _conn(); cur = conn.cursor()
    today = dt.date.today()
    done, out = 0, []
    for s in syms:
        try:
            div = yf.Ticker(s).dividends
            items = [(idx.date(), round(float(v), 4)) for idx, v in div.items()] if div is not None else []
        except Exception as e:
            out.append({"symbol": s, "error": str(e)[:60]}); continue
        if not items:
            out.append({"symbol": s, "note": "no distributions on record"}); continue
        items.sort(key=lambda x: x[0])
        last_date, last_amt = items[-1]
        # cadence from median gap of the last ~6 distributions
        recent = items[-7:]
        gaps = [(recent[i][0] - recent[i - 1][0]).days for i in range(1, len(recent))]
        med = sorted(gaps)[len(gaps) // 2] if gaps else 0
        cad, interval = _cadence(med)
        ttm = round(sum(a for d, a in items if (today - d).days <= 366), 4)
        # Stale schedule guard: if the last payout is older than ~400 days the fund has effectively stopped
        # distributing (e.g. ARKG/ARKX last paid 2021) — don't project a misleading "next" date.
        stale = (today - last_date).days > 400
        next_est = None
        if interval and not stale:
            next_est = last_date + dt.timedelta(days=interval)
            while next_est < today:
                next_est = next_est + dt.timedelta(days=interval)
        if stale:
            cad = "none recently"
        rec = {"symbol": s, "last_distribution_date": str(last_date), "last_distribution_amount": last_amt,
               "distribution_cadence": cad, "next_distribution_est": (str(next_est) if next_est else None),
               "ttm_distribution_amount": ttm}
        out.append(rec)
        if apply:
            rcpt = upsert_profile(cur, s, {"last_distribution_date": last_date, "last_distribution_amount": last_amt,
                                           "distribution_cadence": cad, "next_distribution_est": next_est,
                                           "ttm_distribution_amount": ttm}, source="distributions_enrich")
            done += rcpt.rows_written
            if rcpt.rejected:
                rec["rejected"] = rcpt.rejected[0]["reason"]
        _t.sleep(0.5)
    if apply:
        conn.commit()
    return {"ok": True, "symbols": len(syms), "updated": done, "results": out}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--dry", "--dry-run", dest="dry", action="store_true")
    a = ap.parse_args()
    syms = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else None
    if a.dry:
        res = run(symbols=syms, apply=False)
        cur = _conn().cursor()
        missing = missing_columns(cur)  # catalog SELECT only
        cur.connection.rollback()
        print(json.dumps(res, indent=2, default=str))
        print(f"(dry run — nothing written; would upsert {sum(1 for r in res['results'] if 'last_distribution_date' in r)}"
              f" symbol_profiles rows; would ALTER TABLE for missing columns: {missing or 'none'})")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        res = run(symbols=syms, apply=True)
    except BaseException as exc:
        write_lane_receipt("distributions_enrich", ok=False, exit_code=1, started_at=started,
                           summary={"error": type(exc).__name__})
        raise
    print(json.dumps(res, indent=2, default=str))
    errors = sum(1 for r in res["results"] if "error" in r)
    code = 1 if res["symbols"] and errors == res["symbols"] else 0
    write_lane_receipt("distributions_enrich", ok=code == 0, exit_code=code, started_at=started,
                       summary={"symbols": res["symbols"], "updated": res["updated"], "errors": errors})
    return code


if __name__ == "__main__":
    sys.exit(main())
