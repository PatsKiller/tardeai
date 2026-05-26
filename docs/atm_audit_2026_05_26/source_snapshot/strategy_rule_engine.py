#!/usr/bin/env python3
"""strategy_rule_engine.py — Classification-first strategy rule evaluation.

ALL rules operate on strategy_type, group_id, or portfolio context.
NO executable logic references specific ticker symbols.
Tickers map to strategy_type dynamically via ticker_strategy_classifications.

Usage:
    python3 scripts/strategy_rule_engine.py --symbol SCHD --json
    python3 scripts/strategy_rule_engine.py --all --json
    python3 scripts/strategy_rule_engine.py --classify SYMBOL --strategy-type TYPE --source manual
    python3 scripts/strategy_rule_engine.py --validate --json
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"

_CONDITION_OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: float(a or 0) > float(b),
    ">=": lambda a, b: float(a or 0) >= float(b),
    "<": lambda a, b: float(a or 0) < float(b),
    "<=": lambda a, b: float(a or 0) <= float(b),
    "IN": lambda a, b: a in (b if isinstance(b, (list, set)) else [b]),
    "NOT_IN": lambda a, b: a not in (b if isinstance(b, (list, set)) else [b]),
    "IS_TRUE": lambda a, b: bool(a),
    "IS_FALSE": lambda a, b: not bool(a),
}


def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


# ── Classification functions ─────────────────────────────────────

def classify_symbol(symbol: str) -> dict:
    """Look up symbol classification from DB. Returns {strategy_type, confidence, ...} or None."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (symbol.upper(),))
    r = cur.fetchone()
    conn.close()
    return dict(r) if r else None


def propose_classification(symbol: str, strategy_type: str, agent: str = None,
                           confidence: float = 0.7, rationale: str = None, evidence: dict = None):
    """Agent proposes a classification for a new symbol."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO agent_classification_suggestions
            (symbol, suggested_strategy_type, suggested_asset_type, agent, confidence, rationale, evidence, status)
        VALUES (%s, %s, NULL, %s, %s, %s, %s, %s)
    """, (symbol.upper(), strategy_type, agent, confidence, rationale,
          json.dumps(evidence or {}, default=str),
          'accepted' if confidence >= 0.85 and not agent else 'pending'))

    # Auto-accept high-confidence non-conflicting
    if confidence >= 0.85:
        existing = classify_symbol(symbol)
        if not existing:
            cur.execute("""
                INSERT INTO ticker_strategy_classifications
                    (symbol, strategy_type, classification_source, confidence, assigned_by_agent, rationale, evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO NOTHING
            """, (symbol.upper(), strategy_type, 'agent' if agent else 'manual',
                  confidence, agent, rationale, json.dumps(evidence or {}, default=str)))
            cur.execute("""
                INSERT INTO ticker_classification_history
                    (symbol, old_strategy_type, new_strategy_type, classification_source, confidence, assigned_by_agent, rationale)
                VALUES (%s, NULL, %s, %s, %s, %s, %s)
            """, (symbol.upper(), strategy_type, 'agent' if agent else 'manual', confidence, agent, rationale))

    conn.commit()
    conn.close()


def accept_classification(symbol: str, strategy_type: str, reviewer: str = "system"):
    """Accept a classification (manual or from suggestion)."""
    conn = _get_conn()
    cur = conn.cursor()
    # Get old
    cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s", (symbol.upper(),))
    old = cur.fetchone()
    old_type = old[0] if old else None

    cur.execute("""
        INSERT INTO ticker_strategy_classifications (symbol, strategy_type, classification_source, confidence)
        VALUES (%s, %s, 'manual', 1.0)
        ON CONFLICT (symbol) DO UPDATE SET
            strategy_type=EXCLUDED.strategy_type, classification_source='manual',
            confidence=1.0, updated_at=now()
    """, (symbol.upper(), strategy_type))
    cur.execute("""
        INSERT INTO ticker_classification_history
            (symbol, old_strategy_type, new_strategy_type, classification_source, confidence, rationale)
        VALUES (%s, %s, %s, 'manual', 1.0, %s)
    """, (symbol.upper(), old_type, strategy_type, f"Accepted by {reviewer}"))
    conn.commit()
    conn.close()


