"""A no-op runbook is recorded as evidence (the cap still applies until the routing change)."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from lib import incident_supervisor as S  # noqa: E402
SPEC = {"success_when": {"json": {"acted": {"not_empty": True}}}}

def test_empty_acted_is_a_no_op():
    assert S._action_took_effect(SPEC, json.dumps({"acted": []})) is False

def test_a_real_act_is_not_a_no_op():
    assert S._action_took_effect(SPEC, json.dumps({"acted": ["x"]})) is True

def test_without_a_contract_rc_semantics_hold():
    assert S._action_took_effect({}, "not json") is True


def _rec(*actions):
    return {"attempts": [{"action": a, "actor": S.ACTOR, "at": f"2026-11-03T00:0{i}:00Z", "detail": d}
                         for i, (a, d) in enumerate(actions)]}


def test_the_last_runbook_noop_is_detected():
    assert S._last_action_was_noop(_rec(("cron_self_heal", {"no_op": False}), ("cron_self_heal", {"no_op": True}))) is True


def test_a_real_action_after_a_noop_is_not_a_noop():
    assert S._last_action_was_noop(_rec(("cron_self_heal", {"no_op": True}), ("restart_unit", {"no_op": False}))) is False


def test_triage_rows_do_not_count_as_actions():
    assert S._last_action_was_noop(_rec(("cron_self_heal", {"no_op": True}), ("triage", {"no_op": True}))) is True
