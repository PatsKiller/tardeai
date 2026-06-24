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


def get_recovery_context(symbol, conn=None):
    """Get stopped-out watch data for recovery analysis."""
    try:
        from db_adapter import _execute
        sw = _execute("""
            SELECT exit_price, stop_price, stopped_out_at, reason, thesis_at_exit,
                   status, setup_name, realized_pnl
            FROM stopped_out_watch WHERE symbol=%s AND is_active=true LIMIT 1
        """, [symbol], fetch="one")
        if not sw:
            return f"  No recovery data for {symbol}\n"
        snap = _execute("SELECT data->>'price' as price, rsi, perf_week_pct FROM ticker_snapshot_daily WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1", [symbol], fetch="one")
        exit_p = float(sw.get('exit_price') or 0)
        cur_p = float((snap or {}).get('price') or 0)
        recovery_pct = ((cur_p - exit_p) / exit_p * 100) if exit_p > 0 and cur_p > 0 else 0
        days_out = 0
        if sw.get('stopped_out_at'):
            try:
                days_out = (datetime.now(timezone.utc) - sw['stopped_out_at'].replace(tzinfo=timezone.utc if sw['stopped_out_at'].tzinfo is None else sw['stopped_out_at'].tzinfo)).days
            except Exception:
                pass
        return (
            f"  Exit: ${exit_p} | Stop: ${sw.get('stop_price')} | Stopped: {sw.get('stopped_out_at')}\n"
            f"  Days since exit: {days_out} | Status: {sw.get('status')}\n"
            f"  Reason: {sw.get('reason')} | Setup: {sw.get('setup_name')}\n"
            f"  Thesis at exit: {(str(sw.get('thesis_at_exit') or ''))[:200]}\n"
            f"  Realized P&L: ${sw.get('realized_pnl')}\n"
            f"  Current: ${cur_p} | RSI: {(snap or {}).get('rsi')} | Week: {(snap or {}).get('perf_week_pct')}%\n"
            f"  Recovery from exit: {recovery_pct:+.1f}%\n"
        )
    except Exception as e:
        return f"  Recovery error: {e}\n"


def get_proposal_context(proposal_id, conn=None):
    """Get full proposal data for review."""
    try:
        from db_adapter import _execute
        p = _execute("""
            SELECT proposed_entry, proposed_stop, proposed_target1, proposed_shares,
                   strategy_id, signal_score, signal_grade, catalyst, catalyst_verified,
                   screener_name, created_at
            FROM paper_trade_proposals WHERE id = %s
        """, [proposal_id], fetch="one")
        if not p:
            return f"  Proposal #{proposal_id} not found\n"
        pe = float(p.get('proposed_entry') or 0)
        ps = float(p.get('proposed_stop') or 0)
        pt = float(p.get('proposed_target1') or 0)
        sh = int(p.get('proposed_shares') or 0)
        rr = round((pt - pe) / (pe - ps), 1) if pe > ps and pt > pe else 0
        risk = round(abs(pe - ps) * sh, 2) if pe and ps else 0
        return (
            f"  Strategy: {p.get('strategy_id')} | Grade: {p.get('signal_grade')} | Score: {p.get('signal_score')}\n"
            f"  Entry: ${pe} | Stop: ${ps} | Target: ${pt}\n"
            f"  Shares: {sh} | Risk: ${risk} | R:R: {rr}:1\n"
            f"  Catalyst: {(str(p.get('catalyst') or ''))[:80]} {'(verified)' if p.get('catalyst_verified') else '(unverified)'}\n"
            f"  Source: {p.get('screener_name')} | Created: {p.get('created_at')}\n"
        )
    except Exception as e:
        return f"  Proposal error: {e}\n"


