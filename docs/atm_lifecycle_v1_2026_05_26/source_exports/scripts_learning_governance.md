# Source Export: scripts/learning_governance.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/learning_governance.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `15b8da261ec22e964303634f66c1de71ca26edc9d1db48e09e396db0d8b68e13` |
| **File Size** | 15333 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""learning_governance.py — Learning governance core module.

Learning can be automatic. Promotion cannot be automatic.
All config changes require admin approval. No silent promotion.

Usage:
    .venv/bin/python scripts/learning_governance.py --status --json
    .venv/bin/python scripts/learning_governance.py --list-proposals --json
    .venv/bin/python scripts/learning_governance.py --list-hypotheses --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SECRET_KEYS = {"password", "token", "secret", "api_key", "cookie", "credential", "private_key"}

# Sample size gates
TRADE_SAMPLE_INSIGHT = 30
TRADE_SAMPLE_SHADOW = 100
SOURCE_SAMPLE_INSIGHT = 50
SOURCE_SAMPLE_SHADOW = 250
AGENT_SAMPLE_INSIGHT = 25
AGENT_SAMPLE_SHADOW = 100


def _get_conn():
    try:
        from session13_db import get_conn
        return get_conn()
    except Exception:
        import psycopg2
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        return psycopg2.connect(host="localhost", dbname="trade_ai",
                                user="trade_ai", password=os.getenv("DB_PASSWORD", ""))


def _uid(prefix=""):
    return f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def redact_sensitive_payload(payload):
    """Remove secret-like keys from payload before DB insert."""
    if not isinstance(payload, dict):
        return payload
    return {k: "***REDACTED***" if any(s in k.lower() for s in SECRET_KEYS) else v
            for k, v in payload.items()}


def compute_sample_size_status(domain, sample_size):
    """Return sample tier: insight_only, shadow_allowed, promotion_allowed."""
    if domain in ("trade_execution", "strategy"):
        if sample_size < TRADE_SAMPLE_INSIGHT:
            return "insight_only"
        if sample_size < TRADE_SAMPLE_SHADOW:
            return "shadow_allowed"
        return "promotion_allowed"
    if domain in ("ingestion", "source_quality", "screener"):
        if sample_size < SOURCE_SAMPLE_INSIGHT:
            return "insight_only"
        if sample_size < SOURCE_SAMPLE_SHADOW:
            return "shadow_allowed"
        return "promotion_allowed"
    if domain in ("agent_calibration",):
        if sample_size < AGENT_SAMPLE_INSIGHT:
            return "insight_only"
        if sample_size < AGENT_SAMPLE_SHADOW:
            return "shadow_allowed"
        return "promotion_allowed"
    # Default conservative
    if sample_size < 30:
        return "insight_only"
    if sample_size < 100:
        return "shadow_allowed"
    return "promotion_allowed"


def validate_no_auto_promotion(status):
    """Block any attempt to silently promote."""
    blocked = {"promoted", "implemented"}
    if status in blocked:
        raise ValueError(f"Auto-promotion blocked: status '{status}' requires admin approval")


# ── CRUD functions ────────────────────────────────────────────────────────

