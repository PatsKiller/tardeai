#!/usr/bin/env python3
"""proposal_llm_reviewer.py — Local LLM structured review for paper proposals.

Generates structured review using local LLM (qwen3) or deterministic fallback.
LLM is ANALYSIS ONLY — cannot approve or override risk gate.

Usage:
    .venv/bin/python scripts/proposal_llm_reviewer.py --proposal-id 2
    .venv/bin/python scripts/proposal_llm_reviewer.py --all-pending
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("llm_reviewer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _get_llm():
    try:
        from local_llm import generate, model_used
        return generate
    except ImportError:
        return None


def _get_model_name():
    try:
        from local_llm import model_used
        return model_used
    except Exception:
        return None


def _build_review_prompt(proposal, technical, backtest, stock_history):
    """Build structured review prompt."""
    symbol = proposal.get('symbol', '?')
    strategy = proposal.get('strategy_id', 'unknown')
    entry = proposal.get('proposed_entry', 0)
    stop = proposal.get('proposed_stop', 0)
    target = proposal.get('proposed_target1', 0)
    shares = proposal.get('proposed_shares', 0)

    risk_dollars = abs(float(entry or 0) - float(stop or 0)) * int(shares or 0)
    reward_dollars = (float(target or 0) - float(entry or 0)) * int(shares or 0)
    rr = proposal.get('proposed_rr', 'N/A')

    tech_lines = "No technical data available."
    if technical:
        tech_lines = f"""ATR: {technical.get('atr', 'missing')} / {technical.get('atr_pct', 'N/A')}% ({technical.get('atr_state', 'unknown')})
RSI: {technical.get('rsi', 'missing')} ({technical.get('rsi_state', 'unknown')})
VWAP: {technical.get('vwap_state', 'unknown')} (distance {technical.get('vwap_distance_pct', 'N/A')}%)
RVOL: {technical.get('rvol', 'N/A')} ({technical.get('rvol_state', 'unknown')})
Float: {technical.get('float_m', 'N/A')}M rotation: {technical.get('float_rotation_state', 'unknown')}
Gap: {technical.get('gap_pct', 'N/A')}% ({technical.get('gap_state', 'unknown')})
Fib: {json.dumps(technical.get('fib_context', {}), default=str)[:100]}
ORB: {json.dumps(technical.get('orb_context', {}), default=str)[:100]}
Technical vote: {technical.get('technical_vote', 'unknown')}
Concerns: {', '.join(technical.get('technical_concerns', []))}"""

    bt_lines = "No backtest data available."
    if backtest:
        bt_lines = f"""Quality: {backtest.get('backtest_quality', 'NO_DATA')} ({backtest.get('sample_size', 0)} samples)
Win rate: {backtest.get('win_rate', 'N/A')}
Profit factor: {backtest.get('profit_factor', 'N/A')}
Similar setup: {str(backtest.get('similar_setup_summary', 'N/A'))[:120]}
Repeat pattern: {backtest.get('repeat_pattern_detected', False)}
Limitations: {', '.join(backtest.get('limitations', []))}"""

    hist_lines = "No prior history."
    if stock_history:
        hist_lines = f"""Prior scans: {stock_history.get('prior_scans', 0)}
Paper trades: {stock_history.get('paper_trades', 0)} (wins: {stock_history.get('paper_wins', 0)})
Real trades: {stock_history.get('real_trades', 0)}
Last result: {stock_history.get('last_result', 'N/A')}"""

    return f"""You are reviewing a PAPER TRADE proposal for testing only.

Use the evidence below. Do not invent missing fields.
If data is missing, say it is missing.

Symbol: {symbol}
Strategy: {strategy}
Entry: ${entry} | Stop: ${stop} | Target: ${target}
Shares: {shares}
Risk: ${risk_dollars:.2f} | Reward: ${reward_dollars:.2f} | R:R: {rr}
Catalyst: {proposal.get('catalyst', 'None')} (verified={proposal.get('catalyst_verified', False)})
Critic: {proposal.get('critic_verdict', 'N/A')} — {str(proposal.get('critic_reasoning', ''))[:100]}
Sector: {proposal.get('sector', 'N/A')} (vs sector: {proposal.get('vs_sector_pct', 'N/A')}%)

TECHNICAL:
{tech_lines}

BACKTEST:
{bt_lines}

HISTORY:
{hist_lines}

