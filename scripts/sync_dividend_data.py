#!/usr/bin/env python3
"""sync_dividend_data.py — Sync dividend data from yfinance (declared provider) to ticker_dividend_data.

Replaces seed-only ticker_dividend_data with real API data.

Usage:
    python3 scripts/sync_dividend_data.py [--json] [--dry-run]

Lane ``sync-dividend-data`` (cron L216). ``--dry-run`` prints an offline capped universe/fetch plan
and returns before opening a DB, reading environment files or calling yfinance; counts are unmeasured
and no receipt is written. The separate preview() helper still reads the universe under READ ONLY.
A real run writes ``<state_root>/data/runtime/sync-dividend-data_last.json`` (LaneRunReceipt@v1;
``ok_at`` only on success).

Universe (operator decision 2026-10-26, "widen the dividend refresh to cover everything you hold or watch"):
every symbol held in any account (position store, non-cash, shares > 0), the operator's Watch list
(data_broker.watch_domains.membership_operator) and the prospectus universe come FIRST, at most
PRIORITY_CAP of them; then up to SYMBOL_CAP of the active strategy-classified symbols, stalest first (it was the
same alphabetical 30 every day). Provider pacing: FETCH_PAUSE_S between yfinance calls and a RUN_BUDGET_S wall
clock inside the premarket step's 5-minute timeout -- the priority symbols are fetched first, so a budget stop
drops rotation symbols, never held ones.

Retired-provider rows (config/data_source_authority.json dividends.retired; lib/dividend_source_trust): a
refresh REPLACES their values instead of COALESCE-carrying them forward under the yfinance label, and clears the
superseded marker (migrations/2026_10_26_ticker_dividend_superseded.sql) when that column exists. Rows are
never deleted. yfinance info lacks ``dividendRate`` for many funds: ``trailingAnnualDividendRate`` is the
fallback (annual $/share paid over the trailing year).

Exit codes: 0 = ran (symbols without a dividend, or zero symbols, are findings, not failures);
1 = the run failed: crash / DB unavailable (failed receipt, exception re-raised), or every symbol's
yfinance fetch raised (nothing could be fetched when work existed); 2 = usage error.
"""
import json, os, sys, time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LANE_ID = "sync-dividend-data"
SYMBOL_CAP = 30  # rate limit: rotation (strategy-classified) symbols per run
PRIORITY_CAP = 200  # held + Watch + prospectus symbols per run (all of them in practice)
FETCH_PAUSE_S = 0.5  # pause between yfinance calls (provider pacing)
RUN_BUDGET_S = 240  # stop fetching before the premarket step's 5-minute timeout
_SKIP_PREFIXES = ["FID-", "SP500-", "SS-", "TRP-", "WM-", "AB-", "JPM-", "VANG-"]
#: yfinance fetches that raised during the last sync() in this process (read by main() for the exit code)
_FETCH_ERRORS: list = []


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:  # imported as scripts.sync_dividend_data
        from scripts.lib import lane_last_receipt as lr
    return lr


