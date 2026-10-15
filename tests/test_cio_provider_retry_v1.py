from __future__ import annotations

import json

from scripts.lib.cio_provider_retry_v1 import (
    AMBIGUOUS_PROVIDER_RESULT,
    NON_RETRYABLE_COST,
    NON_RETRYABLE_POLICY,
    NON_RETRYABLE_VALIDATION,
    RETRYABLE_TRANSIENT,
    ProviderRequestJournal,
    classify_failure,
    semantic_request_key,
)


def test_retry_taxonomy_is_bounded_and_hard_failures_do_not_retry() -> None:
    transient = classify_failure("HTTP_503", http_status=503)
    assert transient["disposition"] == RETRYABLE_TRANSIENT
    assert transient["max_attempts"] == 3
    assert transient["maximum_interval_seconds"] == 30
    assert classify_failure("COST_CAP_EXCEEDED")["disposition"] == NON_RETRYABLE_COST
    assert classify_failure("POLICY_NOT_ALLOWED")["disposition"] == NON_RETRYABLE_POLICY
    assert classify_failure("MODEL_MISMATCH")["disposition"] == NON_RETRYABLE_VALIDATION


def test_sent_request_is_ambiguous_even_for_http_500() -> None:
    result = classify_failure("HTTP_500", request_sent=True, http_status=500)
    assert result["disposition"] == AMBIGUOUS_PROVIDER_RESULT
    assert result["retryable"] is False
    assert result["requires_explicit_resolution"] is True


def test_semantic_key_is_stable_and_does_not_expose_request_id() -> None:
    one = semantic_request_key(request_id="operator-visible-id", process_id="alex", model_id="m")
    two = semantic_request_key(request_id="operator-visible-id", process_id="alex", model_id="m")
    assert one == two
    assert "operator-visible-id" not in one


def test_journal_blocks_dispatched_and_completed_requests(tmp_path) -> None:
    journal = ProviderRequestJournal(tmp_path / "requests.jsonl")
    key = semantic_request_key(request_id="req-1", process_id="alex", model_id="model")
    first = journal.reserve(
        semantic_key=key,
        request_id="req-1",
        process_id="alex",
        provider="deepseek",
        model_id="model",
        task="cio_synthesis",
        projected_cost_usd=0.01,
    )
    assert first["allowed"] is True
    journal.record(key, state="DISPATCHED")
    duplicate = journal.reserve(
        semantic_key=key,
        request_id="req-1",
        process_id="alex",
        provider="deepseek",
        model_id="model",
        task="cio_synthesis",
        projected_cost_usd=0.01,
    )
    assert duplicate["allowed"] is False
    journal.record(key, state="COMPLETED", result_hash="abc", actual_cost_usd=0.001)
    assert journal.latest(key)["state"] == "COMPLETED"


def test_retryable_record_allows_next_attempt_but_caps_at_three(tmp_path) -> None:
    journal = ProviderRequestJournal(tmp_path / "requests.jsonl")
    key = "prj_retry"
    for attempt in range(1, 4):
        result = journal.reserve(
            semantic_key=key,
            request_id="req",
            process_id="alex",
            provider="deepseek",
            model_id="model",
            task="cio_synthesis",
            projected_cost_usd=0.01,
        )
        assert result["allowed"] is True
        assert result["current"]["attempt"] == attempt
        journal.record(key, state="RETRYABLE", retry_disposition=RETRYABLE_TRANSIENT)
    blocked = journal.reserve(
        semantic_key=key,
        request_id="req",
        process_id="alex",
        provider="deepseek",
        model_id="model",
        task="cio_synthesis",
        projected_cost_usd=0.01,
    )
    assert blocked["allowed"] is False
    assert blocked["reason"] == "ATTEMPTS_EXHAUSTED"
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert all("prompt" not in row and "response" not in row for row in rows)


# ── 2026-10-15: bounded latest(), locked record(), rotation (bridge OOM) ─────────────────────────
import gzip  # noqa: E402
import multiprocessing  # noqa: E402
import random  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import tracemalloc  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import scripts.lib.cio_provider_retry_v1 as retry_mod  # noqa: E402
from scripts import cio_provider_journal_rotate as rotate_mod  # noqa: E402


