#!/usr/bin/env python3
"""
pipeline_controller.py — Dependency-aware pipeline orchestrator.

Replaces fragile cron-only orchestration with run tracking, retries,
timeouts, SLA monitoring, and degraded mode support.

Usage:
    python pipeline_controller.py --pipeline daily --run-label morning --dry-run
    python pipeline_controller.py --pipeline daily --group data_collection
    python pipeline_controller.py --pipeline daily --only-stage finviz_screener_runner
    python pipeline_controller.py --pipeline daily --list-stages
    python pipeline_controller.py --pipeline daily --status <run_id>
"""
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import psycopg2
import psycopg2.extras

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def _env(key, default=""):
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.getenv(key, default)

def _get_conn():
    import psycopg2, psycopg2.extras
    conn = psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))
    conn.autocommit = False
    return conn


def load_stages(conn, pipeline_key, group_key=None, only_stage=None):
    """Load active stages from DB, sorted by sort_order."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql = "SELECT * FROM pipeline_stages WHERE pipeline_key=%s AND active=true"
    params = [pipeline_key]
    if group_key:
        sql += " AND group_key=%s"
        params.append(group_key)
    if only_stage:
        sql += " AND stage_key=%s"
        params.append(only_stage)
    sql += " ORDER BY sort_order"
    cur.execute(sql, params)
    return cur.fetchall()


def load_dependencies(conn, pipeline_key):
    """Load dependency graph."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT stage_key, depends_on_stage_key, dependency_type FROM pipeline_stage_dependencies WHERE pipeline_key=%s", (pipeline_key,))
    deps = {}
    for row in cur.fetchall():
        deps.setdefault(row['stage_key'], []).append(row)
    return deps


def topo_sort(stages, deps):
    """Topological sort of stages by dependencies."""
    stage_keys = [s['stage_key'] for s in stages]
    graph = {s: [] for s in stage_keys}
    for sk, dep_list in deps.items():
        if sk in graph:
            for d in dep_list:
                if d['depends_on_stage_key'] in graph:
                    graph[sk].append(d['depends_on_stage_key'])

    visited = set()
    order = []
    def visit(node):
        if node in visited:
            return
        visited.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        order.append(node)
    for s in stage_keys:
        visit(s)

    stage_map = {s['stage_key']: s for s in stages}
    return [stage_map[k] for k in order if k in stage_map]


