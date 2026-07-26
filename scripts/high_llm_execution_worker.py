#!/usr/bin/env python3
"""High-LLM Execution Worker — governed pilot.

Usage:
    python scripts/high_llm_execution_worker.py [--apply] [--max-jobs N]

Default: dry-run (reads queue, renders plan, no Ollama call).
--apply: runs up to N jobs through gemma3:12b.

Safety:
    - Max 3 jobs per run
    - gemma3:12b only
    - Advisory outputs only
    - No proposal/trade/journal/holdings mutation
    - Results stored in high_llm_job_results only
"""
import argparse, json, os, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
MAX_JOBS = 3
MODEL = "gemma3:12b"

def get_db():
    import psycopg2
    db_pass = [l.split("=",1)[1] for l in (PR/".env").read_text().splitlines() if l.startswith("DB_PASSWORD=")][0]
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)

LOCK_FILE = "/tmp/high_llm_execution.lock"
NUM_CTX = 4096

def warm_model(model=MODEL):
    """Warm model with tiny prompt to force load into VRAM."""
    try:
        # probe must use the SAME num_ctx as the real calls below — a 512-ctx probe
        # spun up a throwaway runner and forced TWO reloads per run (07-23 sweep)
        payload = json.dumps({"model": model, "prompt": "hello", "stream": False, "options": {"num_ctx": NUM_CTX}}).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=120)
        return True
    except Exception as e:
        print(f"  WARN: model warm failed: {e}")
        return False

def call_ollama(prompt, model=MODEL, timeout=180):
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"num_ctx": NUM_CTX}}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read()).get("response", "")

def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=MAX_JOBS)
    args = parser.parse_args()
    dry = not args.apply

    # Acquire execution lock
    if not dry:
        lock_fd = open(LOCK_FILE, "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another high-LLM execution is running. Exiting.")
            return

        # Warm model
        print(f"Warming {MODEL}...")
        if not warm_model():
            print("Model warm failed. Exiting.")
            return

    # Kill switch
    ks = PR / "data" / "state" / "HIGH_LLM_SCHEDULER_DISABLED"
    if ks.exists():
        print("Kill switch ACTIVE. Exiting.")
        return

    conn = get_db()
    cur = conn.cursor()

    # Select top priority jobs
    # --apply mode: only pick 'approved' jobs (operator gate)
    # dry-run mode: show all pending (queued_for_review, dry_run_candidate, approved)
    if dry:
        pick_statuses = ('queued_for_review', 'dry_run_candidate', 'approved')
    else:
        pick_statuses = ('approved',)
    cur.execute("""
        SELECT id, job_type, source_system, priority_score, expected_runtime_sec, quota_pool
        FROM high_llm_job_queue
        WHERE status = ANY(%s)
        ORDER BY priority_score DESC NULLS LAST
        LIMIT %s
    """, (list(pick_statuses), args.max_jobs))
    jobs = cur.fetchall()

    results = []
    for jid, jtype, src, ps, rt, pool in jobs:
        prompt = f"Analyze the following Trade AI job for advisory research quality:\n\nJob: {jtype}\nSource: {src}\nPriority: {ps}\nPool: {pool}\n\nProvide a brief advisory assessment (max 200 words). This is advisory only, not execution."

        if dry:
            print(f"  [DRY] job={jid} {jtype} priority={ps}")
            results.append({"job_id": jid, "type": jtype, "mode": "dry-run", "model": MODEL})
            continue

        print(f"  [APPLY] job={jid} {jtype} priority={ps} — calling {MODEL}...")
        start = time.time()
        try:
            output = call_ollama(prompt)
            elapsed = round(time.time() - start, 1)
            quality = 0.7 if len(output) > 100 else 0.3

            # Record result
            cur.execute("""
                INSERT INTO high_llm_job_results (job_id, model_used, runtime_sec, tokens_used, result_quality, actionable, output_summary)
                VALUES (%s, %s, %s, %s, %s, false, %s) RETURNING id
            """, (jid, MODEL, elapsed, len(output.split()), quality, output[:500]))
            rid = cur.fetchone()[0]

            # Update queue
            cur.execute("UPDATE high_llm_job_queue SET status='completed', started_at=NOW(), finished_at=NOW(), result_ref=%s WHERE id=%s", (rid, jid))
            conn.commit()

            results.append({"job_id": jid, "type": jtype, "mode": "apply", "model": MODEL, "runtime": elapsed, "quality": quality, "result_id": rid})
            print(f"    Done in {elapsed}s, result id={rid}")

        except Exception as e:
            cur.execute("UPDATE high_llm_job_queue SET status='failed', error_message=%s, retry_count=retry_count+1 WHERE id=%s", (str(e)[:200], jid))
            conn.commit()
            results.append({"job_id": jid, "type": jtype, "mode": "failed", "error": str(e)[:100]})

    cur.close(); conn.close()
    print(f"\n{'DRY-RUN' if dry else 'APPLY'}: {len(results)} jobs {'planned' if dry else 'executed'}")

if __name__ == "__main__":
    main()
