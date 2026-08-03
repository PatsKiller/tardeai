#!/usr/bin/env python3
"""alex_hygiene.py — Three-tier decision hygiene for Alex.

Tier 1 (routine, ~$0.01): Alex alone (Sonnet)
Tier 2 (significant, ~$0.03): Alex + Grok second opinion
Tier 3 (critical, ~$0.15): Alex + Grok + GPT-4o → Opus synthesis

Usage:
    python3 scripts/alex_hygiene.py --classify "Should I set up a pooled SNT?"
    python3 scripts/alex_hygiene.py --run "Monthly Roth review" --type monthly_planning_report
"""
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

TIER_1 = "tier1_routine"
TIER_2 = "tier2_significant"
TIER_3 = "tier3_critical"

DECISION_TIERS = {
    "weekly_health_check": TIER_1, "daily_magi_monitor": TIER_1,
    "stop_triggered_review": TIER_1, "dividend_income_update": TIER_1,
    "portfolio_position_review": TIER_1, "news_analysis": TIER_1,
    "annual_roth_conversion": TIER_2, "irmaa_threshold_approaching": TIER_2,
    "portfolio_rebalance_tax": TIER_2, "tax_loss_harvesting": TIER_2,
    "medicare_plan_change": TIER_2,
    "trust_establishment": TIER_3, "special_needs_trust_pooled": TIER_3,
    "able_account_setup": TIER_3, "large_roth_conversion": TIER_3,
    "medicaid_strategy_change": TIER_3, "estate_planning_decision": TIER_3,
    "ssdi_strategy_change": TIER_3, "ira_large_distribution": TIER_3,
    "beneficiary_designation": TIER_3, "monthly_planning_report": TIER_3,
    "quarterly_strategy_review": TIER_3,
}

TIER3_KEYWORDS = [
    "trust", "snt", "special needs", "pooled trust", "able account",
    "medicaid planning", "irrevocable", "estate plan", "beneficiary",
    "probate", "large conversion", "ssdi strategy", "elder law",
    "5-year lookback", "asset protection",
]

TIER3_BYPASS = ["new_law_passed", "irmaa_threshold_crossed", "medicaid_resource_limit_hit",
                "trust_action_required", "large_unexpected_income", "inheritance_received"]

