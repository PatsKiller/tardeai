#!/usr/bin/env python3
"""Run the deep overnight LLM queue using gemma3-overnight.

Processes queued items in priority order with time budgeting, checkpointing,
and hard stop enforcement.

Usage:
    .venv/bin/python scripts/run_deep_overnight_llm_queue.py --dry-run --limit 5
    .venv/bin/python scripts/run_deep_overnight_llm_queue.py --limit 70 --time-budget-min 240
    .venv/bin/python scripts/run_deep_overnight_llm_queue.py --hard-stop 03:00 --limit 75

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [deep-queue] {msg}", flush=True)


def past_hard_stop(hard_stop_str):
    """Check if current time is past the hard stop time."""
    if not hard_stop_str:
        return False
    now = datetime.now()
    h, m = map(int, hard_stop_str.split(":"))
    # Handle midnight crossing: if hard_stop is 03:00 and now is 02:00, not past
    # If now is 04:00, past
    # If hard_stop is 03:00 and now is 23:00, not past (we haven't crossed midnight yet)
    stop_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if h < 12:  # stop is in early morning (e.g., 03:00)
        if now.hour >= 12:  # we're in the evening, haven't crossed midnight
            return False
        else:  # we're in early morning, compare directly
            return now >= stop_today
    return now >= stop_today


def build_prompt(job):
    """Build a gemma3-overnight prompt for the given job."""
    job_type = job["job_type"]
    symbol = job.get("symbol") or "N/A"
    reasons = job.get("reason_codes") or []
    qwen_summary = job.get("last_qwen_summary") or ""
    meta = job.get("metadata_json") or {}

    if job_type == "strategy_classification":
        return f"""Analyze the trading strategy classification for {symbol}.

Current classification reasons: {', '.join(reasons)}
Prior summary: {qwen_summary[:1000] if qwen_summary else 'None available'}

Provide a structured deep review:
1. CLASSIFICATION ASSESSMENT: Is the current strategy assignment appropriate?
2. EVIDENCE QUALITY: How strong is the evidence supporting this classification?
3. ALTERNATIVE STRATEGIES: Should any other strategies be considered?
4. RISK FLAGS: Any concerns about this position or classification?
5. RECOMMENDATION: Keep current classification, reclassify, or flag for manual review?

Be concise and direct. Use structured format."""

    elif job_type == "closed_trade_review":
        return f"""Review the closed trade for {symbol}.

Trade ID: {job.get('trade_id')}
Account: {job.get('account', 'N/A')}
Review triggers: {', '.join(reasons)}

Provide a structured post-trade analysis:
1. OUTCOME ASSESSMENT: Was this trade well-executed given the setup?
2. ENTRY/EXIT QUALITY: Was timing and sizing appropriate?
3. RISK MANAGEMENT: Were stops and position sizing followed?
4. LESSONS LEARNED: What can be improved for similar setups?
5. PATTERN MATCH: Does this trade fit a recurring pattern (good or bad)?

Be concise and direct. Focus on actionable lessons."""

    elif job_type in ("auto_journal_review", "manual_journal_review"):
        return f"""Review the trade journal entry for {symbol}.

Journal ID: {job.get('journal_id')}
Review type: {job_type}
Review triggers: {', '.join(reasons)}

Provide a structured journal analysis:
1. EXECUTION QUALITY: How well was the trade plan followed?
2. EMOTIONAL FACTORS: Were there emotional influences on decisions?
3. BEHAVIORAL PATTERNS: Does this entry reveal recurring patterns?
4. IMPROVEMENT AREAS: Specific actionable improvements for next trade.
5. COACHING NOTES: What would a trading coach highlight?

Be concise and direct. Focus on behavioral insights."""

    elif job_type == "proposal_review":
        return f"""Deep review of trade proposal for {symbol}.

Proposal ID: {job.get('trade_id')}
Account: {job.get('account', 'N/A')}
Review triggers: {', '.join(reasons)}

Provide a structured proposal assessment:
1. THESIS QUALITY: Is the trade thesis well-supported?
2. RISK/REWARD: Is the risk/reward ratio appropriate?
3. TIMING: Is the entry timing favorable given current conditions?
4. SIZING: Is position sizing appropriate for the account and risk?
5. RECOMMENDATION: Approve, modify, or reject with specific reasons?

