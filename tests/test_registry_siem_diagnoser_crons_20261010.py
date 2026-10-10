"""siem-diagnoser-schedule (2026-10-10): the SIEM bridge and the LLM failure diagnoser declared as host-cron rows
before their crontab lines exist (REMEDIATION_PLAN §5 L2, §6 R1-R5).

Same pattern as tests/test_registry_ops_crons_20261009.py: kind cron, scheduler.expression = the 5 cron fields,
scheduler.install_line = the exact line the operator's `cron` grant installs, state PAUSED until then (green before
and after the install), then a registry PR flips it to ACTIVE. Hermetic: repo files only, no crontab, no systemctl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import reconcile_lane_registry as R  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402

REG = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
ROWS = {r["lane_id"]: r for r in REG["lanes"]}
LANES = {
    # lane_id: (schedule, script + mode, lock, timeout, log, cadence hours, receipt)
    "n8n-siem-bridge": ("1-59/5 * * * *", "scripts/n8n_siem_bridge.py --apply", "/tmp/tradeai_n8n_siem_bridge.lock",
                        "timeout -k 30 120 ", "logs/n8n_siem_bridge.log", 0.1, "data/runtime/n8n_siem_bridge_last.json"),
    "n8n-failure-diagnosis": ("3-59/15 * * * *", "scripts/n8n_failure_diagnosis.py --apply",
                              "/tmp/tradeai_n8n_failure_diagnosis.lock", "timeout -k 30 600 ",
                              "logs/n8n_failure_diagnosis.log", 0.25, "data/runtime/n8n_failure_diagnosis_last.json"),
}


@pytest.mark.parametrize("lane_id", sorted(LANES))
def test_row_is_paused_pending_install_with_the_exact_line(lane_id):
    sched, match, lock, timeout, log, cadence, receipt = LANES[lane_id]
    row = ROWS[lane_id]
    assert LR.validate_row(row) == []
    assert row["state"] == "PAUSED" and row["review_by"] and row["state_since"] == "2026-10-10"
    assert "PENDING INSTALL" in row["state_reason"] and "siem-diagnoser-schedule" in row["state_reason"]
    s = row["scheduler"]
    assert s["kind"] == "cron" and s["match"] == match and s["expression"] == sched
    line = s["install_line"]
    assert line.startswith(sched + " cd $PROJ && TRADEAI_STATE_ROOT=$HOME/trade-ai-releases/persistent-state ")
    assert f"bash $PROJ/scripts/safe_flock.sh {lock} {timeout}$PY {match}" in line
    assert f" >> {log} 2>&1  # TRADEAI_LANE {lane_id}" in line and line.endswith(f"# TRADEAI_LANE {lane_id}")
    assert "/home/" not in line and "%" not in line          # no host path; no cron-escaped char
    assert "--dry-run" not in line and "run_with_deepseek_offpeak" not in line   # see state_reason (diagnoser)
    assert row["expected_cadence_hours"] == cadence and R.cron_cadence_hours(sched) <= cadence
    assert row["output_signal"] == {"kind": "json_key", "path": receipt, "key": "ok_at"}
    assert row["severity"] == "High" and row["remediation"]


def test_lines_are_discovered_as_exactly_these_lanes():
    text = "\n".join(ROWS[lid]["scheduler"]["install_line"] for lid in LANES) + "\n"
    found = LR.discover_cron(text)
    assert len(found) == 2
    for job in found:
        hits = [lid for lid in LANES if ROWS[lid]["scheduler"]["match"] in job["expression"]]
        assert len(hits) == 1


def test_neither_lane_is_a_sender_or_on_the_n8n_allowlist():
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    assert not {x.get("lane_id") for x in allow.get("lanes") or []} & set(LANES)
    for lid in LANES:
        line = ROWS[lid]["scheduler"]["install_line"]
        assert "TELEGRAM" not in line and ".env" not in line