TIER_META = {
    TIER_1: {"cost": 0.01, "seconds": 30, "providers": ["claude_sonnet"]},
    TIER_2: {"cost": 0.03, "seconds": 60, "providers": ["claude_sonnet", "grok"]},
    TIER_3: {"cost": 0.15, "seconds": 240, "providers": ["claude_sonnet", "grok", "gpt4o", "opus_synthesis"]},
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _env(key):
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{key}="): return line.split("=", 1)[1].strip()
    return os.environ.get(key, "")


def classify_decision(decision_type, question="", context=None, force_tier=None):
    """Classify a decision into tier 1/2/3."""
    if force_tier:
        m = TIER_META.get(force_tier, TIER_META[TIER_1])
        return {"tier": force_tier, "reason": "forced", "estimated_cost": m["cost"],
                "estimated_seconds": m["seconds"], "providers": m["providers"], "bypass_cadence": False}

    tier = DECISION_TIERS.get(decision_type, TIER_1)

    if tier != TIER_3 and question:
        hit = next((kw for kw in TIER3_KEYWORDS if kw in question.lower()), None)
        if hit:
            tier = TIER_3
            m = TIER_META[tier]
            return {"tier": tier, "reason": f"auto-upgrade: keyword '{hit}'",
                    "estimated_cost": m["cost"], "estimated_seconds": m["seconds"],
                    "providers": m["providers"], "bypass_cadence": False}

    if context and float(context.get("conversion_amount", 0) or 0) > 30000:
        tier = TIER_3

    m = TIER_META.get(tier, TIER_META[TIER_1])
    return {"tier": tier, "reason": f"classified: {decision_type}",
            "estimated_cost": m["cost"], "estimated_seconds": m["seconds"],
            "providers": m["providers"], "bypass_cadence": False}


def check_cadence(decision_type, bypass_event=None):
    """Check if Tier 3 is allowed by cadence gate (30-day minimum)."""
    if bypass_event and bypass_event in TIER3_BYPASS:
        return {"allowed": True, "reason": f"bypass: {bypass_event}", "last_run": None,
                "next_allowed": None, "days_until_allowed": 0}
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""SELECT ran_at FROM alex_hygiene_log
                       WHERE decision_type=%s AND tier='tier3_critical'
                       ORDER BY ran_at DESC LIMIT 1""", (decision_type,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"allowed": True, "reason": "no prior run", "last_run": None,
                    "next_allowed": None, "days_until_allowed": 0}
        last = row[0]
        nxt = last + timedelta(days=30)
        now = datetime.now(last.tzinfo) if last.tzinfo else datetime.now()
        if now >= nxt:
            return {"allowed": True, "reason": "cadence satisfied", "last_run": str(last),
                    "next_allowed": str(nxt), "days_until_allowed": 0}
        days = (nxt - now).days
        return {"allowed": False, "reason": f"{days} days until next allowed",
                "last_run": str(last), "next_allowed": str(nxt), "days_until_allowed": days}
    except Exception as e:
        return {"allowed": True, "reason": f"cadence check error: {e}", "last_run": None,
                "next_allowed": None, "days_until_allowed": 0}


def _build_shared_context(question, context=None):
    """Build context block for all three models (same input, no anchoring)."""
    try:
        from alex_retirement_advisor import get_disability_context_for_prompt
        disability = get_disability_context_for_prompt()
    except Exception:
        disability = ""
    try:
        from alex_gov_research import format_gov_data_for_alex_prompt
        gov = format_gov_data_for_alex_prompt()
    except Exception:
        gov = ""
    ctx = context or {}
    return f"""═══ JOHN'S SITUATION ═══
SSDI: $45,600/yr. MFS filer. Dual eligible (Medicare + Medicaid).
MAGI: ~$99K. IRMAA threshold: $103K MFS. Headroom: ~$4K.
Portfolio: ~$1.2M. Annual income: ~$14K dividends.
Roth YTD: $35K. Bracket room: ~$67K at 22%.

{disability}

{gov}

═══ QUESTION ═══
{question}"""


GROK_SYSTEM = """You are an expert disability retirement planner. Review this question independently.
Provide: 1) recommendation 2) risks 3) what you'd do differently 4) confidence (High/Med/Low).
Be specific with dollar amounts. This client is on SSDI, dual Medicare/Medicaid eligible."""

GPT4O_SYSTEM = """You are a senior retirement specialist for disabled individuals.
Provide independent analysis: 1) recommendation 2) dollar thresholds 3) SSDI/Medicaid risks
4) timeline 5) red flags 6) confidence. Be specific, not generic."""

OPUS_SYNTH = """Synthesize three independent expert analyses into a final report.
1) Where they AGREE (high confidence). 2) Where they DISAGREE (explain why, pick stronger view).
3) FINAL RECOMMENDATION with specific steps. 4) Confidence level. 5) Minority view if 2-vs-1.
6) Follow-up actions. Include EXECUTIVE SUMMARY and DISCLAIMER (AI analysis, not legal advice)."""


def _run_grok(question, shared_ctx):
    try:
        import llm_lane
        prompt = f"{GROK_SYSTEM}\n\n{shared_ctx}"
        out = llm_lane.generate(prompt, lane="deepseek-flash", timeout=90)
        if out and not str(out).startswith("LLM error"):
            return {"provider": "deepseek-v4-flash", "analysis": out.strip(), "ok": True,
                    "tokens": 0}
        return {"provider": "deepseek-v4-flash", "analysis": "", "ok": False, "error": "empty response"}
    except Exception as e:
        return {"provider": "deepseek-v4-flash", "analysis": "", "ok": False, "error": str(e)}


def _run_gpt4o(question, shared_ctx):
    try:
        import llm_lane
        prompt = f"{GPT4O_SYSTEM}\n\n{shared_ctx}"
        out = llm_lane.generate(prompt, lane="deepseek-flash", timeout=90)
        if out and not str(out).startswith("LLM error"):
            return {"provider": "deepseek-v4-flash", "analysis": out.strip(), "ok": True,
                    "tokens": 0}
        return {"provider": "deepseek-v4-flash", "analysis": "", "ok": False, "error": "empty response"}
    except Exception as e:
        return {"provider": "deepseek-v4-flash", "analysis": "", "ok": False, "error": str(e)}


def _run_opus_synthesis(question, alex, grok, gpt4o, decision_type):
    try:
        import llm_lane
        prompt = f"""{OPUS_SYNTH}

