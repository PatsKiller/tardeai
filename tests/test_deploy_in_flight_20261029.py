"""Deploy console P1 in-flight board (GET /api/v2/ops/in-flight), design DSN-20261029-deploy-console (P1).

Hermetic (AGENTS.md §24.6): no network, no live ``gh``. The pure projection
(``project_pr`` / ``why_held`` / ``next_action`` / ``normalize_mergeable``) is exercised against fixture PR
dicts, and ``build`` / ``handle`` are exercised with an injected ``lister`` returning fixture rows — a gh failure
is UNAVAILABLE with a reason, never an empty list wearing "zero". The route is GET-only and cached.
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


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.delenv("TRADEAI_GITHUB_REPO", raising=False)
    D.clear_cache()
    yield
    D.clear_cache()


def _pr(number, *, mergeable=None, state="CLEAN", labels=(), draft=False, title="t"):
    return {"number": number, "title": title, "url": f"https://github.com/x/y/pull/{number}",
            "headRefOid": SHA, "isDraft": draft,
            "labels": [{"name": n} for n in labels], "mergeable": mergeable,
            "mergeStateStatus": state}


def test_normalize_mergeable_three_states():
    assert D.normalize_mergeable(True) == "MERGEABLE"
    assert D.normalize_mergeable(False) == "CONFLICTING"
    assert D.normalize_mergeable(None) == "UNKNOWN"


def test_project_pr_wire_row():
    row = D.project_pr(_pr(2211, mergeable=True, state="CLEAN", labels=["shared-infra"]))
    assert row["number"] == 2211 and row["title"] == "t"
    assert row["head_sha"] == SHA and row["head_sha_short"] == SHA[:9]
    assert row["mergeable"] == "MERGEABLE" and row["merge_state"] == "CLEAN"
    assert row["is_draft"] is False and row["url"].endswith("/2211")


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


def test_build_projects_and_counts():
    rows = [_pr(2211, mergeable=True, state="CLEAN"), _pr(2212, mergeable=False, state="DIRTY", labels=["held"])]
    d = D.build(None, now=NOW, lister=lambda repo, limit: rows)
    assert d["schema"] == "DeployInFlight@v1" and d["authority"] == "READ_ONLY_ADVISORY"
    assert d["count"] == 2 and [r["number"] for r in d["prs"]] == [2211, 2212]
    assert d["prs"][0]["next"] == "auto-merge" and d["prs"][1]["next"] == "coordinator"
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
                "gh pr merge", "gh pr review", "gh label", "-X", "POST", "put("):
        assert bad not in src, bad
    # gh is called only as a read: `gh pr list` (and nothing else that mutates).
    assert "gh pr list" in src and "gh api" not in src


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

    d = D.build(None, now=NOW, lister=lambda repo, limit: rows, coordination=fake_coordination)
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
                coordination=boom)
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
    d = D.build(None, now=snapshot_at, lister=lambda repo, limit: rows)  # production default coordination

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
