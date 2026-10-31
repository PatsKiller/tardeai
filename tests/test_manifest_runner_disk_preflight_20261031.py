"""Manifest runner disk preflight, log fallback and receipt-failure paging (DSN-20261031-market-risk-engine-P0-T5).

2026-10-30 05:45 ET: the premarket runner died at `exec > >(tee -a $RUN_LOG)` with ENOSPC before its first step,
and nothing paged (RCA finding 7). Pins, hermetically (sandbox copy of the runner, a stub pager, tmp roots):
  * free space below config/pipelines/runner_disk_policy.json `min_free_mb` -> "[disk] LOW FREE SPACE", the
    pager is invoked once with pipeline/stage/reason low_disk, and the steps STILL run and leave a summary;
  * no policy file -> the preflight says so and skips (thresholds live in config, never in the script);
  * an unwritable run log -> "[log] cannot write", steps still run, summary written with log /dev/null;
  * an unwritable data/runtime -> "[summary] FAILED", pager invoked with reason summary_write_failed, exit 1;
  * pipeline_disk_alert.py sends ONE P1 dedupe-0 intent (producer manifest_runner) and exits 1 when refused.
"""

from __future__ import annotations

#: C1 firing coverage — test_pager_sends_one_p1_dedupe_zero_intent injects low disk and asserts the P1 reaches the
#: (stubbed) transport; the pager has one send_telegram site.
COVERS = ["scripts/pipelines/pipeline_disk_alert.py"]

import json
import os
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest
from tests.pipeline_runner_fixtures import runner_env, sandbox_runner

ROOT = Path(__file__).resolve().parents[1]
PIPELINES = ROOT / "scripts" / "pipelines"
RUNNER = PIPELINES / "run_after_close_pipeline.sh"
sys.path.insert(0, str(PIPELINES))
import pipeline_manifest as pm  # noqa: E402

STUB_PAGER = """#!/usr/bin/env python3
import json, os, sys
calls = os.environ["STUB_PAGER_LOG"]
with open(calls, "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
print("stub pager called")
"""


def _manifest(tmp_path: Path, name: str, stage: str = "test") -> Path:
    m = {
        "schema": pm.MANIFEST_SCHEMA,
        "pipeline": name,
        "stages": {stage: {"steps": [{"id": "ok_step", "cron_line": 1, "command": "true", "timeout": 10}]}},
    }
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def _policy(root: Path, min_free_mb: int) -> None:
    d = root / "config" / "pipelines"
    d.mkdir(parents=True, exist_ok=True)
    (d / "runner_disk_policy.json").write_text(
        json.dumps({"schema": "RunnerDiskPolicy@v1", "min_free_mb": min_free_mb})
    )


def _run(root: Path, manifest: Path, *args: str) -> tuple[subprocess.CompletedProcess, Path]:
    env = runner_env(root)
    runner = sandbox_runner(root, RUNNER)
    pager = runner.parent / "pipeline_disk_alert.py"
    pager.write_text(STUB_PAGER, encoding="utf-8")
    pager.chmod(0o755)
    calls = root / "pager_calls.jsonl"
    env["STUB_PAGER_LOG"] = str(calls)
    cmd = ["bash", str(runner), "--manifest", str(manifest), "--project-root", str(root), *args]
    r = subprocess.run(cmd, cwd=str(root), env=env, capture_output=True, text=True, timeout=120)
    return r, calls


def _summary(root: Path, pipeline: str, stage: str) -> dict:
    return json.loads((root / "data" / "runtime" / f"pipeline_{pipeline}_{stage}_last.json").read_text())


def test_bash_syntax_and_helpers_present():
    assert subprocess.run(["bash", "-n", str(PIPELINES / "_manifest_runner.sh")], capture_output=True).returncode == 0
    src = (PIPELINES / "_manifest_runner.sh").read_text(encoding="utf-8")
    for fn in ("_mr_disk_preflight", "_mr_disk_page", "_mr_avail_mb"):
        assert f"{fn}()" in src
    assert "min_free_mb" not in src.replace('["min_free_mb"]', ""), (
        "the threshold value lives in config, not the script"
    )


