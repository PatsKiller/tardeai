"""
Gate-D D2B Live Advisory Canary — Maria + Alex paired advisory call.

This script executes EXACTLY TWO governed provider calls:
  1. Maria research_critique → FAST advisory
  2. Alex cio_synthesis → PRO CIO synthesis (with Maria live output + synthetic disagreement)

Invariants:
  - provider_calls <= 2
  - No broker mutations, no actions, no Telegram, no Hermes
  - All output is SHADOW_ADVISORY_ARTIFACT, not executable actions
  - Uses Financial Agent Governed Gateway only (no direct/OAuth fallback)

Usage:
    CIO_BRIDGE_MODE=canary LLM_GLOBAL_DAILY_USD_CAP=0.25 \
        python3 scripts/gate_d_bundle_2_advisory_canary.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root on path
_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

log = logging.getLogger("tradeai.d2b_advisory_canary")

# ── Synthetic advisory fixture (non-Maria specialists) ────────────────

SYNTHETIC_STEPH_ADVISORY = {
    "specialist_id": "steph",
    "parent_run_id": "d2b-advisory-canary-001",
    "run_purpose": "PORTFOLIO_ALLOCATION_REVIEW",
    "position": "OPPOSE",
    "recommendation": "OPPOSE current allocation. Portfolio concentration in technology (37%) exceeds IPS single-sector limit of 30%. Recommend trimming AAPL and MSFT by 3-5% each before considering any new purchases.",
    "rationale": "IPS Article IV.2 limits any single sector to 30% of portfolio. Current technology exposure at 37% breaches this constraint. This is a binding IPS constraint, not a discretionary judgment. Before the committee considers portfolio adjustments, the concentration breach must first be corrected per IPS compliance rules.",
    "evidence_sources": [
        {"source_id": "s1", "domain": "portfolio", "quality": "STALE"},
        {"source_id": "s2", "domain": "investment_policy", "quality": "AVAILABLE"},
    ],
    "evidence_summary": "Portfolio snapshot shows 37% technology (+7% above IPS cap). IPS Article IV.2 confirmed as binding.",
    "confidence": 0.92,
    "confidence_basis": "evidence_strength",
    "material_risks": [
        "IPS compliance violation (technology 37% vs 30% cap)",
        "Concentration risk amplifies drawdown vulnerability",
        "Regulatory/audit risk from documented IPS breach",
    ],
    "alternatives_considered": [
        "Allow concentration with documented override (requires operator approval)",
        "Phased trim over several weeks to minimize tax impact",
    ],
    "conditions_to_change_view": [
        {
            "condition": "Technology sector drops below 30%",
            "new_position_if_met": "SUPPORT",
            "rationale": "IPS compliance restored",
        },
        {
            "condition": "IPS amended to allow 40% technology sector",
            "new_position_if_met": "SUPPORT",
            "rationale": "Binding constraint removed by operator",
        },
    ],
    "evidence_gaps": [
        "Portfolio data is STALE (beyond freshness threshold)",
        "No live broker reconciliation to verify exact holdings",
    ],
    "deficiencies_acknowledged": True,
    "_synthetic": True,
    "_non_actionable": True,
}

SYNTHETIC_GUARDIAN_ADVISORY = {
    "specialist_id": "guardian",
    "parent_run_id": "d2b-advisory-canary-001",
    "run_purpose": "PORTFOLIO_ALLOCATION_REVIEW",
    "position": "OPPOSE",
    "recommendation": "OPPOSE. Risk envelope is already at maximum utilization (85th percentile of VaR budget). Adding or rebalancing into equities would breach the 90th-percentile VaR hard stop. Committee should consider risk-reducing adjustments only until risk utilization drops below 75%.",
    "rationale": "Current 1-day 95% VaR utilization at 85% of approved envelope (hard stop at 90%). Risk budget architecture requires buffer for adverse market moves. Any allocation that increases equity exposure would trigger automated risk stop per defense_stops_protection rules.",
    "evidence_sources": [
        {"source_id": "s1", "domain": "risk", "quality": "AVAILABLE"},
    ],
    "evidence_summary": "VaR utilization 85%, hard stop at 90%, defense stops active.",
    "confidence": 0.88,
    "confidence_basis": "evidence_strength",
    "material_risks": [
        "Risk envelope breach would trigger forced liquidation",
        "Market regime uncertainty increases tail risk",
        "No live defense_stops_protection data available",
    ],
    "alternatives_considered": [
        "Raise risk envelope (requires operator approval)",
        "Risk-neutral rebalancing only (no net increase in risk)",
    ],
    "conditions_to_change_view": [
        {
            "condition": "VaR utilization drops below 75%",
            "new_position_if_met": "NEUTRAL",
            "rationale": "Sufficient risk budget available",
        },
    ],
    "evidence_gaps": [
        "defense_stops_protection is DATA_UNAVAILABLE — stops may already be triggered",
    ],
    "deficiencies_acknowledged": True,
    "_synthetic": True,
    "_non_actionable": True,
}

SYNTHETIC_LEDGER_ADVISORY = {
    "specialist_id": "ledger",
    "parent_run_id": "d2b-advisory-canary-001",
    "run_purpose": "PORTFOLIO_ALLOCATION_REVIEW",
    "position": "DEFER",
    "recommendation": "DEFER. Insufficient tax evidence to make a qualified tax-impact recommendation. Cost-basis data is available but tax_lots and account_constraints are DATA_UNAVAILABLE. Cannot calculate wash-sale exposure or bracket impact without complete lot-level data.",
    "rationale": "Tax analysis requires lot-level cost basis, holding periods, and account type constraints. Available cost_basis is aggregate only. Missing tax_lots and account_constraints data makes any tax recommendation unreliable.",
    "evidence_sources": [
        {"source_id": "s1", "domain": "cost_basis", "quality": "AVAILABLE"},
        {"source_id": "s2", "domain": "tax_lots", "quality": "DATA_UNAVAILABLE"},
        {"source_id": "s3", "domain": "account_constraints", "quality": "DATA_UNAVAILABLE"},
    ],
    "evidence_summary": "Cost basis available at portfolio level; lot-level data and account constraints unavailable.",
    "confidence": 0.35,
    "confidence_basis": "evidence_insufficient",
    "material_risks": [
        "Unknown wash-sale exposure could create tax liability",
        "Account type unknown — tax treatment differs by account",
    ],
    "alternatives_considered": [
        "Proceed without tax analysis (accept tax uncertainty)",
        "Submit for manual tax review with broker data export",
    ],
    "conditions_to_change_view": [
        {
            "condition": "tax_lots and account_constraints become AVAILABLE",
            "new_position_if_met": "SUPPORT or OPPOSE depending on analysis",
            "rationale": "Complete tax analysis possible",
        },
    ],
    "evidence_gaps": [
        "tax_lots: DATA_UNAVAILABLE",
        "account_constraints: DATA_UNAVAILABLE",
    ],
    "deficiencies_acknowledged": True,
    "_synthetic": True,
    "_non_actionable": True,
}

SYNTHETIC_MORGAN_ADVISORY = {
    "specialist_id": "morgan",
    "parent_run_id": "d2b-advisory-canary-001",
    "run_purpose": "PORTFOLIO_ALLOCATION_REVIEW",
    "position": "SUPPORT",
    "recommendation": "CONDITIONAL SUPPORT. The overall portfolio thesis is sound and the allocation direction is consistent with long-term wealth goals. However, support is conditioned on: (1) maintaining at least 6 months of living expenses in liquid reserves, (2) no single security exceeding 15% of portfolio after adjustment, and (3) verifying that retirement timeline of 15+ years justifies equity-heavy allocation.",
    "rationale": "Wealth planning perspective: 15-year horizon supports equity exposure. The proposed adjustments would improve diversification. But liquidity constraint (6-month reserve) and concentration limits must be verified against actual cash holdings before execution.",
    "evidence_sources": [
        {"source_id": "s1", "domain": "portfolio", "quality": "STALE"},
        {"source_id": "s2", "domain": "retirement", "quality": "AVAILABLE"},
        {"source_id": "s3", "domain": "liquidity", "quality": "DATA_UNAVAILABLE"},
    ],
    "evidence_summary": "Retirement data confirms horizon; portfolio stale; liquidity unavailable.",
    "confidence": 0.65,
    "confidence_basis": "evidence_partial",
    "material_risks": [
        "Liquidity data unavailable — cannot verify reserve requirement",
        "Portfolio stale — actual holdings may differ",
    ],
    "alternatives_considered": [
        "Proceed unconditionally (violates liquidity requirement)",
        "Defer until liquidity data available",
    ],
    "conditions_to_change_view": [
        {
            "condition": "liquidity data confirms 6+ month reserve",
            "new_position_if_met": "SUPPORT",
            "rationale": "Liquidity constraint satisfied",
        },
        {
            "condition": "liquidity below 6-month reserve level",
            "new_position_if_met": "OPPOSE",
            "rationale": "Wealth planning requires adequate liquid reserves",
        },
    ],
    "evidence_gaps": [
        "liquidity: DATA_UNAVAILABLE",
        "portfolio: STALE",
    ],
    "deficiencies_acknowledged": True,
    "_synthetic": True,
    "_non_actionable": True,
}


def build_maria_prompt(run_id: str) -> tuple[list[dict], dict]:
    """Build Maria's advisory prompt with synthetic evidence context."""
    system = """You are Maria, Senior Investment Research Analyst at Trade AI. Your role is to analyze research data and provide a structured ADVISORY recommendation to Alex (Chief Investment Officer).

RULES:
1. You are an ADVISER only. You cannot execute trades or create CIO actions.
2. Your recommendation must be JUDGMENT, not a fact dump. State what you think should happen and why.
3. Link every assertion to evidence sources.
4. Identify material risks explicitly.
5. List conditions that would change your view.
6. If evidence is insufficient, state your confidence accordingly and acknowledge gaps.

OUTPUT FORMAT — return raw JSON (no markdown fences, no code blocks):
{
  "specialist_id": "maria",
  "parent_run_id": "RUN_ID_PLACEHOLDER",
  "run_purpose": "PORTFOLIO_ALLOCATION_REVIEW",
  "position": "<SUPPORT|OPPOSE|NEUTRAL|DEFER|INSUFFICIENT_EVIDENCE>",
  "recommendation": "<your advisory recommendation as a complete sentence>",
  "rationale": "<explain your reasoning, referencing evidence>",
  "evidence_sources": [{"source_id": "id", "domain": "domain_name", "quality": "AVAILABLE|PARTIAL|STALE"}],
  "evidence_summary": "<1-2 sentence summary of what the evidence shows>",
  "confidence": <float 0.0-1.0>,
  "confidence_basis": "<evidence_strength|evidence_partial|evidence_insufficient|intuition>",
  "material_risks": ["<risk 1>", "<risk 2>"],
  "alternatives_considered": ["<alternative 1>", "<alternative 2>"],
  "conditions_to_change_view": [
    {"condition": "<what would change>", "new_position_if_met": "<OPPOSE|SUPPORT|...>", "rationale": "<why>"}
  ],
  "evidence_gaps": ["<gap description>"],
  "deficiencies_acknowledged": true
}""".replace("RUN_ID_PLACEHOLDER", run_id)

    user = f"""You are reviewing a PORTFOLIO_ALLOCATION_REVIEW advisory run for the CIO committee.

Available evidence for your analysis:
- portfolio: STALE (beyond freshness threshold, but contains recent holdings data)
- investment_policy: AVAILABLE (IPS confirmed, current policy constraints apply)
- model_portfolio: AVAILABLE (target allocation model ready for comparison)
- risk: AVAILABLE (VaR and risk metrics current)
- holdings_detail: STALE (individual position data may be outdated)
- cash_buying_power: STALE, PARTIAL (derived from holdings, not verified broker)

The portfolio is equity-heavy with technology as the largest sector. Market regime data and fundamentals are unavailable.

Provide your RESEARCH CRITIQUE advisory to Alex. This is your independent judgment as an investment researcher:
- What does the research evidence tell us about the current portfolio?
- Is the allocation direction sound given the evidence you can see?
- What are the key risks you identify?
- What conditions would change your recommendation?

Remember: you are providing JUDGMENT, not just describing data."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], system


def build_alex_prompt(
    run_id: str,
    maria_live_output: dict,
    synthetic_steph: dict,
    synthetic_guardian: dict,
    synthetic_ledger: dict,
    synthetic_morgan: dict,
) -> list[dict]:
    """Build Alex's CIO synthesis prompt with all committee input."""

    # Format each specialist's position
    specialist_summaries = []
    for adv in [maria_live_output, synthetic_steph, synthetic_guardian, synthetic_ledger, synthetic_morgan]:
        sid = adv.get("specialist_id", "unknown")
        pos = adv.get("position", "?")
        rec = adv.get("recommendation", "")
        conf = adv.get("confidence", 0)
        synthetic_tag = " [SYNTHETIC FIXTURE]" if adv.get("_synthetic") else ""
        specialist_summaries.append(
            f"{sid.upper()}{synthetic_tag}: {pos} (confidence: {conf:.0%})\n  Recommendation: {rec}"
        )

    committee_input = "\n\n".join(specialist_summaries)

    system = f"""You are Alex, Chief Investment Officer of Trade AI. You receive advisory recommendations from your investment committee:
- Maria (Research Analyst): fundamental/catalyst analysis
- Steph (Portfolio Strategist): allocation, concentration, IPS compliance
- Guardian (Risk Officer): risk envelope, VaR, defense stops
- Ledger (Tax Specialist): tax-lot analysis, wash-sale checks
- Morgan (Senior Wealth Advisor): wealth planning, goal tracking, liquidity

YOUR ROLE:
1. You are NOT a vote-counter. Blind majority does not decide.
2. You MUST identify and reconcile disagreements among specialists. If Maria says SUPPORT but Guardian says OPPOSE, you must explain which concern dominates and why.
3. You MUST produce exactly ONE final CIO advisory judgment. Not a list of options.
4. Your recommendation must be JUDGMENT, not a concatenation of specialist outputs.
5. State what conditions would change your judgment.
6. Preserve evidence limitations — do not overstate confidence.
7. You RETAIN operator decision authority. Your output is advisory only.

OUTPUT FORMAT — return raw JSON (no markdown fences, no code blocks):
{{
  "final_advisory_position": "<SUPPORT|OPPOSE|NEUTRAL|DEFER|INSUFFICIENT_EVIDENCE>",
  "recommendation": "<one clear CIO recommendation>",
  "specialist_positions": {{
    "maria": "SUPPORT",
    "steph": "OPPOSE",
    "guardian": "OPPOSE",
    "ledger": "DEFER",
    "morgan": "SUPPORT"
  }},
  "material_disagreements": [
    {{
      "between": ["maria", "guardian"],
      "nature": "Maria supports allocation direction, Guardian opposes due to risk envelope",
      "resolution": "<how Alex resolved this>"
    }}
  ],
  "how_disagreements_were_resolved": "<explain your reconciliation process>",
  "actionability": "SHADOW_ADVISORY_ONLY",
  "confidence": <float 0.0-1.0>,
  "confidence_basis": "<evidence_strength|evidence_partial|evidence_insufficient>",
  "material_risks": ["<risk>"],
  "rationale_linked_to_evidence": "<full rationale>",
  "alternatives_considered": ["<alternative>"],
  "conditions_to_change_view": ["<condition>"],
  "evidence_gaps": ["<gap>"]
}}"""

    user = f"""Advisory Run: {run_id}
Purpose: PORTFOLIO_ALLOCATION_REVIEW

COMMITTEE ADVISORY INPUT:

{committee_input}

Alex, you have received advisory input from all five committee members. Note that:
- Only Maria's advisory was live-generated; the other four are synthetic committee fixtures.
- There is clear DISAGREEMENT: the committee is split with multiple OPPOSE positions.
- Guardian's risk concerns are structural (VaR at 85%)
- Steph's IPS compliance concern is binding (technology at 37% vs 30% cap)
- Ledger is unable to provide tax guidance due to data unavailability
- Morgan is conditionally supportive with liquidity constraints

Synthesize these inputs into your single CIO advisory recommendation. You must explicitly reconcile the disagreement, not simply report the vote count. This is a SHADOW advisory — no executable actions are authorized."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def main():
    log.info("=" * 60)
    log.info("GATE-D BUNDLE 2 — LIVE ADVISORY CANARY")
    log.info("=" * 60)

    # Validate mode
    mode = os.environ.get("CIO_BRIDGE_MODE", "mock")
    if mode != "canary":
        log.error("CIO_BRIDGE_MODE must be 'canary' for live calls. Current: %s", mode)
        log.error("Set: CIO_BRIDGE_MODE=canary")
        sys.exit(1)

    cap = os.environ.get("LLM_GLOBAL_DAILY_USD_CAP", "")
    if not cap:
        log.warning("LLM_GLOBAL_DAILY_USD_CAP not set. Will default to bridge's internal cap.")

    log.info("Mode: %s | Global cap: %s", mode, cap or "(default)")

    # Import governed bridge (after env vars are set)
    from scripts.lib.cio_governed_model_bridge import execute_governed_call

    run_id = f"d2b-advisory-canary-{uuid.uuid4().hex[:8]}"
    log.info("Canary run_id: %s", run_id)

    # ── Step 1: Maria advisory call ──────────────────────────────────
    log.info("--- Step 1: Maria Research Critique (FAST) ---")
    maria_messages, _ = build_maria_prompt(run_id)

    t0 = datetime.now(timezone.utc)
    maria_result = execute_governed_call(
        maria_messages,
        process_id="maria_research_critique",
        max_tokens=4096,
        request_id=f"{run_id}-maria",
    )
    maria_latency = (datetime.now(timezone.utc) - t0).total_seconds()

    if "error" in maria_result:
        log.error("Maria call FAILED: %s", maria_result["error"].get("message", "unknown"))
        print("\nMARIA ERROR:", json.dumps(maria_result["error"], indent=2))
        print("\nCANARY: PROVIDER_BLOCKED — Maria call failed. Canary is FAILED.")
        sys.exit(1)

    maria_content = maria_result.get("choices", [{}])[0].get("message", {}).get("content", "")
    maria_usage = maria_result.get("usage", {})
    maria_cost = maria_result.get("_tradeai", {}).get("cost", {})

    log.info("Maria call: %d tokens, latency=%0.1fs", 
             maria_usage.get("total_tokens", 0), maria_latency)

    # Parse Maria's JSON output
    try:
        # Strip any markdown fences
        cleaned = maria_content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        maria_advisory = json.loads(cleaned)
        log.info("Maria position: %s confidence: %0.2f", 
                 maria_advisory.get("position", "?"), 
                 maria_advisory.get("confidence", 0))
        print("\n=== MARIA ADVISORY ===")
        print(json.dumps(maria_advisory, indent=2))
    except json.JSONDecodeError as e:
        log.error("Could not parse Maria output as JSON: %s", e)
        print("\nMARIA RAW OUTPUT:", maria_content[:500])
        print("\nCANARY: FAILED — Maria output not valid JSON advisory.")
        sys.exit(1)

    # Validate Maria's advisory
    if maria_advisory.get("position") in ("NEUTRAL",):
        log.warning("Maria position is NEUTRAL — not a strong advisory signal")
    if not maria_advisory.get("recommendation"):
        log.error("Maria advisory missing recommendation field")

    # ── Step 2: Alex CIO synthesis call ──────────────────────────────
    log.info("--- Step 2: Alex CIO Synthesis (PRO) ---")
    alex_messages = build_alex_prompt(
        run_id,
        maria_advisory,
        SYNTHETIC_STEPH_ADVISORY,
        SYNTHETIC_GUARDIAN_ADVISORY,
        SYNTHETIC_LEDGER_ADVISORY,
        SYNTHETIC_MORGAN_ADVISORY,
    )

    t0 = datetime.now(timezone.utc)
    alex_result = execute_governed_call(
        alex_messages,
        process_id="alex_cio_synthesis",
        max_tokens=4096,
        request_id=f"{run_id}-alex",
    )
    alex_latency = (datetime.now(timezone.utc) - t0).total_seconds()

    if "error" in alex_result:
        log.error("Alex call FAILED: %s", alex_result["error"].get("message", "unknown"))
        print("\nALEX ERROR:", json.dumps(alex_result["error"], indent=2))
        print("\nCANARY: PROVIDER_BLOCKED — Alex call failed. Maria call succeeded but overall canary is FAILED.")
        sys.exit(1)

    alex_content = alex_result.get("choices", [{}])[0].get("message", {}).get("content", "")
    alex_usage = alex_result.get("usage", {})
    alex_cost = alex_result.get("_tradeai", {}).get("cost", {})

    log.info("Alex call: %d tokens, latency=%0.1fs",
             alex_usage.get("total_tokens", 0), alex_latency)

    # Parse Alex's JSON output
    try:
        cleaned = alex_content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        alex_advisory = json.loads(cleaned)
        log.info("Alex position: %s confidence: %0.2f",
                 alex_advisory.get("final_advisory_position", "?"),
                 alex_advisory.get("confidence", 0))
        print("\n=== ALEX CIO ADVISORY ===")
        print(json.dumps(alex_advisory, indent=2))
    except json.JSONDecodeError as e:
        log.error("Could not parse Alex output as JSON: %s", e)
        print("\nALEX RAW OUTPUT:", alex_content[:500])
        print("\nCANARY: FAILED — Alex output not valid JSON advisory.")
        sys.exit(1)

    # ── Canary assessment ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CANARY ASSESSMENT")

    # Check Maria's advisory quality
    maria_ok = True
    if maria_advisory.get("_synthetic"):
        log.error("Maria returned _synthetic flag — model may have copied the fixture pattern")
        maria_ok = False
    if not maria_advisory.get("recommendation"):
        log.error("Maria missing recommendation")
        maria_ok = False
    if not maria_advisory.get("material_risks"):
        log.error("Maria missing material_risks")
        maria_ok = False
    if not maria_advisory.get("conditions_to_change_view"):
        log.error("Maria missing conditions_to_change_view")
        maria_ok = False
    if not maria_advisory.get("deficiencies_acknowledged"):
        log.warning("Maria did not acknowledge deficiencies")

    # Check Alex's quality
    alex_ok = True
    if not alex_advisory.get("material_disagreements"):
        log.error("Alex did not identify material disagreements — BLIND VOTE")
        alex_ok = False
    if not alex_advisory.get("how_disagreements_were_resolved"):
        log.error("Alex did not explain disagreement resolution")
        alex_ok = False
    if not alex_advisory.get("recommendation"):
        log.error("Alex missing recommendation")
        alex_ok = False
    if alex_advisory.get("actionability") != "SHADOW_ADVISORY_ONLY":
        log.error("Alex actionability is not SHADOW_ADVISORY_ONLY: %s", alex_advisory.get("actionability"))

    total_tokens = maria_usage.get("total_tokens", 0) + alex_usage.get("total_tokens", 0)

    # ── Store canary output ──────────────────────────────────────────
    output = {
        "canary_type": "D2B_FIRST_LIVE_ADVISORY",
        "run_id": run_id,
        "synthetic": True,
        "shadow": True,
        "non_actionable": True,
        "not_operator_financial_advice": True,
        "canonical_CIO_action": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider_calls": 2,
        "total_tokens": total_tokens,
        "maria": {
            "process_id": "maria_research_critique",
            "policy": "FAST",
            "valid_json": True,
            "position": maria_advisory.get("position"),
            "confidence": maria_advisory.get("confidence"),
            "latency_s": maria_latency,
            "tokens": maria_usage,
        },
        "alex": {
            "process_id": "alex_cio_synthesis",
            "policy": "PRO",
            "valid_json": True,
            "position": alex_advisory.get("final_advisory_position"),
            "confidence": alex_advisory.get("confidence"),
            "latency_s": alex_latency,
            "tokens": alex_usage,
            "material_disagreements": len(alex_advisory.get("material_disagreements", [])),
            "blind_majority_vote": not alex_ok,
        },
        "invariants": {
            "CIO_action_writes": 0,
            "Telegram_live_sends": 0,
            "broker_mutations": 0,
            "specialist_promotions": 0,
            "Hermes_challenges": 0,
        },
    }

    canary_dir = Path("data/cio/canary")
    canary_dir.mkdir(parents=True, exist_ok=True)
    canary_path = canary_dir / "d2b_advisory_canary_output.json"
    canary_path.write_text(json.dumps(output, indent=2, default=str))
    log.info("Canary output saved to %s", canary_path)

    print(f"\nTotal tokens: {total_tokens}")
    print(f"Maria: {maria_advisory.get('position', '?')} ({maria_advisory.get('confidence', 0):.0%})")
    print(f"Alex:  {alex_advisory.get('final_advisory_position', '?')} ({alex_advisory.get('confidence', 0):.0%})")
    print(f"Maria advisory OK: {maria_ok}")
    print(f"Alex advisory OK: {alex_ok}")

    if maria_ok and alex_ok:
        print("\nCANARY VERDICT: PASS — advisory pipeline proven with 2 governed calls.")
    else:
        print(f"\nCANARY VERDICT: PARTIAL — Maria={maria_ok}, Alex={alex_ok}")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    main()
