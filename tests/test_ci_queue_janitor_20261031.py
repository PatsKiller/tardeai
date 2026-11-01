"""CI queue saturation fix (2026-10-31). ANCHOR: CI_QUEUE_JANITOR_20261031.

1. .mergify.yml never auto-updates a PR that is not approved (label=operator-merge): the blanket
   "Keep PRs up to date" rule turned every merge to main into ~100 PR re-runs.
2. scripts/ci_queue_janitor.py cancels only pull_request runs whose PR is closed or whose head moved
   on; it never touches main/push/schedule/dynamic runs, main's head SHA or merge-queue branches;
   it is a dry run unless --apply is passed. Hermetic: no network, no gh.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("ci_queue_janitor", ROOT / "scripts" / "ci_queue_janitor.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = mod  # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


J = _load()
REPO = "patskiller/tardeai"
MAIN = "m" * 40


def _run(rid, sha, branch, *, event="pull_request", status="queued", name="cio-full-suite-sharded", repo=REPO):
    return {
        "id": rid,
        "name": name,
        "event": event,
        "status": status,
        "head_sha": sha,
        "head_branch": branch,
        "created_at": "2026-10-31T18:00:00Z",
        "head_repository": {"full_name": repo},
    }


def _pr(number, branch, sha, repo=REPO):
    return {"number": number, "state": "open", "head": {"ref": branch, "sha": sha, "repo": {"full_name": repo}}}


def _by_id(decisions):
    return {d.run_id: d for d in decisions}


# ── .mergify.yml ───────────────────────────────────────────────────────────────────────────────


def test_mergify_updates_or_rebases_only_approved_prs():
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))
    rules = cfg.get("pull_request_rules", [])
    assert any("update" in (r.get("actions") or {}) for r in rules), "the approved-PR update rule must stay"
    for rule in rules:
        actions = set(rule.get("actions") or {}) & {"update", "rebase"}
        if not actions:
            continue
        conds = [c for c in rule.get("conditions", []) if isinstance(c, str)]
        assert "label=operator-merge" in conds, f"{sorted(actions)} without label=operator-merge: {rule.get('name')}"
        assert "-draft" in conds


def test_blanket_keep_up_to_date_rule_is_gone():
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))
    names = [r.get("name") for r in cfg.get("pull_request_rules", [])]
    assert "Keep PRs up to date" not in names


# ── classify ───────────────────────────────────────────────────────────────────────────────────


def test_never_touches_main_push_schedule_dynamic():
    runs = [
        _run(1, MAIN, "main", event="push", name="cio-production-hardening-ci"),
        _run(2, "o" * 40, "main", event="push", name="cio-production-hardening-ci"),  # older main SHA
        _run(3, MAIN, "main", event="schedule"),
        _run(4, "c" * 40, "refs/pull/9/head", event="dynamic", name="PR #9"),
        _run(5, MAIN, "main", event="workflow_dispatch"),
    ]
    d = J.classify(runs, [], MAIN)
    assert all(x.action == "keep" and x.reason == J.KEEP_NOT_PR for x in d)


def test_superseded_and_closed_are_cancelled_current_head_kept():
    runs = [
        _run(10, "a1" * 20, "wt/a"),  # superseded
        _run(11, "a2" * 20, "wt/a", status="pending"),  # current head
        _run(12, "b1" * 20, "wt/closed", status="in_progress"),  # PR closed/merged
    ]
    prs = [_pr(100, "wt/a", "a2" * 20)]
    d = _by_id(J.classify(runs, prs, MAIN))
    assert (d[10].action, d[10].reason, d[10].pr_number) == ("cancel", J.CANCEL_SUPERSEDED, 100)
    assert (d[11].action, d[11].reason) == ("keep", J.KEEP_CURRENT)
    assert (d[12].action, d[12].reason, d[12].pr_number) == ("cancel", J.CANCEL_CLOSED, None)


def test_main_head_sha_and_merge_queue_are_protected():
    runs = [_run(20, MAIN, "wt/x"), _run(21, "q" * 40, "mergify/merge-queue/abc")]
    d = _by_id(J.classify(runs, [], MAIN))
    assert d[20].reason == J.KEEP_MAIN_HEAD
    assert d[21].reason == J.KEEP_MERGE_QUEUE


def test_fork_branch_with_same_name_does_not_match():
    runs = [_run(30, "f" * 40, "wt/a", repo="someone/fork")]
    prs = [_pr(100, "wt/a", "f" * 40)]  # same ref and sha but our repo
    d = _by_id(J.classify(runs, prs, MAIN))
    assert d[30].action == "cancel" and d[30].reason == J.CANCEL_CLOSED


def test_deleted_fork_run_is_kept_not_closed():
    run = _run(31, "g" * 40, "wt/fork-branch")
    run["head_repository"] = None
    d = _by_id(J.classify([run], [], MAIN))
    assert (d[31].action, d[31].reason) == ("keep", J.KEEP_NO_REPO)


def test_completed_runs_are_ignored():
    d = J.classify([_run(40, "z" * 40, "wt/gone", status="completed")], [], MAIN)
    assert d == []


# ── apply / dry run ────────────────────────────────────────────────────────────────────────────


def _no_open(owner, branch):
    return []


def test_apply_rechecks_pr_and_skips_a_run_that_became_current():
    runs = [_run(50, "s" * 40, "wt/a"), _run(51, "t" * 40, "wt/gone")]
    prs = [_pr(100, "wt/a", "n" * 40)]
    decisions = J.classify(runs, prs, MAIN)
    cancelled = []
    res = J.apply_cancels(
        "x/y",
        decisions,
        get_pr=lambda n: {"state": "open", "head": {"sha": "s" * 40}},  # PR head moved back to the run's SHA
        find_open_prs=_no_open,
        cancel=cancelled.append,
    )
    assert [x["run_id"] for x in res["skipped_recheck"]] == [50]
    assert cancelled == [51] == res["cancel_requested"]


def test_closed_run_is_rechecked_by_branch_and_kept_when_pr_is_open():
    """Reviewer's failing input: run on wt/live, empty open-PR list, lookup says open at that SHA."""
    decisions = J.classify([_run(70, "l" * 40, "wt/live")], [], MAIN)
    assert decisions[0].reason == J.CANCEL_CLOSED and decisions[0].pr_number is None
    lookups, cancelled = [], []

    def find(owner, branch):
        lookups.append((owner, branch))
        return [_pr(300, "wt/live", "l" * 40)]

    res = J.apply_cancels("x/y", decisions, get_pr=lambda n: {}, find_open_prs=find, cancel=cancelled.append)
    assert lookups == [("patskiller", "wt/live")]
    assert cancelled == [] and res["cancel_requested"] == []
    assert [x["run_id"] for x in res["skipped_recheck"]] == [70]


