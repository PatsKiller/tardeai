"""ANCHOR: AGENTS_POLICY_30_0_0 — ratified capabilities never arise from a proposed document."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY = (ROOT / "AGENTS.md").read_text()
MANIFEST = json.loads((ROOT / "config/agent_standing_authority.json").read_text())


def load_authority():
    name = "policy30_authority_under_test"
    spec = importlib.util.spec_from_file_location(name, ROOT / ".cursor/hooks/guard_standing_policy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_immutable_broker_and_behavior_rules_match_observed_main():
    rules = re.search(r"(?ms)^1\. .*?(?=^3\. )", POLICY).group(0)
    assert hashlib.sha256(rules.encode()).hexdigest() == "d92d1c87bb25e18b304a90bcf14dc85ab6b1effcbf9ec47d470187e25d5523a5"


def test_one_30_row_and_manifest_status_agree():
    rows = [x for x in POLICY.splitlines() if x.startswith("| 30.0.0 |")]
    assert len(rows) == 1
    state = re.search(r"(?m)^Status:\s+(PROPOSED|ACTIVE)$", POLICY)[1]
    assert MANIFEST["status"] == state
    assert f"| {state} |" in rows[0]
    if state == "PROPOSED":
        assert re.search(r"(?m)^Effective-Date:\s+PENDING$", POLICY)
        assert all(value is None for value in MANIFEST["ratification"].values())


def test_real_proposed_payload_cannot_authorize_even_apply_capability():
    validator = load_authority()
    for capability in validator.CAPABILITIES:
        result = validator.authorize(POLICY, MANIFEST, capability=capability, policy_sha="b" * 40,
                                     branch="wt/synthetic-policy-fixture")
        if MANIFEST["status"] == "PROPOSED":
            assert result["ok"] is False
            assert result["authority"] is None
        else:
            assert result["ok"] is True
            assert result["authority"]["ratification"] == MANIFEST["ratification"]


def test_delegation_definitions_are_reserved_and_registry_rule_present():
    held = json.loads((ROOT / "config/merge_hold_paths.json").read_text())
    globs = next(x["globs"] for x in held["classes"] if x["id"] == "merge_deploy_control")
    for path in ("config/agent_standing_authority.json", "scripts/lib/pr_merge_delegation.py",
                 "scripts/lib/pr_all_checks_green.py"):
        assert path in globs
        assert path in MANIFEST["reserved_paths"]
    assert "Register each approved plan once on the server" in POLICY
    assert "§28.17" in POLICY
