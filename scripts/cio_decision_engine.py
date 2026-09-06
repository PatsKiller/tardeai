#!/usr/bin/env python3
"""cio_decision_engine.py — CIO-level portfolio decision engine.

Reads all signal/research/QA/rule data and produces prioritized decisions.
No broker execution. Human approval required for high-impact actions.

Usage:
    python3 scripts/cio_decision_engine.py --run [--json]
    python3 scripts/cio_decision_engine.py --symbol SCHD [--json]
"""
import json, os, sys, hashlib
from datetime import datetime, timedelta
from pathlib import Path

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _decision_id(symbol, action):
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"cio-{(symbol or 'portfolio').lower()}-{ts}"


def build_cio_decisions() -> list:
    """Build CIO-level decisions for all classified symbols with sufficient data."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all classified symbols with rule evaluations
    cur.execute("""
        SELECT sre.symbol, sre.strategy_type, sre.baseline_action,
               sre.prohibited_actions, sre.rule_flags, sre.human_review_required as rule_hr,
               tsc.classification_source, tsc.confidence as class_conf,
               fs.decision_safety, fs_synth.recommendation as synth_rec,
               fs_synth.confidence as synth_conf, fs_synth.actionable as synth_actionable,
               iap.annual_income, iap.portfolio_income_pct, iap.payout_safety,
               fused.fused_score, fused.severity as signal_severity, fused.research_score
        FROM strategy_rule_evaluations sre
        JOIN ticker_strategy_classifications tsc ON tsc.symbol = sre.symbol AND tsc.active = TRUE
        LEFT JOIN watchlist_final_synthesis fs_synth ON fs_synth.symbol = sre.symbol AND fs_synth.superseded IS NOT TRUE
        LEFT JOIN (SELECT DISTINCT ON (symbol) * FROM fused_signals ORDER BY symbol, created_at DESC) fused ON fused.symbol = sre.symbol
        LEFT JOIN watchlist_final_synthesis fs ON fs.symbol = sre.symbol
        LEFT JOIN income_asset_profiles iap ON iap.symbol = sre.symbol
        WHERE sre.strategy_type IS NOT NULL
    """)
    evaluations = cur.fetchall()

    # Portfolio context
    holdings = json.loads((STATE_DIR / "holdings.json").read_text()) if (STATE_DIR / "holdings.json").exists() else {}
    total_portfolio = sum(info.get("total_value", 0) for info in holdings.get("account_summaries", {}).values())
    sym_values = {}
    for h in holdings.get("holdings", []):
        sym = h.get("symbol", "")
        sym_values[sym] = sym_values.get(sym, 0) + float(h.get("market_value", 0) or 0)

    # Income goals
    cur.execute("SELECT target_income FROM portfolio_income_goals LIMIT 1")
    goal_row = cur.fetchone()
    target_income = float(goal_row["target_income"]) if goal_row else 55000

    decisions = []
    for ev in evaluations:
        sym = ev["symbol"]
        st = ev["strategy_type"]
        baseline = ev["baseline_action"] or "HOLD"
        weight = round(sym_values.get(sym, 0) / total_portfolio * 100, 2) if total_portfolio > 0 else 0
        income_pct = float(ev.get("portfolio_income_pct", 0) or 0)
        fused_score = float(ev.get("fused_score", 0) or 0)
        signal_sev = ev.get("signal_severity", "low")
        synth_rec = ev.get("synth_rec")
        synth_conf = float(ev.get("synth_conf", 0) or 0)
        safety = ev.get("decision_safety", "pending")
        research_score = float(ev.get("research_score", 0) or 0)

        # Determine CIO action
        action = baseline
        action_class = "routine"
        priority = "normal"
        human_review = bool(ev.get("rule_hr"))
        confidence = 0.5

        # Safety gate
        if safety == "blocked":
            action = "BLOCKED"
            action_class = "blocked"
            priority = "critical"
            human_review = True
        elif safety == "unsafe":
            action = "HUMAN_REVIEW"
            action_class = "review"
            priority = "high"
            human_review = True
        elif synth_rec and synth_rec in ("TRIM", "SELL", "REBALANCE_TRIM"):
            action = "TRIM_REVIEW"
            action_class = "trim"
            priority = "high" if weight > 5 else "normal"
            human_review = weight > 8 or income_pct > 15
            confidence = synth_conf
        elif synth_rec and synth_rec in ("BUY", "ADD", "ADD_ON_PULLBACK"):
            action = "ADD_REVIEW"
            action_class = "add"
            priority = "high" if fused_score > 0.6 else "normal"
            confidence = synth_conf
        elif signal_sev in ("high", "critical"):
            action = "ROTATION_REVIEW"
            action_class = "rotation"
            priority = "high"
            human_review = True
            confidence = fused_score
        else:
            action = baseline
            confidence = 0.5 + (research_score * 0.2)

        # High-impact gates
        if weight > 8 and action in ("TRIM_REVIEW", "ADD_REVIEW"):
            human_review = True
            priority = "critical"
        if income_pct > 15 and action in ("TRIM_REVIEW",):
            human_review = True
            priority = "critical"

        did = _decision_id(sym, action)
        rationale = f"{st} {baseline}. Signal={fused_score:.2f} ({signal_sev}). Weight={weight:.1f}%. Income={income_pct:.0f}%."
        if synth_rec:
            rationale += f" Synthesis={synth_rec} ({synth_conf:.0%})."

        decision = {
            "decision_id": did,
            "symbol": sym,
            "strategy_type": st,
            "action": action,
            "action_class": action_class,
            "priority": priority,
            "confidence_raw": round(confidence, 3),
            "decision_safety": safety if safety != "pending" else ("safe" if not human_review else "review"),
            "human_review_required": human_review,
            "rationale": rationale,
            "expected_income_impact": round(float(ev.get("annual_income", 0) or 0), 2),
            "expected_allocation_impact": weight,
            "status": "proposed",
        }

        # Dedup: skip if same symbol+action+priority already exists within last 24 hours
        existing = None
        try:
            cur.execute("""
                SELECT decision_id FROM cio_decisions
                WHERE symbol = %s AND action = %s AND priority = %s
                  AND created_at > NOW() - INTERVAL '24 hours'
                LIMIT 1
            """, (sym, action, priority))
            existing = cur.fetchone()
        except Exception:
            pass

        if existing:
            continue  # skip duplicate — same recommendation already generated today

        # Per-agent vote snapshot at decision time (2026-07-04 hub audit: agent_votes had
        # been '{}' on every row ever written — decisions weren't auditable against votes).
        agent_votes = {}
        try:
            cur.execute("""SELECT DISTINCT ON (agent) agent, recommendation, confidence
                           FROM watchlist_agent_results
                           WHERE upper(symbol) = %s AND status = 'completed'
                             AND created_at > NOW() - INTERVAL '7 days'
                           ORDER BY agent, created_at DESC""", (sym,))
            agent_votes = {a: {"rec": r, "confidence": float(cf) if cf is not None else None}
                           for a, r, cf in cur.fetchall()}
        except Exception:
            agent_votes = {}

        # Persist
        cur.execute("""
            INSERT INTO cio_decisions
                (decision_id, symbol, strategy_type, action, action_class, priority,
                 confidence_raw, decision_safety, human_review_required, rationale,
                 expected_income_impact, expected_allocation_impact, status, agent_votes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (did, sym, st, action, action_class, priority,
              decision["confidence_raw"], decision["decision_safety"],
              human_review, rationale[:500],
              decision["expected_income_impact"], weight, "proposed",
              json.dumps(agent_votes)))

        decisions.append(decision)

    # Intelligence event
    critical = [d for d in decisions if d["priority"] in ("high", "critical")]
    if critical:
        cur.execute("""
            INSERT INTO portfolio_intelligence_events (event_type, severity, source, payload)
            VALUES ('cio_decision_batch', %s, 'cio_decision_engine.py', %s)
        """, ("high" if any(d["priority"] == "critical" for d in critical) else "info",
              json.dumps({"total": len(decisions), "critical": len(critical),
                          "human_review": sum(1 for d in decisions if d["human_review_required"])}, default=str)))

    conn.commit()
    conn.close()
    return decisions


