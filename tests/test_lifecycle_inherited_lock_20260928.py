"""2026-09-28: options_thesis_lifecycle.py self-deadlocked. The crontab wraps it in
`flock -n /tmp/options_thesis_lifecycle.lock ...` and the script (since 09-27) took the same
lock again from a fresh descriptor, so every scheduled pass printed "held by another run" and
exited 0 -- 57 skips, every thesis stuck at CREATED, no CIO decisions. flock(1) leaves its
descriptor open in the child, so the fix inherits an ancestor's lock found in /proc/self/fd.
Hermetic: temp lock file, a real subprocess for the foreign-holder case."""
from __future__ import annotations

import fcntl
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.options_thesis_lifecycle import acquire_lifecycle_lock  # noqa: E402


def test_free_lock_is_acquired(tmp_path):
    state, fh = acquire_lifecycle_lock(str(tmp_path / "l.lock"))
    assert state == "acquired" and fh is not None
    fh.close()


def test_lock_held_on_an_inherited_descriptor_is_inherited_not_refused(tmp_path):
    """Simulates `flock -n path cmd`: the lock file is open and locked in this process before
    the script's lock step runs (the child inherits flock(1)'s descriptor)."""
    path = tmp_path / "l.lock"
    parent = open(path, "a+")
    fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        state, fh = acquire_lifecycle_lock(str(path))
        assert state == "inherited" and fh is None
    finally:
        parent.close()


def test_lock_held_by_a_foreign_process_is_refused(tmp_path):
    path = tmp_path / "l.lock"
    holder = subprocess.Popen(["flock", str(path), "sleep", "5"])
    try:
        for _ in range(50):          # wait until flock(1) really holds it
            time.sleep(0.05)
            probe = open(path, "a+")
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(probe, fcntl.LOCK_UN)
                probe.close()
            except OSError:
                probe.close()
                break
        state, fh = acquire_lifecycle_lock(str(path))
        assert state == "held" and fh is None
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_cron_shape_end_to_end(tmp_path):
    """The real shape: `flock -n path python -c '<acquire>'` must report inherited, not held."""
    path = tmp_path / "l.lock"
    code = ("import sys; sys.path[:0]=[%r, %r]; from scripts.options_thesis_lifecycle import acquire_lifecycle_lock as a; "
            "print(a(%r)[0])") % (str(ROOT), str(ROOT / "scripts"), str(path))
    out = subprocess.run(["flock", "-n", str(path), sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip().splitlines()[-1] == "inherited", out.stdout