def _row(key: str, state: str, ts: datetime, attempt: int = 1, **extra) -> dict:
    return {
        "schema": "ProviderRequestJournal@v1",
        "event": f"REQUEST_{state}",
        "state": state,
        "recorded_at": ts.isoformat(),
        "semantic_key": key,
        "request_id": f"rid-{key}",
        "process_id": "alex",
        "provider": "deepseek",
        "model_id": "m",
        "task": "t",
        "attempt": attempt,
        "authority": "READ_ONLY_ADVISORY",
        **extra,
    }


def _write(path: Path, rows: list, *, tail: bytes = b"") -> None:
    with path.open("wb") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        fh.write(tail)


def _reference_latest(path: Path, key: str):
    """The pre-2026-10-15 whole-file implementation, kept as the oracle."""
    out = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("semantic_key") == key:
            out = row
    return out


def test_latest_peak_memory_is_bounded_on_150k_row_journal(tmp_path) -> None:
    path = tmp_path / "big.jsonl"
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    with path.open("w", encoding="utf-8") as fh:
        for i in range(150_000):
            r = _row(f"prj_{i // 4:064x}", "COMPLETED", t0 + timedelta(seconds=i), pad="x" * 200)
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    assert path.stat().st_size > 60_000_000
    journal = ProviderRequestJournal(path)
    for key, found in ((f"prj_{0:064x}", True), (f"prj_{37_499:064x}", True), ("prj_absent", False)):
        tracemalloc.start()
        try:
            got = journal.latest(key)
            _cur, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert (got is not None) is found
        assert peak < 20_000_000, f"latest({key[:12]}) peaked at {peak / 1e6:.1f} MB"


def test_latest_matches_reference_with_interleaved_and_duplicate_keys(tmp_path) -> None:
    rng = random.Random(1015)
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    keys = [f"prj_{i:04d}" for i in range(40)]
    rows = []
    for i in range(3000):
        key = rng.choice(keys)
        rows.append(
            _row(
                key,
                rng.choice(["RESERVED", "DISPATCHED", "RETRYABLE", "COMPLETED"]),
                t0 + timedelta(seconds=i),
                attempt=rng.randint(1, 3),
                seq=i,
            )
        )
    # a row that MENTIONS a key in another field must not be returned for it
    rows.append(_row("prj_other", "COMPLETED", t0, note="see prj_0003"))
    path = tmp_path / "j.jsonl"
    _write(path, rows)
    journal = ProviderRequestJournal(path)
    # tiny chunks force every chunk-boundary / carry path
    for chunk in (7, 64, 333, 1 << 20):
        for key in keys + ["prj_missing", "prj_0003"]:
            with path.open("rb") as fh:
                got = retry_mod._scan_latest(fh, path.stat().st_size, key, chunk_bytes=chunk)
            assert got == _reference_latest(path, key), (chunk, key)
    assert journal.latest("prj_0003")["semantic_key"] == "prj_0003"


def test_latest_skips_torn_last_line_and_garbage(tmp_path) -> None:
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    path = tmp_path / "j.jsonl"
    torn = json.dumps(_row("prj_a", "COMPLETED", t0)).encode()[:-15]
    _write(
        path, [_row("prj_a", "RESERVED", t0), _row("prj_b", "RESERVED", t0)], tail=b'not json prj_a\n["prj_a"]\n' + torn
    )
    assert ProviderRequestJournal(path).latest("prj_a")["state"] == "RESERVED"
    assert _reference_latest(path, "prj_a")["state"] == "RESERVED"
    # an over-long corrupt line is skipped without buffering it, and older rows are still found
    with path.open("ab") as fh:
        fh.write(b"\n" + b"z" * 5000 + b"prj_a" + b"z" * 5000 + b"\n")
        fh.write(json.dumps(_row("prj_b", "COMPLETED", t0)).encode() + b"\n")
    with path.open("rb") as fh:
        got = retry_mod._scan_latest(fh, path.stat().st_size, "prj_a", chunk_bytes=512, max_line_bytes=1024)
    assert got["state"] == "RESERVED"
    assert ProviderRequestJournal(tmp_path / "absent.jsonl").latest("prj_a") is None


