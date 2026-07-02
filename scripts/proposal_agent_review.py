#!/usr/bin/env python3
"""proposal_agent_review.py — Agent review orchestrator for paper proposals.

Routes each proposal to the required agents based on strategy type.
Uses local LLM when available, deterministic fallback otherwise.

Usage:
    .venv/bin/python scripts/proposal_agent_review.py --proposal-id 2
    .venv/bin/python scripts/proposal_agent_review.py --all-pending
    .venv/bin/python scripts/proposal_agent_review.py --dry-run --proposal-id 2
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
    build_proposal_vote_json_schema,
    merge_structured_into_result,
    parse_proposal_vote_result,
)
from session13_db import get_conn

log = logging.getLogger("agent_review")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# ── Strategy -> required agents mapping ────────────────────────────────────

STRATEGY_AGENTS = {
    "momentum_scalp": ["Maria", "Risk", "Iris", "Aegis"],
    "gap_and_go": ["Maria", "Risk", "Iris", "Aegis"],
    "swing_breakout": ["Maria", "Risk", "Steph", "Aegis"],
    "sector_rotation": ["Risk", "Steph", "Aegis"],
    "income_add": ["Steph", "Tax", "Alex", "Aegis"],
    "earnings_catalyst": ["Maria", "Risk", "Iris", "Aegis"],
}

DEFAULT_AGENTS = ["Risk", "Aegis"]

AGENT_ROLES = {
    "Maria": "catalyst_news",
    "Risk": "technicals_risk",
    "Iris": "source_memory",
    "Aegis": "desk_supervisor",
    "Steph": "portfolio_advisor",
    "Tax": "tax_compliance",
    "Alex": "retirement_advisor",
}

VALID_VOTES = {"APPROVE_TEST", "CAUTIOUS_TEST", "WAIT_FOR_DATA", "REJECT", "BLOCK", "NOT_APPLICABLE"}


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


def _get_trade_history_context(symbol, strategy):
    """Fetch past trade outcomes from RAG for this symbol/strategy."""
    try:
        from rag_retrieval import get_rag_context, format_rag_context_for_prompt
        results = get_rag_context(symbol=symbol, strategy_focus=strategy, limit=5)
        # Filter to trade outcomes only
        outcomes = [r for r in results if r.get('source_type') == 'trade_outcome']
        if outcomes:
            lines = []
            for o in outcomes[:3]:
                lines.append(f"  - {o.get('title', '')}")
            return "PAST TRADE HISTORY (from system memory):\n" + "\n".join(lines)
    except Exception:
        pass
    return ""


def _build_agent_prompt(agent_name, proposal, technical, backtest):
    """Build review prompt for a specific agent."""
    symbol = proposal.get('symbol', '?')
    strategy = proposal.get('strategy_id', 'unknown')
    entry = proposal.get('proposed_entry', 0)
    stop = proposal.get('proposed_stop', 0)
    target = proposal.get('proposed_target1', 0)
    shares = proposal.get('proposed_shares', 0)
    rvol = proposal.get('rvol', 'N/A')
    float_m = proposal.get('float_m', 'N/A')
    gap_pct = proposal.get('gap_pct', 'N/A')
    catalyst = proposal.get('catalyst', 'None')
    catalyst_verified = proposal.get('catalyst_verified', False)
    catalyst_confidence = proposal.get('catalyst_confidence', 'N/A')
    critic = proposal.get('critic_verdict', 'N/A')
    critic_reasoning = str(proposal.get('critic_reasoning') or '')[:120]
    sector = proposal.get('sector', 'N/A')
    vs_sector = proposal.get('vs_sector_pct', 'N/A')

    tech_summary = ""
    if technical:
        tech_summary = f"""ATR: {technical.get('atr', 'missing')} ({technical.get('atr_state', 'unknown')})
RSI: {technical.get('rsi', 'missing')} ({technical.get('rsi_state', 'unknown')})
VWAP: {technical.get('vwap_state', 'unknown')} ({technical.get('vwap_distance_pct', 'N/A')}%)
RVOL: {rvol} ({technical.get('rvol_state', 'unknown')})
Float rotation: {technical.get('float_rotation_state', 'unknown')}
Fib: {json.dumps(technical.get('fib_context', {}), default=str)[:80]}
ORB: {json.dumps(technical.get('orb_context', {}), default=str)[:80]}"""

    bt_summary = ""
    if backtest:
        bt_summary = f"""Backtest quality: {backtest.get('backtest_quality', 'NO_DATA')}
