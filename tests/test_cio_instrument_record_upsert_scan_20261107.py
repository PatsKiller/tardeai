"""The canonical InstrumentRecord write must not re-read the whole store per row.

Found 2026-11-07 from the live scheduler: `cio-opportunity-curator` had produced
no receipt since 2026-10-28. Its assessments and projection were still written
every 30 minutes (16:30:32Z on 2026-11-06), so the run reached
`write_cio_prospects`, then spent the rest of its `timeout 600` re-parsing the
421 MB `data/cio/cio_instrument_records.jsonl` once per prospect, and was killed
before the receipt (written last) could land.

`InstrumentRecordStore.upsert` scanned the whole file for the tip of one key.
These tests pin the replacement: an append-only index that reads only the bytes
appended since this store last read the file, while keeping the
StaleInstrumentRecordWrite contract intact.
"""
import json

import pytest

from scripts.lib.cio_instrument_record import (InstrumentRecordStore,
                                               StaleInstrumentRecordWrite)


def _store(tmp_path, rows=0):
    path = tmp_path / "cio_instrument_records.jsonl"
    if rows:
        with open(path, "w", encoding="utf-8") as fh:
            for i in range(rows):
                fh.write(json.dumps({"subject_key": f"WATCH:S{i}", "kind": "WATCH", "mark": i}) + "\n")
    return InstrumentRecordStore(path), path


def test_upsert_appends_and_the_projection_advances(tmp_path):
    store, path = _store(tmp_path)
    store.upsert({"subject_key": "WATCH:SPCX", "kind": "WATCH", "mark": 1})
    store.upsert({"subject_key": "WATCH:SPCX", "kind": "WATCH", "mark": 2})

    assert store.load("WATCH:SPCX")["mark"] == 2
    assert [r["mark"] for r in store.history("WATCH:SPCX")] == [1, 2]
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_a_batch_of_writes_reads_only_what_it_appended(tmp_path):
    """The regression: 200 rows already stored, 50 writes, not 50 full scans."""
    store, _ = _store(tmp_path, rows=200)
    store._load()                                   # the one legitimate full read
    assert store._tail_lines_parsed == 0            # the index starts at the tip

    for i in range(50):
        store.upsert({"subject_key": f"WATCH:N{i}", "kind": "WATCH", "mark": i})

    assert store.load("WATCH:N49")["mark"] == 49
    # Each write appends exactly one line and absorbs nothing else: the scan cost
    # is proportional to what changed, never to the size of the store.
    assert store._tail_lines_parsed == 0


def test_a_write_after_a_cold_store_absorbs_the_file_exactly_once(tmp_path):
    store, _ = _store(tmp_path, rows=20)
    store.upsert({"subject_key": "WATCH:SPCX", "kind": "WATCH", "mark": 1})
    assert store._tail_lines_parsed == 0            # upsert() loads first, at the tip
    cold = InstrumentRecordStore(store.path)        # never read the file
    cold.upsert({"subject_key": "WATCH:SPCX", "kind": "WATCH", "mark": 2})
    assert cold._tail_lines_parsed == 0             # its own _load() already covered the file
    assert cold._scan_end == store.path.stat().st_size


def test_a_tip_changed_by_another_writer_is_still_refused(tmp_path):
    store, path = _store(tmp_path)
    store.upsert({"subject_key": "WATCH:SPCX", "kind": "WATCH", "mark": 1})
    observed = store.load("WATCH:SPCX")

    other = InstrumentRecordStore(path)             # another process, same file
    other.upsert({"subject_key": "WATCH:SPCX", "kind": "WATCH", "mark": 2})

    with pytest.raises(StaleInstrumentRecordWrite):
        store.upsert(dict(observed, mark=3))        # based on the version it read
    # On disk the other writer's tip survives; the stale write is nowhere in it.
    fresh = InstrumentRecordStore(path)
    assert fresh.load("WATCH:SPCX")["mark"] == 2
    assert [r["mark"] for r in fresh.history("WATCH:SPCX")] == [1, 2]


def test_an_external_append_to_another_key_is_seen_before_it_matters(tmp_path):
    store, path = _store(tmp_path)
    store.upsert({"subject_key": "WATCH:A", "kind": "WATCH", "mark": 1})

    other = InstrumentRecordStore(path)
    other.upsert({"subject_key": "WATCH:B", "kind": "WATCH", "mark": 9})

    # A's tip is untouched by B's append, so A can still be written...
    store.upsert({"subject_key": "WATCH:A", "kind": "WATCH", "mark": 2})
    assert store.load("WATCH:A")["mark"] == 2
    # ...and the index absorbed B, so a fresh read of B sees the newer version.
    fresh = InstrumentRecordStore(path)
    assert fresh.load("WATCH:B")["mark"] == 9


def test_the_index_never_starts_mid_line(tmp_path):
    """A crash mid-append leaves a line with no newline; the index must go cold,
    not start parsing from the middle of that record."""
    store, path = _store(tmp_path, rows=2)
    store._load()
    assert store._scan_end == path.stat().st_size

    with open(path, "a", encoding="utf-8") as fh:   # a writer died mid-append
        fh.write('{"subject_key": "WATCH:PARTI')
    fresh = InstrumentRecordStore(path)
    fresh._load()
    assert fresh._scan_end == 0                     # cold index, re-read in full
    assert fresh.load("WATCH:S1")["mark"] == 1      # the complete lines still read


def test_a_truncated_store_cold_starts_instead_of_parsing_from_a_stale_offset(tmp_path):
    store, path = _store(tmp_path, rows=5)
    store._load()
    store.upsert({"subject_key": "WATCH:A", "kind": "WATCH", "mark": 1})
    path.write_text("", encoding="utf-8")           # rotation / truncation happened

    store.upsert({"subject_key": "WATCH:B", "kind": "WATCH", "mark": 2})
    assert store.load("WATCH:B")["mark"] == 2
    assert json.loads(path.read_text(encoding="utf-8").strip())["subject_key"] == "WATCH:B"
