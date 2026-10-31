"""Regression: a corrupt (truncated) tail on cio_wake_jobs.jsonl must not self-deadlock the writer.

2026-10-30 05:00 ET: after the disk-full night left a truncated final record, cio-event-detector (pid 2375400)
held the store lock in ``_append_event`` and then ``_get_last_event`` -> ``quarantine_corrupt_trailing_events``
opened a SECOND fd on the same lock file and blocked on it forever (flock locks per open file description).
cio_reactive_cycle and every */5 cio_wake_dispatch then queued behind it for 31 hours.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(store: Path, code: str, timeout: float = 20.0) -> subprocess.CompletedProcess:
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
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=timeout, env=env)


def _store_with_truncated_tail(tmp_path: Path) -> Path:
    store = tmp_path / "cio_wake_jobs.jsonl"
    r = _run(store, "pass")
    assert r.returncode == 0, r.stderr
    with open(store, "a", encoding="utf-8") as f:
        f.write('{"event_type": "CIO_WAKE_ENQUEUED", "stream_id": "trunc')  # ENOSPC mid-write, no newline
    return store


def test_enqueue_after_truncated_tail_does_not_deadlock(tmp_path):
    store = _store_with_truncated_tail(tmp_path)
    r = _run(
        store,
        """
        ev = store.enqueue({"wake_job_id": "w-1", "trigger_type": "SCHEDULE_DUE"})
        print("OK", ev["event_type"])
        """,
    )
    assert r.returncode == 0, r.stderr
    assert "OK CIO_WAKE_ENQUEUED" in r.stdout
    rows = [json.loads(x) for x in store.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows[-1]["stream_id"] == "w-1"
    # the truncated record was quarantined beside the store, not lost
    assert list(tmp_path.glob("cio_wake_jobs.jsonl.corrupt-tail-*"))
    # the hash chain links the new event to the last intact one
    assert rows[-1]["prev_event_hash"] == rows[-2]["event_hash"]


def test_lock_wait_is_bounded_when_another_process_holds_it(tmp_path):
    store = tmp_path / "cio_wake_jobs.jsonl"
    assert _run(store, "pass").returncode == 0
    lock = Path(str(store) + ".lock")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import fcntl,os,time; fd=os.open({str(lock)!r}, os.O_CREAT|os.O_RDWR); "
            "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        r = _run(store, 'store.enqueue({"wake_job_id": "w-2", "trigger_type": "SCHEDULE_DUE"})', timeout=30)
        assert r.returncode != 0
        assert "CIOWakeLockTimeout" in r.stderr
    finally:
        holder.kill()
        holder.wait()


def test_nested_acquire_in_one_process_is_reentrant(tmp_path):
    store = tmp_path / "cio_wake_jobs.jsonl"
    r = _run(
        store,
        """
        fd1 = store._acquire_lock()
        other = CIOWakeJobStore(event_store_path=store.event_store_path)  # second instance, same file
        fd2 = other._acquire_lock()
        other._release_lock(fd2)
        store._release_lock(fd1)
        print("nested ok")
        """,
    )
    assert r.returncode == 0, r.stderr
    assert "nested ok" in r.stdout


# ── round 2 (2026-10-31 independent review) ────────────────────────────────────────────────────────


def test_reactive_cycle_stops_without_advancing_cursor_on_store_timeout(monkeypatch, tmp_path):
    """3 events and a lock timeout on the first: the cursor stays where it was and the error is hard."""
    from datetime import datetime, timezone

    import scripts.cio_reactive_cycle as rc
    from scripts.lib.cio_wake_jobs import CIOWakeLockTimeout

    class Ev:
        def __init__(self, i):
            self.event_id = f"e{i}"
            self.event_type = "price.alert"
            self.timestamp = datetime.now(timezone.utc).isoformat()
            self.payload = {}
            self.symbol = "SYMA"

    class Bus:
        advanced: dict = {}

        def poll(self, consumer, event_types):
            return [Ev(1), Ev(2), Ev(3)]

        def advance_cursor(self, consumer, eid):
            Bus.advanced[consumer] = eid

    class Store:
        calls = 0

        def get_wake_job(self, _):
            return None

        def enqueue(self, *a, **k):
            Store.calls += 1
            raise CIOWakeLockTimeout("cio_wake_jobs.jsonl.lock: lock not acquired within 120s")

    out = {"errors": [], "event_enqueued": [], "event_skipped": [], "event_stale": [], "cursor_advanced": []}
    n, _ = rc.process_event_bus(
        Bus(), Store(), out=out, routing={"agent_x": ["price.alert"], "agent_y": ["price.alert"]}
    )
    assert n == 0 and Store.calls == 1  # stopped at the first failure, no second agent either
    assert Bus.advanced == {}  # nothing lost: next run retries from the same cursor
    assert out["errors"] and out["errors"][0].startswith("wake_store_unavailable:")
    soft = ("enqueue:", "cursor:", "wake_store_repair:")
    assert not out["errors"][0].startswith(soft)  # _execute treats it as hard -> exit 1


def test_append_never_glues_onto_a_partial_line_when_trim_fails(tmp_path):
    r = _run(
        tmp_path / "cio_wake_jobs.jsonl",
        """
        import errno
        import scripts.lib.cio_wake_jobs as m
        store.enqueue({"wake_job_id": "good-0", "trigger_type": "SCHEDULE_DUE"})
        with open(store.event_store_path, "a") as f:
            f.write('{"stream_id": "trunc')
        before = store.event_store_path.read_bytes()
        real = m._write_fsync
        def enospc(path, data):
            raise OSError(errno.ENOSPC, "No space left on device")
        m._write_fsync = enospc
        try:
            store.enqueue({"wake_job_id": "acked-1", "trigger_type": "SCHEDULE_DUE"})
            print("NO RAISE")
        except OSError:
            print("raised")
        print("unchanged", store.event_store_path.read_bytes() == before)
        m._write_fsync = real
        store.enqueue({"wake_job_id": "acked-1", "trigger_type": "SCHEDULE_DUE"})
        import json
        print("ids", [json.loads(x)["stream_id"] for x in store.event_store_path.read_bytes().split(b"\\n") if x.strip()])
        """,
    )
    assert r.returncode == 0, r.stderr
    assert "raised" in r.stdout and "unchanged True" in r.stdout
    assert "'good-0', 'acked-1'" in r.stdout


def test_quarantine_splits_on_newline_bytes_only(tmp_path):
    r = _run(
        tmp_path / "cio_wake_jobs.jsonl",
        """
        import json
        store.enqueue({"wake_job_id": "good-headline", "trigger_type": "SCHEDULE_DUE",
                       "context": {"headline": "beat\\u0085 raised\\u2028guide"}})
        with open(store.event_store_path, "a") as f:
            f.write('{"stream_id": "trunc')
        res = store.quarantine_corrupt_trailing_events()
        ids = [json.loads(x)["stream_id"] for x in store.event_store_path.read_bytes().split(b"\\n") if x.strip()]
        print("removed", res["removed"], "ids", ids)
        """,
    )
    assert r.returncode == 0, r.stderr
    assert "removed 1" in r.stdout and "good-headline" in r.stdout
