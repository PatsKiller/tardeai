"""Disk hygiene rules + disk-usage monitor on the n8n fabric (operator 2026-10-18).

"a script with rules that's repeatable, n8n should run this weekly; and also monitor when a threshold is over 80%,
fix and move to n8n where monitored." Pins every rule of scripts/disk_hygiene.py on hermetic tmp git repos and
worktrees (dirty, untracked, unpushed, unmerged, in-use cwd, referenced by the crontab, recent activity, the hard
never-touch list, ignored credential files, not-owned repos, release keep-N / previous served / hold_until, caches),
the plan/dry-run/apply contract (manifest staleness, re-validation skip, item and byte caps, grant required, never
under the n8n executor, `git worktree remove` for linked worktrees), scripts/disk_usage_monitor.py bands and
dedupe-by-band through a tmp coordination ledger, the n8n wiring (registry rows, allowlist entries, REVIEWED health
contracts, host intent routes) and the operator packet against fakes.

Hermetic: tmp homes, tmp bare remotes, GIT_CONFIG_GLOBAL=/dev/null, tmp state roots and ledgers, a fake /proc and a
fake crontab. No live home directory, ledger, service, n8n or Telegram.

COVERS = ["scripts/disk_hygiene.py", "scripts/disk_usage_monitor.py", "config/disk_hygiene_rules.json",
          "config/host_comms_intent_routes.json", "config/lane_registry.json", "config/n8n_run_allowlist.json",
          "config/n8n_health_contracts.json", "docs/ops/packets/disk-hygiene-n8n-20261018/cutover.sh"]
"""

from __future__ import annotations

import json
import os
import re
import shutil
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
from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib import n8n_health_contracts as H  # noqa: E402
from scripts.lib import n8n_output_verdict as OV  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

CONFIG = ROOT / "config"
PACKET = ROOT / "docs" / "ops" / "packets" / "disk-hygiene-n8n-20261018"
SCRIPT = PACKET / "cutover.sh"
LANES = ("disk-usage-monitor", "disk-hygiene")
#: plans run 30 days after the fixtures are built, so everything is idle unless a test touches it to "now"
NOW = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=30)


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    """The Telegram chokepoints are stubs that fail: no path in this file may reach one."""
    calls: list[tuple] = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was called")

    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = boom
    fake.record_operator_message = boom
    for name in ("telegram_alert", "scripts.telegram_alert"):
        monkeypatch.setitem(sys.modules, name, fake)
    yield calls
    assert calls == []


# ── fixtures: a tmp home with a bare remote, a dev clone and worktrees ─────────────────────────────────────────────


def sh(*args: str, cwd: Path | None = None) -> str:
    p = subprocess.run(list(args), cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout


class World:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.bare = tmp / "remote" / "tardeai.git"
        self.other_bare = tmp / "remote" / "nyc-dof.git"
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.bare))
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.other_bare))
        self.dev = self.home / "dev"
        sh("git", "clone", "-q", str(self.bare), str(self.dev))
        (self.dev / "README.md").write_text("hello\n")
        (self.dev / ".gitignore").write_text(".env\n*.log\nnode_modules/\n")
        sh("git", "add", "-A", cwd=self.dev)
        sh("git", "commit", "-q", "-m", "init", cwd=self.dev)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.dev)
        sh("git", "fetch", "-q", "origin", cwd=self.dev)
        self.proc = tmp / "proc"
        self.proc.mkdir()
        self.crontab = tmp / "crontab.txt"
        self.crontab.write_text("*/5 * * * * cd /nowhere && true\n")
        self.units = tmp / "units"
        self.units.mkdir()
        self.state = tmp / "state"
        self.rules_path = tmp / "rules.json"
        self.rules = self.default_rules()
        self.write_rules()

    def default_rules(self) -> dict:
        doc = _load("disk_hygiene_rules.json")
        h = str(self.home)
        doc["home"] = h
        doc["protected_paths"]["paths"] = [str(self.dev), f"{h}/rel/ps/CURRENT"]
        nt = doc["never_touch"]
        nt["paths"] = [f"{h}/db_backups", f"{h}/rel/persistent-state", f"{h}/llama-cpp-vulkan"]
        nt["report_only"] = [{"path": f"{h}/llama-cpp-vulkan", "category": "models", "why": "report only"}]
        doc["git"]["roots"] = [{"path": h, "depth": 1}, {"path": f"{h}/worktrees", "depth": 1}]
        doc["git"]["owned_remote_patterns"] = [re.escape(str(self.bare)) + "$"]
        doc["git"]["size_workers"] = 2
        doc["releases"]["pointer_dir"] = f"{h}/rel/ps"
        doc["releases"]["roots"] = [
            {"path": f"{h}/rel/ps", "entry_kind": "dir", "glob": "*-*", "keep_newest": 2, "previous_served": True,
             "hold_until": None},
            {"path": f"{h}/rel/archive", "entry_kind": "file", "glob": "*.tar.zst", "keep_newest": 1,
             "previous_served": False, "hold_until": None},
            {"path": f"{h}/rel", "entry_kind": "dir", "glob": "persistent-*", "keep_newest": 0, "previous_served": False,
             "hold_until": None},
        ]
        doc["caches"]["rules"] = [{"path": f"{h}/.cache/pip", "older_than_days": 29, "item_depth": 1,
                                   "enabled": False}]
        doc["references"] = {"crontab_cmd": ["cat", str(self.crontab)], "systemd_unit_dirs": [str(self.units)],
                             "proc_root": str(self.proc)}
        mon = doc["monitor"]
        mon["consumer_categories"] = [{"category": "models", "path": f"{h}/llama-cpp-vulkan"}]
        return doc

    def write_rules(self) -> None:
        self.rules_path.write_text(json.dumps(self.rules, indent=1))

    def worktree(self, name: str, *, parent: Path | None = None) -> Path:
        path = (parent or self.home) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        sh("git", "worktree", "add", "-q", "--detach", str(path), "origin/main", cwd=self.dev)
        return path

    def clone(self, name: str, url: Path | None = None) -> Path:
        path = self.home / name
        sh("git", "clone", "-q", str(url or self.bare), str(path))
        if url is not None:
            (path / "f").write_text("x\n")
            sh("git", "add", "-A", cwd=path)
            sh("git", "commit", "-q", "-m", "x", cwd=path)
            sh("git", "push", "-q", "origin", "HEAD:main", cwd=path)
            sh("git", "fetch", "-q", "origin", cwd=path)
        return path

    def plan(self, *extra: str, now: datetime = NOW) -> int:
        return DH.main(["--rules", str(self.rules_path), "--state-root", str(self.state), "--now", now.isoformat(),
                        *extra])

    def manifest(self) -> dict:
        return json.loads((self.state / "data/runtime/disk_hygiene/disk_hygiene_manifest_latest.json").read_text())

    def result(self, path: Path) -> dict:
        m = self.manifest()
        for r in m["items"] + m["excluded"]:
            if r["path"] == str(path):
                return r
        raise KeyError(path)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@e"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@e")):
        monkeypatch.setenv(k, v)
    for k in (DH.GRANT_ENV, DH.RUN_ID_ENV, "TRADEAI_STATE_ROOT", "TRADEAI_N8N_COORDINATION_LEDGER"):
        monkeypatch.delenv(k, raising=False)
    return World(tmp_path)


