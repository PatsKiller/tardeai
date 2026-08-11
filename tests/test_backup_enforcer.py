"""Unit tests for backup_enforcer local cap."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "backup_enforcer.py"
    spec = importlib.util.spec_from_file_location("backup_enforcer", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_enforce_local_keeps_newest_one(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    # create 5 "full" dumps with increasing mtimes
    import time
    paths = []
    for i in range(5):
        p = d / f"trade_ai_2026081{i}_000000.sql.gz"
        p.write_bytes(b"x" * (600 * 1024 * 1024))  # 600MB fake full
        # bump mtime
        t = time.time() - (5 - i) * 100
        import os
        os.utime(p, (t, t))
        paths.append(p)
    # one partial
    partial = d / "trade_ai_partial.sql.gz"
    partial.write_bytes(b"tiny")

    cfg = {
        "dir": str(d),
        "pattern": "trade_ai_*.sql.gz",
        "max_count": 1,
        "min_bytes": 500 * 1024 * 1024,
        "max_total_bytes": 5 * 1024 * 1024 * 1024,
    }
    res = be.enforce_local(cfg, dry_run=False)
    assert res["remaining_full"] == 1
    assert res["remaining_count"] == 1
    assert len(res["kept"]) == 1
    assert not partial.exists()
    # newest kept
    remaining = list(d.glob("trade_ai_*.sql.gz"))
    assert len(remaining) == 1
    assert remaining[0].name == "trade_ai_20260814_000000.sql.gz"


def test_enforce_local_dry_run_does_not_delete(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    for i in range(3):
        p = d / f"trade_ai_{i}.sql.gz"
        p.write_bytes(b"x" * (600 * 1024 * 1024))
    cfg = {
        "dir": str(d),
        "pattern": "trade_ai_*.sql.gz",
        "max_count": 1,
        "min_bytes": 500 * 1024 * 1024,
        "max_total_bytes": 10 * 1024 * 1024 * 1024,
    }
    res = be.enforce_local(cfg, dry_run=True)
    assert res["dry_run"] is True
    assert len(list(d.glob("trade_ai_*.sql.gz"))) == 3
    assert len(res["deleted"]) == 2
