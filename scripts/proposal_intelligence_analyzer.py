#!/usr/bin/env python3
"""proposal_intelligence_analyzer.py — Generate decision-packet narratives for pending proposals.

Uses local LLM if available, deterministic fallback otherwise.

Usage:
    .venv/bin/python scripts/proposal_intelligence_analyzer.py --dry-run
    .venv/bin/python scripts/proposal_intelligence_analyzer.py --limit 5
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

from cio_agent_contract import (
    build_proposal_intelligence_json_schema,
    merge_structured_into_result,
    parse_proposal_intelligence_result,
)
from session13_db import get_conn
from local_llm_config import get_local_llm_model

log = logging.getLogger("proposal_analyzer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _get_llm():
    try:
        from local_llm import generate, model_used
        return generate
    except ImportError:
        return None


def get_pending_proposals(conn, limit=10):
    cur = conn.cursor()
    cur.execute("""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.setup_type,
               ptp.proposed_entry, ptp.proposed_stop, ptp.proposed_target1,
               ptp.proposed_target2, ptp.proposed_shares, ptp.proposed_dollar_risk,
               ptp.proposed_rr, ptp.signal_grade, ptp.signal_score,
               ptp.rvol, ptp.float_m, ptp.gap_pct, ptp.catalyst, ptp.catalyst_verified,
               ptp.intel_readiness, ptp.risk_gate_result,
               scan.critic_verdict, scan.critic_reasoning, scan.sector, scan.industry,
               scan.ticker_perf_1m, scan.sector_perf_1m, scan.vs_sector_pct,
               scan.catalyst_confidence, scan.change_pct,
               ind.atr, ind.full_result as ind_full,
               (SELECT json_agg(json_build_object('title', title))
                FROM (SELECT title FROM news_articles WHERE symbol=ptp.symbol
                      AND published_at > NOW() - INTERVAL '3 days'
                      ORDER BY published_at DESC LIMIT 3) n) as news
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM trade_ai_scans WHERE symbol=ptp.symbol
            ORDER BY scanned_at DESC LIMIT 1
        ) scan ON true
        LEFT JOIN LATERAL (
            SELECT * FROM indicator_confluence_cache WHERE symbol=ptp.symbol
            ORDER BY computed_at DESC LIMIT 1
        ) ind ON true
        WHERE ptp.status = 'PENDING'
        AND ptp.id NOT IN (SELECT proposal_id FROM paper_proposal_analysis WHERE proposal_id IS NOT NULL)
        ORDER BY ptp.created_at DESC
        LIMIT %s
    """, [limit])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_prompt(p):
    entry = float(p.get('proposed_entry') or 0)
    stop = float(p.get('proposed_stop') or 0)
    t1 = float(p.get('proposed_target1') or 0)
    t2 = float(p.get('proposed_target2') or 0)
    shares = int(p.get('proposed_shares') or 0)
    risk = abs(entry - stop) * shares if entry and stop and shares else 0
    reward = (t1 - entry) * shares if t1 and entry and shares else 0
    risk_r = round(risk / entry * 100, 2) if entry else 0

    # Extract indicators from full_result
    ind = p.get('ind_full')
    rsi = None
    vwap = None
    vwap_dist = None
    atr_pct = None
    macd_state = None
    adx = None
    squeeze = None
    if isinstance(ind, dict):
        sigs = ind.get('signals', ind)
        rsi = sigs.get('rsi', {}).get('value')
        vwap = sigs.get('vwap', {}).get('value')
        vwap_dist = sigs.get('vwap', {}).get('details', {}).get('distance_pct')
        atr_pct = sigs.get('atr', {}).get('details', {}).get('atr_pct')
        macd_state = sigs.get('macd', {}).get('signal')
        adx = sigs.get('adx', {}).get('value')
        kc = sigs.get('keltner', {}).get('details', {})
        squeeze = "SQUEEZE_ON" if kc.get('squeeze_on') else "FIRED" if kc.get('squeeze_fired') else "none"

    news_str = "None"
    if p.get('news'):
        news_str = "\n".join(f"  - {n.get('title','')}" for n in (p['news'] or []) if isinstance(n, dict))

    missing = []
    if not p.get('atr'): missing.append('ATR')
    if rsi is None: missing.append('RSI')
    if vwap is None: missing.append('VWAP')
    if not p.get('news'): missing.append('News')

    vs_sector = p.get('vs_sector_pct')
    vs_sector_str = f"{float(vs_sector):+.1f}%" if vs_sector is not None else "N/A"

    # Session 24B: Inject strategy context from YAML
    strategy_ctx = ""
    try:
        from strategy_config_loader import get_strategy_prompt_context
        strategy_ctx = get_strategy_prompt_context(p.get('strategy_id', 'momentum_scalp'), p)
    except Exception:
        strategy_ctx = f"Strategy: {p.get('strategy_id', 'unknown')} (no YAML config loaded)"

    # Session 24B: Setup stack context
    setup_stack_ctx = ""
    if p.get('setup_stack'):
        stack = p['setup_stack'] if isinstance(p['setup_stack'], list) else []
        if stack:
            setup_stack_ctx = "\n=== SETUP STACK ===\n" + "\n".join(
                f"  {m.get('strategy_id','?')}: score={m.get('match_score',0)} "
                f"status={m.get('match_status','?')} {'[PRIMARY]' if m.get('is_primary') else ''}"
                for m in stack[:5])

    # Inject past trade outcomes from RAG for this symbol/strategy
    trade_history_ctx = ""
    try:
        from rag_retrieval import get_rag_context
        rag_results = get_rag_context(symbol=p.get('symbol'), strategy_focus=p.get('strategy_id'), limit=5)
        outcomes = [r for r in rag_results if r.get('source_type') == 'trade_outcome']
        if outcomes:
            trade_history_ctx = "\n=== PAST TRADE OUTCOMES (from system memory) ===\n" + "\n".join(
                f"  - {o.get('title', '')}" for o in outcomes[:3])
            trade_history_ctx += "\nFactor these past results into your assessment. If similar setups lost money, explain why this time is different or recommend rejection.\n"
    except Exception:
        pass

    return f"""You are an institutional prop desk analyst. Analyze this paper trade proposal.
