#!/usr/bin/env python3
"""Data Product Freshness Checker.

Verifies that dashboard-critical data products are within their staleness SLA.
Checks files, DB tables, and API endpoints.

Usage:
    python3 scripts/check_data_product_freshness.py          # human-readable
    python3 scripts/check_data_product_freshness.py --json    # JSON output
"""
import json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
API_BASE = "http://localhost:7777"

results = []


def _now():
    return datetime.now()


def _file_age_hours(path):
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return round((_now() - mtime).total_seconds() / 3600, 1)


def _json_ts_age_hours(path, ts_field):
    if not path.exists():
        return None
    try:
        d = json.load(open(path))
        ts = d.get(ts_field)
        if not ts:
            return None
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
        return round((_now() - dt).total_seconds() / 3600, 1)
    except Exception:
        return None


def _db_age_hours(sql):
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        dt = row[0].replace(tzinfo=None) if hasattr(row[0], 'replace') else datetime.fromisoformat(str(row[0]))
        return round((_now() - dt).total_seconds() / 3600, 1)
    except Exception:
        return None


def _api_get(path):
    try:
        with urllib.request.urlopen(f"{API_BASE}{path}", timeout=15) as r:
            return json.loads(r.read())
    except Exception:
        return None


def check(product, max_stale_h, age_h, source_desc, remediation=None):
    if age_h is None:
        status = "FAIL"
        detail = f"Cannot determine age (source: {source_desc})"
    elif age_h > max_stale_h:
        status = "FAIL"
        detail = f"Stale: {age_h:.0f}h old (max {max_stale_h}h) — {source_desc}"
    elif age_h > max_stale_h * 0.75:
        status = "WARN"
        detail = f"Aging: {age_h:.0f}h old (max {max_stale_h}h) — {source_desc}"
    else:
        status = "PASS"
        detail = f"Fresh: {age_h:.0f}h old (max {max_stale_h}h) — {source_desc}"
    results.append({"product": product, "status": status, "detail": detail,
                     "age_hours": age_h, "max_stale_hours": max_stale_h,
                     "remediation": remediation})
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(status, "?")
    if "--json" not in sys.argv:
        print(f"  {icon} [{status}] {product}: {detail}")


def check_special(product, status, detail):
    results.append({"product": product, "status": status, "detail": detail,
                     "age_hours": None, "max_stale_hours": None, "remediation": None})
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(status, "?")
    if "--json" not in sys.argv:
        print(f"  {icon} [{status}] {product}: {detail}")


