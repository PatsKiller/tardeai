"""§27.1 exact-argv SHADOW admission; broker primitives are recording tripwires.

Reuses the preserved F09 harness, not the obsolete B1 --dry-run guard. No broker
module, live state, .env, network, scheduler, gateway or ledger is contacted.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


def captured_plan():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(executor.RUN_ID_ENV, "fixture")
        patch.setenv(executor.RUN_ATTEMPT_ENV, "1")
        patch.setenv(executor.CODE_SHA_ENV, "")
        return harness.run_py_dry(shadow.WRAPPER, ["--step", "schwab_positions", "--plan"])


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


ROW_MUTATIONS = [
    ("scheduler", {"stage": "canary"}),
    ("scheduler", {"match": "scripts/alpaca_stop_manager.py"}),
    ("scheduler", {"wave": "W4"}),
    ("dispatch", {"mode": "live"}),
    ("dispatch", {"cron": []}),
    ("dispatch", {"tz": "UTC"}),
    (None, {"state": "PAUSED"}),
    (None, {"output_signal": {"kind": "mtime", "path": "x"}}),
    (None, {"command": "scripts/schwab_transport.py"}),
    (None, {"broker_read_step": "not_a_read_step"}),
    (None, {"lane_id": "f09-read-not-a-read-step"}),
]


@pytest.mark.parametrize("step", carve.READ_LANES, ids=lambda s: s.id)
@pytest.mark.parametrize("part,mutation", [(None, {})] + ROW_MUTATIONS)
def test_dispatcher_row_check_matches_full_admission_for_admitted_entries(step, part, mutation):
    """The carve-out-free dispatcher check gives full admission's row verdict for every admitted entry."""
    entry = entry_for(step)
    assert shadow.entry_problem(entry) is None
    row = row_for(entry)
    (row[part] if part else row).update(mutation)
    assert dispatch.broker_read_row_problem(row, entry) == shadow.row_problem(row, entry)
    assert (dispatch.broker_read_row_problem(row, entry) is None) == (not mutation)
    assert (dispatch.BROKER_READ_MARKER, dispatch.BROKER_READ_WRAPPER) == (shadow.MARKER, shadow.WRAPPER)
    assert (dispatch.broker_read_lane_id(step.id), dispatch.broker_read_receipt_path(step.id)) == (
        shadow.lane_id(step.id),
        shadow.receipt_path(step.id),
    )


def test_dispatcher_keeps_read_steps_out_of_every_lane_import_closure():
    """lane_dispatch is in every dispatched lane's closure; it must not reach the carve-out or read scripts."""
    import ast

    forbidden = {"n8n_broker_read_shadow", "n8n_broker_read_carveout", "broker_read_sync_policy"}
    names = set()
    for node in ast.walk(ast.parse((ROOT / "scripts/lib/lane_dispatch.py").read_text())):
        if isinstance(node, ast.Import):
            names |= {p for a in node.names for p in a.name.split(".")}
        elif isinstance(node, ast.ImportFrom):
            names |= set((node.module or "").split(".")) | {a.name for a in node.names}
    assert not names & forbidden, names & forbidden


def test_dispatcher_defers_entry_admission_to_the_executor(monkeypatch):
    """A carve-out refusal no longer reaches lane_dispatch; the executor refuses before any spawn."""
    entry = entry_for(carve.READ_LANES[0])
    row = row_for(entry)
    monkeypatch.setattr(dispatch, "load_run_allowlist_entries", lambda: {entry["lane_id"]: entry})
    monkeypatch.setattr(carve, "CARVEOUT_STATUS", "PROPOSED")
    assert dispatch.dispatch_eligible(row, cutover_policy={}) == (True, "eligible:broker_read_shadow_27_1")
    assert "carveout_not_active" in executor.validate_entry(entry)
    monkeypatch.setattr(dispatch, "load_run_allowlist_entries", lambda: {})
    assert dispatch.dispatch_eligible(row, cutover_policy={}) == (False, "read_not_allowlisted")


