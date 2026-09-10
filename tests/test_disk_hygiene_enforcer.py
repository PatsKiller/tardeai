"""Unit tests for disk_hygiene_enforcer release keep-N + stale backup planning."""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "disk_hygiene_enforcer.py"
    spec = importlib.util.spec_from_file_location("disk_hygiene_enforcer", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_plan_releases_keeps_n_and_current(tmp_path):
    hy = _load()
    root = tmp_path / "portfolio-server"
    root.mkdir()
    # 15 fake releases with increasing mtimes
    dirs = []
    for i in range(15):
        d = root / f"{i:03d}abcde-main-exact-phase2-2026090{i % 10}-000000"
        d.mkdir()
        t = time.time() - (15 - i) * 100
        os.utime(d, (t, t))
        dirs.append(d)
    current = dirs[-1]
    (root / "CURRENT").symlink_to(current)

    cfg = {
        "root": str(root),
        "glob": "*-main-exact-*",
        "keep_n": 3,
        "protect_symlinks": ["CURRENT"],
    }
    plan = hy.plan_releases(cfg)
    assert plan["total"] == 15
    # CURRENT target always kept + up to keep_n newest (CURRENT already counts in keep list)
    assert str(current) in plan["keep"]
    assert plan["would_delete_count"] >= 11
    # dry-run apply does not delete
    res = hy.apply_release_deletes(plan, dry_run=True)
    assert all(p.exists() for p in dirs)
    assert res["dry_run"] is True
    assert len(res["deleted"]) == plan["would_delete_count"]


def test_apply_releases_deletes_only_planned(tmp_path):
    hy = _load()
    root = tmp_path / "portfolio-server"
    root.mkdir()
    keepers = []
    doomed = []
    for i in range(6):
        d = root / f"{i:03d}ffff-main-exact-phase2-20260901-00000{i}"
        d.mkdir()
        (d / "marker").write_text("x")
        t = time.time() - (6 - i) * 50
        os.utime(d, (t, t))
        (keepers if i >= 3 else doomed).append(d)
    current = keepers[-1]
    (root / "CURRENT").symlink_to(current)
    cfg = {
        "root": str(root),
        "glob": "*-main-exact-*",
        "keep_n": 2,
        "protect_symlinks": ["CURRENT"],
    }
    plan = hy.plan_releases(cfg)
    res = hy.apply_release_deletes(plan, dry_run=False)
    assert res["ok"] is True
    assert current.exists()
    for d in plan["delete"]:
        assert not Path(d).exists()


def test_stale_backup_age_filter(tmp_path):
    hy = _load()
    pile = tmp_path / "backups"
    pile.mkdir()
    old = pile / "trade_ai_backup_old.zip"
    new = pile / "trade_ai_backup_new.zip"
    old.write_bytes(b"old" * 1000)
    new.write_bytes(b"new" * 1000)
    old_mtime = time.time() - 90 * 86400
    os.utime(old, (old_mtime, old_mtime))
    piles = [{"path": str(pile), "max_age_days": 45}]
    plan = hy.plan_stale_backups(piles)
    paths = {x["path"] for x in plan["would_delete"]}
    assert str(old) in paths
    assert str(new) not in paths
    res = hy.apply_stale_backup_deletes(plan, dry_run=False)
    assert not old.exists()
    assert new.exists()
    assert res["ok"] is True