def main():
    if "--json" not in sys.argv:
        print("\n=== Data Product Freshness Check ===\n")

    # File-based products
    check("current_portfolio_snapshot", 24,
          _file_age_hours(STATE_DIR / "holdings.json"),
          "holdings.json mtime",
          ".venv/bin/python scripts/portfolio_price_cache.py")

    check("risk_snapshot", 24,
          _file_age_hours(STATE_DIR / "risk_management.json"),
          "risk_management.json mtime")

    check("dividend_calendar", 48,
          _file_age_hours(STATE_DIR / "dividend_calendar.json"),
          "dividend_calendar.json mtime")

    check("ai_analyst_cache", 48,
          _json_ts_age_hours(STATE_DIR / "ai_analysis_cache.json", "generated_at"),
          "ai_analysis_cache.json generated_at",
          ".venv/bin/python scripts/ai_daily_pipeline.py")

    check("retirement_roadmap", 168,
          _file_age_hours(STATE_DIR / "retirement_roadmap.json"),
          "retirement_roadmap.json mtime")

    check("performance_history", 48,
          _file_age_hours(STATE_DIR / "performance_history.json"),
          "performance_history.json mtime")

    # DB-based products
    check("news_articles", 6,
          _db_age_hours("SELECT MAX(created_at) FROM news_articles"),
          "news_articles MAX(created_at)",
          ".venv/bin/python scripts/news_ingestion.py --priority")

    check("cio_decisions", 48,
          _db_age_hours("SELECT MAX(created_at) FROM cio_decisions"),
          "cio_decisions MAX(created_at)")

    check("agent_calibration", 168,
          _db_age_hours("SELECT MAX(computed_at) FROM agent_calibration"),
          "agent_calibration MAX(computed_at)",
          ".venv/bin/python scripts/agent_calibration_engine.py")

    check("topic_monitor", 336,
          _db_age_hours("SELECT MAX(last_searched) FROM topic_monitor WHERE enabled=true"),
          "topic_monitor MAX(last_searched)",
          "curl -X POST localhost:7777/api/v2/topics/run")

    check("paper_proposals", 4,
          _db_age_hours("SELECT MAX(created_at) FROM paper_trade_proposals WHERE status='pending'"),
          "paper_trade_proposals MAX(created_at) pending")

    check("watchlist_agent_jobs", 2,
          _db_age_hours("SELECT MAX(created_at) FROM watchlist_agent_jobs WHERE status='completed'"),
          "watchlist_agent_jobs MAX completed",
          ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 5")

    check("weekly_learning", 168,
          _db_age_hours("SELECT MAX(generated_at) FROM weekly_learning_digests"),
          "weekly_learning_digests MAX(generated_at)",
          ".venv/bin/python scripts/weekly_learning_export.py")

    check("broker_reconciliation", 48,
          _db_age_hours("SELECT MAX(created_at) FROM broker_reconciliation"),
          "broker_reconciliation MAX(created_at)")

    check("morning_brief", 48,
          _db_age_hours("SELECT MAX(observed_at) FROM aegis_portfolio_briefs"),
          "aegis_portfolio_briefs MAX(observed_at)")

    check("screener_results", 48,
          _db_age_hours("SELECT MAX(run_started_at) FROM pipeline_runs WHERE pipeline_key ILIKE '%screener%'"),
          "pipeline_runs screener MAX(run_started_at)")

    # Pipeline health check
    ph = _api_get("/api/v2/pipeline-health-master")
    if ph:
        summary = ph.get("summary", ph.get("data", {}).get("summary", {}))
        healthy = summary.get("healthy", 0)
        critical = summary.get("critical", 0)
        warnings = summary.get("warnings", 0)
        never = summary.get("never_run", 0)
        total = summary.get("total_stages", 31)
        if critical > 0:
            check_special("pipeline_health", "FAIL",
                          f"{healthy}/{total} healthy, {critical} critical, {warnings} warnings, {never} never_run")
        elif warnings > 2 or never > 5:
            check_special("pipeline_health", "WARN",
                          f"{healthy}/{total} healthy, {critical} critical, {warnings} warnings, {never} never_run")
        else:
            check_special("pipeline_health", "PASS",
                          f"{healthy}/{total} healthy, {critical} critical, {warnings} warnings, {never} never_run")

    # Agent queue backlog
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status='queued'")
        queued = cur.fetchone()[0]
        conn.close()
        if queued > 100:
            check_special("agent_queue_backlog", "FAIL", f"{queued} queued jobs (>100)")
        elif queued > 50:
            check_special("agent_queue_backlog", "WARN", f"{queued} queued jobs (>50)")
        else:
            check_special("agent_queue_backlog", "PASS", f"{queued} queued jobs")
    except Exception:
        check_special("agent_queue_backlog", "WARN", "Cannot check queue")

    # CIO duplicate check
    try:
        d = _api_get("/api/v2/cio-decisions")
        if d:
            decisions = d.get("data", d).get("decisions", [])
            symbols = [x.get("symbol", "") for x in decisions]
            dupes = [s for s in set(symbols) if symbols.count(s) > 1]
            if dupes:
                check_special("cio_dedup", "FAIL", f"Duplicate symbols: {dupes[:5]}")
            else:
                check_special("cio_dedup", "PASS", f"{len(decisions)} decisions, no duplicates")
    except Exception:
        pass

    # Summary
    fails = sum(1 for r in results if r["status"] == "FAIL")
    warns = sum(1 for r in results if r["status"] == "WARN")
    passes = sum(1 for r in results if r["status"] == "PASS")

    if "--json" in sys.argv:
        print(json.dumps({"summary": {"pass": passes, "warn": warns, "fail": fails},
                          "products": results}, indent=2, default=str))
    else:
        print(f"\n=== Summary ===")
        print(f"  PASS: {passes}  WARN: {warns}  FAIL: {fails}")

    sys.exit(1 if fails > 0 else (2 if warns > 0 else 0))


if __name__ == "__main__":
    main()
