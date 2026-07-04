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
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from cio_agent_contract import (
    AGENT_JSON_CONTRACT_VERSION,
    build_llm_chunk_evidence_footer,
    extract_json_object,
    merge_structured_into_result,
)
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


def _build_data_summary(proposal, technical, backtest, stock_history):
    """Build compact data summary for the proposal."""
    symbol = proposal.get('symbol', '?')
    strategy = proposal.get('strategy_id', 'unknown')
    entry = proposal.get('proposed_entry', 0)
    stop = proposal.get('proposed_stop', 0)
    target = proposal.get('proposed_target1', 0)
    shares = proposal.get('proposed_shares', 0)
    risk_dollars = abs(float(entry or 0) - float(stop or 0)) * int(shares or 0)
    rr = proposal.get('proposed_rr', 'N/A')
    catalyst = proposal.get('catalyst') or 'None'
    cat_v = proposal.get('catalyst_verified', False)
    critic = proposal.get('critic_verdict') or 'N/A'

    lines = [f"{symbol} {strategy} E${entry} S${stop} T${target} x{shares} Risk${risk_dollars:.0f} RR{rr}"]
    lines.append(f"Cat:{str(catalyst)[:60]}{'(V)' if cat_v else '(UV)'} Critic:{critic} Sector:{proposal.get('vs_sector_pct','?')}%")

    if technical:
        t = technical
        lines.append(f"RSI:{t.get('rsi','?')}({t.get('rsi_state','?')}) ATR:{t.get('atr','?')} VWAP:{t.get('vwap_state','?')} RVOL:{t.get('rvol','?')} Vote:{t.get('technical_vote','?')}")
        concerns = t.get('technical_concerns', [])
        if concerns:
            lines.append(f"Concerns:{','.join(concerns)[:80]}")
    else:
        lines.append("Tech:none")

    if backtest:
        lines.append(f"BT:{backtest.get('backtest_quality','?')} n={backtest.get('sample_size',0)} WR:{backtest.get('win_rate','?')} PF:{backtest.get('profit_factor','?')}")
    else:
        lines.append("BT:none")

    if stock_history:
        h = stock_history
        lines.append(f"Hist:scans={h.get('prior_scans',0)} paper={h.get('paper_trades',0)}(w{h.get('paper_wins',0)}) real={h.get('real_trades',0)}")

    return "\n".join(lines)


def _build_analysis_prompt(data_summary):
    """Chunk 1: Analyze the setup — bull/bear/technical/catalyst."""
    return f"""Paper trade review. Be brief (2-3 sentences each field).
{data_summary}
JSON only:
{{"bull_case":"...","bear_case":"...","technical_condition":"...","catalyst_quality":"...","risk_reward_quality":"..."}}{build_llm_chunk_evidence_footer()}"""


def _build_decision_prompt(data_summary, analysis):
    """Chunk 2: Make decision based on data + analysis."""
    return f"""Paper trade decision. Use this analysis:
{data_summary}
Analysis: {json.dumps(analysis, default=str)[:300]}
JSON only:
{{"setup_summary":"1 sentence","decision":"APPROVE_READY|CAUTIOUS_TEST|WAIT_FOR_DATA|REJECT","confidence_score":0-100,"approval_conditions":"...","invalidation_conditions":"..."}}{build_llm_chunk_evidence_footer()}"""


def _build_risk_prompt(data_summary, analysis):
    """Chunk 3: Risk deep-dive — position sizing, correlation, max drawdown."""
    return f"""Risk analysis for paper trade. Be brief.
{data_summary}
Prior analysis: {json.dumps(analysis, default=str)[:200]}
JSON only:
{{"position_size_assessment":"...","correlation_risk":"...","max_drawdown_scenario":"...","risk_mitigation":"...","risk_grade":"A|B|C|D|F"}}{build_llm_chunk_evidence_footer()}"""


def _build_catalyst_prompt(data_summary, analysis):
    """Chunk 4: Catalyst verification — quality, timing, uniqueness."""
    return f"""Catalyst verification for paper trade. Be brief.
{data_summary}
Prior analysis: {json.dumps(analysis, default=str)[:200]}
JSON only:
{{"catalyst_type":"company_specific|sector|macro|technical|none","catalyst_freshness":"fresh|stale|unknown","catalyst_uniqueness":"unique|common|generic","catalyst_timing":"imminent|near_term|distant|expired","catalyst_grade":"A|B|C|D|F"}}{build_llm_chunk_evidence_footer()}"""


# Chunk stage progression: each stage depends on prior
CHUNK_STAGES = ['analysis', 'decision', 'risk', 'catalyst']