Be specific. Reference at least 5 numeric facts. Identify 2+ kill conditions.
Your analysis MUST explicitly state: (1) primary strategy and why, (2) secondary setups if any,
(3) 3+ criteria met, (4) any criteria failed, (5) whether auto-disqualifiers were checked.
(6) If past trade outcomes are available below, explain whether this trade avoids the same mistakes.
If your answer could apply to any ticker, rewrite it. Under 300 words.

=== TRADE SETUP ===
Symbol: {p.get('symbol')} | Strategy: {p.get('strategy_id')} | Setup: {p.get('setup_type') or 'N/A'}
Entry: ${entry:.2f} | Stop: ${stop:.2f} | Target: ${t1:.2f} | T2: ${t2:.2f}
Shares: {shares} | Risk: ${risk:.0f} | Reward: ${reward:.0f} | R:R: {p.get('proposed_rr') or 'N/A'}

=== {strategy_ctx} ==={setup_stack_ctx}

=== TECHNICAL MAP ===
RSI: {f"{rsi:.1f}" if rsi else 'N/A'} | ATR: {f"${float(p['atr']):.2f} ({atr_pct:.1f}%)" if p.get('atr') and atr_pct else 'N/A'}
VWAP: {f"${float(vwap):.2f} ({float(vwap_dist):+.1f}%)" if vwap and vwap_dist else 'N/A'}
MACD: {macd_state or 'N/A'} | ADX: {f"{float(adx):.0f}" if adx else 'N/A'} | Squeeze: {squeeze or 'N/A'}

