#!/usr/bin/env python3
"""Hermes Observation Check — read-only daily health report.

Usage:
    python scripts/hermes_observation_check.py

Safety:
    - Read-only: no DB writes, no alerts, no service changes
    - File output only to docs/hermes/observations/
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "docs" / "hermes" / "observations"
OUT.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e)[:200], -1


def http_check(url, timeout=5):
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return resp.status, True
    except Exception as e:
        return str(e)[:100], False


def db_count(query):
    try:
        import psycopg2
        env_path = PROJECT_ROOT / ".env"
        db_pass = None
        for line in env_path.read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                db_pass = line.split("=", 1)[1]
        conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)
        cur = conn.cursor()
        cur.execute(query)
        result = cur.fetchone()[0]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        return f"ERROR: {str(e)[:100]}"


def main():
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    checks = {}

    # 1. Hermes gateway
    out, rc = run_cmd(["systemctl", "--user", "is-active", "hermes-gateway.service"])
    checks["hermes_gateway"] = {"status": out, "ok": rc == 0}

    # 2. Hermes autonomous loop timer
    out, rc = run_cmd(["systemctl", "--user", "is-active", "hermes-autonomous-loop.timer"])
    checks["hermes_loop_timer"] = {"status": out, "ok": rc == 0}

    # 3. Last loop log (last 3 lines)
    out, rc = run_cmd("journalctl --user -u hermes-autonomous-loop.service -n 3 --no-pager 2>/dev/null | tail -3")
    checks["hermes_loop_last_log"] = {"log": out[:300], "ok": rc == 0}

    # 4. SearXNG container
    out, rc = run_cmd("sg docker -c 'docker ps --filter name=searxng --format {{.Status}}' 2>/dev/null")
    checks["searxng_container"] = {"status": out or "not running", "ok": "Up" in (out or "")}

    # 5. SearXNG endpoint
    status, ok = http_check("http://127.0.0.1:18888/")
    checks["searxng_endpoint"] = {"http_status": status, "ok": ok}

    # 6. Research backlog count
    count = db_count("SELECT COUNT(*) FROM hermes_research_intelligence WHERE research_type='research_backlog'")
    checks["research_backlog_count"] = {"count": count, "ok": isinstance(count, int)}

    # 7. Staged/promoted counts
    staged = db_count("SELECT COUNT(*) FROM hermes_research_intelligence WHERE status='staged'")
    promoted = db_count("SELECT COUNT(*) FROM hermes_research_intelligence WHERE status='promoted'")
    total = db_count("SELECT COUNT(*) FROM hermes_research_intelligence")
    checks["hermes_rows"] = {"total": total, "staged": staged, "promoted": promoted, "ok": isinstance(total, int)}

    # 8. Embeddings count
    emb = db_count("SELECT COUNT(*) FROM content_embeddings WHERE source_type='hermes_research'")
    checks["hermes_embeddings"] = {"count": emb, "ok": isinstance(emb, int)}

    # 9. Kill switch
    kill_path = PROJECT_ROOT / "hermes_sidecar" / ".hermes" / "DISABLED"
    checks["kill_switch"] = {"active": kill_path.exists(), "ok": True}

    # 10. Safe view availability
    view_ok = db_count("SELECT 1 FROM hermes_v_catalyst_quality_context LIMIT 1")
    checks["safe_views"] = {"accessible": view_ok == 1, "ok": view_ok == 1}

    # 11. Dashboard endpoint
    status, ok = http_check("http://127.0.0.1:7777/api/v2/hermes/health")
    checks["dashboard_health"] = {"http_status": status, "ok": ok}

    # 12. Cron count
    out, rc = run_cmd("crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$' | grep -v '^SHELL\\|^PROJ\\|^PY' | wc -l")
    checks["cron_count"] = {"count": int(out) if out.isdigit() else out, "ok": rc == 0}

    # Summary
    total_checks = len(checks)
    passed = sum(1 for c in checks.values() if c.get("ok"))
    warnings = [k for k, v in checks.items() if not v.get("ok")]

    summary = {
        "date": date_str,
        "timestamp": now.isoformat(),
        "total_checks": total_checks,
        "passed": passed,
        "warnings": warnings,
        "checks": {k: {kk: str(vv) if not isinstance(vv, (int, float, bool, type(None))) else vv
                        for kk, vv in v.items()} for k, v in checks.items()},
    }

    # Write JSON
    (OUT / "latest_observation_summary.json").write_text(json.dumps(summary, indent=2))

    # Write markdown report
    lines = [
        f"# Hermes Observation Report — {date_str}",
        "",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Checks:** {passed}/{total_checks} passed",
        "",
        "---",
        "",
    ]
    for name, data in checks.items():
        ok_str = "PASS" if data.get("ok") else "WARN"
        lines.append(f"## {name.replace('_',' ').title()} — {ok_str}")
        for k, v in data.items():
            if k != "ok":
                lines.append(f"- {k}: {v}")
        lines.append("")

    if warnings:
        lines.append("## Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("---")
    lines.append("**Read-only observation. No DB writes. No alerts. No service changes.**")

    (OUT / f"{date_str}_observation_report.md").write_text("\n".join(lines))

    print(f"Observation: {passed}/{total_checks} checks passed")
    if warnings:
        print(f"Warnings: {', '.join(warnings)}")
    print(f"Report: {OUT}/{date_str}_observation_report.md")
    print("DB writes: 0 | Alerts: 0 | Service changes: 0")


if __name__ == "__main__":
    main()