def _build_review_prompt(proposal, technical, backtest, stock_history):
    """Build structured review prompt (legacy single-shot fallback)."""
    data_summary = _build_data_summary(proposal, technical, backtest, stock_history)
    return f"""Paper trade review. Be brief. Use evidence only.
{data_summary}
JSON only:
{{"setup_summary":"...","technical_condition":"...","catalyst_quality":"...","bull_case":"...","bear_case":"...","risk_reward_quality":"...","confidence_score":0-100,"decision":"APPROVE_READY|CAUTIOUS_TEST|WAIT_FOR_DATA|REJECT"}}{build_llm_chunk_evidence_footer()}"""


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

    return merge_structured_into_result({
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
    })


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

    # Try LLM — first release the proposal-SELECT txn: the chunked review below runs 4-5
    # generations (minutes) and an open txn dies at PG's 120s idle-in-transaction kill,
    # taking the conn (and every status write after it) along.
    conn.commit()
    generate_fn = _get_llm()
    review = None
    model = "deterministic_fallback"
    narrative_source = "deterministic_fallback"

    def _parse_json(raw):
        parsed = extract_json_object(raw)
        return merge_structured_into_result(parsed) if parsed else None

    # Load prior chunk results (resume from where we left off)
    prior_chunks = {}
    raw_chunks = proposal.get('llm_review_chunks')
    if raw_chunks:
        if isinstance(raw_chunks, str):
            try: prior_chunks = json.loads(raw_chunks)
            except Exception: prior_chunks = {}
        elif isinstance(raw_chunks, dict):
            prior_chunks = raw_chunks
    completed_stage = proposal.get('llm_review_stage') or None

    if generate_fn:
        try:
            data_summary = _build_data_summary(proposal, technical, backtest, stock_history)

            # Determine which chunks to run
            need_analysis = 'analysis' not in prior_chunks
            need_decision = 'decision' not in prior_chunks
            need_risk = 'risk' not in prior_chunks
            need_catalyst = 'catalyst' not in prior_chunks

            analysis = prior_chunks.get('analysis')
            decision_result = prior_chunks.get('decision')
            risk_result = prior_chunks.get('risk')
            catalyst_result = prior_chunks.get('catalyst')

            # Chunk 1: Analysis
            if need_analysis:
                prompt1 = _build_analysis_prompt(data_summary)
                log.info(f"  {symbol}: chunk 1 (analysis)...")
                raw1 = generate_fn(prompt1, timeout=300, fallback=True, fast=False)
                analysis = _parse_json(raw1)
                if analysis:
                    prior_chunks['analysis'] = analysis
                    model = _get_model_name() or "local_llm"

            # Chunk 2: Decision (requires analysis)
            if analysis and need_decision:
                prompt2 = _build_decision_prompt(data_summary, analysis)
                log.info(f"  {symbol}: chunk 2 (decision)...")
                raw2 = generate_fn(prompt2, timeout=300, fallback=True, fast=False)
                decision_result = _parse_json(raw2)
                if decision_result:
                    prior_chunks['decision'] = decision_result
                    model = _get_model_name() or model

            # Chunk 3: Risk deep-dive (requires analysis)
            if analysis and need_risk:
                prompt3 = _build_risk_prompt(data_summary, analysis)
                log.info(f"  {symbol}: chunk 3 (risk)...")
                raw3 = generate_fn(prompt3, timeout=300, fallback=True, fast=False)
                risk_result = _parse_json(raw3)
                if risk_result:
                    prior_chunks['risk'] = risk_result
                    model = _get_model_name() or model

            # Chunk 4: Catalyst verification (requires analysis)
            if analysis and need_catalyst:
                prompt4 = _build_catalyst_prompt(data_summary, analysis)
                log.info(f"  {symbol}: chunk 4 (catalyst)...")
                raw4 = generate_fn(prompt4, timeout=300, fallback=True, fast=False)
                catalyst_result = _parse_json(raw4)
                if catalyst_result:
                    prior_chunks['catalyst'] = catalyst_result
                    model = _get_model_name() or model

            # Determine completed stage
            if catalyst_result and risk_result:
                completed_stage = 'catalyst'  # all 4 done
            elif risk_result:
                completed_stage = 'risk'
            elif decision_result:
                completed_stage = 'decision'
            elif analysis:
                completed_stage = 'analysis'

            # Merge all chunks into review
            if analysis:
                review = {}
                for chunk_data in [analysis, decision_result, risk_result, catalyst_result]:
                    if chunk_data:
                        review.update(chunk_data)
                # Validate decision
                decision = review.get('decision', 'CAUTIOUS_TEST')
                if decision not in ('APPROVE_READY', 'CAUTIOUS_TEST', 'WAIT_FOR_DATA', 'REJECT'):
                    decision = 'CAUTIOUS_TEST'
                review['decision'] = decision
                review['confidence_score'] = min(100, max(0, int(review.get('confidence_score', 50))))
                review['chunks_completed'] = list(prior_chunks.keys())
                review['agent_contract'] = AGENT_JSON_CONTRACT_VERSION
                narrative_source = "local_llm" if decision_result else "local_llm_partial"

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

    # Update proposal with chunk state
    try:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET local_llm_review_status = %s,
                llm_model_used = %s,
                confidence_score = %s,
                llm_review_stage = %s,
                llm_review_chunks = %s,
                updated_at = NOW()
            WHERE id = %s
        """, [
            f"{model} reviewed" if narrative_source in ("local_llm", "local_llm_partial") else "deterministic_fallback",
            model,
            review.get('confidence_score'),
            completed_stage,
            json.dumps(prior_chunks, default=str) if prior_chunks else None,
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