=== CATALYST + CONTEXT ===
RVOL: {p.get('rvol') or 'N/A'}x | Float: {p.get('float_m') or 'N/A'}M | Gap: {p.get('gap_pct') or 'N/A'}%
Sector: {p.get('sector') or 'N/A'} | vs Sector: {vs_sector_str}
Catalyst: {str(p.get('catalyst') or 'None')[:150]}
Verified: {p.get('catalyst_verified')} | Confidence: {p.get('catalyst_confidence') or 'N/A'}
Critic: {p.get('critic_verdict') or 'N/A'} — {str(p.get('critic_reasoning') or '')[:100]}
News: {news_str}
Missing: {', '.join(missing) if missing else 'None'}
{trade_history_ctx}
{build_proposal_intelligence_json_schema()}"""


def build_deterministic_analysis(p):
    entry = float(p.get('proposed_entry') or 0)
    stop = float(p.get('proposed_stop') or 0)
    t1 = float(p.get('proposed_target1') or 0)
    shares = int(p.get('proposed_shares') or 0)
    risk = abs(entry - stop) * shares if entry and stop else 0
    reward = (t1 - entry) * shares if t1 and entry else 0
    symbol = p.get('symbol', '?')
    strategy = p.get('strategy_id', 'unknown')
    rvol = p.get('rvol')
    catalyst = p.get('catalyst')
    verified = p.get('catalyst_verified')
    critic = p.get('critic_verdict')
    vs_sector = p.get('vs_sector_pct')

    parts = [f"{symbol} is a {strategy} proposal."]
    if rvol: parts.append(f"RVOL {float(rvol):.1f}x.")
    if verified: parts.append("Catalyst verified.")
    elif catalyst: parts.append("Catalyst unverified.")
    if critic and critic != 'PASS': parts.append(f"Critic: {critic}.")
    if vs_sector is not None:
        parts.append(f"{'Outperforming' if float(vs_sector) > 0 else 'Underperforming'} sector by {abs(float(vs_sector)):.1f}%.")
    summary = " ".join(parts)

    approve = "Paper test to validate system's handling of this setup type."
    if verified and (not critic or critic == 'PASS'):
        approve = f"Verified catalyst with clear trade plan. Risk ${risk:.0f}. Approve as paper test."

    reject = "No strong rejection signals."
    reasons = []
    if critic == 'BLOCK': reasons.append("Critic BLOCKED.")
    if critic == 'DOWNGRADE': reasons.append(f"Critic downgraded: {str(p.get('critic_reasoning',''))[:80]}")
    if vs_sector is not None and float(vs_sector) < -5: reasons.append(f"Weak sector: {float(vs_sector):.1f}%")
    if reasons: reject = " ".join(reasons)

    confidence = 0.5
    if verified and (not critic or critic == 'PASS'): confidence = 0.7
    if critic == 'BLOCK': confidence = 0.2
    if critic == 'DOWNGRADE': confidence = 0.4

    return merge_structured_into_result({
        'summary': summary,
        'approve_case': approve,
        'reject_case': reject,
        'invalidation': 'Price drops below stop before entry or catalyst is invalidated.',
        'confidence': confidence,
    })


def analyze_proposal(conn, p, generate_fn=None, dry_run=False):
    pid = p['id']
    symbol = p['symbol']

    if dry_run:
        log.info(f"[dry-run] Would analyze {symbol} (proposal #{pid})")
        return {'success': True, 'dry_run': True}

    analysis = None
    model = None
    narrative_source = 'deterministic_fallback'

    if generate_fn:
        try:
            prompt = build_prompt(p)
            # Close any open read txn (fetch/RAG lookups) before the LLM call — its 120s timeout
            # matches PG's idle-in-transaction kill exactly, so a slow generation loses the race.
            conn.commit()
            raw = generate_fn(prompt, timeout=120, fallback=True, fast=False)
            if raw:
                parsed = parse_proposal_intelligence_result(raw)
                if parsed:
                    analysis = parsed
                    model = get_local_llm_model()
                    narrative_source = 'local_llm'
        except Exception as e:
            log.warning(f"LLM failed for {symbol}: {e}")

    if not analysis:
        analysis = build_deterministic_analysis(p)
        narrative_source = 'deterministic_fallback'

    # Write to paper_proposal_analysis
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO paper_proposal_analysis
            (proposal_id, symbol, strategy_id, model_used, narrative_source,
             summary, approve_case, reject_case, invalidation, confidence,
             catalyst_summary, risk_summary, technical_summary)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, [pid, symbol, p.get('strategy_id'), model, narrative_source,
          analysis.get('summary'), analysis.get('approve_case'),
          analysis.get('reject_case'), analysis.get('invalidation'),
          analysis.get('confidence'),
          json.dumps({
              "assessment": analysis.get('catalyst_assessment'),
              "agent_contract": analysis.get('agent_contract'),
              "evidence": analysis.get('evidence', []),
              "data_i_doubt": analysis.get('data_i_doubt'),
          }) if analysis.get('catalyst_assessment') or analysis.get('evidence') else None,
          json.dumps({
              "assessment": analysis.get('risk_assessment'),
              "kill_conditions": analysis.get('kill_conditions', []),
              "agent_contract": analysis.get('agent_contract'),
          }) if analysis.get('risk_assessment') or analysis.get('kill_conditions') else None,
          json.dumps({
              "assessment": analysis.get('technical_assessment'),
              "strategy_fit": analysis.get('strategy_fit_assessment'),
              "agent_contract": analysis.get('agent_contract'),
          }) if analysis.get('technical_assessment') or analysis.get('strategy_fit_assessment') else None])

    log.info(f"  {symbol} (#{pid}): {narrative_source} — confidence {analysis.get('confidence')}")
    return {'success': True, 'symbol': symbol, 'source': narrative_source}


def run(limit=10, dry_run=False):
    generate_fn = _get_llm()
    log.info(f"LLM available: {generate_fn is not None}")

    conn = get_conn()
    try:
        proposals = get_pending_proposals(conn, limit)
        log.info(f"Found {len(proposals)} proposals needing analysis")

        processed = 0
        for p in proposals:
            result = analyze_proposal(conn, p, generate_fn, dry_run)
            if result.get('success'):
                processed += 1
            if not dry_run:
                conn.commit()

        log.info(f"Analyzed {processed}/{len(proposals)} proposals")
        return {'processed': processed, 'total': len(proposals), 'dry_run': dry_run}
    finally:
        conn.close()


def expire_stale_proposals(dry_run=False):
    """Expire PENDING proposals that are past expiry or too old for intraday strategies."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        # Expire intraday proposals older than 8 hours
        cur.execute("""
            SELECT id, symbol, strategy_id, created_at
            FROM paper_trade_proposals
            WHERE status = 'PENDING'
            AND proposal_timeframe_class = 'intraday'
            AND created_at < NOW() - INTERVAL '8 hours'
        """)
        old_proposals = cur.fetchall()

        if dry_run:
            log.info(f"[dry-run] Would expire {len(old_proposals)} intraday proposals (>8hr)")
            for pid, sym, sid, created in old_proposals:
                log.info(f"  [dry-run] #{pid} {sym} ({sid}) created {created}")
        else:
            cur.execute("""
                UPDATE paper_trade_proposals
                SET status = 'EXPIRED',
                    rejection_reason = 'EOD cleanup: intraday proposal too old (>8hr)',
                    rejected_at = NOW(), updated_at = NOW()
                WHERE status = 'PENDING'
                AND proposal_timeframe_class = 'intraday'
                AND created_at < NOW() - INTERVAL '8 hours'
            """)
            expired_age = cur.rowcount
            log.info(f"Expired {expired_age} intraday proposals by age (>8hr)")

        # Expire proposals past their expires_at
        cur.execute("""
            SELECT id, symbol, strategy_id, expires_at
            FROM paper_trade_proposals
            WHERE status = 'PENDING' AND expires_at < NOW()
        """)
        past_expiry = cur.fetchall()

        if dry_run:
            log.info(f"[dry-run] Would expire {len(past_expiry)} proposals past expiry time")
        else:
            cur.execute("""
                UPDATE paper_trade_proposals
                SET status = 'EXPIRED',
                    rejection_reason = 'Passed expiry time',
                    rejected_at = NOW(), updated_at = NOW()
                WHERE status = 'PENDING' AND expires_at < NOW()
            """)
            expired_time = cur.rowcount
            log.info(f"Expired {expired_time} proposals past expiry time")

        if not dry_run:
            conn.commit()

        total = (len(old_proposals) + len(past_expiry)) if dry_run else ((expired_age if 'expired_age' in dir() else 0) + (expired_time if 'expired_time' in dir() else 0))
        return {'expired': total, 'dry_run': dry_run}
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proposal intelligence analyzer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pending", action="store_true", help="Process pending proposals")
    parser.add_argument("--apply", action="store_true", help="Write to DB (default is dry-run)")
    parser.add_argument("--expire-stale", action="store_true", help="Expire old/past-expiry proposals")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--proposal-id", type=int, default=None, help="Analyze specific proposal ID")
    args = parser.parse_args()

    if args.expire_stale:
        dry = not args.apply
        result = expire_stale_proposals(dry_run=dry)
        print(json.dumps(result, indent=2))
    elif args.proposal_id:
        # Targeted single-proposal analysis
        dry = not args.apply
        log.info(f"Model configured: {get_local_llm_model()}")
        generate_fn = _get_llm()
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.setup_type,
                       ptp.proposed_entry, ptp.proposed_stop, ptp.proposed_target1,
                       ptp.proposed_target2, ptp.proposed_shares, ptp.proposed_dollar_risk,
                       ptp.proposed_rr, ptp.signal_grade, ptp.signal_score,
                       ptp.rvol, ptp.float_m, ptp.gap_pct, ptp.catalyst, ptp.catalyst_verified,
                       ptp.intel_readiness, ptp.risk_gate_result,
                       scan.critic_verdict, scan.critic_reasoning, scan.sector, scan.industry,
                       scan.ticker_perf_1m, scan.sector_perf_1m, scan.vs_sector_pct,
                       scan.catalyst_confidence, scan.change_pct,
                       ind.atr, ind.full_result as ind_full,
                       NULL as news
                FROM paper_trade_proposals ptp
                LEFT JOIN LATERAL (
                    SELECT * FROM trade_ai_scans WHERE symbol=ptp.symbol
                    ORDER BY scanned_at DESC LIMIT 1
                ) scan ON true
                LEFT JOIN LATERAL (
                    SELECT * FROM indicator_confluence_cache WHERE symbol=ptp.symbol
                    ORDER BY computed_at DESC LIMIT 1
                ) ind ON true
                WHERE ptp.id = %s
            """, [args.proposal_id])
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            if row:
                p = dict(zip(cols, row))
                result = analyze_proposal(conn, p, generate_fn, dry)
                if not dry:
                    conn.commit()
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"Proposal {args.proposal_id} not found")
                sys.exit(1)
        finally:
            conn.close()
    else:
        dry = not args.apply if args.apply or args.pending else args.dry_run
        if args.pending and not args.apply:
            dry = True
        if args.apply:
            dry = False
        log.info(f"Model configured: {get_local_llm_model()}")
        result = run(limit=args.limit, dry_run=dry)
        print(json.dumps(result, indent=2))
