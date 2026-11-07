#!/usr/bin/env python3
"""holdings_llm_refresh.py — Dedicated LLM health check for portfolio holdings.

Enriches each holding with latest news, social, technical, and agent data,
then uses a governed cloud lane for a consolidated health assessment.

Usage:
    .venv/bin/python3 scripts/holdings_llm_refresh.py --dry-run
    .venv/bin/python3 scripts/holdings_llm_refresh.py --run --limit 15
    .venv/bin/python3 scripts/holdings_llm_refresh.py --run --symbol LMT

Refactor wave 2 (cron -> n8n, 2026-10-10; cron:L383 --run --limit 50):
- ``--dry-run`` runs on a READ ONLY session and returns from ``refresh_one`` before any fetch,
  governed-cloud (paid) call, UPDATE or DecisionPayload emit; it reports the symbols it would refresh.
- holdings.json is read from the SERVED state dir (persistent root first), not the checkout copy.
- A real ``--run`` writes data/runtime/holdings_llm_refresh_last.json (LaneRunReceipt@v1 plus the
  @v2 output block, ok_at only on success) and exits 1 when it had candidates and refreshed none
  (lane dead). Per-symbol parse_error/empty results are findings, counted in the receipt, not a
  failed run.
- A run that finds nothing due says WHY (``empty_reason``, 2026-11-07). ``nothing_due`` — the reviewed
  idle token — only when every stock holding was assessed inside the 12 h window; an empty portfolio
  or a ``--symbol`` that is not held gets a sentence, so the EMPTY grade names the real cause.

Governed bridge (2026-10-15, n8n llm lane batch 1): with TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from
the allowlist ``llm_route`` of lane holdings-llm-refresh) ``generate_cloud`` makes ONE governed-bridge request as
process ``holdings_llm_refresh`` and never imports llm_lane; a refusal is a per-symbol ``error`` (no UPDATE, no
payload). The cron line is unchanged.
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

try:
    from lib.day_change_display import format_day_change as _format_day_change
except ImportError:  # pragma: no cover - imported as scripts.<module>
    from scripts.lib.day_change_display import format_day_change as _format_day_change

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

# Schema JSON + G1–G10 preamble does not fit the default 300-token cap
# (2026-08-21: 7/26 parse_error, gemma3:4b num_predict=300). Process-local only.
os.environ.setdefault("LOCAL_LLM_NUM_PREDICT", "900")

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


def _holdings_path() -> Path:
    """The SERVED holdings.json (persistent root first), not a checkout copy (AGENTS.md §9.4)."""
    try:
        from lib.persistent_state_root import portfolio_state_write_targets

        return portfolio_state_write_targets(PROJECT_ROOT)[0] / "holdings.json"
    except Exception:  # noqa: BLE001 -- resolution layer unavailable: the code tree (old behaviour)
        return PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"


def get_holdings(conn):
    """Load current holdings from canonical holdings.json.

    Was `SELECT data FROM holdings` — that table's writer died 2026-04-19, so this daily cron
    spent months assessing an April portfolio (long-sold positions in, all Fidelity positions
    missing). Retired 2026-07-03; holdings.json is the source of truth.
    """
    path = _holdings_path()
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


#: A holding assessed within this window is not due again.
FRESH_WINDOW_S = 43200  # 12 hours


def _age_s(last_llm) -> float | None:
    """Seconds since the last assessment, or None when the holding has never been assessed."""
    if not last_llm:
        return None
    tz = last_llm.tzinfo or timezone.utc
    return (datetime.now(timezone.utc) - last_llm.replace(tzinfo=tz)).total_seconds()


def select_holdings(conn, holdings, limit=15, symbol=None):
    """(candidates, stats): the holdings due for an LLM refresh, and why the rest are not.

    ``stats`` is what lets the receipt say WHY a run produced nothing (2026-11-07): a bare
    ``candidates: 0`` graded EMPTY — "the receipt does not say why" (lib/run_quality.py). The counts are taken
    over every holding considered, not over the (capped) candidate list, so they describe the portfolio.
    """
    cur = conn.cursor()
    considered = [h for h in holdings if not symbol or h["symbol"] == symbol.upper()]
    symbols = [h["symbol"] for h in considered]

    cur.execute("""
        SELECT symbol, holdings_llm_summary, holdings_llm_at
        FROM watchlist_items
        WHERE source = 'portfolio' AND symbol = ANY(%s)
        ORDER BY
            holdings_llm_at ASC NULLS FIRST
        LIMIT %s
    """, [symbols, limit])
    rows = {r["symbol"]: r for r in cur.fetchall()}

    stats = {"considered": len(considered), "fresh": 0, "stale": 0, "no_watchlist_row": 0,
             "cap_reached": False, "symbol": symbol.upper() if symbol else None}
    stale = []
    for h in considered:
        wi = rows.get(h["symbol"])
        age = _age_s((wi or {}).get("holdings_llm_at"))
        if wi is None:
            stats["no_watchlist_row"] += 1
        if age is not None and age <= FRESH_WINDOW_S:
            stats["fresh"] += 1
        else:
            stats["stale"] += 1
            stale.append(h)
    candidates = stale[:limit]
    stats["cap_reached"] = len(stale) > limit
    return candidates, stats


def fetch_holdings_needing_refresh(conn, holdings, limit=15, symbol=None):
    """Get holdings that need LLM refresh (stale or never run). Thin wrapper over select_holdings."""
    return select_holdings(conn, holdings, limit=limit, symbol=symbol)[0]


def empty_reason(holdings, stats) -> str | None:
    """Why this run is about to produce nothing — or None when it has candidates to refresh.

    ``nothing_due`` is the reviewed idle token (config/run_quality_idle_reasons.json): it is returned ONLY
    when every considered holding really was assessed inside the 12 h window, so the run is a correct idle.
    Every other zero is a sentence, which keeps the EMPTY grade and names the cause instead of hiding it:
    an empty portfolio is a data problem, not "nothing due".
    """
    if stats.get("considered", 0) == 0:
        if stats.get("symbol"):
            return (f"requested symbol {stats['symbol']} is not among the {len(holdings)} stock "
                    f"holding(s) holdings.json lists")
        return ("holdings.json lists no stock holding to assess: "
                f"{len(holdings)} row(s) after the cash/fund/unresolved-CUSIP/zero-share filter")
    if stats.get("stale", 0) == 0:
        return "nothing_due"
    return None


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
    day_change = _format_day_change(holding.get('day_change'))
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
{symbol} {shares}sh @${price} val=${value:,.0f} chg={day_change} acct={account}
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
        from lib.governed_cloud_generation import generate_cloud
        raw, lane = generate_cloud(
            prompt, process_id="holdings_llm_refresh",
            task_summary=f"holdings health {symbol}", timeout=300,
        )
        if not raw:
            return {'symbol': symbol, 'status': 'empty'}

        result = parse_holdings_health_result(raw)
        if not result:
            log.warning(f"  {symbol}: parse_error raw[:400]={raw[:400]!r}")
            return {'symbol': symbol, 'status': 'parse_error'}
        health = result.get('health', 'STABLE')
        action = result.get('action', 'HOLD')
        confidence = min(100, max(0, int(result.get('confidence', 50))))

        # lane "bridge": the n8n path (allowlist llm_route -> lib.governed_cloud_generation's governed-bridge branch,
        # process holdings_llm_refresh); the bridge, not this script, chose the provider.
        model = "governed-bridge" if lane == "bridge" else "grok-3-mini" if lane == "grok" else "gpt-5.4"

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
        out = {'symbol': symbol, 'status': 'refreshed', 'health': health,
                'action': action, 'confidence': confidence, 'model': model}
        try:
            from lib.agent_decision_payload import emit_holdings_health_payload
            emit_holdings_health_payload(out)
        except Exception:
            try:
                from scripts.lib.agent_decision_payload import emit_holdings_health_payload
                emit_holdings_health_payload(out)
            except Exception:
                pass
        return out

    except Exception as e:
        log.warning(f"  {symbol}: refresh failed — {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return {'symbol': symbol, 'status': 'error', 'error': str(e)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Holdings LLM health refresh")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--symbol", type=str)
    args = parser.parse_args(argv)

    from lib.lane_last_receipt import enforce_readonly, now_iso, write_lane_receipt

    started_at = now_iso()
    conn = get_db()
    if args.dry_run:
        enforce_readonly(conn)  # the server refuses any write (AGENTS.md §6)
    try:
        holdings = get_holdings(conn)
        log.info(f"Found {len(holdings)} stock holdings")

        candidates, stats = select_holdings(
            conn, holdings, limit=args.limit, symbol=args.symbol)
        reason = empty_reason(holdings, stats) if not candidates else None
        log.info(f"{len(candidates)} need LLM refresh "
                 f"({stats['fresh']} of {stats['considered']} assessed within 12 h)")

        results = []
        for h in candidates:
            r = refresh_one(conn, h, dry_run=args.dry_run)
            results.append(r)

        refreshed = sum(1 for r in results if r.get('status') == 'refreshed')
        errors = sum(1 for r in results if r.get('status') in ('error', 'parse_error', 'empty'))

        print("\nHoldings LLM Refresh")
        print(f"{'=' * 40}")
        print(f"  Holdings:  {len(holdings)}")
        print(f"  Refreshed: {refreshed}")
        print(f"  Errors:    {errors}")
        for r in results:
            h = r.get('health', r.get('status', '?'))
            a = r.get('action', '')
            print(f"  {r['symbol']}: {h} {a}")
        if args.dry_run:
            print(f"  [dry-run] would call the governed cloud lane for {len(candidates)} symbol(s) and "
                  f"UPDATE watchlist_items for each; nothing written")
            if reason:
                print(f"  [dry-run] nothing due — the receipt would state empty_reason={reason!r}")
            return 0
        statuses: dict = {}
        for r in results:
            statuses[r.get("status", "?")] = statuses.get(r.get("status", "?"), 0) + 1
        ok = not candidates or refreshed > 0
        # write_lane_receipt, not its W3 alias write_receipt(): only the former accepts the @v2 output kwargs.
        write_lane_receipt("holdings_llm_refresh", script="holdings_llm_refresh", ok=ok,
                           started_at=started_at,
                           summary={"holdings": len(holdings), "candidates": len(candidates),
                                    "refreshed": refreshed, "errors": errors, "statuses": statuses},
                           error=None if ok else f"0/{len(candidates)} refreshed",
                           # LaneRunReceipt@v2 output: the counts the quality grader reads, and — when nothing was
                           # produced — the reason. Before this, a zero-candidate run said only "candidates: 0" and
                           # lib/run_quality.py could report nothing better than "the receipt does not say why".
                           output={"produced_count": refreshed, "attempted_count": len(candidates),
                                   "skipped_reasons": {"fresh_within_window": stats["fresh"],
                                                       "no_watchlist_row": stats["no_watchlist_row"]},
                                   "empty_reason": reason})
        return 0 if ok else 1
    except Exception as exc:
        if not args.dry_run:
            write_lane_receipt("holdings_llm_refresh", script="holdings_llm_refresh", ok=False,
                               started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
