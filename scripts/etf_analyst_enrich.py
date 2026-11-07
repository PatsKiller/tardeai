#!/usr/bin/env python3
"""etf_analyst_enrich.py — give ETFs (and funds) an "analyst prediction".

ETFs/funds do NOT get traditional sell-side price targets (analysts cover companies, not baskets). So we
produce TWO honest signals and store them in symbol_profiles:
  1. direct: yfinance analyst fields if the provider has any (rare for ETFs);
  2. look_through_upside: the holdings-weighted average analyst upside of the ETF's top constituents — i.e.
     "what do analysts think of what this ETF actually holds." This is the defensible analyst view for a
     basket. For inverse ETFs the sign is flipped (short exposure).

Read-only re: trading. Bounded + polite (yfinance). Run after classify_instruments.py.

Lane ``etf-analyst-enrich`` (cron L505). ``--dry-run`` opens a READ ONLY session and runs only SELECTs: the
ETF/fund rows, how many constituents already have analyst history, and whether the two analyst columns
exist (naming the migration that adds them when they do not). It returns before any yfinance request and
before any symbol_profiles / yahoo_analyst_targets_history write. No receipt.

No DDL (2026-11-07, LQ-20261107-105): this script used to run ``ALTER TABLE symbol_profiles ADD COLUMN IF
NOT EXISTS`` on every real run. An ADD COLUMN takes an ACCESS EXCLUSIVE lock on symbol_profiles — the
whole table, against every reader and writer — and ``db_adapter`` sets ``lock_timeout = 3s`` on each
connection, so one concurrent transaction on the table killed the run:

    $ pg log 2026-11-07 07:00:09.375 EST [731183] trade_ai@trade_ai
    ERROR:  canceling statement due to lock timeout
    STATEMENT:  ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS analyst_look_through_pct numeric

The DDL now lives in ``migrations/2026_11_07_symbol_profiles_analyst_cols.sql`` (the same refactor
``fund_technicals_enrich.py`` took on 2026-10-10, for the same cause). The script only CHECKS the columns
with an ``information_schema`` SELECT and raises ``MissingColumns`` naming the migration file if one is
absent. A run never asks for a table lock, so no other lane can make it time out.

A real run writes ``<state_root>/data/runtime/etf-analyst-enrich_last.json`` (LaneRunReceipt@v1; ``ok_at``
only on success). Exit codes: 0 = ran (ETFs without holdings data, or no constituent needing a fetch, are
findings); 1 = the run failed: crash / DB unavailable (failed receipt, exception re-raised), yfinance
unavailable, ETF/fund rows existed but pass 1 got no holdings and no direct target for any of them, or
constituents needed a fetch and 0 were fetched; 2 = usage error, or the analyst columns are missing and
the migration above has not been applied.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
from db_adapter import _get_conn
from lib.writers.symbol_profiles_writer import upsert_profile

LANE_ID = "etf-analyst-enrich"
ETF_CAP = 45
CONSTITUENT_CAP = 120
REQUIRED_COLUMNS = ("analyst_look_through_pct", "analyst_basis")
MIGRATION = "migrations/2026_11_07_symbol_profiles_analyst_cols.sql"
_ETF_SQL = """SELECT upper(symbol), instrument_type, direction_hint FROM symbol_profiles
                   WHERE instrument_type IN ('etf','inverse_etf','fund')"""


class MissingColumns(RuntimeError):
    """symbol_profiles lacks an analyst column and the migration has not been applied here."""


def present_columns(cur) -> list[str]:
    """Which of the two analyst columns exist (information_schema SELECT — never a table lock)."""
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'symbol_profiles'
                     AND column_name = ANY(%s)""", (list(REQUIRED_COLUMNS),))
    return sorted(r[0] for r in cur.fetchall())


def check_columns(cur) -> None:
    """Read-only schema check (was a per-run ALTER TABLE). Raises MissingColumns naming the migration."""
    have = set(present_columns(cur))
    missing = [c for c in REQUIRED_COLUMNS if c not in have]
    if missing:
        raise MissingColumns(f"symbol_profiles is missing {missing}; apply {MIGRATION}")



def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.etf_analyst_enrich
        from scripts.lib import lane_last_receipt as lr
    return lr


