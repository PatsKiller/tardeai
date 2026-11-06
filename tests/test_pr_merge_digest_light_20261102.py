"""The merge digest lists cheaply and enriches per PR (2026-11-02).

From about 08:15 every digest run failed ~11s in with "HTTP 504 Gateway Timeout (graphql)": one
GraphQL query asked for body, files and statusCheckRollup for all ~67 open PRs, past GitHub's ~10s
limit. The list is now cheap; each candidate PR gets one view, with a bounded retry and a per-PR
soft failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import pr_merge_digest as pmd  # noqa: E402


def _pr(number, *, draft=False, labels=(), title="A plain sentence about the change"):
    return {"number": number, "title": title, "url": f"https://example.com/pull/{number}",
            "headRefOid": "a" * 40, "isDraft": draft, "labels": list(labels), "changedFiles": 1,
            "baseRefName": "main"}


class FakeGh:
    def __init__(self, *, list_out=None, details=None, list_failures=0, detail_failures=0):
        self.list_out = list_out or []
        self.details = details or {}
        self.list_failures = list_failures
        self.detail_failures = detail_failures
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            if self.list_failures > 0:
                self.list_failures -= 1
                return 1, "HTTP 504 Gateway Timeout (graphql)"
            return 0, json.dumps(self.list_out)
        if args[:2] == ["pr", "view"]:
            if self.detail_failures > 0:
                self.detail_failures -= 1
                return 1, "unexpected end of JSON input"
            return 0, json.dumps(self.details.get(int(args[2]), {"body": "", "statusCheckRollup": []}))
        return 1, "unexpected"


def test_the_list_asks_only_for_cheap_fields(monkeypatch):
    gh = FakeGh(list_out=[_pr(1)])
    monkeypatch.setattr(pmd, "_gh", gh)
    pmd.list_open_prs("example-org/example-repo", 50, {})
    listed = " ".join(gh.calls[0])
    assert "statusCheckRollup" not in listed and "body" not in listed and "files" not in listed
    assert "number,title,url,headRefOid,isDraft,labels,baseRefName,changedFiles" in listed


def test_a_504_on_the_list_is_retried(monkeypatch):
    gh = FakeGh(list_out=[_pr(1)], list_failures=1)
    monkeypatch.setattr(pmd, "_gh", gh)
    monkeypatch.setattr(pmd.time, "sleep", lambda s: None)
    rows = pmd.list_open_prs("example-org/example-repo", 50, {"list_retry_attempts": 3, "list_retry_backoff_s": 0})
    assert [r["number"] for r in rows] == [1]
    assert len([c for c in gh.calls if c[:2] == ["pr", "list"]]) == 2


def test_drafts_and_approved_prs_are_not_enriched(monkeypatch):
    prs = [_pr(1, draft=True), _pr(2, labels=[{"name": "operator-merge"}]), _pr(3)]
    gh = FakeGh(list_out=prs, details={3: {"body": "## In plain English\n", "statusCheckRollup": []}})
    monkeypatch.setattr(pmd, "_gh", gh)
    monkeypatch.setattr(pmd, "pr_all_files", lambda repo, n: ["scripts/demo.py"])
    pmd.build_digest("example-org/example-repo", pmd.load_config())
    viewed = [int(c[2]) for c in gh.calls if c[:2] == ["pr", "view"]]
    assert viewed == [3]


def test_one_failed_detail_does_not_fail_the_run(monkeypatch):
    gh = FakeGh(list_out=[_pr(1), _pr(2)], detail_failures=1,
                details={2: {"body": "## In plain English\n", "statusCheckRollup": []}})
    monkeypatch.setattr(pmd, "_gh", gh)
    monkeypatch.setattr(pmd.time, "sleep", lambda s: None)
    monkeypatch.setattr(pmd, "pr_all_files", lambda repo, n: ["scripts/demo.py"])
    out = pmd.build_digest("example-org/example-repo", dict(pmd.load_config(), detail_retry_attempts=1))
    reasons = [s.get("reason") for s in out["skipped"]]
    assert "detail_unavailable" in reasons
    assert out["scanned"] == 2
