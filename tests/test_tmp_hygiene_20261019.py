"""/tmp hygiene + inode bands (operator 2026-10-19, after the /tmp inode incident).

Incident 2026-10-19 ~13:40 ET: /tmp (tmpfs, 1,048,576 inodes) hit 97% INODES with 20G of bytes free and tools failed
with ENOSPC; the files sat in ended Claude sessions' scratch dirs and pytest temp, and the monitor checked bytes only.
Pins scripts/disk_usage_monitor.py inode bands (statvfs f_files / f_ffree, separate thresholds, dedupe per (mount,
metric), top dirs by file count from a bounded scan) and every rule of scripts/tmp_hygiene.py: session scratch idle,
cwd inside, open fd inside, live transcript, registered worktree removal through `git worktree remove`, dirty /
unregistered worktrees, pytest age, never-touch for every non-matching /tmp entry, manifest file_count and the
inodes reclaimable totals, the operator-gated apply, the n8n wiring of lane tmp-hygiene and the packet steps.

Hermetic: a tmp dir stands in for /tmp, a fake /proc (cwd + fd symlinks), fake transcripts, fake statvfs, tmp git
repos (GIT_CONFIG_GLOBAL=/dev/null), tmp state roots and ledgers. No real /tmp entry, ledger, service, n8n or Telegram.

COVERS = ["scripts/tmp_hygiene.py", "scripts/disk_usage_monitor.py", "config/disk_hygiene_rules.json",
          "config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json",
          "docs/ops/packets/disk-hygiene-n8n-20261018/cutover.sh"]
"""

from __future__ import annotations

import json
import os
import pwd
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import disk_hygiene as DH  # noqa: E402
from scripts import disk_usage_monitor as DM  # noqa: E402
from scripts import tmp_hygiene as TH  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib import n8n_output_verdict as OV  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

CONFIG = ROOT / "config"
PACKET = ROOT / "docs" / "ops" / "packets" / "disk-hygiene-n8n-20261018"
UID = os.getuid()
USER = pwd.getpwuid(UID).pw_name
PROJECT = "-home-x-repo"
#: plans run 30 days after the fixtures are built: everything is idle unless a test touches it to NOW
NOW = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=30)
SID = "0549bb07-87c6-4de8-9320-3bd573d0c2b7"


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def sh(*args: str, cwd: Path | None = None) -> str:
    p = subprocess.run(list(args), cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    calls: list = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was called")

    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = boom
    fake.record_operator_message = boom
    for name in ("telegram_alert", "scripts.telegram_alert"):
        monkeypatch.setitem(sys.modules, name, fake)
    yield
    assert calls == []


def touch_now(p: Path) -> None:
    os.utime(p, (NOW.timestamp(), NOW.timestamp()))


class TmpWorld:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.root = tmp / "fake_tmp"
        self.root.mkdir()
        self.home = tmp / "home"
        self.home.mkdir()
        self.proc = tmp / "proc"
        self.proc.mkdir()
        self.state = tmp / "state"
        self.transcripts = self.home / ".claude" / "projects" / PROJECT
        self.transcripts.mkdir(parents=True)
        self.rules_path = tmp / "rules.json"
        doc = _load("disk_hygiene_rules.json")
        doc["home"] = str(self.home)
        doc["git"]["roots"] = []
        doc["releases"]["roots"] = []
        doc["references"] = {"crontab_cmd": ["true"], "systemd_unit_dirs": [], "proc_root": str(self.proc)}
        doc["tmp"]["root"] = str(self.root)
        self.rules = doc
        self.write_rules()

    def write_rules(self) -> None:
        self.rules_path.write_text(json.dumps(self.rules, indent=1))

    def session(self, sid: str = SID, files: int = 5, project: str = PROJECT) -> Path:
        d = self.root / f"claude-{UID}" / project / sid
        (d / "scratchpad").mkdir(parents=True)
        for i in range(files):
            (d / "scratchpad" / f"f{i}.txt").write_text("x" * 10)
        return d

    def pytest_dir(self, name: str) -> Path:
        d = self.root / f"pytest-of-{USER}" / name
        (d / "test_a0").mkdir(parents=True)
        (d / "test_a0" / "f").write_text("y")
        return d

    def fd(self, pid: int, n: int, target: Path) -> None:
        (self.proc / str(pid) / "fd").mkdir(parents=True, exist_ok=True)
        os.symlink(str(target), self.proc / str(pid) / "fd" / str(n))

    def cwd(self, pid: int, target: Path) -> None:
        (self.proc / str(pid)).mkdir(parents=True, exist_ok=True)
        os.symlink(str(target), self.proc / str(pid) / "cwd")

    def run(self, *extra: str, now: datetime = NOW) -> int:
        return TH.main(["--rules", str(self.rules_path), "--state-root", str(self.state), "--now", now.isoformat(),
                        *extra])

    def manifest(self) -> dict:
        return json.loads((self.state / "data/runtime/disk_hygiene/tmp_hygiene_manifest_latest.json").read_text())

    def result(self, path: Path) -> dict:
        m = self.manifest()
        for r in m["items"] + m["excluded"]:
            if r["path"] == str(path):
                return r
        for e in m["untouched"]["entries"]:
            if e["path"] == str(path):
                return {"path": e["path"], "reasons": [e["reason"]], "file_count": None, "candidate": False}
        raise KeyError(path)

    def reasons(self, path: Path) -> set[str]:
        return {r.split(":", 1)[0] for r in self.result(path)["reasons"]}


@pytest.fixture
def tw(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@e"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@e")):
        monkeypatch.setenv(k, v)
    for k in (DH.GRANT_ENV, DH.RUN_ID_ENV, "TRADEAI_STATE_ROOT", "TRADEAI_N8N_COORDINATION_LEDGER"):
        monkeypatch.delenv(k, raising=False)
    return TmpWorld(tmp_path)


