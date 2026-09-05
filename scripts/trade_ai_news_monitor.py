#!/usr/bin/env python3
"""trade_ai_news_monitor.py — Watches active GO tickers for significant news.

When significant news arrives that could change a verdict, re-runs Iris critique
on that ticker and sends a Telegram update if the verdict changes.

Runs every 30 minutes during market hours via cron.
"""
import os, sys, json, logging, time

# --- .env autoload (no hardcoded secrets) ---
import os as _os
if not _os.getenv("DB_PASSWORD"):
    try:
        from pathlib import Path as _P
        for _l in (_P(__file__).resolve().parent.parent / ".env").read_text().splitlines():
            if _l.startswith("DB_PASSWORD="): _os.environ["DB_PASSWORD"] = _l.split("=",1)[1].strip()
    except Exception: pass
from datetime import datetime, timedelta
from pathlib import Path
from calendar import timegm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('trade_ai_monitor')

# Load env
for line in (PROJECT_ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import requests
from db_adapter import _execute, _get_conn

FINNHUB_KEY = os.getenv('FINNHUB_API_KEY', '')


def is_market_hours() -> bool:
    try:
        import pytz
        et = pytz.timezone('America/New_York')
        now = datetime.now(et)
        if now.weekday() >= 5: return False
        return 8 <= now.hour <= 17
    except Exception:
        h = datetime.now().hour
        return 8 <= h <= 17


def get_active_go_tickers() -> list:
    """Get GO tickers from most recent Trade AI CSV (read via the API pattern)."""
    import csv, io, glob
    results = []
    for fp in sorted(glob.glob(str(PROJECT_ROOT / "reports" / "2026-*" / "*" / "run_summary.json")), reverse=True)[:2]:
        csv_dir = str(Path(fp).parent)
        csvs = sorted(glob.glob(csv_dir + "/trade_ai_*_watchlist.csv"))
        if csvs:
            try:
                rows = list(csv.DictReader(io.StringIO(Path(csvs[-1]).read_text())))
                for r in rows:
                    if r.get("Decision") == "GO" and r.get("Disqualified", "").lower() != "true":
                        results.append({
                            "symbol": r.get("Symbol", ""),
                            "score": int(r.get("Score", 0) or 0),
                            "decision": r.get("Decision", ""),
                            "catalyst": r.get("Catalyst", ""),
                            "critic_verdict": r.get("CriticVerdict", ""),
                        })
            except Exception:
                pass
        if results: break
    return results


def check_significant_news(symbol: str, since_minutes: int = 35) -> list:
    """Check for significant news via Finnhub + Yahoo RSS."""
    significant = []
    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)

    if FINNHUB_KEY:
        try:
            from_d = cutoff.strftime('%Y-%m-%d')
            to_d = datetime.utcnow().strftime('%Y-%m-%d')
            r = requests.get(
                f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_d}&to={to_d}&token={FINNHUB_KEY}",
                timeout=5)
            if r.status_code == 200:
                for a in r.json():
                    ts = datetime.utcfromtimestamp(a.get('datetime', 0))
                    if ts >= cutoff:
                        hl = a.get('headline', '')
                        sig_kw = ['earnings', 'revenue', 'guidance', 'fda', 'approval',
                                  'merger', 'acquisition', 'delisting', 'investigation',
                                  'ceo', 'resign', 'contract', 'recall', 'lawsuit',
                                  'dividend', 'bankrupt', 'tariff', 'suspend', symbol.lower()]
                        if any(kw in hl.lower() for kw in sig_kw):
                            significant.append({'headline': hl, 'source': 'finnhub'})
        except Exception as e:
            log.debug(f"{symbol} Finnhub: {e}")

    try:
        import feedparser
        feed = feedparser.parse(
            f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US")
        for entry in feed.entries[:3]:
            pp = entry.get('published_parsed')
            if pp:
                ts = datetime.utcfromtimestamp(timegm(pp))
                if ts >= cutoff:
                    significant.append({'headline': entry.get('title', ''), 'source': 'yahoo'})
    except Exception:
        pass

    return significant[:3]


def re_critique_ticker(symbol: str, new_headline: str) -> dict:
    """Re-run Iris critique on a single ticker with updated news."""
    from scalp_critic_agent import (
        check_danger_flags, validate_catalyst, llm_critique,
        industry_fallback, _call_ollama
    )

    # Pull actual scan data so the LLM gets real context
    price, rvol, float_m, score, company = 0, 0, 0, 0, symbol
    try:
        import psycopg2, re as _re
        conn = psycopg2.connect(host='127.0.0.1', port=5432,
            dbname='trade_ai', user='trade_ai',
            password=os.getenv('DB_PASSWORD', ''))
        cur = conn.cursor()
        cur.execute("""
            SELECT price, rvol, float_m, score, catalyst FROM trade_ai_scans
            WHERE symbol = %s ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()
        if row:
            price = float(row[0] or 0)
            rvol = float(row[1] or 0)
            float_m = float(row[2] or 0)
            score = int(row[3] or 0)
            # Extract company name from catalyst like "Fortrea Holdings Inc. (FTRE) Beats..."
            catalyst_text = row[4] or ''
            m = _re.match(r'^(.+?)\s*\(', catalyst_text)
            if m:
                company = m.group(1).strip().rstrip('.')
        conn.close()
    except Exception:
        pass

    ticker = {"symbol": symbol, "catalyst": new_headline, "decision": "GO",
              "price": price, "relative_volume": rvol, "float_m": float_m,
              "score": score}

    flags = check_danger_flags(symbol, ticker)
    cat_valid, cat_score, _ = validate_catalyst(symbol, company, new_headline)
    industry = industry_fallback(symbol) or ''

    critique = llm_critique(ticker, flags, cat_valid, cat_score, industry)

    return {
        "symbol": symbol,
        "new_headline": new_headline,
        "old_verdict": "CONFIRM",  # was GO, so was confirmed
        "new_verdict": critique.get("verdict", "CONFIRM"),
        "final_decision": critique.get("final_decision", "GO"),
        "reasoning": critique.get("reasoning", ""),
        "verdict_changed": critique.get("verdict") != "CONFIRM",
        "disqualified": critique.get("verdict") == "BLOCK",
    }


def send_verdict_change_telegram(changes: list):
    if not changes:
        return
    lines = ["🔄 *Iris Update — Verdict Changed*\n"]
    for c in changes:
        em = '🚫' if c.get('disqualified') else '⬇'
        lines.append(f"{em} *{c['symbol']}*: {c['old_verdict']} → {c['new_verdict']}")
        if c.get('new_headline'):
            lines.append(f"   📰 _{c['new_headline'][:80]}_")
        if c.get('reasoning'):
            lines.append(f"   💬 _{c['reasoning'][:80]}_")
        lines.append("")
    lines.append("_http://192.168.50.16:7777/v3/trading_")
    msg = '\n'.join(lines)
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="trade_ai_news_monitor", subject_key="ops:iris_verdict",
                retention_class="operational", severity="info",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception as e:
        # ALARM-DELIVERY-DECLARED: best-effort advisory notify after chokepoint migration; never blocks caller
        log.error(f"Telegram send failed: {e}")


def main():
    log.info("=== Trade AI News Monitor ===")
    if not is_market_hours():
        log.info("Outside market hours — skipping")
        return

    tickers = get_active_go_tickers()
    if not tickers:
        log.info("No active GO tickers")
        return

    log.info(f"Checking {len(tickers)} GO tickers for news...")
    changes = []

    for t in tickers:
        sym = t['symbol']
        news = check_significant_news(sym)
        if not news:
            time.sleep(0.2)
            continue

        log.info(f"  [{sym}] {len(news)} significant news item(s)")
        result = re_critique_ticker(sym, news[0]['headline'])

        if result.get('verdict_changed'):
            log.info(f"  [{sym}] VERDICT CHANGED: {result['old_verdict']} → {result['new_verdict']}")
            changes.append(result)
        else:
            log.info(f"  [{sym}] verdict stable")
        time.sleep(0.5)

    # Broadcast verdict changes to live WS feed — non-fatal
    if changes:
        try:
            from scalp_ws_client import broadcast_scalp_update
            for c in changes:
                broadcast_scalp_update({
                    "symbol": c.get("symbol", ""),
                    "grade": "",
                    "score": 0,
                    "decision": c.get("final_decision", "GO"),
                    "change_percent": "",
                    "critic_verdict": c.get("new_verdict", ""),
                    "catalyst_verified": not c.get("disqualified", False),
                    "source": "news_monitor",
                    "verdict_changed": True,
                })
        except Exception as e:
            log.warning("WS broadcast from news monitor failed (non-fatal): %s", e)

        send_verdict_change_telegram(changes)
        log.info(f"{len(changes)} verdict change(s) — Telegram sent")
    else:
        log.info("All verdicts stable")


if __name__ == '__main__':
    main()
