"""Nudger P2: the lane is registered, and it can only ever run dry while its stage is shadow (2026-11-03).

Board item 16 / P2 of docs/ops/NUDGER_N8N_MIGRATION_PROPOSAL_20261103.md.

The claim this file makes is narrow and mechanical: `agent_nudge` is in the executor's allowlist pointing at the
repo script, its registry row is a dispatcher row whose scheduler.stage is `shadow`, and the stage clamp — the code
that runs on every drain pass — turns a requested LIVE run into a dry run. A reviewer or the lead can therefore
dispatch a live fire at this lane and prove nothing is typed.

Hermetic: reads two committed config files and calls the pure clamp. No tmux, no network, no state write.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import lane_dispatch as LD  # noqa: E402
from scripts.lib.lane_stage_clamp import clamp_mode, load_stage_rows  # noqa: E402

LANE = "agent_nudge"
REGISTRY = ROOT / "config" / "lane_registry.json"
ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"


def _row():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["lanes"]
    found = [r for r in rows if r.get("lane_id") == LANE]
    assert len(found) == 1, f"{LANE}: expected exactly one registry row, found {len(found)}"
    return found[0]


def _entry():
    lanes = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["lanes"]
    found = [e for e in lanes if e.get("lane_id") == LANE]
    assert len(found) == 1, f"{LANE}: expected exactly one allowlist entry, found {len(found)}"
    return found[0]


# ── the registry row ────────────────────────────────────────────────────────────────────────────────


def test_the_row_is_a_dispatcher_row_in_shadow():
    sched = _row()["scheduler"]
    assert sched["kind"] == "n8n"
    assert sched["expression"] == "dispatcher"
    assert sched["stage"] == "shadow", "this lane must stay shadow until an operator-approved flip"


def test_the_row_is_dispatchable_and_carries_no_forbidden_token():
    row = _row()
    assert LD.dispatch_mode(row) == "dry_run"
    assert LD.dispatchable(row) is True
    assert LD.forbidden_hits(row) == [], "the row text must not name a forbidden class"


def test_the_row_keeps_the_live_cron_line_for_rollback():
    """P2 does not stop the host timer; the rollback record must say what the timer runs."""
    before = _row()["scheduler_before_cutover"]
    assert before["kind"] == "cron"
    assert "agent_nudger.py" in before["command_text"]
    assert "--apply" in before["command_text"], "the live line is the one that actually types"


# ── the allowlist entry ────────────────────────────────────────────────────────────────────────────


def test_the_entry_points_at_the_repo_script_with_a_real_dry_run_arg():
    e = _entry()
    assert e["command"][1] == "scripts/agent_nudger.py"
    assert e["dry_run_arg"] == ["--dry-run"], (
        "the dispatcher's shadow step requires a NON-EMPTY dry_run_arg (lane_dispatch.dispatch_eligible)")
    assert e["live_arg"] == ["--apply"]
    assert e["lock"].startswith("/") and not e["lock"].endswith(".dryrun")
    assert e["timeout_s"] == 120
    assert e["market_gate"] is False
    assert e["output_signal"] == "data/coordination/agent_nudger/state.json"


def test_the_entry_declares_its_environment_instead_of_inheriting_it():
    e = _entry()
    assert isinstance(e.get("env_names"), list), "enforce mode refuses a lane with no declared names"
    assert e.get("env_allowlist_mode") == "enforce"


def test_the_executor_accepts_the_entry():
    sys.path.insert(0, str(ROOT / "scripts"))
    import n8n_run_executor as X  # noqa: E402

    e = _entry()
    assert X.env_policy_problem(e) is None
    assert X.validate_entry(e) is None


# ── the shadow guarantee, proved by the clamp the executor actually calls ──────────────────────────


def test_a_requested_live_run_is_clamped_to_dry_run():
    rows = load_stage_rows(REGISTRY)
    got = clamp_mode(LANE, "live", rows)
    assert got["requested_mode"] == "live"
    assert got["effective_mode"] == "dry_run"
    assert got["clamped"] is True and got["reason"] == "stage_shadow"


def test_the_clamp_assertion_is_not_vacuous():
    """With the stage flipped the SAME call lets live through — so the test above fails if the row is not shadow."""
    rows = load_stage_rows(REGISTRY)
    flipped = [dict(r, scheduler={**r["scheduler"], "stage": "canary"}) if r.get("lane_id") == LANE else r
               for r in rows]
    got = clamp_mode(LANE, "live", flipped)
    assert got["effective_mode"] == "live" and got["clamped"] is False


def test_the_script_still_defaults_to_dry_and_refuses_two_modes_at_once():
    import agent_nudger as N  # noqa: E402

    # --dry-run is accepted and means exactly what the bare command means.
    assert N.main(["--dry-run", "--state", "/dev/null"]) == 0
    # --apply and --dry-run together are an operator mistake, not a silent choice.
    try:
        N.main(["--apply", "--dry-run"])
    except SystemExit as exc:  # argparse exits 2 on a mutually-exclusive violation
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("--apply --dry-run must be refused")
