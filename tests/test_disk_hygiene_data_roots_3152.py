"""LQ-20261113-3152 — the /data storage roots are registered with cleanup + pressure controls.

ANCHOR: LQ3152_DATA_ROOTS

The migration moves ~/tradeai-wt-* to /data/worktrees and leaves the home path as a SYMLINK (a compatibility
alias). Discovery skips symlinks, so before this patch the migrated trees were invisible to G/W/C. These tests
pin the contract on a temp root with symlinked trees:

* the target is discovered once and the alias is never a second item;
* operator order 2026-11-14 00:25 ET, against the approved retention rules in
  ``config/disk_hygiene_rules.json`` (``standing_apply.rules`` lists W and C; W's age floor is
  ``standing_apply.worktree.untouched_hours``):
  (1) an ACTIVE copy with a compat link is held by its claim/cwd/activity, not by the link;
  (2) a COMPLETED copy past the approved age is NOT held by the link and is selectable under rule W
      (plan only — nothing is removed, no rule is enabled by this patch);
  (3) the pair closes together: the plan row names the link and ``close_compat_alias`` unlinks it, so no
      dangling link is left behind;
* a claim or worklog naming the ALIAS holds the TARGET (realpath both sides);
* a link naming another target, or a real entry where the alias belongs, is held (report both, pick neither);
* a dangling alias is a report-only orphan_link row;
* .migration-records is never a candidate;
* the pressure guard measures every disk_caps mount, not just "/".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.disk_hygiene as D  # noqa: E402
from scripts.lib import disk_hygiene_report as R  # noqa: E402

DATA_ROOT = "worktrees"
ALIAS_GLOB = "tradeai-wt-*"


def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _fixture(tmp_path: Path, *, alias: str | None = "symlink", sub: str = "") -> tuple[Path, Path, Path, Path]:
    """(rules_path, home, target, main). One real linked worktree under <tmp>/data/worktrees/tradeai-wt-x."""
    base = tmp_path / sub if sub else tmp_path
    home = base / "home"
    data = base / "data" / DATA_ROOT
    home.mkdir(parents=True)
    data.mkdir(parents=True)
    main = base / "main"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "commit", "-q", "--allow-empty", "-m", "init")
    _git(main, "remote", "add", "origin", "git@github.com:PatsKiller/trade-ai-test.git")
    target = data / "tradeai-wt-x"
    _git(main, "worktree", "add", "-q", str(target), "-b", "b1")
    if alias == "symlink":
        os.symlink(target, home / "tradeai-wt-x")
    elif alias == "dir":
        (home / "tradeai-wt-x").mkdir()
    doc = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))
    doc["home"] = str(home)
    doc["git"]["roots"] = [{"path": str(home), "depth": 1}, {"path": str(data), "depth": 1}]
    doc["git"]["compat_roots"] = [{"path": str(data), "alias_parent": str(home), "alias_glob": ALIAS_GLOB}]
    doc["never_touch"]["paths"] = [str(data / ".migration-records")]
    doc["standing_apply"]["coordination_root"] = str(base / "coord")
    doc["standing_apply"]["github_repo"] = "PatsKiller/trade-ai-test"
    p = base / "rules.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p, home, target, main


def _only(rows: list[dict], target: Path) -> dict:
    hits = [r for r in rows if r["path"] == str(target)]
    assert len(hits) == 1, [r["path"] for r in rows]
    return hits[0]


def _ctx(rules: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ctx = D.build_context(rules, now)
    ctx["snapshot"] = {"prs": [], "processes": [],
                       "coordination": {"live_claims": [], "live_worklogs": [], "references": []}}
    ctx |= {"offline": False, "opaque_processes": [], "evidence_sha256": "test"}
    return ctx


def test_the_migrated_target_is_discovered_once_and_the_alias_is_never_a_second_item(tmp_path):
    rules = D.load_rules(_fixture(tmp_path)[0])
    found = [str(p) for p in D.discover_git_dirs(rules)]
    assert found == [str(tmp_path / "data" / DATA_ROOT / "tradeai-wt-x")]
    assert not any("home/tradeai-wt-x" in p for p in found)


def test_an_active_copy_with_a_compat_link_is_held_by_its_activity_and_claim_not_by_the_link(tmp_path):
    """Operator order (1): ACTIVE + link -> held. The hold is the approved retention rule's own activity facts; the
    link contributes no reason (``standing_apply.worktree.untouched_hours`` = 24 h in
    config/disk_hygiene_rules.json — a tree younger than that is held by W and, since W does not take it, by C)."""
    p, home, target, _main = _fixture(tmp_path)
    rules = D.load_rules(p)
    ctx = _ctx(rules)
    row = _only(D.standing_results(rules, ctx), target)
    assert row["candidate"] is False
    assert "compat_link_present" not in row["reasons"]
    assert row["evidence"]["compat_alias_state"] == "symlink"
    assert [r for r in row["reasons"] if r.startswith("worktree_not_")], row["reasons"]
    # A claim written against EITHER name is an independent hold, on the same row.
    ctx["refs"] = [*ctx["refs"], ("claim:c-1", f"in-flight on {home}/tradeai-wt-x")]
    claimed = _only(D.standing_results(rules, ctx), target)
    assert "referenced" in claimed["reasons"]
    assert claimed["evidence"]["referenced_by"] == "claim:c-1"


def test_a_completed_copy_past_the_approved_age_is_not_held_by_its_compat_link(tmp_path):
    """Operator order (2): COMPLETED (no live claim/worklog, no cwd, clean, past the approved retention age) + link
    -> NOT held by the link; selectable under rule W, whose age floor is
    ``config/disk_hygiene_rules.json`` → ``standing_apply.worktree.untouched_hours`` (24 h; W is in
    ``standing_apply.rules``). PLAN ONLY: ``standing_results`` removes nothing, and this patch enables no rule."""
    p, home, target, _main = _fixture(tmp_path)
    rules = D.load_rules(p)
    assert "W" in rules["standing_apply"]["rules"]
    now = datetime.now(timezone.utc) + timedelta(hours=26)  # past untouched_hours (24), inside C's idle_days (7)
    row = _only(D.standing_results(rules, _ctx(rules, now)), target)
    assert row["rule"] == "W", (row["rule"], row["reasons"])
    assert row["candidate"] is True, row["reasons"]
    assert "compat_link_present" not in row["reasons"]
    assert row["evidence"]["compat_alias_state"] == "symlink"
    assert row["compat_alias_close"] == {"path": str(home / "tradeai-wt-x"), "target": str(target),
                                         "action": "unlink_symlink_after_target_removed"}
    assert os.path.lexists(target) and os.path.lexists(home / "tradeai-wt-x")  # a plan removes nothing


def test_closing_a_paired_copy_closes_the_link_so_none_is_left_dangling(tmp_path):
    """Operator order (3): the link is not left dangling-protected. The plan row names it and the executor's step
    unlinks only a link that still resolves to the removed target — never a real entry, never a re-pointed link."""
    p, home, target, _main = _fixture(tmp_path)
    rules = D.load_rules(p)
    now = datetime.now(timezone.utc) + timedelta(hours=26)
    row = _only(D.standing_results(rules, _ctx(rules, now)), target)
    alias = home / "tradeai-wt-x"
    assert row["compat_alias_close"]["path"] == str(alias)
    # The executor step on a scratch pair whose target is already gone (the plan above is never executed here).
    scratch = tmp_path / "closing"
    (scratch / "data").mkdir(parents=True)
    (scratch / "home").mkdir()
    gone = scratch / "data" / "tradeai-wt-x"
    link = scratch / "home" / "tradeai-wt-x"
    os.symlink(gone, link)
    item = {"path": str(gone), "compat_alias_close": {"path": str(link), "target": str(gone),
                                                      "action": "unlink_symlink_after_target_removed"}}
    assert D.close_compat_alias(item) == "alias_unlinked"
    assert not os.path.lexists(link)
    # A generic worktree row without the instruction is untouched, so older lanes keep their exact receipt.
    assert D.close_compat_alias({"path": str(gone)}) == "no_alias"
    # A link re-pointed elsewhere is refused and left alone (two names, rule 5), never guessed at.
    other = scratch / "elsewhere"
    link2 = scratch / "home" / "tradeai-wt-y"
    os.symlink(other, link2)
    refused = D.close_compat_alias({"path": str(gone), "compat_alias_close": {"path": str(link2), "target": str(gone)}})
    assert refused == "alias_close_refused:repointed"
    assert os.path.lexists(link2)
    # A target that is still there is never cut off from its own name.
    live_target = scratch / "data" / "tradeai-wt-z"
    live_target.mkdir()
    live_link = scratch / "home" / "tradeai-wt-z"
    os.symlink(live_target, live_link)
    still = D.close_compat_alias({"path": str(live_target),
                                  "compat_alias_close": {"path": str(live_link), "target": str(live_target)}})
    assert still == "alias_close_refused:target_present"
    assert os.path.lexists(live_link)


def test_the_revalidated_row_owns_the_alias_close_instruction():
    """The apply path must execute the FRESH instruction, never a stale manifest one (a link can appear, vanish or
    be re-pointed between plan and apply; replaying the old instruction would close a pair the recheck no longer
    believes in)."""
    key = {"path": "/home/runner/tradeai-wt-x", "target": "/data/worktrees/tradeai-wt-x", "action": "unlink_symlink_after_target_removed"}
    assert D.executed_row({"path": "/data/worktrees/tradeai-wt-x"}, {"path": "/data/worktrees/tradeai-wt-x",
                                                                     "compat_alias_close": key})["compat_alias_close"] == key
    stale = D.executed_row({"path": "/data/worktrees/tradeai-wt-x", "compat_alias_close": key},
                           {"path": "/data/worktrees/tradeai-wt-x"})
    assert "compat_alias_close" not in stale


def test_the_abandoned_worktree_rule_carries_the_alias_close_too(tmp_path):
    """Rule C (standing_apply.abandoned_worktree.idle_days = 7) is the other approved worktree rule; a pair C takes
    must close its link as well, or C would leave the dangling link W was stopped from leaving."""
    p, home, target, _main = _fixture(tmp_path)
    _git(target, "checkout", "-q", "--detach")  # W holds a detached, unmerged tree; C (no branch test) may take it
    rules = D.load_rules(p)
    now = datetime.now(timezone.utc) + timedelta(days=8)  # past idle_days; W no longer takes a detached tree
    row = _only(D.standing_results(rules, _ctx(rules, now)), target)
    assert row["rule"] == "C", (row["rule"], row["reasons"])
    assert "compat_link_present" not in row["reasons"]
    assert row["compat_alias_close"]["path"] == str(home / "tradeai-wt-x")


def _alias_close_harness(tmp_path: Path, monkeypatch, *, key: bool) -> tuple[list[dict], dict]:
    """The executor-level harness for C1 (REVIEW 3152-r2): ``remove_item`` on a worktree pair whose target is already
    gone. ``close_compat_alias`` is RECORDED (or a tripwire when the row carries no instruction), and every effect
    the branch performs — the git removal, the rule-C closeout gate/archive/remove — is stubbed to succeed. Only the
    pair-closing step is under test here; the real unlink is pinned in
    ``test_closing_a_paired_copy_closes_the_link_so_none_is_left_dangling``."""
    rules = D.load_rules(_fixture(tmp_path)[0])  # populates _RELEASE_ROOTS: the location gate below is live
    assert rules["releases"]["roots"], "the release-location gate must be armed, or remove_item refuses everything"
    closed: list[dict] = []
    if key:
        monkeypatch.setattr(D, "close_compat_alias", lambda item: closed.append(dict(item)) or "alias_unlinked")
    else:
        def tripwire(item):  # noqa: ANN001, ANN202 -- any call is the failure: no instruction, no unlink
            raise AssertionError("a link was closed for a row that never asked")
        monkeypatch.setattr(D, "close_compat_alias", tripwire)
    monkeypatch.setattr(D, "_git", lambda cwd, *a, **k: (0, ""))
    monkeypatch.setattr(D, "closeout_guard", lambda item, now=None: None)
    monkeypatch.setattr(D.WC, "archive_worktree",
                        lambda p, ns, note, **k: ({"ref": "refs/archive/x", "sha": "a" * 40}, None))
    monkeypatch.setattr(D.WC, "remove_worktree", lambda p, repo: (True, "worktree remove; prune"))
    target = tmp_path / "gone" / "data" / "tradeai-wt-x"   # not created: removal has already happened
    item = {"path": str(target), "rule": "W", "main_repo": str(tmp_path / "main"),
            "gitdir": str(tmp_path / "gitdir"), "archive_ns": "ns",
            "fingerprint": {"branch": "b1", "activity": 1.0}}
    if key:
        item["compat_alias_close"] = {"path": str(tmp_path / "gone" / "home" / "tradeai-wt-x"),
                                      "target": str(target), "action": "unlink_symlink_after_target_removed"}
    return closed, item


@pytest.mark.parametrize("kind,rule", [("git_worktree", "W"), ("abandoned_worktree", "C")])
def test_remove_item_closes_the_compat_link_on_both_worktree_branches(tmp_path, monkeypatch, kind, rule):
    """C1 (REVIEW LQ-3152-r2, cc-deepseek-6): the plan row is not the action — ``remove_item`` is the step that must
    EXECUTE it. Both approved worktree rules take a migrated pair, so BOTH branches must unlink the link in the same
    step as the target removal: the W branch (``git worktree remove``) and the C branch (archive-then-remove). The
    receipt must name what happened, so a branch that silently skips the link is visible on the run, not in hindsight
    as a dangling ``~/tradeai-wt-*``."""
    closed, item = _alias_close_harness(tmp_path, monkeypatch, key=True)
    item.update(kind=kind, rule=rule)
    out = D.remove_item(item)
    assert out[0] is True, out
    assert closed == [item], f"the {kind} branch removed the target but never closed the planned link"
    assert out[1].rstrip().endswith("; alias_unlinked"), out[1]


@pytest.mark.parametrize("kind,rule", [("git_worktree", "W"), ("abandoned_worktree", "C")])
def test_remove_item_without_the_instruction_never_touches_a_link(tmp_path, monkeypatch, kind, rule):
    """The other direction: a row that carries NO ``compat_alias_close`` (every pre-3152 lane, and a revalidation
    that found the link gone) keeps its historical receipt exactly and calls nothing — closing a link here would be
    acting without an instruction."""
    closed, item = _alias_close_harness(tmp_path, monkeypatch, key=False)
    item.update(kind=kind, rule=rule)
    out = D.remove_item(item)
    assert out[0] is True, out
    assert closed == []
    assert out[1] == ("git worktree remove; prune" if kind == "git_worktree"
                      else "archived refs/archive/x; worktree remove; prune"), out[1]


def test_a_reference_to_the_home_alias_holds_the_target(tmp_path):
    p, home, target, _main = _fixture(tmp_path)
    rules = D.load_rules(p)
    text = f"worklog names {home}/tradeai-wt-x as the tree"
    ctx = _ctx(rules)
    ctx["refs"] = [*ctx["refs"], ("worklog:test", text)]
    row = D.evaluate_git(target, rules, ctx)
    assert "referenced" in row["reasons"]
    assert row["evidence"]["compat_alias"] == str(home / "tradeai-wt-x")


def test_a_live_claim_written_against_the_alias_holds_the_target(tmp_path):
    _p, home, target, _main = _fixture(tmp_path)
    live = [{"claim_id": "c-1", "paths": [str(home / "tradeai-wt-x")]}]
    assert R.live_claim_hold(target, home, live) == "path_in_live_claim:c-1"
    # and the reverse direction: the item is the home path, the claim names the target
    assert R.live_claim_hold(home / "tradeai-wt-x", home, [{"claim_id": "c-2", "paths": [str(target)]}]) == "path_in_live_claim:c-2"


def test_a_dangling_alias_is_a_report_only_orphan_link_and_never_a_candidate(tmp_path, monkeypatch):
    p, home, _target, _main = _fixture(tmp_path)
    os.symlink(tmp_path / "data" / DATA_ROOT / "gone", home / "tradeai-wt-gone")
    rules = D.load_rules(p)
    # The evidence envelope is a different lane's concern (and its own tests); here only the row wiring matters.
    monkeypatch.setattr(D.SR, "evidence_context", lambda doc, now: _ctx(rules, now))
    manifest = D.standing_plan(rules, datetime.now(timezone.utc), {}, measure=False)
    assert not any(str(home / "tradeai-wt-gone") == i["path"] for i in manifest["items"])
    orphans = [i for i in manifest["excluded"] if i["path"] == str(home / "tradeai-wt-gone")]
    assert len(orphans) == 1, [i["path"] for i in manifest["excluded"]]
    assert orphans[0]["reasons"] == ["orphan_link"] and orphans[0]["candidate"] is False


def test_a_real_directory_where_the_alias_belongs_is_held_as_shadowed(tmp_path):
    p, home, target, _main = _fixture(tmp_path, alias="dir")
    rules = D.load_rules(p)
    row = D.evaluate_git(target, rules, _ctx(rules))
    assert "compat_link_shadowed" in row["reasons"]
    assert row["evidence"]["compat_alias_state"] == "shadowed"
    assert "compat_alias_close" not in row  # never unlink a real entry


def test_a_link_that_names_another_target_is_a_hold(tmp_path):
    p, home, target, _main = _fixture(tmp_path, alias="none")
    os.symlink(tmp_path / "elsewhere", home / "tradeai-wt-x")
    rules = D.load_rules(p)
    row = D.evaluate_git(target, rules, _ctx(rules))
    assert "compat_link_mismatch" in row["reasons"]  # two names, report both, pick neither (rule 5)
    assert row["evidence"]["compat_alias_state"] == "mismatch"
    assert "compat_alias_close" not in row


def test_migration_records_are_never_a_candidate(tmp_path):
    p, home, _target, _main = _fixture(tmp_path)
    recs = tmp_path / "data" / DATA_ROOT / ".migration-records"
    recs.mkdir()
    (recs / "a.json").write_text("{}", encoding="utf-8")
    rules = D.load_rules(p)
    assert D.never_touch_reason(recs, rules)
    assert D.never_touch_reason(recs / "a.json", rules)


def test_the_pressure_guard_measures_every_disk_caps_mount_by_default(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import disk_pressure_guard as g  # noqa: E402

    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"disk_caps": {"disks": [{"mount": "/"}, {"mount": "/data"}]}}), encoding="utf-8")
    assert g.default_paths(rules) == ["/", "/data"]
    rules.write_text(json.dumps({"pressure_act": {}}), encoding="utf-8")
    assert g.default_paths(rules) == ["/"]  # a file with no disk_caps keeps the historical single mount

