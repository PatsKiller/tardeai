#!/usr/bin/env python3
"""
Hermes Autonomous Research Loop — Trade AI v12

Manual and scheduled research loop with safety controls.
Usage:
  python scripts/hermes_autonomous_loop.py --loop ticker_challenger [--dry-run|--apply] [--max-rows 5]
"""

import argparse
import fcntl
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCKFILE = Path("/tmp/hermes_autonomous_loop.lock")
KILL_FILE = PROJECT_ROOT / "hermes_sidecar" / ".hermes" / "DISABLED"
MAX_RUNTIME = 600  # seconds
DAILY_ROW_CAP = 10
DAILY_MODEL_CAP = 15
# Model is configurable for cadence: gemma3:4b (~3x faster) keeps continuous ticks under the 15-min cron interval.
LOOP_MODEL = os.environ.get("HERMES_LOOP_MODEL", "gemma3:4b")

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def check_kill_switch():
    if KILL_FILE.exists():
        print(f"ABORT: Kill switch active ({KILL_FILE})")
        sys.exit(1)


def acquire_lock():
    try:
        lock_fd = open(LOCKFILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except (IOError, OSError):
        print("ABORT: Another instance is running (lockfile)")
        sys.exit(1)


def get_db_connection():
    env_path = PROJECT_ROOT / ".env"
    db_pass = None
    for line in env_path.read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            db_pass = line.split("=", 1)[1]
    if not db_pass:
        print("ERROR: DB_PASSWORD not found", file=sys.stderr)
        sys.exit(1)
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)


def get_ticker_targets(conn, max_rows=3):
    """Select tickers with recent activity for challenge."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT t.symbol, COUNT(*) AS trade_count
        FROM hermes_v_trade_reflection_context t
        WHERE t.lifecycle_state = 'closed' AND t.symbol IS NOT NULL
          AND t.symbol NOT IN (SELECT symbol FROM hermes_research_intelligence WHERE symbol IS NOT NULL)
        GROUP BY t.symbol
        HAVING COUNT(*) >= 2
        ORDER BY COUNT(*) DESC
        LIMIT %s
    """, (max_rows,))
    return [{"symbol": row[0], "trade_count": row[1]} for row in cur.fetchall()]


def get_ticker_context(conn, symbol):
    """Get context for a ticker from safe views."""
    cur = conn.cursor()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM hermes_v_ticker_context WHERE symbol=%s ORDER BY snapshot_date DESC LIMIT 1", (symbol,))
    ticker = cur.fetchone()

    cur.execute("""SELECT symbol, entry_price, exit_price, pnl, pnl_pct, exit_reason, lifecycle_state, created_at::date AS trade_date
                   FROM hermes_v_trade_reflection_context WHERE symbol=%s ORDER BY created_at DESC LIMIT 5""", (symbol,))
    trades = cur.fetchall()

    cur.execute("""SELECT symbol, strategy_id, signal_grade, status, proposed_entry, proposed_stop, proposed_target1, created_at::date
                   FROM hermes_v_proposal_context WHERE symbol=%s ORDER BY created_at DESC LIMIT 5""", (symbol,))
    proposals = cur.fetchall()

    def clean(row):
        return {k: (float(v) if isinstance(v, __import__('decimal').Decimal) else
                    v.isoformat() if hasattr(v, 'isoformat') else v)
                for k, v in (dict(row) if row else {}).items()}

    return {
        "ticker": clean(ticker),
        "trades": [clean(t) for t in trades],
        "proposals": [clean(p) for p in proposals],
    }