Be concise and direct."""

    elif job_type == "risk_synthesis":
        return f"""Synthesize current portfolio risk for overnight assessment.

Focus areas: {', '.join(reasons)}

Provide a structured risk report:
1. CONCENTRATION RISK: Any over-concentrated positions or sectors?
2. CORRELATION RISK: Are positions too correlated?
3. DRAWDOWN RISK: Current drawdown vs max acceptable?
4. EVENT RISK: Any upcoming events that could impact the portfolio?
5. ACTION ITEMS: Specific risk-reduction recommendations.

Be concise and direct."""

    else:
        return f"""Deep LLM review for {symbol or 'portfolio'}.

Job type: {job_type}
Triggers: {', '.join(reasons)}

Provide a structured analysis with:
1. KEY FINDINGS
2. RISK FLAGS
3. RECOMMENDATIONS

Be concise and direct."""


def call_gemma(prompt, model="gemma3-overnight", timeout=180):
    """Call gemma3-overnight via Ollama. Returns (text, runtime_sec) or (None, 0)."""
    url = f"{OLLAMA_URL}/api/chat"
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.2, "num_predict": 500},
    }).encode()

    start = time.monotonic()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            text = data.get("message", {}).get("content", "").strip()
            elapsed = round(time.monotonic() - start, 1)
            tokens = data.get("eval_count", 0)
            log(f"  gemma response: {elapsed}s, {tokens} tokens")
            return text, elapsed
    except Exception as e:
        elapsed = round(time.monotonic() - start, 1)
        log(f"  gemma ERROR: {e} ({elapsed}s)")
        return None, elapsed


def recover_stale_running(cur):
    """Reset jobs stuck in 'running' from previous failed runs (>30 min old)."""
    cur.execute("""
        UPDATE deep_overnight_llm_queue
        SET status = 'pending',
            attempt_count = attempt_count,
            last_error = COALESCE(last_error, '') || ' [recovered from stale running]',
            updated_at = NOW()
        WHERE status = 'running'
        AND started_at < NOW() - INTERVAL '30 minutes'
        RETURNING id, job_type, symbol
    """)
    recovered = cur.fetchall()
    if recovered:
        log(f"Recovered {len(recovered)} stale running jobs")
        for rid, jtype, sym in recovered:
            log(f"  recovered: #{rid} {jtype} {sym}")
    return len(recovered)


def main():
    parser = argparse.ArgumentParser(description="Run deep overnight LLM queue")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    parser.add_argument("--limit", type=int, default=70, help="Max jobs to process (default 70, hard max 75)")
    parser.add_argument("--time-budget-min", type=int, default=240, help="Time budget in minutes")
    parser.add_argument("--hard-stop", type=str, default="03:00", help="Hard stop time HH:MM")
    parser.add_argument("--job-types", type=str, default=None,
                        help="Comma-separated job types to process")
    args = parser.parse_args()

    model = os.getenv("LOCAL_LLM_MODEL", "gemma3-overnight")
    log(f"Queue runner starting — model={model}, limit={args.limit}, "
        f"budget={args.time_budget_min}m, hard_stop={args.hard_stop}")

    conn = get_db_connection()
    cur = conn.cursor()

    # Recover stale running jobs
    recovered = recover_stale_running(cur)
    conn.commit()

    # Build query for pending jobs
    type_filter = ""
    type_params = []
    if args.job_types:
        types = [t.strip() for t in args.job_types.split(",")]
        placeholders = ",".join(["%s"] * len(types))
        type_filter = f"AND job_type IN ({placeholders})"
        type_params = types

    cur.execute(f"""
        SELECT id, job_type, symbol, trade_id, journal_id, account,
               priority_tier, priority_score, reason_codes,
               last_qwen_summary, last_qwen_confidence, metadata_json,
               attempt_count, input_hash
        FROM deep_overnight_llm_queue
        WHERE status = 'pending'
        {type_filter}
        ORDER BY priority_score DESC, queued_at ASC
        LIMIT %s
    """, type_params + [args.limit])

    jobs = cur.fetchall()
    columns = [desc[0] for desc in cur.description]

    log(f"Found {len(jobs)} pending jobs")

    if args.dry_run:
        log("=== DRY RUN ===")
        for i, row in enumerate(jobs[:50]):
            job = dict(zip(columns, row))
            sym = job.get("symbol") or f"#{job.get('trade_id') or job.get('journal_id') or '?'}"
            reasons = job.get("reason_codes") or []
            log(f"  {i+1:>3}. [{job['priority_tier']}:{job['priority_score']:>3}] "
                f"{job['job_type']:>25} {sym:>8} — {','.join(reasons[:3])}")
        log(f"Would process up to {len(jobs)} jobs in {args.time_budget_min} minutes")
        conn.close()
        return

    # Process jobs
    start_time = time.monotonic()
    budget_sec = args.time_budget_min * 60
    processed = 0
    succeeded = 0
    failed = 0

    for row in jobs:
        job = dict(zip(columns, row))
        job_id = job["id"]
        elapsed = time.monotonic() - start_time

        # Time budget check
        if elapsed >= budget_sec:
            log(f"Time budget exhausted ({args.time_budget_min}m). Stopping.")
            break

        # Hard stop check
        if past_hard_stop(args.hard_stop):
            log(f"Hard stop {args.hard_stop} reached. Stopping.")
            break

        sym = job.get("symbol") or f"#{job.get('trade_id') or job.get('journal_id') or '?'}"
        log(f"Processing #{job_id}: {job['job_type']} {sym} "
            f"[{job['priority_tier']}:{job['priority_score']}] "
            f"(elapsed={int(elapsed)}s)")

        # Mark as running
        cur.execute("""
            UPDATE deep_overnight_llm_queue
            SET status = 'running', started_at = NOW(),
                attempt_count = attempt_count + 1, updated_at = NOW()
            WHERE id = %s
        """, (job_id,))
        conn.commit()

        # Build prompt and call gemma
        prompt = build_prompt(job)
        text, runtime = call_gemma(prompt, model=model)

        if text:
            # Store result
            cur.execute("""
                INSERT INTO deep_overnight_llm_results
                (queue_id, job_type, symbol, trade_id, journal_id, model,
                 prompt_version, summary, findings_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'v1', %s, %s, NOW())
                RETURNING id
            """, (job_id, job["job_type"], job.get("symbol"),
                  job.get("trade_id"), job.get("journal_id"),
                  model, text[:2000],
                  json.dumps({"raw_response": text[:5000]})))
            result_id = cur.fetchone()[0]

            # Mark done
            cur.execute("""
                UPDATE deep_overnight_llm_queue
                SET status = 'done', completed_at = NOW(),
                    last_gemma_model = %s, last_gemma_runtime_sec = %s,
                    result_table = 'deep_overnight_llm_results', result_id = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (model, runtime, result_id, job_id))
            conn.commit()
            succeeded += 1
            log(f"  DONE #{job_id} — result_id={result_id}, runtime={runtime}s")
        else:
            # Mark failed
            cur.execute("""
                UPDATE deep_overnight_llm_queue
                SET status = CASE WHEN attempt_count >= 3 THEN 'failed' ELSE 'pending' END,
                    last_error = %s,
                    last_gemma_model = %s, last_gemma_runtime_sec = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (f"gemma returned no text after {runtime}s", model, runtime, job_id))
            conn.commit()
            failed += 1
            log(f"  FAILED #{job_id} — no response after {runtime}s")

        processed += 1

    total_elapsed = round((time.monotonic() - start_time) / 60, 1)

    # Summary
    log("=" * 60)
    log(f"Queue run complete:")
    log(f"  Processed:   {processed}")
    log(f"  Succeeded:   {succeeded}")
    log(f"  Failed:      {failed}")
    log(f"  Recovered:   {recovered}")
    log(f"  Total time:  {total_elapsed} min")
    log(f"  Model:       {model}")
    log(f"  Hard stop:   {args.hard_stop}")

    # Remaining pending
    cur.execute("SELECT count(*) FROM deep_overnight_llm_queue WHERE status = 'pending'")
    remaining = cur.fetchone()[0]
    log(f"  Remaining pending: {remaining}")
    log("=" * 60)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
