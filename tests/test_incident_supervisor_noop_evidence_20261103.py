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
