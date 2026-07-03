#!/usr/bin/env python3
"""holdings_llm_refresh.py — Dedicated LLM health check for portfolio holdings.

Enriches each holding with latest news, social, technical, and agent data,
then runs qwen3:14b for a consolidated health assessment.

Usage:
    .venv/bin/python3 scripts/holdings_llm_refresh.py --dry-run
    .venv/bin/python3 scripts/holdings_llm_refresh.py --run --limit 15
    .venv/bin/python3 scripts/holdings_llm_refresh.py --run --symbol LMT
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from cio_agent_contract import build_holdings_health_json_schema, parse_holdings_health_result

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

log = logging.getLogger("holdings_llm")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def get_db():
    import psycopg2, psycopg2.extras
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def get_holdings(conn):
    """Load current holdings from canonical holdings.json.

    Was `SELECT data FROM holdings` — that table's writer died 2026-04-19, so this daily cron
    spent months assessing an April portfolio (long-sold positions in, all Fidelity positions
    missing). Retired 2026-07-03; holdings.json is the source of truth.
    """
    path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    positions = data.get('positions', data.get('holdings', []))
    # Filter to individual stocks (not funds/cash)
    stocks = []
    for p in positions:
        if p.get('is_cash') or p.get('is_fund'):
            continue
        shares = p.get('shares', 0)
        if not shares or float(shares) <= 0:
            continue
        symbol = p.get('symbol', '')
        if not symbol or '-' in symbol:  # skip fund tickers like JPM-LGCG
            continue
        if len(symbol) == 9 and symbol[-1].isdigit() and any(c.isdigit() for c in symbol[:4]):
            continue  # unresolved CUSIP (e.g. 543354104) — no news/technicals to assess
        stocks.append(p)
    return stocks


def fetch_holdings_needing_refresh(conn, holdings, limit=15, symbol=None):
    """Get holdings that need LLM refresh (stale or never run)."""
    cur = conn.cursor()
    symbols = [h['symbol'] for h in holdings]
    if symbol:
        symbols = [s for s in symbols if s == symbol.upper()]

    cur.execute("""
        SELECT symbol, holdings_llm_summary, holdings_llm_at
        FROM watchlist_items
        WHERE source = 'portfolio' AND symbol = ANY(%s)
        ORDER BY
            holdings_llm_at ASC NULLS FIRST
        LIMIT %s
    """, [symbols, limit])
    rows = {r['symbol']: r for r in cur.fetchall()}

    result = []
    for h in holdings:
        sym = h['symbol']
        if sym not in [s for s in symbols]:
            continue
        wi = rows.get(sym, {})
        last_llm = wi.get('holdings_llm_at')
        # Refresh if never run or older than 12 hours
        if not last_llm or (datetime.now(timezone.utc) - last_llm.replace(tzinfo=timezone.utc if last_llm.tzinfo is None else last_llm.tzinfo)).total_seconds() > 43200:
            result.append(h)
        if len(result) >= limit:
            break
    return result


def fetch_news(conn, symbol, limit=5):
    cur = conn.cursor()
    cur.execute("""
        SELECT title, source, sentiment, published_at
        FROM news_articles
        WHERE symbol = %s AND published_at > NOW() - INTERVAL '7 days'
        ORDER BY published_at DESC LIMIT %s
    """, [symbol, limit])
    return [dict(r) for r in cur.fetchall()]


def fetch_social(conn, symbol, limit=3):
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT text, platform, sentiment, post_date
            FROM social_posts
            WHERE text ILIKE %s AND post_date > NOW() - INTERVAL '7 days'
            ORDER BY post_date DESC LIMIT %s
        """, [f'%{symbol}%', limit])
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        conn.rollback()
        return []


def fetch_agent_views(conn, symbol, limit=4):
    cur = conn.cursor()
    cur.execute("""
        SELECT agent, recommendation, confidence, summary, created_at
        FROM watchlist_agent_results
        WHERE symbol = %s
        ORDER BY created_at DESC LIMIT %s
    """, [symbol, limit])
    return [dict(r) for r in cur.fetchall()]


