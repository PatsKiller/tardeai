#!/usr/bin/env python3
"""llm_context_engine.py — Centralized data context builder for ALL LLM prompts.

Every LLM call in the system should use this engine to inject actual data
into prompts. No prompt should pass only IDs or trigger names when the
actual data is available in the DB.

Usage:
    from llm_context_engine import build_context
    ctx = build_context(symbol='GCTS', context_type='trade_review', trade_id=158)
    prompt = f"Review this trade:\\n{ctx}\\n\\nProvide analysis..."

Works with any model: qwen3:14b, gemma3-overnight, Anthropic Sonnet.
The model doesn't matter — bad context produces bad output regardless.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

log = logging.getLogger("llm_context_engine")

ANTI_HALLUCINATION = """
CRITICAL INSTRUCTIONS:
- Use ONLY the data provided above in your analysis
- Do NOT invent, estimate, or assume numbers not in the data
- Do NOT claim patterns unless the data explicitly supports them
- If data is missing, say "data not available" — do not fill gaps
- If you reference a number (price, count, %, date), it must appear in the data above
"""


def _get_conn():
    try:
        from db_adapter import _get_conn as _gc
        return _gc()
    except Exception:
        return None


def _safe(val, fmt=None, default='N/A'):
    if val is None:
        return default
    if fmt == '$':
        return f"${val}"
    if fmt == '%':
        return f"{val}%"
    if fmt == 'x':
        return f"{val}x"
    return str(val)


def get_symbol_snapshot(symbol, conn=None):
    """Get current technical/fundamental snapshot for a symbol."""
    _conn = conn or _get_conn()
    if not _conn:
        return ""
    try:
        from db_adapter import _execute
        row = _execute("""
            SELECT data->>'price' as price, rsi, perf_week_pct,
                   data->>'rvol' as rvol, data->>'sector' as sector,
                   data->>'beta' as beta, data->>'pe' as pe,
                   data->>'div_yield' as div_yield,
                   data->>'sma200' as sma200, data->>'sma50' as sma50,
                   data->>'market_cap' as market_cap,
                   data->>'float_shares' as float_shares,
                   snapshot_date
            FROM ticker_snapshot_daily
            WHERE symbol = %s ORDER BY snapshot_date DESC LIMIT 1
        """, [symbol], fetch="one")
        if not row:
            return f"  No snapshot data for {symbol}\n"
        return (
            f"  Price: {_safe(row.get('price'), '$')} | RSI: {_safe(row.get('rsi'))} | RVOL: {_safe(row.get('rvol'), 'x')}\n"
            f"  Sector: {_safe(row.get('sector'))} | Beta: {_safe(row.get('beta'))} | P/E: {_safe(row.get('pe'))}\n"
            f"  Div yield: {_safe(row.get('div_yield'), '%')} | Float: {_safe(row.get('float_shares'))}M\n"
            f"  Week perf: {_safe(row.get('perf_week_pct'), '%')} | SMA50: {_safe(row.get('sma50'))} | SMA200: {_safe(row.get('sma200'))}\n"
            f"  Snapshot: {_safe(row.get('snapshot_date'))}\n"
        )
    except Exception as e:
        return f"  Snapshot error: {e}\n"


def get_trade_history(symbol, conn=None):
    """Get past trade history for a symbol from both paper_trades and trade_closed."""
    _conn = conn or _get_conn()
    if not _conn:
        return ""
    try:
        from db_adapter import _execute
        # Paper trades
        paper = _execute("""
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                   ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                   ROUND(AVG(CASE WHEN pnl != 0 THEN pnl END)::numeric, 2) as avg_pnl
            FROM paper_trades WHERE symbol = %s AND lifecycle_state = 'closed'
        """, [symbol], fetch="one") or {}
        # Historical trades
        hist = _execute("""
            SELECT COUNT(*) as n,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                   ROUND(SUM(pnl)::numeric, 2) as total_pnl,
                   SUM(CASE WHEN stop_used IS NOT NULL AND stop_used::text != '' THEN 1 ELSE 0 END) as stops_used
            FROM trade_closed WHERE symbol = %s
        """, [symbol], fetch="one") or {}

        lines = []
        pn = paper.get('n', 0)
        if pn and pn > 0:
            lines.append(f"  Paper trades: {pn} ({paper.get('wins', 0)}W {paper.get('losses', 0)}L, PnL ${paper.get('total_pnl', 0)})")
        hn = hist.get('n', 0)
        if hn and hn > 0:
            lines.append(f"  Historical trades: {hn} ({hist.get('wins', 0)}W {hist.get('losses', 0)}L, PnL ${hist.get('total_pnl', 0)}, stops used: {hist.get('stops_used', 0)}/{hn})")
        if not lines:
            return "  No trade history for this symbol\n"
        return "\n".join(lines) + "\n"
    except Exception as e:
        return f"  History error: {e}\n"


def get_closed_trade_detail(trade_id, conn=None):
    """Get full detail for a closed trade from trade_closed table."""
    _conn = conn or _get_conn()
    if not _conn:
        return ""
    try:
        from db_adapter import _execute
        row = _execute("""
            SELECT id, symbol, account, open_date, close_date, trade_type,
                   buy_price, sell_price, pnl, pnl_pct, hold_days, stop_used,
                   r_multiple, setup, note
            FROM trade_closed WHERE id = %s
        """, [trade_id], fetch="one")
        if not row:
            return f"  Trade #{trade_id} not found in trade_closed\n"
        return (
            f"  Symbol: {row.get('symbol')} | Account: {row.get('account')}\n"
            f"  Type: {row.get('trade_type')} | Setup: {_safe(row.get('setup'))}\n"
            f"  Entry: {_safe(row.get('buy_price'), '$')} on {row.get('open_date')}\n"
            f"  Exit: {_safe(row.get('sell_price'), '$')} on {row.get('close_date')}\n"
            f"  P&L: {_safe(row.get('pnl'), '$')} ({_safe(row.get('pnl_pct'), '%')})\n"
            f"  Hold: {_safe(row.get('hold_days'))} days | R: {_safe(row.get('r_multiple'))}\n"
            f"  Stop used: {'$' + str(row['stop_used']) if row.get('stop_used') else 'NONE'}\n"
            f"  Note: {(str(row.get('note') or ''))[:100]}\n"
        )
    except Exception as e:
        return f"  Trade detail error: {e}\n"


def get_recent_news(symbol, days=7, limit=5, conn=None):
    """Get recent news headlines for a symbol."""
    _conn = conn or _get_conn()
    if not _conn:
        return ""
    try:
        from db_adapter import _execute
        rows = _execute("""
            SELECT title, source, sentiment, published_at::date
            FROM news_articles WHERE symbol = %s
            AND published_at > NOW() - INTERVAL '7 days'
            ORDER BY published_at DESC LIMIT %s
        """, [symbol, limit]) or []
        if not rows:
            return "  No recent news\n"
        lines = [f"  {r.get('published_at')}: [{r.get('sentiment', '?')}] {(r.get('title') or '')[:80]} ({r.get('source')})" for r in rows]
        return "\n".join(lines) + "\n"
    except Exception as e:
        return f"  News error: {e}\n"


def get_portfolio_context(conn=None):
    """Get full portfolio context for risk synthesis."""
    try:
        hdata = json.load(open(str(PROJECT_ROOT / "data/portfolios/state/holdings.json")))
        total = hdata.get("portfolio_totals", {}).get("total_value", 0)
        holdings = sorted(hdata.get("holdings", []),
                          key=lambda h: h.get("market_value", 0), reverse=True)[:25]
        lines = [f"Portfolio: ${total:,.0f}"]
        for h in holdings:
            sym = h.get("symbol", "?")
            mv = h.get("market_value", 0)
            pct = h.get("portfolio_pct", 0)
            dc = h.get("day_change", 0)
            lines.append(f"  {sym}: ${mv:,.0f} ({pct:.1f}%) day={dc:+.0f}")
        return "\n".join(lines) + "\n"
    except Exception as e:
        return f"  Portfolio error: {e}\n"


def build_context(symbol=None, context_type='general', trade_id=None,
                  proposal_id=None, conn=None, include_news=True,
                  include_history=True):
    """Build complete data context for any LLM prompt.

    context_type: 'trade_review', 'strategy', 'recovery', 'proposal',
                  'risk_synthesis', 'general'
    """
    sections = []

    if symbol:
        sections.append(f"SYMBOL: {symbol}")
        sections.append("CURRENT DATA:")
        sections.append(get_symbol_snapshot(symbol, conn))

        if include_history:
            sections.append("TRADE HISTORY:")
            sections.append(get_trade_history(symbol, conn))

        if include_news:
            sections.append("RECENT NEWS:")
            sections.append(get_recent_news(symbol, conn=conn))

    if trade_id and context_type == 'trade_review':
        sections.append("TRADE DETAIL:")
        sections.append(get_closed_trade_detail(trade_id, conn))

    if context_type == 'risk_synthesis':
        sections.append("PORTFOLIO:")
        sections.append(get_portfolio_context(conn))

    sections.append(ANTI_HALLUCINATION)

    return "\n".join(sections)
