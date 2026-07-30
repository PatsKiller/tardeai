#!/usr/bin/env python3
"""proposal_decision_gate.py — Decision state engine for paper proposals.

Computes the approval decision state based on research packet data.

Decision states:
    APPROVE_READY_PAPER_TEST
    CAUTIOUS_PAPER_TEST
    RESEARCH_INCOMPLETE
    AI_REVIEW_MISSING
    DATA_STALE
    BACKTEST_INSUFFICIENT
    REJECT_RECOMMENDED
    BLOCKED_BY_RISK_GATE
"""
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("decision_gate")


def _first_sample_override(proposal) -> bool:
    """Explicit opt-in for approving a BACKTEST_INSUFFICIENT proposal as a
    deliberate first-sample learning test. OFF by default (no hardcoded bypass):
    a truthy per-proposal ``allow_first_sample_override`` field, or the
    ``PROPOSAL_ALLOW_FIRST_SAMPLE_OVERRIDE`` env switch."""
    val = (proposal or {}).get("allow_first_sample_override")
    if isinstance(val, str):
        val = val.strip().lower() in ("1", "true", "yes", "on")
    if val:
        return True
    return os.getenv("PROPOSAL_ALLOW_FIRST_SAMPLE_OVERRIDE", "").strip().lower() \
        in ("1", "true", "yes", "on")


