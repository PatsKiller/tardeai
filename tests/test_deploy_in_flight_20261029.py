"""Deploy console in-flight board (GET /api/v2/ops/in-flight), DSN-20261029 + operator clarity.

Hermetic (AGENTS.md §24.6): no network, no live ``gh``. The pure projection
(``project_pr`` / ``why_held`` / ``next_action`` / ``normalize_mergeable`` / digest parity) is
exercised against fixture PR dicts, and ``build`` / ``handle`` with an injected ``lister``.
A gh failure is UNAVAILABLE with a reason, never an empty list wearing "zero".
"""
from __future__ import annotations

import json
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
    # A real rollup row carries the completed status AND its conclusion; the digest's every-check gate refuses
    # a row with no explicit completed status, so the fixture states it the way GitHub does.
    state = "SUCCESS" if ok else "FAILURE"
    return [{"name": n, "status": "completed", "conclusion": state} for n in D.REQUIRED_CHECKS]


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


def _files(*paths: str, changed: int | None = None) -> dict:
    """A `gh pr view --json files,changedFiles` body for the READY file gate."""
    return {"files": [{"path": p, "additions": 1, "deletions": 0} for p in paths],
            "changedFiles": len(paths) if changed is None else changed}


def test_normalize_mergeable_three_states():
    assert D.normalize_mergeable(True) == "MERGEABLE"
    assert D.normalize_mergeable(False) == "CONFLICTING"
    assert D.normalize_mergeable(None) == "UNKNOWN"


def test_project_pr_wire_row():
    row = D.project_pr(_pr(2211, mergeable=True, state="CLEAN", labels=["shared-infra"]), now=NOW,
                       files_for=lambda n: _files("scripts/foo.py"))
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
    # 2026-11-02 (operator-requested Releases fix): an UNMEASURED mergeability is not a conflict.
    # GitHub's "UNKNOWN" means "not computed yet"; it used to be bucketed as auto-rebase, which told the
    # board a rebase was needed for a state nobody had measured.
    assert D.next_action(_pr(7, mergeable=None, state="CLEAN")) == "coordinator"


def test_digest_parity_gates_block_approve():
    assert D.digest_classify_row(_pr(1, draft=True))[0] == "draft"
    assert D.digest_classify_row(_pr(2, labels=["operator-merge"]))[0] == "approved"
    assert D.digest_classify_row(_pr(3, mergeable=False))[0] == "conflict"
    assert D.digest_classify_row(_pr(4, body="no plain english here"))[0] == "not_described"
    assert D.digest_classify_row(_pr(5, labels=["held"]))[0] == "needs_operator"
    assert D.digest_classify_row(_pr(6, rollup=_checks(False)))[0] == "waiting_ci"
    status, reason, can = D.digest_classify_row(_pr(7, mergeable=True, state="CLEAN"), files=["scripts/foo.py"])
    assert status == "ready" and reason == "ready" and can is True


def test_a_non_required_check_that_is_red_keeps_approve_off():
    """codex-cloud F1 at 567486a98: the digest's gate is `every_check_green`, not the required four alone.

    With the four required checks SUCCESS and `secret-scan` FAILED, the board used to return ('ready', True)
    while `pr_merge_digest.classify_pr` returns skip for the same rollup — enabling Approve on a PR the digest
    would hold, under the sentence "same READY rules as Telegram".
    """
    rollup = _checks(True) + [{"name": "secret-scan", "conclusion": "FAILURE"}]
    status, reason, can = D.digest_classify_row(_pr(11, mergeable=True, state="CLEAN", rollup=rollup),
                                                files=["scripts/foo.py"])
    assert (status, can) == ("waiting_ci", False), (status, reason, can)
    # a PENDING non-required check is not green either
    pending = _checks(True) + [{"name": "provider-cost", "conclusion": "PENDING"}]
    assert D.digest_classify_row(_pr(12, mergeable=True, state="CLEAN", rollup=pending),
                                 files=["scripts/foo.py"])[:1] == ("waiting_ci",)
    # and the control: the same rollup with secret-scan green is ready
    green = _checks(True) + [{"name": "secret-scan", "conclusion": "SUCCESS"}]
    assert D.digest_classify_row(_pr(13, mergeable=True, state="CLEAN", rollup=green),
                                 files=["scripts/foo.py"]) == ("ready", "ready", True)