def get_strategy_config(strategy_type: str) -> dict:
    """Load full strategy config from DB registry."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM strategy_registry WHERE strategy_type=%s", (strategy_type,))
    r = cur.fetchone()
    conn.close()
    return dict(r) if r else {}


# ── Rule evaluation ──────────────────────────────────────────────

def _build_symbol_context(symbol: str) -> dict:
    """Build evaluation context for a symbol entirely from DB + holdings."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sym = symbol.upper()

    # Classification
    classification = classify_symbol(sym)
    strategy_type = classification["strategy_type"] if classification else None

    # Strategy config
    config = get_strategy_config(strategy_type) if strategy_type else {}

    # Income profile
    cur.execute("SELECT * FROM income_asset_profiles WHERE symbol=%s", (sym,))
    income = cur.fetchone()

    # Enrichment (RSI, etc.)
    enrichment = json.loads((STATE_DIR / "ticker_enrichment_cache.json").read_text()) if (STATE_DIR / "ticker_enrichment_cache.json").exists() else {}
    e = enrichment.get(sym, {}) if isinstance(enrichment.get(sym), dict) else {}

    # Strategy card
    cur.execute("SELECT risk_reward, support, stop_loss FROM watchlist_strategy_cards WHERE symbol=%s", (sym,))
    sc = cur.fetchone()

    # Agent results
    cur.execute("""
        SELECT DISTINCT ON (agent) agent, recommendation, confidence
        FROM watchlist_agent_results WHERE symbol=%s AND status='completed'
        ORDER BY agent, created_at DESC
    """, (sym,))
    agents = {r["agent"]: {"rec": r["recommendation"], "conf": float(r["confidence"] or 0)} for r in cur.fetchall()}

    # Portfolio weight
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total_portfolio = sum(info.get("total_value", 0) for info in holdings.get("account_summaries", {}).values())
    sym_mv = sum(float(h.get("market_value", 0) or 0) for h in holdings.get("holdings", []) if h.get("symbol") == sym)
    weight = round(sym_mv / total_portfolio * 100, 2) if total_portfolio > 0 else 0

    # Income goals
    cur.execute("SELECT * FROM portfolio_income_goals LIMIT 1")
    goals = cur.fetchone()
    cur.execute("SELECT SUM(annual_income) as total FROM income_asset_profiles")
    total_income = float((cur.fetchone() or {}).get("total", 0) or 0)
    target_income = float(goals.get("target_income", 55000)) if goals else 55000

    # Group allocations
    # (Would need full portfolio scan — approximate from income_asset_profiles)

    # Maturity
    cur.execute("SELECT completed_agents FROM watchlist_analysis_maturity WHERE symbol=%s", (sym,))
    mat = cur.fetchone()
    completed_agents = set(a.replace("_agent", "") for a in (mat.get("completed_agents") or [])) if mat else set()

    conn.close()

    return {
        "symbol": sym,
        "strategy_type": strategy_type,
        "classification_source": classification.get("classification_source") if classification else None,
        "classification_confidence": float(classification.get("confidence", 0)) if classification else 0,
        "review_required": classification.get("review_required", True) if classification else True,
        "is_income_strategy": config.get("is_income_strategy", False),
        "is_tactical": config.get("is_tactical", False),
        "requires_catalyst": config.get("requires_catalyst", False),
        "layer_id": config.get("layer_id"),
        "rsi": float(e.get("rsi", 0) or 0),
        "position_weight": weight,
        "risk_reward": float(sc["risk_reward"] or 0) if sc and sc.get("risk_reward") else 0,
        "income_pct": float(income.get("portfolio_income_pct", 0) or 0) if income else 0,
        "annual_income": float(income.get("annual_income", 0) or 0) if income else 0,
        "payout_safety": income.get("payout_safety", "unknown") if income else "unknown",
        "income_pct_of_target": round(total_income / target_income * 100, 1) if target_income > 0 else 0,
        "income_gap": max(0, target_income - total_income),
        "total_portfolio_income": total_income,
        "agents": agents,
        "completed_agents": list(completed_agents),
        "has_buy_sell_conflict": _has_buy_sell_conflict(agents),
        "has_catalyst": False,  # Would need catalyst data
        "price_above_reclaim": True,  # Would need reclaim level data
        "portfolio_heat": 0,  # Would need heat computation
        "rec": None,  # Set during evaluation from synthesis
        "confidence": 0,
    }


