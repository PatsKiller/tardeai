import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "safe_flock.sh"


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
            env=env, text=True, capture_output=True, timeout=5,
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
        env=env, text=True, capture_output=True, timeout=5,
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
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=5,
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
        env=env, text=True, capture_output=True, timeout=5,
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
        text=True, capture_output=True, timeout=5,
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
        text=True, capture_output=True, timeout=5,
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
        text=True, capture_output=True, timeout=5,
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
        text=True, capture_output=True, timeout=5,
    )

    assert result.returncode != 0
    assert "log path component is not a real directory" in result.stderr
    assert not redirected_logs.exists()
    assert not (tmp_path / "shared.lock").exists()