def test_latest_is_consistent_under_concurrent_appends(tmp_path) -> None:
    path = tmp_path / "j.jsonl"
    journal = ProviderRequestJournal(path)
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _write(path, [_row(f"prj_{i}", "COMPLETED", t0) for i in range(2000)])
    stop = threading.Event()
    errors: list = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            with path.open("a", encoding="utf-8") as fh:  # deliberately unlocked: a raw appender
                fh.write(json.dumps(_row("prj_hot", "RETRYABLE", t0, seq=i)) + "\n")
            i += 1

    th = threading.Thread(target=writer)
    th.start()
    try:
        seen = -1
        for _ in range(200):
            got = journal.latest("prj_hot")
            if got is not None:
                if got["seq"] < seen:
                    errors.append((got["seq"], seen))
                seen = got["seq"]
            assert journal.latest("prj_7")["semantic_key"] == "prj_7"
    finally:
        stop.set()
        th.join()
    assert not errors, "latest() went backwards under concurrent appends"


def test_record_takes_the_journal_lock(tmp_path, monkeypatch) -> None:
    journal = ProviderRequestJournal(tmp_path / "j.jsonl")
    journal.reserve(
        semantic_key="prj_l",
        request_id="r",
        process_id="p",
        provider="x",
        model_id="m",
        task="t",
        projected_cost_usd=None,
    )
    calls: list = []
    real_latest = ProviderRequestJournal.latest

    def spy(self, key):
        # the lock must already be held when record() reads the current row
        import fcntl as _f

        with self.lock_path.open("a+") as other:
            try:
                _f.flock(other.fileno(), _f.LOCK_EX | _f.LOCK_NB)
                calls.append("UNLOCKED")
                _f.flock(other.fileno(), _f.LOCK_UN)
            except BlockingIOError:
                calls.append("LOCKED")
        return real_latest(self, key)

    monkeypatch.setattr(ProviderRequestJournal, "latest", spy)
    journal.record("prj_l", state="DISPATCHED")
    assert calls == ["LOCKED"]


def _hold_lock(lock_path: str, ready, release) -> None:
    import fcntl as _f

    with open(lock_path, "a+") as fh:
        _f.flock(fh.fileno(), _f.LOCK_EX)
        ready.set()
        release.wait(10)
        _f.flock(fh.fileno(), _f.LOCK_UN)


def test_record_blocks_while_another_process_holds_the_lock(tmp_path) -> None:
    journal = ProviderRequestJournal(tmp_path / "j.jsonl")
    journal.reserve(
        semantic_key="prj_p",
        request_id="r",
        process_id="p",
        provider="x",
        model_id="m",
        task="t",
        projected_cost_usd=None,
    )
    ctx = multiprocessing.get_context("fork")
    ready, release = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=_hold_lock, args=(str(journal.lock_path), ready, release))
    proc.start()
    try:
        assert ready.wait(10)
        done = threading.Event()
        th = threading.Thread(target=lambda: (journal.record("prj_p", state="DISPATCHED"), done.set()))
        th.start()
        time.sleep(0.3)
        assert not done.is_set(), "record() appended while another process held the journal lock"
        release.set()
        th.join(10)
        assert done.is_set()
    finally:
        release.set()
        proc.join(10)
    assert journal.latest("prj_p")["state"] == "DISPATCHED"


def _rotation_fixture(tmp_path: Path):
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    old, recent = now - timedelta(days=45), now - timedelta(days=2)
    rows = [
        _row("prj_old_done", "RESERVED", old),
        _row("prj_old_done", "COMPLETED", old),
        _row("prj_old_amb", "RESERVED", old),
        _row("prj_old_amb", "AMBIGUOUS", old),
        # old first rows, recent newest row: the whole key stays (attempt count preserved)
        _row("prj_mixed", "RESERVED", old, attempt=1),
        _row("prj_mixed", "RETRYABLE", old, attempt=1),
        _row("prj_mixed", "RESERVED", recent, attempt=2),
        _row("prj_mixed", "RETRYABLE", recent, attempt=2),
        _row("prj_new", "COMPLETED", recent),
        {"schema": "x", "note": "no key, no ts"},
    ]
    path = tmp_path / "data" / "cio" / "provider_request_journal.jsonl"
    path.parent.mkdir(parents=True)
    _write(path, rows, tail=b"{torn\n")
    return path, now


