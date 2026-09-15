"""2026-09-15 regressions from #1031: deferral wrote an illegal maturity status; the drain ran on the stale env cap."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = (ROOT / "scripts" / "process_watchlist_agent_jobs.py").read_text()
WRAPPER = (ROOT / "scripts" / "run_watchlist_agent_jobs_offpeak.sh").read_text()
# watchlist_analysis_maturity_{maria,steph,risk,tax,full_chain}_status_check
AGENT_STATUS_ALLOWED = {"not_required", "required", "queued", "processing", "completed", "failed"}


def test_every_literal_agent_maturity_status_is_allowed_by_the_db_constraint():
    used = set(re.findall(r'_update_maturity\(\s*conn\s*,\s*\w+\s*,\s*\w+\s*,\s*"([a-z_]+)"', WORKER))
    assert used, "no literal _update_maturity statuses found"
    assert used <= AGENT_STATUS_ALLOWED, f"illegal statuses: {sorted(used - AGENT_STATUS_ALLOWED)}"


def test_the_drain_loads_the_host_cap_file_after_the_runtime_env():
    i_runtime = WRAPPER.index("/run/user/")
    i_cap = WRAPPER.index("llm_global_daily_usd_cap.env")
    i_check = WRAPPER.index("LLM_GLOBAL_DAILY_USD_CAP_ok")
    assert i_runtime < i_cap < i_check