Sample size: {backtest.get('sample_size', 0)}
Win rate: {backtest.get('win_rate', 'N/A')}
Similar setup: {backtest.get('similar_setup_summary', 'N/A')[:100]}"""

    # Inject past trade history from RAG
    history_context = _get_trade_history_context(symbol, strategy)

    base = f"""You are {agent_name}, reviewing a PAPER TRADE proposal for {symbol}.
Strategy: {strategy}
Entry: ${entry} | Stop: ${stop} | Target: ${target} | Shares: {shares}
RVOL: {rvol} | Float: {float_m}M | Gap: {gap_pct}%
Catalyst: {catalyst} (verified={catalyst_verified}, confidence={catalyst_confidence})
Critic: {critic} — {critic_reasoning}
Sector: {sector} | vs Sector: {vs_sector}%
{tech_summary}
{bt_summary}
{history_context}
"""

    agent_instructions = {
        "Maria": """Review catalyst, company/news event, source quality, and freshness.
Is the catalyst specific, fresh, and tradeable?
Is it a generic roundup?
Does it justify attention today?""",
        "Risk": """Review entry, stop, target, ATR, RSI, VWAP, RVOL, float rotation, fib context, ORB context, sector weakness, and R:R.
Is the entry stale or extended?
Is the setup technically valid?""",
        "Iris": """Review source lineage and historical memory.
Where did the idea come from?
Have similar setups worked or failed?
Is there a scar, killed pattern, or proven pattern?""",
        "Aegis": """Act as desk supervisor.
Synthesize all evidence.
Should this be tested now, waited on, or rejected?""",
        "Steph": """Review portfolio fit, position sizing, and diversification impact.
Does this trade make sense given current portfolio composition?""",
        "Tax": """Review tax implications for the proposed account.
Any wash sale risk? SSDI or IRMAA considerations?""",
        "Alex": """Review retirement account implications.
Is this appropriate for the account type?
Any regulatory or compliance concerns?""",
    }

    instructions = agent_instructions.get(agent_name, "Review this proposal and provide your assessment.")

    return base + f"""
{instructions}

