"""Synthetic current-head approval source and integration regressions; no live GitHub calls."""
from __future__ import annotations

import base64
import importlib.util
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.lib import operator_approvals as core
from scripts.lib import operator_approvals_api as api

SPEC = importlib.util.spec_from_file_location("approval_sync_pr_source_test", Path(__file__).resolve().parents[1] / "scripts/lib/operator_approval_pr_source.py")
source = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = source
SPEC.loader.exec_module(source)
HEAD, BASE = "a" * 40, "b" * 40
NOW = datetime(2032, 4, 12, 0, 10, tzinfo=timezone.utc)
STAMP = "2032-04-12T00:10:00Z"


def pr(number=2501):
    return {"number": number, "state": "open", "head": {"sha": HEAD}, "base": {"sha": BASE, "ref": "main"},
            "title": "Review current policy", "created_at": STAMP, "updated_at": STAMP, "user": {"login": "worker"}, "labels": []}


def git(*args):
    if args[0] == "diff":
        return "AGENTS.md\n"
    return "Policy-Version: " + ("30.0.0" if HEAD in args[1] else "29.3.0") + "\n\n# 0 · Rules\nNever bypass a denial.\n"


class Gh:
    repo = "example/project"

    def __init__(self, documents=None):
        self.documents = documents or {}
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        return self.documents.get(path), None if path in self.documents else "synthetic unavailable"


class Board:
    def __init__(self, rows):
        self.prs, self.prs_warning, self._prs_at = rows, None, 0.0
        self._lock = threading.Lock()
        self.kicks = []

    def _kick_prs(self, *, background=True):
        self.kicks.append(background)


def test_policy_source_offers_exact_approval_line_and_ignores_closed_work():
    row = source.project(pr(), git=git, gh=Gh(), as_of=STAMP)
    assert row["policy_approval_command"] == f"APPROVE_AGENTS_POLICY_30_0_0 2501 {HEAD}"
    assert row["document"]["source_verified"] is True
    assert row["source_sha"] == HEAD and row["source_as_of"] == STAMP
    assert row["pr_url"] == "https://github.com/example/project/pull/2501"
    for changed in ({"state": "closed"}, {"merged_at": STAMP}, {"base": {"sha": BASE, "ref": "other"}}):
        assert source.project({**pr(), **changed}, git=git, gh=Gh(), as_of=STAMP) is None


def test_held_pr_stays_visible_until_observed_done_even_with_merge_label():
    row = source.project({**pr(2472), "labels": [{"name": "operator-merge"}]},
                         git=lambda *args: ".github/workflows/ci.yml\n", gh=Gh(), as_of=STAMP)
    assert row["kind"] == "RELEASE" and row["decision_mode"] == "GOVERNED_PATH"
    assert row["governed_href"] == "/coordination?pr=2472"
    assert row["document"]["source_sha"] == HEAD
    assert "policy_approval_command" not in row
    assert source.project(pr(2502), git=lambda *args: "ordinary.txt\n", gh=Gh(), as_of=STAMP) is None


def test_missing_local_commit_reads_exact_sha_and_rechecks_files_head():
    def unavailable(*args):
        raise core.Refused("IMMUTABLE_SOURCE_REPOSITORY_UNAVAILABLE", 503)
    policy = "Policy-Version: 30.0.0\n\n# Rules\nReview this change."
    old = policy.replace("30.0.0", "29.3.0")
    gh = Gh({"repos/example/project/pulls/2501/files?per_page=100&page=1": [{"filename": "AGENTS.md"}],
             "repos/example/project/pulls/2501": pr(),
             f"repos/example/project/contents/AGENTS.md?ref={HEAD}": {"encoding": "base64", "content": base64.b64encode(policy.encode()).decode(), "size": len(policy)},
             f"repos/example/project/contents/AGENTS.md?ref={BASE}": {"encoding": "base64", "content": base64.b64encode(old.encode()).decode(), "size": len(old)}})
    row = source.project(pr(), git=unavailable, gh=gh, as_of=STAMP)
    assert row["document"]["text"] == policy
    assert "repos/example/project/pulls/2501" in gh.calls
    assert all("?ref=" + sha in gh.calls[i] for sha, i in ((HEAD, 2), (BASE, 3)))
    gh.documents["repos/example/project/pulls/2501"] = {**pr(), "head": {"sha": "c" * 40}}
    with pytest.raises(core.Refused, match="PR_HEAD_CHANGED"):
        source.project(pr(), git=unavailable, gh=gh, as_of=STAMP)


