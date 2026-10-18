"""Hermes outcome_feedback_agent cutover to n8n (operator 2026-10-17 "fix now move to n8n now"; decision D2: the
comms-intent consumer goes live first). Pins the narrow queue-only notify gate and the packet's refusals. Hermetic:
no live ledger, crontab, relay env or service is touched (every path is a tmp_path stub)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.lib import lane_dispatch as LD

ROOT = Path(__file__).resolve().parents[1]
LANE = "hermes-learning-outcome-feedback-agent"
GRANT = "0123456789abcdef0123456789abcdef"  # fake active config-write grant id in a tmp guard ledger
PACKET = ROOT / "docs" / "ops" / "packets" / "hermes-feedback-cutover-20261017" / "cutover.sh"
ALLOW = {e["lane_id"]: e for e in json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())["lanes"]}
CMD = ["$PY", "scripts/hermes_outcome_feedback_agent.py"]


def test_queue_only_argv_is_exactly_one_lane_one_argv():
    assert dict(LD.QUEUE_ONLY_NOTIFY_ARGV) == {LANE: ("--apply", "--notify", "queue")}


def test_queue_argv_is_stripped_for_this_lane_only():
    assert LD.strip_queue_only_notify(LANE, CMD + ["--apply", "--notify", "queue"]) == CMD + ["--apply"]
    other = "hermes-learning-outcome-grader"
    argv = CMD + ["--apply", "--notify", "queue"]
    assert LD.strip_queue_only_notify(other, argv) == argv


@pytest.mark.parametrize("tail", [
    ["--apply", "--notify", "chokepoint"],
    ["--apply", "--notify", "record"],
    ["--notify", "queue", "--apply"],
    ["--apply", "--notify", "queue", "--send"],
    ["--apply", "--notify", "QUEUE"],
])
def test_any_other_notify_shape_is_left_for_the_sender_gates(tail):
    argv = CMD + tail
    assert LD.strip_queue_only_notify(LANE, argv) == argv


def test_allowlist_live_arg_is_the_queue_argv_and_matches_the_process_spec():
    spec = json.loads((ROOT / "config" / "n8n_fabric_processes.json").read_text())
    step = spec["processes"]["hermes-learning"]["steps"]["outcome_feedback_agent"]
    assert ALLOW[LANE]["live_arg"] == step["cutover_live_arg"] == ["--apply", "--notify", "queue"]
    assert ALLOW[LANE]["command"] == CMD


def test_feedback_route_has_one_producer_and_no_page():
    routes = json.loads((ROOT / "config" / "host_comms_intent_routes.json").read_text())["routes"]
    mine = [r for r in routes if r.get("domain") == "research" and r.get("kind") == "hermes_closed_loop_alert"]
    assert len(mine) == 1
    assert "PAGE" not in json.dumps(mine[0]).upper().replace("PAGED", "")


def test_packet_is_dry_by_default_and_names_no_crontab_edit():
    text = PACKET.read_text(encoding="utf-8")
    assert os.access(PACKET, os.X_OK)
    assert "set -f" in text and "NO crontab change" in text
    assert '"$CRONTAB_BIN" - <' not in text  # reads the crontab (-l), never installs one


def _run(tmp_path, *args, now="1400", live_lanes=""):
    env_file = tmp_path / "live.env"
    env_file.write_text(f"TRADEAI_N8N_RELAY_LIVE_LANES={live_lanes}\n")
    cron = tmp_path / "crontab"
    cron.write_text("#!/bin/sh\necho '20 11 * * * cd $PROJ && PIPELINE_EFFECT_CLAIM=1 bash "
                    "scripts/pipelines/run_hermes_pipeline.sh --stage learn --apply'\n")
    cron.chmod(0o755)
    approvals = tmp_path / "approvals"
    approvals.mkdir(exist_ok=True)
    (approvals / "grants.json").write_text(json.dumps({"grants": {"config-write": {
        "grant_id": GRANT, "expires": time.time() + 3600, "uses": 5}}}))
    env = dict(os.environ, SERVED=str(ROOT), LIVE_LANES_ENV=str(env_file), CRONTAB_BIN=str(cron), NOW_HM=now,
               FX_LEDGER=str(tmp_path / "fx.sqlite"), LEDGER=str(tmp_path / "ledger.sqlite"),
               GUARD_APPROVALS_DIR=str(approvals), TRADEAI_FABRIC_GRANT=GRANT,
               PY=os.environ.get("PYTHON", "python3"))
    import sys
    env["PY"] = sys.executable
    return subprocess.run(["bash", str(PACKET), *args], env=env, capture_output=True, text=True, timeout=60)


def test_c3_refused_inside_the_learn_window(tmp_path):
    r = _run(tmp_path, "c3", "--apply", now="1105")
    assert r.returncode != 0 and "REFUSED" in r.stdout


def test_c3_refused_while_the_consumer_is_not_live(tmp_path):
    r = _run(tmp_path, "c3", "--apply", now="1400", live_lanes=LANE)
    assert r.returncode != 0 and "REFUSED" in r.stdout
    assert "n8n-comms-intent-consumer" in r.stdout or "NOT served" in r.stdout


def test_relay_dry_run_changes_nothing(tmp_path):
    r = _run(tmp_path, "relay", live_lanes="a b")
    assert (tmp_path / "live.env").read_text() == "TRADEAI_N8N_RELAY_LIVE_LANES=a b\n"
    assert "DRY RUN" in r.stdout or "REFUSED" in r.stdout


def test_registered_in_the_cio_hardening_gates():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "tests/test_hermes_feedback_cutover_20261017.py" in text




def _fake_systemctl(tmp_path):
    calls = tmp_path / "systemctl.calls"
    sc = tmp_path / "systemctl"
    sc.write_text(f'#!/usr/bin/env bash\necho "$*" >> {calls}\n')
    sc.chmod(0o755)
    return sc, calls


def test_relay_apply_refuses_a_label_and_never_touches_services(tmp_path):
    """10-18: relay --apply had NO grant check and called the real systemctl; now the grant gates it first."""
    sc, calls = _fake_systemctl(tmp_path)
    env_file = tmp_path / "live.env"
    env_file.write_text("TRADEAI_N8N_RELAY_LIVE_LANES=a b\n")
    for bad in ("config-write-20261018T103558", ""):
        r = subprocess.run(["bash", str(PACKET), "relay", "--apply"], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, SERVED=str(ROOT), LIVE_LANES_ENV=str(env_file), NOW_HM="1400",
                                    SYSTEMCTL_BIN=str(sc), PROC_ROOT=str(tmp_path / "proc"),
                                    GUARD_APPROVALS_DIR=str(tmp_path / "approvals"), TRADEAI_FABRIC_GRANT=bad,
                                    PY=sys.executable))
        assert r.returncode != 0 and "TRADEAI_FABRIC_GRANT" in r.stdout, bad
    assert env_file.read_text() == "TRADEAI_N8N_RELAY_LIVE_LANES=a b\n" and not calls.exists()


def test_packet_restarts_only_through_the_systemctl_hook():
    text = PACKET.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "systemctl --user" not in code.replace('"$SYSTEMCTL_BIN" --user', "")