def create_run(conn, pipeline_key, run_label, trigger_source="manual"):
    """Create a new pipeline run."""
    run_id = f"{pipeline_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_runs (run_id, pipeline_key, run_label, status, trigger_source, started_at)
        VALUES (%s, %s, %s, 'running', %s, NOW())
    """, (run_id, pipeline_key, run_label, trigger_source))
    conn.commit()
    return run_id


def check_dependencies(stage_key, deps, stage_results, allow_degraded=False):
    """Check if all dependencies are satisfied. Returns (ok, blockers)."""
    stage_deps = deps.get(stage_key, [])
    if not stage_deps:
        return True, []
    blockers = []
    for d in stage_deps:
        dep_key = d['depends_on_stage_key']
        dep_status = stage_results.get(dep_key, "not_run")
        if dep_status == "success":
            continue
        if dep_status == "degraded" and allow_degraded:
            continue
        blockers.append({"stage": dep_key, "status": dep_status, "type": d['dependency_type']})
    return len(blockers) == 0, blockers


def run_stage(conn, run_id, pipeline_key, stage, attempt, dry_run=False):
    """Execute a single pipeline stage. Returns status dict."""
    stage_key = stage['stage_key']
    command = stage['command']
    timeout = stage.get('timeout_seconds', 1800)
    sla = stage.get('sla_seconds')

    # Log path
    log_dir = PROJECT_ROOT / "logs" / "pipeline_controller" / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{stage_key}_attempt{attempt}.log"

    if dry_run:
        print(f"  [DRY] {stage_key}: would run '{command}' (timeout={timeout}s)")
        return {"status": "success", "duration": 0, "exit_code": 0, "dry_run": True}

    print(f"  RUN: {stage_key} (attempt {attempt}, timeout {timeout}s)")
    started = time.time()

    try:
        with open(log_path, "w") as log_file:
            proc = subprocess.run(
                command, shell=True, cwd=str(PROJECT_ROOT),
                stdout=log_file, stderr=subprocess.STDOUT,
                timeout=timeout
            )
        duration = round(time.time() - started, 1)
        exit_code = proc.returncode

        # Read log tail
        try:
            log_text = log_path.read_text(errors="replace")
            stdout_tail = log_text[-2000:] if len(log_text) > 2000 else log_text
        except Exception:
            stdout_tail = ""

        # Determine SLA status
        sla_status = None
        if sla:
            sla_status = "met" if duration <= sla else "missed"

        if exit_code == 0:
            status = "success"
            print(f"  OK:  {stage_key} ({duration}s, exit 0"
                  f"{', SLA ' + sla_status if sla_status else ''})")
        elif stage.get('can_degrade', False):
            status = "degraded"
            print(f"  DEG: {stage_key} ({duration}s, exit {exit_code}) — degraded")
        else:
            status = "failed"
            print(f"  FAIL: {stage_key} ({duration}s, exit {exit_code})")

        # Record to DB
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pipeline_stage_runs
                (run_id, pipeline_key, stage_key, status, attempt,
                 started_at, finished_at, duration_seconds, exit_code,
                 error_message, log_path, stdout_tail, sla_status)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, stage_key, attempt) DO UPDATE SET
                status=EXCLUDED.status, finished_at=NOW(),
                duration_seconds=EXCLUDED.duration_seconds,
                exit_code=EXCLUDED.exit_code, stdout_tail=EXCLUDED.stdout_tail,
                sla_status=EXCLUDED.sla_status
        """, (run_id, pipeline_key, stage_key, status, attempt,
              datetime.fromtimestamp(started, tz=timezone.utc),
              duration, exit_code,
              stdout_tail[-500:] if exit_code != 0 else None,
              str(log_path), stdout_tail[-500:], sla_status))
        conn.commit()

        return {"status": status, "duration": duration, "exit_code": exit_code,
                "sla_status": sla_status, "log_path": str(log_path)}

    except subprocess.TimeoutExpired:
        duration = round(time.time() - started, 1)
        print(f"  TIMEOUT: {stage_key} ({duration}s > {timeout}s)")
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pipeline_stage_runs
                (run_id, pipeline_key, stage_key, status, attempt,
                 started_at, finished_at, duration_seconds,
                 error_type, error_message, log_path)
            VALUES (%s, %s, %s, 'failed', %s, %s, NOW(), %s, 'timeout', %s, %s)
            ON CONFLICT (run_id, stage_key, attempt) DO UPDATE SET
                status='failed', error_type='timeout'
        """, (run_id, pipeline_key, stage_key, attempt,
              datetime.fromtimestamp(started, tz=timezone.utc),
              duration, f"Timed out after {timeout}s", str(log_path)))
        conn.commit()
        return {"status": "failed", "duration": duration, "error": "timeout"}

    except Exception as e:
        duration = round(time.time() - started, 1)
        print(f"  ERR: {stage_key} — {e}")
        return {"status": "failed", "duration": duration, "error": str(e)}


def run_pipeline(conn, pipeline_key, run_label, stages, deps,
                 dry_run=False, allow_degraded=False, fail_fast=False):
    """Run all stages in dependency order."""
    run_id = create_run(conn, pipeline_key, run_label,
                        trigger_source="dry_run" if dry_run else "cli")

    sorted_stages = topo_sort(stages, deps)
    stage_results = {}

    print(f"\n{'='*60}")
    print(f"  Pipeline: {pipeline_key} | Run: {run_id}")
    print(f"  Stages: {len(sorted_stages)} | Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    for stage in sorted_stages:
        sk = stage['stage_key']

        # Check dependencies
        ok, blockers = check_dependencies(sk, deps, stage_results, allow_degraded)
        if not ok:
            print(f"  SKIP: {sk} — blocked by {[b['stage'] for b in blockers]}")
            stage_results[sk] = "skipped"
            # Record skip
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO pipeline_stage_runs
                    (run_id, pipeline_key, stage_key, status, dependency_blockers)
                VALUES (%s, %s, %s, 'skipped', %s)
                ON CONFLICT (run_id, stage_key, attempt) DO NOTHING
            """, (run_id, pipeline_key, sk, json.dumps(blockers)))
            conn.commit()
            continue

        # Run with retries
        max_retries = stage.get('max_retries', 1)
        result = None
        for attempt in range(max_retries + 1):
            result = run_stage(conn, run_id, pipeline_key, stage, attempt, dry_run)
            if result["status"] in ("success", "degraded"):
                break
            if attempt < max_retries:
                backoff = stage.get('retry_backoff_seconds', 60)
                print(f"  RETRY: {sk} in {backoff}s (attempt {attempt+1}/{max_retries})")
                if not dry_run:
                    time.sleep(backoff)

        stage_results[sk] = result["status"]

        if result["status"] == "failed" and fail_fast:
            print(f"\n  FAIL-FAST: stopping pipeline at {sk}")
            break

    # Finalize run
    statuses = list(stage_results.values())
    if "failed" in statuses:
        run_status = "failed"
    elif "degraded" in statuses:
        run_status = "degraded"
    elif all(s in ("success", "skipped") for s in statuses):
        run_status = "success"
    else:
        run_status = "partial"

    cur = conn.cursor()
    summary = {
        "stages": len(sorted_stages),
        "success": statuses.count("success"),
        "failed": statuses.count("failed"),
        "degraded": statuses.count("degraded"),
        "skipped": statuses.count("skipped"),
    }
    cur.execute("""
        UPDATE pipeline_runs SET status=%s, finished_at=NOW(),
            duration_seconds=EXTRACT(EPOCH FROM NOW()-started_at),
            summary=%s
        WHERE run_id=%s
    """, (run_status, json.dumps(summary), run_id))
    conn.commit()

    print(f"\n{'='*60}")
    print(f"  Run {run_id}: {run_status.upper()}")
    print(f"  Success: {summary['success']} | Failed: {summary['failed']} | "
          f"Degraded: {summary['degraded']} | Skipped: {summary['skipped']}")
    print(f"{'='*60}\n")

    return run_id, run_status, summary


