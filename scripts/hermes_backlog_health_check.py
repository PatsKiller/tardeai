#!/usr/bin/env python3
"""Hermes Research Backlog Health Check — read-only daily report.

Usage:
    python scripts/hermes_backlog_health_check.py

Safety:
    - Read-only: no DB writes, no status changes, no alerts
    - File output only to docs/hermes/backlog_health/
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "docs" / "hermes" / "backlog_health"

STALE_DAYS = 7


def get_db():
    import psycopg2
    try:
        from scripts.lib.env_bootstrap import load_env
    except ImportError:
        from lib.env_bootstrap import load_env
    load_env(names=("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"))
    return psycopg2.connect(host=os.getenv("DB_HOST", "localhost"),
                           port=os.getenv("DB_PORT", "5432"),
                           dbname=os.getenv("DB_NAME", "trade_ai"),
                           user=os.getenv("DB_USER", "trade_ai"),
                           password=os.getenv("DB_PASSWORD", ""))


def _execute():
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    conn = get_db()
    cur = conn.cursor()

    # Fetch all backlog rows
    cur.execute("""
        SELECT id, symbol, topic, status, confidence_score, evidence_json::text,
               tags, created_at
        FROM hermes_research_intelligence
        WHERE research_type = 'research_backlog'
          AND NOT ('duplicate_collapsed' = ANY(tags))
        ORDER BY created_at
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()

    # Parse evidence_json for metadata
    for r in rows:
        ej = json.loads(r["evidence_json"]) if r["evidence_json"] else []
        meta = ej[0] if isinstance(ej, list) and ej else (ej if isinstance(ej, dict) else {})
        r["priority"] = meta.get("priority", "unknown")
        r["owner_agent"] = meta.get("owner_agent", "unknown")
        r["backlog_type"] = meta.get("backlog_type", "unknown")
        r["source_surface"] = meta.get("source_surface", "unknown")
        r["has_research_questions"] = bool(meta.get("research_questions"))
        r["age_days"] = (now - r["created_at"].replace(tzinfo=timezone.utc if r["created_at"].tzinfo is None else r["created_at"].tzinfo)).days

    checks = {}

    # 1. Total
    checks["total_backlog"] = len(rows)

    # 2. Open (staged)
    open_rows = [r for r in rows if r["status"] == "staged"]
    checks["open_count"] = len(open_rows)

    # 3. High priority. Terminal history is evidence, not an open operator queue.
    high = [r for r in open_rows if r["priority"] == "high"]
    checks["high_priority_count"] = len(high)
    checks["historical_high_priority_count"] = sum(
        1 for r in rows if r["priority"] == "high"
    )
    checks["terminal_count"] = len(rows) - len(open_rows)

    # 4. Stale (>7 days)
    stale = [r for r in open_rows if r["age_days"] > STALE_DAYS]
    checks["stale_count"] = len(stale)
    checks["stale_ids"] = [r["id"] for r in stale]

    # 5. Duplicate-like (same symbol + backlog_type)
    seen_keys = {}
    dupes = []
    for r in open_rows:
        key = f"{r['symbol'] or 'NULL'}:{r['backlog_type']}"
        if key in seen_keys:
            dupes.append({"id": r["id"], "duplicate_of": seen_keys[key], "key": key})
        else:
            seen_keys[key] = r["id"]
    checks["duplicate_risk_count"] = len(dupes)
    checks["duplicate_risks"] = dupes

    # 6-9. Missing fields
    checks["missing_owner_agent"] = sum(1 for r in open_rows if r["owner_agent"] == "unknown")
    checks["missing_backlog_type"] = sum(1 for r in open_rows if r["backlog_type"] == "unknown")
    checks["missing_research_questions"] = sum(1 for r in open_rows if not r["has_research_questions"])
    checks["missing_evidence"] = sum(1 for r in open_rows if not r["evidence_json"] or r["evidence_json"] == "[]")
    checks["missing_symbol"] = sum(1 for r in open_rows if not r["symbol"])
    checks["historical_missing_owner_agent"] = sum(
        1 for r in rows if r["owner_agent"] == "unknown"
    )

    # 10. Source surface distribution
    surfaces = Counter(r["source_surface"] for r in rows)
    checks["source_surfaces"] = dict(surfaces)

    # 11. Oldest/newest
    if rows:
        checks["oldest_item"] = {"id": rows[0]["id"], "created": str(rows[0]["created_at"])[:19], "age_days": rows[0]["age_days"]}
        checks["newest_item"] = {"id": rows[-1]["id"], "created": str(rows[-1]["created_at"])[:19], "age_days": rows[-1]["age_days"]}
    else:
        checks["oldest_item"] = None
        checks["newest_item"] = None

    # 12. Ready for source discovery
    ready = [r for r in open_rows if "searxng" in str(r.get("tags", [])) or r["owner_agent"] == "source_discovery_agent"]
    checks["ready_for_discovery"] = len(ready)
    checks["not_ready_for_discovery"] = len(open_rows) - len(ready)

    # 13. Operator review recommendations (top 5 by priority)
    priority_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    sorted_open = sorted(open_rows, key=lambda r: (priority_order.get(r["priority"], 3), -r["age_days"]))
    review_list = [{"id": r["id"], "symbol": r["symbol"], "topic": r["topic"][:60],
                    "priority": r["priority"], "age_days": r["age_days"]} for r in sorted_open[:5]]
    checks["operator_review_list"] = review_list

    # Warnings
    warnings = []
    if checks["stale_count"] > 0:
        warnings.append(f"{checks['stale_count']} stale backlog items (>{STALE_DAYS} days)")
    if checks["duplicate_risk_count"] > 0:
        warnings.append(f"{checks['duplicate_risk_count']} potential duplicates")
    if checks["missing_owner_agent"] > 0:
        warnings.append(f"{checks['missing_owner_agent']} items missing owner agent")

    # Summary
    summary = {
        "date": date_str,
        "timestamp": now.isoformat(),
        "checks": checks,
        "warnings": warnings,
        "total_warnings": len(warnings),
    }

    # Write JSON
    (OUT / "latest_backlog_health_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # Write markdown
    lines = [
        f"# Research Backlog Health Report — {date_str}",
        "",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Total backlog:** {checks['total_backlog']}",
        f"**Open (staged):** {checks['open_count']}",
        f"**Terminal history:** {checks['terminal_count']}",
        f"**High priority:** {checks['high_priority_count']}",
        f"**Stale (>{STALE_DAYS}d):** {checks['stale_count']}",
        f"**Warnings:** {len(warnings)}",
        "",
        "---",
        "",
        "## Priority Distribution",
        "",
    ]
    pri_counts = Counter(r["priority"] for r in rows)
    for p in ["high", "medium", "low", "unknown"]:
        if pri_counts.get(p, 0) > 0:
            lines.append(f"- {p}: {pri_counts[p]}")

    lines += ["", "## Source Surface Distribution", ""]
    for s, c in sorted(surfaces.items()):
        lines.append(f"- {s}: {c}")

    lines += ["", "## Stale Items", ""]
    if stale:
        for r in stale:
            lines.append(f"- id={r['id']} ({r['symbol'] or 'SYSTEM'}) — {r['age_days']} days old — {r['topic'][:50]}")
    else:
        lines.append("None")

    if dupes:
        lines += ["", "## Duplicate Risks", ""]
        for d in dupes:
            lines.append(f"- id={d['id']} may duplicate id={d['duplicate_of']} ({d['key']})")

    lines += ["", "## Operator Review Recommendations", ""]
    for r in review_list:
        lines.append(f"- [{r['priority']}] id={r['id']} ({r['symbol'] or 'SYSTEM'}) — {r['topic']}")

    lines += ["", "---", "", "**Read-only. No DB writes. No status changes. No alerts.**"]

    (OUT / f"{date_str}_backlog_health_report.md").write_text("\n".join(lines))

    print(f"Backlog health: {checks['total_backlog']} total, {checks['open_count']} open, "
          f"{checks['high_priority_count']} high, {checks['stale_count']} stale")
    if warnings:
        print(f"Warnings: {', '.join(warnings)}")
    print(f"Report: {OUT}/{date_str}_backlog_health_report.md")
    print("DB writes: 0 | Status changes: 0 | Alerts: 0")


def main(argv=None) -> int:
    """Inspect the report plan without reading backlog or creating output."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true", help="offline source plan")
    args = parser.parse_args(argv)
    lane = "hermes-backlog-health-check"
    if args.dry_run:
        print(f"DRY-RUN {lane}: would read backlog and write the existing health report; no DB, secrets or files; inputs NOT_MEASURED")
        return 0
    try:
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    except ImportError:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    previous = sys.argv
    sys.argv = [previous[0], *argv]
    try:
        result = _execute()
        rc = int(result) if isinstance(result, int) else 0
    except Exception as exc:
        write_lane_receipt(lane, ok=False, exit_code=1, started_at=started,
                           script="hermes_backlog_health_check.py", error=type(exc).__name__)
        raise
    finally:
        sys.argv = previous
    write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started,
                       script="hermes_backlog_health_check.py", summary={"completed": rc == 0})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
