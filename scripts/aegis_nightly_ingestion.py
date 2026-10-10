"""
aegis_nightly_ingestion.py — Aegis Tier 1B: Finviz-first + Yahoo-second nightly delta ingestion.

Resolves the tracked symbol universe, then ingests market/technical/company data
using source priority: internal → Finviz → Yahoo.

All outputs marked model='aegis', stored in aegis_symbol_snapshot_nightly.
Entry point: main() (returns a dict; aegis_overnight.py calls it) / cli() for the cron lane.

Usage (cron L308, lane aegis-nightly-ingestion):
  python3 scripts/aegis_nightly_ingestion.py [--dry-run]

--dry-run (refactor wave 3, 2026-10-10) puts the db_adapter session in READ ONLY, resolves the
universe (holdings/watchlist files + stopped_out_watch/action_queue SELECTs), reads the Finviz enrichment cache
and builds every snapshot row, then prints a DRY-RUN report and returns: it never calls _db_write (no INSERT),
makes no Yahoo request (it reports how many symbols WOULD need the Yahoo fallback) and writes no receipt.

Exit codes (cli): 0 = ran (an empty universe is a finding, still 0); 1 = the run failed: Postgres unavailable
(the SELECT 1 probe fails -- every write would fail), or the universe was non-empty and EVERY snapshot write
failed. A single failed symbol write is a soft failure (logged, counted, exit 0). 2 = usage error (argparse).
A real run writes <state_root>/data/runtime/aegis-nightly-ingestion_last.json (LaneRunReceipt@v1; ok_at only on
success); a crash writes a failed receipt and re-raises.
"""
from __future__ import annotations
import json
import os
import sys
import time
import requests
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Finviz reports EVERY ETF as sector "Financial" (industry "Exchange Traded Fund"), mislabeling
# industrials/materials/bond/income funds. Correct the worst offenders at ingest so downstream
# consumers (Open Trades, Sectors, Watchlist) don't inherit a wrong sector. Canonical map mirrors
# open_trades_intelligence._ETF_SECTOR (reference data, kept in sync).
_ETF_SECTOR_FIX = {
    "XLK": "Technology", "XLF": "Financial", "XLV": "Healthcare", "XLE": "Energy",
    "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities", "XLP": "Consumer Defensive",
    "XLY": "Consumer Cyclical", "XLRE": "Real Estate", "XLC": "Communication Services",
    "BND": "Fixed Income", "AGG": "Fixed Income", "TLT": "Fixed Income", "BNDX": "Fixed Income", "LQD": "Fixed Income",
    "JEPI": "Income / Covered Call", "JEPQ": "Income / Covered Call",
    "SCHD": "Dividend Equity", "DGRO": "Dividend Equity", "VYM": "Dividend Equity", "SCHG": "Growth Equity",
    "SPY": "Broad Equity", "VOO": "Broad Equity", "VTI": "Broad Equity", "QQQ": "Broad Equity", "IWM": "Broad Equity",
    "ARKG": "Healthcare", "ARKK": "Innovation", "ARKQ": "Innovation", "ARKW": "Innovation", "ARKF": "Innovation",
}


def _corrected_sector(symbol: str, finviz_sector: str, industry: str) -> str:
    """ETF map wins; otherwise never let a bare Finviz 'Financial' on an ETF stand."""
    mapped = _ETF_SECTOR_FIX.get((symbol or "").upper())
    if mapped:
        return mapped
    if (industry or "").strip().lower() == "exchange traded fund" and (finviz_sector or "").strip() == "Financial":
        return ""  # unknown ETF — blank is honest, beats a wrong "Financial"
    return finviz_sector or ""

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

AGENT = "aegis"
RUN_ID = f"aegis-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
LANE_ID = "aegis-nightly-ingestion"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _db_write(sql, params=None):
    try:
        from db_adapter import _get_conn
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        print(f"  [aegis] DB write error: {e}")
        return False


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


def _db_available() -> bool:
    """Postgres reachable through db_adapter (``SELECT 1``). False = every read/write in this lane degrades."""
    return bool(_db_query("SELECT 1 AS ok", fetch="one"))


def _enforce_readonly_db() -> bool:
    """Dry run: put this thread's db_adapter session in READ ONLY at the server (AGENTS.md §6)."""
    try:
        from db_adapter import _get_conn
        from lib.lane_last_receipt import enforce_readonly

        conn = _get_conn()
        if conn is None:
            return False
        enforce_readonly(conn)
        return True
    except Exception as e:
        print(f"  [aegis] READ ONLY session not established: {type(e).__name__}")
        return False


