#!/usr/bin/env python3
"""High-Level LLM Priority Scheduler — dry-run simulation.

Reads candidate jobs from various sources and simulates a priority-based
nightly schedule. Does NOT run any LLM jobs. File output only.

Usage:
    python scripts/high_llm_priority_scheduler.py
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PR = Path(__file__).resolve().parent.parent
OUT = PR / "docs" / "llm" / "high_llm_scheduler_dryruns"
OUT.mkdir(parents=True, exist_ok=True)

# Simulated candidate jobs (would come from DB in production)
CANDIDATE_JOBS = [
    {"job_type": "ticker_thesis_challenge", "source": "hermes", "urgency": 0.6, "portfolio_impact": 0.5,
     "evidence_gap": 0.7, "operator_value": 0.6, "staleness": 0, "runtime_est": 300, "model": "gemma3:12b",
     "pool": "hermes_research"},
    {"job_type": "strategy_backtest_analysis", "source": "tradeai", "urgency": 0.8, "portfolio_impact": 0.9,
     "evidence_gap": 0.8, "operator_value": 0.9, "staleness": 3, "runtime_est": 600, "model": "gemma3:12b",
     "pool": "journal_backtest"},
    {"job_type": "income_rotation_research", "source": "hermes", "urgency": 0.5, "portfolio_impact": 0.8,
     "evidence_gap": 0.6, "operator_value": 0.7, "staleness": 1, "runtime_est": 400, "model": "gemma3:12b",
     "pool": "portfolio_risk"},
    {"job_type": "deep_overnight_batch", "source": "tradeai", "urgency": 0.4, "portfolio_impact": 0.5,
     "evidence_gap": 0.5, "operator_value": 0.5, "staleness": 0, "runtime_est": 3600, "model": "gemma3:12b",
     "pool": "legacy_overnight"},
    {"job_type": "catalyst_quality_review", "source": "hermes", "urgency": 0.3, "portfolio_impact": 0.4,
     "evidence_gap": 0.6, "operator_value": 0.5, "staleness": 2, "runtime_est": 200, "model": "gemma3:12b",
     "pool": "hermes_research"},
    {"job_type": "journal_thesis_review", "source": "tradeai", "urgency": 0.7, "portfolio_impact": 0.7,
     "evidence_gap": 0.9, "operator_value": 0.8, "staleness": 5, "runtime_est": 500, "model": "gemma3:12b",
     "pool": "journal_backtest"},
    {"job_type": "portfolio_reflection", "source": "hermes", "urgency": 0.5, "portfolio_impact": 0.6,
     "evidence_gap": 0.5, "operator_value": 0.6, "staleness": 0, "runtime_est": 300, "model": "gemma3:12b",
     "pool": "portfolio_risk"},
]

NIGHTLY_WINDOW_SEC = 6 * 3600  # 6 hours
QUOTA = {"journal_backtest": 0.20, "portfolio_risk": 0.20, "hermes_research": 0.20,
         "flex": 0.20, "legacy_overnight": 0.20}

def score(j):
    age_boost = min(j["staleness"] * 0.1, 0.3)
    return round(
        3.0 * j["urgency"] + 2.5 * j["portfolio_impact"] + 2.0 * j["evidence_gap"]
        + 1.5 * j["operator_value"] + 1.0 * age_boost, 2)

def main():
    now = datetime.now(timezone.utc)
    ds = now.strftime("%Y-%m-%d")

    for j in CANDIDATE_JOBS:
        j["priority_score"] = score(j)

    sorted_jobs = sorted(CANDIDATE_JOBS, key=lambda x: x["priority_score"], reverse=True)

    # Apply quotas
    pool_used = {k: 0 for k in QUOTA}
    pool_budget = {k: int(v * NIGHTLY_WINDOW_SEC) for k, v in QUOTA.items()}
    scheduled = []
    skipped = []
    total_runtime = 0

    for j in sorted_jobs:
        pool = j["pool"]
        if pool not in pool_used:
            pool = "flex"
        budget_remaining = pool_budget[pool] - pool_used[pool]
        if j["runtime_est"] <= budget_remaining and total_runtime + j["runtime_est"] <= NIGHTLY_WINDOW_SEC:
            scheduled.append(j)
            pool_used[pool] += j["runtime_est"]
            total_runtime += j["runtime_est"]
        else:
            j["skip_reason"] = f"pool {pool} budget exhausted or window full"
            skipped.append(j)

    result = {
        "date": ds, "timestamp": now.isoformat(),
        "nightly_window_sec": NIGHTLY_WINDOW_SEC,
        "scheduled": [{"job_type": j["job_type"], "source": j["source"], "priority": j["priority_score"],
                       "runtime_est": j["runtime_est"], "pool": j["pool"]} for j in scheduled],
        "skipped": [{"job_type": j["job_type"], "priority": j["priority_score"],
                     "reason": j.get("skip_reason","")} for j in skipped],
        "total_scheduled": len(scheduled),
        "total_runtime_est": total_runtime,
        "pool_usage": {k: {"used": pool_used[k], "budget": pool_budget[k]} for k in QUOTA},
        "model_swaps_est": len(set(j["model"] for j in scheduled)),
        "llm_jobs_run": 0,
    }

    (OUT / "latest_schedule.json").write_text(json.dumps(result, indent=2))
    lines = [f"# High-LLM Priority Schedule — {ds}", "",
             f"Scheduled: {len(scheduled)}/{len(CANDIDATE_JOBS)}",
             f"Est runtime: {total_runtime}s / {NIGHTLY_WINDOW_SEC}s window", "",
             "## Run Order", ""]
    for i, j in enumerate(scheduled, 1):
        lines.append(f"{i}. [{j['priority_score']}] {j['job_type']} ({j['source']}) — {j['runtime_est']}s")
    if skipped:
        lines += ["", "## Skipped", ""]
        for j in skipped:
            lines.append(f"- {j['job_type']} — {j.get('skip_reason','')}")
    lines += ["", "**LLM jobs actually run: ZERO (dry-run simulation)**"]
    (OUT / f"{ds}_schedule.md").write_text("\n".join(lines))

    print(f"Scheduled: {len(scheduled)}/{len(CANDIDATE_JOBS)}, Runtime: {total_runtime}s/{NIGHTLY_WINDOW_SEC}s")
    print("LLM jobs run: 0 (dry-run)")

if __name__ == "__main__":
    main()
