"""Rules C / R / X and the pressure loop (DSN-20261030-workspace-lifecycle P2-T1/T2/T3/T4).

Synthetic tmp_path repos and files only; fake evidence, processes and PRs; no host census, no real home.
COVERS = ["scripts/disk_hygiene.py", "scripts/lib/workspace_closeout.py", "scripts/lib/disk_hygiene_retention.py"]
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import disk_hygiene as DH
from scripts.lib import disk_hygiene_retention as SR
from scripts.lib import workspace_closeout as WC
from tests.test_disk_standing_apply_20261024 import NOW, _age_tree, _git_fixture, evidence, old, set_source, world  # noqa: F401

REAL_REMOVE = DH.remove_item
NS = "refs/archive/closeout"
C_CFG = {"idle_days": 7, "max_archive_mb": 200, "archive_ns": NS, "archive_retention_days": 90}
R_CFG = {"root": "~/trade-ai-releases/portfolio-server", "keep_newest": 3,
         "lock_path": "~/trade-ai-releases/persistent-state/data/runtime/release_window/.lock"}
P_CFG = {"trigger_pct": 80, "target_pct": 75, "max_passes": 5, "alert_pct": 85}


def lifecycle(world, *, rules=("A", "S", "W", "C", "R"), **cfg_over):
    """Write the C/R/pressure config into the fixture rules file and reload it (load_rules validates)."""
    home, _, rules_path, cfg = world
    sa = cfg["standing_apply"]
    sa.update(rules=list(rules), abandoned_worktree=dict(C_CFG), release_reclaim=dict(R_CFG), pressure=dict(P_CFG))
    for key, val in cfg_over.items():
        sa[key] = val
    rules_path.write_text(json.dumps(cfg))
    loaded = DH.load_rules(rules_path, home=home)
    loaded["_owned_res"] = [re.compile(r"example\.invalid/fixture")]
    return loaded


def git_out(repo, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


def make_worktree(home, name="wt-c1", branch="work/c1"):
    """A main repo with an origin URL (never fetched) and one linked worktree with a tracked edit and an untracked file."""
    main = home / "proj" / "main"
    if not main.exists():
        main.mkdir(parents=True)
        _git_fixture(main, "init", "-q", "-b", "main")
        (main / "a.txt").write_text("base\n")
        (main / ".gitignore").write_text(".env*\nbuild/\n")
        _git_fixture(main, "add", "a.txt", ".gitignore")
        _git_fixture(main, "commit", "-q", "-m", "base")
        _git_fixture(main, "remote", "add", "origin", "https://example.invalid/fixture.git")
    wt = home / name
    _git_fixture(main, "worktree", "add", "-q", "-b", branch, str(wt))
    (wt / "a.txt").write_text("base\nedited in worktree\n")
    (wt / "notes").mkdir()
    (wt / "notes" / "draft.md").write_text("untracked draft\n")
    return main, wt


def age(main, wt):
    _age_tree(wt)
    _age_tree(main / ".git" / "worktrees" / wt.name)


def plan_rows(rules, doc=None):
    return DH.standing_results(rules, SR.evidence_context(doc or evidence(), NOW))


def row_for(rows, path, rule=None):
    return next(r for r in rows if r["path"] == str(path) and (rule is None or r["rule"] == rule))


@pytest.fixture
def cworld(world, monkeypatch):
    home = world[0]
    rules = lifecycle(world)
    main, wt = make_worktree(home)
    monkeypatch.setattr(DH, "discover_git_dirs", lambda *_: [p for p in sorted(home.iterdir()) if (p / ".git").is_file()])
    return home, rules, main, wt


# ── rule C ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_idle_dirty_worktree_is_archived_then_removed_and_the_ref_restores_it(cworld):
    home, rules, main, wt = cworld
    age(main, wt)
    item = row_for(plan_rows(rules), wt)
    assert item["rule"] == "C" and item["kind"] == "abandoned_worktree" and item["candidate"], item["reasons"]
    assert "dirty" in item["evidence"]["w_reasons"]  # rule W does not take it; C does
    ok, how, arc = REAL_REMOVE(item)
    assert ok and not wt.exists() and arc["archive_ref"].startswith(NS + "/") and arc["archive_ref"] in how
    assert git_out(main, "rev-parse", arc["archive_ref"]) == arc["archive_sha"]
    assert git_out(main, "rev-parse", "--verify", "refs/heads/work/c1")  # the branch is never deleted
    restored = home / "restored"
    _git_fixture(main, "worktree", "add", "-q", "--detach", str(restored), arc["archive_ref"])
    assert (restored / "a.txt").read_text() == "base\nedited in worktree\n"
    assert (restored / "notes" / "draft.md").read_text() == "untracked draft\n"
    assert git_out(main, "log", "-1", "--format=%an <%ae>", arc["archive_ref"]) == "closeout <closeout@localhost>"


def test_standing_apply_records_the_archive_ref_of_each_closed_worktree(cworld, monkeypatch):
    from tests.test_disk_standing_apply_20261024 import do_apply
    home, rules, main, wt = cworld
    age(main, wt)
    manifest = DH.standing_plan(rules, NOW, evidence())
    assert [r["rule"] for r in manifest["items"]] == ["C"]
    path = home.parent / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(DH, "remove_item", REAL_REMOVE)  # fixture paths only
    report = do_apply(path, rules, evidence())
    (done,) = report["removed"]
    assert report["refused"] is None and done["rule"] == "C" and not wt.exists()
    assert git_out(main, "rev-parse", done["archive_ref"]) == done["archive_sha"]


def test_rule_c_is_plan_only_until_listed(world, monkeypatch):
    rules = lifecycle(world, rules=("A", "S", "W"))
    main, wt = make_worktree(world[0])
    age(main, wt)
    monkeypatch.setattr(DH, "discover_git_dirs", lambda *_: [wt])
    item = row_for(plan_rows(rules), wt)
    assert item["reasons"] == ["rule_plan_only_not_authorized:C"]


@pytest.mark.parametrize("hold", ["open_pr", "claim", "worklog", "process_cwd", "process_fd", "lock", "recent", "credential", "untracked_cap", "release_tree"])
def test_rule_c_holds(cworld, monkeypatch, hold):
    home, rules, main, wt = cworld
    doc = evidence()
    if hold == "open_pr":
        set_source(doc, "prs", [{"number": 1, "branch": "work/c1", "state": "open"}])
    elif hold in ("claim", "worklog"):
        key = "live_claims" if hold == "claim" else "live_worklogs"
        set_source(doc, "coordination", {"references": [], "live_claims": [], "live_worklogs": [], key: [{"worktree": str(wt)}]})
    elif hold == "process_cwd":
        set_source(doc, "processes", [{"pid": "7", "cwd": str(wt / "notes"), "fds": []}])
    elif hold == "process_fd":
        set_source(doc, "processes", [{"pid": "7", "cwd": "/", "fds": [str(wt / "a.txt")]}])
    elif hold == "lock":
        _git_fixture(main, "worktree", "lock", str(wt))
    elif hold == "credential":
        (wt / ".env.local").write_text("FIXTURE_ONLY=1\n")
    elif hold == "untracked_cap":
        (wt / "notes" / "big.bin").write_bytes(b"x" * 4096)
        rules["standing_apply"]["abandoned_worktree"]["max_archive_mb"] = 0.001
    elif hold == "release_tree":
        rel = home / "trade-ai-releases" / "wt-rel"
        _git_fixture(main, "worktree", "add", "-q", "-b", "work/rel", str(rel))
        (rel / "a.txt").write_text("dirty, so rule W does not take it\n")
        _age_tree(rel)
        _age_tree(main / ".git" / "worktrees" / "wt-rel")
        monkeypatch.setattr(DH, "discover_git_dirs", lambda *_: [rel])
        wt = rel
    if hold != "release_tree":
        age(main, wt)
    if hold == "recent":
        os.utime(wt / "notes" / "draft.md", (NOW.timestamp(), NOW.timestamp()))
    item = row_for(plan_rows(rules, doc), wt)
    expect = {"open_pr": "open_pr_branch", "claim": "referenced:coordination:live_claims",
              "worklog": "referenced:coordination:live_worklogs", "process_cwd": "in_use_cwd", "process_fd": "referenced:processes",
              "lock": "worktree_locked", "recent": "worktree_not_idle_7_days", "credential": "real_credential_file",
              "untracked_cap": "untracked_over_cap", "release_tree": "release_tree"}[hold]
    assert not item["candidate"] and expect in item["reasons"], (item["rule"], item["reasons"])


def test_symlinked_credential_does_not_hold_but_a_real_one_does(cworld, tmp_path):
    home, rules, main, wt = cworld
    target = tmp_path / "elsewhere.txt"
    target.write_text("not read\n")
    (wt / ".env").symlink_to(target)
    age(main, wt)
    os.utime(wt / ".env", (NOW.timestamp() - 9 * 86400,) * 2, follow_symlinks=False)
    assert row_for(plan_rows(rules), wt)["candidate"], row_for(plan_rows(rules), wt)["reasons"]
    (wt / "build").mkdir()
    (wt / "build" / "service_token.json").write_text("{}")  # real file inside an ignored dir
    age(main, wt)
    item = row_for(plan_rows(rules), wt)
    assert "real_credential_file" in item["reasons"] and item["evidence"]["credential_like"] == ["build/service_token.json"]


def test_untracked_nested_repo_holds(cworld):
    home, rules, main, wt = cworld
    (wt / "nested").mkdir()
    _git_fixture(wt / "nested", "init", "-q")
    age(main, wt)
    assert "untracked_nested_repo" in row_for(plan_rows(rules), wt)["reasons"]


def test_clean_merged_worktree_stays_rule_w(world, monkeypatch):
    rules = lifecycle(world)
    main, wt = make_worktree(world[0])
    for p in ("a.txt",):
        _git_fixture(wt, "checkout", "--", p)
    shutil.rmtree(wt / "notes")
    _git_fixture(main, "update-ref", "refs/remotes/origin/main", git_out(main, "rev-parse", "HEAD"))
    age(main, wt)
    monkeypatch.setattr(DH, "discover_git_dirs", lambda *_: [wt])
    rows = plan_rows(rules)
    assert [r["rule"] for r in rows if r["path"] == str(wt)] == ["W"]


def test_ref_name_is_valid_for_a_dot_directory_path(tmp_path):
    home = tmp_path / "home"
    ref = WC.ref_name(home / ".cache" / "x", NS, home)
    assert ref.startswith(NS + "/cache_x-") and len(ref.rsplit("-", 1)[1]) == 10
    subprocess.run(["git", "check-ref-format", ref], check=True)
    assert WC.ref_name(home / ".cache" / "x", NS, home) != WC.ref_name(home / "_cache" / "x", NS, home)


def test_apply_time_guard_refuses_a_changed_or_locked_worktree(cworld):
    home, rules, main, wt = cworld
    age(main, wt)
    item = row_for(plan_rows(rules), wt)
    os.utime(wt / "a.txt", (NOW.timestamp(), NOW.timestamp()))
    assert REAL_REMOVE(item) == (False, "changed_before_archive") and wt.exists()
    age(main, wt)
    _git_fixture(main, "worktree", "lock", str(wt))
    assert REAL_REMOVE(row_for(plan_rows(rules), wt))[0] is False and wt.exists()


def test_rule_x_reports_old_archive_refs_and_never_lists_them(cworld):
    home, rules, main, wt = cworld
    age(main, wt)
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="f", GIT_AUTHOR_EMAIL="f@x", GIT_COMMITTER_NAME="f",
               GIT_COMMITTER_EMAIL="f@x", GIT_COMMITTER_DATE="2026-01-01T00:00:00+00:00")
    tree = git_out(main, "rev-parse", "HEAD^{tree}")
    sha = subprocess.run(["git", "-C", str(main), "commit-tree", tree, "-m", "old"], check=True, capture_output=True, text=True, env=env).stdout.strip()
    _git_fixture(main, "update-ref", "refs/archive/closeout-20260101/old-slug", sha)
    result = DH.standing_plan(rules, NOW, evidence())
    x = [r for r in result["excluded"] if r["rule"] == "X"]
    assert len(x) == 1 and x[0]["reasons"] == ["rule_x_plan_only"] and x[0]["evidence"]["sha"] == sha
    assert not [r for r in result["items"] if r["rule"] == "X"]


# ── rule R ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def releases(home, n=7, current=4):
    ps = home / "trade-ai-releases" / "portfolio-server"
    out = []
    for i in range(1, n + 1):
        p = ps / f"abc{i}-main-exact-phase2-2026100{i}-120000"
        p.mkdir(parents=True)
        (p / "BUILD_SHA").write_text(f"abc{i}\n")
        out.append(p)
    (ps / "CURRENT").symlink_to(out[current])
    (ps / "EXPECTED_RELEASE").write_text(str(out[current]) + "\n")
    return out


def test_rule_r_keeps_current_previous_and_newest_n(world):
    rules = lifecycle(world)
    rel = releases(world[0])
    rows = [r for r in plan_rows(rules) if r["rule"] == "R"]
    assert {r["path"] for r in rows if r["candidate"]} == {str(p) for p in rel[:3]}
    held = {r["path"]: r["reasons"] for r in rows if not r["candidate"]}
    assert "previous_served" in held[str(rel[3])]
    assert any(x.startswith("pointer_symlink") for x in held[str(rel[4])])
    assert "keep_newest" in held[str(rel[5])] and "keep_newest" in held[str(rel[6])]


def test_rule_r_holds_lock_credential_copy_reference_and_missing_current(world):
    home = world[0]
    rules = lifecycle(world)
    rel = releases(home)
    (rel[0] / ".env.bak-fixture").write_text("FIXTURE_ONLY=1\n")
    (rel[1] / ".env.example").write_text("TEMPLATE=\n")
    (rel[1] / ".env").symlink_to(home / "nowhere")
    doc = evidence()
    set_source(doc, "cron", f"0 1 * * * cd {rel[2]} && true\n")
    rows = {r["path"]: r for r in DH.standing_results(rules, SR.evidence_context(doc, NOW)) if r["rule"] == "R"}
    assert "release_holds_credential_file" in rows[str(rel[0])]["reasons"]
    assert rows[str(rel[1])]["candidate"]
    assert "referenced:cron" in rows[str(rel[2])]["reasons"]
    lock = DH._expand(R_CFG["lock_path"], home)
    lock.parent.mkdir(parents=True)
    with open(lock, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        assert all("release_lock_busy" in r["reasons"] for r in plan_rows(rules) if r["rule"] == "R")
    assert row_for(plan_rows(rules), rel[1])["candidate"]
    (home / "trade-ai-releases" / "portfolio-server" / "CURRENT").unlink()
    assert "current_pointer_unresolved" in row_for(plan_rows(rules), rel[1])["reasons"]


def test_rule_r_keep_newest_comes_from_config(world):
    rules = lifecycle(world, release_reclaim={**R_CFG, "keep_newest": 5})
    rel = releases(world[0], current=6)
    assert {r["path"] for r in plan_rows(rules) if r["rule"] == "R" and r["candidate"]} == {str(rel[0]), str(rel[1])}


# ── config validation ───────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key, value, error", [
    ("abandoned_worktree", {**C_CFG, "idle_days": 0}, "abandoned_worktree_idle_days"),
    ("abandoned_worktree", {**C_CFG, "max_archive_mb": 0}, "abandoned_worktree_max_archive_mb"),
    ("abandoned_worktree", {**C_CFG, "archive_ns": "refs/heads/x"}, "abandoned_worktree_archive_ns"),
    ("abandoned_worktree", {**C_CFG, "archive_ns": "refs/archive/.x"}, "abandoned_worktree_archive_ns"),
    ("abandoned_worktree", {**C_CFG, "archive_retention_days": 1}, "abandoned_worktree_archive_retention_days"),
    ("abandoned_worktree", None, "abandoned_worktree_shape"),
    ("release_reclaim", {**R_CFG, "keep_newest": 0}, "release_reclaim_keep_newest"),
    ("release_reclaim", {**R_CFG, "lock_path": "/abs/.lock"}, "release_reclaim_lock_path"),
    ("release_reclaim", {**R_CFG, "root": "~/trade-ai-releases/archive/releases_20260915"}, "release_reclaim_root"),
    ("release_reclaim", None, "release_reclaim_shape"),
    ("pressure", {**P_CFG, "target_pct": 90}, "pressure_order"),
    ("pressure", {**P_CFG, "alert_pct": 120}, "pressure_pct"),
    ("pressure", {**P_CFG, "max_passes": 0}, "pressure_max_passes"),
])
def test_lifecycle_config_is_validated_fail_closed(world, key, value, error):
    with pytest.raises(DH.RulesError, match=error):
        lifecycle(world, **{key: value})


def test_rule_x_can_never_be_listed_for_removal(world):
    with pytest.raises(DH.RulesError, match="standing_rules_shape"):
        lifecycle(world, rules=("A", "X"))


def test_committed_config_lists_c_and_r_but_stays_disabled():
    rules = DH.load_rules()
    sa = rules["standing_apply"]
    assert {"T", "C", "R"} <= set(sa["rules"]) and sa["enabled"] is False
    assert sa["approval"]["status"] == "PENDING_OPERATOR_REVIEW"
    assert sa["pressure"] == {**P_CFG, "_why": sa["pressure"]["_why"]}
    assert sa["abandoned_worktree"]["archive_ns"] == NS


# ── pressure loop ───────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def pworld(world, tmp_path, monkeypatch):
    """N idle rtc scratch dirs; usage = 70 + 5 * remaining; the remover rmtrees fixture dirs only."""
    home, _, rules_path, cfg = world
    cfg["standing_apply"]["max_items_per_run"] = 1  # one removal per pass, so passes are observable
    lifecycle(world)
    scratch = home / ".cache" / "rtc"
    scratch.mkdir(parents=True)
    calls = {"collect": 0, "removed": []}

    def usage(*_):
        return {"used_pct": 70 + 5 * len(list(scratch.iterdir())), "measured_at": NOW.isoformat(), "filesystem_path": str(home)}

    def collect(*_a, **_k):
        calls["collect"] += 1
        return evidence()

    def remove(item):
        assert Path(item["path"]).parent == scratch
        shutil.rmtree(item["path"])
        calls["removed"].append(item["path"])
        return True, "SIMULATED_FIXTURE_RMTREE"

    monkeypatch.setattr(DH, "disk_usage_sample", usage)
    monkeypatch.setattr(DH, "collect_standing_evidence", collect)
    monkeypatch.setattr(DH, "remove_item", remove)
    monkeypatch.setattr(DH.R, "write_lane_receipt", lambda *a, **k: tmp_path / "receipt")
    monkeypatch.setenv(DH.RUN_ID_ENV, "fixture-pressure-run")
    state = tmp_path / "state"

    def make(n, days=10):
        for i in range(n):
            p = scratch / f"s{i}"
            p.mkdir()
            old(p, days)

    def run(*extra):
        rc = DH.main(["--standing", "--apply", "--rules", str(rules_path), "--home", str(home), "--state-root", str(state),
                      "--now", NOW.isoformat(), *extra])
        latest = DH.manifest_dir(DH.load_rules(rules_path, home=home), state) / "disk_hygiene_standing_apply_latest.json"
        return rc, (json.loads(latest.read_text()) if latest.exists() else None)

    return make, run, calls, state, rules_path, home


def test_until_target_stops_when_target_is_reached(pworld):
    make, run, calls, *_ = pworld
    make(4)
    rc, rep = run("--until-target", "75")
    p = rep["pressure"]
    assert rc == 0 and p["stopped_because"] == "target_reached" and len(p["passes"]) == 3 and len(calls["removed"]) == 3
    assert [x["usage_before"]["used_pct"] for x in p["passes"]] == [90, 85, 80]
    assert [x["usage_after"]["used_pct"] for x in p["passes"]] == [85, 80, 75]
    assert rep["ended_above_alert_pct"] is False and p["total_removed"] == 3
    assert calls["collect"] >= 3  # every pass re-collects evidence


def test_until_target_stops_at_max_passes_and_flags_alert_with_held_reasons(pworld):
    make, run, calls, state, rules_path, home = pworld
    cfg = json.loads(rules_path.read_text())
    cfg["standing_apply"]["pressure"]["max_passes"] = 2
    rules_path.write_text(json.dumps(cfg))
    make(6)
    recent = home / ".cache" / "rtc" / "fresh"
    recent.mkdir()
    rc, rep = run("--until-target", "50")
    assert rc == 0 and rep["pressure"]["stopped_because"] == "max_passes" and len(rep["pressure"]["passes"]) == 2
    assert rep["ended_above_alert_pct"] is True  # 70 + 5*5 = 95 > 85
    assert rep["held_top_reasons"][0]["reason"] == "scratch_not_older_than_7_days"
    assert len(list(DH.manifest_dir(DH.load_rules(rules_path, home=home), state).glob("disk_hygiene_pressure_pass_*"))) == 2


def test_until_target_stops_when_a_pass_removes_nothing(pworld):
    make, run, calls, *_ = pworld
    make(2, days=1)  # too recent: nothing is a candidate
    rc, rep = run("--until-target", "50")
    assert rc == 0 and rep["pressure"]["stopped_because"] == "pass_removed_nothing" and len(rep["pressure"]["passes"]) == 1
    assert calls["removed"] == []


def test_only_if_above_exits_early_with_a_below_threshold_receipt(pworld):
    make, run, calls, state, rules_path, home = pworld
    make(1)  # usage 75
    rc, rep = run("--only-if-above", "80", "--until-target", "75")
    assert rc == 0 and rep is None and calls == {"collect": 0, "removed": []}
    check = json.loads((DH.manifest_dir(DH.load_rules(rules_path, home=home), state) / "disk_hygiene_pressure_check_latest.json").read_text())
    assert check["outcome"] == "below_threshold" and check["usage"]["used_pct"] == 75
    rc, rep = run("--only-if-above", "70", "--until-target", "72")
    assert rc == 0 and rep["pressure"]["stopped_because"] == "target_reached" and calls["removed"]


@pytest.mark.parametrize("argv", [["--until-target", "75"], ["--standing", "--plan", "--until-target", "75"],
                                  ["--standing", "--apply", "--until-target", "120"], ["--only-if-above", "0"]])
def test_pressure_flags_are_usage_errors_outside_standing_apply(world, argv):
    home, _, rules_path, _ = world
    lifecycle(world)
    assert DH.main([*argv, "--rules", str(rules_path), "--home", str(home), "--now", NOW.isoformat()]) == 2
