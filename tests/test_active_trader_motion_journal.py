#!/usr/bin/env python3
"""Persistent shadow observation journal: append-only + latest/age semantics."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader import motion_journal as mj  # noqa: E402

NOW = 1_753_700_000.0


def _snap(generated_at: float, tag: str) -> dict:
    return {"contract": "active-trader-motion-snapshot-v1", "generated_at": generated_at, "tag": tag}


def test_absent_journal_is_honest_none(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    assert mj.latest_snapshot(path=p) is None
    assert mj.snapshot_age_seconds(now=NOW, path=p) is None


def test_append_is_append_only_and_latest_wins(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    mj.append_snapshot(_snap(NOW, "a"), path=p)
    mj.append_snapshot(_snap(NOW + 1, "b"), path=p)
    mj.append_snapshot(_snap(NOW + 2, "c"), path=p)

    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # every append added exactly one line
    # earlier lines are preserved verbatim (append never rewrites history)
    assert json.loads(lines[0])["tag"] == "a"
    assert json.loads(lines[1])["tag"] == "b"

    latest = mj.latest_snapshot(path=p)
    assert latest["tag"] == "c"
    assert latest["generated_at"] == NOW + 2


def test_snapshot_age_seconds(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    mj.append_snapshot(_snap(NOW, "a"), path=p)
    age = mj.snapshot_age_seconds(now=NOW + 12.5, path=p)
    assert age == 12.5
    # never negative even if clock skews backward
    assert mj.snapshot_age_seconds(now=NOW - 5, path=p) == 0.0


def test_tolerates_corrupt_trailing_line(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    mj.append_snapshot(_snap(NOW, "good"), path=p)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    latest = mj.latest_snapshot(path=p)
    assert latest is not None and latest["tag"] == "good"


def test_prune_keeps_bounded_tail(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    for i in range(10):
        mj.append_snapshot(_snap(NOW + i, f"n{i}"), path=p)
    mj.prune_journal(3, path=p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[-1])["tag"] == "n9"
    assert mj.latest_snapshot(path=p)["tag"] == "n9"


def test_append_with_max_lines_rotates(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    for i in range(6):
        mj.append_snapshot(_snap(NOW + i, f"n{i}"), path=p, max_lines=2)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1])["tag"] == "n5"


def test_rejects_non_finite(tmp_path):
    p = tmp_path / "motion_journal.jsonl"
    import pytest

    with pytest.raises(ValueError):
        mj.append_snapshot({"generated_at": float("inf")}, path=p)
