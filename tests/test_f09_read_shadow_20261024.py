"""§27.1 exact-argv SHADOW admission; broker primitives are recording tripwires.

Reuses the preserved F09 harness, not the obsolete B1 --dry-run guard. No broker
module, live state, .env, network, scheduler, gateway or ledger is contacted.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]

import n8n_run_executor as executor  # noqa: E402
from lib import lane_dispatch as dispatch  # noqa: E402
from lib import lane_output  # noqa: E402,F401 -- preload pure dependency before harness
from lib import n8n_broker_read_carveout as carve  # noqa: E402
from lib import n8n_broker_read_shadow as shadow  # noqa: E402
from scripts.check_n8n_workflow_framework import _check_expected_output  # noqa: E402
from scripts.lib import n8n_health_contracts as health  # noqa: E402
from scripts.lib import lane_registry  # noqa: E402
from tests.support import f09_onboarding as harness  # noqa: E402

PACKETS = sorted((ROOT / "config/proposals/f09_read_lanes").glob("*.json"))


def entry_for(step):
    return {
        "lane_id": shadow.lane_id(step.id),
        "broker_read_step": step.id,
        "command": ["$PY", step.script, *step.apply_argv],
        "dry_run_arg": [],
        "live_arg": None,
        "market_gate": False,
        "lock": "/fixture/read.lock",
        "lock_kind": "flock",
        "timeout_s": 60,
        "output_signal": shadow.receipt_path(step.id),
        "env_names": [],
        "env_allowlist_mode": "enforce",
    }


def row_for(entry):
    step = shadow.step_for(entry)
    return {
        "lane_id": entry["lane_id"],
        "broker_read_step": step.id,
        "state": "ACTIVE",
        "scheduler": {
            "kind": "n8n",
            "expression": "dispatcher",
            "stage": "shadow",
            "wave": "W5",
            "cadence": "*/15 * * * *",
            "match": f"{shadow.WRAPPER} --step {step.id} --plan",
        },
        "dispatch": {
            "mode": "dry_run",
            "class": "pipeline",
            "retry_policy": "none",
            "priority": 2,
            "cron": ["*/15 * * * *"],
            "wave": "W5",
            "tz": "America/New_York",
        },
        "output_signal": {"kind": "json_key", "path": shadow.receipt_path(step.id), "key": "finished_at"},
    }


@pytest.mark.parametrize("step", carve.READ_LANES, ids=lambda s: s.id)
def test_every_closed_read_has_exact_admission_and_only_an_offline_executor_plan(step, tmp_path):
    entry = entry_for(step)
    assert executor.validate_entry(entry) is None
    argv = executor.build_argv(entry, "dry_run", env={}, state_root=tmp_path, code_root=ROOT)
    assert argv[-4:] == [shadow.WRAPPER, "--step", step.id, "--plan"]
    assert step.script not in argv and "--dry-run" not in argv
    assert "/fixture/read.lock.dryrun" in argv and "/fixture/read.lock" not in argv
    assert executor.build_argv(entry, "live", env={}, state_root=tmp_path, code_root=ROOT) is None


@pytest.mark.parametrize("step", carve.READ_LANES, ids=lambda s: s.id)
def test_offline_plan_uses_preserved_no_broker_no_write_recorders(step):
    code, out, err, calls, new = harness.run_py_dry(shadow.WRAPPER, ["--step", step.id, "--plan"])
    assert code == 0 and calls == []
    assert new <= harness.ALLOWED_NEW_MODULES
    assert f"DRY-RUN {shadow.lane_id(step.id)}:" in out
    harness.assert_lane_output(shadow.lane_id(step.id), err, shadow.EMPTY_REASON)
    plan = json.loads(out.splitlines()[1])
    assert plan["command"] == ["$PY", step.script, *step.apply_argv]
    assert plan["execution_available"] is False and plan["stage"] == "shadow"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--step", "schwab_positions"],
        ["--step", "schwab_positions", "--live"],
        ["--step", "schwab_positions", "--plan", "--apply"],
        ["--step", "stop_manager", "--plan"],
    ],
)
def test_wrapper_refuses_every_non_plan_without_touching_broker_state(args):
    code, out, err, calls, _ = harness.run_py_dry(shadow.WRAPPER, args)
    assert code in (64, 65) and calls == [] and not out and "REFUSED:" in err


@pytest.mark.parametrize(
    "mutation",
    [
        {"broker_read_step": "stop_manager"},
        {"lane_id": "alpaca-stop-manager"},
        {"command": ["$PY", "scripts/positions_sync.py", "--apply", "--dry-run"]},
        {"command": ["bash", "scripts/positions_sync.py", "--apply"]},
        {"dry_run_arg": ["--dry-run"]},
        {"live_arg": []},
        {"market_gate": True},
        {"env_names": ["SCHWAB_TOKEN"]},
        {"env_allowlist_mode": "report"},
        {"retry": {"max": 1}},
        {"output_receipt": "v2"},
    ],
)
def test_malformed_allowlist_refuses_before_spawn(mutation, tmp_path):
    entry = {**entry_for(carve.READ_LANES[0]), **mutation}
    assert executor.validate_entry(entry) is not None
    assert executor.build_argv(entry, "dry_run", env={}, state_root=tmp_path, code_root=ROOT) is None


def test_omitted_marker_cannot_fall_back_to_a_real_read(tmp_path):
    entry = entry_for(carve.READ_LANES[0])
    del entry["broker_read_step"]
    assert executor.validate_entry(entry) == "unknown_read_step"
    assert executor.build_argv(entry, "dry_run", env={}, state_root=tmp_path, code_root=ROOT) is None


def test_proposed_policy_and_dirty_audit_refuse(monkeypatch):
    entry = entry_for(carve.READ_LANES[0])
    monkeypatch.setattr(carve, "CARVEOUT_STATUS", "PROPOSED")
    assert "carveout_not_active" in shadow.entry_problem(entry)
    monkeypatch.setattr(carve, "CARVEOUT_STATUS", "ACTIVE")
    monkeypatch.setattr(carve, "default_audit", lambda step: {"ok": False, "findings": ["bad"]})
    assert shadow.entry_problem(entry).startswith("read_admission:")


@pytest.mark.parametrize(
    "part,mutation",
    [
        ("scheduler", {"stage": "canary"}),
        ("scheduler", {"command_text": "place_order"}),
        ("scheduler", {"match": "scripts/alpaca_stop_manager.py"}),
        ("dispatch", {"mode": "live"}),
        ("dispatch", {"class": "ingest"}),
        ("dispatch", {"retry_policy": "default"}),
        ("dispatch", {"triggers": []}),
        (None, {"exec_start": "scripts/schwab_transport.py place_order"}),
        (None, {"watch": {"stay_behind": True}}),
        (None, {"broker_read_step": "snaptrade"}),
    ],
)
def test_dispatcher_never_lifts_other_commands_or_stages(monkeypatch, part, mutation):
    entry = entry_for(carve.READ_LANES[0])
    row = row_for(entry)
    monkeypatch.setattr(dispatch, "load_run_allowlist_entries", lambda: {entry["lane_id"]: entry})
    assert dispatch.dispatch_eligible(row, cutover_policy={}) == (True, "eligible:broker_read_shadow_27_1")
    (row[part] if part else row).update(mutation)
    assert dispatch.dispatch_eligible(row, cutover_policy={})[0] is False


def test_operator_hold_still_wins_and_unmarked_broker_lane_stays_refused(monkeypatch):
    entry = entry_for(carve.READ_LANES[0])
    row = row_for(entry)
    monkeypatch.setattr(dispatch, "load_run_allowlist_entries", lambda: {entry["lane_id"]: entry})
    monkeypatch.setattr(dispatch, "operator_hold", lambda row, policy: "operator_paused")
    assert dispatch.dispatch_eligible(row, cutover_policy={}) == (False, "operator_hold:operator_paused")
    monkeypatch.setattr(dispatch, "operator_hold", lambda row, policy: None)
    del row["broker_read_step"]
    assert dispatch.dispatch_eligible(row, cutover_policy={})[0] is False


def test_executor_capture_and_live_refusal_have_no_underlying_read(tmp_path):
    entry = entry_for(carve.READ_LANES[0])
    seen = []
    code, out, err, calls, _ = harness.run_py_dry(shadow.WRAPPER, ["--step", "schwab_positions", "--plan"])

    def runner(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, code, out, err)

    row = {"run_id": "fixture", "lane_id": entry["lane_id"], "mode": "dry_run"}
    receipt = executor.execute(row, entry, env={}, state_root=tmp_path, code_root=tmp_path, runner=runner)
    assert receipt["state"] == "RUN_DONE" and receipt["mode"] == "dry_run" and calls == []
    assert receipt["output_signal_mtime_after"] == receipt["output_signal_mtime_before"]
    harness.assert_lane_output(entry["lane_id"], receipt["stderr_tail"], shadow.EMPTY_REASON)
    executor.write_receipt(receipt, state_root=tmp_path, write_last=False)
    success_path = tmp_path / shadow.receipt_path("schwab_positions")
    assert json.loads(success_path.read_text())["finished_at"] == receipt["finished_at"]
    previous = success_path.read_bytes()

    def empty_runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    empty = executor.execute(
        {**row, "run_id": "empty"}, entry, env={}, state_root=tmp_path, code_root=tmp_path, runner=empty_runner
    )
    assert empty["state"] == "RUN_FAILED" and empty["reason"] == "read_plan_evidence_missing"
    executor.write_receipt(empty, state_root=tmp_path, write_last=False)
    assert success_path.read_bytes() == previous
    receipt = executor.execute(
        {**row, "mode": "live"}, entry, env={}, state_root=tmp_path, code_root=tmp_path, runner=runner
    )
    assert receipt["state"] == "RUN_REFUSED" and len(seen) == 1


@pytest.mark.parametrize("path", PACKETS, ids=lambda p: p.stem)
def test_each_reviewed_packet_has_matching_argv_contract_and_unchanged_host_lineage(path, monkeypatch):
    packet = json.loads(path.read_text())
    entry = packet["allowlist_entry"]
    row = packet["registry_row"]
    assert path.stem == entry["broker_read_step"] == packet["step_id"]
    assert packet["source"]["harness_blob"] == "a8c9738b0c1ca36b0edfca42a6273a83c4f1cb9e"
    assert executor.validate_entry(entry) is None and shadow.row_problem(row, entry) is None
    monkeypatch.setattr(dispatch, "load_run_allowlist_entries", lambda: {entry["lane_id"]: entry})
    assert dispatch.validate_dispatch_block(row) == []
    assert lane_registry.validate_row(row) == []
    assert health.validate_contract(packet["health_contract"]) == []
    assert _check_expected_output(packet["health_contract"])["status"] == "pass"
    host = next(
        r
        for r in json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]
        if r["lane_id"] == packet["source"]["host_lane_id"]
    )
    digest = hashlib.sha256(json.dumps(host, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == packet["source"]["host_row_sha256"]
    assert row["lane_id"] != host["lane_id"] and entry["live_arg"] is None
    assert shadow.WRAPPER in row["scheduler"]["match"]
    assert row["scheduler"]["match"] not in json.dumps(host["scheduler"])


def test_positions_apply_and_freshness_are_distinct_closed_lanes():
    apply = next(s for s in carve.READ_LANES if s.id == "positions_store")
    fresh = next(s for s in carve.READ_LANES if s.id == "positions_fresh")
    assert apply.script == fresh.script and shadow.lane_id(apply.id) != shadow.lane_id(fresh.id)
    assert entry_for(apply)["command"][-1] == "--apply"
    assert entry_for(fresh)["command"][-1] == "--check-fresh"


@pytest.mark.parametrize(
    "field,value", [("stdout_tail", ""), ("stderr_tail", ""), ("mode", "live"), ("lane_id", "other-lane")]
)
def test_empty_or_mismatched_evidence_is_not_a_success(field, value):
    code, out, err, calls, _ = harness.run_py_dry(shadow.WRAPPER, ["--step", "schwab_positions", "--plan"])
    receipt = {
        "lane_id": shadow.lane_id("schwab_positions"),
        "broker_read_step": "schwab_positions",
        "mode": "dry_run",
        "state": "RUN_DONE",
        "stdout_tail": out,
        "stderr_tail": err,
    }
    assert code == 0 and calls == [] and shadow.receipt_problem(receipt) is None
    receipt[field] = value
    assert shadow.receipt_problem(receipt) is not None
