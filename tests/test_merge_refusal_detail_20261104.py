"""A merge refusal names the overlapping pair without changing its reason code.

The gate's decision is not touched here: a live-siblings overlap still refuses, with exactly the same
``claim_takeover_chain_invalid`` that every consumer and test already reads. What is added is a bounded
``detail`` beside the code — the two claim ids, the predecessor they both succeed, and the overlapping repo
paths (at most five) — so the refusal is actionable without re-deriving it by hand.

No repo state, claim board, network, DB or broker is touched: every board is a synthetic ``tmp_path``.

ANCHOR: MERGE_REFUSAL_NAMES_THE_PAIR_20261104
"""
from datetime import datetime, timedelta, timezone
import importlib.util
import socket
import subprocess
import sys

import pytest

from scripts.lib.agent_claim_board import ClaimBoard

ROOT = None
NOW = datetime(2030, 1, 7, 23, 45, tzinfo=timezone.utc)  # Monday 18:45 ET: outside the freeze.
T0 = NOW - timedelta(hours=3)
SOURCE = "scripts/synthetic_change.py"
PRED = "20300107T234500Z-pred-a-aaaaaaaa"
LIVE_B = "20300107T234500Z-live-b-bbbbbbbb"
LIVE_C = "20300107T234500Z-live-c-cccccccc"


def _load(name, relative):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(name, root / relative)
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
    return _load("pr_merge_delegation_refusal_detail_under_test", "scripts/lib/pr_merge_delegation.py")


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _write(directory, claim_id, *, session, paths, heartbeat_at=NOW, status="active", takeover_of=()):
    directory.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "AgentClaim@v1", "claim_id": claim_id, "vendor": "codex", "session": session,
        "agent": None, "task": "synthetic", "paths": list(paths), "branch": None, "pr": None,
        "started_at": _iso(heartbeat_at), "heartbeat_at": _iso(heartbeat_at), "status": status,
        "note": None, "host": "synthetic", "takeover_of": list(takeover_of),
    }
    (directory / f"{claim_id}.json").write_text(__import__("json").dumps(doc))


def _sibling_board(tmp_path, left_paths, right_paths):
    directory = tmp_path / "claims"
    _write(directory, PRED, session="session-p", paths=["scripts/**"], heartbeat_at=T0)
    _write(directory, LIVE_B, session="session-live-b", paths=left_paths, takeover_of=[PRED])
    _write(directory, LIVE_C, session="session-live-c", paths=right_paths, takeover_of=[PRED])
    return ClaimBoard(directory, stale_after_hours=2.0, now=lambda: NOW)


def test_refusal_detail_names_both_claims_the_predecessor_and_the_path(mod, tmp_path):
    board = _sibling_board(tmp_path, [SOURCE], [SOURCE])
    views, unreadable = board.views()
    assert not unreadable

    with pytest.raises(mod.Refused) as excinfo:
        mod.validate_takeover_graph(views, board)

    # The decision is unchanged and the reason code is still exactly what every consumer reads.
    assert str(excinfo.value) == "claim_takeover_chain_invalid"
    assert excinfo.value.code == "claim_takeover_chain_invalid"
    # The bounded detail names the pair a human has to sequence.
    assert excinfo.value.detail == {
        "class": "live_takeover_siblings_overlap",
        "claims": [LIVE_B, LIVE_C],
        "predecessors": [PRED],
        "paths": [SOURCE],
    }


def test_disjoint_live_siblings_still_validate_and_carry_no_detail(mod, tmp_path):
    board = _sibling_board(tmp_path, ["scripts/a_*.py"], ["scripts/b_*.py"])
    views, unreadable = board.views()
    assert not unreadable
    mod.validate_takeover_graph(views, board)  # never raises


def test_detail_paths_are_bounded_to_five(mod, tmp_path):
    left = [f"scripts/shared_{index}.py" for index in range(8)]
    right = [f"scripts/shared_{index}.py" for index in range(8)]
    board = _sibling_board(tmp_path, left, right)
    views, _ = board.views()
    with pytest.raises(mod.Refused) as excinfo:
        mod.validate_takeover_graph(views, board)
    assert len(excinfo.value.detail["paths"]) == 5
    assert excinfo.value.detail["claims"] == [LIVE_B, LIVE_C]


def test_evaluate_surfaces_the_detail_beside_the_unchanged_reason(mod, tmp_path):
    baseline = _load("effective_state_harness_20261104", "tests/test_pr_merge_delegation_effective_state.py")
    board = _sibling_board(tmp_path, [SOURCE], [SOURCE])
    result = mod.evaluate(baseline.build_snapshot(mod, baseline.docs(board)), now=NOW, claim_board=board)

    assert result["ok"] is False
    assert result["reason"] == "claim_takeover_chain_invalid"
    assert result["detail"]["claims"] == [LIVE_B, LIVE_C]
    assert result["detail"]["paths"] == [SOURCE]


def test_plan_surfaces_the_detail_and_a_plain_refusal_carries_none(mod):
    class Overlap:
        def collect(self, pr, actor_session):
            raise mod.Refused("claim_takeover_chain_invalid", {
                "class": "live_takeover_siblings_overlap",
                "claims": [LIVE_B, LIVE_C], "predecessors": [PRED], "paths": [SOURCE]})

    class Plain:
        def collect(self, pr, actor_session):
            raise mod.Refused("pr_not_ready_open_main")

    overlap = mod.plan(9999, "session-x", adapter=Overlap())
    assert overlap["reason"] == "claim_takeover_chain_invalid"
    assert overlap["detail"]["claims"] == [LIVE_B, LIVE_C]

    plain = mod.plan(9999, "session-x", adapter=Plain())
    assert plain["reason"] == "pr_not_ready_open_main"
    assert plain["detail"] is None