def show_status(conn, run_id):
    """Show status of a specific run."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM pipeline_runs WHERE run_id=%s", (run_id,))
    run = cur.fetchone()
    if not run:
        print(f"Run {run_id} not found")
        return
    print(f"Run: {run['run_id']} | Status: {run['status']} | Duration: {run.get('duration_seconds','?')}s")
    cur.execute("SELECT stage_key, status, duration_seconds, exit_code, sla_status, error_message FROM pipeline_stage_runs WHERE run_id=%s ORDER BY created_at", (run_id,))
    for s in cur.fetchall():
        status_icon = {"success": "OK", "failed": "FAIL", "degraded": "DEG", "skipped": "SKIP"}.get(s['status'], '??')
        print(f"  [{status_icon:4}] {s['stage_key']:<35} {s.get('duration_seconds','?'):>6}s  exit={s.get('exit_code','?')}  sla={s.get('sla_status','?')}")
        if s.get('error_message'):
            print(f"         error: {s['error_message'][:100]}")


def list_stages(conn, pipeline_key):
    """List all registered stages."""
    stages = load_stages(conn, pipeline_key)
    deps = load_dependencies(conn, pipeline_key)
    print(f"\nPipeline: {pipeline_key} — {len(stages)} active stages\n")
    print(f"{'Stage':<35} {'Group':<18} {'Timeout':>8} {'SLA':>6} {'Degrade':>8} {'Deps'}")
    print("-" * 100)
    for s in stages:
        stage_deps = deps.get(s['stage_key'], [])
        dep_str = ", ".join(d['depends_on_stage_key'] for d in stage_deps) if stage_deps else "-"
        print(f"{s['stage_key']:<35} {s.get('group_key') or '':<18} {s.get('timeout_seconds') or '':>7}s {s.get('sla_seconds') or '?':>5}s {'yes' if s.get('can_degrade') else 'no':>8} {dep_str}")


def main():
    parser = argparse.ArgumentParser(description="Pipeline Controller")
    parser.add_argument("--pipeline", default="daily")
    parser.add_argument("--run-label", default="manual")
    parser.add_argument("--group", help="Run only stages in this group")
    parser.add_argument("--only-stage", help="Run only this stage")
    parser.add_argument("--from-stage", help="Start from this stage")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--allow-degraded", action="store_true")
    parser.add_argument("--list-stages", action="store_true")
    parser.add_argument("--status", help="Show status of run_id")
    args = parser.parse_args()

    conn = _get_conn()

    if args.list_stages:
        list_stages(conn, args.pipeline)
        conn.close()
        return

    if args.status:
        show_status(conn, args.status)
        conn.close()
        return

    stages = load_stages(conn, args.pipeline, args.group, args.only_stage)
    deps = load_dependencies(conn, args.pipeline)

    if args.from_stage:
        start_idx = next((i for i, s in enumerate(stages) if s['stage_key'] == args.from_stage), 0)
        stages = stages[start_idx:]

    if not stages:
        print(f"No active stages found for pipeline '{args.pipeline}'")
        conn.close()
        return

    run_id, status, summary = run_pipeline(
        conn, args.pipeline, args.run_label, stages, deps,
        dry_run=args.dry_run, allow_degraded=args.allow_degraded,
        fail_fast=args.fail_fast
    )
    conn.close()
    sys.exit(0 if status in ("success", "degraded") else 1)


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
