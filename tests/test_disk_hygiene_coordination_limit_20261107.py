"""LQ-20261107-41: a live coordination tree past the old 128 MiB cap refused every standing run (2026-11-07)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts import disk_hygiene as DH

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def _coord(tmp_path):
    base = tmp_path / "coordination"
    for d in ("claims", "worklogs", "handoffs", "coordinator/inbox/a"):
        (base / d).mkdir(parents=True)
    (base / "handoffs" / "PROGRESS_LOG.md").write_text("progress log\n")
    return base


def test_a_40_mib_live_note_and_a_tree_past_128_mib_still_scan(tmp_path):
    base = _coord(tmp_path)
    inbox = base / "coordinator" / "inbox" / "a"
    for i in range(4):  # 4 x 40 MiB = 160 MiB live: the old per-file (32) and total (128) caps both refused this
        (inbox / f"note{i}.json").write_bytes(b" " * (40 * 1024 * 1024))
    out = DH.scan_coordination(base, NOW)
    assert out["live_claims"] == []


def test_scan_still_fails_closed_past_the_new_caps(tmp_path, monkeypatch):
    base = _coord(tmp_path)
    (base / "coordinator" / "inbox" / "a" / "big.md").write_bytes(b" " * 4096)
    monkeypatch.setattr(DH, "COORD_MAX_FILE_BYTES", 1024)
    with pytest.raises(ValueError, match="coordination_scan_limit"):
        DH.scan_coordination(base, NOW)
    monkeypatch.setattr(DH, "COORD_MAX_FILE_BYTES", 10**9)
    monkeypatch.setattr(DH, "COORD_MAX_TOTAL_BYTES", 2048)
    with pytest.raises(ValueError, match="coordination_scan_limit"):
        DH.scan_coordination(base, NOW)


def test_caps_hold_the_live_tree_size_seen_on_2026_11_07():
    assert DH.COORD_MAX_TOTAL_BYTES >= 3 * 145_600_000 and DH.COORD_MAX_FILE_BYTES >= 2 * 30_200_000


def test_activity_counts_syscalls_per_entry_and_keeps_symlinks_unfollowed(tmp_path, monkeypatch):
    """activity() makes one lstat per entry (was lstat + is_dir + is_symlink) and still never follows a symlink."""
    from pathlib import Path

    from scripts.lib import disk_hygiene_retention as R

    root = tmp_path / "scratch"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "f").write_text("x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "newer").write_text("y")
    (root / "link").symlink_to(outside)
    calls = {"is_dir": 0, "is_symlink": 0}
    for name in calls:
        orig = getattr(Path, name)

        def counted(self, *a, _n=name, _o=orig, **k):
            calls[_n] += 1
            return _o(self, *a, **k)

        monkeypatch.setattr(Path, name, counted)
    newest, why = R.activity(root)
    assert why is None and newest is not None
    assert newest < (outside / "newer").stat().st_mtime + 1  # the link target's file was not walked into
    assert calls == {"is_dir": 0, "is_symlink": 0}
