"""Ask the real holder of a path, never a guessed session (plan collision F, 2026-11-01)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import claim_ask as CA  # noqa: E402

NOW = "2026-11-02T04:00:00Z"


def _row(**kw):
    base = {
        "source": "claim",
        "claim_id": "20261102T030000Z-claude-abc",
        "session": "worker-a",
        "branch": "wt/x",
        "task": "t",
        "heartbeat_at": "2026-11-02T03:45:00Z",
        "overlaps": [{"path": "a.py", "held": "a.py"}],
    }
    base.update(kw)
    return base


def test_a_live_holder_is_named_with_its_session():
    out = CA.plan_ask([_row()], now_iso=NOW)
    h = out["holders"][0]
    assert h["session"] == "worker-a"
    assert h["stale"] is False
    assert h["next"] == "SendMessage to this session"


def test_a_stale_holder_points_at_takeover_not_a_restart():
    out = CA.plan_ask([_row(heartbeat_at="2026-11-02T00:00:00Z")], now_iso=NOW, stale_hours=2)
    h = out["holders"][0]
    assert h["stale"] is True
    assert h["next"] == "agent_claim.py takeover"


def test_a_draft_pr_conflict_is_not_a_claim_holder():
    out = CA.plan_ask([{**_row(), "source": "draft_pr"}], now_iso=NOW)
    assert out["holders"] == [] and out["conflict"] is False


def test_no_holder_says_the_paths_are_free():
    assert "go ahead" in CA.render(CA.plan_ask([], now_iso=NOW))


def test_render_names_the_session_and_the_message():
    text = CA.render(CA.plan_ask([_row()], now_iso=NOW, message="can you release a.py?"))
    assert "worker-a" in text
    assert "SendMessage to worker-a" in text
    assert "can you release a.py?" in text


def test_a_stale_render_shows_the_takeover_command():
    text = CA.render(CA.plan_ask([_row(heartbeat_at="2026-11-01T00:00:00Z")], now_iso=NOW))
    assert "agent_claim.py takeover 20261102T030000Z-claude-abc" in text


def test_duplicate_rows_for_one_claim_collapse():
    out = CA.plan_ask([_row(), _row()], now_iso=NOW)
    assert len(out["holders"]) == 1