{build_proposal_vote_json_schema()}"""


def _deterministic_review(agent_name, proposal, technical, backtest):
    """Deterministic fallback when LLM is unavailable."""
    symbol = proposal.get('symbol', '?')
    critic = proposal.get('critic_verdict')
    catalyst_verified = proposal.get('catalyst_verified', False)
    rvol = float(proposal.get('rvol') or 0)
    vs_sector = float(proposal.get('vs_sector_pct') or 0)

    concerns = []
    followups = []

    if agent_name == "Maria":
        if catalyst_verified:
            vote = "CAUTIOUS_TEST"
            confidence = 75
            summary = f"{symbol}: catalyst is company-specific, verified at {proposal.get('catalyst_confidence', 'N/A')} confidence."
        else:
            vote = "WAIT_FOR_DATA"
            confidence = 40
            summary = f"{symbol}: catalyst unverified — cannot confirm quality."
            concerns.append("Catalyst not independently verified")
            followups.append("Verify catalyst through additional sources")

    elif agent_name == "Risk":
        rsi = technical.get('rsi') if technical else None
        atr = technical.get('atr') if technical else None
        vwap_state = technical.get('vwap_state', '') if technical else ''

        if critic == 'BLOCK':
            vote = "REJECT"
            confidence = 85
            summary = f"{symbol}: critic BLOCKED — technical setup invalid."
        elif not atr and not rsi:
            vote = "WAIT_FOR_DATA"
            confidence = 30
            summary = f"{symbol}: missing ATR and RSI — cannot assess technical validity."
            concerns.append("No ATR or RSI data available")
        else:
            vote = "CAUTIOUS_TEST"
            confidence = 65
            summary = f"{symbol}: technical setup partially valid."
            if vwap_state and 'extended' in vwap_state:
                concerns.append("Entry extended above VWAP")
            if vs_sector < -5:
                concerns.append(f"Sector underperformance {vs_sector:.1f}%")

    elif agent_name == "Iris":
        bt_quality = backtest.get('backtest_quality', 'NO_DATA') if backtest else 'NO_DATA'
        sample = backtest.get('sample_size', 0) if backtest else 0

        if bt_quality in ('SUFFICIENT',):
            vote = "CAUTIOUS_TEST"
            confidence = 70
            summary = f"{symbol}: sufficient historical data ({sample} samples)."
        elif bt_quality == 'LIMITED':
            vote = "WAIT_FOR_DATA"
            confidence = 45
            summary = f"{symbol}: limited historical evidence ({sample} samples)."
            concerns.append(f"Only {sample} similar samples in local data")
        else:
            vote = "WAIT_FOR_DATA"
            confidence = 30
            summary = f"{symbol}: insufficient historical evidence."
            concerns.append("No similar setup history found")
            followups.append("Gather more data before testing")

    elif agent_name == "Aegis":
        # Synthesize: check if any hard blocks
        if critic == 'BLOCK':
            vote = "REJECT"
            confidence = 90
            summary = f"{symbol}: critic BLOCK — do not test."
        elif not catalyst_verified and rvol < 5:
            vote = "WAIT_FOR_DATA"
            confidence = 40
            summary = f"{symbol}: weak evidence — no verified catalyst, low RVOL."
        elif critic == 'DOWNGRADE' or vs_sector < -5:
            vote = "CAUTIOUS_TEST"
            confidence = 55
            summary = f"{symbol}: acceptable as paper-learning test only, not approve-ready."
            if critic == 'DOWNGRADE':
                concerns.append("Critic downgraded")
            if vs_sector < -5:
                concerns.append(f"Sector weakness {vs_sector:.1f}%")
        else:
            vote = "CAUTIOUS_TEST"
            confidence = 65
            summary = f"{symbol}: paper test acceptable."

    elif agent_name == "Steph":
        vote = "CAUTIOUS_TEST"
        confidence = 60
        summary = f"{symbol}: position sizing appears within limits for paper test."

    elif agent_name == "Tax":
        account = proposal.get('proposed_account', 'ALPACA_PAPER')
        if 'ira' in account.lower() or 'roth' in account.lower():
            vote = "CAUTIOUS_TEST"
            confidence = 50
            summary = f"{symbol}: retirement account — verify compliance before real trade."
            concerns.append("Retirement account restrictions may apply")
        else:
            vote = "NOT_APPLICABLE"
            confidence = 80
            summary = f"{symbol}: taxable paper account — no tax concerns for paper test."

    elif agent_name == "Alex":
        vote = "NOT_APPLICABLE"
        confidence = 80
        summary = f"{symbol}: retirement advisor review not required for this strategy."

    else:
        vote = "CAUTIOUS_TEST"
        confidence = 50
        summary = f"{symbol}: generic review — insufficient context for strong opinion."

    return merge_structured_into_result({
        "vote": vote,
        "confidence": confidence,
        "summary": summary,
        "concerns": concerns,
        "required_followups": followups,
    })


def review_proposal(conn, proposal_id, dry_run=False):
    """Run agent reviews for a single proposal."""
    cur = conn.cursor()

    # Load proposal
    cur.execute("""
        SELECT id, symbol, strategy_id, setup_type, proposed_entry, proposed_stop,
               proposed_target1, proposed_shares, rvol, float_m, gap_pct,
               catalyst, catalyst_verified, catalyst_confidence,
               critic_verdict, critic_confidence, critic_reasoning,
               sector, industry, proposed_account,
               technical_context, backtest_summary, stock_history_summary
        FROM paper_trade_proposals WHERE id = %s
    """, [proposal_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        return {"error": f"Proposal {proposal_id} not found"}
    proposal = dict(zip(cols, row))
    symbol = proposal['symbol']
    strategy_id = proposal.get('strategy_id') or 'unknown'

    # Get required agents
    agents = STRATEGY_AGENTS.get(strategy_id, DEFAULT_AGENTS)

    if dry_run:
        log.info(f"[dry-run] Would review {symbol} (#{proposal_id}) with agents: {agents}")
        return {"success": True, "dry_run": True, "agents": agents}

    # Load technical context
    technical = proposal.get('technical_context')
    if isinstance(technical, str):
        try:
            technical = json.loads(technical)
        except Exception:
            technical = {}

    # Load backtest
    backtest = proposal.get('backtest_summary')
    if isinstance(backtest, str):
        try:
            backtest = json.loads(backtest)
        except Exception:
            backtest = {}

    # Get LLM
    generate_fn = _get_llm()
    reviews = {}

    for agent_name in agents:
        role = AGENT_ROLES.get(agent_name, "reviewer")

        review = None
        model = "deterministic_fallback"

        if generate_fn:
            try:
                prompt = _build_agent_prompt(agent_name, proposal, technical, backtest)
                raw = generate_fn(prompt, timeout=90, fallback=True, fast=True)
                if raw:
                    review = parse_proposal_vote_result(raw, valid_votes=frozenset(VALID_VOTES))
                    if review:
                        model = _get_model_name() or "local_llm"
            except Exception as e:
                log.warning(f"LLM review failed for {agent_name}/{symbol}: {e}")

        if not review:
            review = _deterministic_review(agent_name, proposal, technical, backtest)
            model = "deterministic_fallback"

        reviews[agent_name] = review

        # Upsert into proposal_agent_reviews
        try:
            now = datetime.now(timezone.utc)
            cur.execute("""
                INSERT INTO proposal_agent_reviews
                    (proposal_id, symbol, strategy_id, agent_name, role,
                     status, vote, confidence, summary, concerns, required_followups,
                     reviewed_by_model, reviewed_at, payload)
                VALUES (%s, %s, %s, %s, %s, 'reviewed', %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id, agent_name) DO UPDATE SET
                    status = 'reviewed',
                    vote = EXCLUDED.vote,
                    confidence = EXCLUDED.confidence,
                    summary = EXCLUDED.summary,
                    concerns = EXCLUDED.concerns,
                    required_followups = EXCLUDED.required_followups,
                    reviewed_by_model = EXCLUDED.reviewed_by_model,
                    reviewed_at = EXCLUDED.reviewed_at,
                    payload = EXCLUDED.payload
            """, [
                proposal_id, symbol, strategy_id, agent_name, role,
                review["vote"], review["confidence"], review["summary"],
                json.dumps(review.get("concerns", [])),
                json.dumps(review.get("required_followups", [])),
                model, now,
                json.dumps(review, default=str),
            ])
            conn.commit()
        except Exception as e:
            log.warning(f"Failed to persist {agent_name} review: {e}")
            conn.rollback()

        log.info(f"  {agent_name}: {review['vote']} ({review['confidence']}%) — {review['summary'][:60]}")

    # Update proposal agent_review_status
    all_reviewed = all(a in reviews for a in agents)
    any_block = any(r.get('vote') == 'BLOCK' for r in reviews.values())
    any_reject = any(r.get('vote') == 'REJECT' for r in reviews.values())

    if any_block:
        status = "BLOCKED"
    elif any_reject:
        status = "REJECTED"
    elif all_reviewed:
        status = "complete"
    else:
        status = "partial"

    agent_votes = {k: {"vote": v["vote"], "confidence": v["confidence"]} for k, v in reviews.items()}

    try:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET agent_review_status = %s,
                required_reviews = %s,
                completed_reviews = %s,
                updated_at = NOW()
            WHERE id = %s
        """, [
            status,
            json.dumps(agents),
            json.dumps(list(reviews.keys())),
            proposal_id,
        ])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to update proposal {proposal_id}: {e}")
        conn.rollback()

    return {
        "success": True,
        "proposal_id": proposal_id,
        "symbol": symbol,
        "agents": agents,
        "reviews": reviews,
        "agent_review_status": status,
        "agent_votes": agent_votes,
    }


def main():
    parser = argparse.ArgumentParser(description="Proposal agent review orchestrator")
    parser.add_argument("--proposal-id", type=int)
    parser.add_argument("--all-pending", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.all_pending:
            cur = conn.cursor()
            cur.execute("SELECT id FROM paper_trade_proposals WHERE status='PENDING' ORDER BY created_at DESC")
            for (pid,) in cur.fetchall():
                result = review_proposal(conn, pid, dry_run=args.dry_run)
                if result.get('error'):
                    log.error(f"  #{pid}: {result['error']}")
        elif args.proposal_id:
            result = review_proposal(conn, args.proposal_id, dry_run=args.dry_run)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Usage: --proposal-id N or --all-pending [--dry-run]")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
