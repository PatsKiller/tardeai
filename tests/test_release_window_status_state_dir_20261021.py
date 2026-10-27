"""ANCHOR RELEASE_WINDOW_STATUS_STATE_DIR_20261021: ``release_window.py status`` prints the ``state_dir`` it reads and
where that path came from, so the deploy STOP latch directory can be compared with the CC's ``GET /api/v2/ops/deploys/
stop`` ``state_dir``. (The release-train arming step-G and packet pins were archived with the train 2026-10-27.)

Hermetic: release_window is imported in a subprocess with a controlled environment and a tmp state dir. No network,
DB, systemd or broker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]


def _status(env_over: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("TRADEAI_STATE_ROOT", "TRADEAI_RELEASE_WINDOW_STATE_DIR")}
    env.update(env_over)
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_window.py"), "status"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_status_names_the_state_dir_from_the_explicit_env(tmp_path):
    d = tmp_path / "rw"
    body = _status({"TRADEAI_RELEASE_WINDOW_STATE_DIR": str(d), "HOME": str(tmp_path)})
    assert body["state_dir"] == str(d) and body["state_dir_source"] == "env:TRADEAI_RELEASE_WINDOW_STATE_DIR"
    assert body["latch_path"] == str(d / "STOP.json") and body["latch_state"] == "ABSENT"


def test_status_names_the_state_root_source(tmp_path):
    body = _status({"TRADEAI_STATE_ROOT": str(tmp_path / "ps"), "HOME": str(tmp_path)})
    assert body["state_dir"] == str(tmp_path / "ps" / "data" / "runtime" / "release_window")
    assert body["state_dir_source"] == "env:TRADEAI_STATE_ROOT"


def test_status_names_the_default(tmp_path):
    body = _status({"HOME": str(tmp_path)})
    assert body["state_dir"] == str(
        tmp_path / "trade-ai-releases" / "persistent-state" / "data" / "runtime" / "release_window"
    )
    assert body["state_dir_source"] == "default"


def test_runner_status_with_an_explicit_root_says_argument(tmp_path):
    from scripts import release_window as RW

    runner = RW.Runner(RW.Host(checkout=tmp_path, releases=tmp_path, canonical=tmp_path), RW.State(tmp_path / "x"))
    code, body = runner.status()
    assert body["state_dir"] == str(tmp_path / "x") and body["state_dir_source"] == "argument"


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_window_status_state_dir_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_WINDOW_STATUS_STATE_DIR_20261021"
    assert "tests/test_release_window_status_state_dir_20261021.py" in doc["files"]
