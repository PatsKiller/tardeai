"""
aegis_nightly_ingestion.py — Aegis Tier 1B: Finviz-first + Yahoo-second nightly delta ingestion.

Resolves the tracked symbol universe, then ingests market/technical/company data
using source priority: internal → Finviz → Yahoo.

All outputs marked model='aegis', stored in aegis_symbol_snapshot_nightly.
Entry point: main()
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

def merge_and_persist(universe: list[dict], finviz_data: dict, yahoo_data: dict):
    """Merge sources and write to aegis_symbol_snapshot_nightly."""
    # Also get internal state (technical_snapshot, holdings)
    ts = _load_json(STATE_DIR / "technical_snapshot.json") or {}
    h = _load_json(STATE_DIR / "holdings.json") or {}
    price_map = {}
    for p in h.get("holdings", []):
        s = p.get("symbol", "")
        if s:
            price_map[s] = {"price": p.get("price"), "market_value": p.get("market_value")}

    written = 0
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
            "sector": pick(fv, internal, key="sector") or "",
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

def main():
    print(f"[aegis-ingestion] Nightly delta ingestion starting — {RUN_ID}")

    # D1: Resolve universe
    universe = resolve_universe()
    symbols = [u["symbol"] for u in universe]
    print(f"  Universe: {len(universe)} symbols ({sum(1 for u in universe if 'holding' in u['reasons'])} holdings, {sum(1 for u in universe if 'watchlist' in u['reasons'])} watchlist, {sum(1 for u in universe if 'recovery' in u['reasons'])} recovery)")

    # D2: Finviz-first
    finviz_data = fetch_finviz_batch(symbols)
    print(f"  Finviz: {len(finviz_data)} symbols with data")

    # D3: Yahoo fallback
    yahoo_data = fetch_yahoo_batch(symbols, finviz_data)
    print(f"  Yahoo: {len(yahoo_data)} symbols enriched")

    # D4: Merge + persist
    written = merge_and_persist(universe, finviz_data, yahoo_data)
    print(f"  Persisted: {written}/{len(universe)} symbol snapshots")

    print(f"[aegis-ingestion] Complete — {datetime.now().isoformat()}")
    return {"universe": len(universe), "finviz": len(finviz_data), "yahoo": len(yahoo_data), "written": written, "run_id": RUN_ID}


if __name__ == "__main__":
    main()
