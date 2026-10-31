"""Follow-up to #2344 (2026-10-31 round-2 review, non-blocking findings).

1. A trim of a corrupt tail that fails mid-write (ENOSPC) must leave no partial ``cio_wake_jobs.tmp`` (up to the
   store size, ~100 MB live) and no ``.corrupt-tail-<ts>`` copy behind; the store is unchanged and the error raises.
2. ``run_once`` must stop after a ``wake_store_unavailable`` error instead of running the goal-wake / dispatch /
   situation tails, each of which writes the same store and can wait the full lock timeout.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(store: Path, code: str) -> subprocess.CompletedProcess:
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from pathlib import Path
        from scripts.lib.cio_wake_jobs import CIOWakeJobStore
        store = CIOWakeJobStore(event_store_path=Path({str(store)!r}))
        """
    ) + textwrap.dedent(code)
    env = dict(os.environ, TRADE_AI_CI="1", CIO_WAKE_JOBS_LOCK_TIMEOUT_S="5")
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30, env=env)


def test_failed_trim_leaves_no_tmp_or_quarantine_files(tmp_path):
    store_path = tmp_path / "cio_wake_jobs.jsonl"
    r = _run(
        store_path,
        """
        import errno
        import scripts.lib.cio_wake_jobs as m
        store.enqueue({"wake_job_id": "good-0", "trigger_type": "SCHEDULE_DUE"})
        with open(store.event_store_path, "a") as f:
            f.write('{"stream_id": "trunc')
        before = store.event_store_path.read_bytes()
        def enospc_after_partial(path, data):
            with open(path, "wb") as fh:  # a real ENOSPC leaves the bytes written so far
                fh.write(data[: max(1, len(data) // 2)])
            raise OSError(errno.ENOSPC, "No space left on device")
        m._write_fsync = enospc_after_partial
        try:
            store.quarantine_corrupt_trailing_events()
            print("NO RAISE")
        except OSError:
            print("raised")
        print("unchanged", store.event_store_path.read_bytes() == before)
        """,
    )
    assert r.returncode == 0, r.stderr
    assert "raised" in r.stdout and "unchanged True" in r.stdout
    leftovers = sorted(
        p.name for p in tmp_path.iterdir() if p.name != "cio_wake_jobs.jsonl" and not p.name.endswith(".lock")
    )
    assert leftovers == [], leftovers


def test_failed_store_replace_also_removes_tmp(tmp_path):
    """The fsyncs succeed but the rename fails: the full-size .tmp must still go."""
    store_path = tmp_path / "cio_wake_jobs.jsonl"
    r = _run(
        store_path,
        """
        import errno, os
        import scripts.lib.cio_wake_jobs as m
        store.enqueue({"wake_job_id": "good-0", "trigger_type": "SCHEDULE_DUE"})
        with open(store.event_store_path, "a") as f:
            f.write('{"stream_id": "trunc')
        def bad_replace(src, dst):
            raise OSError(errno.EIO, "I/O error")
        m.os.replace = bad_replace
        try:
            store.quarantine_corrupt_trailing_events()
        except OSError:
            print("raised")
        """,
    )
    assert r.returncode == 0, r.stderr
    assert "raised" in r.stdout
    leftovers = sorted(
        p.name for p in tmp_path.iterdir() if p.name != "cio_wake_jobs.jsonl" and not p.name.endswith(".lock")
    )
    assert leftovers == [], leftovers


def test_run_once_stops_after_wake_store_unavailable(monkeypatch):
    import scripts.cio_reactive_cycle as rc
    import scripts.lib.cio_event_bus as bus_mod
    import scripts.lib.cio_wake_dispatcher as disp_mod
    import scripts.lib.cio_wake_jobs as jobs_mod

    calls: list[str] = []

    class FakeStore:
        def quarantine_corrupt_trailing_events(self):
            return {"ok": True, "removed": 0}

    class FakeDispatcher:
        def __init__(self, *a, **k):
            calls.append("dispatcher")

        def enqueue_goal_wakes(self, **k):
            calls.append("goal")
            return {}

    def fake_process(bus, store, *, out, max_wakes):
        out["errors"].append("wake_store_unavailable:wj1:CIOWakeLockTimeout:lock not acquired within 120s")
        return 0, []

    monkeypatch.setattr(rc, "_enabled", lambda: True)
    monkeypatch.setattr(rc, "process_event_bus", fake_process)
    monkeypatch.setattr(bus_mod, "CIOEventBus", lambda *a, **k: object())
    monkeypatch.setattr(jobs_mod, "CIOWakeJobStore", FakeStore)
    monkeypatch.setattr(disp_mod, "CIOWakeDispatcher", FakeDispatcher)

    out = rc.run_once(max_wakes=4)
    assert out.get("stopped_early") == "wake_store_unavailable"
    assert calls == []  # no goal-wake, dispatch or later tail touched the unavailable store
    assert out["errors"][0].startswith("wake_store_unavailable:")
