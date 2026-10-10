#!/usr/bin/env python3
"""etf_performance_enrich.py — YTD price performance + dividend yield + trailing dividend for ETFs/funds
(and any instrument), from yfinance. Fills the gap the operator flagged: "I want actual ETF YTD performance
... yield and dividends." Stores on symbol_profiles so the watchlist API → skill → agent can report it.

YTD = price return (year-start close → latest close). Yield = trailing dividend yield. Dividend = TTM $/share.
Read-only re: trading. Bounded + polite. --symbols X,Y to target; default = all etf/fund/inverse_etf on
symbol_profiles. Cron weekly alongside classify_instruments/etf_analyst.

Lane ``etf-performance-enrich`` (cron L520). ``--dry-run`` (and the older ``--no-fetch``, now the same thing)
opens a READ ONLY session and runs only SELECTs: the target symbols and whether the four performance
columns exist. It returns before the per-run ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` (which
``--no-fetch`` used to execute and commit: a "no-op" that ran DDL), before any yfinance request and before
any symbol_profiles write. Moving the DDL to a migration is a follow-up. No receipt.

A real run writes ``<state_root>/data/runtime/etf-performance-enrich_last.json`` (LaneRunReceipt@v1;
``ok_at`` only on success). Exit codes: 0 = ran (some symbols without data, or zero target symbols, are
findings); 1 = the run failed: crash / DB unavailable (failed receipt, exception re-raised), or symbols
were attempted and every one raised or came back with no YTD, yield or dividend value (nothing could be
fetched when work existed); 2 = usage error.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
if not __import__("os").getenv("DB_PASSWORD"):
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
from db_adapter import _get_conn
from lib.writers.symbol_profiles_writer import upsert_profile

LANE_ID = "etf-performance-enrich"
SYMBOL_CAP = 300
_PERF_COLS = (("ytd_return_pct", "numeric"), ("dividend_yield_pct", "numeric"),
              ("ttm_dividend", "numeric"), ("perf_updated_at", "timestamptz"))
_TARGET_SQL = "SELECT upper(symbol) FROM symbol_profiles WHERE instrument_type IN ('etf','fund','inverse_etf') ORDER BY 1"


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.etf_performance_enrich
        from scripts.lib import lane_last_receipt as lr
    return lr


def _flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _norm_yield(v):
    """yfinance yields are inconsistent (0.025 fraction vs 2.5 percent). Normalize to a percent."""
    if not isinstance(v, (int, float)) or v <= 0:
        return None
    return round(v * 100, 2) if v < 1 else round(float(v), 2)


def _target_symbols(cur):
    target = _flag("--symbols")
    if target:
        return [s.strip().upper() for s in target.split(",") if s.strip()]
    cur.execute(_TARGET_SQL)
    return [r[0] for r in cur.fetchall()]


def preview() -> dict:
    """Dry run (AGENTS.md §6): READ ONLY session, SELECTs only -- no DDL, no yfinance, no write."""
    conn = _get_conn()
    _receipt_lib().enforce_readonly(conn)
    cur = conn.cursor()
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'symbol_profiles' AND column_name = ANY(%s)""",
                ([c for c, _ in _PERF_COLS],))
    have_cols = sorted(r[0] for r in cur.fetchall())
    syms = _target_symbols(cur)
    conn.rollback()
    return {"symbols": len(syms), "would_fetch": len(syms[:SYMBOL_CAP]), "first_symbols": syms[:10],
            "perf_columns_present": have_cols, "would_run_ddl": len(have_cols) < len(_PERF_COLS)}


def enrich() -> dict:
    conn = _get_conn(); cur = conn.cursor()
    for col, typ in _PERF_COLS:
        cur.execute(f"ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS {col} {typ}")
    conn.commit()

    syms = _target_symbols(cur)
    if not syms:
        print(f'{{"ok": true, "symbols": {len(syms)}, "note": "empty"}}')
        return {"symbols": 0, "attempted": 0, "updated": 0, "rejected": 0, "errors": 0, "empty": 0}

    import yfinance as yf, time as _t
    done = rejected = errors = empty = 0
    for s in syms[:SYMBOL_CAP]:
        _t.sleep(0.8)
        try:
            tk = yf.Ticker(s)
            info = tk.info or {}
            # YTD = price return year-start → latest (auto_adjust=False so it's price, dividends counted separately)
            ytd = None
            try:
                h = tk.history(period="ytd", auto_adjust=False)
                if h is not None and len(h) >= 2:
                    c0, c1 = float(h["Close"].iloc[0]), float(h["Close"].iloc[-1])
                    if c0 > 0:
                        ytd = round((c1 - c0) / c0 * 100, 2)
            except Exception:
                pass
            if ytd is None and isinstance(info.get("ytdReturn"), (int, float)):
                ytd = round(info["ytdReturn"] * 100, 2)   # fund total-return fallback
            dy = _norm_yield(info.get("yield") or info.get("dividendYield") or info.get("trailingAnnualDividendYield"))
            div = info.get("trailingAnnualDividendRate")
            div = round(float(div), 4) if isinstance(div, (int, float)) and div > 0 else None
            rcpt = upsert_profile(cur, s, {"ytd_return_pct": ytd, "dividend_yield_pct": dy, "ttm_dividend": div},
                                  source="etf_performance_enrich")
            done += rcpt.rows_written
            rejected += rcpt.rows_rejected
            if ytd is None and dy is None and div is None:
                empty += 1
        except Exception:
            errors += 1
            continue
    conn.commit()
    import json
    print(json.dumps({"ok": True, "symbols": len(syms), "updated": done, "rejected": rejected}))
    return {"symbols": len(syms), "attempted": len(syms[:SYMBOL_CAP]), "updated": done, "rejected": rejected,
            "errors": errors, "empty": empty}


def run_failed(res: dict) -> bool:
    """Honest exit: symbols attempted and every one raised or returned no value."""
    return res["attempted"] > 0 and (res["errors"] + res["empty"]) >= res["attempted"]


def main() -> int:
    lr = _receipt_lib()
    if "--dry-run" in sys.argv or "--no-fetch" in sys.argv:
        # Structural (AGENTS.md §6): enrich() -- DDL, yfinance, upserts -- is not reachable from this branch.
        plan = preview()
        lr.dry_run_report(
            LANE_ID, plan,
            would_write=([] if not plan["would_run_ddl"] else ["ALTER TABLE symbol_profiles ADD COLUMN (perf cols)"])
            + [f"symbol_profiles ytd_return_pct/dividend_yield_pct/ttm_dividend (<= {plan['would_fetch']} rows)"])
        return 0
    started = lr.now_iso()
    try:
        res = enrich()
    except Exception as exc:
        lr.write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                              script="etf_performance_enrich.py", error=f"{type(exc).__name__}: {exc}")
        raise
    failed = run_failed(res)
    rc = 1 if failed else 0
    lr.write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                          script="etf_performance_enrich.py", summary=res)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