def test_low_free_space_pages_once_and_the_steps_still_run(tmp_path):
    _policy(tmp_path, 10**9)  # no host has an exabyte free: forces the low-space branch deterministically
    r, calls = _run(tmp_path, _manifest(tmp_path, "pf"), "--stage", "test", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[disk] LOW FREE SPACE" in r.stdout
    lines = calls.read_text().splitlines()
    assert len(lines) == 1
    argv = json.loads(lines[0])
    assert "--pipeline" in argv and argv[argv.index("--pipeline") + 1] == "pf"
    assert argv[argv.index("--reason") + 1] == "low_disk" and "--min-mb" in argv
    s = _summary(tmp_path, "pf", "test")
    assert s["executed_any"] is True and s["step_count"] == 1


def test_missing_policy_skips_the_preflight_and_says_so(tmp_path):
    r, calls = _run(tmp_path, _manifest(tmp_path, "np"), "--stage", "test", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[disk] policy missing" in r.stdout and not calls.exists()
    assert _summary(tmp_path, "np", "test")["step_count"] == 1


def test_healthy_disk_passes_quietly(tmp_path):
    _policy(tmp_path, 1)
    r, calls = _run(tmp_path, _manifest(tmp_path, "hd"), "--stage", "test", "--apply")
    assert r.returncode == 0 and "✓" in r.stdout and "[disk] free" in r.stdout and not calls.exists()


def test_unwritable_run_log_does_not_take_the_steps_with_it(tmp_path):
    _policy(tmp_path, 1)
    logdir = tmp_path / "logs" / "pipelines" / "ul"
    logdir.mkdir(parents=True)
    logdir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # the runner cannot create its RUN_LOG here
    try:
        r, _ = _run(tmp_path, _manifest(tmp_path, "ul"), "--stage", "test", "--apply")
    finally:
        logdir.chmod(0o755)
    # The per-step receipt file lives in the same unwritable directory, so the worker reports a receipt failure
    # and the runner exits 1 — honestly. What must hold: the step RAN, the summary was written, the log fell back.
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "[log] cannot write" in r.stderr + r.stdout
    assert "step ok_step END status=ok" in r.stdout
    s = _summary(tmp_path, "ul", "test")
    assert s["step_count"] == 1 and s["log"] == "/dev/null"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")
def test_unwritable_receipt_dir_pages_and_exits_1(tmp_path):
    _policy(tmp_path, 1)
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    rt.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        r, calls = _run(tmp_path, _manifest(tmp_path, "ur"), "--stage", "test", "--apply")
    finally:
        rt.chmod(0o755)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[summary] FAILED" in r.stderr + r.stdout
    argv = json.loads(calls.read_text().splitlines()[-1])
    assert argv[argv.index("--reason") + 1] == "summary_write_failed"


def test_pager_sends_one_p1_dedupe_zero_intent(monkeypatch, tmp_path):
    sys.path.insert(0, str(PIPELINES))
    import pipeline_disk_alert as pda

    sent = []
    tg = types.ModuleType("telegram_alert")
    tg.send_telegram = lambda msg, **k: sent.append({"msg": msg, **k}) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(pda, "write_receipt", lambda payload: None)
    rc = pda.main(
        ["--pipeline", "premarket", "--stage", "premarket", "--avail-mb", "12", "--min-mb", "2048", "--mount", "/"]
    )
    assert rc == 0 and len(sent) == 1
    c = sent[0]
    assert c["priority"] == "P1" and c["dedupe_minutes"] == 0 and c["producer"] == "manifest_runner"
    assert "12 MB" in c["msg"] and "2048 MB" in c["msg"] and "premarket/premarket" in c["msg"]
    tg.send_telegram = lambda msg, **k: False
    assert pda.main(["--pipeline", "p", "--stage", "s", "--reason", "summary_write_failed"]) == 1