def _reasons(world: World, path: Path) -> set[str]:
    return {r.split(":", 1)[0] for r in world.result(path)["reasons"]}


# ── 1. rule G: every check, one at a time ─────────────────────────────────────────────────────────────────────────


def test_a_clean_merged_idle_linked_worktree_is_a_candidate_with_evidence(world):
    wt = world.worktree("wt-clean")
    assert world.plan() == 0
    r = world.result(wt)
    assert r["candidate"] is True and r["kind"] == "git_worktree" and r["rule"] == "G"
    assert r["main_repo"] == str(world.dev) and r["size_bytes"] > 0
    assert r["evidence"]["merged"] == "ancestor" and r["evidence"]["idle_days"] > 7
    assert set(r["fingerprint"]) == {"head", "last_activity", "kind"}
    assert wt.exists()  # a plan deletes nothing


def test_the_dev_repo_itself_is_protected(world):
    world.plan()
    assert _reasons(world, world.dev) == {"protected"}


def test_dirty_untracked_and_unpushed_trees_are_excluded(world):
    dirty, untracked, unpushed = world.worktree("wt-dirty"), world.worktree("wt-untracked"), world.worktree("wt-unp")
    (dirty / "README.md").write_text("changed\n")
    (untracked / "notes.txt").write_text("new\n")
    (unpushed / "x.txt").write_text("x\n")
    sh("git", "add", "x.txt", cwd=unpushed)
    sh("git", "commit", "-q", "-m", "local only", cwd=unpushed)
    world.plan()
    assert "dirty" in _reasons(world, dirty)
    assert _reasons(world, untracked) == {"untracked"}
    assert {"unpushed_commits", "not_merged"} <= _reasons(world, unpushed)


def test_pushed_but_unmerged_work_is_excluded_as_not_merged(world):
    wt = world.worktree("wt-feature")
    (wt / "y.txt").write_text("y\n")
    sh("git", "add", "y.txt", cwd=wt)
    sh("git", "commit", "-q", "-m", "feature", cwd=wt)
    sh("git", "push", "-q", "origin", "HEAD:refs/heads/feature", cwd=wt)
    sh("git", "fetch", "-q", "origin", cwd=world.dev)
    world.plan()
    assert _reasons(world, wt) == {"not_merged"}


def test_a_process_cwd_inside_the_tree_excludes_it(world):
    wt = world.worktree("wt-busy")
    (world.proc / "4242").mkdir()
    (world.proc / "4242" / "cwd").symlink_to(wt / "")
    (world.proc / "self-not-a-pid").mkdir()
    world.plan()
    r = world.result(wt)
    assert {x.split(":")[0] for x in r["reasons"]} == {"in_use_cwd"} and r["evidence"]["in_use_cwd"] == str(wt)


def test_a_crontab_or_systemd_reference_excludes_it(world):
    by_cron, by_unit = world.worktree("wt-cron"), world.worktree("wt-unit")
    world.crontab.write_text(f"*/5 * * * * cd {by_cron} && ./run.sh\n")
    (world.units / "x.service").write_text(f"[Service]\nWorkingDirectory={by_unit}\n")
    world.plan()
    assert _reasons(world, by_cron) == {"referenced"} and world.result(by_cron)["evidence"]["referenced_by"] == "crontab"
    assert _reasons(world, by_unit) == {"referenced"}
    # a path that only shares a prefix is not a reference
    assert DH.referenced_by(Path(f"{by_cron}-2"), [("crontab", world.crontab.read_text())]) is None


