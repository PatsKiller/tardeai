"""Consolidation C3 (lane disposition 2026-10-15): WS2 family F36, the health/audit plane, as one stage runner.

COVERS = ["config/pipelines/health_audit.json", "scripts/pipelines/run_health_audit_pipeline.sh",
          "docs/ops/packets/consolidation-health-audit-c3-20261015/flip_packet.py"]

F36 is the largest WS2 family without a manifest (premarket F11 and after-close F12 have theirs). Its 22 live crontab
lines (crontab -l 2026-10-15) are partitioned exactly: 4 weekday-morning single-slot checks become stage `morning`
(VERBATIM commands, own locks/logs, the env names their own lines had), 11 are deferred (multi-slot, or already a
fabric lane) and 7 excluded (STAY_HOST). The runner is NEVER_SCHEDULED; the flip packet comments the 4 lines and
adds the one runner line in one act, and rolls back byte-exactly.
Hermetic: repo files, a sandboxed runner copy and tmp_path; a fake `crontab` command. Never the live crontab.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "pipelines"))
import pipeline_manifest as pm  # noqa: E402

from tests.pipeline_runner_fixtures import runner_env, sandbox_runner  # noqa: E402

MANIFEST = ROOT / "config" / "pipelines" / "health_audit.json"
RUNNER = ROOT / "scripts" / "pipelines" / "run_health_audit_pipeline.sh"
PKT = ROOT / "docs" / "ops" / "packets" / "consolidation-health-audit-c3-20261015"
SNAP_PATH = ROOT / "docs/implementation/n8n-maturity/data/disposition_20261015/crontab_20261015.txt"
SNAP = SNAP_PATH.read_text(encoding="utf-8").splitlines()
#: The F36 crontab lines of LANE_DISPOSITION_20261015.csv (family_id F36, source crontab).
F36_LINES = {
    170,
    177,
    204,
    210,
    224,
    339,
    391,
    397,
    402,
    503,
    578,
    619,
    708,
    759,
    876,
    971,
    976,
    982,
    1005,
    1007,
    1060,
    1063,
}
STEP_LINES = {204, 177, 210, 224}


def _load_flip():
    spec = importlib.util.spec_from_file_location("flip_packet_c3", PKT / "flip_packet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FP = _load_flip()


def test_manifest_is_valid_verbatim_and_weekday_only():
    m = pm.load(MANIFEST)
    assert pm.validate(m) == [] and m["pipeline"] == "health_audit" and list(m["stages"]) == ["morning"]
    stage = m["stages"]["morning"]
    assert stage["proposed_schedule"] == "30 7 * * 1-5" and "parallel" not in stage  # serial
    assert [s["id"] for s in stage["steps"]] == [
        "alert_missing_conditions",
        "write_state_freshness_history",
        "portfolio_level_qa",
        "classifier_health_check",
    ]
    for st in stage["steps"]:
        line = SNAP[st["cron_line"] - 1]
        assert st["cron_line_verbatim"] == line and st["command"] in line and st["inv_id"] == f"cron:L{st['cron_line']}"
        assert line.split(None, 5)[:5] == st["cron_schedule"].split() and st["cron_schedule"].endswith("* * 1-5")
        assert st["dow"] == [1, 2, 3, 4, 5] and st["continue_on_error"] is True and "verified" in st["measured"]
        assert pm.timeout_seconds(st["timeout"]) == 600
        assert not any(tok in st["command"] for tok in pm.FORBIDDEN_COMMAND_TOKENS)
        assert not any(w in st["command"] for w in pm.LLM_WRAPPERS)
        env = st["env"]
        assert env["inherit"] == "cron" and {"PROJ", "PY"} <= set(env["crontab_vars"]) and not env["sources"]


def test_every_f36_line_is_a_step_deferred_or_excluded_exactly_once():
    m = pm.load(MANIFEST)
    steps = [s["cron_line"] for s in m["stages"]["morning"]["steps"]]
    deferred = [e["cron_line"] for e in m["deferred"]]
    excluded = [e["cron_line"] for e in m["excluded"]]
    allx = steps + deferred + excluded
    assert len(allx) == len(set(allx)) == 22 and set(allx) == F36_LINES and set(steps) == STEP_LINES
    for e in m["deferred"] + m["excluded"]:
        assert e["reason"] and e["category"] in ("DEFERRED_MULTI_SLOT_OR_FABRIC", "STAY_HOST") and e["lane_id"]
        assert SNAP[e["cron_line"] - 1].split(None, 5)[:5] == e["cron_schedule"].split()


def test_runner_is_never_scheduled_and_parses():
    assert not any("run_health_audit_pipeline" in ln for ln in SNAP)
    r = subprocess.run(["bash", "-n", str(RUNNER)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_runner_dry_run_prints_the_plan_and_executes_nothing(tmp_path):
    env = runner_env(tmp_path)
    env["PIPELINE_TODAY_DOW"] = "3"  # a Wednesday: every dow=1-5 step is in the plan
    runner = sandbox_runner(tmp_path, RUNNER)
    r = subprocess.run(
        ["bash", str(runner), "--project-root", str(tmp_path), "--manifest", str(MANIFEST), "--stage", "morning"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("[DRY_RUN] would run") == 4
    assert "status=ok" not in r.stdout and "status=failed" not in r.stdout
    s = json.loads((tmp_path / "data/runtime/pipeline_health_audit_morning_last.json").read_text())
    assert s["dry_run"] is True and s["executed_any"] is False and len(s["steps"]) == 4


def test_runner_on_a_weekend_skips_every_step(tmp_path):
    env = runner_env(tmp_path)
    env["PIPELINE_TODAY_DOW"] = "0"
    runner = sandbox_runner(tmp_path, RUNNER)
    r = subprocess.run(
        ["bash", str(runner), "--project-root", str(tmp_path), "--manifest", str(MANIFEST), "--stage", "morning"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[DRY_RUN] would run" not in r.stdout


# ── flip packet ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_flip_build_verify_rollback_exact():
    text = SNAP_PATH.read_text(encoding="utf-8")
    cand, problems = FP.build(text, "2026-10-15")
    assert problems == []
    before, after = text.splitlines(), cand.splitlines()
    assert len(after) == len(before) + 1 and after[-1] == FP.RUNNER_LINE
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    assert sorted(i + 1 for i in changed) == sorted(STEP_LINES)
    assert FP.active_count(after) == 394 - 4 + 1
    assert FP.verify(cand, expect_live=False) == []
    restored, problems = FP.rollback(cand)
    assert problems == [] and restored == text
    _c, problems = FP.build(cand, "2026-10-16")
    assert problems  # refuses a table that is already flipped


def test_runner_line_inherits_the_steps_env():
    """The runner line is appended below every NAME=value line any step's env block names (vixie cron parse-time env)."""
    names = {n for s in pm.load(MANIFEST)["stages"]["morning"]["steps"] for n in s["env"]["crontab_vars"]}
    last_assign = max(
        i
        for i, ln in enumerate(SNAP)
        if ln.split("=", 1)[0].strip() in names
        and "=" in ln
        and not ln.lstrip().startswith("#")
        and not ln[:1].isdigit()
        and not ln.startswith("*")
    )
    assert last_assign < len(SNAP)  # the runner goes to the end, after it