def test_executor_admits_reads_when_imported_as_a_package_module(tmp_path):
    """validate_entry/build_argv work as scripts.n8n_run_executor, with no bare `lib` on sys.path."""
    step = carve.READ_LANES[0]
    entry = {**entry_for(step), "lock": str(tmp_path / "read.lock")}
    probe = (
        "import json, sys\n"
        f"sys.path[:] = [{str(ROOT)!r}] + [p for p in sys.path if p and 'scripts' not in p]\n"
        "try:\n    import lib\nexcept ImportError:\n    pass\nelse:\n    raise SystemExit('bare lib importable')\n"
        "from scripts import n8n_run_executor as ex\n"
        "entry = json.loads(sys.argv[1])\n"
        "bad = {k: v for k, v in entry.items() if k != 'broker_read_step'}\n"
        "argv = ex.build_argv(entry, 'dry_run', env={}, state_root=sys.argv[2], code_root=sys.argv[3])\n"
        "print(json.dumps([ex.validate_entry(entry), ex.validate_entry(bad), argv[-4:] if argv else None,\n"
        "                  'lib.n8n_broker_read_shadow' in sys.modules]))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", probe, json.dumps(entry), str(tmp_path), str(ROOT)],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    valid, unmarked, plan, bare = json.loads(proc.stdout.splitlines()[-1])
    assert valid is None and unmarked == "unknown_read_step" and bare is False
    assert plan == [shadow.WRAPPER, "--step", step.id, "--plan"]


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
    code, out, err, calls, _ = captured_plan()

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
def test_each_lane_packet_has_matching_argv_contract_and_unchanged_host_lineage(path, monkeypatch):
    packet = json.loads(path.read_text())
    entry = packet["allowlist_entry"]
    row = packet["registry_row"]
    assert path.stem == entry["broker_read_step"] == packet["step_id"]
    # Repository lock convention (every config/n8n_run_allowlist.json lock is /tmp/<name>.lock); no host paths.
    assert entry["lock"].startswith("/tmp/") and "/home/" not in path.read_text()
    assert packet["source"]["harness_blob"] == "a8c9738b0c1ca36b0edfca42a6273a83c4f1cb9e"
    assert executor.validate_entry(entry) is None and shadow.row_problem(row, entry) is None
    monkeypatch.setattr(dispatch, "load_run_allowlist_entries", lambda: {entry["lane_id"]: entry})
    assert dispatch.validate_dispatch_block(row) == []
    assert lane_registry.validate_row(row) == []
    assert health.validate_contract(packet["health_contract"]) == []
    assert packet["health_contract"]["status"] == "DRAFT"
    assert packet["health_contract"]["review"]["status"] == "PENDING_OWNER_REVIEW"
    assert _check_expected_output(packet["health_contract"])["status"] == "pass"
    timing = packet["offline_timing"]
    assert timing["runs_considered"] == len(timing["samples_s"]) == 5
    assert max(timing["samples_s"]) < timing["slow_above_s"] < timing["timeout_s"]
    for key, relative in [
        ("wrapper_blob", shadow.WRAPPER),
        ("admission_blob", "scripts/lib/n8n_broker_read_shadow.py"),
    ]:
        body = (ROOT / relative).read_bytes()
        assert hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest() == timing[key]
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
    "field,value",
    [
        ("stdout_tail", ""),
        ("stderr_tail", ""),
        ("mode", "live"),
        ("lane_id", "other-lane"),
        ("exit_code", False),
        ("exit_code", 3),
        ("run_id", "another-run"),
        ("attempt", 2),
        ("code_sha", "a" * 40),
    ],
)
def test_empty_or_mismatched_evidence_is_not_a_success(field, value):
    code, out, err, calls, _ = captured_plan()
    receipt = {
        "lane_id": shadow.lane_id("schwab_positions"),
        "broker_read_step": "schwab_positions",
        "mode": "dry_run",
        "state": "RUN_DONE",
        "exit_code": 0,
        "run_id": "fixture",
        "attempt": 1,
        "code_sha": None,
        "stdout_tail": out,
        "stderr_tail": err,
    }
    assert code == 0 and calls == [] and shadow.receipt_problem(receipt) is None
    receipt[field] = value
    assert shadow.receipt_problem(receipt) is not None


