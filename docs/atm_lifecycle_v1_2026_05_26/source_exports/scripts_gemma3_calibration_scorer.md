# Source Export: scripts/gemma3_calibration_scorer.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/gemma3_calibration_scorer.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `447950f857ccaa96bd5efe293ecd3a6c061a37c2b36e543e8bf0fa7723b815d3` |
| **File Size** | 9361 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""Grade gemma3 overnight predictions against actual outcomes.

Runs nightly after market close. Grades three job types:
1. strategy_classification — did the strategy verdict predict trade outcome?
2. recovery_watch_review — was THESIS_INTACT/INVALIDATED correct?
3. rag_content_curation — was APPROVE_BOOST content actually retrieved?

Usage:
    .venv/bin/python scripts/gemma3_calibration_scorer.py
    .venv/bin/python scripts/gemma3_calibration_scorer.py --seed-only

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def get_db_connection():
    import psycopg2
    env_path = ROOT / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip().strip("'\"")
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def seed_pending_events(conn):
    """Create PENDING calibration events for completed gemma3 jobs that
    don't yet have one. This ensures every gemma3 output gets tracked."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gemma3_calibration_events
            (queue_id, job_type, symbol, gemma3_verdict, grade)
        SELECT q.id, q.job_type, q.symbol,
               COALESCE(
                   r.curation_verdict,
                   r.reentry_verdict,
                   r.cc_verdict,
                   LEFT(r.summary, 80)
               ),
               'PENDING'
        FROM deep_overnight_llm_queue q
        JOIN deep_overnight_llm_results r ON r.queue_id = q.id
        WHERE q.job_type IN (
            'strategy_classification', 'recovery_watch_review', 'rag_content_curation'
        )
        AND q.status = 'done'
        AND q.id NOT IN (SELECT queue_id FROM gemma3_calibration_events WHERE queue_id IS NOT NULL)
    """)
    seeded = cur.rowcount
    conn.commit()
    return seeded


def grade_strategy_classifications(conn):
    """Grade strategy_classification verdicts against closed paper trades.
    CORRECT: gemma said strong fit + trade won; or weak fit + trade lost
    WRONG: gemma said strong fit + trade lost; or weak fit + trade won big
    PARTIAL: mixed signals"""
    cur = conn.cursor()
    graded = 0

    cur.execute("""
        SELECT ce.id, ce.symbol, ce.gemma3_verdict, ce.queue_id,
               pt.id as trade_id, pt.pnl, pt.r_multiple,
               pt.strategy_id, pt.closed_at
        FROM gemma3_calibration_events ce
        JOIN paper_trades pt ON pt.symbol = ce.symbol
            AND pt.lifecycle_state = 'closed'
            AND pt.entry_time > ce.created_at
            AND pt.entry_time < ce.created_at + INTERVAL '14 days'
        WHERE ce.job_type = 'strategy_classification'
          AND ce.grade = 'PENDING'
        LIMIT 50
    """)
    rows = cur.fetchall()

    for row in rows:
        ce_id, symbol, verdict, queue_id, trade_id, pnl, r_mult, strategy_id, closed_at = row
        verdict = verdict or ""
        pnl = float(pnl or 0)
        r_mult = float(r_mult or 0)

        is_strong = "STRONG" in verdict.upper()
        is_weak = "WEAK" in verdict.upper() or "POOR" in verdict.upper()
        trade_won = pnl > 0 and r_mult > 0.5

        if is_strong and trade_won:
            grade, rationale = "CORRECT", f"Strong fit, trade won {r_mult:.2f}R"
        elif is_weak and not trade_won:
            grade, rationale = "CORRECT", f"Weak fit, trade lost (correct caution)"
        elif is_strong and not trade_won:
            grade, rationale = "WRONG", f"Strong fit but trade lost {r_mult:.2f}R"
        elif is_weak and trade_won:
            grade, rationale = "WRONG", f"Weak fit but trade won {r_mult:.2f}R"
        else:
            grade, rationale = "PARTIAL", f"Mixed: {verdict[:30]}, R={r_mult:.2f}"

        try:
            days = abs((closed_at.replace(tzinfo=None) - datetime.now()).days)
        except Exception:
            days = None

        cur.execute("""
            UPDATE gemma3_calibration_events SET
                actual_outcome = %s, outcome_date = %s,
                grade = %s, grade_rationale = %s,
                days_to_outcome = %s, r_multiple_actual = %s
            WHERE id = %s
        """, [
            f"trade_{'won' if trade_won else 'lost'}_{r_mult:.2f}R",
            closed_at, grade, rationale, days, r_mult, ce_id
        ])
        graded += 1

    conn.commit()
    return graded


