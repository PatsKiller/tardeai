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


def test_mergify_updates_only_approved_prs():
    cfg = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))
    update_rules = [r for r in cfg.get("pull_request_rules", []) if "update" in (r.get("actions") or {})]
    assert update_rules, "the approved-PR update rule must stay"
    for rule in update_rules:
        conds = [c for c in rule.get("conditions", []) if isinstance(c, str)]
        assert "label=operator-merge" in conds, f"update without label=operator-merge: {rule.get('name')}"
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


def test_completed_runs_are_ignored():
    d = J.classify([_run(40, "z" * 40, "wt/gone", status="completed")], [], MAIN)
    assert d == []


# ── apply / dry run ────────────────────────────────────────────────────────────────────────────


def test_apply_rechecks_pr_and_skips_a_run_that_became_current():
    runs = [_run(50, "s" * 40, "wt/a"), _run(51, "t" * 40, "wt/gone")]
    prs = [_pr(100, "wt/a", "n" * 40)]
    decisions = J.classify(runs, prs, MAIN)
    cancelled = []
    res = J.apply_cancels(
        "x/y",
        decisions,
        get_pr=lambda n: {"state": "open", "head": {"sha": "s" * 40}},  # PR head moved back to the run's SHA
        cancel=cancelled.append,
    )
    assert res["skipped_recheck"] == [50]
    assert cancelled == [51] == res["cancel_requested"]


def test_default_is_dry_run_and_cancels_nothing(capsys, monkeypatch):
    called = []
    monkeypatch.setattr(J, "apply_cancels", lambda *a, **k: called.append(1) or {})
    fetch = lambda repo: ([_run(60, "s" * 40, "wt/gone")], [], MAIN)  # noqa: E731
    assert J.main(["--json"], fetch=fetch) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["mode"] == "dry-run"
    assert out["summary"]["would_cancel"] == 1
    assert called == []
