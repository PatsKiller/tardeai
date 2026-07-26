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
KILL_FILE = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
MAX_RUNTIME = 600  # seconds
DAILY_ROW_CAP = 10
DAILY_MODEL_CAP = 15
# Default gemma3:12b — gemma3:4b is fast but routinely fails the summary/evidence quality gate
# (MISSING summary, evidence_json < 2 keys). Override: HERMES_LOOP_MODEL=gemma3:4b for speed tests.
LOOP_MODEL = os.environ.get("HERMES_LOOP_MODEL", "gemma3:12b")
# Host 2026-07-26: gemma3:12b thesis-challenge ~198s warm; 180s was too tight. Allow 300s default.
OLLAMA_TIMEOUT = int(os.environ.get("HERMES_LOOP_OLLAMA_TIMEOUT", "300"))

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
    """Open a fresh Postgres connection with TCP keepalives.

    Long Ollama calls (60–180s) previously left a single connection idle until
    the server closed SSL; the next cursor.execute then raised OperationalError
    and aborted the whole unit. Keepalives + ensure_live_conn mitigate that.
    """
    env_path = PROJECT_ROOT / ".env"
    db_pass = None
    for line in env_path.read_text().splitlines():
        if line.startswith("DB_PASSWORD="):
            db_pass = line.split("=", 1)[1]
    if not db_pass:
        print("ERROR: DB_PASSWORD not found", file=sys.stderr)
        sys.exit(1)
    import psycopg2
    return psycopg2.connect(
        host="localhost",
        dbname="trade_ai",
        user="trade_ai",
        password=db_pass,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
        connect_timeout=10,
    )


def _conn_is_alive(conn) -> bool:
    if conn is None:
        return False
    try:
        if getattr(conn, "closed", 1):
            return False
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        return True
    except Exception:
        return False


def ensure_live_conn(conn):
    """Return conn if usable; otherwise close and open a new connection."""
    if _conn_is_alive(conn):
        return conn
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    print("    DB: reconnected (previous connection closed or SSL dead)")
    return get_db_connection()


