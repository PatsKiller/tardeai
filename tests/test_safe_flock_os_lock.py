import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tests.support.real_release_layout import real_release_layout

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "safe_flock.sh"
CHECKOUT_JOURNAL = ROOT / "logs" / "safe_flock_events.jsonl"


def _journal_size(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


@pytest.fixture(autouse=True)
def _temp_refusal_journal(tmp_path, monkeypatch):
    """A refused wrapper journals to $PROJECT_ROOT/logs (never to the refused caller path).

    Without this, every refusal test appended to the checkout's logs/ journal, and run
    from a release (CURRENT/logs -> persistent-state/logs) to the PRODUCTION journal the
    cron-outage watchdog reads (2026-10-24: job "rl3", log_path_preflight_refused).
    """
    project = tmp_path / "project-root"
    (project / "logs").mkdir(parents=True)
    monkeypatch.setenv("PROJECT_ROOT", str(project))
    before = _journal_size(CHECKOUT_JOURNAL)
    yield project / "logs" / "safe_flock_events.jsonl"
    assert _journal_size(CHECKOUT_JOURNAL) == before, "a test wrote the checkout/production safe_flock journal"


def _wait(path, proc):
    deadline = time.monotonic() + 10
    while not path.exists():
        assert proc.poll() is None
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_concurrent_invocation_is_skipped_until_command_finishes(tmp_path):
    lock = tmp_path / "shared.lock"
    logdir = tmp_path / "logs"
    entered = tmp_path / "entered"
    env = {**os.environ, "SAFE_FLOCK_LOG_DIR": str(logdir)}
    holder = subprocess.Popen(
        ["bash", str(WRAPPER), str(lock), "bash", "-c", 'touch "$1"; sleep 1', "_", str(entered)], env=env
    )
    try:
        _wait(entered, holder)
        contender = subprocess.run(
            ["bash", str(WRAPPER), str(lock), "bash", "-c", 'echo ran > "$1"', "_", str(tmp_path / "ran")],
            env=env,
            text=True,
            capture_output=True,
            timeout=5,
        )
        assert contender.returncode == 0
        assert "safe_flock: skipped" in contender.stderr
        assert not (tmp_path / "ran").exists()
        holder.wait(timeout=5)
        assert lock.exists(), "lock inode must remain stable after completion"
        events = [json.loads(line) for line in (logdir / "safe_flock_events.jsonl").read_text().splitlines()]
        assert [e["event_type"] for e in events] == ["started", "lock_skip", "completed"]
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()


def test_outer_flock_same_inode_can_wrap_observable_wrapper(tmp_path):
    lock = tmp_path / "shared.lock"
    logdir = tmp_path / "logs"
    env = {**os.environ, "SAFE_FLOCK_LOG_DIR": str(logdir)}
    # This is the deployed cron shape for several jobs: the flock descriptor
    # must be recognized/reused so the inner wrapper does not skip itself.
    result = subprocess.run(
        ["flock", "-n", str(lock), "bash", str(WRAPPER), str(lock), "true"],
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in (logdir / "safe_flock_events.jsonl").read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["started", "completed"]


def test_outer_flock_relative_path_is_recognized_by_inode(tmp_path):
    lock = tmp_path / "shared.lock"
    logdir = tmp_path / "logs"
    env = {**os.environ, "SAFE_FLOCK_LOG_DIR": str(logdir)}
    # The kernel lock is the same even when the outer caller uses a relative
    # path and the wrapper would otherwise compare a different path spelling.
    result = subprocess.run(
        ["flock", "-n", "shared.lock", "bash", str(WRAPPER), "shared.lock", "true"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in (logdir / "safe_flock_events.jsonl").read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["started", "completed"]


def test_reused_live_pid_metadata_does_not_skip_after_kernel_lock_acquired(tmp_path):
    lock = tmp_path / "shared.lock"
    logdir = tmp_path / "logs"
    env = {**os.environ, "SAFE_FLOCK_LOG_DIR": str(logdir)}
    lock.with_name("shared.lock.pid").write_text(f"{os.getpid()}\n")
    lock.with_name("shared.lock.meta").write_text("started_epoch=1\n")

    result = subprocess.run(
        ["bash", str(WRAPPER), str(lock), "bash", "-c", 'echo ran > "$1"', "_", str(tmp_path / "ran")],
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "ran").read_text().strip() == "ran"
    events = [json.loads(line) for line in (logdir / "safe_flock_events.jsonl").read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["stale_lock_cleared", "started", "completed"]


def test_precreated_lock_symlink_is_rejected_without_touching_target(tmp_path):
    target = tmp_path / "victim"
    target.write_text("keep me")
    lock = tmp_path / "shared.lock"
    lock.symlink_to(target)
    ran = tmp_path / "ran"
    result = subprocess.run(
        ["bash", str(WRAPPER), str(lock), "touch", str(ran)],
        env={**os.environ, "SAFE_FLOCK_LOG_DIR": str(tmp_path / "logs")},
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "unsafe existing file" in result.stderr
    assert target.read_text() == "keep me"
    assert not ran.exists()


def test_precreated_sidecar_symlinks_are_rejected_without_truncation(tmp_path):
    for suffix in ("pid", "meta"):
        target = tmp_path / f"victim-{suffix}"
        target.write_text("preserve")
        (tmp_path / f"shared.lock.{suffix}").symlink_to(target)
    ran = tmp_path / "ran"
    result = subprocess.run(
        ["bash", str(WRAPPER), str(tmp_path / "shared.lock"), "touch", str(ran)],
        env={**os.environ, "SAFE_FLOCK_LOG_DIR": str(tmp_path / "logs")},
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "unsafe existing file" in result.stderr
    assert (tmp_path / "victim-pid").read_text() == "preserve"
    assert (tmp_path / "victim-meta").read_text() == "preserve"
    assert not ran.exists()


def test_world_writable_non_sticky_lock_parent_is_rejected(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o777)
    result = subprocess.run(
        ["bash", str(WRAPPER), str(parent / "shared.lock"), "true"],
        env={**os.environ, "SAFE_FLOCK_LOG_DIR": str(tmp_path / "logs")},
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "unsafe parent directory permissions" in result.stderr
    assert not (parent / "shared.lock").exists()


def test_symlinked_log_directory_is_rejected_before_creating_target_path(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    redirected_logs = target / "created-by-mkdir"
    logdir = tmp_path / "logs"
    logdir.symlink_to(redirected_logs, target_is_directory=True)

    result = subprocess.run(
        ["bash", str(WRAPPER), str(tmp_path / "shared.lock"), "true"],
        env={**os.environ, "SAFE_FLOCK_LOG_DIR": str(logdir)},
        text=True,
        capture_output=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "log path component is not a real directory" in result.stderr
    assert not redirected_logs.exists()
    assert not (tmp_path / "shared.lock").exists()


def test_project_root_reached_through_release_symlink_runs(tmp_path):
    """Cron runs from portfolio-server/CURRENT (a symlink to the release dir); the default log dir must work."""
    layout = real_release_layout(tmp_path, ROOT)
    release, current = layout.release, layout.current
    ran = tmp_path / "ran"
    env = {k: v for k, v in os.environ.items() if k not in ("SAFE_FLOCK_LOG_DIR", "PROJECT_ROOT")}
    env["PROJECT_ROOT"] = str(current)
    result = subprocess.run(
        ["bash", str(current / "scripts" / "safe_flock.sh"), str(tmp_path / "job.lock"), "touch", str(ran)],
        env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert ran.exists()
    assert (release / "logs" / "safe_flock_events.jsonl").exists()


def test_symlinked_explicit_log_dir_is_still_rejected(tmp_path):
    real = tmp_path / "real-logs"
    real.mkdir()
    link = tmp_path / "logs"
    link.symlink_to(real)
    ran = tmp_path / "ran"
    result = subprocess.run(
        ["bash", str(WRAPPER), str(tmp_path / "job.lock"), "touch", str(ran)],
        env={**os.environ, "SAFE_FLOCK_LOG_DIR": str(link)}, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert "not a real directory" in result.stderr
    assert not ran.exists()


def test_real_layout_refusal_proof_journals_only_to_the_temp_state(tmp_path, _temp_refusal_journal):
    """The 2026-10-24 "rl3" proof shape, on the release layout, with a temp journal.

    A symlinked SAFE_FLOCK_LOG_DIR is refused; the refusal is recorded in the layout's
    own persistent-state/logs (temp), never in the checkout or production journal.
    """
    layout = real_release_layout(tmp_path, ROOT)
    real = tmp_path / "badlink" / "real"
    real.mkdir(parents=True)
    (tmp_path / "badlink" / "logs").symlink_to(real, target_is_directory=True)
    env = {k: v for k, v in os.environ.items() if k not in ("SAFE_FLOCK_LOG_DIR", "PROJECT_ROOT")}
    env.update(PROJECT_ROOT=str(layout.current), SAFE_FLOCK_LOG_DIR=str(tmp_path / "badlink" / "logs"))
    result = subprocess.run(
        ["bash", str(layout.current / "scripts" / "safe_flock.sh"), str(layout.locks / "rl3.lock"), "echo", "job-ran"],
        env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 1 and "job-ran" not in result.stdout
    events = [json.loads(line) for line in (layout.state / "logs" / "safe_flock_events.jsonl").read_text().splitlines()]
    assert [(e["job_id"], e["event_type"], e["reason"]) for e in events] == [("rl3", "refused", "log_path_preflight_refused")]
    assert not any(real.iterdir())
    assert not _temp_refusal_journal.exists()


# --- Trusted release symlinks in caller paths (2026-10-25) -------------------------------
# d5f51dbef refused EVERY symlink component; a2424b17f fixed only the default log dir.
# A caller path through the operator-owned CURRENT link (SAFE_FLOCK_LOG_DIR or a lock under
# CURRENT/) is accepted when every link is caller-owned and resolves inside a trusted root;
# links elsewhere, dangling links and unsafe resolved parents are still refused.

def _layout_env(project_root, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("SAFE_FLOCK_LOG_DIR", "PROJECT_ROOT")}
    env["PROJECT_ROOT"] = str(project_root)
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _events(journal):
    return [json.loads(line) for line in journal.read_text().splitlines()]


def test_real_layout_log_dir_and_lock_through_current_run(tmp_path):
    """Real layout: CURRENT -> release, release/logs -> persistent-state/logs (all temp)."""
    layout = real_release_layout(tmp_path, ROOT)
    (layout.release / "locks").mkdir()
    ran = tmp_path / "ran"
    result = subprocess.run(
        ["bash", str(layout.current / "scripts" / "safe_flock.sh"), str(layout.current / "locks" / "rl4.lock"),
         "touch", str(ran)],
        env=_layout_env(layout.current, SAFE_FLOCK_LOG_DIR=layout.current / "logs"),
        cwd=str(layout.current), text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert ran.exists()
    events = _events(layout.state / "logs" / "safe_flock_events.jsonl")
    assert [(e["job_id"], e["event_type"]) for e in events] == [("rl4", "started"), ("rl4", "completed")]
    assert (layout.release / "locks" / "rl4.lock").exists()


def test_release_base_layout_other_release_current_logs_run(tmp_path):
    """Production shape: portfolio-server/{relA,relB,CURRENT->relB}; wrapper served from relA."""
    base = tmp_path / "portfolio-server"
    state_logs = tmp_path / "persistent-state" / "logs"
    state_logs.mkdir(parents=True)
    os.chmod(state_logs, 0o775)
    for rel in ("relA", "relB"):
        (base / rel / "scripts" / "lib").mkdir(parents=True)
        (base / rel / "logs").symlink_to(state_logs, target_is_directory=True)
        for name in ("safe_flock.sh", "lib/wrapper_events.py"):
            shutil.copy2(ROOT / "scripts" / name, base / rel / "scripts" / name)
    (base / "CURRENT").symlink_to(base / "relB", target_is_directory=True)
    result = subprocess.run(
        ["bash", str(base / "relA" / "scripts" / "safe_flock.sh"), str(tmp_path / "rl5.lock"), "true"],
        env=_layout_env(base / "relA", SAFE_FLOCK_LOG_DIR=base / "CURRENT" / "logs"),
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert [e["event_type"] for e in _events(state_logs / "safe_flock_events.jsonl")] == ["started", "completed"]


def test_real_layout_symlink_out_of_trusted_roots_is_refused(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    outside = tmp_path / "outside"
    outside.mkdir()
    (layout.release / "escape").symlink_to(outside, target_is_directory=True)
    ran = tmp_path / "ran"
    for extra, lock in (({"SAFE_FLOCK_LOG_DIR": layout.current / "escape"}, layout.locks / "rl6.lock"),
                        ({}, layout.current / "escape" / "rl6.lock")):
        result = subprocess.run(
            ["bash", str(layout.current / "scripts" / "safe_flock.sh"), str(lock), "touch", str(ran)],
            env=_layout_env(layout.current, **extra), text=True, capture_output=True, timeout=10,
        )
        assert result.returncode == 1
        assert "symlink resolves outside the trusted roots" in result.stderr
        assert not ran.exists()
        assert not any(outside.iterdir())
    reasons = [e["reason"] for e in _events(layout.state / "logs" / "safe_flock_events.jsonl")]
    assert reasons == ["log_path_preflight_refused", "lock_or_journal_path_preflight_refused"]


def test_real_layout_dangling_symlink_is_refused_without_mkdir(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    missing = layout.release / "not-yet"
    (layout.release / "dangling").symlink_to(missing, target_is_directory=True)
    result = subprocess.run(
        ["bash", str(layout.current / "scripts" / "safe_flock.sh"), str(layout.locks / "rl7.lock"), "true"],
        env=_layout_env(layout.current, SAFE_FLOCK_LOG_DIR=layout.current / "dangling" / "logs"),
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 1
    assert "symlink target is not an existing directory" in result.stderr
    assert not missing.exists()


def test_symlink_into_unsafe_dir_inside_root_is_refused(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    shared = layout.release / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    (layout.release / "via").symlink_to(shared, target_is_directory=True)
    result = subprocess.run(
        ["bash", str(layout.current / "scripts" / "safe_flock.sh"), str(layout.current / "via" / "rl8.lock"), "true"],
        env=_layout_env(layout.current), text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 1
    assert "unsafe parent directory permissions" in result.stderr
    assert not (shared / "rl8.lock").exists()