def create_hypothesis(conn, title, domain, hypothesis_type, description="",
                      generated_by="system", symbol=None, strategy_id=None,
                      agent_name=None, sample_size=0, payload=None):
    hid = _uid("HYP_")
    payload = redact_sensitive_payload(payload or {})
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_hypotheses
            (hypothesis_id, title, domain, hypothesis_type, description,
             generated_by, symbol, strategy_id, agent_name, sample_size, payload)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING hypothesis_id
    """, [hid, title, domain, hypothesis_type, description,
          generated_by, symbol, strategy_id, agent_name, sample_size,
          json.dumps(payload, default=str)])
    conn.commit()
    return hid


def add_evidence(conn, hypothesis_id, evidence_type, evidence_data,
                 supports=True, symbol=None, strategy_id=None, agent_name=None,
                 source_table=None, source_id=None, weight=1.0, quality=None):
    eid = _uid("EV_")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_evidence
            (evidence_id, hypothesis_id, evidence_type, source_table, source_id,
             symbol, strategy_id, agent_name, supports_hypothesis, weight,
             quality_score, evidence)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, [eid, hypothesis_id, evidence_type, source_table, source_id,
          symbol, strategy_id, agent_name, supports, weight, quality,
          json.dumps(redact_sensitive_payload(evidence_data), default=str)])
    conn.commit()
    return eid


def create_experiment(conn, hypothesis_id, name, domain, experiment_type,
                      champion_config=None, challenger_config=None, min_sample=30):
    xid = _uid("EXP_")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_experiments
            (experiment_id, hypothesis_id, name, domain, experiment_type,
             champion_config, challenger_config, min_sample_size)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, [xid, hypothesis_id, name, domain, experiment_type,
          json.dumps(champion_config or {}, default=str),
          json.dumps(challenger_config or {}, default=str), min_sample])
    conn.commit()
    return xid


def update_experiment_metrics(conn, experiment_id, metrics, sample_size,
                              result_summary=None, conclusion=None, action=None):
    cur = conn.cursor()
    status = "completed" if conclusion else "running"
    cur.execute("""
        UPDATE learning_experiments
        SET metrics=%s, actual_sample_size=%s, result_summary=%s,
            conclusion=%s, recommended_action=%s, status=%s, updated_at=now()
        WHERE experiment_id=%s
    """, [json.dumps(metrics, default=str), sample_size, result_summary,
          conclusion, action, status, experiment_id])
    conn.commit()


def create_recommendation(conn, hypothesis_id, domain, rec_type, title,
                          summary="", sample_size=0, confidence=None,
                          evidence_summary=None, risk_level="medium",
                          experiment_id=None):
    rid = _uid("REC_")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_recommendations
            (recommendation_id, hypothesis_id, experiment_id, domain,
             recommendation_type, title, summary, evidence_summary,
             sample_size, confidence, risk_level, requires_admin_approval)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
    """, [rid, hypothesis_id, experiment_id, domain, rec_type, title, summary,
          json.dumps(evidence_summary or {}, default=str),
          sample_size, confidence, risk_level])
    conn.commit()
    return rid


def create_config_change_proposal(conn, recommendation_id, domain, target_key,
                                  change_type, current_config=None, proposed_config=None,
                                  reason="", risk_assessment="", rollback_plan=""):
    pid = _uid("CCP_")
    diff = None
    if current_config and proposed_config:
        diff = {"added": {k: v for k, v in proposed_config.items() if k not in current_config},
                "changed": {k: {"old": current_config.get(k), "new": v}
                            for k, v in proposed_config.items()
                            if k in current_config and current_config[k] != v},
                "removed": {k: v for k, v in current_config.items() if k not in proposed_config}}
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO config_change_proposals
            (proposal_id, recommendation_id, domain, target_key, change_type,
             current_config, proposed_config, diff, reason, risk_assessment, rollback_plan)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, [pid, recommendation_id, domain, target_key, change_type,
          json.dumps(redact_sensitive_payload(current_config or {}), default=str),
          json.dumps(redact_sensitive_payload(proposed_config or {}), default=str),
          json.dumps(diff, default=str) if diff else None,
          reason, risk_assessment, rollback_plan])
    conn.commit()
    return pid


def approve_proposal(conn, proposal_id, approved_by, decision="approve_config_change"):
    validate_no_auto_promotion(decision)  # will not raise for approve
    cur = conn.cursor()
    cur.execute("""
        UPDATE config_change_proposals SET status='approved', approved_by=%s,
            approved_at=now(), updated_at=now()
        WHERE proposal_id=%s AND status='proposed'
        RETURNING proposal_id
    """, [approved_by, proposal_id])
    row = cur.fetchone()
    if row:
        record_promotion_decision(conn, proposal_id=proposal_id,
                                  decision=decision, decided_by=approved_by)
    conn.commit()
    return bool(row)


def reject_proposal(conn, proposal_id, rejected_by, reason=""):
    cur = conn.cursor()
    cur.execute("""
        UPDATE config_change_proposals SET status='rejected', rejected_at=now(),
            rejection_reason=%s, updated_at=now()
        WHERE proposal_id=%s AND status IN ('proposed', 'shadow_only')
        RETURNING proposal_id
    """, [reason, proposal_id])
    row = cur.fetchone()
    if row:
        record_promotion_decision(conn, proposal_id=proposal_id,
                                  decision="reject_config_change", decided_by=rejected_by,
                                  rationale=reason)
    conn.commit()
    return bool(row)


