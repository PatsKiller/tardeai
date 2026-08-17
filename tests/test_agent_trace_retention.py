"""Trace retention / rotation tests (temp directories only, no production purge)."""
from __future__ import annotations

import json
import sys
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
    assert r["removed"] == 1  # invalid dropped + old dropped = 2 dropped, 1 kept
    kept = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert [k["trace_id"] for k in kept] == ["new"]


def test_max_age_drops_stale_rows(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [
        '{"trace_id":"ancient","started_at":"2020-01-01T00:00:00Z"}',
        '{"trace_id":"recent","started_at":"2026-08-10T00:00:00Z"}',
    ])
    r = enforce_trace_retention(p, max_age_days=1, dry_run=False, allow_unlisted=True)
    kept = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert [k["trace_id"] for k in kept] == ["recent"]


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