QUESTION: {question}

EXPERT 1 (Alex/Sonnet): {alex[:2000]}
EXPERT 2 (Grok): {grok[:2000]}
EXPERT 3 (GPT-4o): {gpt4o[:2000]}

Decision type: {decision_type}. Synthesize now."""
        out = llm_lane.generate(prompt, lane="deepseek-v4", timeout=180)
        if out and not str(out).startswith("LLM error"):
            return {"provider": "deepseek-v4-pro", "synthesis": out.strip(), "ok": True,
                    "input_tokens": 0, "output_tokens": 0}
        return {"provider": "deepseek-v4-pro", "synthesis": "", "ok": False, "error": "empty response"}
    except Exception as e:
        return {"provider": "deepseek-v4-pro", "synthesis": "", "ok": False, "error": str(e)}


def _agreement(alex, grok, gpt4o):
    if not all([alex, grok, gpt4o]): return 0.0
    POS = ["recommend", "suggest", "should", "proceed", "convert", "establish"]
    NEG = ["avoid", "do not", "don't", "risk", "caution", "concern"]
    def sig(t):
        t = t.lower()
        p = sum(1 for s in POS if s in t)
        n = sum(1 for s in NEG if s in t)
        return "pos" if p > n else "neg" if n > p else "neu"
    s = [sig(alex), sig(grok), sig(gpt4o)]
    if len(set(s)) == 1: return 1.0
    if s.count(s[0]) >= 2: return 0.67
    return 0.33


def run_tier3_hygiene(question, alex_analysis, context, decision_type, bypass_event=None):
    """Full Tier 3: Grok + GPT-4o (independent) → Opus synthesis."""
    cadence = check_cadence(decision_type, bypass_event)
    if not cadence["allowed"]:
        return {"ok": False, "blocked": True, "reason": cadence["reason"],
                "days_until_allowed": cadence["days_until_allowed"]}

    started = datetime.now()
    shared = _build_shared_context(question, context)

    print("  [hygiene] Running Grok...")
    grok = _run_grok(question, shared)
    print("  [hygiene] Running GPT-4o...")
    gpt4o = _run_gpt4o(question, shared)
    print("  [hygiene] Running Opus synthesis...")
    synth = _run_opus_synthesis(question, alex_analysis,
                                grok.get("analysis", ""), gpt4o.get("analysis", ""), decision_type)

    elapsed = (datetime.now() - started).seconds
    agreement = _agreement(alex_analysis, grok.get("analysis", ""), gpt4o.get("analysis", ""))

    result = {"ok": True, "tier": TIER_3, "decision_type": decision_type,
              "grok_opinion": grok, "gpt4o_opinion": gpt4o, "synthesis": synth,
              "agreement_score": agreement, "elapsed_seconds": elapsed}

    # Store to DB
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""INSERT INTO alex_hygiene_log
            (decision_type, tier, question, alex_opinion, grok_opinion, gpt4o_opinion,
             synthesis, agreement_score, elapsed_seconds, bypass_event, ran_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())""",
            (decision_type, TIER_3, question[:500], alex_analysis[:2000],
             grok.get("analysis", "")[:2000], gpt4o.get("analysis", "")[:2000],
             synth.get("synthesis", "")[:4000], agreement, elapsed, bypass_event))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [hygiene] DB store error: {e}")

    print(f"  [hygiene] Done in {elapsed}s — agreement: {agreement:.0%}")
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--classify", type=str)
    p.add_argument("--run", type=str)
    p.add_argument("--type", type=str, default="quarterly_strategy_review")
    args = p.parse_args()
    if args.classify:
        r = classify_decision(args.type, args.classify)
        print(json.dumps(r, indent=2))
    elif args.run:
        print("Running Tier 3 hygiene...")
        r = run_tier3_hygiene(args.run, "Alex analysis placeholder", {}, args.type)
        print(json.dumps({k: v for k, v in r.items() if k != "synthesis"}, indent=2, default=str))
        if r.get("synthesis", {}).get("synthesis"):
            print("\n=== SYNTHESIS ===")
            print(r["synthesis"]["synthesis"][:500])
