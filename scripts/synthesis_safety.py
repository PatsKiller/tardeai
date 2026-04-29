#!/usr/bin/env python3
"""synthesis_safety.py — Post-synthesis safety assessment.

Catches bad recommendations that passed through the LLM and post-LLM gating.
Reads all DB context and applies hard portfolio-aware rules.

Usage:
    python3 scripts/synthesis_safety.py [--symbols SCHD RTX] [--all] [--json]
    from synthesis_safety import assess_synthesis_safety
"""
import json, os, re, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

# Patterns that indicate bad RSI-driven income decisions
_BAD_INCOME_PATTERNS = [
    r"RSI\b.*sell signal",
    r"overbought.*(?:trim|sell|reduce|avoid)",
    r"(?:trim|sell).*(?:RSI|overbought)",
    r"potential sell signal",
    r"TRIM \d+ shares?",  # exact share trim without target allocation
]

_REDUCE_RECS = {"TRIM", "SELL", "AVOID", "REBALANCE_TRIM"}

# ── Strategy-specific RSI interpretation rules ──────────────────────

RSI_RULES = {
    "dividend_growth": {
        # SCHD, DGRO, VIG, V — dividend growth compounders
        "bands": [
            (0,  35, "add_zone_candidate",             {"HOLD", "ADD_ON_PULLBACK", "ADD"},     {"SELL", "AVOID"},              "Possible add zone — verify thesis and dividend quality intact"),
            (35, 55, "normal_accumulation_range",       {"HOLD", "ADD_ON_PULLBACK", "ADD"},     set(),                          "Normal accumulation range"),
            (55, 70, "healthy_momentum_do_not_chase",   {"HOLD"},                              {"ADD"},                        "Healthy momentum — hold, do not chase"),
            (70, 80, "extended_wait_for_pullback",      {"HOLD"},                              {"TRIM", "SELL"},               "Extended — wait for pullback. TRIM/SELL prohibited unless above max target or dividend thesis deteriorated"),
            (80, 100,"very_extended_position_review",   {"HOLD", "REBALANCE_TRIM"},            {"SELL"},                       "Very extended — review position size only if overweight"),
        ],
        "max_weight": 0.10,
    },
    "high_yield": {
        # JEPI, JEPQ, BDCs (HTGC, PFLT, MAIN, ARCC)
        "bands": [
            (0,  30, "possible_stress_not_auto_buy",    {"HOLD", "RESEARCH_MORE"},             {"BUY", "ADD"},                 "Possible stress — check payout safety, NAV/coverage, price trend before buying"),
            (30, 50, "possible_add_if_income_safe",     {"HOLD", "ADD_ON_PULLBACK", "ADD"},    set(),                          "Possible add if payout safety confirmed"),
            (50, 70, "collect_income_hold",             {"HOLD"},                              set(),                          "Collect income — hold position"),
            (70, 100,"extended_do_not_chase",           {"HOLD"},                              {"TRIM", "SELL"},               "Extended — do not chase. TRIM/SELL prohibited unless payout deteriorates or NAV premium excessive"),
        ],
        "max_weight": 0.10,
    },
    "core_growth": {
        # SCHG, growth ETFs
        "bands": [
            (0,  35, "pullback_opportunity",            {"HOLD", "ADD_ON_PULLBACK"},           set(),                          "Possible pullback opportunity if thesis intact"),
            (35, 70, "normal_range",                    {"HOLD", "ADD_ON_PULLBACK", "ADD"},    set(),                          "Normal range"),
            (70, 100,"extended_do_not_chase",           {"HOLD"},                              {"ADD"},                        "Extended — do not chase"),
        ],
        "max_weight": 0.15,
    },
    "swing_trade": {
        "bands": [
            (0,  30, "oversold_bounce_candidate",       {"HOLD", "BUY", "ADD"},                set(),                          "Oversold bounce candidate — requires catalyst + support"),
            (30, 60, "normal_setup_zone",               {"HOLD", "BUY", "ADD"},                set(),                          "Normal setup zone"),
            (60, 75, "momentum_breakout_possible",      {"HOLD", "ADD"},                       set(),                          "Momentum/breakout possible"),
            (75, 100,"extended_tighten_stop",           {"HOLD", "TRIM"},                      set(),                          "Extended — tighten stop, consider partial profits"),
        ],
        "max_weight": 0.35,
    },
    "speculative_growth": {
        "bands": [
            (0,  30, "oversold_with_catalyst_only",     {"HOLD", "BUY"},                       set(),                          "Oversold — only act with catalyst + volatility analysis"),
            (30, 70, "normal_range",                    {"HOLD", "BUY", "ADD", "TRIM"},        set(),                          "Normal range — pair with catalyst"),
            (70, 100,"extended_risk_elevated",          {"HOLD", "TRIM"},                      {"BUY", "ADD"},                 "Extended — risk elevated, do not add"),
        ],
        "max_weight": 0.25,
    },
    "defense_thesis": {
        "bands": [
            (0,  100,"secondary_to_thesis",             {"HOLD", "BUY", "ADD", "TRIM", "SELL"}, set(),                         "RSI is secondary — sector thesis, valuation, contracts, and geopolitical catalysts dominate"),
        ],
        "max_weight": 0.10,
    },
}