def test_cold_snapshot_kicks_existing_board_and_refreshes_when_upstream_arrives():
    board, clock = Board(None), [0.0]
    snapshot = source.Snapshot(board=board, git=git, gh_factory=Gh, clock=lambda: clock[0])
    initial = snapshot.view(background=False)
    assert initial["rows"] == [] and initial["gap"]
    assert board.kicks == [False]
    board.prs = [pr()]
    ready = snapshot.view(background=False)
    assert ready["gap"] is None and ready["rows"][0]["pr"] == 2501
    clock[0] = 121.0
    snapshot.git = lambda *args: (_ for _ in ()).throw(OSError("synthetic failure"))
    failed = snapshot.view(background=False)
    assert failed["gap"] and failed["rows"][0]["pr"] == 2501
    clock[0], board.prs, board._prs_at = 242.0, [], 242.0
    assert snapshot.view(background=False)["rows"] == []  # A successful empty listing resolves old PRs.


def test_snapshot_factory_failure_releases_single_flight_for_retry():
    board, clock = Board([pr()]), [0.0]
    def broken():
        raise RuntimeError("synthetic failure")
    snapshot = source.Snapshot(board=board, git=git, gh_factory=broken, clock=lambda: clock[0])
    assert snapshot.view(background=False)["gap"]
    assert snapshot._running is False
    snapshot.gh_factory, clock[0] = Gh, 121.0
    assert snapshot.view(background=False)["rows"][0]["pr"] == 2501


def context(tmp_path, row):
    return api.Ctx(principal=lambda: "tailnet:operator@example.test", listener=lambda: "serve_proxy",
                   csrf=lambda *args: (True, ""), allowed_logins=frozenset({"operator@example.test"}),
                   sources={"synthetic": lambda: [row]}, ledger=core.DecisionLedger(tmp_path / "decisions.jsonl", approved=lambda: True, clock=lambda: NOW),
                   policy=lambda: {}, clock=lambda: NOW, can_read=lambda: True)


def test_current_head_rechecked_before_decision_is_persisted(tmp_path):
    row = source.project(pr(), git=git, gh=Gh(), as_of=STAMP)
    ctx = context(tmp_path, row)
    checks = []
    def changed(item):
        checks.append(item["document"]["source_sha"])
        raise core.Refused("PR_HEAD_CHANGED", 409)
    ctx.verify_current = changed
    response = api.handle(api.PREFIX + "/approvals/policy:2501/decide", "POST",
                          {"decision": "REJECT", "request_id": "request_123456"}, ctx=ctx)
    assert response == (409, {"ok": False, "error": "PR_HEAD_CHANGED"})
    assert checks == [HEAD] and ctx.ledger.rows() == []


@pytest.mark.parametrize("current", [{"state": "closed", "head": {"sha": HEAD}},
    {"state": "open", "head": {"sha": "c" * 40}}, {"state": "open", "head": {"sha": HEAD}, "merged_at": STAMP}])
def test_default_verifier_refuses_changed_closed_and_merged_heads(monkeypatch, current):
    from scripts.lib import agent_claim_lifecycle
    gh = Gh({"repos/example/project/pulls/2501": current})
    monkeypatch.setattr(agent_claim_lifecycle, "GitHubReader", lambda: gh)
    row = source.project(pr(), git=git, gh=Gh(), as_of=STAMP)
    with pytest.raises(core.Refused, match="PR_HEAD_CHANGED"):
        api.verify_current_pr(row)
    assert gh.calls == ["repos/example/project/pulls/2501"]