def get_covered_call_context(symbol, conn=None):
    """Get data for covered call scoring."""
    try:
        from db_adapter import _execute
        snap = _execute("""SELECT data->>'price' as price, rsi, data->>'beta' as beta,
                                  data->>'div_yield' as div_yield, data->>'rvol' as rvol,
                                  perf_week_pct, data->>'sma50_pct' as sma50
                           FROM ticker_snapshot_daily WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1""", [symbol], fetch="one")
        cc = _execute("SELECT verdict, reasoning FROM aegis_covered_call_candidates WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1", [symbol], fetch="one")
        lines = []
        if snap:
            lines.append(f"  Price: ${snap.get('price')} | RSI: {snap.get('rsi')} | Beta: {snap.get('beta')}")
            lines.append(f"  Div: {snap.get('div_yield')}% | RVOL: {snap.get('rvol')}x | Week: {snap.get('perf_week_pct')}%")
        if cc:
            lines.append(f"  Aegis verdict: {cc.get('verdict')} — {(str(cc.get('reasoning') or ''))[:80]}")
        return "\n".join(lines) + "\n" if lines else f"  No CC data for {symbol}\n"
    except Exception as e:
        return f"  CC error: {e}\n"


def build_context(symbol=None, context_type='general', trade_id=None,
                  proposal_id=None, conn=None, include_news=True,
                  include_history=True):
    """Build complete data context for any LLM prompt.

    context_type: 'trade_review', 'strategy_classification', 'recovery_watch',
                  'risk_synthesis', 'proposal', 'covered_call', 'general'
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

    if context_type == 'recovery_watch' and symbol:
        sections.append("RECOVERY DATA:")
        sections.append(get_recovery_context(symbol, conn))

    if context_type == 'proposal' and proposal_id:
        sections.append("PROPOSAL DATA:")
        sections.append(get_proposal_context(proposal_id, conn))

    if context_type == 'covered_call' and symbol:
        sections.append("COVERED CALL DATA:")
        sections.append(get_covered_call_context(symbol, conn))

    # Hermes self-learning injection — promoted research + accumulated lessons (learns over time).
    hk = get_hermes_knowledge(symbol=symbol, context_type=context_type, conn=conn)
    if hk:
        sections.append(hk)

    sections.append(ANTI_HALLUCINATION)

    return "\n".join(sections)


def get_hermes_knowledge(symbol=None, context_type='general', limit=5, conn=None):
    """Hermes self-learning context block: recent staged/promoted research findings + recent trade-close
    lessons. Read-only, advisory. Injected into every build_context() prompt so LLM submissions improve as
    Hermes learns. Returns '' on any error (never blocks a prompt)."""
    try:
        c = conn or _get_conn()
        if c is None:
            return ""
        cur = c.cursor()
        if symbol:
            cur.execute("""SELECT topic, left(summary,200) FROM hermes_research_intelligence
                           WHERE summary IS NOT NULL AND symbol=%s ORDER BY created_at DESC LIMIT %s""", (symbol, limit))
        else:
            cur.execute("""SELECT topic, left(summary,200) FROM hermes_research_intelligence
                           WHERE summary IS NOT NULL ORDER BY created_at DESC LIMIT %s""", (limit,))
        research = cur.fetchall()
        if symbol:
            cur.execute("""SELECT left(summary,160) FROM trade_llm_reviews
                           WHERE summary IS NOT NULL AND symbol=%s ORDER BY created_at DESC LIMIT %s""", (symbol, limit))
        else:
            cur.execute("""SELECT left(summary,160) FROM trade_llm_reviews
                           WHERE summary IS NOT NULL ORDER BY created_at DESC LIMIT %s""", (limit,))
        lessons = cur.fetchall()
        # Canonical Hermes context (composite score+rank + external-lane opinions) — the single source
        # every agent/local-LLM/OAuth-lane reads through, so "what Hermes knows about SYM" is consistent.
        canon = ""
        if symbol:
            try:
                from hermes_data_access import hermes_prompt_block
                canon = hermes_prompt_block(symbol)
            except Exception:
                canon = ""
        if not research and not lessons and not canon:
            return ""
        lines = []
        if canon:
            lines.append(canon)
        lines.append("HERMES RESEARCH & LESSONS (advisory; Hermes self-learning — context, not directives):")
        for t, s in research:
            lines.append(f"  • [{(t or 'research')[:50]}] {s}")
        for row in lessons:
            if row and row[0]:
                lines.append(f"  • lesson: {row[0]}")
        return "\n".join(lines)
    except Exception:
        return ""
