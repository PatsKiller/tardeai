"""ANCHOR: ANALYST_WEEKLY_ALLOWLIST_TIMEOUT_LQ1413_20261109 — weekly analyst n8n bound is 6h.

LQ-20261107-1413. The 2026-11-08 cron run of generate_analyst_reports_autonomous.py --mode weekly
took about 2h25m. The allowlist bound was 1800s (30 min), so the n8n slot could not finish the
job. Cron line 577 was retired 2026-11-09 00:02 ET, and n8n is now the only scheduler. The next
fire is Sunday 2026-11-15 21:15 ET. 21600s is 6h, which covers the measured run and still ends
before the next weekly fire. Synthetic read of the allowlist only.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
LANES = {e["lane_id"]: e for e in DOC["lanes"]}

MEASURED_RUN_S = 2 * 3600 + 25 * 60
WEEK_S = 7 * 24 * 3600


def test_weekly_analyst_timeout_covers_the_measured_run():
    entry = LANES["generate-analyst-reports-autonomous-weekly"]
    assert entry["timeout_s"] == 21600
    assert entry["timeout_s"] >= MEASURED_RUN_S
    assert entry["timeout_s"] < WEEK_S
    assert entry["live_arg"] == ["--mode", "weekly"]
    assert entry["lock"] == "/tmp/analyst_reports_weekly.lock"
    assert entry["lock_kind"] == "flock"
