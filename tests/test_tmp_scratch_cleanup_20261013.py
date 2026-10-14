"""scripts/tmp_scratch_cleanup.py — weekly sweep of leaked pytest scratch in /tmp (inode exhaustion 2026-10-13).

Every test runs against a tmp_path root, never the real /tmp.
"""
from __future__ import annotations

import json
import os
import sys
import tarfile
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import tmp_scratch_cleanup as C  # noqa: E402

NOW = datetime(2026, 10, 18, 7, 30, tzinfo=timezone.utc)
StatVfs = namedtuple("StatVfs", "f_files f_ffree")


def _mk(root: Path, name: str, *, age: timedelta, files: dict[str, str] | None = None) -> Path:
    d = root / name
    d.mkdir()
    for rel, text in (files or {}).items():
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    ts = (NOW - age).timestamp()
    for p in [*d.rglob("*"), d]:
        os.utime(p, (ts, ts), follow_symlinks=False)
    return d


def _run(tmp_path: Path, *extra: str, statvfs=None) -> tuple[int, dict]:
    root = tmp_path / "tmp"
    kwargs = {"statvfs": statvfs} if statvfs else {}
    rc = C.main(
        ["--root", str(root), "--archive-dir", str(tmp_path / "archive"), "--state-root", str(tmp_path / "state"),
         "--now", NOW.isoformat(), *extra],
        **kwargs,
    )
    receipt = json.loads((tmp_path / "state" / C.RECEIPT_REL).read_text())
    return rc, receipt


def _healthy(_path: str) -> StatVfs:
    return StatVfs(f_files=1000, f_ffree=900)


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "tmp"
    root.mkdir()
    _mk(root, "tradeai_audit_ledger_tests_old1", age=timedelta(days=2))
    _mk(root, "tradeai_no_pgpass_old2", age=timedelta(days=3))
    _mk(root, "tradeai_comms_mode_tests_young", age=timedelta(hours=2))
    _mk(root, "tradeai_hermetic_env_full", age=timedelta(days=10), files={"env": "", "home/.gitconfig": "[user]\n"})
    _mk(root, "tradeai_pytest_scratch_fullyoung", age=timedelta(days=3), files={"x": "1"})
    _mk(root, "emergency-abc", age=timedelta(days=30))
    _mk(root, "claude-1000", age=timedelta(days=30))
    (root / "tradeai_finviz_momentum_scalp.lock").write_text("")
    target = _mk(tmp_path, "elsewhere", age=timedelta(days=30))
    (root / "tradeai_audit_ledger_tests_link").symlink_to(target)
    return root


def test_dry_run_removes_nothing_and_counts_what_it_would_do(tmp_path):
    root = _tree(tmp_path)
    before = sorted(p.name for p in root.iterdir())
    rc, receipt = _run(tmp_path, statvfs=_healthy)
    assert rc == 0
    assert sorted(p.name for p in root.iterdir()) == before
    assert receipt["mode"] == "dry-run" and receipt["ok"] is True
    assert receipt["empty_would_remove"] == 2 and receipt["empty_removed"] == 0
    assert receipt["archive_would_take"] == 1 and receipt["archived_dirs"] == 0
    assert not (tmp_path / "archive").exists()


def test_apply_removes_only_old_empty_scratch_and_archives_old_full_scratch(tmp_path):
    root = _tree(tmp_path)
    rc, receipt = _run(tmp_path, "--apply", statvfs=_healthy)
    assert rc == 0, receipt
    left = sorted(p.name for p in root.iterdir())
    assert left == sorted([
        "tradeai_comms_mode_tests_young",  # empty but younger than a day
        "tradeai_pytest_scratch_fullyoung",  # non-empty but younger than a week
        "emergency-abc",  # unmanaged
        "claude-1000",  # unmanaged
        "tradeai_finviz_momentum_scalp.lock",  # a lock file is never touched
        "tradeai_audit_ledger_tests_link",  # a symlink is never followed or removed
    ])
    assert (tmp_path / "elsewhere").is_dir()  # the symlink target is untouched
    assert receipt["empty_removed"] == 2 and receipt["archived_dirs"] == 1
    assert receipt["unmanaged_top_level"] == 4  # emergency, claude, lock file, symlink
    arch = receipt["archives"][0]
    with tarfile.open(arch["archive"]) as tar:
        names = set(tar.getnames())
    assert {"tradeai_hermetic_env_full", "tradeai_hermetic_env_full/env",
            "tradeai_hermetic_env_full/home/.gitconfig"} <= names
    manifest = next(Path(arch["archive"]).parent.glob("*.MANIFEST.json"))
    assert json.loads(manifest.read_text())["sha256"] == arch["sha256"]


def test_inode_alarm_exits_3_and_prints_an_incident(tmp_path, capsys):
    _tree(tmp_path)
    rc, receipt = _run(tmp_path, "--apply", statvfs=lambda _p: StatVfs(f_files=1000, f_ffree=100))
    assert rc == C.EXIT_INODE_ALARM
    assert receipt["ok"] is False and receipt["inode_alarm"] is True
    assert receipt["inode_use_pct_after"] == 90.0
    assert "INCIDENT tmp-scratch-cleanup" in capsys.readouterr().err


def test_a_dir_owned_by_another_uid_is_not_managed(tmp_path, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    _mk(root, "tradeai_audit_ledger_tests_other", age=timedelta(days=5))
    other = os.getuid() + 1
    monkeypatch.setattr(C.os, "getuid", lambda: other)
    rc, receipt = _run(tmp_path, "--apply", statvfs=_healthy)
    assert rc == 0
    assert (root / "tradeai_audit_ledger_tests_other").is_dir()
    assert receipt["unmanaged_top_level"] == 1 and receipt["empty_removed"] == 0