def test_recent_activity_excludes_it(world):
    wt = world.worktree("wt-recent")
    t = (NOW - timedelta(days=1)).timestamp()
    os.utime(wt / "README.md", (t, t))
    world.plan()
    assert _reasons(world, wt) == {"recent_activity"}


def test_a_reflog_rewrite_mtime_is_not_activity_but_its_newest_entry_is(world, tmp_path):
    log = tmp_path / "HEAD.log"
    log.write_text("0 1 t <t@e> 1700000000 +0000\tcommit: a\n1 2 t <t@e> 1700000500 -0400\tcommit: b\n")
    assert DH.last_reflog_ts(log) == 1700000500.0
    assert DH.last_reflog_ts(tmp_path / "absent") == 0.0


def test_the_never_touch_list_is_enforced_before_any_rule(world):
    token = world.worktree("wt-token-refresh")
    backups = world.worktree("db_backups")  # a never-touch PATH, even when it is a clean merged worktree
    world.plan()
    assert _reasons(world, token) == {"never_touch_glob"}
    assert _reasons(world, backups) == {"never_touch_path"}
    rules = DH.load_rules(world.rules_path)
    for p in ("rel/persistent-state/x", "llama-cpp-vulkan/models/a.gguf", "x/.ssh/id_rsa", "proj/.env",
              "a/cookies.json", "a/credentials.json", ".config/systemd"):
        assert DH.never_touch_reason(world.home / p, rules), p
    assert DH.never_touch_reason(world.home, rules).startswith("contains_never_touch_path")
    assert DH.never_touch_reason(world.home / "wt-ok", rules) is None


def test_an_ignored_credential_file_keeps_the_tree_but_vendored_names_do_not(world):
    secret, vendored = world.worktree("wt-dotenv"), world.worktree("wt-vendored")
    (secret / ".env").write_text("NOT_A_REAL_VALUE=1\n")
    (vendored / "node_modules" / "@babel").mkdir(parents=True)
    (vendored / "node_modules" / "@babel" / "token-map.js").write_text("//\n")
    world.plan()
    assert _reasons(world, secret) == {"ignored_credential_like"}
    assert world.result(secret)["evidence"]["ignored_credential_like"] == [".env"]
    assert world.result(vendored)["candidate"] is True


def test_another_applications_repo_is_never_owned(world):
    other = world.clone("nyc-dof", url=world.other_bare)
    world.plan()
    assert _reasons(world, other) == {"not_owned_repo"}


def test_a_standalone_clone_needs_every_branch_pushed_and_no_stash(world):
    ok, branchy, stashy = world.clone("tradeai-clone-ok"), world.clone("tradeai-clone-b"), world.clone("tradeai-clone-s")
    sh("git", "checkout", "-q", "-b", "side", cwd=branchy)
    (branchy / "s.txt").write_text("s\n")
    sh("git", "add", "s.txt", cwd=branchy)
    sh("git", "commit", "-q", "-m", "side", cwd=branchy)
    sh("git", "checkout", "-q", "main", cwd=branchy)
    (stashy / "README.md").write_text("wip\n")
    sh("git", "stash", "-q", cwd=stashy)
    world.plan()
    assert world.result(ok)["candidate"] is True and world.result(ok)["kind"] == "git_clone"
    assert _reasons(world, branchy) == {"unpushed_local_branch"}
    assert _reasons(world, stashy) == {"has_stash"}


def test_a_locked_worktree_and_a_symlinked_tree_are_kept(world):
    locked = world.worktree("wt-locked")
    sh("git", "worktree", "lock", str(locked), cwd=world.dev)
    (world.home / "wt-link").symlink_to(world.worktree("wt-target", parent=world.home / "worktrees"))
    world.plan()
    assert _reasons(world, locked) == {"worktree_locked"}
    assert all(r["path"] != str(world.home / "wt-link") for r in world.manifest()["items"])


def test_an_agent_worktree_nested_in_the_protected_repo_is_judged_on_its_own(world):
    rules = world.rules
    rules["git"]["roots"].append({"path": str(world.dev / ".claude" / "worktrees"), "depth": 1})
    world.write_rules()
    agent = world.worktree("agent-1", parent=world.dev / ".claude" / "worktrees")
    (world.dev / ".gitignore").write_text(".env\n*.log\nnode_modules/\n.claude/\n")
    world.plan()
    assert world.result(agent)["candidate"] is True
    assert _reasons(world, world.dev) == {"protected"}  # the repo itself still is


# ── 2. rule R (releases) and rule C (caches) ──────────────────────────────────────────────────────────────────────


def _releases(world: World) -> list[Path]:
    ps = world.home / "rel" / "ps"
    names = [f"aaa{i}-main-exact-2026100{i}-120000" for i in range(1, 7)]
    out = []
    for n in names:
        (ps / n).mkdir(parents=True)
        (ps / n / "f").write_text(n)
        out.append(ps / n)
    (ps / "CURRENT").symlink_to(out[3])  # the 4th is served
    (ps / "EXPECTED_RELEASE").write_text(str(out[3]) + "\n")
    (ps / "ACTIVE_RELEASE").write_text(str(out[3]) + "\n")
    return out


