"""LQ-20261107-2253 (2246 root cause + regression gate): the executor arm of activate_live.sh never restarts the
executor on an unverified drain target.

Root cause (activate-2198.log, 2026-11-12 09:46 ET, "drain not acknowledged (no result)"): the drain CLI refused
(refused_market_busy, exit 3: a run older than 300 s was in flight) and wrote NO request; the old capture
``dres=$(CLI | sed | tail) || dres=""`` lost the printed token because pipefail failed the substitution on exit 3, so
the case fell to ``*)`` and restarted the executor on top of the previous promote's stale request.

Hermetic: tmp state roots, a stub ``systemctl`` and a stub python; the real CLI is run only against a tmp state root
with non-loopback sockets blocked. No systemd, no network, no broker. AUTHORITY: READ_ONLY_ADVISORY.
"""
# ANCHOR: EXECUTOR_STALE_DRAIN_TARGET_LQ2246_20261112 — gate record: config/ci_gates/executor_stale_drain_target_lq2246_20261112.json
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARM = ROOT / "scripts" / "ops" / "executor_drain_arm.sh"
CLI = ROOT / "scripts" / "n8n_executor_drain.py"
MARKET_NOW = 1794494760.0  # 2026-11-12 09:46 ET, a Thursday

LEGACY_CAPTURE = r'''
set -euo pipefail
dres=$(printf 'DRAIN_RESULT=refused_market_busy\n' | { cat; false; } | sed -n 's/^DRAIN_RESULT=//p' | tail -1) || dres=""
echo "dres=[$dres]"
'''


def _bash(script: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env=env)


def test_legacy_capture_idiom_drops_the_token_on_a_nonzero_exit():
    """The 09:46 mechanism, isolated: a printed token plus exit != 0 under pipefail reads as 'no result'."""
    r = _bash(LEGACY_CAPTURE)
    assert "dres=[]" in r.stdout, r.stdout + r.stderr


@pytest.fixture
def block_net(tmp_path):
    d = tmp_path / "nonet"
    d.mkdir()
    (d / "sitecustomize.py").write_text(
        "import socket\n_c = socket.socket.connect\n"
        "def _guard(self, addr, *a, **k):\n"
        "    host = addr[0] if isinstance(addr, tuple) else str(addr)\n"
        "    if isinstance(addr, tuple) and host not in ('127.0.0.1', '::1', 'localhost'):\n"
        "        raise OSError('non-loopback socket blocked by test')\n"
        "    return _c(self, addr, *a, **k)\n"
        "socket.socket.connect = _guard\n"
    )
    return str(d)


