"""Trace retention / rotation tests (temp directories only, no production purge)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_trace_retention import (  # noqa: E402
    enforce_trace_retention,
)


def _write(path: Path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_dry_run_does_not_write(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, ['{"trace_id":"a","started_at":"2026-08-01T00:00:00Z"}',
               '{"trace_id":"b","started_at":"2026-08-02T00:00:00Z"}'])
    before = p.read_text()
    r = enforce_trace_retention(p, max_rows=1, dry_run=True, allow_unlisted=True)
    assert r["ok"] is True
    assert r["removed"] == 1
    assert r["rotated"] is False
    assert p.read_text() == before


def test_max_rows_keeps_newest_and_drops_invalid(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [
        "not valid json",
        '{"trace_id":"old","started_at":"2026-08-01T00:00:00Z"}',
        '{"trace_id":"new","started_at":"2026-08-03T00:00:00Z"}',
    ])
    r = enforce_trace_retention(p, max_rows=1, dry_run=False, allow_unlisted=True)
    assert r["ok"] is True
    # 2 physical lines were discarded: 1 invalid JSON + 1 age/row-budgeted valid.
    assert r["removed_invalid"] == 1
    assert r["removed_valid"] == 1
    assert r["removed_total"] == 2
    assert r["removed"] == 2
    kept = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert [k["trace_id"] for k in kept] == ["new"]


_NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc).timestamp()


def _iso(epoch_delta_days: float) -> str:
    return datetime.fromtimestamp(_NOW + epoch_delta_days * 86400, tz=timezone.utc).isoformat()


def test_max_age_wall_clock_drops_stale_rows(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [
        f'{{"trace_id":"fresh","started_at":"{_iso(-0.5)}"}}',
        f'{{"trace_id":"stale","started_at":"{_iso(-30)}"}}',
    ])
    r = enforce_trace_retention(p, max_age_days=1, dry_run=False, allow_unlisted=True, now=_NOW)
    kept = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert [k["trace_id"] for k in kept] == ["fresh"]


def test_entire_corpus_older_than_window_all_expired(tmp_path):
    # A file that stopped receiving traces years ago must NOT retain its
    # "newest" record forever under an active age policy.
    p = tmp_path / "t.jsonl"
    _write(p, [
        f'{{"trace_id":"old1","started_at":"{_iso(-400)}"}}',
        f'{{"trace_id":"old2","started_at":"{_iso(-300)}"}}',
    ])
    r = enforce_trace_retention(p, max_age_days=1, dry_run=False, allow_unlisted=True, now=_NOW)
    assert r["removed_valid"] == 2
    assert r["removed_total"] == 2
    assert p.read_text().strip() == ""


def test_newest_record_itself_expires(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [f'{{"trace_id":"only","started_at":"{_iso(-2)}"}}'])
    r = enforce_trace_retention(p, max_age_days=1, dry_run=False, allow_unlisted=True, now=_NOW)
    assert r["removed_valid"] == 1
    assert p.read_text().strip() == ""


def test_no_timestamp_cannot_live_forever_under_age_policy(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, ['{"trace_id":"no_ts"}'])
    r = enforce_trace_retention(p, max_age_days=1, dry_run=False, allow_unlisted=True, now=_NOW)
    assert r["removed_valid"] == 1
    assert p.read_text().strip() == ""


def test_future_dated_row_handled_safely(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [
        f'{{"trace_id":"future","started_at":"{_iso(2)}"}}',
        f'{{"trace_id":"now","started_at":"{_iso(0)}"}}',
    ])
    r = enforce_trace_retention(p, max_age_days=1, dry_run=False, allow_unlisted=True, now=_NOW)
    kept = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert {k["trace_id"] for k in kept} == {"future", "now"}


def test_dry_run_still_no_write_with_accounting(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, ["bad json", f'{{"trace_id":"stale","started_at":"{_iso(-30)}"}}'])
    before = p.read_text()
    r = enforce_trace_retention(p, max_age_days=1, dry_run=True, allow_unlisted=True, now=_NOW)
    assert r["ok"] is True
    assert r["removed_invalid"] == 1
    assert r["removed_valid"] == 1
    assert r["removed_total"] == 2
    assert p.read_text() == before


def test_rotation_is_atomic_and_preserves_newest(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [
        '{"trace_id":"a","started_at":"2026-08-01T00:00:00Z"}',
        '{"trace_id":"b","started_at":"2026-08-02T00:00:00Z"}',
        '{"trace_id":"c","started_at":"2026-08-03T00:00:00Z"}',
    ])
    r = enforce_trace_retention(p, max_rows=2, dry_run=False, allow_unlisted=True)
    assert r["rotated"] is True
    assert r["removed"] == 1
    kept = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert [k["trace_id"] for k in kept] == ["c", "b"]


def test_refuses_unlisted_path_by_default(tmp_path):
    p = tmp_path / "unlisted.jsonl"
    _write(p, ['{"trace_id":"a"}'])
    r = enforce_trace_retention(p, max_rows=1, dry_run=False)
    assert r["ok"] is False
    assert r["reason"] == "not a governed trace path"
    # File untouched.
    assert p.read_text().strip() == '{"trace_id":"a"}'


def test_no_budget_no_removal(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, ['{"trace_id":"a"}', '{"trace_id":"b"}'])
    r = enforce_trace_retention(p, dry_run=False, allow_unlisted=True)
    assert r["ok"] is True
    assert r["removed"] == 0
    assert len(p.read_text().splitlines()) == 2


def test_missing_file_ok(tmp_path):
    p = tmp_path / "nope.jsonl"
    r = enforce_trace_retention(p, max_rows=1, dry_run=False, allow_unlisted=True)
    assert r["ok"] is True
    assert r["removed"] == 0