def _holding_upsides(cur, symbols):
    """Latest analyst upside_pct per holding from yahoo_analyst_targets_history (target vs current)."""
    if not symbols:
        return {}
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, target_mean_price, current_price
                   FROM yahoo_analyst_targets_history WHERE upper(symbol)=ANY(%s)
                   ORDER BY symbol, created_at DESC""", ([s.upper() for s in symbols],))
    out = {}
    for s, tm, cp in cur.fetchall():
        if tm and cp and float(cp) > 0:
            out[s.upper()] = round((float(tm) - float(cp)) / float(cp) * 100, 1)
    return out


def preview() -> dict:
    """Dry run (AGENTS.md §6): READ ONLY session, SELECTs only -- no DDL, no yfinance, no write."""
    conn = _get_conn()
    _receipt_lib().enforce_readonly(conn)
    cur = conn.cursor()
    have_cols = present_columns(cur)
    cur.execute(_ETF_SQL)
    etfs = cur.fetchall()
    cur.execute("SELECT count(DISTINCT upper(symbol)) FROM yahoo_analyst_targets_history")
    with_history = int((cur.fetchone() or (0,))[0] or 0)
    conn.rollback()
    batch = [r[0] for r in etfs[:ETF_CAP]]
    missing = [c for c in REQUIRED_COLUMNS if c not in have_cols]
    return {"etfs_funds": len(etfs), "would_fetch_etfs": len(batch), "first_etfs": batch[:10],
            "symbols_with_analyst_history": with_history, "constituent_fetch_cap": CONSTITUENT_CAP,
            "analyst_columns_present": have_cols,
            "analyst_columns_missing": missing,
            # The real run would stop on the check, not write: name the migration, not a phantom DDL statement.
            "required_migration": MIGRATION if missing else None}


def enrich():
    conn = _get_conn()
    cur = conn.cursor()
    # Read-only schema check. The ALTER these two columns used to need took ACCESS EXCLUSIVE on
    # symbol_profiles and died on db_adapter's 3s lock_timeout whenever another transaction held the
    # table (2026-11-07 07:00 ET). The DDL is a migration now (see the module docstring).
    check_columns(cur)
    conn.rollback()  # end the check's read transaction before the long yfinance passes
    cur.execute(_ETF_SQL)
    etfs = cur.fetchall()
    try:
        import yfinance as yf
        import time as _t
        from db_adapter import save_yahoo_analyst_targets_history
    except Exception as e:
        print("yfinance unavailable:", e)
        return {"ok": False, "error": f"yfinance unavailable: {type(e).__name__}", "etfs_funds": len(etfs)}

    # Pass 1: top holdings + weights per ETF (and direct provider target if any).
    etf_holdings, direct_up = {}, {}
    for sym, itype, direction in etfs[:ETF_CAP]:
        _t.sleep(0.8)
        try:
            tk = yf.Ticker(sym)
            info = tk.info
            tm, cp = info.get("targetMeanPrice"), info.get("currentPrice") or info.get("regularMarketPrice")
            if tm and cp and cp > 0:
                direct_up[sym] = round((tm - cp) / cp * 100, 1)
            fd = getattr(tk, "funds_data", None)
            top = fd.top_holdings if fd is not None else None
            if top is not None and len(top):
                etf_holdings[sym] = [(str(s).upper(), float(w)) for s, w in zip(top.index, top.iloc[:, -1])][:12]
        except Exception:
            continue

    # Pass 2: fetch analyst for constituents we don't already have (dedup, bounded), save to history.
    have = set()
    cur.execute("SELECT DISTINCT upper(symbol) FROM yahoo_analyst_targets_history")
    have = {r[0] for r in cur.fetchall()}
    need = sorted({h for hs in etf_holdings.values() for h, _ in hs} - have)
    import datetime
    ds = datetime.datetime.now().strftime("%Y-%m-%d")
    fetched = 0
    for s in need[:CONSTITUENT_CAP]:
        _t.sleep(0.8)
        try:
            info = yf.Ticker(s).info
            tm, nop = info.get("targetMeanPrice"), info.get("numberOfAnalystOpinions")
            if tm is None and not nop:
                continue
            # Keyword arguments (2026-10-10): the signature is (snapshot_date, targets_payload). Passing them
            # positionally in the reverse order iterated the date string, raised inside the bare except
            # below, and discarded every constituent's .info call (up to CONSTITUENT_CAP a run).
            save_yahoo_analyst_targets_history(snapshot_date=ds, targets_payload=[{
                "symbol": s, "current_price": info.get("currentPrice"),
                "target_mean_price": tm, "target_high_price": info.get("targetHighPrice"),
                "target_low_price": info.get("targetLowPrice"), "target_median_price": info.get("targetMedianPrice"),
                "recommendation_mean": info.get("recommendationMean"),
                "recommendation_key": info.get("recommendationKey"), "number_of_analyst_opinions": nop}])
            fetched += 1
        except Exception:
            continue

    # Pass 3: compute holdings-weighted look-through from the now-populated analyst history.
    done = 0
    dirmap = {sym: direction for sym, _, direction in etfs}
    for sym, hs in etf_holdings.items():
        holds = [h for h, _ in hs]
        wts = {h: w for h, w in hs}
        ups = _holding_upsides(cur, holds)
        ncov = len([h for h in holds if h in ups])
        num = sum(wts[h] * ups[h] for h in holds if h in ups)
        den = sum(wts[h] for h in holds if h in ups)
        # require >=2 covered constituents — a 1-stock "look-through" isn't a basket view, just that stock.
        lt = round(num / den, 1) if (den > 0 and ncov >= 2) else None
        if lt is not None and dirmap.get(sym) == "short":
            lt = round(-lt, 1)
        final = direct_up.get(sym) if direct_up.get(sym) is not None else lt
        basis = ("direct analyst target" if sym in direct_up else
                 (f"holdings look-through ({len([h for h in holds if h in ups])} constituents)" if lt is not None else None))
        upsert_profile(cur, sym, {"analyst_look_through_pct": final, "analyst_basis": basis},
                       source="etf_analyst_enrich")
        if final is not None:
            done += 1
    conn.commit()
    res = {"ok": True, "etfs_funds": len(etfs), "etfs_with_holdings": len(etf_holdings),
           "etfs_with_direct_target": len(direct_up), "constituents_needed": len(need[:CONSTITUENT_CAP]),
           "constituents_fetched": fetched, "with_analyst_view": done}
    print(json.dumps(res, indent=2))
    return res


def run_failed(res: dict) -> bool:
    """Honest exit (see module docstring)."""
    if not res.get("ok"):
        return True
    pass1_empty = res["etfs_funds"] > 0 and not res["etfs_with_holdings"] and not res["etfs_with_direct_target"]
    nothing_fetched = res["constituents_needed"] > 0 and res["constituents_fetched"] == 0
    return pass1_empty or nothing_fetched


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="ETF/fund analyst look-through into symbol_profiles.")
    ap.add_argument("--dry-run", action="store_true", help="SELECTs only (READ ONLY); no DDL, fetch or write")
    a = ap.parse_args(argv)
    lr = _receipt_lib()
    if a.dry_run:
        # Structural (AGENTS.md §6): enrich() -- yfinance, upserts -- is not reachable from this branch.
        plan = preview()
        lr.dry_run_report(
            LANE_ID, plan,
            # No DDL is ever "would do": a missing column stops the run (exit 2) and names the migration.
            would_write=([] if plan["required_migration"] else
                         [f"symbol_profiles analyst_look_through_pct/analyst_basis (<= {plan['would_fetch_etfs']} rows)",
                          f"yahoo_analyst_targets_history (<= {CONSTITUENT_CAP} constituent rows)"]))
        return 0
    started = lr.now_iso()
    try:
        res = enrich()
    except MissingColumns as exc:
        # Configuration, not a crash: say which migration is missing and exit 2 (fund_technicals_enrich.py's rule).
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=2, started_at=started, script="etf_analyst_enrich.py",
                              error=str(exc), output={"produced_count": 0, "attempted_count": 0,
                                                      "skipped_reasons": {"schema_migration_missing": 1}})
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script="etf_analyst_enrich.py",
                              error=f"{type(exc).__name__}: {exc}",
                              output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    failed = run_failed(res)
    rc = 1 if failed else 0
    lr.write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started, script="etf_analyst_enrich.py",
                          summary={k: v for k, v in res.items() if k != "ok"}, output=lane_output(res))
    return rc


def lane_output(res: dict) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: ETFs/funds upserted onto symbol_profiles WITH an
    analyst view). attempted = ETFs whose holdings were read (each is upserted); no ETF/fund in the universe is
    fatal (``universe_empty_unexpected``)."""
    produced = int(res.get("with_analyst_view") or 0)
    attempted = int(res.get("etfs_with_holdings") or 0)
    skipped = {"no_analyst_view": max(attempted - produced, 0)}
    if not res.get("ok", True):
        skipped["dependency_unavailable"] = 1  # yfinance import failed (the run also exits 1)
    elif not int(res.get("etfs_funds") or 0):
        skipped["universe_empty_unexpected"] = 1
    return {"produced_count": produced, "attempted_count": max(attempted, produced), "skipped_reasons": skipped,
            "empty_reason": None}


if __name__ == "__main__":
    raise SystemExit(main())
