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


# ── LQ-20261107-533: an env override never gets an arbitrary path executed as root or believed as the view ──────────

class _St:
    def __init__(self, uid, mode):
        self.st_uid, self.st_mode = uid, mode


@pytest.fixture()
def strict(monkeypatch):
    """The state ``main`` sets for --apply, restored afterwards."""
    monkeypatch.setattr(J, "_STRICT_HELPER", True)


def test_apply_refuses_an_override_helper_the_caller_owns(tmp_path, helper, strict, monkeypatch):
    """The fake claims complete:true and no holders. Under --apply an agent-owned override must not be that view."""
    _seed(tmp_path)
    assert J.helper_distrust(helper) is not None
    assert J.fd_holders_helper() != helper, "the env override is ignored under --apply"
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res


def test_apply_refuses_a_group_writable_installed_helper_even_when_root_owned(tmp_path, helper, strict, monkeypatch):
    """The installed path itself must also be root-owned and unwritable by others, whatever put it there."""
    monkeypatch.delenv("TRADEAI_FD_HOLDERS")
    monkeypatch.setattr(J, "FD_HOLDERS_HELPER", str(helper))
    monkeypatch.setattr(J, "_stat_for_trust", lambda c: _St(0, 0o775))
    _seed(tmp_path)
    assert (J.helper_distrust(helper) or "").startswith("group_or_world_writable")
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert "helper_untrusted:group_or_world_writable" in res["detail"], res


def test_apply_ignores_even_a_root_owned_unwritable_override(tmp_path, helper, strict, monkeypatch):
    """LQ-20261107-546: owner is not identity. Under --apply the env override is never read, however clean the path."""
    monkeypatch.setattr(J, "_stat_for_trust", lambda c: _St(0, 0o755))
    live = _seed(tmp_path)
    assert J.helper_distrust(helper) is None
    assert J.fd_holders_helper() != helper
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert live.is_file()


def test_dry_run_still_honours_the_override_unprivileged(tmp_path, helper, monkeypatch):
    monkeypatch.setattr(J, "_STRICT_HELPER", False)
    monkeypatch.setattr(J.os, "geteuid", lambda: 1000)
    assert J.fd_holders_helper() == helper


def test_root_never_trusts_an_agent_owned_override(tmp_path, helper, monkeypatch):
    """Even a plan run, when the process is root, must not exec an env-given path."""
    monkeypatch.setattr(J, "_STRICT_HELPER", False)
    monkeypatch.setattr(J.os, "geteuid", lambda: 0)
    assert J.fd_holders_helper() != helper


def test_main_apply_sets_the_strict_mode_and_refuses_the_override(tmp_path, helper, monkeypatch, capsys):
    monkeypatch.setattr(J, "_STRICT_HELPER", False)
    live = _seed(tmp_path)
    before = live.read_bytes()
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"jsonl_retention": _cfg()}))
    rc = J.main(["--apply", "--confirm", "APPLY", "--rules", str(rules), "--state-root", str(tmp_path),
                 "--now", NOW.isoformat()])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "fd_visibility_unknown" in out, out
    assert live.read_bytes() == before, "nothing was rotated"
    assert J._STRICT_HELPER is True
    monkeypatch.setattr(J, "_STRICT_HELPER", False)


# ── LQ-20261107-553b: the review's bypasses A, B and Root, and changes 2-4 (each fails on b6dccab3b) ─────────────────

def _root_owned_interpreter() -> str:
    for c in ("/bin/bash", "/usr/bin/bash"):
        if J.helper_distrust(Path(c)) is None:
            return c
    pytest.skip("no root-owned bash with a root-owned, non-writable directory chain on this host")


def _evil_bash_env(tmp_path, store: Path) -> Path:
    """What an agent can write: a BASH_ENV file that prints a complete, holder-free view of the real store."""
    st = os.stat(store)
    doc = {"schema": "tradeai_fd_holders.v1", "complete": True,
           "paths": [{"path": str(store), "dev": st.st_dev, "ino": st.st_ino, "holders": [], "unknown": []}]}
    ev = tmp_path / "evil.sh"
    ev.write_text(f"echo '{json.dumps(doc)}'\n: > {tmp_path}/ran-as-helper\nexit 0\n")
    return ev


def test_bypass_a_a_root_owned_interpreter_named_by_the_env_is_never_the_helper(tmp_path, strict, monkeypatch):
    """/bin/bash passes an ownership check, and BASH_ENV makes it print whatever the caller wrote."""
    bash = _root_owned_interpreter()
    live = _seed(tmp_path)
    ev = _evil_bash_env(tmp_path, live)
    monkeypatch.setenv("TRADEAI_FD_HOLDERS", bash)
    monkeypatch.setenv("TRADEAI_FD_HOLDERS_SUDO", "0")
    monkeypatch.setenv("BASH_ENV", str(ev))
    monkeypatch.setattr(J, "FD_HOLDERS_HELPER", str(tmp_path / "not-installed"))
    before = live.read_bytes()
    res = J.rotate_store(_cfg()["stores"][0], _cfg(), tmp_path, NOW, proc_root=Path("/proc"),
                         sleep=_no_sleep, grace_s=0)
    assert res["ok"] is False and res["reason"] == "fd_visibility_unknown", res
    assert not (tmp_path / "ran-as-helper").exists(), "the caller's BASH_ENV ran"
    assert live.read_bytes() == before


