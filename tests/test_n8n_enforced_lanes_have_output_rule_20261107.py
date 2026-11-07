"""Every allowlist lane enforced at ``output_receipt: "v2"`` must have an output rule in the served contracts.

2026-11-02: ``conflict-resolver`` was armed for enforcement on 2026-10-29 (42e3211cd: allowlist entry with
``output_receipt: "v2"``) while its health contract carried no ``expected_output`` block. The lane ran fine —
exit 0, ``status: ok``, ``produced_count: 1`` — and ``apply_output_verdict`` stamped
``{"verdict": "unverifiable", "why": "rule_missing"}``, which turns an exit-0 run into RUN_FAILED. Five such
runs opened the lane's breaker on 2026-11-02T14:15:59Z and it has not fired since. The rule landed only on
2026-11-05 (0a540a987, #2368).

The gap was invisible because nothing compared the two configs: the allowlist said "judge this lane's output",
the contract map said nothing, and the executor had to choose — it chose to fail the run. This test makes that
pairing a build-time invariant. Synthetic fixtures only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import n8n_run_executor as E  # noqa: E402

ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
CONTRACTS = ROOT / "config" / "n8n_health_contracts.json"


def enforced_without_rule(allowlist: dict, rules: dict, enforced: str = E.OUTPUT_RECEIPT_ENFORCED) -> list[str]:
    """Lanes the executor will judge at ``live`` mode but for which it has no rule (→ ``rule_missing``)."""
    return sorted(
        lane for lane, entry in allowlist.items()
        if (entry or {}).get("output_receipt") == enforced and lane not in rules
    )


def _rules(contracts: list[dict]) -> dict:
    return E.parse_expected_outputs(json.dumps({"schema": "N8nHealthContracts@v1", "contracts": contracts}).encode())


def test_the_shipped_config_has_no_lane_armed_for_enforcement_without_a_rule():
    allowlist = E.load_allowlist(ALLOWLIST)
    rules = E.parse_expected_outputs(CONTRACTS.read_bytes())
    armed = [lane for lane, e in allowlist.items() if (e or {}).get("output_receipt") == E.OUTPUT_RECEIPT_ENFORCED]
    assert len(armed) >= 50, f"only {len(armed)} enforced lanes — the loaders are not reading what the executor reads"
    assert enforced_without_rule(allowlist, rules) == []


def test_the_check_catches_the_2026_11_02_shape():
    allowlist = {"conflict-resolver": {"output_receipt": "v2"}, "other-lane": {"output_receipt": "v2"}}
    rules = {"other-lane": {"rule": "min_produced", "min_produced": 1}}
    assert enforced_without_rule(allowlist, rules) == ["conflict-resolver"]


def test_a_contract_that_exists_without_an_expected_output_block_is_still_no_rule():
    """The lane's contract entry *did* exist on 2026-11-02; the block inside it did not. The map is the authority."""
    contracts = [
        {"id": "conflict-resolver", "kind": "lane", "status": "REVIEWED"},
        {"id": "other-lane", "kind": "lane", "expected_output": {"rule": "min_produced", "min_produced": 1}},
    ]
    rules = _rules(contracts)
    assert "conflict-resolver" not in rules
    assert enforced_without_rule({"conflict-resolver": {"output_receipt": "v2"}}, rules) == ["conflict-resolver"]


def test_a_lane_that_is_not_armed_is_allowed_to_have_no_rule():
    assert enforced_without_rule({"shadow-lane": {"output_receipt": None}}, {}) == []
