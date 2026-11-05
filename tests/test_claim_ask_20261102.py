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


def test_a_draft_pr_is_reported_but_is_not_a_claim_holder():
    # It cannot be taken over, and it has no claim id -- but suppressing it entirely made `ask` answer
    # "go ahead" about a path an open draft PR is editing.
    out = CA.plan_ask([{**_row(), "source": "draft_pr", "pr": 9999, "branch": "feat/other",
                        "url": "https://example.invalid/pull/9999"}], now_iso=NOW)
    assert out["conflict"] is True and len(out["holders"]) == 1
    h = out["holders"][0]
    assert h["kind"] == "draft_pr" and "claim_id" not in h
    assert h["stale"] is False and "cannot be taken over" in h["next"]
    text = CA.render(out)
    assert "open draft PR #9999" in text and "takeover" not in text


def test_the_board_state_beats_recomputed_age():
    # 7190s rounds to 2.0h and would read as stale by age; the board calls it live and blocking. The board wins.
    row = _row(heartbeat_at="2026-11-02T02:00:10Z", state="live")
    out = CA.plan_ask([row], now_iso=NOW, stale_hours=2.0)
    assert out["holders"][0]["stale"] is False
    row = _row(heartbeat_at="2026-11-01T00:00:00Z", state="stale")
    assert CA.plan_ask([row], now_iso=NOW, stale_hours=2.0)["holders"][0]["stale"] is True


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


# -- the real CLI path: these fail if `ask` stops seeing stale claims, draft PRs, or the global flag ------------

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402


def _load_cli():
    spec = importlib.util.spec_from_file_location("agent_claim_cli_under_test", ROOT / "scripts" / "agent_claim.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _claim_file(tmp_path, *, claim_id, session, path, heartbeat, state="active"):
    claims = tmp_path / "claims"
    claims.mkdir(exist_ok=True)
    (claims / f"{claim_id}.json").write_text(json.dumps({
        "schema": "AgentClaim@v1", "claim_id": claim_id, "session": session, "branch": "wt/other",
        "task": "holder task", "paths": [path], "status": state,
        "started_at": heartbeat, "heartbeat_at": heartbeat, "head_sha": "a" * 40,
    }), encoding="utf-8")
    return claims


def _ask_args(claims, path, *, stale_hours=None, no_gh=True):
    return argparse.Namespace(paths=[path], message=None, stale_hours=stale_hours, json=True,
                              claims_dir=str(claims), session="asker-session", no_gh=no_gh,
                              gh_timeout=15.0, gh_call_timeout=8.0, compact_days=90.0)


def test_the_real_ask_command_sees_a_stale_claim_and_points_at_takeover(tmp_path, capsys):
    """The whole point of the command. It failed because Board.conflicts filtered stale claims out first."""
    claims = _claim_file(tmp_path, claim_id="20261101T000000Z-claude-aaaa1111", session="holder-a",
                         path="tests/fixture_target.py", heartbeat="2026-11-01T00:00:00Z")
    cli = _load_cli()
    assert cli.cmd_ask(_ask_args(claims, "tests/fixture_target.py")) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["conflict"] is True and len(out["holders"]) == 1
    h = out["holders"][0]
    assert h["claim_id"] == "20261101T000000Z-claude-aaaa1111" and h["stale"] is True
    assert h["next"] == "agent_claim.py takeover"


def test_the_real_ask_command_reports_a_draft_pr_instead_of_saying_go_ahead(tmp_path, monkeypatch, capsys):
    claims = tmp_path / "claims"
    claims.mkdir()
    cli = _load_cli()
    monkeypatch.setattr(cli.B, "draft_pr_conflicts", lambda paths, **kw: ([{
        "source": "draft_pr", "pr": 9999, "branch": "feat/draft", "title": "x", "author": "cloud-agent",
        "url": "https://example.invalid/pull/9999",
        "overlaps": [{"path": "tests/fixture_target.py", "held": "tests/fixture_target.py"}]}], None))
    args = _ask_args(claims, "tests/fixture_target.py", no_gh=False)
    assert cli.cmd_ask(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["conflict"] is True and out["holders"][0]["kind"] == "draft_pr"


def test_stale_hours_given_before_the_subcommand_is_honoured():
    """The ask subparser used to redefine --stale-hours with a literal 2.0, discarding the global value."""
    cli = _load_cli()
    parser = cli.build_parser()
    ns = parser.parse_args(["--stale-hours", "5", "ask", "a.py"])
    assert ns.stale_hours == 5.0
