"""Effective claim-state (stale takeover) regression for pr_merge_delegation.

Private prototype. Every claim is created through the REAL ``ClaimBoard`` (copied
verbatim from the repo) on an isolated ``tmp_path`` state. No repo, runtime, guard
tree, coordination store, network, DB or broker is touched.

ANCHOR: PR_MERGE_DELEGATION_EFFECTIVE_STATE_20261103
"""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from scripts.lib.agent_claim_board import ClaimBoard

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
MAIN = "b" * 40
NOW = datetime(2030, 1, 7, 23, 45, tzinfo=timezone.utc)  # Monday 18:45 ET: outside the freeze.
T0 = NOW - timedelta(hours=3)
COORD = "persistent-state/data/coordination/coordinator/coordinators.json"
SOURCE = "scripts/synthetic_change.py"
ACTOR_B = "coordinator-session-b"
AUTHOR = "author-synthetic"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("process/network is forbidden in merge delegation tests")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.delenv("TRADEAI_AGENT_CLAIMS_STALE_HOURS", raising=False)
    return load("pr_merge_delegation_effective_under_test", "scripts/lib/pr_merge_delegation.py")


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


def iso(at):
    return at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_board(tmp_path, clock):
    return ClaimBoard(tmp_path / "claims", stale_after_hours=2.0, now=clock)


def seed_author(board):
    """A real, released source claim on the source file (head_sha must bind to HEAD)."""
    doc = board.claim(vendor="claude", session=AUTHOR, agent=None, task="synthetic source",
                      paths=[SOURCE], head_sha=HEAD)
    board.release(doc["claim_id"], session=AUTHOR, status="done")
    return doc["claim_id"]


def docs(board):
    return [{k: v for k, v in doc.items() if not k.startswith("_")} for doc in board.read_all()[0]]