if __name__ == "__main__":
    with PipelineRun("cio_decision_engine") as _run:
        if "--symbol" in sys.argv:
            sym = sys.argv[sys.argv.index("--symbol") + 1].upper()
            decisions = build_cio_decisions()
            matched = [d for d in decisions if d["symbol"] == sym]
            if "--json" in sys.argv:
                print(json.dumps(matched, indent=2, default=str))
            else:
                for d in matched:
                    print(f"  {d['symbol']:>6} {d['action']:>16} {d['priority']:>8} conf={d['confidence_raw']:.2f} hr={d['human_review_required']} — {d['rationale'][:80]}")
        elif "--run" in sys.argv:
            decisions = build_cio_decisions()
            critical = [d for d in decisions if d["priority"] in ("high", "critical")]
            hr = [d for d in decisions if d["human_review_required"]]
            # Report what was produced. Without this the run records
            # rows_produced=0 and pipeline_zero_rows fires on a working engine —
            # which it did, on 3,010 runs in 7 days.
            _run.rows(len(decisions))
            print(f"[cio] Generated {len(decisions)} decisions: {len(critical)} high/critical, {len(hr)} need human review")
            if "--json" in sys.argv:
                print(json.dumps(decisions[:10], indent=2, default=str))
        else:
            print("Usage: --run [--json] | --symbol SCHD [--json]")

