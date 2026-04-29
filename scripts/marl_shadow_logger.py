#!/usr/bin/env python3
"""marl_shadow_logger.py — Shadow-mode MARL episode logger. Advisory only, no live execution.

Logs decision episodes for offline training: state, classification, rule eval, agent outputs,
synthesis, QA, final recommendation. MARL cannot alter final action or execute trades.

Usage:
    python3 scripts/marl_shadow_logger.py --symbol SCHD [--json]
    python3 scripts/marl_shadow_logger.py --all [--json]
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def log_decision_episode(symbol: str) -> dict:
    """Log one decision episode for a symbol. Returns episode summary."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sym = symbol.upper()

    # Classification
    cur.execute("SELECT strategy_type, classification_source, confidence FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (sym,))
    classification = cur.fetchone()

    # Rule evaluation
    cur.execute("SELECT baseline_action, prohibited_actions, rule_flags, matched_rules FROM strategy_rule_evaluations WHERE symbol=%s ORDER BY updated_at DESC LIMIT 1", (sym,))
    rule_eval = cur.fetchone()

    # Agent results
    cur.execute("SELECT agent, recommendation, confidence FROM watchlist_agent_results WHERE symbol=%s AND status='completed' ORDER BY created_at DESC LIMIT 5", (sym,))
    agents = [dict(r) for r in cur.fetchall()]

    # Synthesis
    cur.execute("SELECT recommendation, confidence, decision_safety, actionable FROM watchlist_final_synthesis WHERE symbol=%s", (sym,))
    synthesis = cur.fetchone()

    # QA
    cur.execute("SELECT decision_quality_status, actionable FROM watchlist_analysis_maturity WHERE symbol=%s", (sym,))
    qa = cur.fetchone()

    # Income
    cur.execute("SELECT annual_income, portfolio_income_pct, payout_safety FROM income_asset_profiles WHERE symbol=%s", (sym,))
    income = cur.fetchone()

    episode = {
        "symbol": sym,
        "strategy_type": classification["strategy_type"] if classification else None,
        "classification_source": classification.get("classification_source") if classification else None,
        "baseline_action": rule_eval.get("baseline_action") if rule_eval else None,
        "agent_outputs": {a["agent"]: {"rec": a["recommendation"], "conf": float(a["confidence"] or 0)} for a in agents},
        "synthesis_rec": synthesis.get("recommendation") if synthesis else None,
        "synthesis_conf": float(synthesis.get("confidence", 0) or 0) if synthesis else None,
        "decision_safety": synthesis.get("decision_safety") if synthesis else None,
        "qa_status": qa.get("decision_quality_status") if qa else None,
        "actionable": bool(synthesis.get("actionable")) if synthesis else False,
        "income_annual": float(income.get("annual_income", 0) or 0) if income else 0,
        "income_pct": float(income.get("portfolio_income_pct", 0) or 0) if income else 0,
    }

    # Store episode
    cur.execute("""
        INSERT INTO marl_training_episodes (episode_date, state, actions, rewards, outcome)
        VALUES (CURRENT_DATE, %s, %s, %s, %s)
    """, (
        json.dumps({"classification": dict(classification) if classification else None,
                     "rule_eval": dict(rule_eval) if rule_eval else None,
                     "income": dict(income) if income else None}, default=str),
        json.dumps({"agents": episode["agent_outputs"], "synthesis": episode["synthesis_rec"]}, default=str),
        json.dumps({"safety": episode["decision_safety"], "actionable": episode["actionable"]}, default=str),
        json.dumps({"pending_outcome": True}, default=str),
    ))

    conn.commit()
    conn.close()
    return episode


def log_all_open_decisions() -> list:
    """Log episodes for all symbols with active synthesis."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT symbol FROM watchlist_final_synthesis WHERE superseded IS NOT TRUE")
    symbols = [r["symbol"] for r in cur.fetchall()]
    conn.close()

    results = []
    for sym in symbols:
        try:
            results.append(log_decision_episode(sym))
        except Exception as e:
            print(f"  [marl] {sym}: error — {e}")
    return results


if __name__ == "__main__":
    if "--symbol" in sys.argv:
        sym = sys.argv[sys.argv.index("--symbol") + 1].upper()
        r = log_decision_episode(sym)
        if "--json" in sys.argv:
            print(json.dumps(r, indent=2, default=str))
        else:
            print(f"  Logged: {r['symbol']} strategy={r['strategy_type']} rec={r['synthesis_rec']} safe={r['decision_safety']}")
    elif "--all" in sys.argv:
        results = log_all_open_decisions()
        print(f"[marl] Logged {len(results)} episodes")
        if "--json" in sys.argv:
            print(json.dumps(results, indent=2, default=str))
    else:
        print("Usage: --symbol SCHD [--json] | --all [--json]")
