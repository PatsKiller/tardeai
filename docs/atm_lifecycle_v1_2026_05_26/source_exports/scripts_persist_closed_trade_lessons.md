# Source Export: scripts/persist_closed_trade_lessons.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/persist_closed_trade_lessons.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `8ef646dc0b6be345b609adf1ceeb04815fbf20869df20536b45c95ac105ad106` |
| **File Size** | 7175 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""persist_closed_trade_lessons.py — Persist postmortem lessons from closed trades into trade_lesson_memory.

Reads closed trades from paper_trades, runs build_postmortem, writes lesson rows.
Read-only unless --apply is passed. No trades, no orders.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from db_adapter import _get_conn
from closed_trade_postmortem_model import build_postmortem


def _load_closed_trades(conn, date_filter):
    """Load closed trades, optionally filtered by date."""
    cur = conn.cursor()
    # Get column names
    cur.execute("SELECT * FROM paper_trades WHERE status='closed' LIMIT 0")
    cols = [desc[0] for desc in cur.description]

    if date_filter == "today":
        cur.execute(
            "SELECT * FROM paper_trades WHERE status='closed' AND closed_at::date = CURRENT_DATE"
        )
        rows = cur.fetchall()
        if not rows:
            if True:  # fallback to all closed
                cur.execute("SELECT * FROM paper_trades WHERE status='closed'")
                rows = cur.fetchall()
    else:
        cur.execute("SELECT * FROM paper_trades WHERE status='closed'")
        rows = cur.fetchall()

    return [dict(zip(cols, row)) for row in rows]


def run(args):
    conn = _get_conn()
    if conn is None:
        print("[ERROR] No database connection available.")
        return {"status": "error", "reason": "no_db_connection"}

    trades = _load_closed_trades(conn, args.date)
    if not trades:
        print("[INFO] No closed trades found.")
        return {"status": "ok", "trades_processed": 0}

    lessons_created = 0
    already_existing = 0
    repeated_patterns = {}
    processed = 0
    errors = []

    cur = conn.cursor()

    for trade in trades:
        try:
            pm = build_postmortem(trade)
        except Exception as e:
            errors.append({"trade_id": trade.get("id"), "error": str(e)})
            continue

        trade_id = pm.get("trade_id")
        exit_reason = pm.get("exit_reason", "")
        lesson_category = pm.get("lesson_category", "")
        repeated_pattern_key = f"{pm.get('strategy', '')}_{pm.get('mistake_type', '')}_{lesson_category}"
        source_payload_hash = hashlib.md5(
            f"{trade_id}_{exit_reason}_{lesson_category}".encode()
        ).hexdigest()

        # Track repeated patterns
        if repeated_pattern_key in repeated_patterns:
            repeated_patterns[repeated_pattern_key] += 1
        else:
            repeated_patterns[repeated_pattern_key] = 1

        if args.apply:
            try:
                cur.execute("""
                    INSERT INTO trade_lesson_memory (
                        trade_id, symbol, strategy_id, close_date, exit_reason,
                        dashboard_verdict, exit_quality, mistake_type, lesson_category,
                        improved_lesson, rule_feedback, next_operator_action,
                        action_priority, action_owner, confidence_delta,
                        repeated_pattern_key, pattern_count, pnl, r_multiple,
                        human_review_only, source_payload_hash
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s
                    ) ON CONFLICT (trade_id, lesson_category, source_payload_hash) DO NOTHING
                """, (
                    trade_id,
                    pm.get("symbol"),
                    pm.get("strategy"),
                    trade.get("closed_at"),
                    exit_reason,
                    pm.get("dashboard_verdict"),
                    pm.get("exit_quality"),
                    pm.get("mistake_type"),
                    lesson_category,
                    pm.get("improved_lesson"),
                    pm.get("rule_feedback"),
                    pm.get("next_operator_action"),
                    pm.get("action_priority"),
                    pm.get("action_owner"),
                    pm.get("confidence_delta"),
                    repeated_pattern_key,
                    repeated_patterns[repeated_pattern_key],
                    pm.get("pnl"),
                    pm.get("r_multiple"),
                    pm.get("human_review_only", True),
                    source_payload_hash,
                ))
                if cur.rowcount > 0:
                    lessons_created += 1
                else:
                    already_existing += 1
            except Exception as e:
                conn.rollback()
                errors.append({"trade_id": trade_id, "error": str(e)})
                continue

        processed += 1

    if args.apply:
        conn.commit()

    repeated_found = {k: v for k, v in repeated_patterns.items() if v >= 2}

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "trades_processed": processed,
        "lessons_created": lessons_created,
        "already_existing": already_existing,
        "repeated_patterns_found": repeated_found,
        "errors": errors,
    }

    mode_label = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode_label}] Trades processed: {processed}, "
          f"Lessons created: {lessons_created}, "
          f"Already existing: {already_existing}, "
          f"Repeated patterns: {len(repeated_found)}")

    if args.verbose:
        for k, v in repeated_found.items():
            print(f"  Repeated: {k} x{v}")
        for e in errors:
            print(f"  Error: trade {e['trade_id']}: {e['error']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(report, indent=2, default=str))
    if args.output_md:
        print(f"\n## Closed Trade Lessons Report")
        print(f"- Mode: {mode_label}")
        print(f"- Trades processed: {processed}")
        print(f"- Lessons created: {lessons_created}")
        print(f"- Already existing: {already_existing}")
        print(f"- Repeated patterns: {len(repeated_found)}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Persist closed trade lessons to trade_lesson_memory")
    parser.add_argument("--date", default="today", help="Date filter: 'today' or 'all' (default: today)")
    parser.add_argument("--dry-run", dest="apply", action="store_false", default=False,
                        help="Preview only (default)")
    parser.add_argument("--apply", dest="apply", action="store_true",
                        help="Write lesson rows")
    parser.add_argument("--output-json", type=str, help="Output JSON path")
    parser.add_argument("--output-md", type=str, help="Output Markdown path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
```
