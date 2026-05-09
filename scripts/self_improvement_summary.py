#!/usr/bin/env python3
"""self_improvement_summary.py — Unified read-only aggregator for all self-improvement subsystems.

No config changes. No approvals. No broker actions. Read-only aggregation.

Usage:
    .venv/bin/python scripts/self_improvement_summary.py --status --json
    .venv/bin/python scripts/self_improvement_summary.py --snapshot --dry-run --json
    .venv/bin/python scripts/self_improvement_summary.py --review-queue --json
    .venv/bin/python scripts/self_improvement_summary.py --component-health --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _f(v): return float(v) if isinstance(v, Decimal) else v
def _uid(p="SIS_"): return f"{p}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()

def _safe(cur, sql):
    try:
        cur.execute(sql)
        return cur.fetchone()[0]
    except Exception:
        cur.connection.rollback()
        return 0


def collect_status(conn):
    cur = conn.cursor()
    s = {}

    # Safety
    try:
        from live_trading_gate import evaluate
        gate = evaluate()
        s["safety"] = {"mode": gate["mode"], "allowed": gate["allowed"],
                       "blocked_reasons": gate["blocked_reasons"],
                       "alpaca_mode": gate["gates"].get("alpaca_mode"),
                       "holdings_guard": True}
    except Exception:
        s["safety"] = {"mode": "PAPER", "allowed": False, "blocked_reasons": ["gate_unavailable"]}

    try:
        h = json.load(open(PROJECT_ROOT / "data/portfolios/state/holdings.json"))
        s["safety"]["holdings_value"] = h["portfolio_totals"]["total_value"]
        s["safety"]["holdings_guard"] = h["portfolio_totals"]["total_value"] > 1_000_000
    except Exception:
        s["safety"]["holdings_value"] = 0; s["safety"]["holdings_guard"] = False

    # Paper trading
    s["paper_trading"] = {
        "open": _safe(cur, "SELECT COUNT(*) FROM paper_trades WHERE status='open'"),
        "closed": _safe(cur, "SELECT COUNT(*) FROM paper_trades WHERE status='closed'"),
        "pending_proposals": _safe(cur, "SELECT COUNT(*) FROM paper_trade_proposals WHERE status IN ('PROPOSED','PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')"),
        "low_sample": _safe(cur, "SELECT COUNT(*) FROM paper_trades WHERE status='closed'") < 30,
    }

    # Execution revalidation
    s["execution_revalidation"] = {
        "pending_rechecks": _safe(cur, "SELECT COUNT(*) FROM paper_trade_execution_rechecks WHERE status IN ('pending','delayed')"),
        "material_changes": _safe(cur, "SELECT COUNT(*) FROM paper_trade_proposals WHERE material_change_pending_approval=true"),
    }

    # Learning governance
    s["learning"] = {
        "hypotheses": _safe(cur, "SELECT COUNT(*) FROM learning_hypotheses"),
        "experiments": _safe(cur, "SELECT COUNT(*) FROM learning_experiments"),
        "recommendations_pending": _safe(cur, "SELECT COUNT(*) FROM learning_recommendations WHERE status='proposed'"),
        "config_proposals_pending": _safe(cur, "SELECT COUNT(*) FROM config_change_proposals WHERE status='proposed'"),
    }

    # Agent calibration
    s["agent_calibration"] = {
        "recommendations": _safe(cur, "SELECT COUNT(*) FROM agent_recommendation_registry"),
        "calibration_events": _safe(cur, "SELECT COUNT(*) FROM agent_calibration_events"),
        "weight_proposals": _safe(cur, "SELECT COUNT(*) FROM agent_weight_shadow_proposals WHERE status='proposed'"),
        "disagreements": _safe(cur, "SELECT COUNT(*) FROM agent_disagreement_outcomes"),
    }

    # Digest/thesis
    s["weekly_digest"] = {
        "digests": _safe(cur, "SELECT COUNT(*) FROM weekly_learning_digests"),
        "thesis_reviews": _safe(cur, "SELECT COUNT(*) FROM trade_thesis_reviews"),
    }

    # Backtesting
    s["backtesting"] = {
        "runs": _safe(cur, "SELECT COUNT(*) FROM strategy_backtest_runs"),
        "trades": _safe(cur, "SELECT COUNT(*) FROM strategy_backtest_trades"),
        "challengers": _safe(cur, "SELECT COUNT(*) FROM challenger_definitions"),
    }

    # Pipeline
    s["pipeline"] = {
        "stages": _safe(cur, "SELECT COUNT(*) FROM pipeline_stages WHERE active=true"),
        "runs": _safe(cur, "SELECT COUNT(*) FROM pipeline_runs"),
        "failures": _safe(cur, "SELECT COUNT(*) FROM pipeline_stage_runs WHERE status='failed'"),
    }

    # Source health
    try:
        cur.execute("SELECT COUNT(*) FILTER (WHERE degraded=true), COUNT(*) FROM data_source_health")
        row = cur.fetchone()
        s["sources"] = {"degraded": row[0], "total": row[1]}
    except Exception:
        s["sources"] = {"degraded": 0, "total": 0}
        conn.rollback()

    # Warnings
    warnings = []
    if s["paper_trading"]["low_sample"]:
        warnings.append({"type": "low_sample", "msg": f"Only {s['paper_trading']['closed']} closed trades (need 30+)"})
    if s["learning"]["config_proposals_pending"] > 0:
        warnings.append({"type": "approval_needed", "msg": f"{s['learning']['config_proposals_pending']} config proposals pending"})
    if s["learning"]["recommendations_pending"] > 0:
        warnings.append({"type": "review_needed", "msg": f"{s['learning']['recommendations_pending']} recommendations pending review"})
    if s["execution_revalidation"]["material_changes"] > 0:
        warnings.append({"type": "reapproval", "msg": f"{s['execution_revalidation']['material_changes']} material changes pending reapproval"})
    if s["sources"]["degraded"] > 0:
        warnings.append({"type": "source_degraded", "msg": f"{s['sources']['degraded']} sources degraded"})
    s["warnings"] = warnings

    # Operator actions
    actions = []
    if s["learning"]["config_proposals_pending"] > 0:
        actions.append({"action": "Review config proposals", "route": "/v2/learning-governance"})
    if s["execution_revalidation"]["material_changes"] > 0:
        actions.append({"action": "Review execution rechecks", "route": "/v2/paper-trade-intelligence"})
    if s["agent_calibration"]["weight_proposals"] > 0:
        actions.append({"action": "Review agent weight proposals", "route": "/v2/agent-calibration"})
    s["recommended_actions"] = actions

    return s


def build_review_queue(conn, status):
    """Build operator review queue from current status."""
    items = []

    if status["learning"]["config_proposals_pending"] > 0:
        items.append({"review_item_id": _uid("RQ_"), "source_domain": "learning_governance",
                       "title": f"{status['learning']['config_proposals_pending']} config proposals pending",
                       "severity": "important", "review_type": "approval_needed",
                       "linked_dashboard_route": "/v2/learning-governance", "requires_action": True})

    if status["learning"]["recommendations_pending"] > 0:
        items.append({"review_item_id": _uid("RQ_"), "source_domain": "learning_governance",
                       "title": f"{status['learning']['recommendations_pending']} recommendations pending",
                       "severity": "normal", "review_type": "decision_needed",
                       "linked_dashboard_route": "/v2/learning-governance"})

    if status["execution_revalidation"]["material_changes"] > 0:
        items.append({"review_item_id": _uid("RQ_"), "source_domain": "execution_revalidation",
                       "title": f"{status['execution_revalidation']['material_changes']} execution material changes",
                       "severity": "warning", "review_type": "approval_needed",
                       "linked_dashboard_route": "/v2/paper-trade-intelligence", "requires_action": True})

    if status["paper_trading"]["low_sample"]:
        items.append({"review_item_id": _uid("RQ_"), "source_domain": "safety",
                       "title": f"Low sample size: {status['paper_trading']['closed']} closed trades",
                       "severity": "info", "review_type": "low_sample_warning",
                       "linked_dashboard_route": "/v2/weekly-learning"})

    if status["sources"]["degraded"] > 0:
        items.append({"review_item_id": _uid("RQ_"), "source_domain": "source_health",
                       "title": f"{status['sources']['degraded']} sources degraded",
                       "severity": "warning", "review_type": "stale_data",
                       "linked_dashboard_route": "/v2/pipeline-controller"})

    if status["pipeline"]["failures"] > 0:
        items.append({"review_item_id": _uid("RQ_"), "source_domain": "pipeline",
                       "title": f"{status['pipeline']['failures']} pipeline stage failures",
                       "severity": "warning", "review_type": "failed_pipeline",
                       "linked_dashboard_route": "/v2/pipeline-controller"})

    return items


def build_component_health(conn, status):
    """Build component health from status."""
    components = []
    for key, name, check in [
        ("safety_gate", "Safety Gate", lambda: "healthy" if not status["safety"]["allowed"] else "warning"),
        ("paper_trading", "Paper Trading", lambda: "healthy"),
        ("execution_revalidation", "Execution Revalidation", lambda: "warning" if status["execution_revalidation"]["material_changes"] > 0 else "healthy"),
        ("learning_governance", "Learning Governance", lambda: "healthy"),
        ("agent_calibration", "Agent Calibration", lambda: "healthy" if status["agent_calibration"]["recommendations"] > 0 else "unknown"),
        ("weekly_digest", "Weekly Digest", lambda: "healthy" if status["weekly_digest"]["digests"] > 0 else "unknown"),
        ("backtesting", "Backtesting", lambda: "healthy" if status["backtesting"]["runs"] > 0 else "unknown"),
        ("pipeline_controller", "Pipeline Controller", lambda: "warning" if status["pipeline"]["failures"] > 0 else "healthy"),
        ("ingestion_sources", "Ingestion Sources", lambda: "degraded" if status["sources"]["degraded"] > 0 else "healthy"),
    ]:
        components.append({"component_key": key, "component_name": name, "status": check()})
    return components


def save_snapshot(conn, status, queue, health, dry_run=True):
    if dry_run:
        return _uid()
    sid = _uid()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO self_improvement_snapshots
            (snapshot_id, safety_status, paper_trading_summary, execution_revalidation_summary,
             learning_governance_summary, agent_calibration_summary, weekly_digest_summary,
             backtesting_summary, pipeline_summary, ingestion_source_summary,
             review_queue_summary, warnings, recommended_operator_actions,
             low_sample_warnings)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, [sid, json.dumps(status.get("safety"), default=str),
          json.dumps(status.get("paper_trading"), default=str),
          json.dumps(status.get("execution_revalidation"), default=str),
          json.dumps(status.get("learning"), default=str),
          json.dumps(status.get("agent_calibration"), default=str),
          json.dumps(status.get("weekly_digest"), default=str),
          json.dumps(status.get("backtesting"), default=str),
          json.dumps(status.get("pipeline"), default=str),
          json.dumps(status.get("sources"), default=str),
          json.dumps({"items": len(queue)}, default=str),
          json.dumps(status.get("warnings"), default=str),
          json.dumps(status.get("recommended_actions"), default=str),
          json.dumps([w for w in status.get("warnings", []) if w.get("type") == "low_sample"], default=str)])

    # Save component health
    for c in health:
        cur.execute("""
            INSERT INTO self_improvement_component_health (component_key, component_name, status, last_checked_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (component_key) DO UPDATE SET status=EXCLUDED.status, last_checked_at=now(), updated_at=now()
        """, [c["component_key"], c["component_name"], c["status"]])

    conn.commit()
    return sid


def main():
    parser = argparse.ArgumentParser(description="Self-Improvement Summary Aggregator")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument("--review-queue", action="store_true")
    parser.add_argument("--component-health", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = _get_conn()
    try:
        status = collect_status(conn)

        if args.status:
            if args.json:
                print(json.dumps(status, indent=2, default=str))
            else:
                print(f"Safety: {status['safety']['mode']}")
                print(f"Holdings: ${status['safety'].get('holdings_value', 0):,.0f}")
                print(f"Paper: {status['paper_trading']['closed']} closed, {status['paper_trading']['open']} open")
                print(f"Warnings: {len(status['warnings'])}")
                print(f"Actions: {len(status['recommended_actions'])}")

        if args.review_queue:
            queue = build_review_queue(conn, status)
            if args.json:
                print(json.dumps(queue, indent=2, default=str))
            else:
                for q in queue:
                    print(f"  [{q['severity']}] {q['title']}")

        if args.component_health:
            health = build_component_health(conn, status)
            if args.json:
                print(json.dumps(health, indent=2, default=str))
            else:
                for c in health:
                    print(f"  {c['component_key']}: {c['status']}")

        if args.snapshot:
            queue = build_review_queue(conn, status)
            health = build_component_health(conn, status)
            sid = save_snapshot(conn, status, queue, health, dry_run=dry_run)
            out = {"mode": "dry_run" if dry_run else "applied", "snapshot_id": sid,
                   "warnings": len(status["warnings"]), "review_items": len(queue),
                   "components": len(health)}
            if args.json:
                out["status"] = status
                print(json.dumps(out, indent=2, default=str))
            else:
                print(f"Snapshot: {sid} ({out['mode']}), {out['warnings']} warnings, {out['review_items']} items")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