def test_releases_keep_current_previous_served_and_the_newest_n(world):
    rel = _releases(world)
    world.plan()
    cand = {r["path"] for r in world.manifest()["items"] if r["rule"] == "R"}
    assert cand == {str(rel[0]), str(rel[1])}
    assert "previous_served" in _reasons(world, rel[2])
    assert {"pointer_symlink", "protected"} & _reasons(world, rel[3])
    assert _reasons(world, rel[4]) == {"keep_newest"} and _reasons(world, rel[5]) == {"keep_newest"}


def test_persistent_state_is_never_a_release_candidate(world):
    ps = world.home / "rel" / "persistent-state"
    ps.mkdir(parents=True)
    (ps / "data").mkdir()
    world.plan()
    assert _reasons(world, ps) == {"never_touch_path"}


def test_an_archive_hold_until_date_holds_every_entry(world):
    arch = world.home / "rel" / "archive"
    arch.mkdir(parents=True)
    for i in range(3):
        (arch / f"r{i}-2026080{i}-120000.tar.zst").write_bytes(b"z" * 10)
    (arch / "README_TRIPWIRE.md").write_text("keep\n")
    world.plan()
    assert sorted(Path(r["path"]).name for r in world.manifest()["items"] if r["rule"] == "R") == [
        "r0-20260800-120000.tar.zst", "r1-20260801-120000.tar.zst"]
    world.rules["releases"]["roots"][1]["hold_until"] = (NOW + timedelta(days=1)).date().isoformat()
    world.write_rules()
    world.plan()
    assert not [r for r in world.manifest()["items"] if r["rule"] == "R"]
    assert _reasons(world, arch / "r0-20260800-120000.tar.zst") == {"hold_until"}


def test_cache_rule_is_off_by_default_and_age_gated_when_on(world):
    pip = world.home / ".cache" / "pip"
    (pip / "old").mkdir(parents=True)
    (pip / "old" / "a").write_text("a")
    (pip / "new").mkdir()
    (pip / "new" / "b").write_text("b")
    t = (NOW - timedelta(days=1)).timestamp()
    os.utime(pip / "new" / "b", (t, t))
    world.plan()
    assert not [r for r in world.manifest()["items"] if r["rule"] == "C"]
    world.rules["caches"]["rules"][0]["enabled"] = True
    world.write_rules()
    world.plan()
    assert [Path(r["path"]).name for r in world.manifest()["items"] if r["rule"] == "C"] == ["old"]
    assert _reasons(world, pip / "new") == {"recent_activity"}


# ── 3. plan / dry-run / receipt ───────────────────────────────────────────────────────────────────────────────────


def test_dry_run_writes_nothing_and_plan_writes_manifest_and_v2_receipt(world, monkeypatch, capsys):
    world.worktree("wt-clean")
    assert world.plan("--dry-run") == 0
    assert not world.state.exists()
    assert "DRY-RUN " in capsys.readouterr().out
    monkeypatch.setenv("TRADEAI_RUN_ID", "d:disk-hygiene:live:20261018T0400")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    assert world.plan() == 0
    rec = json.loads((world.state / "data/runtime/disk-hygiene_last.json").read_text())
    assert rec["status"] == "ok" and rec["produced_count"] == 1 and rec["output_fields"] == "LaneRunReceipt@v2"
    att = json.loads(next((world.state / "data/runtime/lane_attempts/disk-hygiene").glob("*.json")).read_text())
    contract = {c["id"]: c for c in _load("n8n_health_contracts.json")["contracts"]}["disk-hygiene"]
    v = OV.evaluate(contract["expected_output"], att, run_id="d:disk-hygiene:live:20261018T0400",
                    lane_id="disk-hygiene", mode="live")
    assert v["verdict"] == "produced"
    m = world.manifest()
    assert m["schema"] == DH.MANIFEST_SCHEMA and m["totals"]["candidates"] >= 1
    assert m["totals"]["reclaimable_bytes"] == sum(i["size_bytes"] for i in m["items"])
    assert len(list((world.state / "data/runtime/disk_hygiene").glob("disk_hygiene_manifest_2*.json"))) == 1