def get_ticker_targets(conn, max_rows=3, drain_closed_trades=False):
    """Select tickers for Hermes LLM research, prioritized (2026-06-04):
       0. HELD positions across ALL accounts (trades + paper_trades, status=open) — re-researched if
          not done in the last 24h, so live holdings get around-the-clock coverage.
       1. OPEN proposals (actionable statuses) — same 24h re-research window.
       2. CLOSED trades (retrospective reflection) — one-time (never re-researched).
    Held/proposals use a 24h window (cycle daily); closed-trade reflection uses lifetime dedup.

    drain_closed_trades=True (manual DRAIN MODE only): closed_trade_needing_reflection becomes the sole
    priority-0 tier and held/proposals are skipped for THIS RUN ONLY — used to pull down the all-trades
    closed backlog without held-position starvation. Normal production cron priority is unchanged
    (drain mode is off by default). Canonical: targets carry trade_instance_id (not legacy paper ids).
    """
    cur = conn.cursor()
    targets_block = (
        "SELECT symbol, 0 AS pri, 'closed_trade_needing_reflection:'||source_system AS src, ti_id "
        "FROM needs_reflection"
    ) if drain_closed_trades else (
        "SELECT symbol, 0 AS pri, 'held_position' AS src, NULL::bigint AS ti_id FROM held "
        "  WHERE symbol NOT IN (SELECT symbol FROM researched_recent) "
        "UNION ALL "
        "SELECT symbol, 1 AS pri, 'open_proposal' AS src, NULL::bigint FROM proposals "
        "  WHERE symbol NOT IN (SELECT symbol FROM researched_recent) "
        "UNION ALL "
        "SELECT symbol, 1 AS pri, 'closed_trade_needing_reflection:'||source_system AS src, ti_id "
        "  FROM needs_reflection"
    )
    cur.execute(("""
        WITH researched_recent AS (
            SELECT DISTINCT symbol FROM hermes_research_intelligence
            WHERE symbol IS NOT NULL AND created_at > now() - interval '24 hours'
        ),
        researched_ever AS (
            SELECT DISTINCT symbol FROM hermes_research_intelligence WHERE symbol IS NOT NULL
        ),
        held AS (
            SELECT symbol FROM trades       WHERE lower(status)='open' AND symbol ~ '^[A-Z]{1,5}$'
            UNION
            SELECT symbol FROM paper_trades WHERE lower(status)='open' AND symbol ~ '^[A-Z]{1,5}$'
        ),
        proposals AS (
            SELECT symbol FROM paper_trade_proposals
            WHERE symbol ~ '^[A-Z]{1,5}$'
              AND status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST','MODIFIED')
        ),
        needs_reflection AS (
            SELECT symbol, id AS ti_id, source_system FROM trade_instances ti
            WHERE lower(coalesce(status,''))='closed' AND symbol ~ '^[A-Z]{1,5}$'
              AND NOT EXISTS (SELECT 1 FROM hermes_research_intelligence h WHERE h.trade_instance_id = ti.id)
        ),
        targets AS (
            __TARGETS_BLOCK__
        ),
        deduped AS (
            SELECT DISTINCT ON (symbol) symbol, src, pri, ti_id FROM targets
              ORDER BY symbol, pri, ti_id DESC NULLS LAST
        )
        SELECT symbol, src, ti_id FROM deduped ORDER BY pri, symbol LIMIT %s
    """).replace("__TARGETS_BLOCK__", targets_block), (max_rows,))
    rows = cur.fetchall()
    targets = []
    for symbol, src, ti_id in rows:
        rtid = rpid = None
        tiid = ti_id
        if ti_id is not None:
            cur.execute("SELECT source_table, source_trade_id FROM trade_instances WHERE id=%s", (ti_id,))
            r = cur.fetchone()
            if r and r[0] == 'paper_trades':
                rtid = int(r[1])
        else:
            cur.execute("SELECT id FROM paper_trades WHERE symbol=%s AND lower(coalesce(status,''))='open' ORDER BY id DESC LIMIT 1", (symbol,))
            r = cur.fetchone()
            rtid = r[0] if r else None
            if rtid is not None:
                cur.execute("SELECT id FROM trade_instances WHERE source_table='paper_trades' AND source_trade_id=%s", (str(rtid),))
                ti = cur.fetchone()
                tiid = ti[0] if ti else None
        cur.execute("""SELECT id FROM paper_trade_proposals WHERE symbol=%s
                       AND status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST','MODIFIED')
                       ORDER BY id DESC LIMIT 1""", (symbol,))
        r = cur.fetchone()
        rpid = r[0] if r else None
        targets.append({"symbol": symbol, "src": src, "trade_count": 0, "trade_instance_id": tiid,
                        "related_trade_id": rtid, "related_proposal_id": rpid})
    return targets


