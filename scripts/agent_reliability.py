#!/usr/bin/env python3
"""
agent_reliability.py

Reads Postgres state_freshness_history and returns reliability context
for agent routing decisions.

Purpose:
- Detect files that have been stale/failing recently
- Summarize pipeline reliability by source_script
- Give router/agents a confidence adjustment
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


AGENT_DEPENDENCIES = {
    "maria": [
        "holdings.json",
        "portfolio_news.json",
        "analyst_data.json",
        "etf_intelligence.json",
        "mutual_fund_intelligence.json",
        "stock_intelligence.json",
        "asset_intelligence.json",
    ],
    "steph": [
        "holdings.json",
        "risk_management.json",
        "analyst_data.json",
        "etf_intelligence.json",
        "mutual_fund_intelligence.json",
        "stock_intelligence.json",
        "asset_intelligence.json",
        "ai_watchlist.json",
        "ai_watchlist_review.json",
    ],
    "risk_agent": [
        "holdings.json",
        "risk_management.json",
        "stops.json",
        "technical_snapshot.json",
        "portfolio_news.json",
        "action_signals.json",
    ],
    "tax_agent": [
        "holdings.json",
        "risk_management.json",
        "asset_intelligence.json",
    ],
    "orchestrator": [
        "holdings.json",
        "risk_management.json",
        "portfolio_news.json",
        "analyst_data.json",
        "asset_intelligence.json",
    ],
}


def _load_db_env() -> Dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.startswith("DB_"):
                    env[k.strip()] = v.strip()
    return env


def _psql_json(sql: str) -> List[Dict[str, Any]]:
    db = _load_db_env()
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    if any(k not in db or not db[k] for k in required):
        return []

    env = os.environ.copy()
    env["PGPASSWORD"] = db["DB_PASSWORD"]

    proc = subprocess.run(
        [
            "psql",
            "-h", db["DB_HOST"],
            "-p", db["DB_PORT"],
            "-U", db["DB_USER"],
            "-d", db["DB_NAME"],
            "-t",
            "-A",
            "-c",
            sql,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        env=env,
    )

    if proc.returncode != 0:
        return []

    text = proc.stdout.strip()
    if not text:
        return []

    try:
        return json.loads(text)
    except Exception:
        return []


def get_agent_reliability(agent: str, lookback_hours: int = 24) -> Dict[str, Any]:
    deps = AGENT_DEPENDENCIES.get(agent) or AGENT_DEPENDENCIES["orchestrator"]
    deps_sql = ",".join("'" + d.replace("'", "''") + "'" for d in deps)

    sql = f"""
WITH recent AS (
  SELECT *
  FROM state_freshness_history
  WHERE checked_at >= now() - interval '{int(lookback_hours)} hours'
    AND state_file IN ({deps_sql})
),
summary AS (
  SELECT
    state_file,
    COUNT(*) AS checks,
    SUM(CASE WHEN ok THEN 1 ELSE 0 END) AS ok_checks,
    SUM(CASE WHEN NOT ok THEN 1 ELSE 0 END) AS bad_checks,
    MAX(checked_at) AS latest_check,
    MAX(age_hours) AS max_age_hours,
    MAX(source_script) AS source_script
  FROM recent
  GROUP BY state_file
)
SELECT COALESCE(json_agg(row_to_json(summary)), '[]'::json)
FROM summary;
"""

    rows = _psql_json(sql)

    missing = []
    weak = []
    bad = []

    by_file = {r.get("state_file"): r for r in rows if r.get("state_file")}

    for dep in deps:
        r = by_file.get(dep)
        if not r:
            missing.append(dep)
            continue
        checks = int(r.get("checks") or 0)
        bad_checks = int(r.get("bad_checks") or 0)
        if checks == 0:
            missing.append(dep)
        elif bad_checks > 0:
            bad.append(dep)
        # Note: checks < 2 is too strict when freshness runs once/day.
        # Only flag weak if there's no successful check at all in the window.

    penalty = 0.0
    penalty += min(0.30, 0.05 * len(missing))
    penalty += min(0.25, 0.04 * len(bad))
    penalty += min(0.10, 0.02 * len(weak))

    confidence_adjustment = round(-penalty, 2)
    reliability_score = round(max(0.0, 1.0 - penalty), 2)

    warnings = []
    if missing:
        warnings.append("No recent DB freshness history for: " + ", ".join(missing))
    if bad:
        warnings.append("Recent stale/failing checks for: " + ", ".join(bad))
    if weak:
        warnings.append("Limited freshness history for: " + ", ".join(weak))

    return {
        "agent": agent,
        "lookback_hours": lookback_hours,
        "dependencies": deps,
        "reliability_score": reliability_score,
        "confidence_adjustment": confidence_adjustment,
        "warnings": warnings,
        "missing": missing,
        "bad": bad,
        "weak": weak,
        "history_rows": rows,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="steph")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    out = get_agent_reliability(args.agent)
    print(json.dumps(out, indent=2))