def test_unreadable_rules_fail_the_run_with_the_fatal_skip(world, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert DH.main(["--rules", str(bad), "--state-root", str(world.state)]) == 1
    rec = json.loads((world.state / "data/runtime/disk-hygiene_last.json").read_text())
    assert rec["status"] == "failed" and rec["skipped_reasons"] == {"dependency_unavailable": 1}


def test_human_summary_lists_largest_candidates_and_exclusion_totals(world):
    world.worktree("wt-a")
    (world.worktree("wt-b") / "u.txt").write_text("u")
    m = DH.plan(DH.load_rules(world.rules_path), NOW)
    text = DH.human_summary(m, 20)
    assert "CANDIDATES 1" in text and "wt-a" in text and "untracked" in text and "REPORT ONLY" in text


# ── 4. apply: grant, staleness, re-validation, caps, removal ──────────────────────────────────────────────────────


def _apply(world: World, now: datetime = NOW, **env) -> int:
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return DH.main(["--apply", "--rules", str(world.rules_path), "--state-root", str(world.state), "--now",
                        now.isoformat()])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _last_apply(world: World) -> dict:
    files = sorted((world.state / "data/runtime/disk_hygiene").glob("disk_hygiene_apply_*.json"))
    return json.loads(files[-1].read_text())


def test_apply_requires_the_grant_and_never_runs_under_the_executor(world):
    wt = world.worktree("wt-clean")
    world.plan()
    assert _apply(world) == 1 and _last_apply(world)["refused"] == f"{DH.GRANT_ENV}_missing"
    assert _apply(world, **{DH.GRANT_ENV: "g1", "TRADEAI_RUN_ID": "d:disk-hygiene:live:x"}) == 1
    assert wt.exists()


def test_apply_refuses_a_stale_manifest(world):
    wt = world.worktree("wt-clean")
    world.plan()
    hours = world.rules["apply"]["manifest_max_age_hours"]
    assert _apply(world, NOW + timedelta(hours=hours + 1), **{DH.GRANT_ENV: "g1"}) == 1
    assert _last_apply(world)["refused"] == "manifest_stale" and wt.exists()


def test_apply_removes_worktrees_with_git_worktree_remove_and_clones_and_releases(world):
    wt, clone = world.worktree("wt-clean"), world.clone("tradeai-clone-ok")
    rel = _releases(world)
    world.plan()
    assert _apply(world, **{DH.GRANT_ENV: "g1"}) == 0
    rep = _last_apply(world)
    assert {r["path"] for r in rep["removed"]} == {str(wt), str(clone), str(rel[0]), str(rel[1])}
    assert {r["how"] for r in rep["removed"] if r["kind"] == "git_worktree"} == {"git worktree remove"}
    assert not wt.exists() and not clone.exists() and not rel[0].exists() and rel[2].exists() and rel[3].exists()
    assert str(wt) not in sh("git", "worktree", "list", "--porcelain", cwd=world.dev)  # no stale registration
    assert rep["reclaimed_bytes"] == sum(r["bytes"] for r in rep["removed"]) and rep["grant"] == "g1"
    assert world.dev.exists()


def test_apply_revalidates_and_skips_anything_that_changed(world):
    a, b = world.worktree("wt-a"), world.worktree("wt-b")
    world.plan()
    (a / "late.txt").write_text("new work after the plan\n")  # now untracked
    sh("git", "checkout", "-q", "--detach", "HEAD~0", cwd=b)
    t = (NOW - timedelta(hours=1)).timestamp()
    os.utime(b / "README.md", (t, t))  # activity after the plan
    assert _apply(world, **{DH.GRANT_ENV: "g1"}) == 0
    rep = _last_apply(world)
    why = {Path(s["path"]).name: s["why"] for s in rep["skipped"]}
    assert why["wt-a"].startswith("rule_now_fails:untracked")
    assert why["wt-b"].startswith("rule_now_fails:recent_activity")
    assert a.exists() and b.exists() and rep["removed"] == []


def test_apply_skips_items_whose_fingerprint_moved(world):
    a = world.worktree("wt-a")
    world.plan()
    mpath = world.state / "data/runtime/disk_hygiene/disk_hygiene_manifest_latest.json"
    m = json.loads(mpath.read_text())
    m["items"][0]["fingerprint"]["head"] = "0" * 40
    mpath.write_text(json.dumps(m))
    assert _apply(world, **{DH.GRANT_ENV: "g1"}) == 0
    assert _last_apply(world)["skipped"] == [{"path": str(a), "why": "changed_since_manifest"}] and a.exists()


def test_apply_stops_at_the_item_and_byte_caps(world):
    for n in ("wt-1", "wt-2", "wt-3"):
        world.worktree(n)
    world.plan()
    world.rules["apply"]["max_items_per_run"] = 1
    world.write_rules()
    assert _apply(world, **{DH.GRANT_ENV: "g1"}) == 0
    rep = _last_apply(world)
    assert len(rep["removed"]) == 1 and [s["why"] for s in rep["skipped"]] == ["item_cap", "item_cap"]
    world.plan()
    world.rules["apply"]["max_items_per_run"] = 10
    world.rules["apply"]["max_bytes_per_run"] = 1
    world.write_rules()
    assert _apply(world, **{DH.GRANT_ENV: "g1"}) == 0
    rep = _last_apply(world)
    assert rep["removed"] == [] and {s["why"] for s in rep["skipped"]} == {"byte_cap"}


def test_apply_rechecks_the_never_touch_list_even_for_a_tampered_manifest(world):
    world.worktree("wt-a")
    world.plan()
    mpath = world.state / "data/runtime/disk_hygiene/disk_hygiene_manifest_latest.json"
    m = json.loads(mpath.read_text())
    target = world.home / "db_backups"
    target.mkdir()
    m["items"].append({**m["items"][0], "path": str(target), "kind": "git_clone"})
    mpath.write_text(json.dumps(m))
    assert _apply(world, **{DH.GRANT_ENV: "g1"}) == 0
    assert any(s["path"] == str(target) and s["why"].startswith("never_touch") for s in _last_apply(world)["skipped"])
    assert target.exists()


# ── 5. the monitor: bands, dedupe by band, intents through a tmp ledger ──────────────────────────────────────────


@pytest.fixture
def mon(world, monkeypatch):
    ledger = world.state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    ledger.parent.mkdir(parents=True)
    CoordinationLedger(ledger).close()  # the gateway creates the ledger; a lane never does
    pct = {"/": 50.0}

    def fake_measure(mount):
        size = 1000 * 1024 ** 3
        used = int(size * pct[mount] / 100)
        return {"mount": mount, "used_pct": pct[mount], "used_bytes": used, "avail_bytes": size - used,
                "size_bytes": size}

    monkeypatch.setattr(DM, "measure", fake_measure)
    clock = {"t": NOW}

    def run(p: float, *extra: str) -> int:
        pct["/"] = p
        clock["t"] += timedelta(minutes=15)
        return DM.main(["--apply", "--rules", str(world.rules_path), "--state-root", str(world.state), "--ledger",
                        str(ledger), "--now", clock["t"].isoformat(), *extra])

    def intents() -> list[tuple]:
        c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
        try:
            return c.execute("SELECT domain, kind, subject, summary, workflow_id FROM comms_intents ORDER BY first_at").fetchall()
        except sqlite3.OperationalError:
            return []
        finally:
            c.close()

    return types.SimpleNamespace(run=run, intents=intents, ledger=ledger, world=world)


def test_band_thresholds_and_transitions():
    m = {"warn_pct": 80.0, "critical_pct": 90.0}
    assert [DM.band_of(p, m) for p in (79.99, 80.0, 89.9, 90.0, 99)] == ["ok", "warn", "warn", "critical", "critical"]
    assert DM.transition(None, "ok") is None and DM.transition("ok", "ok") is None
    assert DM.transition(None, "warn") == "warn" and DM.transition("warn", "warn") is None
    assert DM.transition("critical", "warn") == "warn" and DM.transition("warn", "ok") == "ok"


def test_monitor_alerts_once_per_band_change_never_per_percent(mon):
    assert mon.run(50.0) == 0 and mon.intents() == []  # first run at ok: nothing to say
    assert mon.run(85.0) == 0
    assert mon.run(87.5) == 0  # same band, higher percent: no new intent
    assert mon.run(92.0) == 0
    assert mon.run(91.0) == 0
    assert mon.run(70.0) == 0
    kinds = [(d, k) for d, k, *_ in mon.intents()]
    assert kinds == [("host", "disk_usage_warn"), ("host", "disk_usage_critical"), ("host", "disk_usage_recovered")]
    subjects = [s for _, _, s, _, _ in mon.intents()]
    assert subjects[0] == "Disk / WARN: at or above 80% used" and "%" not in subjects[0].split("80")[0]
    assert all(w == "host.disk_usage_monitor" for *_, w in mon.intents())
    state = json.loads((mon.world.state / "data/runtime/disk_usage_monitor_state.json").read_text())
    assert state["mounts"]["/"]["band"] == "ok"
    rec = json.loads((mon.world.state / "data/runtime/disk-usage-monitor_last.json").read_text())
    assert rec["status"] == "ok" and rec["produced_count"] == 1


def test_monitor_summary_carries_consumers_and_the_manifest_reclaimable(mon):
    mon.world.worktree("wt-clean")
    models = mon.world.home / "llama-cpp-vulkan"
    models.mkdir()
    (models / "m.gguf").write_bytes(b"0" * 8192)
    mon.world.plan()
    assert mon.run(85.0) == 0
    summary = mon.intents()[0][3]
    assert "85.0% used" in summary and "models" in summary.split("top: ")[1] and "reclaimable" in summary
    assert "in 1 items per hygiene manifest" in summary and len(summary) <= 300


def test_a_queue_failure_does_not_record_the_band_so_the_next_run_retries(mon, tmp_path):
    missing = tmp_path / "no-ledger.sqlite"
    assert mon.run(50.0) == 0  # band ok recorded, nothing due
    assert mon.run(85.0, "--ledger", str(missing)) == 1  # warn due, but the ledger is absent
    rec = json.loads((mon.world.state / "data/runtime/disk-usage-monitor_last.json").read_text())
    assert rec["status"] == "failed" and rec["summary"]["mounts"][0]["intent_error"] == "ledger_absent"
    state = json.loads((mon.world.state / "data/runtime/disk_usage_monitor_state.json").read_text())
    assert state["mounts"]["/"]["band"] == "ok"  # not recorded as warn
    assert mon.run(85.0) == 0 and [k for _, k, *_ in mon.intents()] == ["disk_usage_warn"]


def test_monitor_dry_run_writes_and_queues_nothing(mon, capsys):
    DM.main(["--dry-run", "--rules", str(mon.world.rules_path), "--state-root", str(mon.world.state), "--ledger",
             str(mon.ledger), "--now", NOW.isoformat()])
    out = capsys.readouterr().out
    assert "DRY-RUN " in out and mon.intents() == []
    assert not (mon.world.state / "data/runtime/disk_usage_monitor_state.json").exists()
    assert not (mon.world.state / "data/runtime/disk-usage-monitor_last.json").exists()


def test_monitor_refuses_out_of_order_thresholds(world):
    world.rules["monitor"]["warn_pct"] = 95
    world.write_rules()
    assert DM.main(["--dry-run", "--rules", str(world.rules_path), "--state-root", str(world.state)]) == 1


def test_monitor_imports_no_sender():
    src = (ROOT / "scripts" / "disk_usage_monitor.py").read_text() + (ROOT / "scripts" / "disk_hygiene.py").read_text()
    for bad in ("telegram_alert", "send_telegram", "requests", "urllib", "psycopg"):
        assert bad not in src, bad


# ── 6. the committed config and n8n wiring ────────────────────────────────────────────────────────────────────────


def test_the_committed_rules_hold_the_operator_numbers_and_the_hard_list():
    doc = _load("disk_hygiene_rules.json")
    rules = DH.load_rules(CONFIG / "disk_hygiene_rules.json")
    assert doc["monitor"]["warn_pct"] == 80.0 and doc["monitor"]["critical_pct"] == 90.0
    assert doc["monitor"]["host_backstop_pct"] == 95.0
    assert doc["git"]["idle_days"] == 7 and doc["git"]["main_ref"] == "origin/main"
    assert all(c["enabled"] is False for c in doc["caches"]["rules"])
    home = rules["_home"]
    for p in ("db_backups", "trade-ai-releases/persistent-state", "llama-cpp-vulkan", ".ssh", ".config", ".docker"):
        assert DH.never_touch_reason(home / p / "x", rules), p
    assert str(home / "tradeai-exact-main-20260827") in map(str, rules["_protected"])
    assert str(home / "trade-ai-v12-rebuild/trade-ai-v12-rebuild") in map(str, rules["_protected"])


def test_registry_rows_are_dispatch_live_n8n_lanes_at_canary():
    rows = {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}
    want = {"disk-usage-monitor": ("*/15 * * * *", "monitor", 0.25), "disk-hygiene": ("0 4 * * 0", "hygiene", 168.0)}
    for lane, (cron, klass, hours) in want.items():
        row = rows[lane]
        assert (row["scheduler"]["kind"], row["scheduler"]["expression"], row["scheduler"]["stage"]) == (
            "n8n", "dispatcher", "canary")
        assert row["dispatch"]["mode"] == "live" and row["dispatch"]["cron"] == [cron]
        assert row["dispatch"]["tz"] == "America/New_York" and row["expected_cadence_hours"] == hours
        assert LD.dispatch_eligible(row) == (True, "eligible"), lane
        assert LD.parse_dispatch_block(row).klass == klass
        assert LD.forbidden_hits(row) == []
        assert row["output_signal"] == {"kind": "json_key", "path": f"data/runtime/{lane}_last.json", "key": "ok_at"}


def test_allowlist_entries_never_pass_apply_to_the_hygiene_lane():
    allow = {e["lane_id"]: e for e in _load("n8n_run_allowlist.json")["lanes"]}
    hyg, mon = allow["disk-hygiene"], allow["disk-usage-monitor"]
    assert hyg["command"] == ["$PY", "scripts/disk_hygiene.py"] and hyg["live_arg"] == ["--plan"]
    assert mon["command"] == ["$PY", "scripts/disk_usage_monitor.py"] and mon["live_arg"] == ["--apply"]
    for e in (hyg, mon):
        assert e["dry_run_arg"] == ["--dry-run"] and e["lock_kind"] == "flock" and e["output_receipt"] == "v2"
        assert e["market_gate"] is False
    assert "--apply" not in json.dumps({k: hyg[k] for k in ("command", "live_arg", "dry_run_arg")})
    assert hyg["env_allowlist_mode"] == "enforce" and mon["env_allowlist_mode"] == "report"
    assert DH.main(["--apply", "--dry-run"]) == 2 and DH.main(["--plan", "--apply"]) == 2


def test_health_contracts_are_reviewed_with_an_output_rule_matching_the_code():
    hc = {c["id"]: c for c in _load("n8n_health_contracts.json")["contracts"]}
    allow = {e["lane_id"]: e for e in _load("n8n_run_allowlist.json")["lanes"]}
    for lane in LANES:
        c = hc[lane]
        assert c["status"] == "REVIEWED" and c["stage"] == "canary" and c["workflow_id"] == "dispatcher"
        assert H.validate_contract(c) == [] and H.unknown_fields(c) == []
        eo = c["expected_output"]
        assert OV.validate_expected_output(eo) == [] and eo["rule"] == "min_produced" and eo["min_produced"] == 1
        assert "dependency_unavailable" in eo["fatal_skip_reasons"]
        assert c["baseline"]["timeout_s"] == allow[lane]["timeout_s"]
        assert c["alerting"]["failed"]["notifier_priority"] in ("P2", "P3")  # never PAGE from n8n (§24.1)
    res = H.check(_load("n8n_health_contracts.json"), _load("lane_registry.json"), H.load_json(H.GENERIC_INDEX_PATH))
    assert not [e for e in res["errors"] if any(lane in e for lane in LANES)]


def test_host_routes_name_the_monitor_as_the_only_producer_and_no_page():
    from scripts.lib import n8n_fabric_store as F

    routes = F.load_host_intent_routes()["routes"]
    for kind in ("disk_usage_warn", "disk_usage_critical", "disk_usage_recovered"):
        assert routes[("host", kind)]["producer"] == "disk_usage_monitor"
        assert routes[("host", kind)]["tier"] == "DIGEST"
    doc = _load("disk_hygiene_rules.json")["monitor"]
    assert set(doc["intent_kinds"].values()) == {"disk_usage_warn", "disk_usage_critical", "disk_usage_recovered"}
    assert doc["producer"] == "disk_usage_monitor" and doc["intent_domain"] == "host"


def test_the_systemd_guard_is_unchanged_its_backstop_is_a_printed_proposal():
    src = (ROOT / "scripts" / "disk_pressure_guard.py").read_text()
    assert "DEFAULT_USED_PCT = 85.0" in src  # the code default stays; the drop-in passes --used-pct
    from tests.support import disk_hygiene_n8n as S

    assert S.LIVE == LANES


# ── 7. the operator packet against fakes ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def pk(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    calls = tmp_path / "systemctl.calls"
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {calls}\n'
        'case "$*" in *"show -p MainPID"*) echo 4242 ;; *is-active*) echo active ;; esac\n'
    )
    (bin_dir / "docker").write_text("#!/usr/bin/env bash\necho true\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    live = tmp_path / "n8n-live-lanes.env"
    live.write_text("# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-comms-intent-consumer\n")
    live.chmod(0o600)
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "PY": sys.executable,
        "REPO": str(ROOT),
        "SERVED": str(ROOT),
        "STATE": str(state),
        "LEDGER": str(state / "data" / "governance" / "n8n_coordination_ledger.sqlite"),
        "LIVE_LANES_ENV": str(live),
        "SYSTEMCTL_BIN": str(bin_dir / "systemctl"),
        "DOCKER_BIN": str(bin_dir / "docker"),
        "PROC_ROOT": str(proc),
        "RESTART_SETTLE_S": "0",
    }

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                              timeout=300, cwd=str(tmp_path))

    return types.SimpleNamespace(run=run, live=live, proc=proc, calls=calls, state=state, tmp=tmp_path)