@pytest.mark.parametrize(
    "mutation",
    ["future", "naive", "missing_clock", "reversed", "missing_run", "exit_one", "exit_false", "missing_exit"],
)
def test_invalid_final_receipt_never_advances_control_success(tmp_path, mutation):
    code, out, err, calls, _ = captured_plan()
    now = datetime.now(timezone.utc)
    receipt = {
        "lane_id": shadow.lane_id("schwab_positions"),
        "broker_read_step": "schwab_positions",
        "run_id": "fixture",
        "attempt": 1,
        "code_sha": None,
        "mode": "dry_run",
        "state": "RUN_DONE",
        "exit_code": code,
        "stdout_tail": out,
        "stderr_tail": err,
        "started_at": (now - timedelta(seconds=2)).isoformat(),
        "finished_at": (now - timedelta(seconds=1)).isoformat(),
    }
    assert calls == [] and shadow.final_receipt_problem(receipt, now=now) is None
    executor.write_receipt(receipt, state_root=tmp_path, write_last=False)
    path = tmp_path / shadow.receipt_path("schwab_positions")
    before = path.read_bytes()
    if mutation == "future":
        receipt["finished_at"] = (now + timedelta(hours=1)).isoformat()
    elif mutation == "naive":
        receipt["finished_at"] = now.replace(tzinfo=None).isoformat()
    elif mutation == "missing_clock":
        receipt.pop("finished_at")
    elif mutation == "reversed":
        receipt["started_at"] = now.isoformat()
    elif mutation == "missing_run":
        receipt.pop("run_id")
    elif mutation == "exit_one":
        receipt["exit_code"] = 1
    elif mutation == "exit_false":
        receipt["exit_code"] = False
    elif mutation == "missing_exit":
        receipt.pop("exit_code")
    assert shadow.final_receipt_problem(receipt, now=now) is not None
    # Generic RunReceipt storage still requires a run id. A missing-id receipt is
    # rejected before publishing any record, and cannot advance the success alias.
    if mutation == "missing_run":
        with pytest.raises(KeyError):
            executor.write_receipt(receipt, state_root=tmp_path, write_last=False)
    else:
        executor.write_receipt(receipt, state_root=tmp_path, write_last=False)
    assert path.read_bytes() == before


def test_shadow_plan_runs_through_current_symlink_layout(tmp_path):
    """§28.9: the substituted wrapper runs from a CURRENT symlink, not a flat repo."""
    from tests.support.real_release_layout import real_release_layout

    layout = real_release_layout(tmp_path, ROOT)
    for rel in (
        "scripts/n8n_broker_read_shadow.py",
        "scripts/lib/n8n_broker_read_shadow.py",
        "scripts/lib/n8n_broker_read_carveout.py",
        "scripts/lib/broker_read_sync_policy.py",
        "scripts/lib/lane_output.py",
    ):
        shutil.copy2(ROOT / rel, layout.release / rel)
    logs = layout.state / "logs"
    assert layout.current.is_symlink() and not layout.release.is_symlink()
    assert (layout.release / "logs").is_symlink()
    assert (logs.stat().st_mode & 0o777) == 0o775

    step = next(s for s in carve.READ_LANES if s.id == "schwab_positions")
    entry = {**entry_for(step), "lock": str(layout.locks / "read.lock")}
    argv = executor.build_argv(entry, "dry_run", env={}, state_root=tmp_path, code_root=layout.current)
    assert argv is not None
    assert argv[-4:] == [shadow.WRAPPER, "--step", "schwab_positions", "--plan"]
    assert step.script not in argv and "--dry-run" not in argv
    assert executor.build_argv(entry, "live", env={}, state_root=tmp_path, code_root=layout.current) is None
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "TRADEAI_RUN_ID": "layout-fixture",
        "TRADEAI_RUN_ATTEMPT": "1",
        "TRADEAI_CODE_SHA": "e37fd36a6e2025482a3dbb7b91a2bcc9fe09e994",
    }
    proc = subprocess.run(argv, cwd=layout.current, env=env, text=True, capture_output=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    assert "N8nBrokerReadShadowPlan@v1" in proc.stdout
    assert '"execution_available": false' in proc.stdout
    assert "schwab_position_sync" in proc.stdout
    assert list(logs.iterdir()) == []