def test_policy_and_held_sources_share_one_snapshot(monkeypatch, tmp_path):
    rows = [source.project(pr(), git=git, gh=Gh(), as_of=STAMP),
            source.project(pr(2472), git=lambda *args: ".github/workflows/ci.yml\n", gh=Gh(), as_of=STAMP)]
    snapshot = SimpleNamespace(view=lambda: {"rows": rows, "gap": "missing detail", "as_of": STAMP})
    monkeypatch.setitem(api._PR_SNAPSHOTS, tmp_path.resolve(), snapshot)
    sources = api._default_sources(tmp_path)
    assert sources["policy_prs"]()["rows"] == rows[:1]
    assert sources["held_prs"]()["rows"] == rows[1:]
    assert sources["held_prs"]()["gap"] == "missing detail"
    assert api._pr_snapshot(tmp_path) is snapshot


def test_coordinator_source_uses_durable_state_root(monkeypatch, tmp_path):
    from scripts.lib import coordination_approval_source, lane_last_receipt
    monkeypatch.setattr(lane_last_receipt, "runtime_dir", lambda: tmp_path / "data/runtime")
    monkeypatch.setattr(api, "source_revision", lambda root: HEAD)
    calls = []
    monkeypatch.setattr(coordination_approval_source, "load", lambda root, sha: calls.append((root, sha)) or {"rows": []})
    assert api._default_sources(tmp_path)["coordinator_decisions"]() == {"rows": []}
    assert calls == [(tmp_path, HEAD)]


def test_keep_retire_is_publicly_visible_and_reader_remains_reachable(tmp_path):
    row = core.item(ident="design:old", kind="DESIGN", title="Old proposal", proposed_by=None, created_at=None,
                    source="fixture", doc=core.document("Proposed work", source_sha=HEAD))
    row["decision_mode"] = "GOVERNED_PATH"
    ctx = context(tmp_path, row)
    ctx.sources = {"fixture": lambda: {"rows": [], "keep_retire": [row]}}
    status, response = api.handle(api.PREFIX + "/approvals", "GET", ctx=ctx)
    assert status == 200 and response["data"]["pending_count"] == 0
    assert "document" not in response["data"]["keep_retire"][0]
    assert api.handle(api.PREFIX + "/approvals/design%3Aold", "GET", ctx=ctx)[1]["data"]["document"]["text"] == "Proposed work"
    assert not ctx.ledger.path.exists()


def test_keep_retire_age_uses_elapsed_aware_time_and_configurable_threshold():
    assert api._keep_retire_reason("2032-04-11T19:00:00-04:00", now=NOW) is None
    assert api._keep_retire_reason("2032-04-10T23:00:00Z", now=NOW)
    assert api._keep_retire_reason("2032-04-11T23:00:00Z", now=NOW, after_hours=1)
    assert api._keep_retire_reason(None, now=NOW) == "age_unavailable"
    assert api._keep_retire_reason("2032-04-11T23:00:00", now=NOW) == "age_unavailable"
    assert api._keep_retire_reason((NOW - timedelta(hours=24)).isoformat(), now=NOW) is None



def test_actionable_projection_is_document_free_and_independent_of_pagination(tmp_path):
    rows = [core.item(ident=f"item:{i}", kind="FINDING", title=f"Question {i}", proposed_by=None, created_at=None,
                      source="fixture", doc=core.document("Question", source_sha=HEAD)) for i in range(55)]
    ctx = context(tmp_path, rows[0])
    ctx.sources = {"fixture": lambda: rows}
    status, response = api.handle(api.PREFIX + "/approvals", "GET", query={"offset": 50}, ctx=ctx)
    data = response["data"]
    assert status == 200 and len(data["items"]) == 5
    assert data["actionable_count"] == data["pending_count"] == 55
    assert len(data["actionable_items"]) == 55
    assert all("document" not in row for row in data["actionable_items"])
    assert not ctx.ledger.path.exists()