def _get_conn():
    import psycopg2
    if str(PROJECT_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from lib.env_bootstrap import load_env
    load_env(names=("DB_PASSWORD",))
    pw = os.environ.get("DB_PASSWORD", "")
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _fetch_yf_dividend(symbol: str) -> dict:
    """Dividend facts from yfinance (declared provider for the dividends domain).

    FMP retired 2026-09-13 (paid-only; 403/429 since July). yfinance `info` carries
    dividendRate (annual $/share), exDividendDate (epoch) and the last price.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        result = {}
        rate = info.get("dividendRate")
        if not rate or float(rate) <= 0:  # funds: yfinance often omits dividendRate (audit A2 follow-up)
            rate = info.get("trailingAnnualDividendRate")
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if rate and float(rate) > 0:
            result["annual_dividend_per_share"] = round(float(rate), 4)
            if price and float(price) > 0:
                result["dividend_yield_pct"] = round(float(rate) / float(price) * 100, 2)
        exd = info.get("exDividendDate")
        if exd:
            result["ex_div_date"] = datetime.utcfromtimestamp(int(exd)).date().isoformat()
        beta = info.get("beta")
        if beta:
            result["_beta"] = float(beta)
        return result
    except Exception as exc:
        _FETCH_ERRORS.append(f"{symbol}: {type(exc).__name__}")
        return {}


def _universe(cur) -> list:
    """Active strategy-classified symbols, stalest dividend row first, Fidelity proprietary codes removed."""
    cur.execute("SELECT c.symbol FROM ticker_strategy_classifications c"
                " LEFT JOIN ticker_dividend_data d ON d.symbol = c.symbol"
                " WHERE c.active=TRUE ORDER BY d.last_updated ASC NULLS FIRST, c.symbol")
    symbols = [r["symbol"] for r in cur.fetchall()]
    # Filter to real tickers (skip Fidelity proprietary)
    return [s for s in symbols if not any(s.startswith(p) for p in _SKIP_PREFIXES)]


def _lib(name: str):
    import importlib
    if str(PROJECT_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        return importlib.import_module(f"lib.{name}")
    except ImportError:
        return importlib.import_module(f"scripts.lib.{name}")


def _norm(sym) -> str:
    s = str(sym or "").strip().upper()
    if not s or len(s) > 12 or any(s.startswith(p) for p in _SKIP_PREFIXES):
        return ""
    return s if all(ch.isalnum() or ch in ".-" for ch in s) else ""


def _held(state_root: Path) -> list:
    pp = _lib("portfolio_positions")
    doc = pp.load_store(pp.store_path(state_root)) or {}
    out = []
    for r in doc.get("holdings") or []:
        if not isinstance(r, dict) or pp.is_cash(r):
            continue
        try:
            qty = float(r.get("shares", r.get("quantity")) or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty > 0:
            out.append(r.get("symbol"))
    return out


def _watch(cur) -> list:
    def q(sql, params=None):
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        except Exception:
            # A failed SELECT aborts the transaction; nothing is written before the universe is read, so a
            # rollback loses nothing and keeps the later upserts possible.
            conn = getattr(cur, "connection", None)
            if conn is not None:
                conn.rollback()
            raise
    return list((_lib("data_broker.watch_domains").membership_operator(q).get("names") or {}).keys())


def _prospectus(state_root: Path) -> list:
    pst = _lib("prospectus.store")
    try:
        cfg = json.loads((PROJECT_ROOT / "config" / "prospectus.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    return [r.get("symbol") for r in pst.read_universe(pst.base_dir(state_root, cfg))]


def priority_universe(cur, state_root: Path = None, conn=None) -> dict:
    """{symbols: [...held, then Watch, then prospectus, de-duplicated], sources: {name: {status, count}}}.

    Each source fails independently (recorded, never fatal). A failed Watch read rolls the transaction back;
    nothing has been written at that point."""
    root = Path(state_root) if state_root else _receipt_lib()._state_root()
    seen, symbols, sources = set(), [], {}
    for name, fn in (("held", lambda: _held(root)), ("watch", lambda: _watch(cur)),
                     ("prospectus", lambda: _prospectus(root))):
        try:
            got = [s for s in (_norm(x) for x in fn() or []) if s]
            sources[name] = {"status": "ok", "count": len(set(got))}
        except Exception as exc:  # noqa: BLE001 - one missing source must not stop the others
            got = []
            sources[name] = {"status": "error", "error": type(exc).__name__}
            if name == "watch" and conn is not None:
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
        for s in got:
            if s not in seen:
                seen.add(s)
                symbols.append(s)
    return {"symbols": symbols, "sources": sources}


def plan_batch(priority: list, rotation: list) -> list:
    """Priority symbols first (<= PRIORITY_CAP), then <= SYMBOL_CAP rotation symbols not already included."""
    head = list(dict.fromkeys(priority))[:PRIORITY_CAP]
    taken = set(head)
    tail = [s for s in dict.fromkeys(rotation) if s not in taken][:SYMBOL_CAP]
    return head + tail


def _has_superseded_column(cur) -> bool:
    cur.execute("SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'ticker_dividend_data' AND column_name = 'superseded_at'")
    return bool(cur.fetchall())


def preview(symbols: list = None) -> dict:
    """Dry run (AGENTS.md §6): READ ONLY session, universe SELECTs only; no yfinance call, no INSERT."""
    import psycopg2.extras
    conn = _get_conn()
    pri = {"symbols": [], "sources": {}}
    try:
        _receipt_lib().enforce_readonly(conn)
        if not symbols:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            rotation = _universe(cur)
            pri = priority_universe(cur, conn=conn)
            symbols = plan_batch(pri["symbols"], rotation)
            return {"symbols_total": len(set(rotation) | set(pri["symbols"])), "would_check": len(symbols),
                    "priority": len(pri["symbols"][:PRIORITY_CAP]), "priority_sources": pri["sources"],
                    "symbols": symbols}
    finally:
        conn.close()
    batch = symbols[:SYMBOL_CAP]
    return {"symbols_total": len(symbols), "would_check": len(batch), "symbols": batch}


_UPSERT = """
    INSERT INTO ticker_dividend_data (symbol, dividend_yield_pct, annual_dividend_per_share, ex_div_date, source, last_updated, updated_at)
    VALUES (%s, %s, %s, %s, 'yfinance', now(), now())
    ON CONFLICT (symbol) DO UPDATE SET
        dividend_yield_pct = CASE WHEN {retired} THEN EXCLUDED.dividend_yield_pct
            ELSE COALESCE(EXCLUDED.dividend_yield_pct, ticker_dividend_data.dividend_yield_pct) END,
        annual_dividend_per_share = CASE WHEN {retired} THEN EXCLUDED.annual_dividend_per_share
            ELSE COALESCE(EXCLUDED.annual_dividend_per_share, ticker_dividend_data.annual_dividend_per_share) END,
        ex_div_date = CASE WHEN {retired} THEN EXCLUDED.ex_div_date
            ELSE COALESCE(EXCLUDED.ex_div_date, ticker_dividend_data.ex_div_date) END,
        source = 'yfinance', last_updated = now(), updated_at = now(){clear}
"""


def _upsert_sql(clear_superseded: bool) -> str:
    trust = _lib("dividend_source_trust")
    retired = "NOT " + trust.trusted_row_sql("ticker_dividend_data.source")
    clear = ",\n        superseded_at = NULL, superseded_reason = NULL" if clear_superseded else ""
    return _UPSERT.format(retired=retired, clear=clear)


def sync(symbols: list = None) -> dict:
    import psycopg2.extras
    _FETCH_ERRORS.clear()
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    pri = {"symbols": [], "sources": {}}
    if symbols:
        batch = list(symbols)[:SYMBOL_CAP]
    else:
        rotation = _universe(cur)
        pri = priority_universe(cur, conn=conn)
        batch = plan_batch(pri["symbols"], rotation)
    sql = _upsert_sql(_has_superseded_column(cur))

    updated, checked, started = 0, 0, time.monotonic()
    for i, sym in enumerate(batch):  # Rate limit: priority first, then the capped rotation
        if time.monotonic() - started > RUN_BUDGET_S:
            break
        if i:
            time.sleep(FETCH_PAUSE_S)
        checked += 1
        data = _fetch_yf_dividend(sym)
        if data:
            # Remove internal fields
            clean = {k: v for k, v in data.items() if not k.startswith("_") and v is not None}
            if clean:
                yld = clean.get("dividend_yield_pct")
                annual = clean.get("annual_dividend_per_share")
                exd = clean.get("ex_div_date")
                cur.execute(sql, (sym, yld, annual, exd))
                updated += 1
                print(f"  {sym}: yield={yld}% annual_div={annual}")

    conn.commit()
    conn.close()

    n_pri = len(pri["symbols"][:PRIORITY_CAP])
    result = {"symbols_checked": checked, "updated": updated, "fetch_errors": len(_FETCH_ERRORS),
              "priority_planned": n_pri, "priority_checked": min(checked, n_pri),
              "priority_sources": pri["sources"], "planned": len(batch),
              "budget_stopped": checked < len(batch)}
    print(f"[dividend-sync] Updated {updated} of {checked} symbols from yfinance "
          f"(priority {min(checked, n_pri)}/{n_pri}, planned {len(batch)})")
    return result


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Sync yfinance dividend data into ticker_dividend_data.", allow_abbrev=False)
    ap.add_argument("--json", action="store_true", help="also print the result as JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline universe/fetch plan; no DB, fetch, write or receipt")
    a = ap.parse_args(argv)
    if a.dry_run:
        # Structural (AGENTS.md §6): sync() -- yfinance + INSERT -- is not reachable from this branch.
        plan = {"symbol_cap": SYMBOL_CAP, "priority_cap": PRIORITY_CAP, "fetch_pause_s": FETCH_PAUSE_S,
                "run_budget_s": RUN_BUDGET_S,
                "universe": "held + Watch + prospectus first, then active ticker_strategy_classifications (stalest first)",
                "would_check": None, "measured": False, "provider": "yfinance dividendRate"}
        if a.json:
            print(json.dumps(plan, sort_keys=True))
        print(f"DRY-RUN {LANE_ID}: would read held, Watch and prospectus symbols (<= {PRIORITY_CAP}) then active "
              f"strategy symbols stalest first (<= {SYMBOL_CAP}), skip proprietary codes, fetch yfinance dividends "
              f"{FETCH_PAUSE_S}s apart within {RUN_BUDGET_S}s and upsert ticker_dividend_data; counts unmeasured")
        return 0
    started = _receipt_lib().now_iso()
    try:
        r = sync()
    except Exception as exc:
        _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                          script="sync_dividend_data.py", error=f"{type(exc).__name__}: {exc}")
        raise
    if a.json:
        print(json.dumps(r, indent=2, default=str))
    failed = r["symbols_checked"] > 0 and r["fetch_errors"] >= r["symbols_checked"]
    rc = 1 if failed else 0
    _receipt_lib().write_lane_receipt(LANE_ID, ok=not failed, exit_code=rc, started_at=started,
                                      script="sync_dividend_data.py", summary=r)
    return rc


if __name__ == "__main__":
    sys.exit(main())