def test_ready_requires_a_file_view_and_a_missing_one_is_never_approvable():
    """F1 (PR 2307): the digest's LAST gate is the changed-path hold rule. A row that passes every other gate but
    whose files nobody read is NOT ready — that is the defect this test replaces, which used to assert ready/True."""
    pr = _pr(7, mergeable=True, state="CLEAN")
    status, reason, can = D.digest_classify_row(pr)
    assert (status, reason, can) == ("files_unverified", "files_unverified", False)

    row = D.project_pr(pr, now=NOW)  # no files_for: the honest default
    assert row["can_approve"] is False and row["digest_status"] == "files_unverified"
    assert "could not be checked" in row["next_plain"] and "Safe to Approve" not in row["next_plain"]


def test_a_hold_rule_on_a_changed_path_blocks_approve_even_with_no_hold_label():
    """The digest's held_class gate, which the board did not reproduce (PR 2307 F1)."""
    pr = _pr(8, mergeable=True, state="CLEAN")  # no hold label anywhere
    status, reason, can = D.digest_classify_row(pr, files=["scripts/schwab_position_sync.py"])
    assert status == "needs_operator" and reason.startswith("held:") and can is False
    row = D.project_pr(pr, now=NOW, files_for=lambda n: _files("scripts/schwab_position_sync.py"))
    assert row["can_approve"] is False and "hold rule covers a path" in row["next_plain"]


def test_a_partial_file_view_is_never_approvable():
    """The digest refuses to offer Approve when `changedFiles` exceeds the paths it could read."""
    pr = _pr(9, mergeable=True, state="CLEAN")
    pr["changedFiles"] = 5
    status, reason, can = D.digest_classify_row(pr, files=["scripts/a.py", "scripts/b.py"])
    assert (status, can) == ("files_unverified", False)
    # a full view of the same PR is ready
    full = ["scripts/%s.py" % c for c in "abcde"]
    assert D.digest_classify_row(pr, files=full) == ("ready", "ready", True)
    # and the count from the loader wins over len(files)
    row = D.project_pr(_pr(9, mergeable=True, state="CLEAN"), now=NOW, files_for=lambda n: _files("scripts/a.py", changed=5))
    assert row["can_approve"] is False


def test_an_unreadable_file_view_is_not_a_pass():
    def boom(_n):
        raise RuntimeError("gh pr view failed: rate limited")
    row = D.project_pr(_pr(10, mergeable=True, state="CLEAN"), now=NOW, files_for=boom)
    assert row["can_approve"] is False and row["digest_status"] == "files_unverified"
    assert row["digest_reason"] == "files_unreadable:RuntimeError"


def test_a_malformed_file_view_is_never_a_verified_empty_scope():
    """cx-openai-4 R4 at 8cd7fee69: a successful-but-unusable view used to become files=[]/changed0 and ready.

    The no-file-view control was closed by F1, but a returned ``{}`` / ``None`` / ``[]`` body, a pathless file
    object and a string count all still produced a verified empty scope and enabled Approve.
    """
    pr = _pr(20, mergeable=True, state="CLEAN")
    for bad in ({}, None, [], {"files": None, "changedFiles": 0}):
        row = D.project_pr(pr, now=NOW, files_for=lambda n, bad=bad: bad)
        assert row["digest_status"] == "files_unverified" and row["can_approve"] is False, bad
    # a pathless file object used to become the literal path "None"
    row = D.project_pr(pr, now=NOW, files_for=lambda n: {"files": [{}], "changedFiles": 1})
    assert (row["digest_status"], row["can_approve"]) == ("files_unverified", False)
    # a string count is not a typed count
    row = D.project_pr(pr, now=NOW, files_for=lambda n: {"files": [{"path": "scripts/foo.py"}], "changedFiles": "1"})
    assert (row["digest_status"], row["can_approve"]) == ("files_unverified", False)
    # the healthy control: a current, consistent view is still ready
    row = D.project_pr(pr, now=NOW, files_for=lambda n: _files("scripts/foo.py"))
    assert (row["digest_status"], row["can_approve"]) == ("ready", True)


