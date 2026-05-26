#!/usr/bin/env python3
"""report_trade_lesson_memory.py — Read-only report on trade_lesson_memory contents.

Queries counts by strategy, mistake_type, action_priority, lesson_category,
repeated_pattern_key, and operator_review_status. No writes.
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from db_adapter import _get_conn


def _query_counts(cur, column, since_date):
    """Query counts grouped by a column."""
    cur.execute(f"""
        SELECT {column}, COUNT(*) as cnt
        FROM trade_lesson_memory
        WHERE created_at >= %s
        GROUP BY {column}
        ORDER BY cnt DESC
    """, (since_date,))
    return [{"value": r[0], "count": r[1]} for r in cur.fetchall()]


def run(args):
    conn = _get_conn()
    if conn is None:
        print("[ERROR] No database connection available.")
        return {"status": "error", "reason": "no_db_connection"}

    since_date = (datetime.now(timezone.utc) - timedelta(days=args.since_days)).date()
    cur = conn.cursor()

    # Total count
    cur.execute("SELECT COUNT(*) FROM trade_lesson_memory WHERE created_at >= %s", (since_date,))
    total = cur.fetchone()[0]

    # Breakdowns
    by_strategy = _query_counts(cur, "strategy_id", since_date)
    by_mistake = _query_counts(cur, "mistake_type", since_date)
    by_priority = _query_counts(cur, "action_priority", since_date)
    by_category = _query_counts(cur, "lesson_category", since_date)

    # Repeated patterns (count >= 2)
    cur.execute("""
        SELECT repeated_pattern_key, COUNT(*) as cnt
        FROM trade_lesson_memory
        WHERE created_at >= %s AND repeated_pattern_key IS NOT NULL
        GROUP BY repeated_pattern_key
        HAVING COUNT(*) >= 2
        ORDER BY cnt DESC
    """, (since_date,))
    repeated_patterns = [{"pattern": r[0], "count": r[1]} for r in cur.fetchall()]

    # Operator review status
    by_review_status = _query_counts(cur, "operator_review_status", since_date)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "since_days": args.since_days,
        "since_date": since_date.isoformat(),
        "total_lessons": total,
        "by_strategy": by_strategy,
        "by_mistake_type": by_mistake,
        "by_action_priority": by_priority,
        "by_lesson_category": by_category,
        "repeated_patterns": repeated_patterns,
        "by_operator_review_status": by_review_status,
    }

    print(f"[REPORT] Trade Lesson Memory — last {args.since_days} days ({since_date})")
    print(f"  Total lessons: {total}")
    print(f"  Strategies: {len(by_strategy)}")
    print(f"  Repeated patterns (>=2): {len(repeated_patterns)}")

    if args.verbose:
        print(f"\n  By Strategy:")
        for item in by_strategy:
            print(f"    {item['value']}: {item['count']}")
        print(f"\n  By Mistake Type:")
        for item in by_mistake:
            print(f"    {item['value']}: {item['count']}")
        print(f"\n  By Action Priority:")
        for item in by_priority:
            print(f"    {item['value']}: {item['count']}")
        print(f"\n  By Lesson Category:")
        for item in by_category:
            print(f"    {item['value']}: {item['count']}")
        print(f"\n  Repeated Patterns:")
        for item in repeated_patterns:
            print(f"    {item['pattern']}: {item['count']}")
        print(f"\n  By Review Status:")
        for item in by_review_status:
            print(f"    {item['value']}: {item['count']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(report, indent=2, default=str))
    if args.output_md:
        print(f"\n## Trade Lesson Memory Report")
        print(f"- Period: last {args.since_days} days (since {since_date})")
        print(f"- Total lessons: {total}")
        print(f"\n### By Strategy")
        for item in by_strategy:
            print(f"- {item['value']}: {item['count']}")
        print(f"\n### By Mistake Type")
        for item in by_mistake:
            print(f"- {item['value']}: {item['count']}")
        print(f"\n### By Action Priority")
        for item in by_priority:
            print(f"- {item['value']}: {item['count']}")
        print(f"\n### Repeated Patterns (>=2)")
        for item in repeated_patterns:
            print(f"- {item['pattern']}: {item['count']}")
        print(f"\n### Review Status")
        for item in by_review_status:
            print(f"- {item['value']}: {item['count']}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Report on trade_lesson_memory contents")
    parser.add_argument("--since-days", type=int, default=30, help="Look back N days (default: 30)")
    parser.add_argument("--output-json", type=str, help="Output JSON path")
    parser.add_argument("--output-md", type=str, help="Output Markdown path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
