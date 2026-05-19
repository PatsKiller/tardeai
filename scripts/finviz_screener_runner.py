#!/usr/bin/env python3
"""finviz_screener_runner.py — Execute Finviz screeners and discover new candidates.

Reads screener URLs from DB, fetches results, classifies new tickers,
adds promising ones to watchlist.

Usage:
    python3 scripts/finviz_screener_runner.py --run [--json]
    python3 scripts/finviz_screener_runner.py --screener dividend_growth [--json]
    python3 scripts/finviz_screener_runner.py --dry-run [--json]
"""
import json, os, re, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _get_finviz_cookie():
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("FINVIZ_COOKIE="): return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def _fetch_screener_tickers(url: str, cookie: str) -> list:
    """Fetch tickers from a Finviz screener URL. Returns list of ticker strings."""
    tickers = []
    try:
        # Convert to export URL for CSV download
        export_url = url.replace("/screener.ashx?", "/export?").replace("elite.finviz.com", "elite.finviz.com")
        if "elite.finviz.com" not in export_url:
            export_url = export_url.replace("finviz.com", "elite.finviz.com")

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Cookie": cookie,
            "Referer": "https://elite.finviz.com/screener.ashx",
        }
        req = urllib.request.Request(export_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")

            # CSV format: first column is "No.", second is "Ticker"
            lines = content.strip().split("\n")
            if len(lines) > 1:
                for line in lines[1:]:  # Skip header
                    parts = line.split(",")
                    if len(parts) >= 2:
                        ticker = parts[1].strip().strip('"')
                        if re.match(r'^[A-Z]{1,6}$', ticker):
                            tickers.append(ticker)
    except Exception as e:
        print(f"  [screener] Fetch error: {e}")

    # Fallback: try to scrape HTML if CSV fails
    if not tickers:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Cookie": cookie if cookie else "",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                # Extract tickers from screener HTML
                ticker_pattern = re.findall(r'quote\.ashx\?t=([A-Z]{1,6})', html)
                tickers = list(dict.fromkeys(ticker_pattern))  # dedup preserving order
        except Exception as e:
            print(f"  [screener] HTML fallback error: {e}")

    # SCREENER-ARCH-1: Raised cap from 50 to 500 per screener.
    # Finviz export returns all matching rows — the old [:50] was artificial truncation.
    return tickers[:500]


def run_screener(screener_id: str = None, dry_run: bool = False) -> dict:
    """Run one or all screeners. Returns discovery summary."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cookie = _get_finviz_cookie()

    if screener_id:
        cur.execute("SELECT * FROM finviz_screeners WHERE screener_id=%s AND active=TRUE", (screener_id,))
    else:
        cur.execute("SELECT * FROM finviz_screeners WHERE active=TRUE ORDER BY screener_id")
    screeners = cur.fetchall()

    # Get already classified symbols
    cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    known = set(r["symbol"] for r in cur.fetchall())

    results = []
    total_new = 0

    for s in screeners:
        sid = s["screener_id"]
        strategy = s["strategy_type"]
        url = s["finviz_url"]

        print(f"  [{sid}] Fetching {s['display_name']}...")
        tickers = _fetch_screener_tickers(url, cookie)
        new_tickers = [t for t in tickers if t not in known]

        screener_result = {
            "screener_id": sid,
            "strategy_type": strategy,
            "total_found": len(tickers),
            "new_tickers": len(new_tickers),
            "sample": new_tickers[:10],
        }
        results.append(screener_result)

        if not dry_run and new_tickers:
            for ticker in new_tickers[:10]:  # Cap new additions per screener
                # Auto-classify with the screener's strategy type
                cur.execute("""
                    INSERT INTO ticker_strategy_classifications
                        (symbol, strategy_type, asset_type, classification_source, confidence, rationale)
                    VALUES (%s, %s, 'stock', 'screener', 0.7, %s)
                    ON CONFLICT (symbol) DO NOTHING
                """, (ticker, strategy, f"Discovered by screener {sid}"))

                # Add to watchlist
                cur.execute("""
                    INSERT INTO watchlist_items (symbol, source, status, updated_at)
                    VALUES (%s, 'ai_discovered', 'active', now())
                    ON CONFLICT DO NOTHING
                """, (ticker,))

                total_new += 1
                known.add(ticker)

            # Update screener last_run
            cur.execute("UPDATE finviz_screeners SET last_run=now(), results_count=%s WHERE screener_id=%s",
                        (len(tickers), sid))

        # Intelligence event
        if not dry_run and new_tickers:
            cur.execute("""
                INSERT INTO portfolio_intelligence_events (event_type, severity, source, payload)
                VALUES ('screener_discovery', 'info', 'finviz_screener_runner.py', %s)
            """, (json.dumps({"screener": sid, "new": len(new_tickers), "sample": new_tickers[:5]}, default=str),))

        time.sleep(1)  # Rate limit between screeners

    if not dry_run:
        conn.commit()

    conn.close()

    summary = {
        "mode": "dry_run" if dry_run else "live",
        "screeners_run": len(results),
        "total_new_tickers": total_new,
        "results": results,
    }
    print(f"[screener] {'DRY RUN — ' if dry_run else ''}Ran {len(results)} screeners, discovered {total_new} new tickers")
    return summary


if __name__ == "__main__":
    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start('finviz_screener_runner')
    except Exception:
        pass

    try:
        dry = "--dry-run" in sys.argv
        sid = None
        if "--screener" in sys.argv:
            sid = sys.argv[sys.argv.index("--screener") + 1]

        result = run_screener(screener_id=sid, dry_run=dry)

        if "--json" in sys.argv:
            print(json.dumps(result, indent=2, default=str))
        else:
            for r in result.get("results", []):
                if r["new_tickers"] > 0:
                    print(f"  {r['screener_id']:>25}: {r['total_found']} found, {r['new_tickers']} NEW → {r['sample'][:5]}")

        try:
            if _run_id:
                total_new = sum(r.get('new_tickers', 0) for r in result.get('results', []))
                run_complete(_run_id, rows_processed=total_new)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        raise