def fetch_technical(conn, symbol):
    cur = conn.cursor()
    cur.execute("""
        SELECT confluence_score, confluence_tier, atr, adx_regime,
               entry_quality, full_result
        FROM indicator_confluence_cache
        WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if not row:
        return {}
    result = dict(row)
    fr = result.get('full_result')
    if fr and isinstance(fr, dict):
        result['rsi'] = fr.get('rsi')
        result['rvol'] = fr.get('rvol')
    return result


def build_holdings_prompt(holding, news, social, agents, technical):
    symbol = holding['symbol']
    shares = holding.get('shares', 0)
    value = holding.get('market_value', 0)
    day_change = holding.get('day_change', 0)
    price = holding.get('price', 0)
    account = holding.get('account', '?')

    # News
    news_str = "No recent news."
    if news:
        news_str = " | ".join([f"{n['title'][:50]}({n.get('sentiment','?')})" for n in news[:3]])

    # Social
    social_str = "No social."
    if social:
        social_str = f"{len(social)} mentions. " + " | ".join([
            f"{str(s.get('text',''))[:40]}({s.get('sentiment','?')})" for s in social[:2]
        ])

    # Agent views
    agent_str = "No agent views."
    if agents:
        agent_str = " | ".join([
            f"{a['agent']}:{a.get('recommendation','?')}({a.get('confidence','?')})" for a in agents[:3]
        ])

    # Technical
    tech_str = "No technical."
    if technical:
        t = technical
        parts = []
        if t.get('rsi'): parts.append(f"RSI:{t['rsi']:.0f}")
        if t.get('atr'): parts.append(f"ATR:${t['atr']:.2f}")
        if t.get('confluence_tier'): parts.append(t['confluence_tier'])
        if t.get('adx_regime'): parts.append(f"ADX:{t['adx_regime']}")
        tech_str = " ".join(parts) if parts else tech_str

    return f"""Holdings health check. You are reviewing a CURRENT portfolio position.
{symbol} {shares}sh @${price} val=${value:,.0f} chg=${day_change:,.0f} acct={account}
Tech:{tech_str}
News:{news_str[:200]}
Social:{social_str[:150]}
Agents:{agent_str[:200]}
{build_holdings_health_json_schema()}"""


def refresh_one(conn, holding, dry_run=False):
    symbol = holding['symbol']
    if dry_run:
        log.info(f"[dry-run] Would refresh {symbol}")
        return {'symbol': symbol, 'status': 'dry_run'}

    news = fetch_news(conn, symbol)
    social = fetch_social(conn, symbol)
    agents = fetch_agent_views(conn, symbol)
    technical = fetch_technical(conn, symbol)

    prompt = build_holdings_prompt(holding, news, social, agents, technical)

    try:
        from local_llm import generate
        raw = generate(prompt, timeout=300, fallback=True, fast=False)
        if not raw:
            return {'symbol': symbol, 'status': 'empty'}

        result = parse_holdings_health_result(raw)
        if not result:
            return {'symbol': symbol, 'status': 'parse_error'}
        health = result.get('health', 'STABLE')
        action = result.get('action', 'HOLD')
        confidence = min(100, max(0, int(result.get('confidence', 50))))

        try:
            from local_llm import model_used
            model = model_used or 'local_llm'
        except Exception:
            model = 'local_llm'

        # Validate
        if health not in ('STRONG', 'STABLE', 'WATCH', 'CONCERN', 'EXIT'):
            health = 'STABLE'
        if action not in ('HOLD', 'ADD', 'TRIM', 'EXIT'):
            action = 'HOLD'

        # Save to watchlist_items
        cur = conn.cursor()
        cur.execute("""
            UPDATE watchlist_items
            SET holdings_llm_summary = %s,
                holdings_llm_health = %s,
                holdings_llm_action = %s,
                holdings_llm_confidence = %s,
                holdings_llm_model = %s,
                holdings_llm_at = NOW()
            WHERE source = 'portfolio' AND symbol = %s
        """, [json.dumps(result, default=str), health, action, confidence, model, symbol])

        if cur.rowcount == 0:
            # No watchlist_items row — insert might be needed, skip for now
            log.debug(f"  {symbol}: no watchlist_items row to update")

        conn.commit()

        log.info(f"  {symbol}: health={health} action={action} conf={confidence} model={model}")
        return {'symbol': symbol, 'status': 'refreshed', 'health': health,
                'action': action, 'confidence': confidence, 'model': model}

    except Exception as e:
        log.warning(f"  {symbol}: refresh failed — {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return {'symbol': symbol, 'status': 'error', 'error': str(e)}


def main():
    parser = argparse.ArgumentParser(description="Holdings LLM health refresh")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--symbol", type=str)
    args = parser.parse_args()

    conn = get_db()
    try:
        holdings = get_holdings(conn)
        log.info(f"Found {len(holdings)} stock holdings")

        candidates = fetch_holdings_needing_refresh(
            conn, holdings, limit=args.limit, symbol=args.symbol)
        log.info(f"{len(candidates)} need LLM refresh")

        if candidates and args.run:
            from local_llm import warmup_ollama
            log.info("Warming up Ollama...")
            warmup_ollama()

        results = []
        for h in candidates:
            r = refresh_one(conn, h, dry_run=args.dry_run)
            results.append(r)

        refreshed = sum(1 for r in results if r.get('status') == 'refreshed')
        errors = sum(1 for r in results if r.get('status') == 'error')

        print(f"\nHoldings LLM Refresh")
        print(f"{'=' * 40}")
        print(f"  Holdings:  {len(holdings)}")
        print(f"  Refreshed: {refreshed}")
        print(f"  Errors:    {errors}")
        for r in results:
            h = r.get('health', r.get('status', '?'))
            a = r.get('action', '')
            print(f"  {r['symbol']}: {h} {a}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
