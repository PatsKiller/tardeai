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

from session13_db import get_conn

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
    shares = int(p.get('proposed_shares') or 0)
    risk = abs(entry - stop) * shares if entry and stop and shares else 0
    reward = (t1 - entry) * shares if t1 and entry and shares else 0

    # Extract RSI from indicator
    rsi = None
    ind = p.get('ind_full')
    if isinstance(ind, dict):
        rsi = ind.get('signals', {}).get('rsi', {}).get('value')

    news_str = "None"
    if p.get('news'):
        news_str = "\n".join(f"  - {n.get('title','')}" for n in (p['news'] or []) if isinstance(n, dict))

    missing = []
    if not p.get('atr'): missing.append('ATR')
    if rsi is None: missing.append('RSI')
    if not p.get('news'): missing.append('News')

    return f"""Analyze this paper trade proposal for TESTING only. Be concise (under 250 words).

Symbol: {p.get('symbol')}
Strategy: {p.get('strategy_id')}
Setup: {p.get('setup_type') or 'N/A'}
Entry: ${entry:.2f}
Stop: ${stop:.2f}
Target 1: ${t1:.2f}
Shares: {shares}
Risk dollars: ${risk:.2f}
Reward dollars: ${reward:.2f}
R:R: {p.get('proposed_rr') or 'N/A'}
RVOL: {p.get('rvol') or 'N/A'}
Float: {p.get('float_m') or 'N/A'}M
Gap: {p.get('gap_pct') or 'N/A'}%
ATR: {f"${float(p['atr']):.2f}" if p.get('atr') else 'missing'}
RSI: {f"{rsi:.1f}" if rsi else 'missing'}
Sector: {p.get('sector') or 'N/A'}
Sector perf: {p.get('sector_perf_1m') or 'N/A'}%
Ticker perf: {p.get('ticker_perf_1m') or 'N/A'}%
Catalyst: {str(p.get('catalyst') or 'None')[:100]}
Catalyst verified: {p.get('catalyst_verified')}
Critic: {p.get('critic_verdict') or 'N/A'} — {str(p.get('critic_reasoning') or '')[:100]}
News: {news_str}
Missing data: {', '.join(missing) if missing else 'None'}

Answer as JSON:
{{"summary":"...","approve_case":"...","reject_case":"...","invalidation":"what would invalidate this","confidence":0.0-1.0}}"""


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

    return {
        'summary': summary,
        'approve_case': approve,
        'reject_case': reject,
        'invalidation': 'Price drops below stop before entry or catalyst is invalidated.',
        'confidence': confidence,
    }


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
            raw = generate_fn(prompt, timeout=120, fallback=True, fast=False)
            if raw:
                try:
                    start = raw.find('{')
                    end = raw.rfind('}') + 1
                    if start >= 0 and end > start:
                        analysis = json.loads(raw[start:end])
                        try:
                            from local_llm import model_used
                            model = model_used
                        except Exception:
                            try:
                                from local_llm_config import get_local_llm_model
                                model = get_local_llm_model()
                            except Exception:
                                model = 'unknown'
                        narrative_source = 'local_llm'
                except Exception:
                    pass
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
             summary, approve_case, reject_case, invalidation, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, [pid, symbol, p.get('strategy_id'), model, narrative_source,
          analysis.get('summary'), analysis.get('approve_case'),
          analysis.get('reject_case'), analysis.get('invalidation'),
          analysis.get('confidence')])

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proposal intelligence analyzer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    result = run(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