# ── 1. rule S: claude session scratch ─────────────────────────────────────────────────────────────────────────────


def test_an_idle_ended_session_is_a_candidate_with_its_file_count(tw):
    s = tw.session(files=7)
    (tw.transcripts / f"{SID}.jsonl").write_text("{}\n")  # present and old: the session ended
    assert tw.run() == 0
    r = tw.result(s)
    assert r["candidate"] is True and r["kind"] == TH.KIND_SESSION and r["rule"] == "S"
    assert r["file_count"] == 1 + 1 + 7  # the session dir, scratchpad/, 7 files: the inodes a removal frees
    assert r["evidence"]["transcript"]["idle_days"] > 2
    t = tw.manifest()["totals"]
    assert t["candidates"] == 1 and t["reclaimable_files"] == 9 and t["reclaimable_bytes"] >= 0
    assert t["by_kind"]["S:tmp_claude_session"]["files"] == 9
    assert tw.manifest()["scope"] == "tmp" and tw.manifest()["schema"] == DH.MANIFEST_SCHEMA


def test_any_recent_file_deep_in_the_tree_keeps_the_session(tw):
    s = tw.session()
    deep = s / "scratchpad" / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "new").write_text("z")
    touch_now(deep / "new")
    tw.run()
    assert tw.reasons(s) == {"recent_activity"}


def test_a_process_cwd_inside_keeps_the_session(tw):
    s = tw.session()
    tw.cwd(4242, s / "scratchpad")
    tw.run()
    assert tw.reasons(s) == {"in_use_cwd"}


def test_an_open_fd_inside_keeps_the_session(tw):
    s = tw.session()
    tw.fd(4343, 7, s / "scratchpad" / "f1.txt")
    tw.fd(4343, 8, Path("/dev/null"))
    os.symlink("socket:[123]", tw.proc / "4343" / "fd" / "9")
    tw.run()
    assert tw.reasons(s) == {"open_fd"}


def test_a_live_transcript_keeps_the_session_and_an_absent_one_does_not_block(tw):
    live = tw.session(SID)
    other = tw.session("1b922dbb-6f1c-42c8-81cb-df2db8060b4d")
    tr = tw.transcripts / f"{SID}.jsonl"
    tr.write_text("{}\n")
    touch_now(tr)
    tw.run()
    assert tw.reasons(live) == {"session_transcript_live"}
    assert tw.result(other)["candidate"] is True and tw.result(other)["evidence"]["transcript"] is None