Return structured JSON:
{{"setup_summary":"...","stock_history":"...","technical_condition":"...","catalyst_quality":"...","sector_context":"...","backtest_context":"...","bull_case":"...","bear_case":"...","risk_reward_quality":"...","approval_conditions":"...","invalidation_conditions":"...","confidence_score":0-100,"decision":"APPROVE_READY|CAUTIOUS_TEST|WAIT_FOR_DATA|REJECT"}}"""


def _deterministic_review(proposal, technical, backtest, stock_history):
    """Build deterministic fallback review."""
    symbol = proposal.get('symbol', '?')
    strategy = proposal.get('strategy_id', 'unknown')
    catalyst = proposal.get('catalyst')
    catalyst_verified = proposal.get('catalyst_verified', False)
    critic = proposal.get('critic_verdict')
    vs_sector = float(proposal.get('vs_sector_pct') or 0)
    rr = float(proposal.get('proposed_rr') or 0)

    # Technical condition
    tech_cond = "Technical data unavailable — indicator engine pending"
    if technical:
        parts = []
        if technical.get('rsi'):
            parts.append(f"RSI {technical['rsi']} ({technical.get('rsi_state', 'unknown')})")
        if technical.get('atr'):
            parts.append(f"ATR ${technical['atr']} ({technical.get('atr_state', 'unknown')})")
        if technical.get('vwap_state'):
            parts.append(technical['vwap_state'])
        tech_cond = "; ".join(parts) if parts else tech_cond

    # Catalyst quality
    cat_quality = "No catalyst"
    if catalyst_verified:
        cat_quality = f"Company-specific verified catalyst ({proposal.get('catalyst_confidence', 'N/A')} confidence)"
    elif catalyst:
        cat_quality = "Unverified catalyst — could be generic roundup"

    # Sector context
    if vs_sector > 5:
        sector_ctx = f"Outperforming sector by {vs_sector:.1f}% — tailwind"
    elif vs_sector > -5:
        sector_ctx = f"Sector neutral ({vs_sector:+.1f}%)"
    else:
        sector_ctx = f"Underperforming sector by {abs(vs_sector):.1f}% — headwind"

    # Backtest context
    bt_ctx = "No local backtest data available"
    if backtest:
        bt_ctx = f"Quality: {backtest.get('backtest_quality', 'NO_DATA')} ({backtest.get('sample_size', 0)} samples)"
        if backtest.get('win_rate') is not None:
            bt_ctx += f", win rate {backtest['win_rate']*100:.0f}%"

    # Decision
    confidence = 50
    decision = "CAUTIOUS_TEST"
    if critic == 'BLOCK':
        decision = "REJECT"
        confidence = 20
    elif not catalyst_verified and vs_sector < -5:
        decision = "WAIT_FOR_DATA"
        confidence = 35
    elif catalyst_verified and critic != 'DOWNGRADE' and rr >= 1.5:
        decision = "APPROVE_READY"
        confidence = 75
    elif catalyst_verified:
        decision = "CAUTIOUS_TEST"
        confidence = 60
    else:
        decision = "CAUTIOUS_TEST"
        confidence = 45

    # History
    hist_summary = "No prior trading history"
    if stock_history:
        hist_summary = f"Scans: {stock_history.get('prior_scans', 0)}, Paper: {stock_history.get('paper_trades', 0)}, Real: {stock_history.get('real_trades', 0)}"

    # R:R quality
    if rr >= 2.0:
        rr_quality = f"Good R:R ({rr:.2f})"
    elif rr >= 1.5:
        rr_quality = f"Acceptable R:R ({rr:.2f})"
    elif rr >= 1.0:
        rr_quality = f"Marginal R:R ({rr:.2f})"
    else:
        rr_quality = f"Poor R:R ({rr:.2f}) — risk exceeds reward"

    return {
        "setup_summary": f"{symbol} {strategy} proposal. {'Verified' if catalyst_verified else 'Unverified'} catalyst. Critic: {critic or 'N/A'}.",
        "stock_history": hist_summary,
        "technical_condition": tech_cond,
        "catalyst_quality": cat_quality,
        "sector_context": sector_ctx,
        "backtest_context": bt_ctx,
        "bull_case": f"{'Verified catalyst' if catalyst_verified else 'Potential catalyst'} with {strategy} setup. RVOL {proposal.get('rvol', 'N/A')}x.",
        "bear_case": f"{'Critic ' + critic + '. ' if critic and critic != 'PASS' else ''}{'Sector weakness. ' if vs_sector < -5 else ''}{'Missing technical data. ' if not technical or not technical.get('rsi') else ''}",
        "risk_reward_quality": rr_quality,
        "approval_conditions": f"Verify catalyst, confirm technical levels, ensure data freshness.",
        "invalidation_conditions": f"Price below stop ${proposal.get('proposed_stop', 0)} or catalyst reversed.",
        "confidence_score": confidence,
        "decision": decision,
    }


def review_proposal(conn, proposal_id):
    """Generate LLM review for a single proposal."""
    cur = conn.cursor()

    # Load proposal
    cur.execute("""
        SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, proposed_target1,
               proposed_shares, proposed_rr, rvol, float_m, gap_pct,
               catalyst, catalyst_verified, catalyst_confidence,
               critic_verdict, critic_confidence, critic_reasoning,
               sector, proposed_account,
               technical_context, backtest_summary, stock_history_summary
        FROM paper_trade_proposals WHERE id = %s
    """, [proposal_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        return {"error": f"Proposal {proposal_id} not found"}
    proposal = dict(zip(cols, row))
    symbol = proposal['symbol']

    # Parse stored JSON contexts
    technical = proposal.get('technical_context')
    if isinstance(technical, str):
        try: technical = json.loads(technical)
        except Exception: technical = {}

    backtest = proposal.get('backtest_summary')
    if isinstance(backtest, str):
        try: backtest = json.loads(backtest)
        except Exception: backtest = {}

    stock_history = proposal.get('stock_history_summary')
    if isinstance(stock_history, str):
        try: stock_history = json.loads(stock_history)
        except Exception: stock_history = {}

    # Try LLM
    generate_fn = _get_llm()
    review = None
    model = "deterministic_fallback"
    narrative_source = "deterministic_fallback"

    if generate_fn:
        try:
            prompt = _build_review_prompt(proposal, technical, backtest, stock_history)
            raw = generate_fn(prompt, timeout=120, fallback=True, fast=False)
            if raw:
                start = raw.find('{')
                end = raw.rfind('}') + 1
                if start >= 0 and end > start:
                    parsed = json.loads(raw[start:end])
                    # Validate decision
                    decision = parsed.get('decision', 'CAUTIOUS_TEST')
                    if decision not in ('APPROVE_READY', 'CAUTIOUS_TEST', 'WAIT_FOR_DATA', 'REJECT'):
                        decision = 'CAUTIOUS_TEST'
                    parsed['decision'] = decision
                    # Clamp confidence
                    parsed['confidence_score'] = min(100, max(0, int(parsed.get('confidence_score', 50))))
                    review = parsed
                    model = _get_model_name() or "local_llm"
                    narrative_source = "local_llm"
        except Exception as e:
            log.warning(f"LLM review failed for {symbol}: {e}")

    if not review:
        review = _deterministic_review(proposal, technical, backtest, stock_history)
        narrative_source = "deterministic_fallback"

    # Store in local_llm_runs
    now = datetime.now(timezone.utc)
    try:
        cur.execute("""
            INSERT INTO local_llm_runs
                (run_type, symbol, strategy_id, model_used, prompt_tokens, response_tokens,
                 result, narrative_source, created_at)
            VALUES ('proposal_review', %s, %s, %s, 0, 0, %s, %s, %s)
        """, [symbol, proposal.get('strategy_id'), model,
              json.dumps(review, default=str), narrative_source, now])
    except Exception as e:
        log.debug(f"local_llm_runs insert failed (table may differ): {e}")
        try: conn.rollback()
        except: pass

    # Update proposal
    try:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET local_llm_review_status = %s,
                confidence_score = %s,
                updated_at = NOW()
            WHERE id = %s
        """, [
            f"{model} reviewed" if narrative_source == "local_llm" else "deterministic_fallback",
            review.get('confidence_score'),
            proposal_id,
        ])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to update proposal {proposal_id}: {e}")
        conn.rollback()

    log.info(f"  {symbol} (#{proposal_id}): {narrative_source} — decision={review.get('decision')} confidence={review.get('confidence_score')}")

    return {
        "success": True,
        "proposal_id": proposal_id,
        "symbol": symbol,
        "narrative_source": narrative_source,
        "model": model,
        "review": review,
    }


def main():
    parser = argparse.ArgumentParser(description="Local LLM proposal reviewer")
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--all-pending", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.all_pending:
            cur = conn.cursor()
            cur.execute("SELECT id FROM paper_trade_proposals WHERE status='PENDING' ORDER BY created_at DESC")
            for (pid,) in cur.fetchall():
                review_proposal(conn, pid)
        elif args.proposal_id:
            result = review_proposal(conn, args.proposal_id)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Usage: --proposal-id N or --all-pending")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