# ── D1: Universe resolver ────────────────────────────────────────────────

def resolve_universe() -> list[dict]:
    """Build deduplicated tracked symbol universe with reason tags."""
    universe: dict[str, set] = {}

    # Holdings
    h = _load_json(STATE_DIR / "holdings.json") or {}
    for p in h.get("holdings", []):
        sym = p.get("symbol", "").upper()
        if sym and not p.get("is_cash") and (p.get("market_value") or 0) > 50:
            universe.setdefault(sym, set()).add("holding")

    # Watchlist
    wl = _load_json(STATE_DIR / "watchlist.json") or {}
    for sym in wl:
        universe.setdefault(sym.upper(), set()).add("watchlist")

    # Recovery watch
    recovery = _db_query("SELECT symbol FROM stopped_out_watch WHERE is_active = true") or []
    for r in recovery:
        sym = (r.get("symbol") or "").upper()
        if sym:
            universe.setdefault(sym, set()).add("recovery")

    # Approval/rebalance
    approvals = _db_query("SELECT DISTINCT symbol FROM action_queue WHERE status = 'pending' AND symbol IS NOT NULL") or []
    for r in approvals:
        sym = (r.get("symbol") or "").upper()
        if sym:
            universe.setdefault(sym, set()).add("approval")

    # Filter out mutual fund symbols (no Finviz/Yahoo data)
    fund_prefixes = ("FID-", "SP500-", "SS-", "TRP-", "JPM-", "WM-", "AB-", "VANG-")
    items = []
    for sym, reasons in sorted(universe.items()):
        if any(sym.startswith(p) for p in fund_prefixes):
            continue
        items.append({"symbol": sym, "reasons": sorted(reasons)})

    return items


# ── D2: Finviz ingestion ─────────────────────────────────────────────────

def fetch_finviz_batch(symbols: list[str]) -> dict[str, dict]:
    """Fetch from existing enrichment cache (populated by Finviz pipeline)."""
    ec = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    results = {}
    for sym in symbols:
        data = ec.get(sym) or ec.get(sym.upper())
        if isinstance(data, dict) and data:
            results[sym] = {
                "price": None,  # enrichment cache doesn't have live price
                "company": data.get("company"),
                "sector": data.get("sector"),
                "industry": data.get("industry"),
                "market_cap_b": data.get("market_cap_b"),
                "rsi": data.get("rsi"),
                "beta": data.get("beta"),
                "atr": data.get("atr"),
                "pe": data.get("pe"),
                "relvol": data.get("rvol"),
                "analyst_recom": data.get("recom"),
                "change_pct": data.get("perf_week_pct"),
                "_source": "finviz",
            }
    return results


# ── D3: Yahoo fallback ───────────────────────────────────────────────────