def _has_buy_sell_conflict(agents: dict) -> bool:
    buy_group = {"BUY", "ADD", "ADD_ON_PULLBACK", "STRONG_BUY"}
    sell_group = {"SELL", "TRIM", "AVOID", "REBALANCE_TRIM"}
    has_buy = any(v["rec"].upper() in buy_group for v in agents.values() if v.get("rec"))
    has_sell = any(v["rec"].upper() in sell_group for v in agents.values() if v.get("rec"))
    return has_buy and has_sell


def evaluate_condition(condition: dict, context: dict) -> bool:
    """Evaluate a single condition against context."""
    field = condition.get("field", "")
    op = condition.get("op", "=")
    value = condition.get("value")

    actual = context.get(field)
    if actual is None and op not in ("IS_FALSE",):
        return False

    # Special: if value references another context field
    if isinstance(value, str) and value in context:
        value = context[value]

    evaluator = _CONDITION_OPS.get(op)
    if not evaluator:
        return False

    try:
        return evaluator(actual, value)
    except (TypeError, ValueError):
        return False


def evaluate_rule(rule: dict, context: dict) -> dict:
    """Evaluate a single rule against context. Returns {matched, actions, ...}."""
    conditions = rule.get("conditions") or []
    logical_op = rule.get("logical_operator", "AND")

    results = [evaluate_condition(c, context) for c in conditions]

    if logical_op == "AND":
        matched = all(results) if results else False
    elif logical_op == "OR":
        matched = any(results) if results else False
    else:
        matched = all(results) if results else False

    return {
        "rule_name": rule.get("rule_name"),
        "matched": matched,
        "then_actions": rule.get("then_actions", {}) if matched else {},
        "prohibited_actions": rule.get("prohibited_actions", []) if matched else [],
        "narrative": rule.get("narrative_template", "") if matched else "",
    }


