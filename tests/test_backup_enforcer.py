"""Unit tests for backup_enforcer local cap. Dumps are archived, never unlinked."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "backup_enforcer.py"
    spec = importlib.util.spec_from_file_location("backup_enforcer", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _cfg(d: Path) -> dict:
    return {
        "dir": str(d),
        "pattern": "trade_ai_*.sql.gz",
        "max_count": 1,
        "min_bytes": 50,
        "max_total_bytes": 10_000,
        "skip_younger_than_s": 7200,
    }


def _stamp(path: Path, age_s: float, now: float, payload: bytes) -> None:
    path.write_bytes(payload)
    t = now - age_s
    os.utime(path, (t, t))


def test_enforce_local_archives_old_partial_and_keeps_newest_full(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    for i in range(5):
        _stamp(d / f"trade_ai_2026081{i}_000000.sql.gz", age_s=(5 - i) * 10_000, now=now, payload=b"x" * 60)
    partial = d / "trade_ai_partial.sql.gz"
    _stamp(partial, age_s=10_000, now=now, payload=b"tiny")
    res = be.enforce_local(_cfg(d), dry_run=False, now=now)
    assert res["remaining_full"] == 1
    assert res["remaining_count"] == 1
    assert not partial.exists()
    archived = list((d / "archive").glob("trade_ai_*.sql.gz"))
    assert partial.name in {p.name for p in archived}
    remaining = list(d.glob("trade_ai_*.sql.gz"))
    assert [p.name for p in remaining] == ["trade_ai_20260814_000000.sql.gz"]
    assert (d / "archive" / "TRIPWIRE.txt").is_file()


def test_young_and_part_dumps_are_not_archived(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    growing = d / "trade_ai_growing.sql.gz"
    _stamp(growing, age_s=30, now=now, payload=b"tiny")
    part = d / "trade_ai_open.sql.gz.part"
    _stamp(part, age_s=30, now=now, payload=b"tiny")
    # .part does not match the live glob; a young .sql.gz does.
    res = be.enforce_local(_cfg(d), dry_run=False, now=now)
    assert growing.exists()
    assert part.exists()
    assert growing.name in {Path(p).name for p in res["skipped_in_progress"]}
    assert not (d / "archive").exists() or not any((d / "archive").glob("trade_ai_growing*"))


def test_enforce_local_dry_run_does_not_move(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    for i in range(3):
        _stamp(d / f"trade_ai_{i}.sql.gz", age_s=10_000 + i, now=now, payload=b"x" * 60)
    res = be.enforce_local(_cfg(d), dry_run=True, now=now)
    assert res["dry_run"] is True
    assert len(list(d.glob("trade_ai_*.sql.gz"))) == 3
    assert len(res["archived"]) == 2
    assert all(item.startswith("would_archive:") for item in res["archived"])