def run_ticker_challenger(args):
    """Run ticker challenger loop."""
    from hermes_research_prompt import build_research_prompt
    from hermes_staging_ingest import validate_payload

    conn = get_db_connection()
    targets = get_ticker_targets(conn, args.max_rows)

    if not targets:
        print("No new ticker targets found (all already researched)")
        conn.close()
        return []

    run_id = f"auto_ticker_challenger_{datetime.now().strftime('%Y%m%d_%H%M')}"
    print(f"Run ID: {run_id}")
    print(f"Targets: {[t['symbol'] for t in targets]}")

    results = []
    outdir = PROJECT_ROOT / "docs" / "hermes" / "phase3b_dryrun"
    outdir.mkdir(parents=True, exist_ok=True)

    for i, target in enumerate(targets):
        sym = target["symbol"]
        print(f"\n  [{i+1}/{len(targets)}] {sym} ({target['trade_count']} trades)")

        ctx = get_ticker_context(conn, sym)

        prompt = build_research_prompt(
            task_id=f"{run_id}_{sym}",
            agent_name="ticker_research_agent",
            research_type="ticker_thesis_challenge",
            topic=f"{sym} autonomous thesis challenge — {target['trade_count']} trades",
            context=ctx, symbol=sym,
            source_views=["hermes_v_ticker_context", "hermes_v_trade_reflection_context", "hermes_v_proposal_context"],
            phase="3"
        )

        # Call Ollama
        try:
            payload = json.dumps({
                "model": LOOP_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_ctx": 8192, "num_predict": 2000, "temperature": 0.3},
                "format": "json"
            }).encode()
            req = urllib.request.Request("http://localhost:11434/api/chat",
                                         data=payload, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=180)
            result = json.loads(resp.read())
            content = result.get("message", {}).get("content", "")
            output = json.loads(content)
        except Exception as e:
            print(f"    FAILED: {e}")
            results.append({"symbol": sym, "status": "failed", "error": str(e)[:200]})
            continue

        # Normalize
        output.setdefault("confidence_score", 0.5)
        output.setdefault("freshness_date", date.today().isoformat())
        output.setdefault("model_used", LOOP_MODEL)
        ej = output.get("evidence_json", {})
        if not isinstance(ej, dict):
            ej = {}
        for field in ["challenge_points", "source_views", "limitations", "facts", "inferences",
                       "missing_data", "confidence_explanation"]:
            if field in output and field not in ej:
                ej[field] = output.pop(field, None)
        ej["run_id"] = run_id
        output["evidence_json"] = ej

        # Validate
        ok, errors = validate_payload(output, "hermes_research_intelligence")
        if not ok:
            print(f"    VALIDATION FAILED: {errors[:2]}")
            results.append({"symbol": sym, "status": "rejected", "errors": errors})
            continue

        # Save payload
        pay_path = outdir / f"hermes_{run_id}_{sym}_payload.json"
        with open(pay_path, "w") as f:
            json.dump(output, f, indent=2)

        print(f"    VALIDATED: confidence={output['confidence_score']}")
        results.append({"symbol": sym, "status": "validated", "payload_path": str(pay_path)})

        if args.apply:
            from hermes_staging_ingest import build_insert, get_db_connection as get_ingest_conn
            iconn = get_ingest_conn()
            try:
                sql, vals = build_insert("hermes_research_intelligence", output)
                icur = iconn.cursor()
                icur.execute(sql, vals)
                row = icur.fetchone()
                iconn.commit()
                print(f"    COMMITTED: id={row[0]}")
                results[-1]["row_id"] = row[0]
                results[-1]["status"] = "applied"
            except Exception as e:
                iconn.rollback()
                print(f"    APPLY ERROR: {e}")
                results[-1]["status"] = "apply_failed"
            finally:
                iconn.close()

    conn.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Hermes autonomous research loop")
    parser.add_argument("--loop", required=True, choices=["ticker_challenger", "portfolio_reflection", "pipeline_quality"])
    parser.add_argument("--apply", action="store_true", help="Apply to DB (default: dry-run)")
    parser.add_argument("--max-rows", type=int, default=3)
    args = parser.parse_args()

    check_kill_switch()
    lock_fd = acquire_lock()
    start = time.time()

    print(f"{'[DRY-RUN]' if not args.apply else '[APPLY]'} Loop: {args.loop}, max_rows: {args.max_rows}")

    try:
        if args.loop == "ticker_challenger":
            results = run_ticker_challenger(args)
        else:
            print(f"Loop '{args.loop}' not yet implemented")
            results = []

        elapsed = time.time() - start
        validated = sum(1 for r in results if r["status"] in ("validated", "applied"))
        failed = sum(1 for r in results if r["status"] not in ("validated", "applied"))
        print(f"\nDone in {elapsed:.1f}s: {validated} validated, {failed} failed/rejected")

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            LOCKFILE.unlink()
        except:
            pass


if __name__ == "__main__":
    main()
