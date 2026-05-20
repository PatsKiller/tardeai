#!/usr/bin/env python3
"""report_pipeline_truth_audit.py — Pipeline truth audit across all stages.

Read-only. No trades, no orders, no mutations.

For each known pipeline stage (7 categories), determines:
  - last_run: from pipeline_stage_runs or data-presence queries
  - expected_schedule_hour: from known cron times
  - should_have_run: True if current hour >= expected_schedule_hour
  - truth_status: NOMINAL / WAITING_FOR_SCHEDULE / NOT_STARTED_TODAY / STALE / NO_DATA_PRODUCED

Usage:
    .venv/bin/python scripts/report_pipeline_truth_audit.py --verbose
    .venv/bin/python scripts/report_pipeline_truth_audit.py --output-json /tmp/pipeline_truth.json
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from db_adapter import _get_conn
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

# ── Pipeline stage definitions ──────────────────────────────────────────────
# Each category maps to stages with:
#   stage_key, friendly_name, expected_hour (ET), data_check_table, data_check_filter
# data_check_table is used as a fallback when pipeline_stage_runs has no entry.

PIPELINE_STAGES = {
    "Data Collection": [
        ("market_regime_snapshot", "Market Regime Snapshot", 6, "market_regime_snapshots", "snapshot_date = CURRENT_DATE"),
        ("finviz_screener_runner", "Finviz Screener Runner", 10, "trade_ai_scans", "run_date = CURRENT_DATE"),
        ("news_ingestion", "News Ingestion", 6, "article_index", "created_at::date = CURRENT_DATE"),
        ("indicator_cache_refresh", "Indicator Cache Refresh", 6, "indicator_confluence_cache", None),
        ("sec_data_ingest", "SEC Data Ingest", 6, "sec_form4", None),
    ],
    "Enrichment": [
        ("finviz_enrichment", "Finviz 5-View Enrichment", 7, "ticker_snapshot_daily", "snapshot_date = CURRENT_DATE::text"),
        ("catalyst_enrichment", "Catalyst Enrichment (7 sources)", 7, "catalyst_events", "created_at::date = CURRENT_DATE"),
        ("price_db_sync", "Price DB Sync", 7, "price_cache", None),
        ("rag_indexer", "RAG Indexer", 7, "content_embeddings", None),
    ],
    "Scoring": [
        ("trade_ai_orchestrator", "Trade AI Orchestrator (55-pt)", 7, "trade_ai_scans", "run_date = CURRENT_DATE"),
        ("multi_strategy_classifier", "Multi-Strategy Classifier", 7, "ticker_strategy_classifications", None),
    ],
    "Intelligence": [
        ("cio_decision_engine", "CIO Decision Engine", 7, "cio_decisions", "created_at::date = CURRENT_DATE"),
        ("agent_context_refresh", "Agent Context Refresh", 6, "agent_context_refreshes", "created_at::date = CURRENT_DATE"),
        ("strategy_rotation_signal_refresh", "Strategy Rotation Signals", 7, "strategy_rotation_signals", None),
        ("topic_curator", "Topic Curator", 7, "topic_monitor", None),
        ("pipeline_watchdog", "Pipeline Watchdog", 7, None, None),
    ],
    "Proposal Pipeline": [
        ("daily_incubator_refresh", "Daily Incubator Refresh", 7, "incubator_universe", "updated_at::date = CURRENT_DATE"),
        ("incubator_proposal_promoter", "Incubator Proposal Promoter", 7, "paper_trade_proposals", "created_at::date = CURRENT_DATE"),
        ("proposal_enrichment_loop", "Proposal Enrichment Loop", 7, "paper_trade_proposals", "updated_at::date = CURRENT_DATE"),
    ],
    "Execution": [
        ("risk_gate", "Risk Gate", 7, "risk_gate_results", "created_at::date = CURRENT_DATE"),
        ("live_trading_gate", "Live Trading Gate (paper mode)", 7, None, None),
        ("execution_quality", "Execution Quality Analyzer", 7, "paper_execution_quality", None),
        ("paper_execution_revalidation_scan", "Paper Execution Revalidation", 7, "paper_trade_execution_rechecks", None),
        ("execution_readiness_check", "Execution Readiness Check", 7, "proposal_execution_readiness", None),
    ],
    "Overnight": [
        ("overnight_batch", "Overnight Batch", 20, "aegis_portfolio_briefs", None),
        ("agent_outcome_scorer", "Agent Outcome Scorer", 20, "agent_recommendation_outcomes", None),
        ("system_facts", "Generate System Facts", 20, "system_facts_history", None),
        ("ingestion_learning_analysis", "Ingestion Learning Analysis", 20, "learning_evidence", None),
        ("trade_learning_analysis", "Trade Learning Analysis", 20, "trade_lesson_memory", None),
    ],
}


def _safe_query(conn, sql, params=None):
    """Execute a read-only query, return result or None on error."""
    if conn is None:
        return None
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def _safe_query_one(conn, sql, params=None):
    rows = _safe_query(conn, sql, params)
    if rows:
        return rows[0]
    return None


def _table_exists(conn, table_name):
    """Check if a table exists in the public schema."""
    row = _safe_query_one(
        conn,
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
        (table_name,),
    )
    return row is not None


def get_crontab_entries():
    """Read current user crontab, return list of (minute, hour, command_fragment) tuples."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        entries = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 6:
                try:
                    minute = parts[0]
                    hour = parts[1]
                    cmd = " ".join(parts[5:])
                    entries.append((minute, hour, cmd))
                except (ValueError, IndexError):
                    pass
        return entries
    except Exception:
        return []


