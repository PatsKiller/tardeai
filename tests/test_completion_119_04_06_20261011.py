"""Owned 04–06 remediation: CLI isolation and truthful compound/failure receipts.

Everything executed here uses temporary state and fake business children.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYTHON_CASES = [
    ("hermes_coordinator", "hermes-coordinator", []),
    ("hermes_backlog_health_check", "hermes-backlog-health-check", []),
    ("hermes_source_curation", "hermes-source-curation", []),
    ("hermes_analyst_coverage", "hermes-analyst-coverage", ["--apply", "--limit", "8"]),
    ("generate_analyst_daily_digest", "generate-analyst-daily-digest", ["--format", "json", "--days", "2"]),
    ("generate_analyst_reports_autonomous", "generate-analyst-reports-autonomous-weekly", ["--mode", "weekly"]),
    ("generate_analyst_reports_autonomous", "generate-analyst-reports-autonomous-full", ["--mode", "full"]),
    ("run_dormant_lane_consumers", "dormant-lane-consumers", ["--json"]),
    ("wire_advisory_lessons", "wire-advisory-lessons", []),
    ("hermes_autonomous_librarian_backlog_loop", "hermes-librarian-backlog-loop", ["--apply", "--max-rows", "3"]),
    ("run_goal_pilot_material_change", "goal-pilot-material-change", []),
    ("cio_reactive_cycle", "cio-wake-turn-effects", ["--once", "--max-wakes", "2"]),
    ("eod_consolidated_close_sync", "eod-consolidated-close-sync", ["--apply", "--json"]),
    ("gir_projector", "gir-projector", ["--incremental", "--apply"]),
    ("watch_decision_scheduler", "tradeai-watch-decision-scheduler", ["--run"]),
    ("hermes_deep_research_local", "hermes-deep-research-local", ["--apply", "--max-rows", "3", "--model", "chatgpt"]),
    ("enqueue_holdings_agent_opinions", "holdings-agent-enqueue", ["--apply"]),
    ("aec_command_center_cycle", "tradeai-aec-command-center-cycle", []),
]
SHELL_CASES = [
    ("scripts/agent_intelligence_cron.sh", ["daily"]),
    ("scripts/agent_intelligence_cron.sh", ["deep"]),
    ("scripts/agent_intelligence_cron.sh", ["intraday"]),
    ("linux_launchers/run_inference_cycle.sh", ["cron_preopen"]),
    ("linux_launchers/run_inference_cycle.sh", ["cron_midday"]),
    ("linux_launchers/run_inference_cycle.sh", ["cron_postclose"]),
    ("scripts/run_research_intelligence_overnight.sh", ["--phase", "full"]),
    ("scripts/run_research_intelligence_overnight.sh", ["--phase=archive"]),
    ("scripts/run_free_first_circulation.sh", []),
    ("linux_launchers/run_provider_cost_daily.sh", []),
]


def load(name):
    spec = importlib.util.spec_from_file_location("completion04_06_" + name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    for name in ("TRADEAI_STATE_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT", "TRADEAI_WAKE_STATE_ROOT"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.setenv("M2_SKIP_DOCKER", "1")
    monkeypatch.setenv("TRADE_AI_CI", "1")
    return tmp_path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("name,lane,argv", PYTHON_CASES)
def test_offline_main_cannot_reach_legacy_work(scratch, monkeypatch, capsys, name, lane, argv):
    module = load(name)
    monkeypatch.setattr(module, "_execute", lambda *a: pytest.fail("preview reached legacy work"))
    before = snapshot(scratch)
    assert module.main([*argv, "--dry-run"]) == 0
    assert snapshot(scratch) == before
    assert f"DRY-RUN {lane}: would" in capsys.readouterr().out


@pytest.mark.parametrize("name,lane,argv", PYTHON_CASES)
def test_preview_guard_mutation_reaches_fake_business_boundary(scratch, monkeypatch, name, lane, argv):
    module = load(name)
    attempts = []

    def work(*a):
        attempts.append(True)
        raise RuntimeError("synthetic business boundary")

    monkeypatch.setattr(module, "_execute", work)
    tree = ast.parse((ROOT / "scripts" / (name + ".py")).read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    fn.body = [n for n in fn.body if not (isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
                                         and n.test.attr == "dry_run")]
    namespace = dict(vars(module))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "fixture-remove-preview-return", "exec"), namespace)
    with pytest.raises(RuntimeError, match="synthetic business boundary"):
        namespace["main"]([*argv, "--dry-run"])
    assert attempts == [True]


@pytest.mark.parametrize("name,lane,argv", PYTHON_CASES)
@pytest.mark.parametrize("bad", ["--dry", "--unknown", "--dry-rn"])
def test_unknown_flag_refuses_before_work(scratch, monkeypatch, name, lane, argv, bad):
    module = load(name)
    monkeypatch.setattr(module, "_execute", lambda *a: pytest.fail("usage reached legacy work"))
    with pytest.raises(SystemExit) as exc:
        module.main([*argv, bad])
    assert exc.value.code == 2 and snapshot(scratch) == {}


@pytest.mark.parametrize("name,lane,argv", PYTHON_CASES)
def test_fake_work_retains_argv_and_failed_receipt_keeps_previous_success(scratch, monkeypatch, name, lane, argv):
    module = load(name)
    observed = []

    def work(*a):
        observed.append(list(sys.argv[1:]))
        return 0

    monkeypatch.setattr(module, "_execute", work)
    assert module.main(argv) == 0 and observed == [argv]
    path = scratch / "data/runtime" / (lane + "_last.json")
    first = json.loads(path.read_text())
    assert first["schema"] == "LaneRunReceipt@v1" and first["status"] == "ok"
    monkeypatch.setattr(module, "_execute", lambda *a: 7)
    assert module.main(argv) == 7
    failed = json.loads(path.read_text())
    assert failed["status"] == "failed" and failed["exit"] == 7 and failed["ok_at"] == first["ok_at"]


@pytest.mark.parametrize("name,lane,argv", PYTHON_CASES)
def test_actual_cli_offline_from_neutral_directory(scratch, name, lane, argv):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    before = snapshot(scratch)
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / (name + ".py")), *argv, "--dry-run"],
                            cwd=scratch, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"DRY-RUN {lane}: would" in result.stdout and snapshot(scratch) == before


@pytest.mark.parametrize("name,argv", SHELL_CASES)
def test_shell_preview_and_usage_do_not_resolve_interpreter_or_touch_project(scratch, name, argv):
    missing = str(scratch / "missing-project")
    env = dict(os.environ, PROJECT_DIR=missing, TRADEAI_ROOT=missing, TRADEAI_CURRENT=missing,
               TRADEAI_PYTHON=str(scratch / "missing-python"), TRADEAI_VENV_PYTHON=str(scratch / "missing-python"))
    before = snapshot(scratch)
    result = subprocess.run(["bash", str(ROOT / name), *argv, "--dry-run"], cwd=scratch,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and "DRY-RUN" in result.stdout, result.stderr
    assert snapshot(scratch) == before
    result = subprocess.run(["bash", str(ROOT / name), *argv, "--unknown"], cwd=scratch,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and snapshot(scratch) == before


def test_compound_lock_skip_cannot_advance_ok_at(scratch):
    module = load("completion_compound_receipt")
    assert module.main(["--lane", "fixture-compound", "--step", "one", "--exit", "0"]) == 0
    p = scratch / "data/runtime/fixture-compound--step-one_last.json"
    previous = json.loads(p.read_text())["ok_at"]
    assert module.main(["--lane", "fixture-compound", "--step", "one", "--exit", "75"]) == 0
    skipped = json.loads(p.read_text())
    assert skipped["status"] == "failed" and skipped["ok_at"] == previous
    assert skipped["summary"]["status"] == "RUN_SKIPPED_LOCK"


def test_deep_research_cost_deferral_preserves_success(scratch, monkeypatch):
    module = load("hermes_deep_research_local")
    monkeypatch.setattr(module, "_execute", lambda: 0)
    assert module.main([]) == 0
    path = scratch / "data/runtime/hermes-deep-research-local_last.json"
    successful = json.loads(path.read_text())["ok_at"]

    def defer():
        module._LAST_RUN.update(completed=False, status="EXPECTED_SILENT",
                                reason="deepseek_cost_window")
        return 0

    monkeypatch.setattr(module, "_execute", defer)
    assert module.main([]) == 0
    receipt = json.loads(path.read_text())
    assert receipt["ok_at"] == successful
    assert receipt["summary"]["status"] == "EXPECTED_SILENT"


def test_provider_cost_child_failure_attempts_both_steps_and_fails_parent(scratch):
    """The prior launcher masked both child failures with `|| true`."""
    project = scratch / "project"
    project.mkdir()
    helper = project / "scripts"
    helper.mkdir()
    (helper / "completion_compound_receipt.py").write_bytes(
        (ROOT / "scripts/completion_compound_receipt.py").read_bytes())
    # The real helper needs the receipt library; business children remain fake.
    (project / "scripts/__init__.py").write_text("")
    (helper / "lib").symlink_to(ROOT / "scripts/lib", target_is_directory=True)
    fake_python = scratch / "fake-python"
    fake_python.write_text(
        '#!/usr/bin/env bash\n'
        'if [[ "$1" == */completion_compound_receipt.py ]]; then exec "$REAL_PYTHON" "$@"; fi\n'
        'printf "%s\\n" "$1" >> "$CHILD_CALLS"\n'
        'if [[ "$1" == */provider_cost_reconcile.py ]]; then exit 13; fi\n'
        'exit 0\n')
    fake_python.chmod(0o755)
    calls = scratch / "children.txt"
    env = dict(os.environ, TRADEAI_ROOT=str(project), TRADEAI_PYTHON=str(fake_python),
               REAL_PYTHON=sys.executable, CHILD_CALLS=str(calls))
    result = subprocess.run(["bash", str(ROOT / "linux_launchers/run_provider_cost_daily.sh")],
                            cwd=scratch, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stdout + result.stderr
    assert calls.read_text().splitlines() == [
        str(project / "scripts/provider_cost_reconcile.py"),
        str(project / "scripts/provider_cost_export.py")]
    receipt = json.loads((scratch / "data/runtime/provider-cost-reconcile_last.json").read_text())
    assert receipt["status"] == "failed" and receipt["ok_at"] is None


def test_pilot_unavailable_result_does_not_write_success(scratch, monkeypatch):
    import types
    module = load("run_goal_pilot_material_change")
    monkeypatch.setitem(sys.modules, "scripts.lib.canonical_store_registry", types.SimpleNamespace(
        production_state_root=lambda: scratch))
    from scripts import lib
    monkeypatch.setattr(lib, "goal_pilot_material_change", types.SimpleNamespace(
        run_shadow=lambda: {"status": "unavailable", "ok": False}), raising=False)
    assert module.main([]) == 1
    row = json.loads((scratch / "data/cio/goal_pilot_material_change.jsonl").read_text().splitlines()[-1])
    assert row["ok"] is False
    assert json.loads((scratch / "data/runtime/goal-pilot-material-change_last.json").read_text())["status"] == "failed"


def test_daily_digest_preview_does_not_call_chart_or_json_builder(scratch, monkeypatch):
    module = load("generate_analyst_daily_digest")
    monkeypatch.setattr(module, "_execute", lambda: pytest.fail("old dry-run writes reports before checking flag"))
    assert module.main(["--format", "all", "--dry-run"]) == 0 and snapshot(scratch) == {}


def test_candidate_admissions_are_draft_source_only_and_never_operational():
    candidate = json.loads((ROOT / "docs/implementation/n8n-maturity/completion-119/candidates-04-06.json").read_text())
    assert candidate["operational_admission"] is False and candidate["runtime"] == "NOT_MEASURED"
    assert len(candidate["rows"]) == 55
    assert len({row["lane_id"] for row in candidate["rows"]}) == 55
    for row in candidate["rows"]:
        contract = row.get("health_contract_candidate")
        if contract:
            assert contract["status"] == "DRAFT" and not contract.get("reviewed_by")
        allow = row.get("allowlist_candidate")
        if allow:
            assert allow["live_arg"] is None
            assert not any(any(token in name.upper() for token in ("BROKER", "ALPACA", "SCHWAB", "MOOMOO"))
                           for name in allow["env_names"])


def test_coordinator_child_failure_isolated_but_parent_not_green(scratch, monkeypatch):
    import types
    module = load("hermes_coordinator")
    connection = types.SimpleNamespace(rollback=lambda: None, close=lambda: None)
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=lambda **k: connection))
    monkeypatch.setitem(sys.modules, "hermes_embedding_enqueue", types.SimpleNamespace(backfill_promoted=lambda *a, **k: 0))
    monkeypatch.setattr(module, "kill_switch_active", lambda: None)
    monkeypatch.setattr(module, "venv_python", lambda root: sys.executable)
    monkeypatch.setattr(module, "auto_promote", lambda c: 0)
    monkeypatch.setattr(module, "log_plan", lambda *a: None)
    calls = []

    def child(label, argv, timeout=600):
        calls.append(label)
        return {"agent": label, "ok": label != "backlog_drain", "exit": 9 if label == "backlog_drain" else 0}

    monkeypatch.setattr(module, "run_script", child)
    assert module.main([]) == 1
    assert "backlog_drain" in calls and "embedding_worker" in calls
    assert json.loads((scratch / "data/runtime/hermes-coordinator_last.json").read_text())["status"] == "failed"


def test_lesson_rollup_failure_preserved_in_parent_exit_and_receipt(scratch, monkeypatch):
    import types
    module = load("wire_advisory_lessons")
    monkeypatch.setattr(module, "_db", lambda *a, **k: [])
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=17, stdout="fixture failure"))
    assert module.main([]) == 17
    assert json.loads((scratch / "data/runtime/wire-advisory-lessons_last.json").read_text())["exit"] == 17