# Map strategy_type + layer to RSI rule set
_RSI_RULE_MAP = {
    "income": "dividend_growth",
    "core_holding": "dividend_growth",
    "growth_etf": "core_growth",
    "defense_thesis": "defense_thesis",
    "speculative_growth": "speculative_growth",
    "swing_trade": "swing_trade",
}
_LAYER_RSI_MAP = {
    "income_generators": "high_yield",
    "core_compounders": "dividend_growth",
    "tactical": "swing_trade",
}


def interpret_rsi(rsi: float, strategy_type: str = None, layer: str = None) -> dict:
    """Get RSI interpretation for a given value and strategy context.

    Returns:
        interpretation: human-readable meaning
        allowed_actions: set of safe actions at this RSI
        prohibited_actions: set of blocked actions at this RSI
        max_weight: how much RSI should weigh in the decision (0-1)
        description: detailed explanation
    """
    # Determine rule set
    rule_key = None
    if layer and layer in _LAYER_RSI_MAP:
        rule_key = _LAYER_RSI_MAP[layer]
    if strategy_type and strategy_type in _RSI_RULE_MAP:
        rule_key = _RSI_RULE_MAP[strategy_type]
    if not rule_key:
        rule_key = "dividend_growth"  # safe default

    rules = RSI_RULES.get(rule_key, RSI_RULES["dividend_growth"])

    for low, high, interp, allowed, prohibited, desc in rules["bands"]:
        if low <= rsi < high:
            return {
                "rsi_value": rsi,
                "rsi_rule_set": rule_key,
                "interpretation": interp,
                "allowed_actions": list(allowed),
                "prohibited_actions": list(prohibited),
                "max_weight": rules["max_weight"],
                "description": desc,
            }

    # Fallback
    return {
        "rsi_value": rsi,
        "rsi_rule_set": rule_key,
        "interpretation": "unknown",
        "allowed_actions": ["HOLD"],
        "prohibited_actions": [],
        "max_weight": 0.10,
        "description": f"RSI {rsi:.0f} — no matching band",
    }


