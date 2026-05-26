# Source Export: scripts/extract_overnight_actionable_outcomes.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/extract_overnight_actionable_outcomes.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `bcce39c9342ea87c4960166dd5844abc91966c63f4e14a185626dd9e89ae5a39` |
| **File Size** | 6055 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""extract_overnight_actionable_outcomes.py — Extract actionable outcomes from deep overnight LLM results.

Populates overnight_actionable_outcomes from deep_overnight_llm_results.
Read-only by default (--dry-run). Use --apply to write.

No trades. No orders. No strategy changes.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")


def extract_verdict(result):
    """Extract structured verdict from result findings/summary."""
    findings = result.get("findings_json") or {}
    if isinstance(findings, str):
        try:
            findings = json.loads(findings)
        except Exception:
            findings = {}

    verdict = findings.get("verdict") or result.get("reentry_verdict") or ""
    confidence = findings.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (ValueError, TypeError):
            confidence = None

    action = findings.get("recommended_action") or findings.get("action") or ""
    lesson = findings.get("lesson") or findings.get("lessons_learned") or ""
    if isinstance(lesson, list):
        lesson = "; ".join(str(l) for l in lesson[:3])

    # Determine if actionable
    actionable_verdicts = {"BUY", "SELL", "TRIM", "ADD", "REENTER", "EXIT", "CLOSE"}
    is_actionable = verdict.upper() in actionable_verdicts or bool(action)

    summary = result.get("summary") or ""
    # Strip markdown code fences from summary
    if summary.startswith("```"):
        summary = summary.split("\n", 1)[-1] if "\n" in summary else summary

    return {
        "parsed_verdict": verdict[:100] if verdict else None,
        "parsed_confidence": confidence,
        "parsed_action": action[:200] if action else None,
        "parsed_lesson": lesson[:500] if lesson else None,
        "parsed_grade": None,
        "is_actionable": is_actionable,
        "action_summary": f"{verdict}: {action[:100]}" if verdict and action else verdict or None,
    }


def main():
    p = argparse.ArgumentParser(description="Extract actionable outcomes from overnight LLM results")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--job-types", type=str, default="recovery_watch_review,closed_trade_review,risk_synthesis")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--output-json", type=str)
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB"); sys.exit(1)
    cur = conn.cursor()

    job_types = [j.strip() for j in args.job_types.split(",")]
    mode = "DRY RUN" if args.dry_run else "APPLY"

    # Find results not yet extracted
    cur.execute("""
        SELECT r.id, r.queue_id, r.job_type, r.symbol, r.summary, r.findings_json,
               r.recommendations_json, r.reentry_verdict, r.created_at
        FROM deep_overnight_llm_results r
        WHERE r.job_type = ANY(%s)
        AND NOT EXISTS (
            SELECT 1 FROM overnight_actionable_outcomes o WHERE o.result_id = r.id
        )
        ORDER BY r.created_at DESC
        LIMIT %s
    """, [job_types, args.limit])
    cols = [d[0] for d in cur.description]
    results = [dict(zip(cols, r)) for r in cur.fetchall()]

    extracted = []
    for r in results:
        verdict = extract_verdict(r)
        entry = {
            "result_id": r["id"],
            "queue_id": r["queue_id"],
            "job_type": r["job_type"],
            "symbol": r["symbol"],
            **verdict,
        }
        extracted.append(entry)

        if not args.dry_run:
            try:
                cur.execute("SELECT 1")  # transaction health check
            except Exception:
                conn.rollback()
                cur = conn.cursor()

            try:
                cur.execute("""
                    INSERT INTO overnight_actionable_outcomes
                        (queue_id, result_id, job_type, symbol, parsed_grade, parsed_lesson,
                         parsed_verdict, parsed_action, parsed_confidence, is_actionable, action_summary)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, [r["queue_id"], r["id"], r["job_type"], r["symbol"],
                      verdict["parsed_grade"], verdict["parsed_lesson"],
                      verdict["parsed_verdict"], verdict["parsed_action"],
                      verdict["parsed_confidence"], verdict["is_actionable"],
                      verdict["action_summary"]])
                conn.commit()
            except Exception as e:
                conn.rollback()
                if args.verbose:
                    print(f"  ERROR {r['symbol']}: {e}")

    actionable_count = sum(1 for e in extracted if e["is_actionable"])

    if args.verbose:
        print(f"[{mode}] Overnight Actionable Outcome Extraction")
        print(f"  Results scanned: {len(results)}")
        print(f"  Extracted: {len(extracted)}")
        print(f"  Actionable: {actionable_count}")
        for e in extracted[:10]:
            print(f"  {e['symbol']:8s} {e['job_type']:25s} verdict={e['parsed_verdict'] or '?':20s} actionable={e['is_actionable']}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "results_scanned": len(results),
        "extracted": len(extracted),
        "actionable": actionable_count,
        "job_types": job_types,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    conn.close()


if __name__ == "__main__":
    main()
```
