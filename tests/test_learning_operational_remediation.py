"""Fail-closed deployment/session gates and honest exit diagnostics, all isolated."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = module("remediation_release_preflight", "scripts/release_grant_preflight.py")
pins = module("remediation_worker_pins", "scripts/check_worker_pins.py")
SHA = "a" * 40


def runs():
    return [dict(id=i, workflow_id=i + 10, path=path, name=path, run_number=1,
                 head_sha=SHA, event="push", head_branch="main", status="completed",
                 conclusion="success", run_attempt=1)
            for i, path in enumerate(sorted(gate.REQUIRED_PUSH_WORKFLOWS), 1)]


@pytest.mark.parametrize("status,conclusion", [("queued", None), ("in_progress", None),
                         ("completed", "failure"), ("completed", "cancelled"),
                         ("completed", "skipped"), ("completed", "neutral"), (None, None)])
def test_promotion_requires_success(status, conclusion):
    rows = runs()
    rows[0].update(status=status, conclusion=conclusion)
    assert not gate.evaluate_push_checks(SHA, rows)["ok"]


@pytest.mark.parametrize("field,value", [("head_sha", "b" * 40), ("event", "pull_request"),
                         ("head_branch", "feature"), ("workflow_id", None)])
def test_wrong_identity_refused(field, value):
    rows = runs()
    rows[0][field] = value
    assert not gate.evaluate_push_checks(SHA, rows)["ok"]


def test_missing_and_pending_rerun_refused():
    rows = runs()
    assert gate.evaluate_push_checks(SHA, rows)["ok"]
    assert not gate.evaluate_push_checks(SHA, rows[1:])["ok"]
    rows.append(dict(rows[0], run_attempt=2, status="in_progress", conclusion=None))
    report = gate.evaluate_push_checks(SHA, rows)
    assert not report["ok"]
    assert report["checks"][0]["run_attempt"] == 2


@pytest.mark.parametrize("status,conclusion", [("in_progress", None), ("completed", "failure")])
def test_advisory_sharded_main_run_does_not_gate_promote(status, conclusion):
    """cio-full-suite-sharded.yml runs on push/main since 2026-10-09 (ci_signal) but stays advisory."""
    path = ".github/workflows/cio-full-suite-sharded.yml"
    assert path in gate.ADVISORY_PUSH_WORKFLOWS
    rows = runs()
    rows.append(dict(rows[0], id=99, workflow_id=199, path=path, name="cio-full-suite-sharded",
                     status=status, conclusion=conclusion))
    report = gate.evaluate_push_checks(SHA, rows)
    assert report["ok"], report
    assert report["advisory_not_gating"] == [path]
    assert path not in {c["path"] for c in report["checks"]}
    # Any other unexpected push workflow on the SHA still fails closed.
    rows[-1]["path"] = ".github/workflows/some-other-ci.yml"
    assert not gate.evaluate_push_checks(SHA, rows)["ok"]


def test_github_unavailable_and_pagination():
    def offline(*args, **kwargs):
        raise OSError("unavailable")
    assert "checks_unavailable:OSError" in gate.collect_push_checks(SHA, runner=offline)["errors"]

    def api(cmd, **kwargs):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/example/repository.git\n")
        assert "--paginate" in cmd
        assert "--slurp" not in cmd  # gh 2.46 on the deployment host has no such flag
        pages = [{"workflow_runs": runs()[:1]}, {"workflow_runs": runs()[1:]}]
        return subprocess.CompletedProcess(cmd, 0, "\n".join(json.dumps(p, indent=2) for p in pages))
    assert gate.collect_push_checks(SHA, runner=api)["ok"]


@pytest.mark.parametrize("response", ["", "[]", "{}", '{"workflow_runs": []} trailing',
                                      '{"workflow_runs": null}', '{"workflow_runs": []} []'])
def test_invalid_paginated_response_refuses_promotion(response):
    def api(cmd, **kwargs):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, "git@github.com:example/repository.git\n")
        return subprocess.CompletedProcess(cmd, 0, response)
    report = gate.collect_push_checks(SHA, runner=api)
    assert not report["ok"]
    assert any(error.startswith("checks_unavailable:") for error in report["errors"])


@pytest.mark.parametrize("session,rc,expected", [("regular", 0, "SKIPPED"), ("premarket", 0, "SKIPPED"),
                         ("afterhours", 0, "ALLOWED"), ("closed", 0, "ALLOWED"),
                         ("weekend", 0, "ALLOWED"), ("holiday", 0, "ALLOWED"),
                         ("unknown", 65, "FAILED")])
def test_session_gate_real_shell(tmp_path, session, rc, expected):
    # Run by absolute path from a neutral cwd, with no checkout .venv.
    interpreter = tmp_path / "runtime"
    interpreter.write_text("#!/bin/sh\nprintf '%s\\n' '" + session + "'\n")
    interpreter.chmod(0o700)
    marker = tmp_path / "must_not_run"
    result = subprocess.run(["bash", str(ROOT / "scripts/non_trading_hours_gate.sh"), "--dry-run",
                             "touch", str(marker)], cwd=tmp_path, env={**os.environ, "PY": str(interpreter)},
                            capture_output=True, text=True)
    assert result.returncode == rc, result.stderr
    assert "status=" + expected in result.stdout
    assert not marker.exists()


@pytest.mark.parametrize("exists,rc,reason", [(False, 69, "interpreter_missing"),
                                           (True, 70, "session_check_failed")])
def test_session_infrastructure_failure(tmp_path, exists, rc, reason):
    interpreter = tmp_path / "runtime"
    if exists:
        interpreter.write_text("#!/bin/sh\nexit 1\n")
        interpreter.chmod(0o700)
    result = subprocess.run(["bash", str(ROOT / "scripts/non_trading_hours_gate.sh"), "--dry-run", "true"],
                            cwd=tmp_path, env={**os.environ, "PY": str(interpreter)},
                            capture_output=True, text=True)
    assert result.returncode == rc
    assert reason in result.stdout


def test_exit_signal_and_oom_counters_do_not_invent_causation(tmp_path):
    group = tmp_path / "user.slice" / "example.service"
    group.mkdir(parents=True)
    (group / "memory.events").write_text("oom 2\noom_kill 1\n")

    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "Id=example.service\nResult=signal\nExecMainCode=2\n"
                       "ExecMainStatus=9\nNRestarts=3\nControlGroup=/user.slice/example.service\n")
    result = pins.service_observation("example.service", runner=runner, cgroup_root=tmp_path)
    assert result["exit_signal"] == "9"
    assert result["cgroup_memory_events"]["oom_kill"] == 1
    assert result["oom_causation"] == "NOT_ESTABLISHED"


def test_separate_daemon_chdir_is_observation_not_release_mismatch():
    row = {"name": "lab-postgres.service", "kind": "unit", "active": "active",
           "deployment_binding": "DECLARED_SEPARATE", "cwd_is_release_pin": False,
           "declared_path": "/lab", "path": "/lab/pgdata", "tree": "other"}
    report = pins.evaluate(served=SHA, rows=[row])
    assert report["ok"]
    assert row["verdict"] == "SEPARATE_WORKDIR_OBSERVED"
    # An explicit immutable deployment path still must match the process.
    row.update(cwd_is_release_pin=True)
    assert not pins.evaluate(served=SHA, rows=[row])["ok"]


def test_promotion_gate_precedes_activation_in_real_shell(tmp_path):
    # Source only the function definitions; replace host mutations with sentinels.
    source = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    source = source[:source.rindex('case "$MODE" in')]
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "BUILD_SHA").write_text(SHA)
    script = tmp_path / "harness.sh"
    script.write_text(source + '\nROOT="' + str(ROOT) + '"\n' + r'''
load_state() { :; }
current_release() { echo previous; }
release_grant_preflight() { :; }
conformance_gate() { :; }
write_deploy_receipt() { echo "RECEIPT:$*"; }
write_state() { echo MUTATION; }
activate_release() { echo MUTATION; }
VENV_PYTHON=/bin/false
cmd_promote "$1"
''')
    result = subprocess.run(["bash", str(script), str(candidate)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "post_merge_ci_refused" in result.stdout
    assert "MUTATION" not in result.stdout