def test_closed_run_kept_when_branch_has_any_open_pr_even_at_another_sha():
    decisions = J.classify([_run(71, "o" * 40, "wt/reopened")], [], MAIN)
    cancelled = []
    res = J.apply_cancels(
        "x/y",
        decisions,
        get_pr=lambda n: {},
        find_open_prs=lambda o, b: [_pr(301, "wt/reopened", "p" * 40)],
        cancel=cancelled.append,
    )
    assert cancelled == [] and [x["run_id"] for x in res["skipped_recheck"]] == [71]


def test_pr_shifted_across_page_boundary_is_not_cancelled():
    """119 open PRs span two pages. If PR #1 closes between the page reads, PR #101 shifts onto
    page 1 after page 1 was read, so the listing misses it and its current-head run looks closed."""
    page1 = [_pr(i, f"wt/p{i}", f"{i:040d}") for i in range(1, 101)]  # read before PR #1 closed
    page2 = [_pr(i, f"wt/p{i}", f"{i:040d}") for i in range(102, 120)]  # read after: #101 moved to page 1
    live = {pr["head"]["ref"]: pr for pr in page1[1:] + [_pr(101, "wt/p101", f"{101:040d}")] + page2}
    runs = [_run(101, f"{101:040d}", "wt/p101"), _run(1, f"{1:040d}", "wt/p1")]
    decisions = _by_id(J.classify(runs, page1 + page2, MAIN))
    assert decisions[101].reason == J.CANCEL_CLOSED  # the listing really did lose it
    cancelled = []
    res = J.apply_cancels(
        "x/y",
        list(decisions.values()),
        get_pr=lambda n: {},
        find_open_prs=lambda o, b: [live[b]] if b in live else [],
        cancel=cancelled.append,
    )
    assert 101 not in cancelled
    assert [x["run_id"] for x in res["skipped_recheck"]] == [101]
    # PR #1 is genuinely closed, but its run was its current head in the stale listing → kept by classify.
    assert decisions[1].action == "keep"