def test_non_uuid_entries_in_the_scratch_tree_are_never_evaluated(tw):
    tw.session()
    stray = tw.root / f"claude-{UID}" / PROJECT / "backlog.bak"
    stray.write_text("keep")
    other_uid = tw.root / "claude-99999" / PROJECT / SID
    other_uid.mkdir(parents=True)
    tw.run()
    m = tw.manifest()
    paths = {r["path"] for r in m["items"] + m["excluded"] + m["untouched"]["entries"]}
    assert str(stray) not in paths and str(other_uid) not in paths
    assert tw.reasons(tw.root / "claude-99999") == {"no_tmp_rule"}


def test_a_scan_cut_by_the_cap_is_never_a_candidate(tw):
    s = tw.session(files=20)
    tw.rules["tmp"]["scan"]["max_entries"] = 5
    tw.write_rules()
    tw.run()
    assert tw.reasons(s) == {"scan_incomplete"}


# ── 2. git trees inside a scratch dir ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tw):
    bare = tw.tmp / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    dev = tw.tmp / "dev"
    sh("git", "clone", "-q", str(bare), str(dev))
    (dev / "README.md").write_text("hi\n")
    sh("git", "add", "-A", cwd=dev)
    sh("git", "commit", "-q", "-m", "init", cwd=dev)
    sh("git", "push", "-q", "origin", "HEAD:main", cwd=dev)
    sh("git", "fetch", "-q", "origin", cwd=dev)
    return dev