def test_bypass_b_the_file_run_is_the_file_checked_not_the_name_it_started_with(tmp_path, helper, strict, monkeypatch):
    """The check resolves; the exec used the unresolved link, so a link could name two files. Run the resolved one."""
    link = tmp_path / "link"
    link.symlink_to(helper)
    live = _seed(tmp_path)
    monkeypatch.setattr(J, "FD_HOLDERS_HELPER", str(link))
    monkeypatch.delenv("TRADEAI_FD_HOLDERS")
    monkeypatch.setattr(J, "_stat_for_trust", lambda c: _St(0, 0o755))
    monkeypatch.setattr(J, "_fstat_for_trust", lambda fd: _Fst(fd))
    monkeypatch.setattr(J, "_sudo_bin", lambda: "/usr/bin/sudo")
    seen = []
    real_run = J.subprocess.run
    monkeypatch.setattr(J.subprocess, "run", lambda argv, **kw: seen.append(argv) or real_run(
        [str(helper), argv[-1]], **{k: v for k, v in kw.items() if k != "pass_fds"}))
    J._helper_scan(live, Path("/proc"))
    assert seen and str(link) not in seen[0] and str(helper.resolve()) in seen[0], seen


def test_bypass_b_a_file_swapped_between_check_and_open_is_untrusted(tmp_path, helper, monkeypatch):
    monkeypatch.setattr(J, "_stat_for_trust", lambda c: _St(0, 0o755))

    class Other(_Fst):
        def __init__(self, fd):
            super().__init__(fd)
            self.st_ino += 1

    monkeypatch.setattr(J, "_fstat_for_trust", lambda fd: Other(fd))
    fd, real, why = J._open_trusted_helper(helper)
    assert fd is None and real is None and "swapped" in (why or ""), why


class _Fst:
    """The fd's real dev/ino/type, shown as a root-owned file nobody else may write."""
    def __init__(self, fd):
        st = os.fstat(fd)
        self.st_dev, self.st_ino = st.st_dev, st.st_ino
        self.st_uid, self.st_mode = 0, stat.S_IFREG | 0o755


def test_root_never_execs_an_interpreter_the_env_chose(tmp_path, monkeypatch):
    """euid 0 plus TRADEAI_FD_HOLDERS=/bin/bash used to exec bash with the caller's BASH_ENV, as root."""
    bash = _root_owned_interpreter()
    live = _seed(tmp_path)
    ev = _evil_bash_env(tmp_path, live)
    monkeypatch.setattr(J.os, "geteuid", lambda: 0)
    monkeypatch.setattr(J, "_STRICT_HELPER", False)
    monkeypatch.setenv("TRADEAI_FD_HOLDERS", bash)
    monkeypatch.setenv("BASH_ENV", str(ev))
    monkeypatch.setattr(J, "FD_HOLDERS_HELPER", str(tmp_path / "not-installed"))
    assert J.fd_holders_helper() is None
    holders, unknown = J._helper_scan(live, Path("/proc")) or ([], [])
    assert not (tmp_path / "ran-as-helper").exists(), "the caller's BASH_ENV ran"
    assert holders == [] and "helper_failed" not in " ".join(unknown)


def test_the_sudo_knob_is_ignored_under_apply_for_a_non_root_caller(tmp_path, helper, strict, monkeypatch):
    monkeypatch.setattr(J, "_sudo_bin", lambda: "/usr/bin/sudo")
    assert J._helper_argv(helper, tmp_path / "x")[:2] == ["/usr/bin/sudo", "-n"]
    monkeypatch.setattr(J, "_STRICT_HELPER", False)
    assert J._helper_argv(helper, tmp_path / "x")[0] == str(helper), "outside strict mode the knob still works"


def test_root_runs_the_checked_descriptor_with_a_scrubbed_environment(tmp_path, helper, monkeypatch):
    """End to end as 'root': the helper that answers is the open descriptor, and it sees none of the caller's env."""
    live = _seed(tmp_path)
    marker = tmp_path / "saw-env"
    monkeypatch.setattr(J.os, "geteuid", lambda: 0)
    monkeypatch.delenv("TRADEAI_FD_HOLDERS")
    monkeypatch.setattr(J, "FD_HOLDERS_HELPER", str(helper))
    monkeypatch.setattr(J, "_stat_for_trust", lambda c: _St(0, 0o755))
    monkeypatch.setattr(J, "_fstat_for_trust", lambda fd: _Fst(fd))
    monkeypatch.setenv("FAKE_MODE", "marker")        # a caller-chosen variable the helper would obey if it saw it
    monkeypatch.setenv("FAKE_MARKER", str(marker))
    seen = []
    real_run = J.subprocess.run
    monkeypatch.setattr(J.subprocess, "run", lambda argv, **kw: seen.append((argv, kw)) or real_run(argv, **kw))
    holders, unknown = J._helper_scan(live, Path("/proc"))
    argv, kw = seen[0]
    assert argv[0].startswith("/proc/self/fd/") and kw["pass_fds"], argv
    assert kw["env"] == {"PATH": "/usr/bin:/bin"}
    assert holders == [] and unknown == [], (holders, unknown)
    assert not marker.exists(), "the helper saw the caller's FAKE_MODE"


def test_the_installed_helper_asks_for_an_isolated_interpreter():
    first = Path(J.__file__).with_name("tradeai_fd_holders.py").read_text().splitlines()[0]
    assert first == "#!/usr/bin/python3 -I", first