def compute_decision_state(proposal, technical, backtest, agent_reviews,
                           agent_votes, llm_review, risk_gate):
    """Compute the decision state for a proposal.

    Returns dict with decision_state, reasons, approval_allowed.
    """
    reasons = []
    decision_state = "RESEARCH_INCOMPLETE"

    # Extract values
    research_score = float(proposal.get('research_score') or 0)
    confidence_score = float(proposal.get('confidence_score') or 0)
    entry = float(proposal.get('proposed_entry') or 0)
    rr = float(proposal.get('proposed_rr') or 0)
    critic_verdict = proposal.get('critic_verdict')
    catalyst_verified = proposal.get('catalyst_verified', False)
    catalyst = proposal.get('catalyst')

    # Technical data
    atr = technical.get('atr') if technical else None
    rsi = technical.get('rsi') if technical else None
    vwap_state = technical.get('vwap_state', '') if technical else ''
    price_vs_entry = technical.get('price_vs_entry_pct') if technical else None

    # Backtest data
    bt_quality = backtest.get('backtest_quality', 'NO_DATA') if backtest else 'NO_DATA'
    bt_samples = backtest.get('sample_size', 0) if backtest else 0

    # Agent data
    required_agents = proposal.get('required_reviews')
    if isinstance(required_agents, str):
        try: required_agents = json.loads(required_agents)
        except: required_agents = []
    completed_agents = proposal.get('completed_reviews')
    if isinstance(completed_agents, str):
        try: completed_agents = json.loads(completed_agents)
        except: completed_agents = []

    agent_review_status = proposal.get('agent_review_status', '')

    # 1. BLOCKED_BY_RISK_GATE — highest priority
    if not risk_gate.get('approved', True):
        result = risk_gate.get('result', 'REJECTED')
        if result not in ('APPROVED',):
            decision_state = "BLOCKED_BY_RISK_GATE"
            reasons.append(f"Risk gate: {result} — {', '.join(risk_gate.get('reason_codes', []))}")
            return {
                "decision_state": decision_state,
                "reasons": reasons,
                "approval_allowed": False,
            }

    # 2. REJECT_RECOMMENDED
    reject_reasons = []
    if critic_verdict == 'BLOCK':
        reject_reasons.append("Critic BLOCKED")
    if rr < 1.2 and rr > 0:
        reject_reasons.append(f"R:R too low ({rr:.2f})")
    if not catalyst_verified and not catalyst:
        reject_reasons.append("No catalyst")

    # Check agent blocks
    for name, v in (agent_votes or {}).items():
        vote = v.get('vote') if isinstance(v, dict) else v
        if vote == 'BLOCK':
            reject_reasons.append(f"{name} BLOCKED")
        elif vote == 'REJECT':
            reject_reasons.append(f"{name} REJECTED")

    # Sector check
    vs_sector = float(proposal.get('vs_sector_pct') or 0)
    if vs_sector < -10 and not (atr or rsi):
        reject_reasons.append(f"Severe sector underperformance ({vs_sector:.1f}%) with no technical confirmation")

    if len(reject_reasons) >= 2 or any('BLOCK' in r for r in reject_reasons):
        decision_state = "REJECT_RECOMMENDED"
        reasons.extend(reject_reasons)
        return {"decision_state": decision_state, "reasons": reasons, "approval_allowed": False}

    # 3. AI_REVIEW_MISSING
    if required_agents and completed_agents:
        missing_agents = [a for a in required_agents if a not in (completed_agents or [])]
        if missing_agents:
            decision_state = "AI_REVIEW_MISSING"
            reasons.append(f"Missing agent reviews: {', '.join(missing_agents)}")
            llm_status = proposal.get('local_llm_review_status', '')
            if not llm_status or llm_status == 'unavailable':
                reasons.append("Local LLM review not run")
            return {"decision_state": decision_state, "reasons": reasons, "approval_allowed": False}
    elif not agent_review_status or agent_review_status in ('', 'pending'):
        # No reviews at all yet
        decision_state = "AI_REVIEW_MISSING"
        reasons.append("No agent reviews completed yet")
        return {"decision_state": decision_state, "reasons": reasons, "approval_allowed": False}

    # 4. DATA_STALE
    if technical and technical.get('scan_timestamp'):
        try:
            scan_ts = datetime.fromisoformat(str(technical['scan_timestamp']).replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - scan_ts).total_seconds() / 3600
            if age_hours > 2:
                reasons.append(f"Scan data is {age_hours:.1f} hours old")
                if price_vs_entry and abs(float(price_vs_entry)) > 3:
                    reasons.append(f"Price moved {price_vs_entry:+.1f}% from entry")
                    decision_state = "DATA_STALE"
                    return {"decision_state": decision_state, "reasons": reasons, "approval_allowed": False}
                elif age_hours > 4:
                    decision_state = "DATA_STALE"
                    return {"decision_state": decision_state, "reasons": reasons, "approval_allowed": False}
        except Exception:
            pass

    # 5. RESEARCH_INCOMPLETE
    if research_score < 75:
        decision_state = "RESEARCH_INCOMPLETE"
        reasons.append(f"Research score {research_score}/100 below threshold (75)")
        if not technical or not technical.get('rsi'):
            reasons.append("Technical snapshot missing")
        return {"decision_state": decision_state, "reasons": reasons, "approval_allowed": False}

    # 6. BACKTEST_INSUFFICIENT — thin evidence must NOT silently reach approval.
    # The deliberate "first-sample learning test" path is preserved, but it is
    # now opt-in (see _first_sample_override); default is approval BLOCKED.
    if bt_quality in ('NO_DATA', 'INSUFFICIENT') and bt_samples < 10:
        decision_state = "BACKTEST_INSUFFICIENT"
        reasons.append(f"Backtest: {bt_quality} ({bt_samples} samples)")
        override = _first_sample_override(proposal)
        if override:
            reasons.append("First-sample learning-test override active — approval allowed")
        else:
            reasons.append("Thin backtest evidence — approval blocked "
                           "(set allow_first_sample_override to run as a first-sample test)")
        return {"decision_state": decision_state, "reasons": reasons,
                "approval_allowed": bool(override)}

    # 7. APPROVE_READY_PAPER_TEST vs CAUTIOUS_PAPER_TEST
    cautious_reasons = []

    if critic_verdict == 'DOWNGRADE':
        cautious_reasons.append("Critic downgraded")
    if vs_sector < -5:
        cautious_reasons.append(f"Sector underperformance ({vs_sector:.1f}%)")
    if bt_quality == 'LIMITED':
        cautious_reasons.append("Backtest limited")
    if research_score < 85:
        cautious_reasons.append(f"Research score {research_score}/100")
    if confidence_score < 75:
        cautious_reasons.append(f"Confidence {confidence_score}/100")
    if price_vs_entry is not None and abs(float(price_vs_entry)) > 1:
        cautious_reasons.append(f"Price {float(price_vs_entry):+.1f}% from entry")

    # Check for cautious agent votes
    for name, v in (agent_votes or {}).items():
        vote = v.get('vote') if isinstance(v, dict) else v
        if vote == 'WAIT_FOR_DATA':
            cautious_reasons.append(f"{name} voted WAIT_FOR_DATA")
        elif vote == 'CAUTIOUS_TEST':
            pass  # fine for both states

    if not cautious_reasons:
        # Check all APPROVE_READY requirements
        approve_ready = True
        if not risk_gate.get('approved', True):
            approve_ready = False
        if research_score < 85:
            approve_ready = False
        if confidence_score < 75:
            approve_ready = False
        if rr < 1.5:
            approve_ready = False
            cautious_reasons.append(f"R:R {rr:.2f} below 1.5")
        if not catalyst_verified and not (catalyst and float(proposal.get('catalyst_confidence') or 0) > 0.8):
            approve_ready = False
            cautious_reasons.append("Catalyst not verified")

        # Check Maria/Risk/Aegis not reject/block
        for critical_agent in ('Maria', 'Risk', 'Aegis'):
            v = (agent_votes or {}).get(critical_agent, {})
            vote = v.get('vote') if isinstance(v, dict) else None
            if vote in ('REJECT', 'BLOCK'):
                approve_ready = False
                cautious_reasons.append(f"{critical_agent} {vote}")

        if approve_ready:
            decision_state = "APPROVE_READY_PAPER_TEST"
            return {"decision_state": decision_state, "reasons": ["All checks passed"], "approval_allowed": True}

    decision_state = "CAUTIOUS_PAPER_TEST"
    return {
        "decision_state": decision_state,
        "reasons": cautious_reasons if cautious_reasons else ["Acceptable as cautious paper test"],
        "approval_allowed": True,
    }