def _run_rotation(path: Path, now: datetime, tmp_path: Path, apply: bool) -> dict:
    return rotate_mod.rotate(
        path,
        window_days=30,
        retain_states={"AMBIGUOUS", "DISPATCHED"},
        archive_dir=tmp_path / "state" / "archive" / "file_prune" / "provider_request_journal",
        label="provider_request_journal",
        apply=apply,
        now=now,
    )


def test_rotation_dry_run_changes_nothing(tmp_path) -> None:
    path, now = _rotation_fixture(tmp_path)
    before = path.read_bytes()
    report = _run_rotation(path, now, tmp_path, apply=False)
    assert report["result"] == "DRY_RUN"
    assert report["keys_to_archive"] == 1 and report["keys_held_unresolved"] == 1
    assert report["rows_to_archive"] == 3  # prj_old_done x2 + the torn line
    assert path.read_bytes() == before
    assert not (tmp_path / "state").exists()


def test_rotation_apply_archives_never_deletes_and_preserves_idempotency(tmp_path) -> None:
    path, now = _rotation_fixture(tmp_path)
    before_lines = path.read_bytes().splitlines(keepends=True)
    journal = ProviderRequestJournal(path)
    live_keys = ["prj_old_amb", "prj_mixed", "prj_new"]
    expected = {k: journal.latest(k) for k in live_keys}

    report = _run_rotation(path, now, tmp_path, apply=True)
    assert report["result"] == "APPLIED"
    assert report["rows_archived"] == 3 and report["rows_kept"] == len(before_lines) - 3

    archive = Path(report["archive"])
    with gzip.open(archive, "rb") as fh:
        archived = fh.read().splitlines(keepends=True)
    kept = path.read_bytes().splitlines(keepends=True)
    # never delete: every original line is in exactly one of live / archive, byte-for-byte
    assert sorted(archived + kept) == sorted(before_lines)
    manifest = json.loads(Path(str(archive) + ".manifest.json").read_text())
    assert manifest["rows"] == 3 and manifest["writer"] == "cio_provider_journal_rotate"
    tripwire = [json.loads(x) for x in (archive.parent / "TRIPWIRE.jsonl").read_text().splitlines()]
    assert tripwire[-1]["archive"] == str(archive)

    # semantics: keys inside the window (and unresolved ones) answer exactly as before
    for k in live_keys:
        assert journal.latest(k) == expected[k]
    assert journal.latest("prj_old_done") is None
    amb = journal.reserve(
        semantic_key="prj_old_amb",
        request_id="r",
        process_id="p",
        provider="x",
        model_id="m",
        task="t",
        projected_cost_usd=None,
    )
    assert amb["allowed"] is False  # AMBIGUOUS still blocks after rotation
    mixed = journal.reserve(
        semantic_key="prj_mixed",
        request_id="r",
        process_id="p",
        provider="x",
        model_id="m",
        task="t",
        projected_cost_usd=None,
    )
    assert mixed["allowed"] is True and mixed["current"]["attempt"] == 3  # attempt count carried over

    # a second run is a no-op
    again = _run_rotation(path, now + timedelta(seconds=1), tmp_path, apply=True)
    assert again["result"] == "NOTHING_TO_ARCHIVE"


def test_rotation_cli_refuses_window_below_minimum_and_dry_runs_by_default(tmp_path) -> None:
    path, _now = _rotation_fixture(tmp_path)
    before = path.read_bytes()
    rc = rotate_mod.main(["--journal", str(path), "--window-days", "3", "--archive-dir", str(tmp_path / "a")])
    assert rc == 2
    rc = rotate_mod.main(["--journal", str(path), "--archive-dir", str(tmp_path / "a"), "--json"])
    assert rc == 0 and not (tmp_path / "a").exists()
    assert path.read_bytes() == before
