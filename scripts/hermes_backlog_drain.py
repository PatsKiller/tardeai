#!/usr/bin/env python3
"""hermes_backlog_drain.py — drain research_backlog staged rows into real research.

Picks priority backlog findings, runs LLM analysis (Ollama), validates, commits resolution
rows, and archives the backlog parent. Wired into hermes_coordinator every tick.

Usage:
    python scripts/hermes_backlog_drain.py [--apply] [--max-rows N]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LOCKFILE = Path("/tmp/hermes_backlog_drain.lock")
LOOP_MODEL = os.environ.get("HERMES_LOOP_MODEL", "gemma3:4b")
MAX_RUNTIME = 540


def _env():
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def get_db_connection():
    import psycopg2
    pw = os.getenv("DB_PASSWORD", "")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=pw,
    )


def check_kill_switch():
    from hermes_killswitch import is_hermes_disabled
    active, path = is_hermes_disabled(extra=[PROJECT_ROOT / "data" / "runtime" / "BACKLOG_DRAIN_DISABLED"])
    if active:
        print(f"Kill switch ACTIVE ({path}). Exiting.")
        sys.exit(0)


def acquire_lock():
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    fd = open(LOCKFILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another backlog drain is running. Exiting.")
        sys.exit(0)
    return fd


def _priority_rank(evidence_json) -> int:
    try:
        ej = evidence_json if isinstance(evidence_json, (dict, list)) else json.loads(evidence_json or "[]")
        if isinstance(ej, list) and ej:
            p = str(ej[0].get("priority", "")).lower()
        elif isinstance(ej, dict):
            p = str(ej.get("priority", "")).lower()
        else:
            p = ""
        return {"high": 0, "medium": 1, "low": 2}.get(p, 3)
    except Exception:
        return 3


def _has_resolution(cur, backlog_id: int) -> bool:
    cur.execute(
        """SELECT 1 FROM hermes_research_intelligence
           WHERE research_type='backlog_resolution'
             AND evidence_json::text LIKE %s LIMIT 1""",
        (f'%"backlog_id": {backlog_id}%',),
    )
    return cur.fetchone() is not None


def fetch_backlog_targets(conn, limit: int) -> list[dict]:
    """Prefer staged backlog; fall back to legacy archived rows never drained."""
    cur = conn.cursor()
    out: list[dict] = []
    for status, status_rank in (("staged", 0), ("archived", 1)):
        if len(out) >= limit * 4:
            break
        # Engine Room v1 (WS-4): resolved rows carry a 'drained' tag so the fetch
        # window skips them in SQL — the old oldest-60 scan starved once its whole
        # window was already resolved, wedging the drain with 2,400+ rows waiting.
        cur.execute(
            """SELECT id, topic, summary, evidence_json, created_at
               FROM hermes_research_intelligence
               WHERE research_type='research_backlog' AND status=%s
                 AND NOT (tags && ARRAY['drained','duplicate_collapsed'])
               ORDER BY created_at ASC
               LIMIT %s""",
            (status, max(limit * 12, 60)),
        )
        for rid, topic, summary, ej, created_at in cur.fetchall():
            if _has_resolution(cur, rid):
                continue
            out.append({
                "id": rid, "topic": topic, "summary": summary,
                "evidence_json": ej, "created_at": created_at,
                "priority": _priority_rank(ej),
                "status_rank": status_rank,
            })
    out.sort(key=lambda x: (x["status_rank"], x["priority"], x["created_at"]))
    return out[:limit]


def _trade_context(conn, topic: str) -> dict:
    """Light context for backlog resolution prompts."""
    cur = conn.cursor()
    ctx: dict = {"backlog_topic": topic}
    if "strategy" in topic.lower() or "backtest" in topic.lower():
        cur.execute(
            """SELECT strategy_id, win_rate, profit_factor, sample_size
               FROM hermes_v_backtest_results_context
               ORDER BY sample_size DESC NULLS LAST LIMIT 8"""
        )
        ctx["backtest_snapshot"] = [
            {"strategy_id": r[0], "win_rate": float(r[1]) if r[1] is not None else None,
             "profit_factor": float(r[2]) if r[2] is not None else None, "sample_size": r[3]}
            for r in cur.fetchall()
        ]
    if "catalyst" in topic.lower():
        cur.execute(
            """SELECT catalyst_type, confidence, COUNT(*) AS n
               FROM hermes_v_catalyst_quality_context
               GROUP BY catalyst_type, confidence ORDER BY n DESC LIMIT 12"""
        )
        ctx["catalyst_quality"] = [
            {"type": r[0], "confidence": float(r[1]) if r[1] is not None else None, "count": r[2]}
            for r in cur.fetchall()
        ]
    if "screener" in topic.lower():
        cur.execute(
            """SELECT status, COUNT(*) FROM hermes_v_screener_context
               WHERE run_date > CURRENT_DATE - INTERVAL '14 days'
               GROUP BY status"""
        )
        ctx["screener_14d"] = {r[0]: r[1] for r in cur.fetchall()}
    return ctx


def _call_ollama(prompt: str) -> dict:
    payload = json.dumps({
        "model": LOOP_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_ctx": 8192, "num_predict": 2000, "temperature": 0.3},
        "format": "json",
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=180)
    result = json.loads(resp.read())
    content = result.get("message", {}).get("content", "")
    return json.loads(content)


def drain_backlog(*, apply: bool, max_rows: int) -> list[dict]:
    from hermes_research_prompt import build_research_prompt
    from hermes_staging_ingest import validate_payload, build_insert

    conn = get_db_connection()
    targets = fetch_backlog_targets(conn, max_rows)
    if not targets:
        print("No drainable backlog targets.")
        conn.close()
        return []

    run_id = f"backlog_drain_{datetime.now().strftime('%Y%m%d_%H%M')}"
    print(f"Run {run_id}: draining {len(targets)} backlog rows")
    results = []

    for i, target in enumerate(targets):
        if time.time() - start > MAX_RUNTIME:
            print(f"Runtime cap {MAX_RUNTIME}s reached.")
            break
        bid = target["id"]
        topic = target["topic"] or "backlog finding"
        print(f"\n  [{i+1}/{len(targets)}] backlog_id={bid} topic={topic[:80]}")

        ctx = _trade_context(conn, topic)
        ctx["backlog_summary"] = target.get("summary")
        ctx["backlog_evidence"] = target.get("evidence_json")

        prompt = build_research_prompt(
            task_id=f"{run_id}_{bid}",
            agent_name="backlog_drain_agent",
            research_type="backlog_resolution",
            topic=f"Resolve backlog finding: {topic}",
            context=ctx,
            symbol=None,
            source_views=["hermes_research_intelligence", "hermes_v_backtest_results_context",
                          "hermes_v_catalyst_quality_context", "hermes_v_screener_context"],
            phase="49",
        )

        try:
            output = _call_ollama(prompt)
        except Exception as e:
            print(f"    LLM FAILED: {e}")
            results.append({"backlog_id": bid, "status": "failed", "error": str(e)[:200]})
            continue

        output["hermes_agent_name"] = "backlog_drain_agent"
        output["research_type"] = "backlog_resolution"
        output.setdefault("topic", f"Backlog resolution: {topic[:160]}")
        output.setdefault("confidence_score", 0.45)
        output.setdefault("freshness_date", date.today().isoformat())
        output.setdefault("model_used", LOOP_MODEL)
        ej = output.get("evidence_json", {})
        if not isinstance(ej, dict):
            ej = {}
        ej["backlog_id"] = bid
        ej["backlog_topic"] = topic
        ej["run_id"] = run_id
        ej["drain_agent"] = "backlog_drain_agent"
        ej["finding_type"] = "backlog_resolution"
        for field in ["challenge_points", "source_views", "limitations", "facts", "inferences",
                      "missing_data", "confidence_explanation"]:
            if field in output and field not in ej:
                ej[field] = output.pop(field, None)
        ej.setdefault("limitations", [
            "Resolution derived from backlog finding and partial safe-view context only.",
        ])
        ej.setdefault("source_views", [
            "hermes_research_intelligence",
            "hermes_v_backtest_results_context",
        ])
        ej.setdefault("challenge_points", [
            f"Backlog item '{topic[:80]}' requires structured follow-up research.",
        ])
        if not output.get("summary"):
            thesis = str(output.get("thesis") or "").strip()
            output["summary"] = (
                f"Autonomous backlog resolution for: {topic}. "
                f"{thesis or 'Analysis recorded from available Hermes safe views and backlog metadata.'}"
            )[:800]
        output["evidence_json"] = ej

        ok, errors = validate_payload(output, "hermes_research_intelligence")
        if not ok and any("MISSING required column: summary" in e for e in errors) and not output.get("summary"):
            try:
                from hermes_output_recovery import recover_summary_from_output
                rec = recover_summary_from_output(output, symbol=None)
                if rec.get("recovered"):
                    output["summary"] = rec["summary"]
                    ej.setdefault("summary_recovery", {"method": rec.get("recovery_method")})
                    output["evidence_json"] = ej
                    ok, errors = validate_payload(output, "hermes_research_intelligence")
            except Exception:
                pass

        if not ok:
            print(f"    VALIDATION FAILED: {errors[:2]}")
            results.append({"backlog_id": bid, "status": "rejected", "errors": errors[:3]})
            continue

        print(f"    VALIDATED conf={output.get('confidence_score')}")
        if not apply:
            results.append({"backlog_id": bid, "status": "validated", "dry_run": True})
            continue

        cur = conn.cursor()
        try:
            sql, vals = build_insert("hermes_research_intelligence", output)
            cur.execute(sql, vals)
            new_id = cur.fetchone()[0]
            cur.execute(
                """UPDATE hermes_research_intelligence
                   SET status = CASE WHEN status='staged' THEN 'archived' ELSE status END,
                       tags = CASE WHEN 'drained' = ANY(tags) THEN tags
                                   ELSE array_append(tags, 'drained') END
                   WHERE id=%s""",
                (bid,),
            )
            cur.execute(
                """INSERT INTO hermes_memory_events
                   (created_at, source, hermes_agent_name, event_type, topic, content,
                    metadata_json, related_research_id, status)
                   VALUES (NOW(),'hermes','backlog_drain_agent','research_debt_logged',%s,%s,%s,%s,'active')""",
                (topic[:200], f"Drained backlog #{bid} → research #{new_id}",
                 json.dumps({"backlog_id": bid, "research_id": new_id, "run_id": run_id,
                             "drain_status": "resolved"}),
                 new_id),
            )
            conn.commit()
            print(f"    COMMITTED research_id={new_id}, archived backlog #{bid}")
            results.append({"backlog_id": bid, "status": "applied", "research_id": new_id})
        except Exception as e:
            conn.rollback()
            print(f"    APPLY ERROR: {e}")
            results.append({"backlog_id": bid, "status": "apply_failed", "error": str(e)[:200]})

    conn.close()
    return results


def main():
    global start, MAX_RUNTIME
    start = time.time()
    _env()
    parser = argparse.ArgumentParser(description="Drain Hermes research backlog into real research")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-rows", type=int, default=2)
    parser.add_argument("--max-runtime", type=int, default=MAX_RUNTIME,
                        help="Seconds before the drain stops picking new rows (nightly run uses a longer cap)")
    parser.add_argument("--telegram-summary", action="store_true",
                        help="Send one backlog-status line to Telegram after the run (nightly cron)")
    args = parser.parse_args()
    MAX_RUNTIME = args.max_runtime

    check_kill_switch()
    lock_fd = acquire_lock()
    try:
        results = drain_backlog(apply=args.apply, max_rows=args.max_rows)
        applied = sum(1 for r in results if r["status"] == "applied")
        validated = sum(1 for r in results if r["status"] == "validated")
        failed = len(results) - applied - validated
        print(f"\nDone in {time.time() - start:.1f}s: {applied} drained, "
              f"{validated} validated (dry-run), {failed} failed/rejected")
        if args.telegram_summary:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""SELECT count(*) FROM hermes_research_intelligence
                               WHERE research_type='research_backlog'
                                 AND status IN ('staged','archived')
                                 AND NOT (tags && ARRAY['drained','duplicate_collapsed'])""")
                remaining = cur.fetchone()[0]
                conn.close()
                sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
                from telegram_alert import send_telegram
                send_telegram(
                    f"🗂 Hermes backlog drain: {applied} drained, {failed} failed/rejected · "
                    f"{remaining} remaining",
                    bypass_router=True,  # operator-specced nightly ops line
                )
            except Exception as e:
                print(f"Telegram summary failed: {e}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            LOCKFILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()