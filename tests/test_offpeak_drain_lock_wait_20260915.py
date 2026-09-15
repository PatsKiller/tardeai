"""R-03 (2026-09-15): the agent-job drain waits for the market canary's lock instead of losing every tick."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAIN = (ROOT / "scripts" / "run_watchlist_agent_jobs_offpeak.sh").read_text()
CANARY = (ROOT / "scripts" / "run_governed_agent_flash_market.sh").read_text()


def _live_flock_lines(text):
    return [ln for ln in text.splitlines() if re.search(r"^\s*flock\b", ln) and "process_watchlist_agent_jobs.py" in ln]


def test_the_paid_drain_waits_a_bounded_time_for_the_shared_lock():
    lines = _live_flock_lines(DRAIN)
    assert len(lines) == 1 and '-w "$LOCK_WAIT_SEC"' in lines[0] and " -n " not in lines[0]
    default = int(re.search(r'LOCK_WAIT_SEC="\$\{TRADEAI_OFFPEAK_LOCK_WAIT_SEC:-(\d+)\}"', DRAIN).group(1))
    canary_max = int(re.search(r"Hard timeout <= (\d+)s", CANARY).group(1))
    # longer than the canary can hold the lock, shorter than the 15-minute drain interval
    assert canary_max < default < 900


def test_both_lanes_share_the_same_production_lock():
    assert "/tmp/tradeai_watchlist_agent_jobs.lock" in DRAIN and "/tmp/tradeai_watchlist_agent_jobs.lock" in CANARY


def test_flock_wait_acquires_a_lock_released_within_the_wait(tmp_path):
    lock = tmp_path / "jobs.lock"
    holder = subprocess.Popen(["flock", str(lock), "sleep", "1.5"])
    time.sleep(0.3)
    t0 = time.time()
    rc = subprocess.run(["flock", "-w", "10", "-E", "99", str(lock), sys.executable, "-c", "pass"]).returncode
    holder.wait()
    assert rc == 0 and time.time() - t0 >= 1.0
    assert subprocess.run(["flock", "-n", "-E", "99", str(lock), "true"]).returncode == 0