@pytest.fixture()
def fake_crontab(tmp_path):
    table = tmp_path / "table"
    table.write_bytes(SNAP_PATH.read_bytes())
    exe = tmp_path / "fakecron"
    exe.write_text(
        f'#!/bin/bash\nT="{table}"\nif [ "$1" = "-l" ]; then cat "$T"; '
        'elif [ "$1" = "-" ]; then cat > "$T"; else exit 9; fi\n'
    )
    exe.chmod(0o755)
    return table, exe


def _sh(script, args, env, tmp_path):
    e = dict(os.environ, **env, BACKUP_DIR=str(tmp_path / "bk"))
    return subprocess.run(["bash", str(PKT / script), *args], capture_output=True, text=True, env=e, timeout=60)


def test_install_and_rollback_round_trip_on_a_fake_crontab(tmp_path, fake_crontab):
    table, exe = fake_crontab
    dry = _sh("install.sh", [], {"CRONTAB_CMD": str(exe), "WORK_DIR": str(tmp_path / "w0")}, tmp_path)
    assert dry.returncode == 0 and "DRY RUN" in dry.stdout and table.read_bytes() == SNAP_PATH.read_bytes()
    inst = _sh(
        "install.sh",
        ["--apply"],
        {"CRONTAB_CMD": str(exe), "WORK_DIR": str(tmp_path / "w1"), "CRON_GRANT_ID": "rehearsal"},
        tmp_path,
    )
    assert inst.returncode == 0, inst.stdout + inst.stderr
    assert "VERIFY OK" in inst.stdout and table.read_text().splitlines()[-1] == FP.RUNNER_LINE
    rb = _sh(
        "rollback.sh",
        ["--apply"],
        {"CRONTAB_CMD": str(exe), "WORK_DIR": str(tmp_path / "w2"), "CRON_GRANT_ID": "rehearsal"},
        tmp_path,
    )
    assert rb.returncode == 0, rb.stdout + rb.stderr
    assert table.read_bytes() == SNAP_PATH.read_bytes()