def _env_proc(pk, carries: bool) -> None:
    text = "PATH=/usr/bin\0TRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-comms-intent-consumer"
    (pk.proc / "4242" / "environ").write_text(text + (" disk-usage-monitor disk-hygiene\0" if carries else "\0"))


def test_packet_is_dry_by_default_set_f_and_never_deletes_or_touches_cron_or_workflows():
    src = SCRIPT.read_text()
    assert src.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in src and "\nset -f\n" in src
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    for bad in ("rm ", "rm -", "crontab", "n8n import", "import:workflow", "update:workflow", "DELETE ", "DROP ",
                "--force", "deactivate", "UPDATE ", "INSERT ", "rmtree"):
        assert bad not in code, bad
    assert os.access(SCRIPT, os.X_OK)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_packet_passes_shellcheck():
    proc = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout


def test_relay_dry_run_changes_nothing_and_apply_needs_a_grant(pk):
    before = pk.live.read_bytes()
    p = pk.run("relay")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DRY RUN" in p.stdout and "adds: disk-usage-monitor disk-hygiene" in p.stdout
    assert "DISK HYGIENE N8N PR SERVED" in p.stdout
    p = pk.run("relay", "--apply")
    assert p.returncode == 1 and "TRADEAI_FABRIC_GRANT not set" in p.stdout
    assert pk.live.read_bytes() == before and not pk.calls.exists()


