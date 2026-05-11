#!/usr/bin/env python3
"""market_regime_collector.py — Collect regime indicators from available local sources.

Usage:
    .venv/bin/python scripts/market_regime_collector.py --dry-run --json
    .venv/bin/python scripts/market_regime_collector.py --apply --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="IND_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()

INDEX_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU"]


def collect_scan_based_indicators(conn, snapshot_id):
    """Use trade_ai_scans as a breadth/activity proxy."""
    cur = conn.cursor()
    indicators = []

    # Scan breadth: how many symbols scanned recently
    cur.execute("SELECT COUNT(DISTINCT symbol), COUNT(*) FROM trade_ai_scans WHERE scanned_at > now() - interval '24 hours'")
    row = cur.fetchone()
    symbols_24h, scans_24h = row[0], row[1]
    indicators.append({
        "indicator_id": _uid(), "snapshot_id": snapshot_id,
        "indicator_key": "scan_breadth_24h", "indicator_group": "breadth",
        "value": symbols_24h, "signal": "broad" if symbols_24h > 50 else ("narrow" if symbols_24h > 10 else "missing"),
        "freshness_seconds": 86400, "source_key": "trade_ai_scans",
    })

    # Score distribution as momentum proxy
    cur.execute("SELECT AVG(score), STDDEV(score) FROM trade_ai_scans WHERE scanned_at > now() - interval '24 hours' AND score IS NOT NULL")
    row = cur.fetchone()
    avg_score = _f(row[0]) if row[0] else None
    if avg_score:
        signal = "bullish" if avg_score > 60 else ("bearish" if avg_score < 40 else "neutral")
        indicators.append({
            "indicator_id": _uid(), "snapshot_id": snapshot_id,
            "indicator_key": "scan_score_avg", "indicator_group": "index",
            "value": round(avg_score, 1), "signal": signal,
            "source_key": "trade_ai_scans",
        })

    # Gap distribution as volatility proxy
    cur.execute("SELECT AVG(ABS(gap_pct)), STDDEV(gap_pct) FROM trade_ai_scans WHERE scanned_at > now() - interval '24 hours' AND gap_pct IS NOT NULL")
    row = cur.fetchone()
    avg_gap = _f(row[0]) if row[0] else None
    if avg_gap:
        signal = "high_vol" if avg_gap > 3.0 else ("low_vol" if avg_gap < 1.0 else "neutral")
        indicators.append({
            "indicator_id": _uid(), "snapshot_id": snapshot_id,
            "indicator_key": "gap_volatility_proxy", "indicator_group": "volatility",
            "value": round(avg_gap, 2), "signal": signal,
            "source_key": "trade_ai_scans",
        })

    # Source health as data quality indicator
    cur.execute("SELECT source_key, status, degraded FROM data_source_health WHERE source_key='finviz'")
    row = cur.fetchone()
    if row:
        indicators.append({
            "indicator_id": _uid(), "snapshot_id": snapshot_id,
            "indicator_key": "finviz_health", "indicator_group": "source_health",
            "value_text": row[1], "signal": "risk_on" if row[1] == "healthy" else "risk_off",
            "source_key": "data_source_health",
        })

    # News sentiment proxy
    cur.execute("SELECT AVG(relevance_score) FROM news_articles WHERE created_at > now() - interval '24 hours' AND relevance_score IS NOT NULL")
    row = cur.fetchone()
    if row[0]:
        indicators.append({
            "indicator_id": _uid(), "snapshot_id": snapshot_id,
            "indicator_key": "news_sentiment_proxy", "indicator_group": "news",
            "value": round(_f(row[0]), 2), "signal": "neutral",
            "source_key": "news_articles",
        })

    return indicators


def collect_vix(snapshot_id):
    """Fetch VIX from Yahoo Finance chart API."""
    try:
        import urllib.request
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        vix = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
        signal = "extreme" if vix > 30 else ("high" if vix > 20 else ("normal" if vix > 14 else "low"))
        return {
            "indicator_id": _uid(), "snapshot_id": snapshot_id,
            "indicator_key": "vix_close", "indicator_group": "volatility",
            "value": round(vix, 2), "signal": signal,
            "source_key": "yahoo_finance",
        }
    except Exception:
        return None


def collect_market_session(snapshot_id):
    """Collect market session indicator."""
    from market_session import current_market_session
    session = current_market_session()
    return {
        "indicator_id": _uid(), "snapshot_id": snapshot_id,
        "indicator_key": "market_session", "indicator_group": "index",
        "value_text": session, "signal": "risk_on" if session == "regular" else "neutral",
        "source_key": "market_session",
    }


def save_indicators(conn, indicators, dry_run=True):
    if dry_run: return
    cur = conn.cursor()
    for ind in indicators:
        cur.execute("""
            INSERT INTO market_regime_indicators
                (indicator_id, snapshot_id, indicator_key, indicator_group,
                 value, value_text, signal, weight, freshness_seconds, source_key, payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (indicator_id) DO NOTHING
        """, [ind["indicator_id"], ind.get("snapshot_id"), ind["indicator_key"],
              ind.get("indicator_group"), ind.get("value"), ind.get("value_text"),
              ind.get("signal"), ind.get("weight", 1.0), ind.get("freshness_seconds"),
              ind.get("source_key"), json.dumps(ind.get("payload", {}), default=str)])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Market Regime Collector")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--symbols")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    snapshot_id = _uid("SNAP_")
    conn = _get_conn()
    try:
        indicators = collect_scan_based_indicators(conn, snapshot_id)
        indicators.append(collect_market_session(snapshot_id))
        vix_ind = collect_vix(snapshot_id)
        if vix_ind:
            indicators.append(vix_ind)

        if not dry_run:
            save_indicators(conn, indicators)

        missing = []
        for sym in INDEX_SYMBOLS:
            missing.append(f"no_direct_quote_{sym}")

        out = {
            "mode": "dry_run" if dry_run else "applied",
            "snapshot_id": snapshot_id,
            "indicators_collected": len(indicators),
            "missing_data": missing,
            "stale_data": len(indicators) < 3,
        }
        if args.json:
            out["indicators"] = [{k: v for k, v in i.items() if k != "payload"} for i in indicators]
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Collected {out['indicators_collected']} indicators ({out['mode']})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
