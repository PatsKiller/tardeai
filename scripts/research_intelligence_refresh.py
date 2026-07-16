#!/usr/bin/env python3
"""Research Intelligence freshness + archive maintenance.

- Reports category freshness vs SLO
- Marks stale low-priority Hermes rows as archived (searchable, not deleted)
- Never auto-archives retirement_tax primary topics
- Optionally lists topic_monitor rows due for re-ingest

Usage:
  python scripts/research_intelligence_refresh.py              # report only
  python scripts/research_intelligence_refresh.py --archive    # apply archive
  python scripts/research_intelligence_refresh.py --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.research_intelligence import (  # noqa: E402
    classify_text,
    freshness_report,
    load_freshness_policy,
)


def _archive_stale_hermes(*, apply: bool, days: int, dry_limit: int = 200) -> dict:
    """Archive old non-retirement Hermes rows. Archive ≠ delete."""
    from db_adapter import _execute

    policy = load_freshness_policy()
    never = set((policy.get("archive") or {}).get("never_auto_archive_categories") or ["retirement_tax"])
    days = days or int((policy.get("archive") or {}).get("hermes_auto_archive_after_days") or 45)

    rows = _execute(
        """
        SELECT id, topic, summary, thesis, research_type, status, created_at
        FROM hermes_research_intelligence
        WHERE status IN ('staged', 'reviewed', 'promoted')
          AND created_at < NOW() - make_interval(days => %s)
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (int(days), dry_limit),
        fetch="all",
    ) or []

    candidates, skipped = [], []
    for r in rows:
        cats = classify_text(r.get("topic"), r.get("summary"), r.get("thesis"),
                             research_type=r.get("research_type"))
        primary = cats[0] if cats else ""
        if primary in never or any(c in never for c in cats[:1]):
            skipped.append({"id": r["id"], "topic": (r.get("topic") or "")[:60], "reason": "retirement_pillar"})
            continue
        # Keep high-signal catalyst/risk recent noise? Archive old risk stop noise freely
        candidates.append({"id": r["id"], "topic": (r.get("topic") or "")[:60], "cats": cats, "status": r.get("status")})

    archived_ids = []
    if apply and candidates:
        ids = [c["id"] for c in candidates]
        # batch update
        _execute(
            """
            UPDATE hermes_research_intelligence
            SET status = 'archived',
                updated_at = NOW()
            WHERE id = ANY(%s)
              AND status IN ('staged', 'reviewed', 'promoted')
            """,
            (ids,),
            fetch=None,
        )
        archived_ids = ids

    return {
        "archive_after_days": days,
        "candidates": len(candidates),
        "skipped_protected": len(skipped),
        "archived": len(archived_ids) if apply else 0,
        "apply": apply,
        "sample": candidates[:8],
        "skipped_sample": skipped[:5],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="store_true", help="Apply auto-archive of stale rows")
    ap.add_argument("--days", type=int, default=0, help="Override archive age days")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from db_adapter import _execute, USE_DB
    if not USE_DB:
        print("DB unavailable", file=sys.stderr)
        return 2

    def db_query(sql, params=None, fetch="all"):
        return _execute(sql, params, fetch=fetch)

    report = freshness_report(db_query=db_query)
    arch = _archive_stale_hermes(apply=args.archive, days=args.days or 0)

    out = {
        "ok": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "freshness": report,
        "archive_run": arch,
    }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"[ri-refresh] as_of={out['as_of']}")
        print(f"  stale topics due: {report.get('stale_topic_count')}")
        by = report.get("by_category") or {}
        for cat, d in sorted(by.items(), key=lambda x: -x[1].get("count", 0))[:10]:
            slo = "OK" if d.get("slo_ok") else "BREACH"
            print(f"  {cat:22} n={d.get('count'):3} refresh={d.get('needs_refresh'):3} "
                  f"avg_age={d.get('avg_age_h')}h freshest={d.get('freshest_h')}h slo={slo}")
        print(f"  archive candidates={arch['candidates']} protected_skip={arch['skipped_protected']} "
              f"archived={arch['archived']} apply={arch['apply']}")
        if report.get("stale_topics"):
            print("  top stale monitors:")
            for t in (report.get("stale_topics") or [])[:8]:
                print(f"    - {t.get('topic_id')}: age={t.get('age_hours')}h max={t.get('max_age_hours')}h")
        print(f"  queued research (stubs off the desk): {report.get('queued_research_count')}")
        print("  next-action label distribution (cap 20% per label):")
        for d in report.get("action_label_distribution") or []:
            print(f"    {d['pct']:5.1f}%  n={d['count']:3}  {d['label']}")
        over = report.get("action_labels_over_20pct") or []
        if over:
            print(f"  ⚠ {len(over)} label(s) over the 20% cap: "
                  + ", ".join(f"{d['label']} ({d['pct']}%)" for d in over))
        else:
            print("  ✓ no action label exceeds 20% of briefs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