def _compute_rsi(closes: list, period: int = 14) -> float | None:
    if not closes or len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes)) if closes[i] is not None and closes[i - 1] is not None]
    if len(changes) < period:
        return None
    gains = [max(c, 0) for c in changes[-period:]]
    losses = [max(-c, 0) for c in changes[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)


def fetch_yahoo_single(symbol: str) -> dict:
    """Fetch from Yahoo v8 chart for price, RSI, 52-week data."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return {}
        data = resp.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        meta = result.get("meta", {})
        closes = []
        try:
            closes = [c for c in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if c is not None]
        except Exception:
            pass
        price = meta.get("regularMarketPrice")
        high52 = meta.get("fiftyTwoWeekHigh")
        low52 = meta.get("fiftyTwoWeekLow")
        return {
            "price": price,
            "prev_close": meta.get("chartPreviousClose"),
            "company": meta.get("shortName") or meta.get("longName", ""),
            "rsi": _compute_rsi(closes),
            "week52_high": high52,
            "week52_low": low52,
            "pct_from_52wk_high": round(((price - high52) / high52) * 100, 1) if price and high52 else None,
            "_source": "yahoo",
        }
    except Exception:
        return {}


def fetch_yahoo_batch(symbols: list[str], finviz_data: dict) -> dict[str, dict]:
    """Fetch Yahoo for symbols missing from Finviz or needing price enrichment."""
    results = {}
    for sym in symbols:
        fv = finviz_data.get(sym, {})
        needs_yahoo = not fv or fv.get("price") is None or fv.get("rsi") is None
        if needs_yahoo:
            yq = fetch_yahoo_single(sym)
            if yq:
                results[sym] = yq
            time.sleep(0.3)  # Rate limit
    return results


# ── D4: Merge + persist ──────────────────────────────────────────────────

def build_snapshot_rows(universe: list[dict], finviz_data: dict, yahoo_data: dict) -> list[dict]:
    """Merge sources into one aegis_symbol_snapshot_nightly row per universe symbol. Pure: writes nothing."""
    # Also get internal state (technical_snapshot, holdings)
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    h = _load_json(STATE_DIR / "holdings.json") or {}
    price_map = {}
    for p in h.get("holdings", []):
        s = p.get("symbol", "")
        if s:
            price_map[s] = {"price": p.get("price"), "market_value": p.get("market_value")}

    rows = []
    for item in universe:
        sym = item["symbol"]
        reasons = item["reasons"]
        fv = finviz_data.get(sym, {})
        yq = yahoo_data.get(sym, {})
        internal = ts.get(sym, {}) if isinstance(ts.get(sym), dict) else {}
        hp = price_map.get(sym, {})

        # Merge: Finviz wins, Yahoo fills gaps, internal fills remaining
        def pick(*sources, key):
            for s in sources:
                v = s.get(key)
                if v is not None:
                    return v
            return None

        price = pick(fv, yq, internal, hp, key="price")
        sources_used = []
        if fv:
            sources_used.append("finviz")
        if yq:
            sources_used.append("yahoo")
        if internal:
            sources_used.append("technical_snapshot")
        if hp.get("price"):
            sources_used.append("holdings")
        primary = sources_used[0] if sources_used else "none"

        merged = {
            "price": price,
            "prev_close": yq.get("prev_close"),
            "change_pct": pick(fv, yq, key="change_pct"),
            "rsi": pick(fv, yq, internal, key="rsi"),
            "sma50_pct": pick(internal, key="sma50_pct"),
            "sma200_pct": pick(internal, key="sma200_pct"),
            "beta": pick(fv, internal, key="beta"),
            "atr": pick(fv, internal, key="atr"),
            "company": pick(fv, yq, key="company") or "",
            "sector": _corrected_sector(sym, pick(fv, internal, key="sector") or "", fv.get("industry") or ""),
            "industry": fv.get("industry") or "",
            "market_cap_b": fv.get("market_cap_b"),
            "pe": fv.get("pe"),
            "relvol": fv.get("relvol"),
            "analyst_recom": fv.get("analyst_recom"),
            "week52_high": yq.get("week52_high"),
            "week52_low": yq.get("week52_low"),
            "pct_from_52wk_high": yq.get("pct_from_52wk_high"),
        }

        field_count = sum(1 for v in merged.values() if v is not None)
        confidence = min(field_count / 15, 1.0)
        rows.append({"symbol": sym, "reasons": reasons, "primary": primary, "sources_used": sources_used,
                     "merged": merged, "field_count": field_count, "confidence": confidence})
    return rows


def merge_and_persist(universe: list[dict], finviz_data: dict, yahoo_data: dict):
    """Merge sources and write to aegis_symbol_snapshot_nightly."""
    written = 0
    for row in build_snapshot_rows(universe, finviz_data, yahoo_data):
        sym, reasons, primary = row["symbol"], row["reasons"], row["primary"]
        sources_used, merged = row["sources_used"], row["merged"]
        field_count, confidence = row["field_count"], row["confidence"]
        ok = _db_write(
            """INSERT INTO aegis_symbol_snapshot_nightly
               (run_id, symbol, universe_reason, primary_source, sources_used,
                price, prev_close, change_pct, volume, relvol,
                rsi, sma50_pct, sma200_pct, beta, atr,
                week52_high, week52_low, pct_from_52wk_high,
                company, sector, industry, market_cap_b, pe, analyst_recom,
                field_count, confidence, provenance)
               VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s,%s, %s,%s,%s)
               ON CONFLICT (run_id, symbol) DO UPDATE SET
                price=EXCLUDED.price, rsi=EXCLUDED.rsi, company=EXCLUDED.company,
                sources_used=EXCLUDED.sources_used, field_count=EXCLUDED.field_count,
                confidence=EXCLUDED.confidence, observed_at=NOW()""",
            (RUN_ID, sym, reasons, primary, sources_used,
             merged["price"], merged["prev_close"], merged["change_pct"], None, merged["relvol"],
             merged["rsi"], merged["sma50_pct"], merged["sma200_pct"], merged["beta"], merged["atr"],
             merged["week52_high"], merged["week52_low"], merged["pct_from_52wk_high"],
             merged["company"], merged["sector"], merged["industry"], merged["market_cap_b"], merged["pe"], merged["analyst_recom"],
             field_count, round(confidence, 2),
             json.dumps({"run_id": RUN_ID, "agent": AGENT, "sources": sources_used}, default=str))
        )
        if ok:
            written += 1

    return written


# ── Main ─────────────────────────────────────────────────────────────────

def main(dry_run: bool = False):
    print(f"[aegis-ingestion] Nightly delta ingestion starting — {RUN_ID}" + (" (DRY RUN)" if dry_run else ""))
    readonly = _enforce_readonly_db() if dry_run else False
    if not _db_available():
        # Every snapshot write (and the recovery/approval universe reads) would fail: a failed run, not a quiet 0.
        print("  [aegis] Postgres unavailable — nothing can be persisted")
        return {"universe": 0, "finviz": 0, "yahoo": 0, "written": 0, "run_id": RUN_ID,
                "db_ok": False, "error": "db_unavailable"}

    # D1: Resolve universe
    universe = resolve_universe()
    symbols = [u["symbol"] for u in universe]
    print(f"  Universe: {len(universe)} symbols ({sum(1 for u in universe if 'holding' in u['reasons'])} holdings, {sum(1 for u in universe if 'watchlist' in u['reasons'])} watchlist, {sum(1 for u in universe if 'recovery' in u['reasons'])} recovery)")

    # D2: Finviz-first
    finviz_data = fetch_finviz_batch(symbols)
    print(f"  Finviz: {len(finviz_data)} symbols with data")

    if dry_run:
        # No Yahoo request (rate-limited external fetch) and no _db_write: report, then return.
        need_yahoo = [s for s in symbols if not finviz_data.get(s) or finviz_data[s].get("price") is None
                      or finviz_data[s].get("rsi") is None]
        rows = build_snapshot_rows(universe, finviz_data, {})
        from lib.lane_last_receipt import dry_run_report
        summary = {"universe": len(universe), "finviz": len(finviz_data), "would_fetch_yahoo": len(need_yahoo),
                   "would_write_rows": len(rows), "rows_without_price_pre_yahoo":
                   sum(1 for r in rows if r["merged"]["price"] is None), "readonly_session": readonly,
                   "run_id": RUN_ID}
        dry_run_report(LANE_ID, summary, would_write=[f"aegis_symbol_snapshot_nightly: {len(rows)} rows (run_id={RUN_ID})"])
        return {**summary, "dry_run": True, "written": 0}

    # D3: Yahoo fallback
    yahoo_data = fetch_yahoo_batch(symbols, finviz_data)
    print(f"  Yahoo: {len(yahoo_data)} symbols enriched")

    # D4: Merge + persist
    written = merge_and_persist(universe, finviz_data, yahoo_data)
    print(f"  Persisted: {written}/{len(universe)} symbol snapshots")

    print(f"[aegis-ingestion] Complete — {datetime.now().isoformat()}")
    result = {"universe": len(universe), "finviz": len(finviz_data), "yahoo": len(yahoo_data), "written": written, "run_id": RUN_ID, "db_ok": True}
    if universe and written == 0:
        result["error"] = "all_writes_failed"
    return result


def cli(argv=None) -> int:
    """Cron entry: --dry-run, honest exit code, LaneRunReceipt@v1 on real runs only (see module docstring)."""
    import argparse

    ap = argparse.ArgumentParser(description="Aegis nightly delta ingestion (cron L308)")
    ap.add_argument("--dry-run", action="store_true",
                    help="read + build rows + report; no INSERT, no Yahoo fetch, no receipt")
    args = ap.parse_args(argv)
    if args.dry_run:
        result = main(dry_run=True)
        return 1 if result.get("error") else 0

    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        result = main()
    except Exception as exc:
        write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script="aegis_nightly_ingestion.py",
                           error=f"{type(exc).__name__}: {exc}")
        raise
    failed = bool(result.get("error"))
    write_lane_receipt(LANE_ID, ok=not failed, exit_code=1 if failed else 0, started_at=started,
                       script="aegis_nightly_ingestion.py",
                       summary={k: result.get(k) for k in ("universe", "finviz", "yahoo", "written", "run_id", "error")},
                       error=result.get("error"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(cli())
