"""JSONL archive rotation — the root-owned holder helper (LQ-20261107-501, operator route 1).

ANCHOR: JSONL_ARCHIVE_ROTATE_FD_HOLDERS_20261107. Operator 2026-11-07 20:19 ET, verbatim "1,": the fd view
blocking ``jsonl_archive_rotate`` is read through a tiny root-owned, read-only helper
(``scripts/ops/tradeai_fd_holders.py``, installed at ``/usr/local/sbin/tradeai-fd-holders`` behind one sudoers
line), never by giving this script itself CAP_SYS_PTRACE or sudo. These tests use a *fake* helper: it is a real
executable in tmp_path that answers for a tmp_path store, so no test here reads the host's /proc through the
helper and none needs root. What is under test is the rotator's decision: a complete helper answer is a complete
view; an absent helper keeps today's strict refusal; a helper that fails, answers for another path, reports a
stale inode or admits an unreadable fd table is an *incomplete view*, never "nobody holds it".
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.ops import jsonl_archive_rotate as J

NOW = datetime(2026, 11, 7, 20, 45, tzinfo=timezone.utc)  # Sat 15:45 ET, outside the refusal window

_FAKE = r'''#!/usr/bin/env python3
"""A stand-in for /usr/local/sbin/tradeai-fd-holders: answers for whatever path it is given."""
import json, os, sys
mode = os.environ.get("FAKE_MODE", "ok")
p = sys.argv[1]
if mode == "marker":
    open(os.environ["FAKE_MARKER"], "w").write(p)
    mode = "ok"
if mode == "exit":
    sys.exit(4)
if mode == "wrongpath":
    p = "/nonexistent/other.jsonl"
    row = {"path": p, "dev": 0, "ino": 0, "holders": [], "unknown": []}
else:
    st = os.stat(p)
    dev, ino = (0, 0) if mode == "stale" else (st.st_dev, st.st_ino)
    holders = [{"pid": int(x), "fd": "9", "comm": "fake"} for x in (os.environ.get("FAKE_HOLDERS") or "").split(",") if x]
    unknown = [{"pid": 999, "comm": "ghost", "reason": "fd_dir_denied"}] if mode == "incomplete" else []
    row = {"path": p, "dev": dev, "ino": ino, "holders": holders, "unknown": unknown}
print(json.dumps({"schema": "tradeai_fd_holders.v1", "complete": mode != "incomplete", "paths": [row]}))
'''


def _cfg(**over):
    cfg = {
        "enabled": False,
        "min_rotate_bytes": 0,
        "quiesce_timeout_s": 1,
        "max_install_attempts": 20,
        "refuse_window_et": {"days": "Mon-Fri", "start": "04:00", "end": "16:15"},
        "stores": [{"id": "s1", "path": "data/cio/s1.jsonl", "ts_fields": ["at"], "rotate": True, "hot_days": 3,
                    "min_tail_rows": 5, "retention_days": 7, "max_archive_bytes": 10_000_000}],
    }
    cfg.update(over)
    return cfg


def _seed(root: Path) -> Path:
    p = root / "data" / "cio" / "s1.jsonl"
    p.parent.mkdir(parents=True)
    with open(p, "wb") as fh:
        for i in range(200):
            fh.write((json.dumps({"at": (NOW - timedelta(days=10, minutes=-i)).isoformat(), "i": i}) + "\n").encode())
        for i in range(200, 250):
            fh.write((json.dumps({"at": (NOW - timedelta(hours=5, minutes=-i)).isoformat(), "i": i}) + "\n").encode())
    return p


def _no_sleep(_s):
    time.sleep(0.001)


@pytest.fixture()
def helper(tmp_path, monkeypatch):
    """Install the fake helper and point the rotator at it (no sudo: the fake needs none)."""
    p = tmp_path / "tradeai-fd-holders"
    p.write_text(_FAKE.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1))
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("TRADEAI_FD_HOLDERS", str(p))
    monkeypatch.setenv("TRADEAI_FD_HOLDERS_SUDO", "0")
    monkeypatch.delenv("FAKE_MODE", raising=False)
    monkeypatch.delenv("FAKE_HOLDERS", raising=False)
    return p


def test_the_helper_is_found_only_when_it_is_installed_and_executable(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_FD_HOLDERS", str(tmp_path / "absent"))
    assert J.fd_holders_helper() is None
    p = tmp_path / "present"
    p.write_text("#!/bin/sh\n")
    monkeypatch.setenv("TRADEAI_FD_HOLDERS", str(p))
    assert J.fd_holders_helper() is None, "a file the user may not execute is not an installed helper"
    p.chmod(0o755)
    assert J.fd_holders_helper() == p


def test_plan_reads_the_helper_as_a_complete_view(tmp_path, helper):
    _seed(tmp_path)
    row = J.plan_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW)
    assert row["fd_visibility"] == "ok", row
    assert row["fd_view"] == "helper", row
    assert row["fd_holders_now"] == 0
    assert row["action"] == "rotate"


def test_apply_rotates_when_the_helper_answers_completely(tmp_path, helper):
    live = _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is True and res["action"] == "rotated", res
    assert live.is_file() and len(live.read_bytes().splitlines()) >= 5


def test_absent_helper_keeps_the_class_b_refusal(tmp_path, monkeypatch):
    """Route 1 must not open class B: no helper on the host means exactly today's refusal."""
    monkeypatch.setenv("TRADEAI_FD_HOLDERS", str(tmp_path / "not-installed"))
    _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res