def test_digest_classify_row_refuses_an_inconsistent_or_unusable_path_list():
    base = _pr(21, mergeable=True, state="CLEAN")
    assert D.digest_classify_row(base, files=[]) == ("files_unverified", "files_unverified", False)
    assert D.digest_classify_row({**base, "changedFiles": 2}, files=["scripts/a.py"])[:1] == ("files_unverified",)
    assert D.digest_classify_row({**base, "changedFiles": True}, files=["scripts/a.py"])[:1] == ("files_unverified",)
    assert D.digest_classify_row(base, files=["None"])[:1] == ("files_unverified",)
    assert D.digest_classify_row(base, files=[""])[:1] == ("files_unverified",)
    assert D.digest_classify_row({**base, "changedFiles": 1}, files=["scripts/a.py"]) == ("ready", "ready", True)


def test_build_does_not_count_a_malformed_file_view_as_ready():
    """The finding reproduced this through the real build/projection path, not just the pure classifier."""
    rows = [_pr(30, mergeable=True, state="CLEAN")]
    d = D.build(None, now=NOW, lister=lambda repo, limit: rows,
                coordination=lambda prs, now: {"status": "OK", "work": {}},
                files_for=lambda n: {})
    assert d["status"] == "OK" and d["freshness"] == "OK"
    assert d["ready_count"] == 0 and d["prs"][0]["can_approve"] is False
    assert d["prs"][0]["digest_status"] == "files_unverified"


def test_next_plain_unknown_is_not_conflict():
    row = D.project_pr(_pr(8, mergeable=None, state="CLEAN", rollup=_checks(True)), now=NOW,
                       files_for=lambda n: _files("scripts/foo.py"))
    # checks green + plain → ready, but next_plain still explains UNKNOWN mergeability
    assert row["digest_status"] == "ready"
    assert "not the same as a conflict" in row["next_plain"]


def test_build_projects_and_counts():
    rows = [_pr(2211, mergeable=True, state="CLEAN"), _pr(2212, mergeable=False, state="DIRTY", labels=["held"])]
    d = D.build(None, now=NOW, lister=lambda repo, limit: rows, files_for=lambda n: _files("scripts/foo.py"))
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


# ─────────────────────────── 2026-11-02: the string form GitHub's API actually returns
def test_normalize_mergeable_accepts_the_enum_form_as_well_as_the_boolean():
    """`gh pr list --json mergeable` gives a boolean; the GraphQL/API projection gives the enum strings.

    Only the boolean was handled, so a real "CONFLICTING" fell through to UNKNOWN and the PR lost its
    conflict bucket, while "MERGEABLE" read as unknown too.
    """
    assert D.normalize_mergeable("MERGEABLE") == "MERGEABLE"
    assert D.normalize_mergeable("CONFLICTING") == "CONFLICTING"
    assert D.normalize_mergeable("UNKNOWN") == "UNKNOWN"
    assert D.normalize_mergeable(" mergeable ") == "MERGEABLE"  # case/space tolerant
    assert D.normalize_mergeable(True) == "MERGEABLE"
    assert D.normalize_mergeable(False) == "CONFLICTING"
    assert D.normalize_mergeable(None) == "UNKNOWN"
    assert D.normalize_mergeable("something-else") == "UNKNOWN"  # never a guess


def test_unknown_never_implies_a_rebase_even_in_the_string_form():
    for value in (None, "UNKNOWN", "unknown", "not-a-state"):
        assert D.next_action(_pr(9, mergeable=value, state="CLEAN")) == "coordinator", value
    # A real conflict in the string form is bucketed as a conflict, not as unknown.
    assert D.next_action(_pr(10, mergeable="CONFLICTING", state="CLEAN")) == "coordinator"
    assert D.why_held(_pr(11, mergeable="CONFLICTING")) == "merge conflict — needs a coordinator"
    assert D.why_held(_pr(12, mergeable="MERGEABLE", state="CLEAN")) is None