def grade_recovery_watch(conn):
    """Grade recovery_watch_review verdicts. Check if thesis assessment was correct
    by comparing current price to exit price after 14+ days."""
    cur = conn.cursor()
    graded = 0

    cur.execute("""
        SELECT ce.id, ce.symbol, ce.gemma3_verdict, ce.created_at,
               sd.data->>'price' as current_price,
               sw.exit_price
        FROM gemma3_calibration_events ce
        LEFT JOIN ticker_snapshot_daily sd ON sd.symbol = ce.symbol
            AND sd.snapshot_date = (SELECT MAX(snapshot_date) FROM ticker_snapshot_daily)
        LEFT JOIN stopped_out_watch sw ON sw.symbol = ce.symbol
        WHERE ce.job_type = 'recovery_watch_review'
          AND ce.grade = 'PENDING'
          AND ce.created_at < NOW() - INTERVAL '14 days'
        LIMIT 20
    """)
    rows = cur.fetchall()

    for ce_id, symbol, verdict, created_at, current_price, exit_price in rows:
        try:
            current = float(current_price or 0)
            exit_p = float(exit_price or 0)
            if exit_p == 0:
                continue
            recovered = current > exit_p * 1.05
        except (ValueError, TypeError):
            continue

        verdict = verdict or ""
        thesis_intact = "INTACT" in verdict.upper()

        if thesis_intact and recovered:
            grade, rationale = "CORRECT", "Thesis intact, symbol recovered"
        elif not thesis_intact and not recovered:
            grade, rationale = "CORRECT", "Thesis invalidated, symbol stayed down"
        elif thesis_intact and not recovered:
            grade, rationale = "WRONG", "Thesis intact but symbol did not recover"
        else:
            grade, rationale = "WRONG", "Thesis invalidated but symbol recovered"

        cur.execute("""
            UPDATE gemma3_calibration_events SET
                actual_outcome = %s, grade = %s,
                grade_rationale = %s, outcome_date = NOW()
            WHERE id = %s
        """, [f"price_{'recovered' if recovered else 'stayed_down'}",
              grade, rationale, ce_id])
        graded += 1

    conn.commit()
    return graded


def grade_rag_curation(conn):
    """Grade rag_content_curation verdicts. Check if APPROVE_BOOST content was
    actually retrieved more than APPROVE_STANDARD content."""
    cur = conn.cursor()
    graded = 0

    # For now, just mark rag curation events as PENDING until we have
    # retrieval count tracking. This placeholder prevents them from being
    # re-seeded and will be graded once RAG retrieval logging is added.
    # No actual grading logic yet — needs retrieval count data.

    return graded


def run_scoring(conn):
    seeded = seed_pending_events(conn)
    graded_strat = grade_strategy_classifications(conn)
    graded_recovery = grade_recovery_watch(conn)
    graded_rag = grade_rag_curation(conn)

    cur = conn.cursor()
    cur.execute("""
        SELECT job_type, total_graded, correct, partial, wrong, pending,
               accuracy_pct, tracking_since
        FROM gemma3_accuracy_by_job_type
    """)
    accuracy = cur.fetchall()

    print(f"\n[gemma3_calibration] Results:")
    print(f"  Seeded:  {seeded} new pending events")
    print(f"  Graded:  {graded_strat} strategy, {graded_recovery} recovery, {graded_rag} rag")
    print(f"\n  Accuracy by job type:")
    for row in accuracy:
        jt, total, correct, partial, wrong, pending, acc_pct, since = row
        print(f"    {jt}: {acc_pct}% accuracy ({total} graded, {pending} pending)")

    return {
        "seeded": seeded,
        "graded": graded_strat + graded_recovery + graded_rag,
        "accuracy_by_type": [
            {
                "job_type": r[0], "total_graded": r[1], "correct": r[2],
                "partial": r[3], "wrong": r[4], "pending": r[5],
                "accuracy_pct": float(r[6]) if r[6] else None,
                "tracking_since": r[7].isoformat() if r[7] else None,
            }
            for r in accuracy
        ],
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Grade gemma3 overnight predictions")
    parser.add_argument("--seed-only", action="store_true", help="Only seed, don't grade")
    args = parser.parse_args()

    conn = get_db_connection()

    if args.seed_only:
        seeded = seed_pending_events(conn)
        print(f"Seeded {seeded} pending calibration events")
    else:
        result = run_scoring(conn)
        print(json.dumps(result, indent=2, default=str))

    conn.close()
```
