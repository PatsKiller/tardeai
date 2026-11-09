"""LQ-20261107-1634 — the InstrumentRecord store is one object per path, and a read catches up
from the append tail instead of re-parsing the whole file.

Measured defect (2026-11-09, read-only on the live release): ``/api/v2/overview`` spent 7.36 of
its 8.49 s in ``cio_company_facts.load_snapshot`` → ``InstrumentRecordStore.all()``, which
re-parsed the canonical 805,710,421-byte / 86,558-line append-only store (89,220 ``json.loads``)
into a 5,680-subject projection, 6.76 s warm and 18.3 s cold. Two halves made that repeat:

* ``_store_for_root()`` constructed a new ``InstrumentRecordStore`` on every call, so
  ``_scan_end``/``_cache``/``_disk_hashes`` never survived a call and every caller started cold;
* ``_load()`` returned ``self._cache`` immediately once populated, so even one long-lived object
  would have served a stale projection — the incremental scanner existed but only the write path
  used it.

The store is append-hot (the canonical file gained 139,046 bytes in 6 m 15 s), so every append
changed the file signature and forced a full re-parse: that is the heap ratchet and the 21 s
first-burst latency after each rebuild.

Fail-before: a second ``all()`` on the same object does not see an appended row, ``_store_for_root``
returns two different objects for one path, and an append is never absorbed from the tail.
Pass-after: all three hold, and freshness is not traded away — truncation, replacement, an
in-place same-length rewrite, a half-written final line and the stale-write guard each keep a test.
Hermetic: tmp dirs only, no DB, no network.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import cio_instrument_record as ir  # noqa: E402
from scripts.lib.cio_instrument_record import (  # noqa: E402
    DEFAULT_PATH,
    InstrumentRecordStore,
    StaleInstrumentRecordWrite,
    _store_for_root,
)


def _row(key: str, **extra) -> dict:
    return {"subject_key": key, "schema": ir.SCHEMA, "authority": ir.AUTHORITY, **extra}


def _path(root: Path) -> Path:
    p = root / DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _append(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


# ── the object is reused per path ────────────────────────────────────────────────────────────────

def test_the_resolver_returns_one_store_per_path(tmp_path):
    """Fail-before: a fresh object per call is what threw the append index away."""
    first = _store_for_root(tmp_path)
    second = _store_for_root(tmp_path)
    assert first is second
    assert first.path == _path(tmp_path).resolve()
    other = _store_for_root(tmp_path / "other")
    assert other is not first, "two roots never share a projection"


# ── a read catches up from the tail ──────────────────────────────────────────────────────────────

def test_a_reused_store_serves_rows_appended_after_its_first_read(tmp_path):
    """Fail-before: the same object returned its cached projection forever (0.0002 s, stale)."""
    path = _path(tmp_path)
    _write(path, [_row("HELD:AAA", n=1)])
    store = _store_for_root(tmp_path)
    assert [r["subject_key"] for r in store.all()] == ["HELD:AAA"]
    _append(path, [_row("WATCH:BBB", n=1), _row("HELD:AAA", n=2)])
    rows = {r["subject_key"]: r for r in store.all()}
    assert set(rows) == {"HELD:AAA", "WATCH:BBB"}
    assert rows["HELD:AAA"]["n"] == 2, "the projection is the last row per subject, refreshed"


def test_an_append_is_absorbed_from_the_tail_not_reparsed(tmp_path):
    """The whole point: the second read must not be a second full parse."""
    path = _path(tmp_path)
    _write(path, [_row(f"HELD:S{i:03d}", n=i) for i in range(50)])
    store = InstrumentRecordStore(path)
    assert len(store.all()) == 50
    assert store._full_parses == 1
    assert store._tail_lines_parsed == 0
    _append(path, [_row("WATCH:NEW", n=1), _row("HELD:S000", n=99), _row("WATCH:NEW2", n=2)])
    rows = {r["subject_key"]: r for r in store.all()}
    assert len(rows) == 52
    assert rows["HELD:S000"]["n"] == 99 and "WATCH:NEW2" in rows
    assert store._full_parses == 1, "an append must not cost a full parse"
    assert store._tail_lines_parsed == 3, "exactly the appended lines"


def test_many_appends_still_match_a_fresh_parse(tmp_path):
    path = _path(tmp_path)
    _write(path, [_row("HELD:A", n=0)])
    store = _store_for_root(tmp_path)
    store.all()
    for i in range(1, 21):
        _append(path, [_row(f"WATCH:{i}", n=i), _row("HELD:A", n=i)])
        served = {r["subject_key"]: r for r in store.all()}
        fresh = {r["subject_key"]: r for r in InstrumentRecordStore(path).all()}
        assert served == fresh, f"projection drifted from a fresh parse after append {i}"
    assert store._full_parses == 1


def test_a_half_written_final_line_waits_for_the_next_read(tmp_path):
    path = _path(tmp_path)
    _write(path, [_row("HELD:A")])
    store = InstrumentRecordStore(path)
    assert [r["subject_key"] for r in store.all()] == ["HELD:A"]
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"subject_key": "WATCH:PART"')          # no newline: a write in flight
    assert [r["subject_key"] for r in store.all()] == ["HELD:A"]
    with path.open("a", encoding="utf-8") as fh:
        fh.write(', "n": 1}\n')                            # completed
    assert {r["subject_key"] for r in store.all()} == {"HELD:A", "WATCH:PART"}


# ── freshness is not traded away ────────────────────────────────────────────────────────────────

def test_a_truncated_store_is_re_read_in_full(tmp_path):
    path = _path(tmp_path)
    _write(path, [_row("HELD:A"), _row("WATCH:B")])
    store = InstrumentRecordStore(path)
    assert len(store.all()) == 2
    _write(path, [_row("SECTOR:X")])                        # shorter: a tail cannot catch this up
    assert [r["subject_key"] for r in store.all()] == ["SECTOR:X"]


def test_a_replaced_file_at_the_same_length_is_re_read(tmp_path):
    path = _path(tmp_path)
    first = [_row("HELD:AAA")]
    second = [_row("WATCH:BB")]
    assert len(json.dumps(first[0], sort_keys=True)) == len(json.dumps(second[0], sort_keys=True))
    _write(path, first)
    store = InstrumentRecordStore(path)
    assert [r["subject_key"] for r in store.all()] == ["HELD:AAA"]
    path.unlink()
    _write(path, second)                                   # new inode, same size
    assert [r["subject_key"] for r in store.all()] == ["WATCH:BB"]


def test_a_rewrite_in_place_at_the_same_length_is_re_read(tmp_path):
    path = _path(tmp_path)
    first = [_row("HELD:AAA")]
    second = [_row("WATCH:BB")]
    assert len(json.dumps(first[0], sort_keys=True)) == len(json.dumps(second[0], sort_keys=True))
    _write(path, first)
    store = InstrumentRecordStore(path)
    assert [r["subject_key"] for r in store.all()] == ["HELD:AAA"]
    time.sleep(0.01)                                       # a distinct mtime, not a filesystem tick
    _write(path, second)                                   # same inode and size, new mtime
    assert [r["subject_key"] for r in store.all()] == ["WATCH:BB"]


def test_the_returned_rows_are_copies(tmp_path):
    """One caller mutating a row before upsert must not rewrite the shared projection."""
    path = _path(tmp_path)
    _write(path, [_row("HELD:AAA", n=1)])
    store = _store_for_root(tmp_path)
    served = store.all()[0]
    served["n"] = 999
    assert store.load("HELD:AAA")["n"] == 1
    loaded = store.load("HELD:AAA")
    loaded["n"] = 998
    assert store.load("HELD:AAA")["n"] == 1


# ── the stale-write guard keeps its shape ───────────────────────────────────────────────────────

def test_the_guard_still_fires_when_another_writer_changed_the_tip(tmp_path):
    path = _path(tmp_path)
    _write(path, [_row("HELD:AAA", n=1)])
    mine = _store_for_root(tmp_path)
    observed = mine.load("HELD:AAA")
    assert observed["n"] == 1
    InstrumentRecordStore(path).upsert(_row("HELD:AAA", n=2))   # another writer moves the tip
    observed["n"] = 3
    with pytest.raises(StaleInstrumentRecordWrite):
        mine.upsert(observed)


def test_a_writer_that_read_the_new_tip_is_not_told_it_is_stale(tmp_path):
    path = _path(tmp_path)
    _write(path, [_row("HELD:AAA", n=1)])
    store = _store_for_root(tmp_path)
    store.load("HELD:AAA")
    InstrumentRecordStore(path).upsert(_row("HELD:AAA", n=2))
    fresh = store.load("HELD:AAA")                             # a read: the projection refreshes
    assert fresh["n"] == 2
    fresh["n"] = 3
    stored = store.upsert(fresh)
    assert stored["n"] == 3
    assert any(r["subject_key"] == "HELD:AAA" and r["n"] == 3 for r in store.all())


def test_the_writers_own_append_is_visible_to_the_next_read_without_a_parse(tmp_path):
    path = _path(tmp_path)
    _write(path, [_row("HELD:AAA", n=1)])
    store = _store_for_root(tmp_path)
    store.all()
    store.upsert(_row("HELD:AAA", n=2))
    rows = [r for r in store.all() if r["subject_key"] == "HELD:AAA"]
    assert rows and rows[0]["n"] == 2
    assert store._full_parses == 1


# ── shared by threads ───────────────────────────────────────────────────────────────────────────

def test_concurrent_readers_never_see_a_torn_projection(tmp_path):
    path = _path(tmp_path)
    _write(path, [_row(f"HELD:S{i:03d}", n=0) for i in range(30)])
    store = _store_for_root(tmp_path)
    store.all()
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                assert len(store.all()) >= 30
        except BaseException as exc:  # noqa: BLE001 — the assertion detail is the evidence
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for i in range(30):
            _append(path, [_row(f"WATCH:T{i:03d}", n=i)])
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=10)
    assert not errors, errors
    assert len(store.all()) == 60