def test_relay_apply_appends_both_backs_up_reads_back_and_restarts(pk):
    _env_proc(pk, carries=True)
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert pk.live.read_text() == ("# keep me\nTRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch n8n-comms-intent-consumer "
                                   "disk-usage-monitor disk-hygiene\n")
    assert oct(pk.live.stat().st_mode & 0o777) == "0o600"
    assert len(list(pk.tmp.glob("n8n-live-lanes.env.bak-*-disk-hygiene-n8n-live"))) == 1
    calls = pk.calls.read_text()
    assert "restart tradeai-n8n-run-relay.service" in calls and "restart tradeai-n8n-coordination-gateway.service" in calls
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0 and "already has" in p.stdout


def test_relay_apply_fails_when_a_unit_did_not_pick_up_the_lanes(pk):
    _env_proc(pk, carries=False)
    p = pk.run("relay", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 1 and "env lacks" in p.stdout


def test_rollback_removes_only_the_two_lanes(pk):
    pk.live.write_text("TRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch disk-usage-monitor x disk-hygiene\n")
    p = pk.run("rollback")
    assert p.returncode == 0 and "DRY RUN" in p.stdout and "disk-hygiene" in pk.live.read_text()
    _env_proc(pk, carries=False)
    p = pk.run("rollback", "--apply", TRADEAI_FABRIC_GRANT="g1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert pk.live.read_text() == "TRADEAI_N8N_RELAY_LIVE_LANES=heartbeat-watch x\n"


def test_backstop_prints_the_95_percent_drop_in_and_runs_nothing(pk):
    p = pk.run("backstop")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "PRINT ONLY" in p.stdout and "--used-pct 95.0" in p.stdout and "daemon-reload" in p.stdout
    assert "95-host-backstop.conf.disabled-" in p.stdout  # rollback archives, never deletes
    assert not pk.calls.exists() and not (pk.tmp / ".config").exists()


def test_hygiene_apply_is_dry_by_default_and_needs_the_grant(pk):
    p = pk.run("hygiene-apply")
    assert p.returncode == 1 and "no manifest" in p.stdout
    mdir = pk.state / "data/runtime/disk_hygiene"
    mdir.mkdir(parents=True)
    (mdir / "disk_hygiene_manifest_latest.json").write_text(json.dumps(
        {"generated_at": NOW.isoformat(), "items": [],
         "totals": {"candidates": 0, "reclaimable_gb": 0.0, "by_kind": {}}}))
    p = pk.run("hygiene-apply")
    assert p.returncode == 0 and "DRY RUN" in p.stdout and "0 candidates" in p.stdout
    p = pk.run("hygiene-apply", "--apply")
    assert p.returncode == 1 and "TRADEAI_DISK_HYGIENE_GRANT not set" in p.stdout
    p = pk.run("hygiene-apply", "--apply", TRADEAI_DISK_HYGIENE_GRANT="g", TRADEAI_RUN_ID="d:x")
    assert p.returncode == 1 and "never runs under the n8n executor" in p.stdout


def test_publish_is_read_only_and_needs_no_import(pk):
    p = pk.run("publish")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "NO IMPORT NEEDED" in p.stdout and "tradeai-dispatcher active=true" in p.stdout