def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def assess_synthesis_safety(symbol: str) -> dict:
    """Full safety assessment for a symbol's current synthesis."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sym = symbol.upper()

    # Gather all context
    cur.execute("SELECT * FROM watchlist_final_synthesis WHERE symbol=%s", (sym,))
    synthesis = cur.fetchone()

    cur.execute("SELECT * FROM income_asset_profiles WHERE symbol=%s", (sym,))
    income = cur.fetchone()

    cur.execute("SELECT * FROM watchlist_strategy_cards WHERE symbol=%s", (sym,))
    strategy = cur.fetchone()

    cur.execute("SELECT * FROM portfolio_income_goals LIMIT 1")
    goals = cur.fetchone()

    cur.execute("SELECT COUNT(*) as cnt FROM alert_events WHERE symbol=%s AND data_quality_status NOT IN ('valid','unknown') AND created_at > NOW() - INTERVAL '7 days'", (sym,))
    dq_count = cur.fetchone()["cnt"]

    # Get RSI from enrichment
    enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text()) if (STATE_DIR / "ticker_enrichment_cache.json").exists() else {}
    rsi_val = float(enrichment.get(sym, {}).get("rsi", 0) or 0) if isinstance(enrichment.get(sym), dict) else 0

    # Holdings weight
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total_portfolio = sum(info.get("total_value", 0) for info in holdings.get("account_summaries", {}).values())
    sym_mv = sum(float(h.get("market_value", 0) or 0) for h in holdings.get("holdings", []) if h.get("symbol") == sym)
    weight = round(sym_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0

    cur.close()
    conn.close()

    # ── Default result ──
    result = {
        "symbol": sym,
        "decision_safety": "safe",
        "recommendation_before": None,
        "recommendation_after": None,
        "safety_reasons": [],
        "overrides_applied": {},
        "human_review_required": False,
        "actionable_allowed": True,
        "portfolio_context_used": True,
        "income_context_used": income is not None,
        "target_allocation_used": False,
        "rsi_interpretation": None,
    }

    if not synthesis:
        result["decision_safety"] = "pending"
        result["actionable_allowed"] = False
        return result

    rec = (synthesis.get("recommendation") or "").upper()
    conf = float(synthesis.get("confidence", 0) or 0)
    raw_response = synthesis.get("raw_response") or ""
    narrative = synthesis.get("synthesis_narrative") or ""
    reason_codes = synthesis.get("reason_codes") or []
    all_text = f"{raw_response} {narrative}".lower()

    result["recommendation_before"] = rec
    result["recommendation_after"] = rec  # may be overridden

    income_pct = float(income.get("portfolio_income_pct", 0) or 0) if income else 0
    annual_income = float(income.get("annual_income", 0) or 0) if income else 0
    layer = income.get("layer_id", "") if income else ""
    payout = income.get("payout_safety", "unknown") if income else "unknown"
    strategy_type = strategy.get("strategy_type", "") if strategy else ""
    is_income_asset = layer in ("income_generators",) or strategy_type == "income"
    is_compounder = layer == "core_compounders" and annual_income > 0

    # ── RULE 1: Income protection override ──
    if rec in _REDUCE_RECS and (is_income_asset or is_compounder):
        if income_pct > 20 and conf < 0.80:
            result["safety_reasons"].append({
                "rule": "income_protection_override",
                "detail": f"Position provides {income_pct:.0f}% of income, confidence {conf:.0%} < 80% required for reduction",
            })
            result["recommendation_after"] = "HOLD"
            result["overrides_applied"]["income_protection"] = f"{rec} → HOLD"
            result["human_review_required"] = True
            result["decision_safety"] = "unsafe"

    # ── RULE 2: Technical-only income block ──
    if rec in _REDUCE_RECS and is_income_asset:
        tech_reasons = {"overbought", "rsi_high", "technical_overbought", "technical_support", "overvalued"}
        if reason_codes and set(r.lower() for r in reason_codes) <= tech_reasons:
            result["safety_reasons"].append({
                "rule": "technical_only_income_decision",
                "detail": f"Reason codes {reason_codes} are all technical — cannot drive income asset reduction",
            })
            result["recommendation_after"] = "HOLD"
            result["overrides_applied"]["technical_block"] = f"{rec} → HOLD"
            result["decision_safety"] = "unsafe"
            result["actionable_allowed"] = False

    # ── RULE 2b: RSI interpretation check ──
    if rsi_val > 0:
        rsi_interp = interpret_rsi(rsi_val, strategy_type, layer)
        result["rsi_interpretation"] = rsi_interp

        # Check if recommendation is in prohibited actions for this RSI band
        prohibited = set(rsi_interp.get("prohibited_actions", []))
        if rec in prohibited:
            result["safety_reasons"].append({
                "rule": "rsi_prohibited_action",
                "detail": f"RSI {rsi_val:.0f} ({rsi_interp['interpretation']}) prohibits {rec} for {rsi_interp['rsi_rule_set']} strategy. {rsi_interp['description']}",
            })
            # Override to best allowed action
            allowed = rsi_interp.get("allowed_actions", ["HOLD"])
            safe_rec = "HOLD" if "HOLD" in allowed else allowed[0] if allowed else "HOLD"
            result["recommendation_after"] = safe_rec
            result["overrides_applied"]["rsi_rule"] = f"{rec} → {safe_rec} (RSI {rsi_val:.0f} prohibits {rec})"
            if result["decision_safety"] != "unsafe":
                result["decision_safety"] = "unsafe"
            result["human_review_required"] = True

        # Check if RSI weight exceeds max for this strategy
        max_rsi_weight = rsi_interp.get("max_weight", 0.10)
        if reason_codes:
            rsi_reasons = sum(1 for r in reason_codes if "rsi" in r.lower() or "overbought" in r.lower() or "oversold" in r.lower())
            total_reasons = len(reason_codes)
            if total_reasons > 0:
                rsi_weight = rsi_reasons / total_reasons
                if rsi_weight > max_rsi_weight and (is_income_asset or is_compounder):
                    result["safety_reasons"].append({
                        "rule": "rsi_overweight_in_decision",
                        "detail": f"RSI accounts for {rsi_weight:.0%} of reason codes but max allowed is {max_rsi_weight:.0%} for {rsi_interp['rsi_rule_set']}",
                    })

    # ── RULE 3: Missing target allocation for trim ──
    if rec in ("TRIM", "REBALANCE_TRIM"):
        result["safety_reasons"].append({
            "rule": "missing_target_allocation_for_trim",
            "detail": "No target allocation database — exact trim quantities are estimates, not computed from targets",
        })
        result["target_allocation_used"] = False
        if result["decision_safety"] != "unsafe":
            result["decision_safety"] = "unsafe"
        result["actionable_allowed"] = False

    # ── RULE 4: Income gap protection ──
    if rec in _REDUCE_RECS and goals and annual_income > 0:
        target = float(goals.get("target_income", 55000))
        cur2 = _get_conn().cursor()
        cur2.execute("SELECT SUM(annual_income) as total FROM income_asset_profiles")
        total_income = float(cur2.fetchone()[0] or 0)
        cur2.close()
        if total_income < target:
            gap = target - total_income
            result["safety_reasons"].append({
                "rule": "income_gap_protection",
                "detail": f"Income gap ${gap:,.0f} exists (${total_income:,.0f} vs ${target:,.0f} target). Reducing ${sym} removes ${annual_income:,.0f}/yr.",
            })
            result["human_review_required"] = True
            if result["decision_safety"] != "unsafe":
                result["decision_safety"] = "unsafe"

    # ── RULE 5: Layer allocation conflict ──
    if rec in _REDUCE_RECS and is_income_asset:
        # Check if income_generators layer is underweight
        try:
            conn2 = _get_conn()
            cur2 = conn2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute("SELECT target_min_pct FROM portfolio_layers WHERE layer_id='income_generators'")
            lr = cur2.fetchone()
            cur2.close()
            conn2.close()
            if lr:
                # Income layer actual is 8.5% vs 25% min
                result["safety_reasons"].append({
                    "rule": "layer_allocation_conflict",
                    "detail": f"income_generators layer is underweight (target min {lr['target_min_pct']}%). Reducing income exposure worsens allocation drift.",
                })
        except Exception:
            pass

    # ── RULE 6: Contradictory synthesis ──
    contradictions = []
    if "underweight" in all_text and rec in _REDUCE_RECS:
        contradictions.append("Says underweight but recommends reduction")
    if "below target" in all_text and rec in _REDUCE_RECS:
        contradictions.append("Says below target but recommends reduction")
    if ("income critical" in all_text or f"{income_pct:.0f}% of" in all_text) and rec in _REDUCE_RECS:
        contradictions.append(f"Acknowledges {income_pct:.0f}% income contribution but recommends reduction")
    if contradictions:
        result["safety_reasons"].append({
            "rule": "contradictory_synthesis",
            "detail": "; ".join(contradictions),
        })
        result["decision_safety"] = "unsafe"
        result["human_review_required"] = True

    # ── RULE 7: Old bad synthesis detection ──
    bad_found = []
    for pattern in _BAD_INCOME_PATTERNS:
        if re.search(pattern, all_text, re.IGNORECASE):
            bad_found.append(pattern)
    if bad_found and is_income_asset:
        result["safety_reasons"].append({
            "rule": "legacy_bad_synthesis_language",
            "detail": f"Found {len(bad_found)} problematic patterns in synthesis text for income asset",
        })
        if result["decision_safety"] != "unsafe":
            result["decision_safety"] = "unsafe"

    # ── RULE 8: Tiny position ──
    if weight > 0 and weight < 0.5 and rec in ("BUY", "SELL", "TRIM", "AVOID"):
        result["safety_reasons"].append({
            "rule": "tiny_position_low_priority",
            "detail": f"Position {weight:.2f}% is <0.5% — major actions suppressed",
        })
        if rec in ("SELL", "TRIM"):
            result["recommendation_after"] = "HOLD"
            result["overrides_applied"]["tiny_position"] = f"{rec} → HOLD"

    # ── RULE 9: Data quality ──
    if dq_count >= 3:
        result["decision_safety"] = "blocked"
        result["actionable_allowed"] = False
        result["safety_reasons"].append({
            "rule": "data_quality_blocked",
            "detail": f"{dq_count} data quality issues in last 7 days",
        })
    elif dq_count > 0:
        result["safety_reasons"].append({
            "rule": "data_quality_warning",
            "detail": f"{dq_count} data quality issue(s) — confidence reduced",
        })

    # ── RULE 10: Safe criteria check ──
    if result["decision_safety"] == "safe":
        # Verify all required context was used
        if not result["income_context_used"] and is_income_asset:
            result["decision_safety"] = "unsafe"
            result["safety_reasons"].append({
                "rule": "income_context_missing",
                "detail": "Income asset has no income profile — run materialize_income_engine.py",
            })
        if rec in ("TRIM", "REBALANCE_TRIM") and not result["target_allocation_used"]:
            result["decision_safety"] = "unsafe"
            result["safety_reasons"].append({
                "rule": "trim_without_target_allocation",
                "detail": "Trim recommended without target allocation data",
            })

    # Set actionable based on safety
    if result["decision_safety"] in ("unsafe", "blocked"):
        result["actionable_allowed"] = False

    return result


def persist_safety(symbol: str, safety: dict):
    """Write safety assessment to DB."""
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE watchlist_final_synthesis
        SET decision_safety = %s,
            safety_reasons = %s,
            safety_overrides = %s,
            portfolio_context_used = %s,
            income_context_used = %s,
            target_allocation_used = %s,
            actionable = %s,
            human_review_required = %s,
            updated_at = now()
        WHERE symbol = %s
    """, (
        safety["decision_safety"],
        json.dumps(safety["safety_reasons"], default=str),
        json.dumps(safety["overrides_applied"], default=str),
        safety["portfolio_context_used"],
        safety["income_context_used"],
        safety["target_allocation_used"],
        safety["actionable_allowed"],
        safety["human_review_required"],
        symbol,
    ))

    # Update maturity
    cur.execute("""
        UPDATE watchlist_analysis_maturity
        SET actionable = %s, decision_quality_status = %s, updated_at = now()
        WHERE symbol = %s
    """, (safety["actionable_allowed"],
          safety["decision_safety"] if safety["decision_safety"] != "safe" else "actionable",
          symbol))

    # Safety history
    cur.execute("""
        INSERT INTO watchlist_synthesis_safety_history
            (symbol, decision_safety, recommendation_before, recommendation_after,
             safety_reasons, overrides_applied)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (symbol, safety["decision_safety"],
          safety["recommendation_before"], safety["recommendation_after"],
          json.dumps(safety["safety_reasons"], default=str),
          json.dumps(safety["overrides_applied"], default=str)))

    # Event
    if safety["decision_safety"] != "safe":
        cur.execute("""
            INSERT INTO watchlist_events (event_type, symbol, status, message)
            VALUES ('synthesis_safety', %s, %s, %s)
        """, (symbol, safety["decision_safety"],
              f"Safety: {safety['decision_safety']} | {safety['recommendation_before']} → {safety['recommendation_after']} | {len(safety['safety_reasons'])} reason(s)"))

    conn.commit()
    conn.close()


def assess_all():
    """Assess all symbols with synthesis."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT symbol FROM watchlist_final_synthesis")
    symbols = [r["symbol"] for r in cur.fetchall()]
    conn.close()

    results = []
    for sym in symbols:
        r = assess_synthesis_safety(sym)
        persist_safety(sym, r)
        results.append(r)
    return results


if __name__ == "__main__":
    symbols = None
    if "--symbols" in sys.argv:
        idx = sys.argv.index("--symbols")
        symbols = [s.upper() for s in sys.argv[idx + 1:] if not s.startswith("-")]

    if symbols:
        results = []
        for sym in symbols:
            r = assess_synthesis_safety(sym)
            persist_safety(sym, r)
            results.append(r)
    else:
        results = assess_all()

    for r in results:
        icon = "\u2713" if r["decision_safety"] == "safe" else "\u2717"
        override = f" [{r['recommendation_before']} → {r['recommendation_after']}]" if r["recommendation_before"] != r["recommendation_after"] else ""
        reasons = [s["rule"] for s in r["safety_reasons"]]
        print(f"  {icon} {r['symbol']:>6} {r['decision_safety']:>8}{override} reasons={reasons}")

    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))