def test_a_helper_that_cannot_run_is_an_incomplete_view(tmp_path, helper, monkeypatch):
    """Installed-but-broken is not absent: the refusal stands and names the helper as the cause."""
    monkeypatch.setenv("FAKE_MODE", "exit")
    _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert "helper_failed:exit_4" in res["detail"], res


def test_a_helper_that_admits_an_unreadable_fd_table_is_not_complete(tmp_path, helper, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "incomplete")
    _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert "999:ghost:fd_dir_denied" in res["detail"], res


def test_no_sudo_with_a_helper_installed_is_not_a_complete_view(tmp_path, helper, monkeypatch):
    """The helper is useless without its sudoers line, and that must refuse rather than skip the view."""
    monkeypatch.delenv("TRADEAI_FD_HOLDERS_SUDO")
    monkeypatch.setattr(J, "_sudo_bin", lambda: None)
    _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert "helper_unusable:sudo_not_found" in res["detail"], res


def test_a_helper_answer_for_another_path_is_not_trusted(tmp_path, helper, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "wrongpath")
    _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert "helper_failed:no_row_for_path" in res["detail"], res


def test_a_helper_answer_for_a_stale_inode_is_not_trusted(tmp_path, helper, monkeypatch):
    """The store was replaced between the helper's stat and ours: its "no holder" is about a dead inode."""
    monkeypatch.setenv("FAKE_MODE", "stale")
    _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert "helper_failed:stale_inode" in res["detail"], res


def test_a_helper_reported_holder_blocks_the_rotation(tmp_path, helper, monkeypatch):
    monkeypatch.setenv("FAKE_HOLDERS", "4242")
    live = _seed(tmp_path)
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "long_lived_fd_holder", res
    assert res["holders"] == ["4242/9"], res
    assert live.is_file() and len(live.read_bytes().splitlines()) == 250, "the store is untouched"


def test_the_helper_finds_an_inode_holder_in_a_planted_proc(tmp_path):
    """The helper's own scan, on a fake proc root: a planted fd link is a holder, and the answer is complete."""
    from scripts.ops import tradeai_fd_holders as H

    store = _seed(tmp_path)
    proc = tmp_path / "proc"
    (proc / "1234" / "fd").mkdir(parents=True)
    (proc / "1234" / "comm").write_text("codex\n")
    (proc / "1234" / "fd" / "5").symlink_to(store)
    (proc / "8888" / "fd").mkdir(parents=True)
    (proc / "8888" / "comm").write_text("idle\n")

    rows, complete = H.scan(proc, [store])
    assert complete is True
    assert rows[0]["holders"] == [{"pid": 1234, "fd": "5", "comm": "codex"}]
    assert rows[0]["unknown"] == []


def test_the_helper_reports_an_unreadable_fd_table_as_incomplete(tmp_path, monkeypatch):
    """The half that makes it safe: a table it cannot list is reported, so the caller refuses."""
    from scripts.ops import tradeai_fd_holders as H

    store = _seed(tmp_path)
    proc = tmp_path / "proc"
    (proc / "4321").mkdir(parents=True)
    (proc / "4321" / "comm").write_text("systemd\n")
    real = os.listdir

    def fake_listdir(p):
        if str(p).endswith(os.path.join("4321", "fd")):
            raise PermissionError(13, "Permission denied")
        return real(p)

    monkeypatch.setattr(H.os, "listdir", fake_listdir)
    rows, complete = H.scan(proc, [store])
    assert complete is False
    assert rows[0]["unknown"] == [{"pid": 4321, "comm": "systemd",
                                   "reason": "fd_dir_denied:Permission denied"}]


def test_the_helper_is_not_consulted_for_a_fake_proc_root(tmp_path, helper, monkeypatch):
    """Every existing test passes a fake /proc: a host-level helper must never answer for it."""
    marker = tmp_path / "helper-was-called"
    monkeypatch.setenv("FAKE_MODE", "marker")
    monkeypatch.setenv("FAKE_MARKER", str(marker))
    proc = tmp_path / "proc"
    proc.mkdir()
    store = _seed(tmp_path)
    holders, unknown = J._scan_holders(store, proc)
    assert not marker.exists(), "the helper ran for a fake /proc view"
    assert holders == [] and unknown == []
