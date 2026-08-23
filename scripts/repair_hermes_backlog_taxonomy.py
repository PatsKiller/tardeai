#!/usr/bin/env python3
"""Repair Autonomous Librarian backlog taxonomy without changing lifecycle status.

Default is a read-only preview. ``--apply`` updates only evidence_json on rows whose
writer/finding type can be classified deterministically. No broker or trading tables
are read or written.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def classify(finding_type: str) -> dict[str, object] | None:
    from hermes_autonomous_librarian_backlog_loop import (
        BACKLOG_TYPE_BY_FINDING,
        OWNER_BY_FINDING,
        QUESTION_BY_FINDING,
        SURFACE_BY_FINDING,
    )

    key = str(finding_type or "").strip()
    if key not in OWNER_BY_FINDING:
        return None
    return {
        "owner_agent": OWNER_BY_FINDING[key],
        "backlog_type": BACKLOG_TYPE_BY_FINDING[key],
        "research_questions": [QUESTION_BY_FINDING[key]],
        "source_surface": SURFACE_BY_FINDING[key],
    }


def repair_payload(raw: object) -> tuple[object, bool]:
    payload = raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw, False
    rows = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    if not rows or not isinstance(rows[0], dict):
        return payload, False
    meta = dict(rows[0])
    patch = classify(str(meta.get("finding_type") or ""))
    if not patch:
        return payload, False
    changed = False
    for key, value in patch.items():
        if not meta.get(key) or meta.get(key) == "unknown":
            meta[key] = value
            changed = True
    if not changed:
        return payload, False
    rows[0] = meta
    return rows if isinstance(payload, list) else meta, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    from db_adapter import _get_conn

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, evidence_json FROM hermes_research_intelligence
           WHERE research_type='research_backlog'
             AND hermes_agent_name='autonomous_librarian_loop'
           ORDER BY id LIMIT %s""",
        (max(1, args.limit),),
    )
    candidates = []
    for row_id, raw in cur.fetchall():
        repaired, changed = repair_payload(raw)
        if changed:
            candidates.append((row_id, repaired))

    if args.apply:
        for row_id, repaired in candidates:
            cur.execute(
                """UPDATE hermes_research_intelligence
                   SET evidence_json=%s::jsonb, updated_at=NOW()
                   WHERE id=%s AND research_type='research_backlog'
                     AND hermes_agent_name='autonomous_librarian_loop'""",
                (json.dumps(repaired), row_id),
            )
        conn.commit()
    else:
        conn.rollback()
    cur.close()
    conn.close()
    print(json.dumps({
        "schema": "HermesBacklogTaxonomyRepair@v1",
        "mode": "APPLY" if args.apply else "PREVIEW",
        "eligible_rows": len(candidates),
        "updated_rows": len(candidates) if args.apply else 0,
        "status_changes": 0,
        "broker_writes": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