def test_real_cli_refuses_in_market_hours_exits_3_and_writes_nothing(tmp_path, block_net):
    state = tmp_path / "state"
    (state / "data" / "runtime").mkdir(parents=True)
    started = "2026-11-12T14:36:55+00:00"  # 9 min 5 s before MARKET_NOW, like the 09:46 sweep
    (state / "data" / "runtime" / "n8n_run_executor_last.json").write_text(
        json.dumps({"busy": [{"lane_id": "sweep", "run_id": "r1", "started_at": started}]})
    )
    new = tmp_path / "rel-new"
    new.mkdir()
    env = dict(os.environ, PYTHONPATH=block_net + os.pathsep + str(ROOT))
    r = subprocess.run(
        [sys.executable, str(CLI), "request", "--target", str(new), "--state-root", str(state),
         "--now", str(MARKET_NOW), "--no-systemd", "--wait-s", "0", "--ack-s", "0"],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert r.returncode == 3 and "DRAIN_RESULT=refused_market_busy" in r.stdout, r.stdout + r.stderr
    assert not (state / "data" / "runtime" / "n8n_executor_drain_request.json").exists()


# ── the arm, with a stub systemctl and a stub python ───────────────────────────────────────────────────────────


def _rig(tmp_path, request_out, request_rc, retarget_out, with_cli=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    new = tmp_path / "rel-new"
    (new / "scripts").mkdir(parents=True)
    if with_cli:
        (new / "scripts" / "n8n_executor_drain.py").write_text("# stub\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "systemctl.log"
    (bindir / "systemctl").write_text(f'#!/usr/bin/env bash\necho "$@" >> {log}\nexit 0\n')
    (bindir / "systemctl").chmod(0o755)
    vpy = bindir / "vpy"
    vpy.write_text(
        "#!/usr/bin/env bash\n"
        'case "$2" in\n'
        f'  request) printf %s "$STUB_REQUEST_OUT"; exit {request_rc} ;;\n'
        '  retarget) printf %s "$STUB_RETARGET_OUT"; exit 0 ;;\n'
        "esac\n"
    )
    vpy.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
               STUB_REQUEST_OUT=request_out, STUB_RETARGET_OUT=retarget_out)
    return new, vpy, log, env


def _run_arm(tmp_path, request_out, request_rc, retarget_out, with_cli=True, extra_env=None):
    new, vpy, log, env = _rig(tmp_path, request_out, request_rc, retarget_out, with_cli)
    env.update(extra_env or {})
    script = (
        "set -euo pipefail\n"
        f'source "{ARM}"\n'
        f'VPY="{vpy}"; NEW="{new}"\n'
        'RESTARTED=""; RESTART_FAILED=""; DEFERRED=""; DEFERRED_IN_FLIGHT=""\n'
        "executor_drain_arm tradeai-n8n-run-executor.service\n"
        'echo "RESTARTED=[$RESTARTED]"; echo "DEFERRED=[$DEFERRED]"; echo "HELD=[$DEFERRED_IN_FLIGHT]"; echo "FAILED=[$RESTART_FAILED]"\n'
    )
    r = _bash(script, env)
    assert r.returncode == 0, r.stdout + r.stderr
    restarts = [ln for ln in (log.read_text().splitlines() if log.exists() else []) if "restart" in ln]
    return r.stdout, restarts


UNIT = "tradeai-n8n-run-executor.service"


def test_re_resolved_is_not_restarted_again(tmp_path):
    out, restarts = _run_arm(tmp_path, "DRAIN_RESULT=re_resolved\n", 0, "")
    assert restarts == [] and f"RESTARTED=[ {UNIT}]" in out


def test_deferred_draining_is_not_restarted(tmp_path):
    out, restarts = _run_arm(tmp_path, "DRAIN_RESULT=deferred_draining\n", 0, "")
    assert restarts == [] and f"DEFERRED=[ {UNIT}]" in out


def test_in_flight_is_held_without_a_restart(tmp_path):
    out, restarts = _run_arm(tmp_path, "DRAIN_RESULT=in_flight\n", 0, "")
    assert restarts == [] and f"HELD=[ {UNIT}]" in out


def test_refused_market_busy_exit_3_is_held_without_a_restart(tmp_path):
    """The 09:46 arm: token printed with exit 3. Must HOLD (and must not need the retarget to be consulted)."""
    out, restarts = _run_arm(tmp_path, "DRAIN_RESULT=refused_market_busy\n", 3, "RETARGET_RESULT=ok\n")
    assert restarts == [] and f"HELD=[ {UNIT}]" in out and "market-hours long run" in out


def test_no_result_with_retarget_ok_restarts_once(tmp_path):
    out, restarts = _run_arm(tmp_path, "", 1, "RETARGET_RESULT=ok\n")
    assert len(restarts) == 1 and f"RESTARTED=[ {UNIT}]" in out and "HELD=[]" in out


def test_not_acknowledged_with_nothing_to_retarget_restarts(tmp_path):
    out, restarts = _run_arm(tmp_path, "DRAIN_RESULT=not_acknowledged\n", 0, "RETARGET_RESULT=absent\n")
    assert len(restarts) == 1 and "drain target verified (absent)" in out


@pytest.mark.parametrize("retarget_out", ["RETARGET_RESULT=mismatch\n", "", "garbage\n"])
def test_no_result_with_an_unverified_retarget_is_held_without_a_restart(tmp_path, retarget_out):
    out, restarts = _run_arm(tmp_path, "", 1, retarget_out)
    assert restarts == [] and f"HELD=[ {UNIT}]" in out and "RESTARTED=[]" in out


def test_release_without_the_cli_is_held_unless_explicitly_overridden(tmp_path):
    out, restarts = _run_arm(tmp_path / "a", "", 0, "", with_cli=False)
    assert restarts == [] and f"HELD=[ {UNIT}]" in out
    out2, restarts2 = _run_arm(tmp_path / "b", "", 0, "", with_cli=False,
                               extra_env={"ACTIVATE_UNVERIFIED_EXECUTOR_RESTART": "1"})
    assert len(restarts2) == 1