def load_active_rules(strategy_type: str = None, group_ids: list = None) -> list:
    """Load active rules for a strategy_type and/or group_ids."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    conditions = ["active = TRUE", "(active_to IS NULL OR active_to > NOW())"]
    params = []

    type_conds = []
    if strategy_type:
        type_conds.append("strategy_type = %s")
        params.append(strategy_type)
    if group_ids:
        type_conds.append("group_id = ANY(%s)")
        params.append(group_ids)
    type_conds.append("strategy_type IS NULL AND group_id IS NULL")  # Portfolio-wide rules

    conditions.append(f"({' OR '.join(type_conds)})")

    sql = f"SELECT * FROM strategy_rule_sets WHERE {' AND '.join(conditions)} ORDER BY rule_priority"
    cur.execute(sql, params)
    rules = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rules


def evaluate_strategy_rules(symbol: str) -> dict:
    """Full rule evaluation for a symbol. Classification-first, zero hard-coded tickers."""
    sym = symbol.upper()

    # Step 1: Classify
    classification = classify_symbol(sym)
    if not classification:
        return {
            "symbol": sym,
            "strategy_type": None,
            "baseline_action": "CLASSIFICATION_REQUIRED",
            "allowed_actions": [],
            "prohibited_actions": [],
            "rule_flags": [{"rule": "unclassified", "action": "CLASSIFICATION_REQUIRED", "reason": "Symbol not in ticker_strategy_classifications"}],
            "required_data_missing": ["classification"],
            "required_agents_missing": [],
            "escalation_required": True,
            "human_review_required": True,
            "confidence_floor": 0,
            "rule_narrative": f"{sym} has no classification. Assign strategy_type before evaluation.",
            "matched_rules": [],
            "rule_violations": [],
        }

    strategy_type = classification["strategy_type"]

    # Step 2: Build context
    context = _build_symbol_context(sym)

    # Step 3: Load strategy config
    config = get_strategy_config(strategy_type)

    # Step 4: Load group memberships
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT group_id FROM strategy_group_caps WHERE member_strategy_types ? %s", (strategy_type,))
    group_ids = [r["group_id"] for r in cur.fetchall()]
    conn.close()

    # Step 5: Load and evaluate rules
    rules = load_active_rules(strategy_type, group_ids)
    matched_rules = []
    all_prohibited = list(config.get("prohibited_actions") or [])
    all_allowed = list(config.get("allowed_actions") or [])
    flags = []
    escalation = False
    human_review = False

    for rule in rules:
        result = evaluate_rule(rule, context)
        if result["matched"]:
            matched_rules.append(result)
            all_prohibited.extend(result.get("prohibited_actions", []))
            actions = result.get("then_actions", {})
            if actions.get("action") in ("BLOCK", "BLOCK_ADD", "PAUSE"):
                flags.append({"rule": result["rule_name"], "action": actions.get("action"), "reason": actions.get("reason", "")})
            if actions.get("escalation") or actions.get("action") == "ESCALATE":
                escalation = True
            if actions.get("human_review"):
                human_review = True

    # Step 6: Determine baseline action
    baseline = "HOLD"
    weight = context["position_weight"]
    rsi = context["rsi"]
    is_income = context["is_income_strategy"]

    if weight == 0:
        if is_income and rsi < 55:
            baseline = "ADD_ON_PULLBACK"
        elif context["requires_catalyst"] and not context["has_catalyst"]:
            baseline = "RESEARCH_MORE"
        else:
            baseline = "RESEARCH_MORE"
    elif weight > 0 and weight < 0.5:
        baseline = "HOLD"
        flags.append({"rule": "tiny_position", "action": "LOW_PRIORITY", "reason": f"Weight {weight:.2f}% < 0.5%"})

    # Check required agents
    required = [a.replace("_agent", "") for a in (config.get("required_agents") or [])]
    missing = [a for a in required if a not in context["completed_agents"]]

    # Check required data
    missing_data = []
    if is_income and context["annual_income"] == 0:
        missing_data.append("income_profile")
    if strategy_type == "swing_trade" and context["risk_reward"] == 0:
        missing_data.append("risk_reward")

    # Build narrative
    narrative = f"Strategy: {config.get('display_name', strategy_type)}"
    if context["annual_income"] > 0:
        narrative += f" | Income: ${context['annual_income']:,.0f}/yr ({context['income_pct']:.0f}%)"
    if rsi > 0:
        narrative += f" | RSI {rsi:.0f}"
    if matched_rules:
        narrative += f" | {len(matched_rules)} rule(s) triggered"
    if missing:
        narrative += f" | Missing: {','.join(missing)}"

    result = {
        "symbol": sym,
        "strategy_type": strategy_type,
        "strategy_display": config.get("display_name"),
        "classification_source": classification.get("classification_source"),
        "classification_confidence": float(classification.get("confidence", 0)),
        "baseline_action": baseline,
        "allowed_actions": list(set(all_allowed)),
        "prohibited_actions": list(set(all_prohibited)),
        "rule_flags": flags,
        "required_data_missing": missing_data,
        "required_agents_missing": missing,
        "escalation_required": escalation,
        "human_review_required": human_review or classification.get("review_required", False),
        "confidence_floor": 0.5,
        "rule_narrative": narrative,
        "matched_rules": [{"name": r["rule_name"], "narrative": r.get("narrative", "")} for r in matched_rules],
        "rule_violations": [],
        "rsi_value": rsi,
        "portfolio_weight": weight,
        "income_pct": context["income_pct"],
        "group_ids": group_ids,
    }

    # Persist
    _persist_evaluation(sym, result)
    return result


def apply_agent_overlay(symbol: str, agent_results: dict) -> list:
    """Check if agent recommendations violate strategy rules. Returns violations."""
    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT prohibited_actions, strategy_type FROM strategy_rule_evaluations WHERE symbol=%s ORDER BY updated_at DESC LIMIT 1", (symbol.upper(),))
    r = cur.fetchone()
    conn.close()

    if not r:
        return []

    prohibited = set(p.upper() for p in (r.get("prohibited_actions") or []))
    violations = []
    for agent, rec in agent_results.items():
        rec_upper = (rec or "").upper()
        for p in prohibited:
            # Check if the prohibited pattern matches
            if rec_upper in p or p in rec_upper:
                violations.append({
                    "agent": agent,
                    "recommendation": rec,
                    "violated_rule": p,
                    "strategy_type": r.get("strategy_type"),
                    "action": "requires_cio_synthesis_and_human_review",
                })
    return violations


def _persist_evaluation(symbol: str, result: dict):
    conn = _get_conn()
    cur = conn.cursor()

    # Upsert into strategy_rule_evaluations (symbol PK)
    cur.execute("""
        INSERT INTO strategy_rule_evaluations
            (symbol, strategy_type, baseline_action, allowed_actions, prohibited_actions,
             rule_flags, required_data_missing, required_agents_missing,
             escalation_required, human_review_required, confidence_floor,
             rule_narrative, matched_rules, rule_violations, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
        ON CONFLICT (symbol) DO UPDATE SET
            strategy_type=EXCLUDED.strategy_type, baseline_action=EXCLUDED.baseline_action,
            allowed_actions=EXCLUDED.allowed_actions, prohibited_actions=EXCLUDED.prohibited_actions,
            rule_flags=EXCLUDED.rule_flags, required_data_missing=EXCLUDED.required_data_missing,
            required_agents_missing=EXCLUDED.required_agents_missing,
            escalation_required=EXCLUDED.escalation_required,
            human_review_required=EXCLUDED.human_review_required,
            rule_narrative=EXCLUDED.rule_narrative,
            matched_rules=EXCLUDED.matched_rules,
            rule_violations=EXCLUDED.rule_violations,
            updated_at=now()
    """, (symbol, result["strategy_type"], result["baseline_action"],
          result["allowed_actions"], result["prohibited_actions"],
          json.dumps(result["rule_flags"], default=str),
          result["required_data_missing"], result["required_agents_missing"],
          result["escalation_required"], result["human_review_required"],
          result["confidence_floor"], result["rule_narrative"],
          json.dumps(result["matched_rules"], default=str),
          json.dumps(result["rule_violations"], default=str)))

    # History
    cur.execute("""
        INSERT INTO strategy_rule_history (symbol, strategy_type, baseline_action, rule_flags, rule_violations)
        VALUES (%s, %s, %s, %s, %s)
    """, (symbol, result["strategy_type"], result["baseline_action"],
          json.dumps(result["rule_flags"], default=str),
          json.dumps(result["rule_violations"], default=str)))

    conn.commit()
    conn.close()


def evaluate_all():
    """Evaluate all classified symbols."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE")
    symbols = [r["symbol"] for r in cur.fetchall()]
    conn.close()

    results = []
    for sym in symbols:
        try:
            results.append(evaluate_strategy_rules(sym))
        except Exception as e:
            print(f"  [rule-engine] {sym}: error — {e}")
    return results