def build_snapshot(mod, claims, *, actor=ACTOR_B, author_claim_id="20300107T234500Z-claude-aaaaaaaa"):
    """Model the rest of the snapshot from tests/test_pr_merge_delegation_20261102.py."""
    raw = json.dumps({"reviewer": "reviewer-synthetic-0", "head_sha": HEAD, "verdict": "MERGE"}).encode()
    artifact = "inbox/codex/review-synthetic-0.json"
    checks_module = load("delegation_real_checks_effective", "scripts/lib/pr_all_checks_green.py")
    checks = checks_module.evaluate_merge_rollup([
        {"name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}
        for name in ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")])
    return {
        "authority": {"ok": True, "authority": {"policy_sha": MAIN, "policy_version": "30.0.0",
                      "capability": "coordinator_merge",
                      "requirements": {"ordinary_reviews": 1, "held_reviews": 2},
                      "reserved_paths": ["synthetic/reserved/*"],
                      "ratification": {"pr": 9000, "reviewed_head": MAIN}}},
        "pr": {"number": 9999, "state": "OPEN", "baseRefName": "main", "isDraft": False,
               "headRefOid": HEAD, "headRefName": "wt/synthetic-change", "mergeable": "MERGEABLE",
               "mergeStateStatus": "CLEAN", "files": [SOURCE], "changedFiles": 1,
               "commit_shas": [HEAD]},
        "coordinators": {"schema": "CoordinatorRegistry@v1", "lead": "codex", "coordinators": [
            {"id": "codex", "vendor": "codex", "role": "lead", "territories": ["release"]}]},
        "claims": claims,
        "evidence": {
            "schema": "PrMergeReviewEvidence@v1", "pr": 9999, "head_sha": HEAD,
            "registered_by": {"actor": "codex", "session": actor},
            "identity_provenance": "manual_coordinator_claim_and_source_check",
            "source_commit_shas": [HEAD],
            "authors": [{"actor": "claude", "session": AUTHOR, "claim_id": author_claim_id}],
            "reviews": [{"reviewer_session": "reviewer-synthetic-0", "artifact": artifact,
                         "artifact_sha256": hashlib.sha256(raw).hexdigest(), "head_sha": HEAD,
                         "verdict": "MERGE"}],
            "authors_and_coauthors_complete": True,
            "source_authorship_sha256": mod.digest({"author": None, "commits": [{"oid": HEAD}]}),
            "shared_infra_isolated_reviewed": True, "authority_rails_unchanged": True,
            "section17_review_completed": True, "engineering_tests_completed": True,
            "engineering_docs_completed": True},
        "review_artifacts": {artifact: raw},
        "registration_sha256": "d" * 64,
        "checks": checks, "checks_head": HEAD, "excluded_globs": ["synthetic/reserved/*"],
        "held": False, "held_classes": [], "shared_infra": {"required": False, "ok": True},
        "source_authorship_sha256": mod.digest({"author": None, "commits": [{"oid": HEAD}]}),
        "actor_session": actor,
    }


# --------------------------------------------------------------------------- positive: real takeover


def test_stale_takeover_successor_qualifies(mod, tmp_path):
    clock = Clock(T0)
    board = make_board(tmp_path, clock)
    author_id = seed_author(board)
    a = board.claim(vendor="claude", session="session-a", agent=None, task="holds coordinator and source",
                    paths=[COORD, SOURCE])
    clock.at = NOW  # A's heartbeat is 3 h old: stale.
    b = board.claim(vendor="codex", session=ACTOR_B, agent=None, task="takes over coordinator", paths=[COORD])

    # 1/2. The predecessor file is untouched (still raw-active) while the board resolves it.
    raw_a = json.loads((board.dir / f"{a['claim_id']}.json").read_text(encoding="utf-8"))
    assert raw_a["status"] == "active"
    assert raw_a["takeover_of"] == []
    views, unreadable = board.views()
    assert unreadable == []
    by_id = {view.claim_id: view for view in views}
    assert by_id[a["claim_id"]].state == "stale"
    assert by_id[a["claim_id"]].taken_over_by == [b["claim_id"]]
    assert by_id[b["claim_id"]].state == "live"

    # 3. The successor qualifies even though a raw-active predecessor overlaps the source.
    data = build_snapshot(mod, docs(board), author_claim_id=author_id)
    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is True, result
    assert result["reason"] == "qualified"

    # The same snapshot also resolves from a claims-dir (the Host.collect wiring).
    data["claim_board_dir"] = str(board.dir)
    from_dir = mod.evaluate(data, now=NOW)
    assert from_dir["ok"] is True, from_dir
    assert from_dir["reason"] == "qualified"


def test_superseded_actor_holder_refuses_distinctly(mod, tmp_path):
    clock = Clock(T0)
    board = make_board(tmp_path, clock)
    seed_author(board)
    a = board.claim(vendor="codex", session=ACTOR_B, agent=None, task="coordinator holder",
                    paths=[COORD])
    clock.at = NOW  # A (the actor) went stale without ever taking anyone over.
    board.claim(vendor="codex", session="session-c", agent=None, task="successor", paths=[COORD])

    data = build_snapshot(mod, docs(board), actor=ACTOR_B)
    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is False
    assert result["reason"] == "actor_holder_superseded"


# --------------------------------------------------------------------------- negative: age is not enough


def test_live_predecessor_without_takeover_refuses(mod, tmp_path):
    clock = Clock(NOW)
    board = make_board(tmp_path, clock)
    author_id = seed_author(board)
    a = board.claim(vendor="claude", session="session-a", agent=None, task="live source holder",
                    paths=[SOURCE])
    board.claim(vendor="codex", session=ACTOR_B, agent=None, task="coordinator holder", paths=[COORD])
    views, _ = board.views()
    assert {view.claim_id: view.state for view in views}[a["claim_id"]] == "live"

    data = build_snapshot(mod, docs(board), author_claim_id=author_id)
    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is False
    assert result["reason"] == "current_source_holder_not_released"


def test_stale_predecessor_without_takeover_link_refuses(mod, tmp_path):
    clock = Clock(T0)
    board = make_board(tmp_path, clock)
    author_id = seed_author(board)
    a = board.claim(vendor="claude", session="session-a", agent=None, task="stale source holder",
                    paths=[SOURCE])
    clock.at = NOW  # B claims a non-overlapping path: no takeover link is recorded.
    board.claim(vendor="codex", session=ACTOR_B, agent=None, task="coordinator holder", paths=[COORD])

    views, _ = board.views()
    by_id = {view.claim_id: view for view in views}
    assert by_id[a["claim_id"]].state == "stale"
    assert by_id[a["claim_id"]].taken_over_by == []
    assert json.loads((board.dir / f"{a['claim_id']}.json").read_text())["status"] == "active"

    data = build_snapshot(mod, docs(board), author_claim_id=author_id)
    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is False
    assert result["reason"] == "current_source_holder_not_released"


# --------------------------------------------------------------------------- malformed takeover graphs


def write_claim(directory, claim_id, *, session, status="active", heartbeat_at=NOW,
                paths=None, takeover_of=None, vendor="codex"):
    directory.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "AgentClaim@v1", "claim_id": claim_id, "vendor": vendor, "session": session,
        "agent": None, "task": "synthetic", "paths": list(paths or [SOURCE]), "branch": None,
        "pr": None, "started_at": iso(heartbeat_at), "heartbeat_at": iso(heartbeat_at),
        "status": status, "note": None, "host": "synthetic", "takeover_of": list(takeover_of or []),
    }
    (directory / f"{claim_id}.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                                                encoding="utf-8")
    return doc


def chain_refusal(mod, tmp_path, specs):
    directory = tmp_path / "claims"
    for spec in specs:
        write_claim(directory, **spec)
    board = ClaimBoard(directory, stale_after_hours=2.0, now=lambda: NOW)
    data = build_snapshot(mod, docs(board))
    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is False
    assert result["reason"] == "claim_takeover_chain_invalid"


def test_cycle_is_chain_invalid(mod, tmp_path):
    x, y = "20300107T234500Z-cycle-a-aaaaaaaa", "20300107T234500Z-cycle-b-bbbbbbbb"
    chain_refusal(mod, tmp_path, [
        {"claim_id": x, "session": "session-x", "takeover_of": [y]},
        {"claim_id": y, "session": "session-y", "takeover_of": [x]},
    ])


def test_two_live_claimants_naming_one_predecessor_is_chain_invalid(mod, tmp_path):
    p, l1, l2 = ("20300107T234500Z-pred-a-aaaaaaaa", "20300107T234500Z-live-b-bbbbbbbb",
                 "20300107T234500Z-live-c-cccccccc")
    chain_refusal(mod, tmp_path, [
        {"claim_id": p, "session": "session-p", "heartbeat_at": T0, "paths": [SOURCE]},
        {"claim_id": l1, "session": "session-l1", "paths": [COORD], "takeover_of": [p]},
        {"claim_id": l2, "session": "session-l2", "paths": ["scripts/synthetic_other.py"],
         "takeover_of": [p]},
    ])


def test_stale_claimant_link_is_durable_not_chain_invalid(mod, tmp_path):
    """A successor that later went stale still supplies durable supersession evidence."""
    clock = Clock(T0)
    board = make_board(tmp_path, clock)
    author_id = seed_author(board)
    p = board.claim(vendor="claude", session="session-p", agent=None, task="predecessor",
                    paths=["coordination/coordinator/synthetic-predecessor.json", SOURCE])
    clock.at = NOW
    s = board.claim(vendor="codex", session="session-s", agent=None, task="successor",
                    paths=["coordination/coordinator/synthetic-predecessor.json"])
    b = board.claim(vendor="codex", session=ACTOR_B, agent=None, task="coordinator holder",
                    paths=[COORD])
    clock.at = NOW + timedelta(hours=3)
    board.heartbeat(b["claim_id"], session=ACTOR_B)  # the actor stays live; S goes stale

    states = mod.effective_claim_states(docs(board), board)
    assert states[p["claim_id"]] == "superseded"  # named by the now-stale S
    assert states[s["claim_id"]] == "unresolved"  # stale, named by nobody
    assert states[b["claim_id"]] == "live"

    data = build_snapshot(mod, docs(board), author_claim_id=author_id)
    result = mod.evaluate(data, now=clock.at, claim_board=board)
    assert result["ok"] is True, result


def test_takeover_link_to_missing_target_is_chain_invalid(mod, tmp_path):
    m = "20300107T234500Z-live-a-aaaaaaaa"
    chain_refusal(mod, tmp_path, [
        {"claim_id": m, "session": "session-m", "paths": [COORD],
         "takeover_of": ["20300107T234500Z-missing-b-bbbbbbbb"]},
    ])


# --------------------------------------------------------------------------- durable supersession


def test_released_successor_keeps_predecessor_superseded(mod, tmp_path):
    """A takeover is durable: releasing the successor must not un-supersede the predecessor."""
    clock = Clock(T0)
    board = make_board(tmp_path, clock)
    author_id = seed_author(board)
    a = board.claim(vendor="claude", session="session-a", agent=None, task="holds coordinator and source",
                    paths=[COORD, SOURCE])
    clock.at = NOW
    b = board.claim(vendor="codex", session=ACTOR_B, agent=None, task="takes over coordinator", paths=[COORD])
    board.release(b["claim_id"], session=ACTOR_B, status="done")

    raw_b = json.loads((board.dir / f"{b['claim_id']}.json").read_text(encoding="utf-8"))
    assert raw_b["status"] == "done"
    assert raw_b["takeover_of"] and raw_b["takeover_of"][0]["claim_id"] == a["claim_id"]

    states = mod.effective_claim_states(docs(board), board)
    assert states[a["claim_id"]] == "superseded"
    assert states[b["claim_id"]] == "released"

    # The next coordinator holder can merge; the completed takeover still frees the source.
    c = board.claim(vendor="codex", session="session-c", agent=None, task="next coordinator holder",
                    paths=[COORD])
    data = build_snapshot(mod, docs(board), actor="session-c", author_claim_id=author_id)
    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is True, result
    assert mod.effective_claim_states(docs(board), board)[a["claim_id"]] == "superseded"


def test_forged_takeover_of_live_predecessor_does_not_supersede(mod, tmp_path):
    """A link naming a live claim is ineffective: it stays live and keeps blocking."""
    clock = Clock(NOW)
    board = make_board(tmp_path, clock)
    author_id = seed_author(board)
    p = board.claim(vendor="claude", session="session-p", agent=None, task="live source holder",
                    paths=[SOURCE])
    board.claim(vendor="codex", session=ACTOR_B, agent=None, task="coordinator holder", paths=[COORD])
    write_claim(board.dir, "20300107T234500Z-forge-a-ffffffff", session="session-forge",
                paths=["scripts/synthetic_other.py"], heartbeat_at=NOW,
                takeover_of=[p["claim_id"]])

    # The board's raw resolver marks P stale just because an active claim names it.
    views, _ = board.views()
    assert {view.claim_id: view.state for view in views}[p["claim_id"]] == "stale"
    # The effective classification refuses to let a forged link defeat a live predecessor.
    states = mod.effective_claim_states(docs(board), board)
    assert states[p["claim_id"]] == "live"

    data = build_snapshot(mod, docs(board), author_claim_id=author_id)
    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is False
    assert result["reason"] == "current_source_holder_not_released"


# --------------------------------------------------------------------------- read-only proof


def tree_state(root, *, exclude=None):
    out = {}
    root = Path(root)
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if exclude is not None and (path == exclude or exclude in path.parents):
            continue
        if path.is_dir():
            out[str(path)] = ("dir",)
        elif path.is_file():
            st = path.stat()
            out[str(path)] = (st.st_size, st.st_mtime_ns,
                              hashlib.sha256(path.read_bytes()).hexdigest())
    return out


def test_evaluate_is_readonly_and_uses_only_read_apis(mod, tmp_path, monkeypatch):
    clock = Clock(T0)
    board = make_board(tmp_path, clock)
    author_id = seed_author(board)
    board.claim(vendor="claude", session="session-a", agent=None, task="stale holder",
                paths=[COORD, SOURCE])
    clock.at = NOW
    board.claim(vendor="codex", session=ACTOR_B, agent=None, task="successor", paths=[COORD])
    data = build_snapshot(mod, docs(board), author_claim_id=author_id)

    from scripts.lib import agent_claim_board as AB
    tmp_root = Path(os.environ.get("TMPDIR") or "/tmp").resolve()
    scratch_before = tree_state(ROOT, exclude=tmp_root)
    claims_before = tree_state(board.dir)

    def forbidden(*args, **kwargs):
        raise AssertionError("evaluate reached a claim mutation API")

    for name in ("claim", "heartbeat", "release", "extend", "stage", "compact",
                 "refresh_claims", "sync"):
        monkeypatch.setattr(AB.ClaimBoard, name, forbidden)
    monkeypatch.setattr(AB, "_write_exclusive", forbidden)
    monkeypatch.setattr(AB, "_replace_own", forbidden)
    monkeypatch.setattr(AB.LC, "write_sidecars", forbidden)
    monkeypatch.setattr(AB, "log_override", forbidden)

    result = mod.evaluate(data, now=NOW, claim_board=board)
    assert result["ok"] is True, result
    assert tree_state(board.dir) == claims_before
    assert tree_state(ROOT, exclude=tmp_root) == scratch_before


# -- claim-directory contents: one known auxiliary schema is skipped, anything else still refuses -----------------

def _board_with(tmp_path, extra: dict, *, claim_id="c1", session="s1"):
    from lib.agent_claim_board import ClaimBoard
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / f"{claim_id}.json").write_text(json.dumps({
        "schema": "AgentClaim@v1", "claim_id": claim_id, "session": session, "vendor": "claude",
        "status": "active", "started_at": "2030-01-07T23:30:00Z", "heartbeat_at": "2030-01-07T23:30:00Z",
        "paths": ["a.py"],
    }))
    for name, doc in extra.items():
        (claims / name).write_text(json.dumps(doc))
    return ClaimBoard(claims, now=lambda: datetime(2030, 1, 7, 23, 45, tzinfo=timezone.utc))


def test_an_unknown_schema_file_still_refuses_the_whole_board(tmp_path):
    """A file nobody recognises is not silently skipped: it is exactly the case the resolver must refuse."""
    from lib import pr_merge_delegation as mod
    board = _board_with(tmp_path, {"mystery.json": {"schema": "Mystery@v1"}})
    with pytest.raises(mod.Refused) as exc:
        mod.effective_claim_states([{"claim_id": "c1"}], board)
    assert "claim_board_unavailable_or_truncated" in str(exc.value)


def test_a_malformed_claim_file_still_refuses(tmp_path):
    from lib import pr_merge_delegation as mod
    board = _board_with(tmp_path, {"broken.json": {"schema": "AgentClaim@v1"}})
    with pytest.raises(mod.Refused):
        mod.effective_claim_states([{"claim_id": "c1"}], board)
