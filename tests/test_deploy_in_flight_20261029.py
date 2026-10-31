"""Deploy console in-flight board (GET /api/v2/ops/in-flight), DSN-20261029 + operator clarity.

Hermetic (AGENTS.md §24.6): no network, no live ``gh``. The pure projection
(``project_pr`` / ``why_held`` / ``next_action`` / ``normalize_mergeable`` / digest parity) is
exercised against fixture PR dicts, and ``build`` / ``handle`` with an injected ``lister``.
A gh failure is UNAVAILABLE with a reason, never an empty list wearing "zero".
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import deploy_in_flight as D  # noqa: E402

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
SHA = "e" * 40

PLAIN_BODY = """## In plain English
**What changes:** Adds operator clarity fields to the deploy board.
**Why:** So a non-developer can Approve safely.
**Who / what it affects:** The Releases Deploys tab only.
**When it takes effect:** After merge and promote to CURRENT.
**Approval:** Operator Approve when READY.
**Risk and fallback:** Hold removes the label; no force push.
"""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.delenv("TRADEAI_GITHUB_REPO", raising=False)
    D.clear_cache()
    yield
    D.clear_cache()


def _checks(ok=True):
    state = "SUCCESS" if ok else "FAILURE"
    return [{"name": n, "conclusion": state} for n in D.REQUIRED_CHECKS]


def _pr(number, *, mergeable=None, state="CLEAN", labels=(), draft=False, title="Adds a clear operator sentence here",
        body=None, rollup=None, created=None, updated=None):
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/x/y/pull/{number}",
        "headRefOid": SHA,
        "headRefName": f"branch-{number}",
        "isDraft": draft,
        "labels": [{"name": n} for n in labels],
        "mergeable": mergeable,
        "mergeStateStatus": state,
        "body": PLAIN_BODY if body is None else body,
        "statusCheckRollup": _checks(True) if rollup is None else rollup,
        "createdAt": created or "2026-10-29T12:00:00Z",
        "updatedAt": updated or "2026-10-29T14:00:00Z",
        "author": {"login": "agent"},
    }


def test_normalize_mergeable_three_states():
    assert D.normalize_mergeable(True) == "MERGEABLE"
    assert D.normalize_mergeable(False) == "CONFLICTING"
    assert D.normalize_mergeable(None) == "UNKNOWN"


def test_project_pr_wire_row():
    row = D.project_pr(_pr(2211, mergeable=True, state="CLEAN", labels=["shared-infra"]), now=NOW)
    assert row["number"] == 2211
    assert row["head_sha"] == SHA and row["head_sha_short"] == SHA[:9]
    assert row["mergeable"] == "MERGEABLE" and row["merge_state"] == "CLEAN"
    assert row["is_draft"] is False and row["url"].endswith("/2211")
    assert row["plain_english"]["What changes"]
    assert row["checks"]["cio-hardening"] == "SUCCESS"
    assert row["digest_status"] == "ready" and row["can_approve"] is True
    assert row["updated_age"] == "60m ago"
    assert "Safe to Approve" in row["next_plain"]


def test_why_held_labels_and_mergeability():
    assert D.why_held(_pr(1, mergeable=True, state="CLEAN", labels=["broker"])) == "broker change — operator held"
    assert D.why_held(_pr(2, mergeable=True, labels=["held"])) == "held — operator"
    assert "shared infra" in D.why_held(_pr(3, mergeable=True, labels=["shared-infra"]))
    assert "solo" in D.why_held(_pr(4, mergeable=True, labels=["solo"]))
    assert D.why_held(_pr(5, mergeable=False)) == "merge conflict — needs a coordinator"
    assert D.why_held(_pr(6, mergeable=None)) == "mergeability unknown"
    assert D.why_held(_pr(7, mergeable=True, draft=True)) == "draft — needs the author to mark ready"
    assert D.why_held(_pr(8, mergeable=True, state="BLOCKED")) == "merge blocked"
    assert D.why_held(_pr(9, mergeable=True, state="CLEAN")) is None  # nothing holding it


def test_next_action_four_buckets():
    assert D.next_action(_pr(1, mergeable=True, state="CLEAN")) == "auto-merge"
    assert D.next_action(_pr(2, mergeable=False)) == "coordinator"           # conflict
    assert D.next_action(_pr(3, mergeable=True, labels=["held"])) == "coordinator"  # operator held
    assert D.next_action(_pr(4, mergeable=True, draft=True)) == "coordinator"
    assert D.next_action(_pr(5, mergeable=True, state="BLOCKED")) == "blocked-shard-hints"
    assert D.next_action(_pr(6, mergeable=True, state="BEHIND")) == "auto-rebase"
    assert D.next_action(_pr(7, mergeable=None, state="CLEAN")) == "auto-rebase"


def test_digest_parity_gates_block_approve():
    assert D.digest_classify_row(_pr(1, draft=True))[0] == "draft"
    assert D.digest_classify_row(_pr(2, labels=["operator-merge"]))[0] == "approved"
    assert D.digest_classify_row(_pr(3, mergeable=False))[0] == "conflict"
    assert D.digest_classify_row(_pr(4, body="no plain english here"))[0] == "not_described"
    assert D.digest_classify_row(_pr(5, labels=["held"]))[0] == "needs_operator"
    assert D.digest_classify_row(_pr(6, rollup=_checks(False)))[0] == "waiting_ci"
    status, reason, can = D.digest_classify_row(_pr(7, mergeable=True, state="CLEAN"))
    assert status == "ready" and reason == "ready" and can is True


def test_next_plain_unknown_is_not_conflict():
    row = D.project_pr(_pr(8, mergeable=None, state="CLEAN", rollup=_checks(True)), now=NOW)
    # checks green + plain → ready, but next_plain still explains UNKNOWN mergeability
    assert row["digest_status"] == "ready"
    assert "not the same as a conflict" in row["next_plain"]


def test_build_projects_and_counts():
    rows = [_pr(2211, mergeable=True, state="CLEAN"), _pr(2212, mergeable=False, state="DIRTY", labels=["held"])]
    d = D.build(None, now=NOW, lister=lambda repo, limit: rows)
    assert d["schema"] == "DeployInFlight@v1" and d["authority"] == "READ_ONLY_ADVISORY"
    assert d["count"] == 2 and [r["number"] for r in d["prs"]] == [2211, 2212]
    assert d["prs"][0]["next"] == "auto-merge" and d["prs"][1]["next"] == "coordinator"
    assert d["ready_count"] == 1
    assert d["freshness"] == "OK" and d["status"] == "OK"


def test_build_gh_failure_is_unavailable_not_zero():
    def boom(repo, limit):
        raise RuntimeError("gh pr list failed: not logged in")
    d = D.build(None, now=NOW, lister=boom)
    assert d["prs"] is None and d["count"] is None
    assert d["freshness"] == "UNAVAILABLE" and d["status"] == "UNAVAILABLE"
    assert "not logged in" in d["reason"]


def test_handle_get_only_and_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(D, "build", lambda db: calls.append(1) or {"schema": D.SCHEMA, "count": 0, "prs": []})
    assert D.handle("/api/v2/ops/other", "GET", {}, None) is None
    assert D.handle(D.ROUTE, "POST", {}, None)[0] == 405
    s1, b1 = D.handle(D.ROUTE, "GET", {}, None)
    s2, b2 = D.handle(D.ROUTE + "/", "GET", {}, None)
    assert s1 == s2 == 200 and b1["data"]["cache"] == "MISS" and b2["data"]["cache"] == "HIT" and len(calls) == 1


def test_api_v2_wires_route_before_generic_handlers():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('if base_path.rstrip("/") == "/api/v2/ops/in-flight":')
    assert i < src.index("# Inference Layers routes") < src.index("handler = ROUTES.get(base_path)")


def test_module_is_read_only():
    src = (ROOT / "scripts" / "lib" / "deploy_in_flight.py").read_text(encoding="utf-8")
    # No write path: no file writes, no SQL mutations, no merge/approve/label/promote/order verbs.
    for bad in ("write_text(", "open(\"w", "INSERT ", "UPDATE ", "DELETE ", "place_order",
                "gh pr merge", "gh pr review", "gh label", "-X", "put("):
        assert bad not in src, bad
    # gh is called only as a read: `gh pr list` (and nothing else that mutates).
    assert "gh pr list" in src and "gh api" not in src
    assert "statusCheckRollup" in src and "plain_english" in src