def _worktree(dev: Path, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sh("git", "worktree", "add", "-q", "--detach", str(path), "origin/main", cwd=dev)
    return path


def test_a_registered_clean_worktree_is_removed_through_git_worktree_remove(tw, repo, monkeypatch):
    s = tw.session()
    wt = _worktree(repo, s / "wt" / "agent-1")
    assert tw.run() == 0
    r = tw.result(s)
    assert r["candidate"] is True, r["reasons"]
    assert [(g["kind"], g["registered"]) for g in r["git_trees"]] == [("git_worktree", True)]
    calls: list = []
    real_git = DH._git

    def spy(path, *args, **kw):
        calls.append((str(path), args[:2]))
        return real_git(path, *args, **kw)

    monkeypatch.setattr(DH, "_git", spy)
    monkeypatch.setenv(DH.GRANT_ENV, "grant-t")
    assert tw.run("--apply", now=NOW + timedelta(hours=1)) == 0
    assert (str(repo), ("worktree", "remove")) in calls
    assert not s.exists() and not wt.exists()
    assert str(wt) not in sh("git", "worktree", "list", cwd=repo)  # git's own registry no longer lists it
    rep = json.loads(sorted((tw.state / "data/runtime/disk_hygiene").glob("tmp_hygiene_apply_*.json"))[-1].read_text())
    assert rep["removed"][0]["how"].startswith("git worktree remove x1") and rep["reclaimed_files"] == r["file_count"]


def test_a_dirty_worktree_or_a_detached_commit_keeps_the_session(tw, repo):
    s1 = tw.session(SID)
    wt1 = _worktree(repo, s1 / "wt")
    (wt1 / "untracked.txt").write_text("work in progress")
    s2 = tw.session("20037685-f0d9-451f-8b42-2a0f86d3b2e0")
    wt2 = _worktree(repo, s2 / "wt")
    (wt2 / "README.md").write_text("changed\n")
    sh("git", "commit", "-q", "-am", "local only", cwd=wt2)
    tw.run()
    assert tw.reasons(s1) == {"git_tree_dirty"}
    assert tw.reasons(s2) == {"git_unpushed_commits"}


def test_an_unregistered_worktree_is_plain_files(tw):
    s = tw.session()
    wt = s / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {tw.tmp}/gone/.git/worktrees/wt\n")
    tw.run()
    r = tw.result(s)
    assert r["candidate"] is True and r["git_trees"][0]["registered"] is False
    os.environ[DH.GRANT_ENV] = "g"
    try:
        assert tw.run("--apply", now=NOW + timedelta(hours=1)) == 0
    finally:
        del os.environ[DH.GRANT_ENV]
    assert not s.exists()


# ── 3. rule P: pytest temp ────────────────────────────────────────────────────────────────────────────────────────


def test_old_pytest_dirs_are_candidates_recent_ones_and_the_current_symlink_are_not(tw):
    old = tw.pytest_dir("pytest-101")
    new = tw.pytest_dir("pytest-102")
    touch_now(new / "test_a0" / "f")
    os.symlink(str(new), tw.root / f"pytest-of-{USER}" / "pytest-current")
    tw.cwd(5050, Path("/"))
    tw.run()
    assert tw.result(old)["candidate"] is True and tw.result(old)["kind"] == TH.KIND_PYTEST
    assert tw.result(old)["file_count"] == 3
    assert tw.reasons(new) == {"recent_activity"}
    paths = {r["path"] for r in tw.manifest()["items"] + tw.manifest()["excluded"]}
    assert str(tw.root / f"pytest-of-{USER}" / "pytest-current") not in paths


def test_a_pytest_dir_with_an_open_fd_is_kept(tw):
    d = tw.pytest_dir("pytest-7")
    tw.fd(6060, 3, d / "test_a0" / "f")
    tw.run()
    assert tw.reasons(d) == {"open_fd"}


# ── 4. never-touch ────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_non_matching_tmp_entry_is_never_scanned_nor_a_candidate(tw):
    camp = tw.root / "n8n-campaign-20261018"
    (camp / "deep").mkdir(parents=True)
    (camp / "deep" / "x").write_text("x")
    for name in ("tradeai-momentum-lineage-20261013", "momentum-native-abc", "some-random-dir"):
        (tw.root / name).mkdir()
    (tw.root / "loose-file.txt").write_text("x")
    tw.run()
    m = tw.manifest()
    assert m["items"] == []
    assert tw.reasons(camp) == {"never_touch_glob"} and tw.result(camp)["file_count"] is None
    assert tw.reasons(tw.root / "tradeai-momentum-lineage-20261013") == {"never_touch_glob"}
    assert tw.reasons(tw.root / "momentum-native-abc") == {"never_touch_glob"}
    assert tw.reasons(tw.root / "some-random-dir") == {"no_tmp_rule"}
    assert tw.reasons(tw.root / "loose-file.txt") == {"no_tmp_rule"}
    assert m["totals"]["untouched_by_reason"] == {"never_touch_glob": 3, "no_tmp_rule": 2}
    assert m["untouched"]["total"] == 5 and m["excluded"] == []
    tw.rules["tmp"]["untouched_list_max"] = 2
    tw.write_rules()
    tw.run()
    u = tw.manifest()["untouched"]
    assert u["total"] == 5 and [e["reason"].split(":")[0] for e in u["entries"]] == ["never_touch_glob"] * 2


def test_apply_refuses_a_tampered_manifest_item_outside_the_patterns(tw):
    s = tw.session()
    camp = tw.root / "n8n-campaign-x"
    camp.mkdir()
    tw.run()
    mp = tw.state / "data/runtime/disk_hygiene/tmp_hygiene_manifest_latest.json"
    m = json.loads(mp.read_text())
    m["items"] = [dict(m["items"][0], path=str(camp)), dict(m["items"][0], path=str(tw.home))]
    mp.write_text(json.dumps(m))
    os.environ[DH.GRANT_ENV] = "g"
    try:
        assert tw.run("--apply", now=NOW + timedelta(hours=1)) == 0
    finally:
        del os.environ[DH.GRANT_ENV]
    rep = json.loads(sorted((tw.state / "data/runtime/disk_hygiene").glob("tmp_hygiene_apply_*.json"))[-1].read_text())
    assert rep["removed"] == [] and {x["why"] for x in rep["skipped"]} == {"pattern_mismatch", "outside_tmp_root"}
    assert camp.exists() and s.exists() and tw.home.exists()


# ── 5. plan / dry-run / apply contract ────────────────────────────────────────────────────────────────────────────


def test_dry_run_writes_nothing_and_plan_writes_manifest_and_v2_receipt(tw, capsys):
    s = tw.session()
    assert tw.run("--dry-run", "--report") == 0
    out = capsys.readouterr().out
    assert "DRY-RUN " in out and "CANDIDATES 1" in out and "inodes" in out and not tw.state.exists()
    assert tw.run() == 0
    rec = json.loads((tw.state / "data/runtime/tmp-hygiene_last.json").read_text())
    assert rec["status"] == "ok" and rec["produced_count"] == 1 and rec["summary"]["reclaimable_files"] == 7
    assert s.exists()  # the plan deletes nothing


def test_apply_needs_the_grant_never_runs_under_the_executor_and_refuses_stale(tw):
    s = tw.session()
    tw.run()
    assert tw.run("--apply") == 1
    os.environ[DH.GRANT_ENV] = "g"
    os.environ[DH.RUN_ID_ENV] = "d:tmp-hygiene:live:x"
    try:
        assert tw.run("--apply") == 1
        del os.environ[DH.RUN_ID_ENV]
        assert tw.run("--apply", now=NOW + timedelta(hours=25)) == 1
        rep = json.loads(sorted((tw.state / "data/runtime/disk_hygiene").glob("tmp_hygiene_apply_*.json"))[-1]
                         .read_text())
        assert rep["refused"] == "manifest_stale"
    finally:
        os.environ.pop(DH.GRANT_ENV, None)
        os.environ.pop(DH.RUN_ID_ENV, None)
    assert s.exists()


def test_apply_skips_a_changed_item_and_stops_at_the_file_cap(tw):
    a = tw.session(SID, files=3)
    b = tw.session("1bdde23e-0969-41c0-b879-b775aad44e91", files=3)
    c = tw.session("229f45b3-bc93-4dbd-a915-8016c13fc9bf", files=3)
    tw.run()
    (a / "scratchpad" / "late").write_text("x")  # changed since the manifest (new entry, still idle by mtime)
    os.utime(a / "scratchpad" / "late", (0, 0))
    tw.rules["tmp"]["apply"]["max_files_per_run"] = 6
    tw.write_rules()
    os.environ[DH.GRANT_ENV] = "g"
    try:
        tw.run("--apply", now=NOW + timedelta(hours=1))
    finally:
        del os.environ[DH.GRANT_ENV]
    rep = json.loads(sorted((tw.state / "data/runtime/disk_hygiene").glob("tmp_hygiene_apply_*.json"))[-1].read_text())
    why = {Path(x["path"]).name: x["why"] for x in rep["skipped"]}
    assert why[a.name].startswith(("changed_since_manifest", "rule_now_fails")) and a.exists()
    assert [Path(x["path"]).name for x in rep["removed"]] == [b.name] and not b.exists()
    assert why[c.name] == "file_cap" and c.exists()


# ── 6. the monitor: inode bands ───────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mon(tw, monkeypatch):
    ledger = tw.state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    ledger.parent.mkdir(parents=True)
    CoordinationLedger(ledger).close()
    tw.rules["monitor"]["mounts"] = ["/", str(tw.root)]
    tw.rules["monitor"]["consumer_categories"] = []
    tw.rules["monitor"]["inodes"]["top_dirs"]["mounts"] = [str(tw.root)]
    tw.write_rules()
    byte_pct = {"/": 50.0, str(tw.root): 10.0}
    ino_pct = {"/": 30.0, str(tw.root): 10.0}

    def fake_measure(mount):
        size = 1000 * 1024 ** 3
        used = int(size * byte_pct[mount] / 100)
        return {"mount": mount, "used_pct": byte_pct[mount], "used_bytes": used, "avail_bytes": size - used,
                "size_bytes": size}

    def fake_inodes(mount):
        total = 1_048_576
        used = int(total * ino_pct[mount] / 100)
        return {"mount": mount, "inodes_used_pct": ino_pct[mount], "inodes_used": used, "inodes_total": total,
                "inodes_free": total - used, "avail_bytes": 20 * 1024 ** 3}

    monkeypatch.setattr(DM, "measure", fake_measure)
    monkeypatch.setattr(DM, "measure_inodes", fake_inodes)
    clock = {"t": NOW}

    def run(*extra: str) -> int:
        clock["t"] += timedelta(minutes=15)
        return DM.main(["--apply", "--rules", str(tw.rules_path), "--state-root", str(tw.state), "--ledger",
                        str(ledger), "--now", clock["t"].isoformat(), *extra])

    def intents() -> list[tuple]:
        c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
        try:
            return c.execute("SELECT kind, subject, summary FROM comms_intents ORDER BY first_at").fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            c.close()

    return types.SimpleNamespace(run=run, intents=intents, byte=byte_pct, ino=ino_pct, tw=tw, root=str(tw.root))


def test_measure_inodes_reads_statvfs_and_skips_a_filesystem_without_an_inode_limit(monkeypatch):
    st = types.SimpleNamespace(f_files=1_048_576, f_ffree=31_457, f_bavail=5_000_000, f_frsize=4096)
    monkeypatch.setattr(DM.os, "statvfs", lambda m: st)
    m = DM.measure_inodes("/tmp")
    assert m["inodes_used"] == 1_048_576 - 31_457 and m["inodes_used_pct"] == 97.0
    assert m["avail_bytes"] == 5_000_000 * 4096
    monkeypatch.setattr(DM.os, "statvfs", lambda m: types.SimpleNamespace(f_files=0, f_ffree=0, f_bavail=1,
                                                                          f_frsize=1))
    assert DM.measure_inodes("/btrfs") is None


def test_inode_bands_alert_once_per_change_and_apart_from_the_byte_bands(mon):
    # a short mount key ("/tmp", faked: no statvfs, no scan) keeps the 120-char subjects whole on any CI tmp path
    r = "/tmp"
    mon.tw.rules["monitor"]["mounts"] = ["/", r]
    mon.tw.rules["monitor"]["inodes"]["top_dirs"]["mounts"] = []
    mon.tw.write_rules()
    mon.byte[r] = 10.0
    mon.ino[r] = 10.0
    assert mon.run() == 0 and mon.intents() == []
    mon.ino[r] = 85.0
    assert mon.run() == 0
    mon.ino[r] = 88.0
    assert mon.run() == 0  # same band, higher percent: no new intent
    mon.byte[r] = 82.0  # bytes cross too: their own band, their own intent
    assert mon.run() == 0
    mon.ino[r] = 97.0
    assert mon.run() == 0
    mon.ino[r] = 40.0
    mon.byte[r] = 10.0
    assert mon.run() == 0
    got = [(k, s) for k, s, _ in mon.intents()]
    assert got == [
        ("disk_usage_warn", "Disk /tmp INODES WARN: at or above 80% inodes used"),
        ("disk_usage_warn", "Disk /tmp WARN: at or above 80% used"),
        ("disk_usage_critical", "Disk /tmp INODES CRITICAL: at or above 90% inodes used"),
        ("disk_usage_recovered", "Disk /tmp INODES recovered: below 80% inodes used"),
        ("disk_usage_recovered", "Disk /tmp recovered: below 80% used"),
    ]
    state = json.loads((mon.tw.state / "data/runtime/disk_usage_monitor_state.json").read_text())
    assert state["inodes"][r]["band"] == "ok" and state["mounts"][r]["band"] == "ok"
    assert state["inodes"]["/"]["band"] == "ok"


def test_inode_thresholds_are_config_and_must_be_ordered(mon):
    mon.tw.rules["monitor"]["inodes"]["warn_pct"] = 50.0
    mon.tw.write_rules()
    mon.ino[mon.root] = 55.0
    assert mon.run() == 0 and mon.intents()[0][0] == "disk_usage_warn"
    mon.tw.rules["monitor"]["inodes"]["critical_pct"] = 40.0
    mon.tw.write_rules()
    assert mon.run() == 1


def test_the_inode_alert_names_the_top_dirs_by_file_count_and_the_tmp_plan(mon):
    tw = mon.tw
    big = tw.session(files=60)
    tw.session("77a6de60-3513-40ce-9220-25d684930e93", files=2)
    camp = tw.root / "n8n-campaign-20261018"
    for i in range(3):
        (camp / f"part{i}").mkdir(parents=True)
        for j in range(8):
            (camp / f"part{i}" / f"f{j}").write_text("x")
    tw.run()  # a tmp plan for the summary
    mon.ino[mon.root] = 97.0
    assert mon.run() == 0
    kind, subject, summary = mon.intents()[0]
    assert kind == "disk_usage_critical" and subject.startswith("Disk ")  # (the store clips a long tmp-path subject)
    assert len(summary) <= 300 and "97.0% inodes used" in summary
    top = summary.split("top files: ")[1]
    assert top.index("0549bb07") < top.index("n8n-camp")  # the dominant session first, then the spread campaign dir
    assert "tmp plan" in summary and "files reclaimable" in summary
    st = json.loads((tw.state / "data/runtime/disk-usage-monitor_last.json").read_text())
    row = [x for x in st["summary"]["inodes"] if x["mount"] == mon.root][0]
    assert row["top_dirs"]["dirs"][0][0] == str(big) and "INODES CRITICAL" in row["subject"]


def test_top_file_dirs_descends_only_while_one_child_dominates_and_is_bounded(tmp_path):
    root = tmp_path / "t"
    s = root / "claude-1" / "proj" / "sess"
    s.mkdir(parents=True)
    for i in range(30):
        (s / f"f{i}").write_text("x")
    (root / "claude-1" / "proj" / "other").mkdir()
    spread = root / "spread"
    for i in range(4):
        (spread / f"d{i}").mkdir(parents=True)
        for j in range(5):
            (spread / f"d{i}" / f"f{j}").write_text("x")
    os.symlink(str(spread), root / "link-to-spread")
    cfg = {"max_depth": 3, "dominant_share": 0.5, "time_cap_s": 30, "max_entries": 10_000, "top_n": 3}
    got = DM.top_file_dirs(str(root), cfg)
    dirs = dict(got["dirs"])
    # each count includes the dir's own entry: 30 files + sess; 4 dirs + 20 files + spread
    assert dirs[str(s)] == 31 and dirs[str(spread)] == 25 and not got["partial"]
    assert str(root / "link-to-spread") in dirs and dirs[str(root / "link-to-spread")] == 1  # never followed
    small = DM.top_file_dirs(str(root), {**cfg, "max_entries": 5})
    assert small["partial"] is True


def test_monitor_and_tmp_hygiene_import_no_sender():
    src = (ROOT / "scripts" / "tmp_hygiene.py").read_text() + (ROOT / "scripts" / "disk_usage_monitor.py").read_text()
    for bad in ("telegram_alert", "send_telegram", "requests", "urllib", "psycopg", "import host_comms_intents",
                "lib.host_comms_intents import", "n8n_coordination_gateway import"):
        assert bad not in src, bad


# ── 7. committed config and n8n wiring ────────────────────────────────────────────────────────────────────────────


def test_the_committed_rules_hold_the_operator_numbers():
    doc = _load("disk_hygiene_rules.json")
    mon = doc["monitor"]
    assert "/tmp" in mon["mounts"] and "/" in mon["mounts"]
    assert mon["inodes"]["warn_pct"] == 80.0 and mon["inodes"]["critical_pct"] == 90.0
    assert mon["inodes"]["top_dirs"]["max_depth"] <= 3 and mon["inodes"]["top_dirs"]["mounts"] == ["/tmp"]
    t = doc["tmp"]
    assert t["root"] == "/tmp" and t["claude_scratch"]["idle_days"] == 2
    assert t["claude_scratch"]["transcript_idle_days"] == 2 and t["pytest"]["older_than_days"] == 1
    assert t["claude_scratch"]["dir_name"] == "claude-{uid}" and t["pytest"]["dir_name"] == "pytest-of-{user}"
    for g in ("n8n-campaign-*", "tradeai-*", "momentum-*"):
        assert g in t["never_touch_globs"]
    rules = DH.load_rules(CONFIG / "disk_hygiene_rules.json")
    tr = TH.tmp_rules(rules, uid=1000, user="johnclaw")
    assert tr["_claude_dir"] == "claude-1000" and tr["_pytest_dir"] == "pytest-of-johnclaw"


def test_registry_row_is_a_daily_dispatch_live_n8n_lane_at_canary():
    row = {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}["tmp-hygiene"]
    assert (row["scheduler"]["kind"], row["scheduler"]["expression"], row["scheduler"]["stage"]) == (
        "n8n", "dispatcher", "canary")
    assert row["scheduler"]["match"] == "scripts/tmp_hygiene.py"
    assert row["dispatch"]["mode"] == "live" and row["dispatch"]["cron"] == ["0 5 * * *"]
    assert row["dispatch"]["tz"] == "America/New_York" and row["expected_cadence_hours"] == 24.0
    assert LD.dispatch_eligible(row) == (True, "eligible") and LD.forbidden_hits(row) == []
    assert LD.parse_dispatch_block(row).klass == "hygiene"
    assert row["output_signal"] == {"kind": "json_key", "path": "data/runtime/tmp-hygiene_last.json", "key": "ok_at"}


def test_allowlist_entry_is_plan_only_and_enforced():
    e = {x["lane_id"]: x for x in _load("n8n_run_allowlist.json")["lanes"]}["tmp-hygiene"]
    assert e["command"] == ["$PY", "scripts/tmp_hygiene.py"] and e["live_arg"] == ["--plan"]
    assert e["dry_run_arg"] == ["--dry-run"] and e["lock_kind"] == "flock" and e["output_receipt"] == "v2"
    assert "--apply" not in json.dumps({k: e[k] for k in ("command", "live_arg", "dry_run_arg")})
    assert e["env_allowlist_mode"] == "enforce" and e["market_gate"] is False
    assert TH.main(["--apply", "--dry-run"]) == 2 and TH.main(["--plan", "--apply"]) == 2
    assert (TH.GRANT_ENV, TH.RUN_ID_ENV) == (DH.GRANT_ENV, DH.RUN_ID_ENV)
    assert set(e["env_names"]) == {"TRADEAI_DISK_HYGIENE_GRANT", "TRADEAI_PERSISTENT_STATE_ROOT"}


def test_health_contract_is_reviewed_with_an_output_rule_matching_the_code():
    hc = {c["id"]: c for c in _load("n8n_health_contracts.json")["contracts"]}["tmp-hygiene"]
    allow = {x["lane_id"]: x for x in _load("n8n_run_allowlist.json")["lanes"]}["tmp-hygiene"]
    assert hc["status"] == "REVIEWED" and hc["stage"] == "canary" and hc["workflow_id"] == "dispatcher"
    assert H.validate_contract(hc) == [] and H.unknown_fields(hc) == []
    eo = hc["expected_output"]
    assert OV.validate_expected_output(eo) == [] and eo["rule"] == "min_produced" and eo["min_produced"] == 1
    assert hc["baseline"]["timeout_s"] == allow["timeout_s"]
    assert hc["baseline"]["freshness_degraded_after_h"] == 48.0
    assert TH.lane_output({"totals": {"candidates": 0, "reclaimable_bytes": 0, "reclaimable_files": 0,
                                      "excluded": 0}}, True)["produced_count"] == 1
    assert TH.lane_output(None, False)["skipped_reasons"] == {"dependency_unavailable": 1}
    res = H.check(_load("n8n_health_contracts.json"), _load("lane_registry.json"), H.load_json(H.GENERIC_INDEX_PATH))
    assert not [e for e in res["errors"] if "tmp-hygiene" in e]


# ── 8. the operator packet ────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def pk(tw, tmp_path):
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PY": sys.executable, "REPO": str(ROOT),
           "SERVED": str(ROOT), "STATE": str(tw.state), "LIVE_LANES_ENV": str(tmp_path / "none.env"),
           "SYSTEMCTL_BIN": "false", "DOCKER_BIN": "false", "PROC_ROOT": str(tw.proc),
           "HYGIENE_EXTRA": f"--rules {tw.rules_path} --now {NOW.isoformat()}"}

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(PACKET / "cutover.sh"), *args], env={**env, **extra}, capture_output=True,
                              text=True, timeout=300, cwd=str(tmp_path))

    return run


def test_packet_tmp_dry_scans_only_the_rules_root_and_writes_nothing(tw, pk):
    s = tw.session()
    p = pk("tmp-dry")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DRY RUN" in p.stdout and "CANDIDATES 1" in p.stdout and str(tw.root) in p.stdout
    assert not tw.state.exists() and s.exists()


def test_packet_tmp_apply_is_dry_by_default_and_needs_the_grant(tw, pk):
    p = pk("tmp-apply")
    assert p.returncode == 1 and "no /tmp manifest" in p.stdout
    s = tw.session()
    tw.run()
    p = pk("tmp-apply")
    assert p.returncode == 0 and "DRY RUN" in p.stdout and "1 candidates" in p.stdout and s.exists()
    p = pk("tmp-apply", "--apply")
    assert p.returncode == 1 and "TRADEAI_DISK_HYGIENE_GRANT not set" in p.stdout
    p = pk("tmp-apply", "--apply", TRADEAI_DISK_HYGIENE_GRANT="g", TRADEAI_RUN_ID="d:x")
    assert p.returncode == 1 and "never runs under the n8n executor" in p.stdout
    assert s.exists()
