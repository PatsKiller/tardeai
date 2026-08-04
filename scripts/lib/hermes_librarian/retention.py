"""Retention policy engine — config-driven retention ladder.

Consolidates hardcoded retention windows from hermes_autonomous_self_tune.py
and the hermes_research_curator.py into a single policy config.

Lifecycle: live → hidden/flagged → archived → purge (never deletes live rows).
"""
from __future__ import annotations

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "config" / "hermes_librarian_policy.yaml"

DEFAULT_RETENTION = {
    "hermes_research_intelligence": {
        "staged_max_days": 90,
        "promoted_max_days": 365,
        "archived_purge_days": 180,  # purge archived rows after 6mo
    },
    "hermes_score_history": {
        "max_days": 21,  # already handled by hermes_score_history_retention.py
    },
    "hermes_discovery_candidates": {
        "cold_archive_days": 90,  # ARCHIVED_COLD after 90d idle
    },
    "content_embeddings": {
        "orphan_purge_days": 30,  # purge embeddings whose source row is gone
    },
    "hermes_embedding_queue": {
        "failed_purge_days": 14,
    },
}


def load_policy():
    if POLICY_PATH.exists():
        return yaml.safe_load(POLICY_PATH.read_text())
    return DEFAULT_RETENTION


def apply_retention(conn, *, dry_run: bool = False) -> dict:
    """Apply retention policy per table. Returns summary of actions."""
    policy = load_policy()
    cur = conn.cursor()
    actions = []

    # 1. Archive staged research older than staged_max_days
    staged_cfg = policy.get("hermes_research_intelligence", {}).get("staged_max_days", 90)
    cur.execute("""
        SELECT COUNT(*) FROM hermes_research_intelligence
        WHERE status = 'staged' AND created_at < CURRENT_DATE - %s::int
    """, (staged_cfg,))
    staged_count = cur.fetchone()[0]
    if staged_count > 0 and not dry_run:
        cur.execute("""
            UPDATE hermes_research_intelligence
            SET status = 'archived',
                tags = array_append(coalesce(tags, ARRAY[]::text[]), 'auto_archived')
            WHERE status = 'staged' AND created_at < CURRENT_DATE - %s::int
        """, (staged_cfg,))
        conn.commit()
    actions.append({"table": "hermes_research_intelligence", "action": "archive_staged",
                    "count": staged_count, "threshold_days": staged_cfg})

    # 2. Purge archived research
    purge_cfg = policy.get("hermes_research_intelligence", {}).get("archived_purge_days", 180)
    cur.execute("""
        SELECT COUNT(*) FROM hermes_research_intelligence
        WHERE status = 'archived' AND created_at < CURRENT_DATE - %s::int
    """, (purge_cfg,))
    archived_count = cur.fetchone()[0]
    if archived_count > 0 and not dry_run:
        cur.execute("""
            DELETE FROM hermes_research_intelligence
            WHERE status = 'archived' AND created_at < CURRENT_DATE - %s::int
        """, (purge_cfg,))
        conn.commit()
    actions.append({"table": "hermes_research_intelligence", "action": "purge_archived",
                    "count": archived_count, "threshold_days": purge_cfg})

    # 3. Cold-archive old discovery candidates
    cold_cfg = policy.get("hermes_discovery_candidates", {}).get("cold_archive_days", 90)
    cur.execute("""
        SELECT COUNT(*) FROM hermes_discovery_candidates
        WHERE status NOT IN ('ARCHIVED_COLD', 'REJECTED', 'BLOCKED', 'PROMOTED_TO_WATCH_EVALUATION')
          AND updated_at < CURRENT_DATE - %s::int
    """, (cold_cfg,))
    cold_count = cur.fetchone()[0]
    if cold_count > 0 and not dry_run:
        cur.execute("""
            UPDATE hermes_discovery_candidates
            SET status = 'ARCHIVED_COLD', updated_at = NOW()
            WHERE status NOT IN ('ARCHIVED_COLD', 'REJECTED', 'BLOCKED', 'PROMOTED_TO_WATCH_EVALUATION')
              AND updated_at < CURRENT_DATE - %s::int
        """, (cold_cfg,))
        conn.commit()
    actions.append({"table": "hermes_discovery_candidates", "action": "cold_archive",
                    "count": cold_count, "threshold_days": cold_cfg})

    # 4. Purge failed embedding queue entries
    failed_cfg = policy.get("hermes_embedding_queue", {}).get("failed_purge_days", 14)
    cur.execute("""
        SELECT COUNT(*) FROM hermes_embedding_queue
        WHERE embedding_status = 'failed' AND created_at < CURRENT_DATE - %s::int
    """, (failed_cfg,))
    failed_count = cur.fetchone()[0]
    if failed_count > 0 and not dry_run:
        cur.execute("""
            DELETE FROM hermes_embedding_queue
            WHERE embedding_status = 'failed' AND created_at < CURRENT_DATE - %s::int
        """, (failed_cfg,))
        conn.commit()
    actions.append({"table": "hermes_embedding_queue", "action": "purge_failed",
                    "count": failed_count, "threshold_days": failed_cfg})

    cur.close()
    return {
        "mode": "dry-run" if dry_run else "apply",
        "total_affected": sum(a["count"] for a in actions),
        "actions": actions,
    }