if __name__ == "__main__":
    if "--classify" in sys.argv:
        idx = sys.argv.index("--classify")
        sym = sys.argv[idx + 1].upper()
        st_idx = sys.argv.index("--strategy-type") if "--strategy-type" in sys.argv else None
        st = sys.argv[st_idx + 1] if st_idx else None
        src = "manual"
        if "--source" in sys.argv:
            src = sys.argv[sys.argv.index("--source") + 1]
        if st:
            accept_classification(sym, st, "cli")
            print(f"Classified {sym} → {st} (source={src})")
        sys.exit(0)

    if "--validate" in sys.argv:
        # Quick validation
        checks = []
        c = classify_symbol("SCHD")
        checks.append(("SCHD classified", c is not None and c["strategy_type"] == "dividend_growth_compounder"))
        c2 = classify_symbol("NONEXISTENT_TICKER_XYZ")
        checks.append(("Unknown returns None", c2 is None))
        r = evaluate_strategy_rules("SCHD")
        checks.append(("SCHD evaluates", r["strategy_type"] == "dividend_growth_compounder"))
        checks.append(("SCHD has prohibited", len(r["prohibited_actions"]) > 0))
        r2 = evaluate_strategy_rules("NONEXISTENT_TICKER_XYZ")
        checks.append(("Unknown = CLASSIFICATION_REQUIRED", r2["baseline_action"] == "CLASSIFICATION_REQUIRED"))
        for name, ok in checks:
            print(f"  {'PASS' if ok else 'FAIL'} {name}")
        if "--json" in sys.argv:
            print(json.dumps({"checks": [{"name": n, "passed": p} for n, p in checks]}, indent=2))
        sys.exit(0 if all(p for _, p in checks) else 1)

    symbols = None
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        symbols = [sys.argv[idx + 1].upper()]
    elif "--all" in sys.argv:
        symbols = None

    if symbols:
        results = [evaluate_strategy_rules(s) for s in symbols]
    else:
        results = evaluate_all()

    for r in results:
        flags_n = len(r.get("rule_flags", []))
        miss = r.get("required_agents_missing", [])
        matched = len(r.get("matched_rules", []))
        print(f"  {r['symbol']:>6} {r['strategy_type'] or '?':>30} baseline={r['baseline_action']:>20} rules={matched} flags={flags_n} prohibited={len(r.get('prohibited_actions',[]))}{' missing='+','.join(miss) if miss else ''}")

    if "--json" in sys.argv:
        print(json.dumps(results, indent=2, default=str))