def test_recheck_error_skips_that_run_and_continues():
    runs = [_run(80, "a" * 40, "wt/boom"), _run(81, "b" * 40, "wt/fine")]
    decisions = J.classify(runs, [], MAIN)

    def find(owner, branch):
        if branch == "wt/boom":
            raise RuntimeError("HTTP 502")
        return []

    cancelled = []
    res = J.apply_cancels("x/y", decisions, get_pr=lambda n: {}, find_open_prs=find, cancel=cancelled.append)
    assert cancelled == [81] == res["cancel_requested"]
    assert res["failed"] == [{"run_id": 80, "stage": "recheck", "error": "HTTP 502"}]


def test_get_pr_error_skips_that_run_and_continues():
    runs = [_run(90, "a" * 40, "wt/a"), _run(91, "c" * 40, "wt/c")]
    prs = [_pr(400, "wt/a", "z" * 40), _pr(401, "wt/c", "y" * 40)]
    decisions = J.classify(runs, prs, MAIN)

    def get_pr(n):
        if n == 400:
            raise RuntimeError("timeout")
        return {"state": "open", "head": {"sha": "y" * 40}}

    cancelled = []
    res = J.apply_cancels("x/y", decisions, get_pr=get_pr, find_open_prs=_no_open, cancel=cancelled.append)
    assert cancelled == [91]
    assert [f["run_id"] for f in res["failed"]] == [90]


def test_default_is_dry_run_and_cancels_nothing(capsys, monkeypatch):
    called = []
    monkeypatch.setattr(J, "apply_cancels", lambda *a, **k: called.append(1) or {})
    fetch = lambda repo: ([_run(60, "s" * 40, "wt/gone")], [], MAIN)  # noqa: E731
    assert J.main(["--json"], fetch=fetch) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["mode"] == "dry-run"
    assert out["summary"]["would_cancel"] == 1
    assert called == []


def test_superseded_run_kept_when_a_new_pr_on_the_branch_is_at_its_sha():
    """PR #500 was closed and #501 opened on the same branch at the run's SHA: get_pr(#500) says
    closed, so only the by-branch lookup proves the run is current."""
    decisions = J.classify([_run(95, "r" * 40, "wt/again")], [_pr(500, "wt/again", "x" * 40)], MAIN)
    assert decisions[0].reason == J.CANCEL_SUPERSEDED
    cancelled = []
    res = J.apply_cancels(
        "x/y",
        decisions,
        get_pr=lambda n: {"state": "closed", "head": {"sha": "x" * 40}},
        find_open_prs=lambda o, b: [_pr(501, "wt/again", "r" * 40)],
        cancel=cancelled.append,
    )
    assert cancelled == [] and [x["run_id"] for x in res["skipped_recheck"]] == [95]