# ────────────────── 2026-11-02: the additive coordination view on the same GET projection
def test_the_coordination_view_is_additive_and_preserves_the_existing_keys():
    """The PR list keeps its keys and values; the envelope and per-row `work` are added beside them."""
    rows = [_pr(2211, mergeable=True, state="CLEAN")]
    seen = {}

    def fake_coordination(prs, now):
        seen["prs"] = [p["number"] for p in prs]
        return {"schema": "ReleasesCoordination@v1", "status": "OK", "as_of": "2026-11-02T17:00:00Z",
                "captured_at": "2026-11-02T18:00:00Z", "source": "claims+coordinator_ledger", "gaps": [],
                "agents": [], "authority": "READ_ONLY_ADVISORY",
                "work": {2211: {"owner": "s1", "current_task": "t", "publication_state": "published",
                                "local_head": "a" * 40, "published_head": "a" * 40,
                                "review": {"state": "MERGE", "head_sha": "a" * 40, "as_of": "2026-11-02T17:00:00Z",
                                           "source": "coordinator_ledger"},
                                "ci": {"state": "GREEN", "head_sha": "a" * 40, "as_of": "2026-11-02T17:30:00Z",
                                       "source": "coordinator_ledger"},
                                "blockers": [], "next_action": "push", "as_of": "2026-11-02T17:30:00Z",
                                "source": "claims"}}}

    d = D.build(None, now=NOW, lister=lambda repo, limit: rows, coordination=fake_coordination,
                files_for=lambda n: _files("scripts/foo.py"))
    assert d["schema"] == "DeployInFlight@v1" and d["generated_at"] and d["count"] == 1
    row = d["prs"][0]
    assert row["number"] == 2211 and row["mergeable"] == "MERGEABLE" and row["next"] == "auto-merge"
    assert row["work"]["owner"] == "s1" and row["work"]["ci"]["state"] == "GREEN"
    assert d["coordination"]["as_of"] == "2026-11-02T17:00:00Z"
    assert d["coordination"]["captured_at"] == "2026-11-02T18:00:00Z"
    assert seen["prs"] == [2211]


def test_a_broken_coordination_read_degrades_only_the_envelope():
    def boom(prs, now):
        raise RuntimeError("ledger on fire")

    d = D.build(None, now=NOW, lister=lambda repo, limit: [_pr(2211, mergeable=True, state="CLEAN")],
                coordination=boom, files_for=lambda n: _files("scripts/foo.py"))
    assert d["status"] == "OK" and d["count"] == 1           # the board still renders
    assert d["coordination"]["status"] == "UNAVAILABLE"
    assert d["coordination"]["gaps"] and "ledger on fire" in d["coordination"]["gaps"][0]
    row = d["prs"][0]
    assert row["work"]["ci"]["state"] == "UNKNOWN" and row["work"]["review"]["state"] == "UNKNOWN"


# ────────────────── 2026-11-03: the DEFAULT coordination reader is the one production uses
# Both tests above inject `coordination=`, so neither ever ran `_default_coordination` — the only reader the
# /api/v2/ops/in-flight route has in a release. It referenced `Path` without importing it and defaulted to a
# repo-relative state root that exists nowhere (portfolio-server/…, trade-ai-v12-rebuild/…), so every live
# read raised NameError and the served Releases page showed UNKNOWN owner/task/review/CI for every PR, with
# the agents panel empty. Run against the release's own module on 2026-11-03:
#   coordination.status = UNAVAILABLE, gaps = ["NameError: name 'Path' is not defined"].
HEAD = "d" * 40


def _state_root_tree(tmp_path: Path) -> Path:
    """The layout `releases_coordination.build` expects under TRADEAI_STATE_ROOT."""
    coord = tmp_path / "data" / "coordination" / "coordinator"
    coord.mkdir(parents=True)
    rows = [
        {"kind": "review_receipt_recorded", "pr_number": 2211, "head_sha": HEAD, "verdict": "BLOCK",
         "reviewer_session": "cc3", "evidence_class": "reported_review_not_approval",
         "observed_at": "2026-11-03T00:30:00Z"},
        {"kind": "ci_observation", "pr_number": 2211, "head_sha": HEAD, "state": "RED",
         "observed_at": "2026-11-03T00:40:00Z", "source": "GitHub Actions", "workflows": []},
    ]
    (coord / "ledger.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (coord / "BOARD.md").write_text(
        "# COORDINATION BOARD\n\nUpdated: 2026-11-03T00:45:00Z by **codex** (x).\n\n"
        "## Agents\n\n| session | task now | branch / PR | next |\n|---|---|---|---|\n"
        "| cc-deepseek-4 | Releases coordination fix | wt/x | push |\n\n## Open PRs\n",
        encoding="utf-8")
    claims = tmp_path / "data" / "coordination" / "claims"
    claims.mkdir(parents=True)
    (claims / "c0.json").write_text(json.dumps({
        "session": "cc-deepseek-4", "branch": "wt/x", "task": "t", "status": "active",
        "head_sha": HEAD, "heartbeat_at": "2026-11-03T00:44:00Z",
    }), encoding="utf-8")
    return tmp_path


