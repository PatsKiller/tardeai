"""FQ-136 / D39 (operator-approved 2026-11-05): an undatable-in-archive takeover target is UNKNOWN before the cutoff.

The gate resolved every takeover target through the live board and the canonical archive, and refused
``claim_takeover_chain_invalid`` when neither carried it. The archive has no coverage for 2026-10-23..2026-10-25 — 70
distinct targets, measured 2026-11-05 — and those documents are gone, so every claim naming one was permanently
unmergeable. D39 narrows exactly that: a missing target whose own claim id dates it BEFORE 2026-10-26 is UNKNOWN (the
chain validates, and a warning is printed), while a target dated on or after the cutoff, or one whose id is not in the
canonical dated form, still refuses. Nothing else moves: cycles, malformed links, live-claimant contention, archive
validation, review counts, claims, holds and checks are untouched by this file.

Each test here fails on the pre-FQ-136 gate for the reason it names — the pre-cutover case refused, the others already
refused and must keep refusing.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.agent_claim_board import ClaimBoard

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "pr_merge_delegation.py"
NOW = datetime(2030, 1, 7, 23, 45, tzinfo=timezone.utc)  # Monday 18:45 ET: outside the market freeze.
SOURCE = "scripts/synthetic_change.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pr_merge_delegation_fq136", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod():
    return load_module()


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_claim(directory, claim_id, *, session, heartbeat_at=NOW, paths=None, takeover_of=None):
    directory.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "AgentClaim@v1", "claim_id": claim_id, "vendor": "codex", "session": session,
        "agent": None, "task": "synthetic FQ-136 fixture", "paths": list(paths or [SOURCE]), "branch": None,
        "pr": None, "started_at": iso(heartbeat_at), "heartbeat_at": iso(heartbeat_at),
        "status": "active", "note": None, "host": "synthetic", "takeover_of": list(takeover_of or []),
    }
    (directory / f"{claim_id}.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def board_naming(tmp_path, target):
    """One live claim whose only predecessor is ``target`` — nothing named target is on the board or in the archive."""
    directory = tmp_path / "claims"
    write_claim(directory, "20300107T234500Z-live-a-aaaaaaaa", session="session-live", takeover_of=[target])
    return ClaimBoard(directory, stale_after_hours=2.0, now=lambda: NOW)


def test_missing_target_before_the_cutoff_is_unknown_and_warns(mod, tmp_path, capsys):
    """FQ-136: dated 2026-10-25, absent from board and archive -> validates, and says so.

    On the pre-FQ-136 gate this raised ``claim_takeover_chain_invalid``; the assertion on the warning is what keeps the
    release attributable rather than silent.
    """
    target = "20261025T235959Z-claude-archived-gone-abcdef12"
    board = board_naming(tmp_path, target)
    views, unreadable = board.views()
    assert not unreadable

    mod.validate_takeover_graph(views, board)  # must not raise

    captured = capsys.readouterr()
    assert target in captured.err
    assert "UNKNOWN, not invalid" in captured.err
    assert "FQ-136/D39" in captured.err
    # The edge is still unresolved: the release never invents a claim for the missing target.
    assert target not in {view.claim_id for view in views}


@pytest.mark.parametrize("target", [
    "20261026T000000Z-claude-archived-gone-abcdef12",  # the cutoff itself is not "before" it
    "20261101T120000Z-claude-archived-gone-abcdef12",  # inside archive coverage: it could still exist
    "not-a-claim-id",                                  # undatable ids cannot earn the exception
    "20261332T000000Z-claude-impossible-abcdef12",     # a real-looking stamp with an impossible date
])
def test_missing_target_on_or_after_the_cutoff_still_refuses(mod, tmp_path, target):
    """Everything else is unchanged: only a datable pre-cutoff target is released."""
    board = board_naming(tmp_path, target)
    views, unreadable = board.views()
    assert not unreadable
    with pytest.raises(mod.Refused, match="claim_takeover_chain_invalid"):
        mod.validate_takeover_graph(views, board)


def test_archived_target_still_resolves_without_warning_and_cycles_still_refuse(mod, tmp_path, capsys):
    """The release did not become a general loosening: a resolvable target resolves silently, a cycle still refuses."""
    directory = tmp_path / "claims"
    predecessor = "20261020T120000Z-claude-pred-11111111"
    write_claim(directory, "20300107T234500Z-live-a-aaaaaaaa", session="session-live", takeover_of=[predecessor])
    board = ClaimBoard(directory, stale_after_hours=2.0, now=lambda: NOW)
    views, unreadable = board.views()
    assert not unreadable
    archive = board.history
    archived_doc = {
        "schema": "AgentClaimArchive@v1", "state_at_archive": "done", "archived_at": iso(NOW - timedelta(hours=1)),
        "claim": {"schema": "AgentClaim@v1", "claim_id": predecessor, "vendor": "codex", "session": "session-pred",
                  "agent": None, "task": "synthetic", "paths": [SOURCE], "branch": None, "pr": None,
                  "started_at": iso(NOW - timedelta(hours=5)), "heartbeat_at": iso(NOW - timedelta(hours=5)),
                  "status": "done", "note": None, "host": "synthetic", "takeover_of": []},
    }
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(archived_doc, sort_keys=True) + "\n")
    capsys.readouterr()
    mod.validate_takeover_graph(views, board)
    assert "UNKNOWN, not invalid" not in capsys.readouterr().err  # resolved normally, so nothing was released

    # A cycle is still a cycle, cutoff or not.
    x, y = "20261020T120000Z-cycle-x-22222222", "20261020T120000Z-cycle-y-33333333"
    cycle_dir = tmp_path / "cycle"
    write_claim(cycle_dir, x, session="s-x", takeover_of=[y])
    write_claim(cycle_dir, y, session="s-y", takeover_of=[x])
    cycle_board = ClaimBoard(cycle_dir, stale_after_hours=2.0, now=lambda: NOW)
    cycle_views, unreadable = cycle_board.views()
    assert not unreadable
    with pytest.raises(mod.Refused, match="claim_takeover_chain_invalid"):
        mod.validate_takeover_graph(cycle_views, cycle_board)
