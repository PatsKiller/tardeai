"""MEM-CONTAIN 2026-11-13: portfolio_server_watchdog.sh never overlaps (flock -n) and stops killing after 3 kills in
30 min (ESCALATE, server left alone). Every external effect is a recording stub: a fake URL, a fake pid above
pid_max, a fake systemctl, and PORTFOLIO_WATCHDOG_KILL_CMD pointing at a recorder, so nothing is ever signalled."""
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "portfolio_server_watchdog.sh"
FAKE_PID = "2147483000"  # above any kernel pid_max: even a real kill could not hit a process


def _stub(d: Path, name: str, body: str) -> None:
    p = d / name
    p.write_text("#!/bin/bash\n" + body + "\n")
    p.chmod(0o755)


@pytest.fixture
def env(tmp_path):
    stub = tmp_path / "bin"
    stub.mkdir()
    rec = tmp_path / "calls.log"
    killed = tmp_path / "killed.marker"
    # curl fails (server hung) until the recorder has "killed" the pid, then the respawned server answers
    # CURL_DELAY (real seconds) keeps a run inside its probes; NEVER_RECOVER keeps the server dead after the kill
    _stub(stub, "curl", f'echo "curl $*" >> "{rec}"; [ -n "$CURL_DELAY" ] && /bin/sleep "$CURL_DELAY"; '
                         f'[ -z "$NEVER_RECOVER" ] && [ -f "{killed}" ] && exit 0; exit 7')
    _stub(stub, "pgrep", f'echo "pgrep $*" >> "{rec}"; echo {FAKE_PID}')
    _stub(stub, "systemctl", f'echo "systemctl $*" >> "{rec}"; case "$*" in *is-active*) echo active; exit 0;; '
                              f'*ControlGroup*) echo ""; exit 0;; esac; exit 0')
    _stub(stub, "sleep", f'echo "sleep $*" >> "{rec}"; exit 0')
    _stub(stub, "fake_kill", f'echo "kill $*" >> "{rec}"; [ "$1" = "-0" ] && exit 1; touch "{killed}"; exit 0')
    logs = tmp_path / "logs"
    logs.mkdir()
    e = dict(os.environ)
    e.update({
        "PATH": f"{stub}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "PORTFOLIO_WATCHDOG_URL": "http://127.0.0.1:9/fake-health",
        "PORTFOLIO_WATCHDOG_LOG": str(logs / "wd.log"),
        "PORTFOLIO_WATCHDOG_PROC": "fake_portfolio_server_for_test.py",
        "PORTFOLIO_WATCHDOG_KILL_CMD": str(stub / "fake_kill"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent",
    })
    return {"env": e, "rec": rec, "log": logs / "wd.log", "state": logs / ".portfolio_server_watchdog_kills",
            "lock": logs / ".portfolio_server_watchdog.lock", "tmp": tmp_path}


def _run(env, timeout=60):
    cp = subprocess.run(["/bin/bash", str(SH)], env=env["env"], capture_output=True, text=True, timeout=timeout)
    calls = env["rec"].read_text().splitlines() if env["rec"].exists() else []
    log = env["log"].read_text() if env["log"].exists() else ""
    return cp, calls, log


def test_first_kill_proceeds_and_is_recorded(env):
    cp, calls, log = _run(env)
    assert cp.returncode == 0, cp.stderr
    assert f"kill -TERM {FAKE_PID}" in calls
    assert f"killing pid {FAKE_PID}" in log and "RECOVERED" in log
    assert len(env["state"].read_text().split()) == 1
    assert any(c.startswith("curl ") and "127.0.0.1:9/fake-health" in c for c in calls)


def test_cap_reached_escalates_and_does_not_kill(env):
    now = int(time.time())
    env["state"].write_text("".join(f"{now - s}\n" for s in (100, 600, 1200)))
    cp, calls, log = _run(env)
    assert cp.returncode == 0, cp.stderr
    assert not any(c.startswith("kill ") for c in calls), calls
    assert "ESCALATE: 3 kills in the last 1800s (cap 3)" in log and f"NOT killing pid {FAKE_PID}" in log
    assert "killing pid" not in log.replace("NOT killing pid", "")
    assert len(env["state"].read_text().split()) == 3  # an escalation is not a kill


def test_old_kills_age_out_of_the_window(env):
    now = int(time.time())
    env["state"].write_text("".join(f"{now - s}\n" for s in (1900, 2500, 4000)) + "garbage\n")
    cp, calls, log = _run(env)
    assert f"kill -TERM {FAKE_PID}" in calls and "ESCALATE" not in log
    assert len(env["state"].read_text().split()) == 1  # pruned to the one new kill


def test_overlapping_run_is_skipped_by_flock(env):
    holder = subprocess.Popen(["flock", str(env["lock"]), "sleep", "30"])
    try:
        for _ in range(50):
            if env["lock"].exists():
                break
            time.sleep(0.05)
        time.sleep(0.2)
        cp, calls, log = _run(env)
    finally:
        holder.kill()
        holder.wait()
    assert cp.returncode == 0
    assert "previous watchdog run still active (flock busy)" in log
    assert not any(c.startswith(("curl ", "kill ")) for c in calls), calls


def test_healthy_server_is_left_alone(env):
    env["tmp"].joinpath("killed.marker").write_text("")  # curl stub answers
    cp, calls, log = _run(env)
    assert cp.returncode == 0
    assert not any(c.startswith("kill ") for c in calls) and "killing" not in log


def test_dry_run_text_names_flock_and_cycle_cap(env):
    cp = subprocess.run(["/bin/bash", str(SH), "--dry-run"], env=env["env"], capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0
    assert "flock" in cp.stdout and "3 kills in 30 min" in cp.stdout and "ESCALATE" in cp.stdout
    assert not env["rec"].exists() and not env["log"].exists()


def test_two_runs_at_once_one_exits_on_the_lock(env):
    e = dict(env["env"], CURL_DELAY="1.5")
    a = subprocess.Popen(["/bin/bash", str(SH)], env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.5)
    b = subprocess.run(["/bin/bash", str(SH)], env=e, capture_output=True, text=True, timeout=60)
    a.communicate(timeout=120)
    log = env["log"].read_text()
    assert b.returncode == 0 and a.returncode == 0
    assert log.count("previous watchdog run still active (flock busy)") == 1
    calls = env["rec"].read_text().splitlines()
    assert sum(1 for c in calls if c.startswith("kill -TERM")) == 1  # only the lock holder acted


def test_failed_restart_is_logged_and_still_counts(env):
    e = dict(env["env"], NEVER_RECOVER="1", PORTFOLIO_WATCHDOG_VERIFY_SEC="2")
    cp = subprocess.run(["/bin/bash", str(SH)], env=e, capture_output=True, text=True, timeout=60)
    log = env["log"].read_text()
    assert cp.returncode == 0
    assert f"killing pid {FAKE_PID}" in log and "still not responding 2s after restart attempt" in log
    assert len(env["state"].read_text().split()) == 1


def test_cooldown_blocks_a_second_kill_soon_after_the_first(env):
    env["state"].write_text(f"{int(time.time()) - 60}\n")
    cp, calls, log = _run(env)
    assert cp.returncode == 0
    assert not any(c.startswith("kill ") for c in calls), calls
    assert "COOLDOWN: last kill" in log and "NOT killing pid" in log
    assert len(env["state"].read_text().split()) == 1


def test_budget_persists_across_separate_invocations_then_escalates(env):
    e = dict(env["env"], NEVER_RECOVER="1", PORTFOLIO_WATCHDOG_VERIFY_SEC="1", PORTFOLIO_WATCHDOG_KILL_COOLDOWN_S="0")
    for _ in range(4):  # four separate cron-like invocations, nothing shared but the files
        cp = subprocess.run(["/bin/bash", str(SH)], env=e, capture_output=True, text=True, timeout=60)
        assert cp.returncode == 0, cp.stderr
    calls = env["rec"].read_text().splitlines()
    log = env["log"].read_text()
    assert sum(1 for c in calls if c.startswith("kill -TERM")) == 3
    assert log.count("ESCALATE: 3 kills in the last 1800s (cap 3)") == 1
    assert len(env["state"].read_text().split()) == 3
    assert not list(env["state"].parent.glob("*.tmp*"))  # atomic rewrite leaves no temp file
