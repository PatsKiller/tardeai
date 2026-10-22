"""Release train arming finding 4 (ANCHOR RELEASE_WINDOW_STATUS_STATE_DIR_20261021): ``release_window.py status``
prints the ``state_dir`` it reads and where that path came from, so step G compares the runner's STOP latch
directory with the CC's ``GET /stop`` ``state_dir`` from the status output itself.

Hermetic: release_window is imported in a subprocess with a controlled environment and a tmp state dir. No network,
DB, systemd or broker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from tests.test_release_train_arming_20261021 import Sandbox  # noqa: E402


def _status(env_over: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("TRADEAI_STATE_ROOT", "TRADEAI_RELEASE_WINDOW_STATE_DIR")}
    env.update(env_over)
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "release_window.py"), "status"], cwd=str(ROOT),
                       env=env, capture_output=True, text=True, timeout=60)
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
    assert body["state_dir"] == str(tmp_path / "trade-ai-releases" / "persistent-state" / "data" / "runtime"
                                    / "release_window")
    assert body["state_dir_source"] == "default"


def test_runner_status_with_an_explicit_root_says_argument(tmp_path):
    from scripts import release_window as RW

    runner = RW.Runner(RW.Host(checkout=tmp_path, releases=tmp_path, canonical=tmp_path), RW.State(tmp_path / "x"))
    code, body = runner.status()
    assert body["state_dir"] == str(tmp_path / "x") and body["state_dir_source"] == "argument"


def test_train_status_names_the_state_dir_too(tmp_path):
    from scripts import release_window as RW
    from scripts.lib import release_train_controller as T

    body = T.status(RW.State(tmp_path / "s"))
    assert body["state_dir"] == str(tmp_path / "s") and body["state_dir_source"] == "argument"


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


def test_step_g_reads_the_runner_dir_from_status(sb):
    r = sb.run("G")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "release_window.py status state_dir (claimer env)" in r.stdout
    line = next(x for x in r.stdout.splitlines() if "release_window.py status state_dir" in x)
    assert str(sb.state_dir) in line and "[default]" in line and "verdict: MATCH" in r.stdout


def test_packet_finding_4_is_marked_fixed():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    seg = text[text.index("4. **`release_window.py status` reports no `state_dir`.**"):]
    assert "**Status: FIXED**" in seg[:1200]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_window_status_state_dir_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_WINDOW_STATUS_STATE_DIR_20261021"
    assert "tests/test_release_window_status_state_dir_20261021.py" in doc["files"]
