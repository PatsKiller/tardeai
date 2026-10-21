"""a1a_compliance failed 2026-10-21 07:40 with summary errors=[] — a failure with no reason.

Root cause: release dirs stopped carrying .git (the exact-main overlay excludes it; the
first such release went CURRENT 2026-10-20 08:56). check_a1a_compliance.py ran
`git diff --name-only HEAD~1 HEAD` with cwd=<release>, git found no repository, and the
script died with CalledProcessError. The wrapper then recorded status=failed with no
errors, so the alert said "failed" and nothing else.

Fixed: a release is checked against the commit it was stamped from (BUILD_STAMP.json
source_sha) in the source checkout (lib.live_project_root.DEV_ROOT); when that is not
possible the checker writes its report with an `errors` entry and exits 2 instead of a
traceback, and the wrapper hands the reason to record_stage_run(errors=...).

Hermetic: temp git repo + temp release dir; never the served release, never the DB.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "scripts" / "check_a1a_compliance.py"
WRAPPER = ROOT / "scripts" / "run_scheduled_a1a_check.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd), env=_env(cwd.parent), stderr=subprocess.STDOUT,
    ).decode().strip()


def _env(ceiling: Path, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    env.update(extra)
    return env


def _source_repo(tmp: Path) -> tuple[Path, str]:
    repo = tmp / "src"
    (repo / "scripts").mkdir(parents=True)
    (repo / "README").write_text("x\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    (repo / "scripts" / "thing.py").write_text("print(1)\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "two")
    return repo, _git(repo, "rev-parse", "HEAD")


def _release(tmp: Path, sha: str | None) -> Path:
    rel = tmp / "release"
    (rel / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(CHECKER, rel / "scripts" / "check_a1a_compliance.py")
    shutil.copy(ROOT / "scripts" / "lib" / "__init__.py", rel / "scripts" / "lib" / "__init__.py")
    shutil.copy(ROOT / "scripts" / "lib" / "live_project_root.py", rel / "scripts" / "lib" / "live_project_root.py")
    if sha:
        (rel / "BUILD_STAMP.json").write_text(json.dumps({"source_sha": sha, "build_sha": sha}))
    return rel


def _run(rel: Path, tmp: Path, dev_root: Path):
    out_json = tmp / "out.json"
    p = subprocess.run(
        [sys.executable, str(rel / "scripts" / "check_a1a_compliance.py"), "--last-commit",
         "--output-json", str(out_json), "--verbose"],
        cwd=str(rel), env=_env(tmp, TRADEAI_DEV_ROOT=str(dev_root)),
        capture_output=True, text=True, timeout=60,
    )
    return p, out_json


def test_release_dir_without_git_checks_the_stamped_commit(tmp_path):
    repo, sha = _source_repo(tmp_path)
    rel = _release(tmp_path, sha)
    p, out_json = _run(rel, tmp_path, repo)
    assert "Traceback" not in p.stdout + p.stderr, p.stdout + p.stderr
    assert p.returncode == 0, p.stdout + p.stderr
    rep = json.loads(out_json.read_text())
    assert rep["errors"] == []
    assert rep["git_head"] == sha[:9]
    assert rep["files_checked"] == 1
    assert any(f["check"] == "code_without_docs" for f in rep["findings"])


def test_unresolvable_change_set_is_a_recorded_error_not_a_traceback(tmp_path):
    rel = _release(tmp_path, None)  # no .git, no stamp
    p, out_json = _run(rel, tmp_path, tmp_path / "absent")
    assert "Traceback" not in p.stdout + p.stderr, p.stdout + p.stderr
    assert p.returncode == 2
    assert "A1A ERROR:" in p.stdout
    rep = json.loads(out_json.read_text())
    assert rep["status"] == "check_error"
    assert rep["errors"] and "not a git work tree" in rep["errors"][0]


def test_wrapper_passes_failure_reason_to_telemetry():
    src = WRAPPER.read_text()
    call = [ln for ln in src.splitlines()
            if "record_stage_run('a1a_compliance','Governance','$_TELEM_STATUS'" in ln]
    assert len(call) == 1
    assert "errors=" in call[0]
    assert "A1A_TELEM_ERR" in call[0]
