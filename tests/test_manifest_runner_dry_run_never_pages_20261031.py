"""A --dry-run of the manifest runner never pages for real (DSN-20261031-market-risk-engine-P0-T5 follow-up).

Live verification 2026-10-31 (agent_scratch/live-verify/MATRIX.md, #2316 row): the runner's disk preflight called
scripts/pipelines/pipeline_disk_alert.py without --dry-run even when the runner itself was a dry run, so checking any
manifest pipeline on a full disk sent a real P1. Pins, in a temp PROJECT_ROOT with a stub pager that records its argv:
a dry run passes --dry-run to the pager; an --apply run does not.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.pipeline_runner_fixtures import runner_env, sandbox_runner
from tests.test_manifest_runner_disk_preflight_20261031 import RUNNER, STUB_PAGER, _manifest, _policy


def _run(root: Path, manifest: Path, *args: str):
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


def _argv(calls: Path) -> list[list[str]]:
    return [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []


def test_dry_run_passes_dry_run_to_the_pager(tmp_path):
    _policy(tmp_path, 10**9)  # forces the low-space branch
    r, calls = _run(tmp_path, _manifest(tmp_path, "dr"), "--stage", "test", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    argvs = _argv(calls)
    assert argvs, "the preflight still evaluates in a dry run"
    assert all("--dry-run" in a for a in argvs), argvs


def test_default_invocation_is_a_dry_run_and_does_not_page(tmp_path):
    _policy(tmp_path, 10**9)
    r, calls = _run(tmp_path, _manifest(tmp_path, "df"), "--stage", "test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert all("--dry-run" in a for a in _argv(calls))


def test_apply_pages_for_real(tmp_path):
    _policy(tmp_path, 10**9)
    r, calls = _run(tmp_path, _manifest(tmp_path, "ap"), "--stage", "test", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    argvs = _argv(calls)
    assert len(argvs) == 1 and "--dry-run" not in argvs[0], argvs
