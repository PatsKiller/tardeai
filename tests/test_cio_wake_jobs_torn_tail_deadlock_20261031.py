"""ANCHOR: CIO_WAKE_JOBS_TORN_TAIL_DEADLOCK_20261031

The 2026-10-30 disk-full night tore the last record of cio_wake_jobs.jsonl. Every
wake writer then hung in `_append_event`: it held the store flock and its
auto-trim tried to take the same flock again on a new descriptor (flock locks
belong to the open file description, so that blocks forever). No CIO wake was
recorded for 33 hours. The trim also left 41 zero-byte `.corrupt-tail-*` copies
because the quarantine write was not atomic on a full disk.
"""
from __future__ import annotations

import contextlib
import errno
import json
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.lib import cio_wake_jobs
from scripts.lib.cio_wake_jobs import CIOWakeJobStore

REPO = Path(__file__).resolve().parent.parent
TORN = '{"actor_id": "cio_wake_dispatcher", "event_type": "CIO_WAKE_IN_FLIGHT", "payl'


def _payload(n: int) -> dict:
    return {
        "wake_job_id": f"wake_test_{n}",
        "trigger_type": "EVENT_BUS",
        "trigger_ref": f"ev{n}",
        "trigger_hash": f"h{n}",
        "reason_codes": ["EVENT_BUS"],
        "required_domains": ["portfolio"],
        "wake_intent": "NEW_RUN",
        "idempotency_key": f"wake_test_{n}",
        "context": {"target_agent": "alex"},
    }


def _enqueue(store: CIOWakeJobStore, n: int) -> None:
    store.enqueue(_payload(n), actor_id="test", actor_type="system", authority="READ_ONLY_ADVISORY")


@contextlib.contextmanager
def _must_finish_within(seconds: int):
    """Fail instead of hanging the suite if an append blocks on the store's own flock."""

    def _boom(*_a):
        raise AssertionError(f"append blocked > {seconds}s: _append_event re-took its own flock")

    previous = signal.signal(signal.SIGALRM, _boom)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _bad_lines(path: Path) -> int:
    bad = 0
    for line in path.read_bytes().splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except ValueError:
            bad += 1
    return bad


def test_enqueue_after_torn_tail_does_not_hang(tmp_path: Path) -> None:
    """The real incident path: a writer appends while the tail is torn. Run in a child
    process so a regression shows as a timeout instead of hanging the test run."""
    store_path = tmp_path / "cio_wake_jobs.jsonl"
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(REPO)!r})
        from pathlib import Path
        from scripts.lib.cio_wake_jobs import CIOWakeJobStore
        p = Path({str(store_path)!r})
        s = CIOWakeJobStore(event_store_path=p)
        payload = lambda n: {{"wake_job_id": f"wake_test_{{n}}", "trigger_type": "EVENT_BUS",
            "trigger_ref": f"ev{{n}}", "trigger_hash": f"h{{n}}", "reason_codes": ["EVENT_BUS"],
            "required_domains": ["portfolio"], "wake_intent": "NEW_RUN",
            "idempotency_key": f"wake_test_{{n}}", "context": {{"target_agent": "alex"}}}}
        s.enqueue(payload(1), actor_id="t", actor_type="system", authority="READ_ONLY_ADVISORY")
        with p.open("a", encoding="utf-8") as fh:
            fh.write({TORN!r})
        s.enqueue(payload(2), actor_id="t", actor_type="system", authority="READ_ONLY_ADVISORY")
        assert s.get_wake_job("wake_test_2") is not None
        print("ENQUEUED")
        """
    )
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30, cwd=REPO)
    except subprocess.TimeoutExpired:
        pytest.fail("enqueue after a torn tail hung: _append_event re-took its own flock (2026-10-30 wake stall)")
    assert proc.returncode == 0, proc.stderr
    assert "ENQUEUED" in proc.stdout
    assert _bad_lines(store_path) == 0
    quarantines = sorted(tmp_path.glob("cio_wake_jobs.jsonl.corrupt-tail-*"))
    assert len(quarantines) == 1
    assert quarantines[0].read_text(encoding="utf-8") == TORN


def test_trim_truncates_in_place_without_a_second_copy(tmp_path: Path) -> None:
    path = tmp_path / "cio_wake_jobs.jsonl"
    store = CIOWakeJobStore(event_store_path=path)
    _enqueue(store, 1)
    inode = path.stat().st_ino
    with path.open("a", encoding="utf-8") as fh:
        fh.write(TORN)
    result = store.quarantine_corrupt_trailing_events()
    assert result["ok"] is True and result["removed"] == 1
    assert result["bytes_removed"] == len(TORN)
    assert path.stat().st_ino == inode, "trim must not rewrite the store through a full second copy"
    assert _bad_lines(path) == 0
    assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob("*.partial"))


def test_full_disk_leaves_no_empty_quarantine_and_store_untouched(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "cio_wake_jobs.jsonl"
    store = CIOWakeJobStore(event_store_path=path)
    _enqueue(store, 1)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(TORN)
    before = path.read_bytes()

    def enospc(target: Path, data: bytes) -> None:
        target.write_bytes(b"")  # the file gets created, then the disk is full
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(cio_wake_jobs, "_write_durable", enospc)
    result = store.quarantine_corrupt_trailing_events()
    assert result["ok"] is False and result["removed"] == 0
    assert result["reason"] == f"quarantine_write_failed:{errno.ENOSPC}"
    assert list(tmp_path.glob("cio_wake_jobs.jsonl.corrupt-tail-*")) == []
    assert path.read_bytes() == before


def test_untrimmable_torn_tail_does_not_swallow_the_next_event(tmp_path: Path, monkeypatch) -> None:
    """If the trim cannot run (full disk), the next append still lands on its own line."""
    path = tmp_path / "cio_wake_jobs.jsonl"
    store = CIOWakeJobStore(event_store_path=path)
    _enqueue(store, 1)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(TORN)

    def enospc(target: Path, data: bytes) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(cio_wake_jobs, "_write_durable", enospc)
    with _must_finish_within(20):
        _enqueue(store, 2)
    assert store.get_wake_job("wake_test_2") is not None
    lines = [ln for ln in path.read_bytes().splitlines() if ln.strip()]
    assert lines[-2] == TORN.encode()  # kept in place for forensics, isolated
    assert _bad_lines(path) == 1
    last = json.loads(lines[-1])
    assert last["payload"]["wake_job_id"] == "wake_test_2"


def test_clean_store_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "cio_wake_jobs.jsonl"
    store = CIOWakeJobStore(event_store_path=path)
    _enqueue(store, 1)
    before = path.read_bytes()
    assert store.quarantine_corrupt_trailing_events() == {"ok": True, "removed": 0, "reason": "clean"}
    assert path.read_bytes() == before