def get_ticker_context(conn, symbol):
    """Get context for a ticker from safe views."""
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
    import psycopg2

    conn = get_db_connection()
    drain = getattr(args, "drain_closed_trades", False)
    try:
        targets = get_ticker_targets(conn, args.max_rows, drain_closed_trades=drain)
    except psycopg2.OperationalError as e:
        print(f"TARGET SELECT failed, reconnecting once: {e}")
        conn = ensure_live_conn(None)
        targets = get_ticker_targets(conn, args.max_rows, drain_closed_trades=drain)

    if not targets:
        print("No new ticker targets found (all already researched)")
        try:
            conn.close()
        except Exception:
            pass
        return []

    if drain:
        from collections import Counter
        by_src = Counter((t["src"].split(":")[1] if ":" in t["src"] else t["src"]) for t in targets)
        print(f"drain_closed_trades=true | target_tier=closed_trade_needing_reflection | "
              f"target_count={len(targets)} | by_source_system={dict(by_src)} | "
              f"with_trade_instance_id={sum(1 for t in targets if t.get('trade_instance_id'))} | held_position_skipped=true")

    run_id = f"auto_ticker_challenger_{datetime.now().strftime('%Y%m%d_%H%M')}"
    print(f"Run ID: {run_id}")
    print(f"Targets: {[t['symbol'] for t in targets]}")
    print(f"Ollama timeout: {OLLAMA_TIMEOUT}s · model: {LOOP_MODEL}")

    results = []
    outdir = PROJECT_ROOT / "docs" / "hermes" / "phase3b_dryrun"
    outdir.mkdir(parents=True, exist_ok=True)

    for i, target in enumerate(targets):
        sym = target["symbol"]
        print(f"\n  [{i+1}/{len(targets)}] {sym} ({target.get('src','target')})")

        try:
            conn = ensure_live_conn(conn)
            try:
                ctx = get_ticker_context(conn, sym)
            except psycopg2.OperationalError as e:
                print(f"    CONTEXT failed ({e}); reconnecting…")
                conn = ensure_live_conn(None)
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
                resp = urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT)
                result = json.loads(resp.read())
                content = result.get("message", {}).get("content", "")
                output = json.loads(content)
            except Exception as e:
                print(f"    FAILED: {e}")
                results.append({"symbol": sym, "status": "failed", "error": str(e)[:200]})
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
                continue

            output["hermes_agent_name"] = "ticker_research_agent"
            output["research_type"] = "ticker_thesis_challenge"
            output.setdefault("topic", f"{sym} autonomous thesis challenge — {target.get('trade_count', 0)} trades")
            output.setdefault("confidence_score", 0.5)
            output.setdefault("freshness_date", date.today().isoformat())
            output.setdefault("model_used", LOOP_MODEL)
            output["symbol"] = sym
            if target.get("trade_instance_id") is not None:
                output["trade_instance_id"] = target["trade_instance_id"]
            if target.get("related_trade_id") is not None:
                output["related_trade_id"] = target["related_trade_id"]
            if target.get("related_proposal_id") is not None:
                output["related_proposal_id"] = target["related_proposal_id"]
            ej = output.get("evidence_json", {})
            if not isinstance(ej, dict):
                ej = {}
            for field in ["challenge_points", "source_views", "limitations", "facts", "inferences",
                           "missing_data", "confidence_explanation"]:
                if field in output and field not in ej:
                    ej[field] = output.pop(field, None)
            ej["run_id"] = run_id
            output["evidence_json"] = ej

            ok, errors = validate_payload(output, "hermes_research_intelligence")
            if not ok and any("MISSING required column: summary" in e for e in errors) and not output.get("summary"):
                try:
                    from hermes_output_recovery import recover_summary_from_output
                    rec = recover_summary_from_output(output if isinstance(output, dict) else content,
                                                      symbol=sym)
                except Exception as _re:
                    rec = {"recovered": False, "rejection_reason": f"recover error: {_re}"}
                if rec.get("recovered"):
                    output["summary"] = rec["summary"]
                    ej.setdefault("summary_recovery", {
                        "summary_recovered": True, "summary_recovery_method": rec.get("recovery_method"),
                        "summary_source_key": rec.get("source_key"), "summary_recovery_confidence": rec.get("confidence"),
                        "validator_version": rec.get("validator_version"), "raw_validation_error": "MISSING summary"})
                    output["evidence_json"] = ej
                    ok, errors = validate_payload(output, "hermes_research_intelligence")
                    print(f"    SUMMARY RECOVERED ({rec.get('recovery_method')}/{rec.get('source_key')}, conf={rec.get('confidence')})")
                else:
                    print(f"    summary recovery rejected: {rec.get('rejection_reason')}")
            if not ok:
                print(f"    VALIDATION FAILED: {errors[:2]}")
                results.append({"symbol": sym, "status": "rejected", "errors": errors})
                continue

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

            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None

        except Exception as e:
            print(f"    TICKER ERROR (isolated): {e}")
            results.append({"symbol": sym, "status": "failed", "error": str(e)[:200]})
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
            continue

    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass
    return results


def main():
    parser = argparse.ArgumentParser(description="Hermes autonomous research loop")
    parser.add_argument("--loop", required=True, choices=["ticker_challenger", "portfolio_reflection", "pipeline_quality"])
    parser.add_argument("--apply", action="store_true", help="Apply to DB (default: dry-run)")
    parser.add_argument("--max-rows", type=int, default=3)
    parser.add_argument("--drain-closed-trades", action="store_true",
                        help="Manual DRAIN MODE: prioritize closed_trade_needing_reflection over held-position "
                             "monitoring for THIS RUN ONLY (off by default; normal cron priority unchanged).")
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
        if results and validated == 0 and failed == len(results):
            sys.exit(1)

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            LOCKFILE.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