def audit_stage(conn, stage_key, friendly_name, expected_hour, data_table, data_filter, now_hour, today_str, verbose):
    """Audit a single pipeline stage. Returns a dict with truth status."""
    result = {
        "stage_key": stage_key,
        "name": friendly_name,
        "expected_schedule_hour": expected_hour,
        "last_run": None,
        "last_run_status": None,
        "should_have_run": now_hour >= expected_hour,
        "data_produced_today": None,
        "data_row_count_today": None,
        "truth_status": "UNKNOWN",
    }

    # 1) Check pipeline_stage_runs for the most recent run of this stage
    if _table_exists(conn, "pipeline_stage_runs"):
        row = _safe_query_one(
            conn,
            """SELECT started_at, finished_at, status, duration_seconds
               FROM pipeline_stage_runs
               WHERE stage_key = %s
               ORDER BY started_at DESC LIMIT 1""",
            (stage_key,),
        )
        if row:
            result["last_run"] = row["started_at"].isoformat() if row.get("started_at") else None
            result["last_run_status"] = row.get("status")

    # 2) Check data presence if a data table is specified
    if data_table and _table_exists(conn, data_table):
        if data_filter:
            count_row = _safe_query_one(
                conn,
                f"SELECT count(*) AS cnt FROM {data_table} WHERE {data_filter}",
            )
        else:
            # No date filter -- just check if table has any rows at all
            count_row = _safe_query_one(
                conn,
                f"SELECT count(*) AS cnt FROM {data_table} LIMIT 1",
            )
        if count_row:
            cnt = count_row.get("cnt", 0)
            result["data_row_count_today"] = cnt
            result["data_produced_today"] = cnt > 0

    # 3) Determine truth_status
    last_run = result["last_run"]
    last_run_today = False
    last_run_stale = False
    if last_run:
        try:
            lr_dt = datetime.fromisoformat(last_run)
            if lr_dt.tzinfo is None:
                lr_dt = lr_dt.replace(tzinfo=timezone.utc)
            last_run_today = lr_dt.date() == datetime.now(timezone.utc).date()
            last_run_stale = (datetime.now(timezone.utc) - lr_dt) > timedelta(hours=36)
        except Exception:
            pass

    should_have_run = result["should_have_run"]
    data_produced = result["data_produced_today"]

    if last_run_today and result.get("last_run_status") in ("success", "completed", None):
        if data_produced is False and data_table:
            result["truth_status"] = "NO_DATA_PRODUCED"
        else:
            result["truth_status"] = "NOMINAL"
    elif not should_have_run:
        result["truth_status"] = "WAITING_FOR_SCHEDULE"
    elif last_run_stale and last_run:
        result["truth_status"] = "STALE"
    elif not last_run_today:
        # Data-presence fallback: if no pipeline_stage_runs entry but data exists today
        if data_produced is True:
            result["truth_status"] = "NOMINAL"
        else:
            result["truth_status"] = "NOT_STARTED_TODAY"
    else:
        result["truth_status"] = "NOMINAL"

    if verbose:
        status_icon = {
            "NOMINAL": "OK",
            "WAITING_FOR_SCHEDULE": "WAIT",
            "NOT_STARTED_TODAY": "MISS",
            "STALE": "STALE",
            "NO_DATA_PRODUCED": "EMPTY",
            "UNKNOWN": "??",
        }.get(result["truth_status"], "??")
        data_info = ""
        if result["data_row_count_today"] is not None:
            data_info = f"  rows_today={result['data_row_count_today']}"
        print(f"  [{status_icon:5s}] {friendly_name:<45s}  sched={expected_hour:02d}:00  last={result['last_run'] or 'never'}{data_info}")

    return result