def record_promotion_decision(conn, proposal_id=None, recommendation_id=None,
                               hypothesis_id=None, decision="", decided_by="system",
                               rationale="", payload=None):
    did = _uid("DEC_")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_promotion_decisions
            (decision_id, proposal_id, recommendation_id, hypothesis_id,
             decision, decided_by, rationale, decision_payload)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, [did, proposal_id, recommendation_id, hypothesis_id,
          decision, decided_by, rationale,
          json.dumps(redact_sensitive_payload(payload or {}), default=str)])
    conn.commit()
    return did


def record_rollback_event(conn, proposal_id, domain, target_key, reason,
                          prior_config=None, rollback_config=None):
    rid = _uid("RB_")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_rollback_events
            (rollback_id, proposal_id, domain, target_key, rollback_reason,
             prior_config, rollback_config)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, [rid, proposal_id, domain, target_key, reason,
          json.dumps(prior_config or {}, default=str),
          json.dumps(rollback_config or {}, default=str)])
    conn.commit()
    return rid


def require_admin_approval(status):
    """Ensure no config change happens without approval."""
    return status not in ("approved", "implemented")


# ── Status/query functions ────────────────────────────────────────────────

def get_learning_status(conn):
    cur = conn.cursor()
    status = {}
    for tbl, label in [
        ("learning_hypotheses", "hypotheses"),
        ("learning_experiments", "experiments"),
        ("learning_recommendations", "recommendations"),
        ("config_change_proposals", "config_proposals"),
        ("learning_evidence", "evidence_items"),
        ("source_learning_scores", "source_scores"),
        ("strategy_learning_scores", "strategy_scores"),
        ("agent_learning_scores", "agent_scores"),
    ]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            status[f"{label}_total"] = cur.fetchone()[0]
        except Exception:
            status[f"{label}_total"] = 0
            conn.rollback()

    # Status breakdowns
    for tbl, label in [("learning_hypotheses", "hypotheses"), ("config_change_proposals", "proposals")]:
        try:
            cur.execute(f"SELECT status, COUNT(*) FROM {tbl} GROUP BY status")
            status[f"{label}_by_status"] = {r[0]: r[1] for r in cur.fetchall()}
        except Exception:
            status[f"{label}_by_status"] = {}
            conn.rollback()

    # Paper trade stats for sample size context
    try:
        cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'")
        status["closed_paper_trades"] = cur.fetchone()[0]
    except Exception:
        status["closed_paper_trades"] = 0
        conn.rollback()

    status["sample_size_tier"] = compute_sample_size_status("trade_execution",
                                                            status["closed_paper_trades"])
    return status


def main():
    parser = argparse.ArgumentParser(description="Learning Governance")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--list-proposals", action="store_true")
    parser.add_argument("--list-hypotheses", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    conn = _get_conn()
    try:
        if args.status:
            s = get_learning_status(conn)
            if args.json:
                print(json.dumps(s, indent=2, default=str))
            else:
                print(f"Learning Status:")
                for k, v in s.items():
                    print(f"  {k}: {v}")

        if args.list_proposals:
            cur = conn.cursor()
            cur.execute("""SELECT proposal_id, domain, target_key, change_type, status, created_at
                           FROM config_change_proposals ORDER BY created_at DESC LIMIT 20""")
            rows = [{"proposal_id": r[0], "domain": r[1], "target_key": r[2],
                     "change_type": r[3], "status": r[4], "created_at": str(r[5])}
                    for r in cur.fetchall()]
            if args.json:
                print(json.dumps(rows, indent=2, default=str))
            else:
                for r in rows:
                    print(f"  {r['proposal_id']}: {r['domain']}/{r['target_key']} [{r['status']}]")

        if args.list_hypotheses:
            cur = conn.cursor()
            cur.execute("""SELECT hypothesis_id, title, domain, status, sample_size, created_at
                           FROM learning_hypotheses ORDER BY created_at DESC LIMIT 20""")
            rows = [{"hypothesis_id": r[0], "title": r[1], "domain": r[2],
                     "status": r[3], "sample_size": r[4], "created_at": str(r[5])}
                    for r in cur.fetchall()]
            if args.json:
                print(json.dumps(rows, indent=2, default=str))
            else:
                for r in rows:
                    print(f"  {r['hypothesis_id']}: {r['title']} [{r['status']}, n={r['sample_size']}]")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
