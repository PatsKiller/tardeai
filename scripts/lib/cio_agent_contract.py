"""cio_agent_contract.py — Shared CIO agent v2 JSON contract (fleet parity).

Extracted from process_watchlist_agent_jobs.py (Stage 2b, 2026-07-02) for reuse across
CIO watchlist agents, proposal review, and portfolio analysis pipelines.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

AGENT_JSON_CONTRACT_VERSION = "cio_agent_v2_structured_evidence_2026-07-02"
EVIDENCE_TAGS = frozenset({"fact", "technical", "risk"})

GLOBAL_RULES_G1_G10 = """=== GLOBAL RULES (mandatory — apply to every analysis) ===
G1 DATA FRESHNESS: Never analyze with stale data (news >7d, prices >24h, SEC >30d, FRED >7d). If stale: log stale_data, skip, no recommendation.
G2 INCOME PROTECTION: NEVER recommend TRIM/SELL on positions where yield × market_value > $11,000/yr or strategies: dividend_growth_compounder, high_yield_income_bdc, tactical_income. If blocked: escalate to Alex with INCOME_CRITICAL.
G3 SSDI AWARENESS: For IRA/401k positions include: MAGI impact estimate, IRMAA flag if MAGI >$103K (MFS), bracket flag if >$94,300, Medicaid lookback flag if distribution >$50K. If any flag: set ssdi_review=true.
G4 CONFIDENCE GATING: If confidence <40%: output LOW_CONFIDENCE_SKIP. If only 1 source: skip. Decisions >14 days old: expire.
G5 LEARNING LOOP: Read outcome lessons below and adjust confidence ±0.05 per past approval/rejection.
G6 MACRO CONTEXT: Check FRED data in context. VIX >25: elevated volatility. T10Y2Y <0: recession risk. DFF >5%: bonds competitive. DFF <2%: equity premium.
G7 ESCALATION: Auto-escalate to Alex when: agent conflict (BUY vs SELL same symbol 48h), any Roth conversion rec, income-critical flag, confidence 40-60% on portfolio position.
G10 NO DIRECT EXECUTION: No trade executes without human approval.
=== END GLOBAL RULES ==="""

PROPOSAL_GLOBAL_RULES = """=== GLOBAL RULES (paper proposals) ===
G1 DATA FRESHNESS: Flag stale inputs (news >7d, prices >24h, indicators missing) in data_i_doubt; lower confidence.
G4 CONFIDENCE GATING: If confidence <40% or only one weak source: vote WAIT_FOR_DATA.
G10 NO DIRECT EXECUTION: Analysis only — human approves all paper/live trades.
=== END GLOBAL RULES ==="""

_EVIDENCE_FIELDS_DOC = """- "evidence": array of 3-5 objects — each {"tag": "fact"|"technical"|"risk", "text": "specific verifiable claim"} (fact=ownership/catalyst/SEC; technical=RSI/MA/support; risk=stop/heat/concentration)
- "data_i_doubt": string — which inputs may be stale, missing, or unreliable (use "none" if confident)"""


def contract_header() -> str:
    return f"[agent_contract: {AGENT_JSON_CONTRACT_VERSION}]"


def build_evidence_fields_doc() -> str:
    return _EVIDENCE_FIELDS_DOC


def build_base_json_instruction(
    *,
    context: str = "",
    include_global_rules: bool = True,
    global_rules: Optional[str] = None,
    extra_fields: Optional[List[str]] = None,
) -> str:
    """CIO watchlist agent JSON contract block (maria/steph/risk/tax/full_chain)."""
    rules = (global_rules or GLOBAL_RULES_G1_G10) if include_global_rules else ""
    fields = [
        '- "summary": 1-2 sentence executive summary',
        '- "full_narrative": detailed 3-5 paragraph analysis (this is the primary output)',
        '- "recommendation": one of BUY, HOLD, AVOID, ADD, TRIM, SELL, NEUTRAL, RESEARCH_MORE',
        '- "confidence": decimal 0.0-1.0',
        _EVIDENCE_FIELDS_DOC,
        '- "reason_codes": array of short reason tags (e.g. ["strong_dividend", "overvalued", "technical_support"])',
        '- "next_action": what should happen next',
    ]
    if extra_fields:
        fields.extend(extra_fields)
    parts = [
        contract_header(),
        "Respond in JSON format with these fields:",
        *fields,
    ]
    if rules:
        parts.append(rules)
    if context:
        parts.append(f"Context:\n{context}")
    return "\n".join(parts)


def build_proposal_vote_json_schema() -> str:
    return (
        f'{contract_header()}\n'
        f"{PROPOSAL_GLOBAL_RULES}\n"
        "Answer as JSON:\n"
        '{"vote":"APPROVE_TEST|CAUTIOUS_TEST|WAIT_FOR_DATA|REJECT|BLOCK",'
        '"confidence":0-100,"summary":"...",'
        '"concerns":["..."],'
        '"required_followups":["..."],'
        '"evidence":[{"tag":"fact|technical|risk","text":"..."}],'
        '"data_i_doubt":"none or specific stale/missing inputs"}'
    )


def build_proposal_intelligence_json_schema() -> str:
    return (
        f'{contract_header()}\n'
        f"{PROPOSAL_GLOBAL_RULES}\n"
        "Answer as JSON:\n"
        '{"setup_narrative":"what this trade is and why it exists (reference numbers)",'
        '"strategy_fit_assessment":"how well setup matches strategy criteria",'
        '"technical_assessment":"RSI/VWAP/ATR interpretation for this specific setup",'
        '"catalyst_assessment":"catalyst quality and expected duration",'
        '"risk_assessment":"what could go wrong, be specific",'
        '"kill_conditions":["condition 1 that invalidates in first 30-60 min","condition 2"],'
        '"approve_case":"bull case with numbers",'
        '"reject_case":"bear case with numbers",'
        '"verdict":"APPROVE_PAPER_TEST or CAUTIOUS_PAPER_TEST or REJECT",'
        '"conviction":"HIGH or MEDIUM or LOW",'
        '"confidence":0.0-1.0,'
        '"evidence":[{"tag":"fact|technical|risk","text":"..."}],'
        '"data_i_doubt":"none or specific stale/missing inputs"}'
    )


def build_portfolio_brief_json_schema() -> str:
    return (
        f'{contract_header()}\n'
        f"{GLOBAL_RULES_G1_G10}\n"
        "Answer as JSON:\n"
        '{"summary":"2-3 sentence portfolio health summary",'
        '"key_actions":"single most important action item",'
        '"watch_holdings":[{"symbol":"TICKER","status":"WATCH|CONCERN|OK","reason":"..."}],'
        '"news_impacts":[{"symbol":"TICKER","impact":"..."}],'
        '"evidence":[{"tag":"fact|technical|risk","text":"..."}],'
        '"data_i_doubt":"none or specific stale/missing inputs"}'
    )


def build_llm_chunk_evidence_footer() -> str:
    """Append to proposal LLM chunk prompts for structured evidence parity."""
    return (
        f"\n{contract_header()}\n"
        f"Also include in your JSON: {_EVIDENCE_FIELDS_DOC}\n"
        f"{PROPOSAL_GLOBAL_RULES}"
    )


def extract_json_object(raw: str) -> Optional[dict]:
    if not raw:
        return None
    for start_char in ("{", "```json\n{", "```\n{"):
        idx = raw.find(start_char)
        if idx < 0:
            continue
        end = raw.rfind("}")
        if end <= idx:
            continue
        candidate = raw[idx : end + 1]
        if candidate.startswith("```"):
            candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def normalize_evidence(raw) -> list:
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw[:5]:
        if isinstance(item, dict):
            tag = str(item.get("tag") or "fact").lower().strip()
            text = str(item.get("text") or "").strip()
            if tag not in EVIDENCE_TAGS:
                tag = "fact"
        elif isinstance(item, str) and item.strip():
            tag, text = "fact", item.strip()
        else:
            continue
        if text:
            out.append({"tag": tag, "text": text[:300]})
    return out


def normalize_data_i_doubt(raw) -> str:
    if raw is None:
        return "none"
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw if str(x).strip()]
        return "; ".join(parts)[:500] if parts else "none"
    s = str(raw).strip()
    return s[:500] if s else "none"


def merge_structured_into_result(base: dict) -> dict:
    """Ensure agent_contract + normalized evidence fields on any parsed result."""
    out = dict(base)
    out["agent_contract"] = AGENT_JSON_CONTRACT_VERSION
    out["evidence"] = normalize_evidence(out.get("evidence"))
    out["data_i_doubt"] = normalize_data_i_doubt(out.get("data_i_doubt"))
    return out


def format_evidence_for_synthesis(parsed: dict) -> str:
    lines = []
    for ev in parsed.get("evidence") or []:
        lines.append(f"  - [{ev.get('tag', 'fact')}] {ev.get('text', '')}")
    doubt = parsed.get("data_i_doubt") or "none"
    block = ""
    if lines:
        block += "Structured evidence:\n" + "\n".join(lines) + "\n"
    if doubt and doubt.lower() != "none":
        block += f"Data doubt: {doubt}\n"
    return block


def parse_agent_result(raw: str) -> dict:
    """Parse CIO watchlist agent LLM response (recommendation vocabulary)."""
    parsed = extract_json_object(raw)
    if parsed and "recommendation" in parsed:
        return {
            "summary": str(parsed.get("summary", ""))[:500],
            "full_narrative": str(parsed.get("full_narrative", parsed.get("summary", "")))[:3000],
            "recommendation": str(parsed.get("recommendation", "RESEARCH_MORE")).upper(),
            "confidence": min(1.0, max(0.0, float(parsed.get("confidence", 0.5)))),
            "evidence": normalize_evidence(parsed.get("evidence")),
            "data_i_doubt": normalize_data_i_doubt(parsed.get("data_i_doubt")),
            "reason_codes": parsed.get("reason_codes", []) if isinstance(parsed.get("reason_codes"), list) else [],
            "next_action": str(parsed.get("next_action", ""))[:200],
            "agent_contract": AGENT_JSON_CONTRACT_VERSION,
        }

    summary = (raw or "")[:300]
    full_narrative = (raw or "")[:3000]
    recommendation = "RESEARCH_MORE"
    confidence = 0.5
    reason_codes = []

    for line in (raw or "").split("\n"):
        l = line.lower()
        if "recommend" in l:
            for r in ("STRONG_BUY", "BUY", "HOLD", "AVOID", "TRIM", "ADD", "SELL", "NEUTRAL", "RESEARCH_MORE"):
                if r.lower() in l:
                    recommendation = r
                    break
        if "confidence" in l:
            m = re.search(r"(\d+\.?\d*)", l)
            if m:
                v = float(m.group(1))
                confidence = v if v <= 1 else v / 100

    return {
        "summary": summary,
        "full_narrative": full_narrative,
        "recommendation": recommendation,
        "confidence": confidence,
        "evidence": [],
        "data_i_doubt": "none",
        "reason_codes": reason_codes,
        "next_action": "",
        "agent_contract": AGENT_JSON_CONTRACT_VERSION,
    }


def parse_proposal_vote_result(raw: str, valid_votes: Optional[frozenset] = None) -> Optional[dict]:
    parsed = extract_json_object(raw)
    if not parsed:
        return None
    vote = str(parsed.get("vote", "CAUTIOUS_TEST")).upper()
    if valid_votes and vote not in valid_votes:
        vote = "CAUTIOUS_TEST"
    return merge_structured_into_result({
        "vote": vote,
        "confidence": min(100, max(0, int(parsed.get("confidence", 50)))),
        "summary": str(parsed.get("summary", ""))[:500],
        "concerns": parsed.get("concerns", []) if isinstance(parsed.get("concerns"), list) else [],
        "required_followups": parsed.get("required_followups", []) if isinstance(parsed.get("required_followups"), list) else [],
        "evidence": parsed.get("evidence"),
        "data_i_doubt": parsed.get("data_i_doubt"),
    })


def parse_proposal_intelligence_result(raw: str) -> Optional[dict]:
    parsed = extract_json_object(raw)
    if not parsed:
        return None
    kill = parsed.get("kill_conditions", [])
    if not isinstance(kill, list):
        kill = []
    out = merge_structured_into_result({
        "setup_narrative": str(parsed.get("setup_narrative", ""))[:800],
        "strategy_fit_assessment": str(parsed.get("strategy_fit_assessment", ""))[:500],
        "technical_assessment": str(parsed.get("technical_assessment", ""))[:500],
        "catalyst_assessment": str(parsed.get("catalyst_assessment", ""))[:500],
        "risk_assessment": str(parsed.get("risk_assessment", ""))[:500],
        "kill_conditions": kill[:5],
        "approve_case": str(parsed.get("approve_case", ""))[:500],
        "reject_case": str(parsed.get("reject_case", ""))[:500],
        "verdict": str(parsed.get("verdict", ""))[:40],
        "conviction": str(parsed.get("conviction", ""))[:20],
        "confidence": min(1.0, max(0.0, float(parsed.get("confidence", 0.5)))),
        "summary": str(parsed.get("summary") or parsed.get("setup_narrative", ""))[:500],
        "invalidation": "; ".join(kill[:3]) if kill else "",
        "evidence": parsed.get("evidence"),
        "data_i_doubt": parsed.get("data_i_doubt"),
    })
    return out


def parse_portfolio_brief_result(raw: str) -> Optional[dict]:
    parsed = extract_json_object(raw)
    if not parsed:
        return None
    watch = parsed.get("watch_holdings", [])
    news = parsed.get("news_impacts", [])
    if not isinstance(watch, list):
        watch = []
    if not isinstance(news, list):
        news = []
    return merge_structured_into_result({
        "summary": str(parsed.get("summary", ""))[:800],
        "key_actions": str(parsed.get("key_actions", ""))[:400],
        "watch_holdings": watch[:8],
        "news_impacts": news[:8],
        "evidence": parsed.get("evidence"),
        "data_i_doubt": parsed.get("data_i_doubt"),
    })


def format_portfolio_brief_display(parsed: dict) -> str:
    """Render structured portfolio brief JSON as readable prose for the UI."""
    parts = []
    if parsed.get("summary"):
        parts.append(parsed["summary"])
    if parsed.get("news_impacts"):
        parts.append("\nKey news impacts:")
        for item in parsed["news_impacts"]:
            if isinstance(item, dict):
                parts.append(f"  • {item.get('symbol', '?')}: {item.get('impact', '')}")
    if parsed.get("watch_holdings"):
        parts.append("\nHoldings flagged:")
        for item in parsed["watch_holdings"]:
            if isinstance(item, dict):
                parts.append(f"  • {item.get('symbol', '?')} [{item.get('status', '?')}]: {item.get('reason', '')}")
    if parsed.get("key_actions"):
        parts.append(f"\nPriority action: {parsed['key_actions']}")
    ev_block = format_evidence_for_synthesis(parsed)
    if ev_block.strip():
        parts.append("\n" + ev_block.strip())
    return "\n".join(parts).strip() or str(parsed.get("summary", ""))