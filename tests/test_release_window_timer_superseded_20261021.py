"""Release train arming finding 7 (ANCHOR RELEASE_WINDOW_TIMER_SUPERSEDED_20261021): nothing installs the old
12:00/17:30 ``release_window.py run`` timer beside the release train.

* ``install_release_window_timer.sh --apply`` refuses (SUPERSEDED), even with ``TRADEAI_OPERATOR_INSTALL=1``; the dry
  run says SUPERSEDED; ``--disable`` (archive, never delete) is unchanged;
* the old packet's timer step (§5, §8 step 3) is marked SUPERSEDED with a pointer to the arming packet;
* ``release_train_arm.sh`` step D refuses to install the claimer while ``tradeai-release-window.timer`` is present.

Hermetic: the installer runs with HOME in tmp_path and a PATH whose systemctl is a recording stub; the arming
sandbox under $TMPDIR. Nothing touches the real user units.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_release_train_arming_20261021 import Sandbox  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "docs/ops/packets/release-train-20261021"
INSTALL = OLD / "install_release_window_timer.sh"


def _install(tmp_path, *args, **env):
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "systemctl").write_text(f"#!/bin/sh\necho \"systemctl $*\" >> {tmp_path}/calls.log\nexit 0\n")
    (stub / "systemctl").chmod(0o755)
    e = {"PATH": f"{stub}:{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
         "CANONICAL_SOURCE": str(tmp_path / "nope"), "TRADEAI_RELEASE_CHECKOUT": str(tmp_path / "nope"), **env}
    return subprocess.run(["bash", str(INSTALL), *args], env=e, capture_output=True, text=True, timeout=60)


def test_apply_is_refused_even_for_the_operator(tmp_path):
    r = _install(tmp_path, "--apply", TRADEAI_OPERATOR_INSTALL="1")
    assert r.returncode == 2 and "SUPERSEDED" in r.stdout and "release-train-arming-20261021" in r.stdout
    assert not (tmp_path / "home" / ".config" / "systemd").exists()
    assert not (tmp_path / "calls.log").exists()                     # no systemctl call at all


def test_dry_run_says_superseded_and_writes_nothing(tmp_path):
    r = _install(tmp_path)
    assert r.returncode == 0 and r.stdout.startswith("== SUPERSEDED")
    assert not (tmp_path / "home").exists()


def test_disable_still_archives_an_installed_copy(tmp_path):
    units = tmp_path / "home" / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    (units / "tradeai-release-window.timer").write_text("[Timer]\n")
    r = _install(tmp_path, "--disable", TRADEAI_OPERATOR_INSTALL="1")
    assert r.returncode == 0 and not (units / "tradeai-release-window.timer").exists()
    assert list(units.glob("archived-tradeai-release-window-*/tradeai-release-window.timer"))


def test_old_packet_marks_the_timer_step_superseded():
    text = (OLD / "README.md").read_text(encoding="utf-8")
    s5 = text[text.index("## 5. Scheduling"):text.index("## 6.")]
    assert "**SUPERSEDED 2026-10-21 (release-train arming finding 7).**" in s5
    assert "docs/ops/packets/release-train-arming-20261021/README.md" in s5
    s8 = text[text.index("## 8. Operator steps"):text.index("## 9.")]
    assert "3. **SUPERSEDED**" in s8 and "TRADEAI_OPERATOR_INSTALL=1 … --apply" not in s8


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


def test_step_d_refuses_while_the_old_timer_is_installed(sb):
    sb.units.mkdir(parents=True, exist_ok=True)
    (sb.units / "tradeai-release-window.timer").write_text("[Timer]\n")
    r = sb.run("D")
    assert r.returncode == 2 and "superseded tradeai-release-window.timer" in r.stdout
    r = sb.apply("D")
    assert r.returncode == 2 and "never both release paths" in r.stdout
    assert not (sb.units / "tradeai-release-train-claim.service").exists()


def test_packet_finding_7_is_marked_fixed():
    text = (ROOT / "docs/ops/packets/release-train-arming-20261021/README.md").read_text(encoding="utf-8")
    seg = text[text.index("7. **Two release schedules.**"):]
    assert "**Status: FIXED**" in seg[:1400]


def test_gate_file_registers_this_test():
    doc = json.loads((ROOT / "config/ci_gates/release_window_timer_superseded_20261021.json").read_text())
    assert doc["anchor"] == "RELEASE_WINDOW_TIMER_SUPERSEDED_20261021"
    assert "tests/test_release_window_timer_superseded_20261021.py" in doc["files"]