def main():
    p = argparse.ArgumentParser(description="Pipeline truth audit (read-only)")
    p.add_argument("--output-json", type=str, help="Write JSON report to this path")
    p.add_argument("--output-md", type=str, help="Write Markdown report to this path")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    now_hour = now.hour  # UTC
    today_str = now.date().isoformat()

    conn = _get_conn()
    if conn is None:
        print("ERROR: Could not connect to database.")
        sys.exit(1)

    # Read crontab
    cron_entries = get_crontab_entries()

    # Audit all stages
    all_stages = []
    counters = {
        "total": 0,
        "completed_today": 0,
        "waiting": 0,
        "stale": 0,
        "no_data": 0,
        "not_started": 0,
        "unknown": 0,
    }

    for category, stages in PIPELINE_STAGES.items():
        if args.verbose:
            print(f"\n{'='*60}")
            print(f"  {category}")
            print(f"{'='*60}")
        for stage_key, name, expected_hour, data_table, data_filter in stages:
            stage_result = audit_stage(
                conn, stage_key, name, expected_hour,
                data_table, data_filter, now_hour, today_str, args.verbose,
            )
            stage_result["category"] = category
            all_stages.append(stage_result)
            counters["total"] += 1
            ts = stage_result["truth_status"]
            if ts == "NOMINAL":
                counters["completed_today"] += 1
            elif ts == "WAITING_FOR_SCHEDULE":
                counters["waiting"] += 1
            elif ts == "STALE":
                counters["stale"] += 1
            elif ts == "NO_DATA_PRODUCED":
                counters["no_data"] += 1
            elif ts == "NOT_STARTED_TODAY":
                counters["not_started"] += 1
            else:
                counters["unknown"] += 1

    # Build summary message
    issues = counters["stale"] + counters["no_data"] + counters["not_started"]
    if issues == 0:
        summary = f"All {counters['completed_today']} completed stages nominal, {counters['waiting']} waiting for schedule."
    else:
        parts = []
        if counters["not_started"]:
            parts.append(f"{counters['not_started']} not started")
        if counters["stale"]:
            parts.append(f"{counters['stale']} stale")
        if counters["no_data"]:
            parts.append(f"{counters['no_data']} produced no data")
        summary = f"{counters['completed_today']}/{counters['total']} nominal, {counters['waiting']} waiting. Issues: {', '.join(parts)}."

    report = {
        "generated_at": now.isoformat(),
        "audit_hour_utc": now_hour,
        "total_stages": counters["total"],
        "completed_today": counters["completed_today"],
        "waiting_for_schedule": counters["waiting"],
        "stale": counters["stale"],
        "no_data_produced": counters["no_data"],
        "not_started_today": counters["not_started"],
        "unknown": counters["unknown"],
        "cron_entries_count": len(cron_entries),
        "summary": summary,
        "stages": all_stages,
    }

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"  SUMMARY: {summary}")
        print(f"  Total={counters['total']}  Nominal={counters['completed_today']}  "
              f"Waiting={counters['waiting']}  NotStarted={counters['not_started']}  "
              f"Stale={counters['stale']}  NoData={counters['no_data']}")
        print(f"  Crontab entries: {len(cron_entries)}")
        print(f"{'='*60}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        if args.verbose:
            print(f"  JSON written to {args.output_json}")

    if args.output_md:
        md = []
        md.append(f"# Pipeline Truth Audit  {today_str}")
        md.append(f"\n**Summary:** {summary}")
        md.append(f"\n| Metric | Count |")
        md.append(f"|--------|-------|")
        md.append(f"| Total stages | {counters['total']} |")
        md.append(f"| Completed today | {counters['completed_today']} |")
        md.append(f"| Waiting for schedule | {counters['waiting']} |")
        md.append(f"| Not started today | {counters['not_started']} |")
        md.append(f"| Stale | {counters['stale']} |")
        md.append(f"| No data produced | {counters['no_data']} |")
        md.append(f"| Cron entries | {len(cron_entries)} |")
        md.append("")
        for category in PIPELINE_STAGES:
            cat_stages = [s for s in all_stages if s["category"] == category]
            md.append(f"\n## {category}")
            md.append(f"| Stage | Status | Last Run | Data Today |")
            md.append(f"|-------|--------|----------|------------|")
            for s in cat_stages:
                lr = s["last_run"] or "never"
                if len(lr) > 19:
                    lr = lr[:19]
                data = str(s["data_row_count_today"]) if s["data_row_count_today"] is not None else "n/a"
                md.append(f"| {s['name']} | {s['truth_status']} | {lr} | {data} |")
        Path(args.output_md).write_text("\n".join(md))
        if args.verbose:
            print(f"  Markdown written to {args.output_md}")

    # Print compact JSON to stdout
    print(json.dumps({k: v for k, v in report.items() if k != "stages"}, indent=2, default=str))


if __name__ == "__main__":
    main()
