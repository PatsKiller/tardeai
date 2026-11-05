"""Unit tests for backup_enforcer local cap. Older dumps are removed only after the newest is verified (§24.15)."""
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


def _verified(path, st):
    return {"verified": True, "reason": "verified", "drive_name": "db_backup_fixture.sql.gz.gpg"}


def test_enforce_local_removes_older_and_old_partial_only_after_newest_verified(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    for i in range(5):
        _stamp(d / f"trade_ai_2026081{i}_000000.sql.gz", age_s=(5 - i) * 10_000, now=now, payload=b"x" * 60)
    partial = d / "trade_ai_partial.sql.gz"
    _stamp(partial, age_s=60_000, now=now, payload=b"tiny")
    res = be.enforce_local(_cfg(d), dry_run=False, now=now, verify=_verified)
    assert res["remaining_full"] == 1
    assert res["remaining_count"] == 1
    assert not partial.exists()
    assert not (d / "archive").exists()  # removed, never moved (a same-disk move frees nothing)
    remaining = list(d.glob("trade_ai_*.sql.gz"))
    assert [p.name for p in remaining] == ["trade_ai_20260814_000000.sql.gz"]


def test_enforce_local_without_verification_removes_nothing(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    for i in range(3):
        _stamp(d / f"trade_ai_{i}.sql.gz", age_s=10_000 + i, now=now, payload=b"x" * 60)
    res = be.enforce_local(_cfg(d), dry_run=False, now=now)
    assert len(list(d.glob("trade_ai_*.sql.gz"))) == 3
    assert res["refused"] == "drive_verification_unavailable"
    assert res["removed"] == []


def test_young_and_part_dumps_are_not_removed(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    growing = d / "trade_ai_growing.sql.gz"
    _stamp(growing, age_s=30, now=now, payload=b"tiny")
    part = d / "trade_ai_open.sql.gz.part"
    _stamp(part, age_s=30, now=now, payload=b"tiny")
    # .part does not match the live glob; a young .sql.gz does.
    res = be.enforce_local(_cfg(d), dry_run=False, now=now, verify=_verified)
    assert growing.exists()
    assert part.exists()
    assert growing.name in {Path(p).name for p in res["skipped_in_progress"]}


def test_enforce_local_dry_run_does_not_remove(tmp_path):
    be = _load()
    d = tmp_path / "db_backups"
    d.mkdir()
    now = 1_800_000_000.0
    for i in range(3):
        _stamp(d / f"trade_ai_{i}.sql.gz", age_s=10_000 + i, now=now, payload=b"x" * 60)
    res = be.enforce_local(_cfg(d), dry_run=True, now=now, verify=_verified)
    assert res["dry_run"] is True
    assert len(list(d.glob("trade_ai_*.sql.gz"))) == 3
    assert len(res["removed"]) == 2
    assert all(item["action"] == "would_remove" for item in res["removed"])


def test_status_respects_byte_cap_even_with_one_full_dump(tmp_path):
    be = _load()
    dump = tmp_path / "trade_ai_latest.sql.gz"
    dump.write_bytes(b"x" * 60)
    cfg = {**_cfg(tmp_path), "max_total_bytes": 59}
    result = be.status_local(cfg)
    assert result["full_count"] == 1
    assert result["total_bytes"] == 60
    assert result["over_bytes"] is True
    assert result["compliant"] is False


def test_status_reports_disjoint_tree_bytes_without_expanding_live_cap(tmp_path, monkeypatch):
    be = _load()
    sizes = {
        "trade_ai_latest.sql.gz": 60,
        "archive/trade_ai_old.sql.gz": 100,
        "archive/hold-review/retained.dump": 20,
        "hold-prerecovery/retained.dump": 30,
        "backup.log": 5,
        "trade_ai_in_progress.sql.gz.part": 7,
    }
    for name, size in sizes.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    before = {name: (tmp_path / name).read_bytes() for name in sizes}
    cfg = {**_cfg(tmp_path), "max_total_bytes": 70}
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("payload read")))
        patch.setattr(be, "_remove_dump", lambda *a, **k: (_ for _ in ()).throw(AssertionError("remove called")))
        patch.setattr(be, "enforce_drive_db", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Drive called")))
        result = be.status_local(cfg)
    assert {name: (tmp_path / name).read_bytes() for name in sizes} == before
    assert result["total_bytes"] == 60  # backup_verify's existing per-dump baseline
    assert result["compliant"] is True  # the existing cap is explicitly LIVE-only
    storage = result["storage"]
    assert storage["measurement_complete"] is True
    assert storage["unknown_reasons"] == []
    assert storage["live_dump_bytes"] == 60
    assert storage["archive_bytes"] == 100
    assert storage["held_bytes"] == 50  # held descendants are not counted in archive too
    assert storage["other_bytes"] == 12
    assert storage["local_backup_total_bytes"] == sum(sizes.values())
    assert storage["archive_and_holds_outside_cap"] is True
    assert storage["cap_scope"] == "top_level_dump_pattern_only"


def test_symlink_targets_are_not_followed_or_presented_as_a_complete_total(tmp_path):
    be = _load()
    root = tmp_path / "backups"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "unread_payload").write_bytes(b"x" * 200)
    (root / "archive").symlink_to(outside, target_is_directory=True)
    storage = be.local_storage_usage(_cfg(root))
    assert storage["measurement_complete"] is False
    assert storage["unknown_reasons"] == ["symlink_not_followed"]
    assert storage["local_backup_total_bytes"] is None
    assert storage["observed_bytes"]["archive_bytes"] == 0


def test_unreadable_archive_is_unknown_and_never_zero_or_compliant(tmp_path, monkeypatch):
    be = _load()
    (tmp_path / "trade_ai_latest.sql.gz").write_bytes(b"x" * 60)
    archive = tmp_path / "archive"
    archive.mkdir()
    real_open = os.open

    def open_dir(path, flags, **kwargs):
        if path == "archive" and kwargs.get("dir_fd") is not None:
            raise PermissionError("fixture only")
        return real_open(path, flags, **kwargs)

    monkeypatch.setattr(be.os, "open", open_dir)
    result = be.status_local(_cfg(tmp_path))
    assert result["total_bytes"] == 60
    assert result["compliant"] is False
    assert result["storage"]["measurement_complete"] is False
    assert result["storage"]["archive_bytes"] is None
    assert result["storage"]["local_backup_total_bytes"] is None
    assert "entry_unavailable" in result["storage"]["unknown_reasons"]


def test_entry_and_time_limits_never_publish_partial_complete_totals(tmp_path, monkeypatch):
    be = _load()
    for i in range(4):
        (tmp_path / f"trade_ai_{i}.sql.gz").write_bytes(b"x")
    limited = be.local_storage_usage(_cfg(tmp_path), max_entries=2)
    assert limited["measurement_complete"] is False
    assert limited["unknown_reasons"] == ["scan_limit"]
    assert limited["local_backup_total_bytes"] is None
    assert limited["entries_scanned"] <= 2
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(be.time, "monotonic", lambda: next(ticks))
    expired = be.local_storage_usage(_cfg(tmp_path), max_seconds=0.5)
    assert expired["measurement_complete"] is False
    assert expired["unknown_reasons"] == ["scan_limit"]
    assert expired["local_backup_total_bytes"] is None


def test_missing_or_invalid_root_does_not_prove_empty_backup_storage(tmp_path):
    be = _load()
    for path in [tmp_path / "absent", tmp_path / "not_a_directory"]:
        if path.name == "not_a_directory":
            path.write_bytes(b"fixture")
        result = be.local_storage_usage(_cfg(path))
        assert result["measurement_complete"] is False
        assert result["local_backup_total_bytes"] is None
    assert be.status_local(_cfg(tmp_path / "absent"))["compliant"] is False


def test_unreadable_live_listing_never_returns_known_zero_bytes(tmp_path, monkeypatch):
    be = _load()
    monkeypatch.setattr(be, "list_local_dumps", lambda cfg: (_ for _ in ()).throw(PermissionError("fixture")))
    result = be.status_local(_cfg(tmp_path))
    assert result["total_bytes"] is None
    assert result["live_measurement_complete"] is False
    assert result["compliant"] is False


def test_observed_directory_swapped_to_symlink_never_scans_outside_metadata(tmp_path, monkeypatch):
    be = _load()
    root = tmp_path / "backups"
    archive = root / "archive"
    archive.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "unread_payload").write_bytes(b"x" * 123)
    outside_inode = outside.stat().st_ino
    real_open, real_scan = os.open, os.scandir
    swapped = []

    def open_dir(path, flags, **kwargs):
        if path == "archive" and kwargs.get("dir_fd") is not None and not swapped:
            # This hook runs after entry.stat and immediately before opening it.
            archive.rename(root / "archive_before_swap")
            archive.symlink_to(outside, target_is_directory=True)
            swapped.append(True)
        return real_open(path, flags, **kwargs)

    def scan(descriptor):
        info = os.fstat(descriptor) if isinstance(descriptor, int) else os.stat(descriptor)
        assert info.st_ino != outside_inode, "outside metadata was reached"
        return real_scan(descriptor)

    # be.os IS the os module: scope the patch to the call, so pytest's own tmp_path cleanup (it removes passing tests'
    # dirs at teardown since tmp_path_retention_policy = "failed") never runs through the fake scandir.
    with monkeypatch.context() as m:
        m.setattr(be.os, "open", open_dir)
        m.setattr(be.os, "scandir", scan)
        result = be.local_storage_usage(_cfg(root))
    assert swapped
    assert result["measurement_complete"] is False
    assert result["local_backup_total_bytes"] is None
    assert sum(result["observed_bytes"].values()) == 0


def test_depth_limit_releases_descriptors_and_never_claims_complete_storage(tmp_path):
    be = _load()
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "unread_payload").write_bytes(b"fixture")
    before = len(os.listdir("/proc/self/fd"))
    result = be.local_storage_usage(_cfg(tmp_path), max_depth=1)
    assert result["measurement_complete"] is False
    assert result["unknown_reasons"] == ["depth_limit"]
    assert result["local_backup_total_bytes"] is None
    assert len(os.listdir("/proc/self/fd")) == before