def test_the_default_coordination_reader_really_runs(tmp_path, monkeypatch):
    """Production passes no `coordination=` argument: this is the path the operator's page depends on."""
    root = _state_root_tree(tmp_path)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(root))
    rows = [{"number": 2211, "title": "t", "url": "u", "headRefOid": HEAD, "headRefName": "wt/x",
             "isDraft": False, "labels": [], "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN"}]

    # This scenario observes the November fixtures after their last recorded event.
    snapshot_at = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc)
    d = D.build(None, now=snapshot_at, lister=lambda repo, limit: rows,
                files_for=lambda n: _files("scripts/foo.py"))  # production default coordination

    assert not any("NameError" in g for g in d["coordination"]["gaps"])
    assert d["coordination"]["status"] == "OK", d["coordination"]["gaps"]
    assert [a["session"] for a in d["coordination"]["agents"]] == ["cc-deepseek-4"]
    work = d["prs"][0]["work"]
    assert work["owner"] == "cc-deepseek-4" and work["review"]["state"] == "BLOCK" and work["ci"]["state"] == "RED"


def test_the_default_state_root_is_env_first_then_the_house_convention(monkeypatch):
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)
    assert D._state_root() == Path.home() / "trade-ai-releases" / "persistent-state"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", "/srv/state")
    assert D._state_root() == Path("/srv/state")


def test_file_views_share_one_aggregate_deadline():
    """A per-call timeout is not a bound: the browser aborts this endpoint at 30 s, so the whole file-view
    projection must fit in one budget. Past it, rows raise and stay files_unverified."""
    t = [0.0]
    seen: list[tuple[int, float]] = []

    def fetch(number, *, timeout):
        seen.append((number, timeout))
        t[0] += timeout  # this call consumed its whole slice
        return {"files": [{"path": "scripts/foo.py"}], "changedFiles": 1}

    bounded = D._bounded_file_views(fetch, budget_s=10.0, clock=lambda: t[0])
    bounded(1)
    assert seen[0][1] <= 10.0
    with pytest.raises(TimeoutError):
        bounded(2)
    assert len(seen) == 1


def test_an_exhausted_file_view_budget_leaves_rows_unverified_not_approved():
    raw = [_pr(n, mergeable=True, state="CLEAN") for n in (1, 2)]
    calls: list[int] = []

    def files_for(number):
        calls.append(number)
        raise TimeoutError("file view budget exhausted")

    out = D.build(lister=lambda repo, limit: raw, files_for=files_for,
                  coordination=lambda rows, now: {"work": {}})
    assert out["status"] == "OK" and out["count"] == 2
    assert calls and all(row["can_approve"] is False for row in out["prs"])
    assert all(row["digest_status"] == "files_unverified" for row in out["prs"])


def test_build_bounds_its_own_file_views(monkeypatch):
    """The default path is the bounded one — a caller that injects nothing still gets the aggregate deadline."""
    seen: list[float] = []

    def fake_view(repo, number, *, timeout=None):
        seen.append(timeout)
        return {"files": [{"path": "scripts/foo.py"}], "changedFiles": 1}

    monkeypatch.setattr(D, "pr_file_view", fake_view)
    raw = [_pr(5, mergeable=True, state="CLEAN")]
    out = D.build(lister=lambda repo, limit: raw, coordination=lambda rows, now: {"work": {}})
    assert out["status"] == "OK" and seen, "the default file view was never called"
    assert seen[0] is not None and seen[0] <= D.FILE_VIEW_BUDGET_S


def test_the_help_glossary_names_the_configured_merge_windows():
    """The glossary must not promise evening/weekend merges: the windows are in .mergify.yml, Mon-Fri only."""
    import re

    cfg = (ROOT / ".mergify.yml").read_text()
    windows = re.findall(r"schedule=Mon-Fri (\d\d:\d\d)-(\d\d:\d\d)\[America/New_York\]", cfg)
    assert windows, "no weekday merge windows found in .mergify.yml"
    drawer = (ROOT / "apps/command-center-v3/src/components/DeployHelpDrawer.tsx").read_text()
    for start, end in windows:
        assert f"{start}–{end}" in drawer, f"the help drawer does not name the {start}-{end} ET window"
    assert "evenings/weekends are the usual merge times" not in drawer
    assert "outside market hours" not in drawer
