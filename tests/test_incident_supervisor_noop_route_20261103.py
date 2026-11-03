"""A runbook that succeeded without acting routes to the fixer, not to a person (2026-11-03)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from lib import incident_supervisor as S  # noqa: E402

SPEC = {"success_when": {"json": {"acted": {"not_empty": True}}}}


def test_an_empty_acted_list_is_not_a_fix():
    assert S._action_took_effect(SPEC, json.dumps({"acted": [], "notified": [], "dry": False})) is False


def test_a_real_act_is_a_fix():
    assert S._action_took_effect(SPEC, json.dumps({"acted": ["restart unit"], "dry": False})) is True


def test_unparseable_output_is_not_a_fix():
    assert S._action_took_effect(SPEC, "not json") is False


def test_an_action_without_the_contract_keeps_rc_semantics():
    assert S._action_took_effect({}, "anything") is True


def test_the_runbook_config_declares_the_contract():
    doc = json.loads((ROOT / "config" / "incident_runbook_actions.json").read_text())
    acts = doc.get("actions")
    if isinstance(acts, dict):
        spec = acts.get("cron_self_heal") or {}
    else:
        specs = [s for s in (acts or []) if isinstance(s, dict)]
        spec = next((s for s in specs if s.get("id") == "cron_self_heal" or s.get("name") == "cron_self_heal"), {})
    assert spec.get("success_when", {}).get("json", {}).get("acted"), (type(acts).__name__, list(doc)[:6])
