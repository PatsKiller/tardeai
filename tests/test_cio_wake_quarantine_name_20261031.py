"""Follow-up to #2360 (2026-10-31 round-3 review, LOW): two corrupt-tail trims inside one second shared the name
``.corrupt-tail-<int(time.time())>``; a failed second trim's cleanup could then delete the FIRST trim's quarantine copy.
Names now carry ns + pid (plus a bump if a name is still taken), and cleanup only removes a file this call created."""

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


def _quarantines(tmp_path: Path) -> list[Path]:
    return sorted(p for p in tmp_path.iterdir() if ".corrupt-tail-" in p.name)


def test_failed_second_trim_never_removes_the_first_trims_copy_on_a_frozen_clock(tmp_path):
    r = _run(
        tmp_path / "cio_wake_jobs.jsonl",
        """
        import errno, time
        import scripts.lib.cio_wake_jobs as m
        m.time.time_ns = lambda: 1793460000000000000  # both trims in the same nanosecond, same pid
        store.enqueue({"wake_job_id": "good-0", "trigger_type": "SCHEDULE_DUE"})
        with open(store.event_store_path, "a") as f:
            f.write('{"stream_id": "first-trunc')
        print("first", store.quarantine_corrupt_trailing_events()["removed"])
        with open(store.event_store_path, "a") as f:
            f.write('{"stream_id": "second-trunc')
        real = m._write_fsync
        def enospc_on_tmp(path, data):
            if path.name.endswith(".tmp"):
                raise OSError(errno.ENOSPC, "No space left on device")
            real(path, data)
        m._write_fsync = enospc_on_tmp
        try:
            store.quarantine_corrupt_trailing_events()
        except OSError:
            print("second raised")
        """,
    )
    assert r.returncode == 0, r.stderr
    assert "first 1" in r.stdout and "second raised" in r.stdout
    q = _quarantines(tmp_path)
    assert len(q) == 1, [p.name for p in q]  # the first trim's copy survives; the failed second left nothing
    assert b"first-trunc" in q[0].read_bytes()


def test_quarantine_name_carries_ns_and_pid(tmp_path):
    r = _run(
        tmp_path / "cio_wake_jobs.jsonl",
        """
        import os
        store.enqueue({"wake_job_id": "good-0", "trigger_type": "SCHEDULE_DUE"})
        with open(store.event_store_path, "a") as f:
            f.write('{"stream_id": "trunc')
        out = store.quarantine_corrupt_trailing_events()
        print("pid", os.getpid())
        print("name", Path(out["quarantine"]).name)
        """,
    )
    assert r.returncode == 0, r.stderr
    pid = r.stdout.split("pid ")[1].split()[0]
    name = r.stdout.split("name ")[1].split()[0]
    stamp = name.split(".corrupt-tail-")[1]
    ns, got_pid = stamp.split("-")[:2]
    assert len(ns) >= 18 and got_pid == pid
