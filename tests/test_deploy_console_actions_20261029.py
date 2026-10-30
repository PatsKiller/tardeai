"""Deploy console P2 write path (POST /api/v2/ops/in-flight/action), design DSN-20261029-deploy-console (P2).

Hermetic (AGENTS.md §24.6): no network, no live ``gh``, no real guard ledger write, no real git push,
no real label write. The pure logic — label mapping, push-grant reason scoping (branch/head named, the
"override" keyword), fast-forward-only push, force refusal, and the authority/CSRF gate — is exercised
against injected doubles. The real guard ledger, ``gh``, ``git push`` and the refresh subprocess are never
reached from a test.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import deploy_console_actions as A  # noqa: E402
from lib import deploy_in_flight as D  # noqa: E402
from lib import guard_push_auth as G  # noqa: E402
from lib import tradeai_push_budget as B  # noqa: E402

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
SHA = "e" * 40
BRANCH = "wt/deploy-console-p2-20261029"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))  # receipts land in tmp, never persistent state
    monkeypatch.delenv("TRADEAI_GITHUB_REPO", raising=False)
    monkeypatch.delenv("GUARD_APPROVALS_DIR", raising=False)
    yield


# ── pure logic: label mapping ─────────────────────────────────────────────────


def test_label_intent_maps_actions():
    assert A.label_intent("approve") == ("add", "operator-merge")
    assert A.label_intent("hold") == ("remove", "operator-merge")
    assert A.label_intent("refresh_hints") is None
    assert A.label_intent("push") is None


# ── pure logic: push-grant reason scoping + override keyword ─────────────────


def test_push_reason_names_branch_and_head_sha():
    reason = A.push_reason(branch=BRANCH, head_sha=SHA)
    assert BRANCH in reason
    assert SHA[:12] in reason
    assert "override" not in reason


def test_push_reason_override_only_when_asked():
    assert "override" not in A.push_reason(branch=BRANCH, head_sha=SHA, override=False)
    assert "override" in A.push_reason(branch=BRANCH, head_sha=SHA, override=True)


def test_built_reason_is_scope_covered_and_lifts_budget_only_with_override():
    reason = A.push_reason(branch=BRANCH, head_sha=SHA)
    covers, why = G.grant_scope_covers(reason, branch=BRANCH, head_sha=SHA)
    assert covers and why == "grant names this branch"
    assert B.grant_overrides_budget(reason) is False
    over = A.push_reason(branch=BRANCH, head_sha=SHA, override=True)
    assert G.grant_scope_covers(over, branch=BRANCH, head_sha=SHA)[0] is True
    assert B.grant_overrides_budget(over) is True


# ── pure logic: fast-forward only, force stays refused ───────────────────────


def test_push_command_is_fast_forward_only():
    argv = A.push_command(BRANCH, SHA)
    assert argv[:2] == ["git", "push"]
    assert "origin" in argv and f"{SHA}:refs/heads/{BRANCH}" in argv
    for bad in ("--force", "--force-with-lease", "--mirror", "--delete"):
        assert bad not in argv, bad


def test_force_refusal_blocks_history_rewrite():
    assert A.force_refusal({"force": True}) is not None
    assert A.force_refusal({"force_with_lease": True}) is not None
    assert A.force_refusal({"rewrite_history": "1"}) is not None
    assert A.force_refusal({"reason": "please --force push"}) is not None
    assert A.force_refusal({"reason": "fast-forward", "override": False}) is None


# ── perform: authority first (identity + CSRF), then the action ──────────────


def test_perform_refuses_without_operator_identity(tmp_path):
    code, body = A.perform({"action": "hold", "pr_number": 1, "head_sha": SHA},
                           actor="service-token", csrf_ok=True, repo_root=tmp_path)
    assert code == 403 and body["refusal"] == "NO_OPERATOR_IDENTITY"
    assert body["outcome"] == "REFUSED"


def test_perform_refuses_without_csrf(tmp_path):
    code, body = A.perform({"action": "hold", "pr_number": 1, "head_sha": SHA},
                           actor="tailnet:operator", csrf_ok=False,
                           csrf_reason="csrf: no request context", repo_root=tmp_path)
    assert code == 403 and body["refusal"] == "CSRF"


def test_perform_approve_adds_label_bound_to_head(tmp_path):
    calls = {}
    view = {"state": "OPEN", "headRefOid": SHA, "isDraft": False}

    def fake_view(pr_number, *, repo):
        calls["viewed"] = pr_number
        return view

    def fake_add(pr_number, *, repo):
        calls["added"] = pr_number
        return {"ok": True, "rc": 0}

    def fake_comment(pr_number, body, *, repo):
        calls["comment"] = pr_number
        return {"ok": True}

    code, body = A.perform({"action": "approve", "pr_number": 2211, "head_sha": SHA},
                           actor="tailnet:operator", csrf_ok=True, repo_root=tmp_path,
                           pr_view=fake_view, add_label=fake_add, comment=fake_comment)
    assert code == 200 and body["ok"] and body["outcome"] == "LABEL_ADDED"
    assert calls["added"] == 2211 and calls["comment"] == 2211


def test_perform_approve_refuses_head_changed(tmp_path):
    def fake_view(pr_number, *, repo):
        return {"state": "OPEN", "headRefOid": "f" * 40, "isDraft": False}

    code, body = A.perform({"action": "approve", "pr_number": 2211, "head_sha": SHA},
                           actor="tailnet:operator", csrf_ok=True, repo_root=tmp_path,
                           pr_view=fake_view, add_label=lambda pr_number, *, repo: {"ok": True})
    assert code == 409 and body["refusal"] == "HEAD_CHANGED"


def test_perform_hold_removes_label(tmp_path):
    removed = []

    def fake_view(pr_number, *, repo):
        return {"state": "OPEN", "headRefOid": SHA, "isDraft": False}

    def fake_remove(pr_number, *, repo):
        removed.append(pr_number)
        return {"ok": True, "rc": 0}

    code, body = A.perform({"action": "hold", "pr_number": 2211, "head_sha": SHA},
                           actor="tailnet:operator", csrf_ok=True, repo_root=tmp_path,
                           pr_view=fake_view, remove_label=fake_remove)
    assert code == 200 and body["outcome"] == "LABEL_REMOVED" and removed == [2211]


# ── perform: push writes a bound grant then fast-forward pushes ──────────────


def test_perform_push_writes_bound_grant_and_pushes(tmp_path):
    grant_reason = {}
    pushed = {}

    def fake_grant(*, branch, head_sha, reason, adir=None):
        grant_reason["reason"] = reason
        return {"grant_id": "a" * 32}

    def fake_push(branch, head_sha, *, repo_root):
        pushed["branch"] = branch
        pushed["head_sha"] = head_sha
        return {"ok": True, "rc": 0, "argv": A.push_command(branch, head_sha), "stdout": "", "stderr": "",
                "fast_forward_only": True}

    code, body = A.perform({"action": "push", "branch": BRANCH, "head_sha": SHA, "override": False},
                           actor="tailnet:operator", csrf_ok=True, repo_root=tmp_path,
                           write_grant=fake_grant, git_push=fake_push)
    assert code == 200 and body["ok"] and body["outcome"] == "PUSHED"
    assert pushed["branch"] == BRANCH and pushed["head_sha"] == SHA
    assert BRANCH in grant_reason["reason"] and SHA[:12] in grant_reason["reason"]
    assert "override" not in grant_reason["reason"]


def test_perform_push_refuses_force_even_with_operator(tmp_path):
    code, body = A.perform({"action": "push", "branch": BRANCH, "head_sha": SHA, "force": True},
                           actor="tailnet:operator", csrf_ok=True, repo_root=tmp_path)
    assert code == 400 and body["refusal"] == "FORCE_PUSH_REFUSED"


def test_perform_push_override_flows_into_reason(tmp_path):
    grant_reason = {}

    def fake_grant(*, branch, head_sha, reason, adir=None):
        grant_reason["reason"] = reason
        return {"grant_id": "a" * 32}

    def fake_push(branch, head_sha, *, repo_root):
        return {"ok": True, "rc": 0, "argv": [], "stdout": "", "stderr": "", "fast_forward_only": True}

    A.perform({"action": "push", "branch": BRANCH, "head_sha": SHA, "override": True},
              actor="tailnet:operator", csrf_ok=True, repo_root=tmp_path,
              write_grant=fake_grant, git_push=fake_push)
    assert "override" in grant_reason["reason"]


# ── the board projection now carries branch + operator-merge state (P2 additive) ──────────────────


def test_deploy_in_flight_projects_branch_and_operator_merge():
    row = D.project_pr({"number": 2211, "title": "t", "url": "https://github.com/x/y/pull/2211",
                        "headRefOid": SHA, "headRefName": BRANCH, "isDraft": False,
                        "labels": [{"name": "operator-merge"}], "mergeable": True, "mergeStateStatus": "CLEAN"})
    assert row["branch"] == BRANCH and row["has_operator_merge"] is True


def test_api_v2_wires_p2_action_route():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert '"/api/v2/ops/in-flight/action"' in src
    assert "deploy_console_actions" in src
    assert "command_csrf_check" in src
    assert src.index('"/api/v2/ops/in-flight/action"') < src.index("# Inference Layers routes")


def test_module_has_no_push_bypass_or_force_flag():
    src = (ROOT / "scripts" / "lib" / "deploy_console_actions.py").read_text(encoding="utf-8")
    # The push must never set the env bypass that would skip the guard hook. The argv builder's
    # fast-forward-only guarantee (no --force) is asserted on the real argv in test_push_command_is_fast_forward_only.
    assert "TRADEAI_REMOTE_PUSH_AUTHORIZED" not in src
    assert "place_order" not in src
