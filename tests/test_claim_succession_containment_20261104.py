"""Succession is containment or explicit — never "any stale claim that shares one file".

`_claim_locked` used to record EVERY stale claim whose paths merely overlapped, so a new claim inherited the whole
stale frontier of a shared file. Measured on the live board before this change: 2,628 edges, 98 (3.7 %) actually
contained, 323 of 397 claims carrying a predecessor list they had no relation to — and two agents touching one file
became "live siblings" that refused every merge.

Every board here is a synthetic ``tmp_path``; no repo, coordination store, network or DB is touched.

ANCHOR: CLAIM_SUCCESSION_CONTAINMENT_20261104
"""
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.agent_claim_board import ClaimBoard, ClaimError, claim_covers

NOW = datetime(2030, 1, 7, 23, 45, tzinfo=timezone.utc)  # Monday 18:45 ET: outside the freeze.
T0 = NOW - timedelta(hours=3)  # older than the 2h stale window below
SHARED = "scripts/api_v2.py"
OTHER = "scripts/lib/other_module.py"
THIRD = "apps/command-center-v3/src/App.tsx"


def _board(tmp_path, clock):
    return ClaimBoard(tmp_path / "claims", stale_after_hours=2.0, now=clock)


def _stale_predecessor(tmp_path, paths):
    """A real claim that went stale (heartbeat at T0, now is T0 + 3h)."""
    board = _board(tmp_path, lambda: T0)
    doc = board.claim(vendor="codex", session="session-old", agent=None, task="old work", paths=paths)
    return doc["claim_id"]


def _claim_now(tmp_path, paths, *, session="session-new", takeover_ids=None):
    board = _board(tmp_path, lambda: NOW)
    doc = board.claim(
        vendor="claude",
        session=session,
        agent=None,
        task="new work",
        paths=paths,
        takeover_ids=takeover_ids,
    )
    return doc, board


# --------------------------------------------------------------------------------------------- the predicate


@pytest.mark.parametrize("mine,theirs", [
    (["scripts/api_v2.py"], ["scripts/api_v2.py"]),
    (["scripts/**"], ["scripts/api_v2.py"]),
    (["scripts/lib"], ["scripts/lib/deep/thing.py"]),
    (["scripts/*.py"], ["scripts/api_v2.py"]),
    ([SHARED, OTHER, THIRD], [SHARED, OTHER]),
    (["scripts/**"], [SHARED, OTHER]),
])
def test_full_succession_is_containment(mine, theirs):
    assert claim_covers(mine, theirs) is True


@pytest.mark.parametrize("mine,theirs", [
    ([SHARED], [SHARED, OTHER]),                    # one shared file of two is not succession
    ([SHARED], [OTHER]),                            # no relation at all
    (["scripts/*.py"], ["scripts/lib/deep/thing.py"]),  # a segment glob does not span directories
    (["scripts/api_v2.py"], ["scripts/**"]),        # a glob predecessor is covered only by itself
    (["scripts/api*.py"], ["scripts/api_*.py"]),    # two different globs, even if they could meet
    ([], [SHARED]),
    ([SHARED], []),
])
def test_partial_or_unrelated_overlap_is_not_succession(mine, theirs):
    assert claim_covers(mine, theirs) is False


# --------------------------------------------------------------------------------------------- the board


def test_a_shared_file_records_an_overlap_link_never_a_succession(tmp_path):
    """The link is still recorded — the state resolver needs it — but it says what it is: shared ancestry."""
    predecessor = _stale_predecessor(tmp_path, [SHARED, OTHER])
    doc, _ = _claim_now(tmp_path, [SHARED])  # the newcomer holds ONLY the shared file
    assert [e["claim_id"] for e in doc["takeover_of"]] == [predecessor]
    assert [e["kind"] for e in doc["takeover_of"]] == ["overlap"], "a shared file was recorded as a succession"


def test_full_containment_still_records_the_predecessor(tmp_path):
    predecessor = _stale_predecessor(tmp_path, [SHARED, OTHER])
    doc, _ = _claim_now(tmp_path, [SHARED, OTHER, THIRD])
    assert [entry["claim_id"] for entry in doc["takeover_of"]] == [predecessor]
    assert doc["takeover_of"][0]["kind"] == "containment", "full succession was not tagged containment"
    assert set(doc["takeover_of"][0]) == {"claim_id", "vendor", "session", "agent", "branch", "heartbeat_at", "kind"}


def test_explicit_takeover_records_a_deliberate_partial_succession(tmp_path):
    predecessor = _stale_predecessor(tmp_path, [SHARED, OTHER])
    doc, _ = _claim_now(tmp_path, [SHARED], takeover_ids=[predecessor])
    assert [entry["claim_id"] for entry in doc["takeover_of"]] == [predecessor]


def test_explicit_takeover_refuses_a_live_claim(tmp_path):
    # Same session, so the claim itself is allowed (a session may hold two claims) and the refusal is the
    # takeover validation — a live predecessor cannot be succeeded, only a stale one.
    board = _board(tmp_path, lambda: NOW)
    live = board.claim(vendor="codex", session="session-x", agent=None, task="live", paths=[SHARED, OTHER])
    with pytest.raises(ClaimError, match="not stale"):
        board.claim(vendor="claude", session="session-x", agent=None, task="other",
                    paths=[SHARED], takeover_ids=[live["claim_id"]])


def test_explicit_takeover_refuses_an_unknown_claim(tmp_path):
    with pytest.raises(ClaimError, match="not a claim on this board"):
        _claim_now(tmp_path, [SHARED], takeover_ids=["20300107T234500Z-ghost-aaaaaaaa"])


def test_explicit_takeover_refuses_a_disjoint_claim(tmp_path):
    predecessor = _stale_predecessor(tmp_path, [OTHER])
    with pytest.raises(ClaimError, match="shares none"):
        _claim_now(tmp_path, [SHARED], takeover_ids=[predecessor])


def test_explicit_and_mechanical_targets_are_deduplicated(tmp_path):
    first = _stale_predecessor(tmp_path, [SHARED, OTHER])
    second = _stale_predecessor(tmp_path, [THIRD])
    doc, _ = _claim_now(tmp_path, [SHARED, OTHER, THIRD], takeover_ids=[first, second])
    assert sorted(entry["claim_id"] for entry in doc["takeover_of"]) == sorted([first, second])


def test_two_claims_on_one_shared_file_are_siblings_not_a_chain(tmp_path):
    """The measured #2614 shape: one session, two live claims, one shared file — both links are `overlap`, so the merge
    gate sees siblings and does not refuse every merge."""
    _stale_predecessor(tmp_path, [SHARED, OTHER])
    board = _board(tmp_path, lambda: NOW)
    first = board.claim(vendor="claude", session="session-x", agent=None, task="first", paths=[SHARED])
    second = board.claim(vendor="claude", session="session-x", agent=None, task="second", paths=[SHARED])
    assert [e["kind"] for e in first["takeover_of"]] == ["overlap"]
    assert [e["kind"] for e in second["takeover_of"]] == ["overlap"]
    from scripts.lib import pr_merge_delegation as D
    D.validate_takeover_graph(board.views()[0], board)   # siblings, not rivals: no refusal
