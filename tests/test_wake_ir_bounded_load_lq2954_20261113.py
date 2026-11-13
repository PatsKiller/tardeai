"""LQ-2954: the cio wake must not hold the whole InstrumentRecord history in memory.

Synthetic fixtures only. The production file (2.96 GB, ~360k rows) drove the
hourly cio wake to 13.2 GB RSS because the selector loaded every row as a dict.
"""
from __future__ import annotations

import json
import random
import tracemalloc
from datetime import datetime, timezone

import pytest

from scripts.lib import wake_subject_selector as wss

PAD = "x" * 2000


def _row(sk: str, i: int, *, as_of: str | None = None, nxt: str | None = None) -> dict:
    r = {"subject_key": sk, "rev": i, "next_eligible_at": nxt, "pad": PAD}
    if as_of is not None:
        r["as_of"] = as_of
    return r


def _write(path, rows, tail: str = "") -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        fh.write(tail)


def _history(n_subjects: int, versions: int, seed: int = 7) -> list[dict]:
    rnd = random.Random(seed)
    rows = []
    for i in range(versions):
        for s in range(n_subjects):
            kind = ("HELD", "WATCH", "EXIT")[s % 3]
            as_of = None if s % 4 == 0 else f"2026-11-{rnd.randint(1, 12):02d}T00:00:00Z"
            rows.append(_row(f"{kind}:S{s}", i, as_of=as_of))
    rnd.shuffle(rows)
    return rows


def _env(path) -> dict:
    return {"TRADEAI_WAKE_INSTRUMENT_RECORDS_PATH": str(path)}


def test_stream_keeps_the_same_tips_as_latest_record_per_subject(tmp_path):
    rows = _history(30, 40)
    rows.append({"subject_key": "", "rev": -1})
    p = tmp_path / "ir.jsonl"
    _write(p, rows)
    got = {r["subject_key"]: r for r in wss.stream_instrument_record_tips(p)}
    want = {r["subject_key"]: r for r in wss.latest_record_per_subject(rows)}
    assert got == want
    assert len(got) == 30


def test_selection_is_unchanged_by_the_bounded_loader(tmp_path):
    now = datetime(2026, 11, 13, 14, tzinfo=timezone.utc)
    rows = []
    for i in range(5):
        rows.append(_row("HELD:AAA", i, nxt="2026-11-13T00:00:00Z" if i == 4 else "2026-12-01T00:00:00Z"))
        rows.append(_row("WATCH:BBB", i, nxt="2026-12-01T00:00:00Z" if i == 4 else "2026-11-01T00:00:00Z"))
    p = tmp_path / "ir.jsonl"
    _write(p, rows)
    guid = {"AAA": "g-aaa", "BBB": "g-bbb"}.get
    loaded = wss.load_selection_inputs(_env(p))["instrument_records"]
    a = wss.instrument_record_candidates(loaded, now=now, guid_for_symbol=guid)
    b = wss.instrument_record_candidates(rows, now=now, guid_for_symbol=guid)
    assert [c.source_id for c in a] == [c.source_id for c in b] == ["HELD:AAA"]


def test_selection_inputs_memory_is_bounded_by_subjects_not_history(tmp_path):
    # 20 subjects x 1000 versions x ~2 KB = ~40 MB of history; tips are ~40 KB.
    p = tmp_path / "ir.jsonl"
    _write(p, _history(20, 1000))
    assert p.stat().st_size > 35_000_000
    tracemalloc.start()
    try:
        out = wss.load_selection_inputs(_env(p))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(out["instrument_records"]) == 20
    # The unbounded loader peaks above the file size (the read_text string
    # plus every row as a dict). The streamed loader holds tips + one line.
    assert peak < 4_000_000, peak


def test_too_many_subjects_fails_closed_with_a_logged_error(tmp_path, capsys):
    p = tmp_path / "ir.jsonl"
    _write(p, [_row(f"WATCH:S{i}", 0) for i in range(12)])
    ro = tmp_path / "ro.jsonl"
    _write(ro, [{"subject_guid": "g1", "research_object_id": "r1"}])
    env = {**_env(p), "TRADEAI_WAKE_IR_MAX_SUBJECTS": "10",
           "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH": str(ro)}
    out = wss.load_selection_inputs(env)
    assert out["instrument_records"] == []
    assert len(out["research_objects"]) == 1  # the other sources still run
    err = capsys.readouterr().err
    assert "instrument_record_load_refused" in err and "more than 10 distinct" in err
    with pytest.raises(wss.InstrumentRecordLoadRefused):
        wss.stream_instrument_record_tips(p, max_subjects=10)


def test_retained_bytes_bound_fails_closed(tmp_path, capsys):
    p = tmp_path / "ir.jsonl"
    _write(p, [_row(f"WATCH:S{i}", 0) for i in range(10)])
    env = {**_env(p), "TRADEAI_WAKE_IR_MAX_RETAINED_BYTES": "10000"}
    assert wss.load_selection_inputs(env)["instrument_records"] == []
    assert "retained tips exceed 10000 bytes" in capsys.readouterr().err
    # Re-appending the same subjects does not grow the retained total.
    _write(p, [_row("WATCH:S0", i) for i in range(500)])
    assert len(wss.stream_instrument_record_tips(p, max_retained_bytes=10000)) == 1


def test_an_oversized_line_is_refused_before_it_is_parsed(tmp_path, capsys):
    p = tmp_path / "ir.jsonl"
    _write(p, [_row("WATCH:A", 0), {"subject_key": "WATCH:B", "pad": "y" * 50_000}])
    env = {**_env(p), "TRADEAI_WAKE_IR_MAX_LINE_BYTES": "10000"}
    assert wss.load_selection_inputs(env)["instrument_records"] == []
    assert "exceeds 10000 bytes" in capsys.readouterr().err


def test_partial_and_malformed_lines_are_skipped(tmp_path):
    p = tmp_path / "ir.jsonl"
    _write(p, [_row("WATCH:A", 0), _row("WATCH:A", 1)], tail='not json\n\n{"subject_key": "WATCH:A", "rev": 9')
    tips = wss.stream_instrument_record_tips(p)
    assert [(t["subject_key"], t["rev"]) for t in tips] == [("WATCH:A", 1)]


def test_missing_or_unset_path_is_empty(tmp_path):
    assert wss.load_instrument_record_tips(None) == []
    assert wss.load_instrument_record_tips(tmp_path / "absent.jsonl") == []
