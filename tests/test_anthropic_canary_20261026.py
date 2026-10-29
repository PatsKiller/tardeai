"""Offline operator canary proof: routing, real receipts, and honest refusals."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from scripts import anthropic_governed_canary as canary
from scripts.lib.anthropic_credit import CreditBook
from scripts.lib.anthropic_transport import load_policy

NOW = datetime(2026, 10, 26, 3, tzinfo=timezone.utc)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "source"
    (root / "config").mkdir(parents=True)
    for name in ("anthropic_credit_policy.json", "llm_model_registry.json"):
        (root / "config" / name).write_bytes((canary.ROOT / "config" / name).read_bytes())
    return root


def settled_response(root, request_id="synthetic-canary"):
    policy = load_policy(root)
    book = CreditBook(root, policy)
    book.reserve(request_id, canary.PROCESS, Decimal("0.02"), tier="standard", now=NOW)
    book.settle(request_id, Decimal("0.001"), now=NOW)
    event = {"provider": "anthropic", "request_id": "synthetic-provider-id",
             "source_process": canary.PROCESS, "calculated_cost_usd": 0.001,
             "model": policy["models"]["standard"], "reservation_id": "synthetic-reservation",
             "outcome": "success"}
    (root / "data/runtime/provider_cost/events.jsonl").write_text(json.dumps(event) + "\n")
    return {
        "model": policy["models"]["standard"],
        "choices": [{"message": {"content": '{"status":"ANTHROPIC_CANARY_OK"}'}}],
        "usage": {"anthropic_usage": {"input_tokens": 150, "output_tokens": 20}},
        "_tradeai": {"governance_pass": True, "mock": False, "process_id": canary.PROCESS,
                     "reservation_id": "synthetic-reservation", "provider": "anthropic",
                     "request_id": request_id, "provider_request_id": "synthetic-provider-id",
                     "cost_estimate": 0.001},
    }


def test_dry_run_has_no_dispatch_or_state_writes(monkeypatch, tree):
    monkeypatch.setattr(canary, "ROOT", tree)
    before = sorted(p.relative_to(tree) for p in tree.rglob("*"))
    assert canary.main([]) == 0
    assert sorted(p.relative_to(tree) for p in tree.rglob("*")) == before
    assert not (tree / "data").exists()


def test_apply_refuses_without_operator_confirmation(monkeypatch, tree):
    monkeypatch.setattr(canary, "ROOT", tree)
    monkeypatch.delenv("ANTHROPIC_CANARY_OPERATOR_RUN", raising=False)
    assert canary.main(["--apply"]) == 2
    assert not (tree / "data").exists()


def test_apply_refuses_worktree_even_with_operator_flag(monkeypatch, tree):
    monkeypatch.setattr(canary, "ROOT", tree)
    monkeypatch.setenv("ANTHROPIC_CANARY_OPERATOR_RUN", "1")
    monkeypatch.setattr(Path, "home", lambda: tree / "synthetic-home")
    assert canary.main(["--apply"]) == 2
    assert not (tree / "data").exists()


def test_matching_provider_and_credit_settlement_proves_call(tree):
    response = settled_response(tree)
    proof = canary.prove_response(response, canary.preview(tree), "synthetic-canary", tree)
    assert proof["status"] == "ANTHROPIC_CANARY_VERIFIED"
    assert proof["credit_settlement_verified"] and proof["provider_cost_verified"]


@pytest.mark.parametrize("field,value", [
    ("provider", "grok"), ("mock", True), ("process_id", "another-process"),
    ("request_id", "wrong-request"), ("reservation_id", None), ("governance_pass", False),
])
def test_fallback_mock_and_unrelated_authority_never_pass(tree, field, value):
    response = settled_response(tree)
    response["_tradeai"][field] = value
    with pytest.raises(RuntimeError, match="ANTHROPIC_RESPONSE_NOT_PROVEN"):
        canary.prove_response(response, canary.preview(tree), "synthetic-canary", tree)


@pytest.mark.parametrize("change", ["wrong_model", "empty", "unknown_cost", "over_cap", "wrong_text"])
def test_invalid_response_is_not_a_success(tree, change):
    response = settled_response(tree)
    if change == "wrong_model":
        response["model"] = "synthetic-other-model"
    elif change == "empty":
        response["choices"] = []
    elif change == "unknown_cost":
        response["_tradeai"]["cost_estimate"] = None
    elif change == "over_cap":
        response["_tradeai"]["cost_estimate"] = 0.26
    else:
        response["choices"][0]["message"]["content"] = "not the requested response"
    with pytest.raises(RuntimeError):
        canary.prove_response(response, canary.preview(tree), "synthetic-canary", tree)


@pytest.mark.parametrize("change", ["no_event", "duplicate_event", "wrong_cost", "wrong_process", "is_test",
                                    "wrong_model", "wrong_reservation", "attempt_only", "missing_outcome"])
def test_missing_or_mismatched_cost_receipt_fails(tree, change):
    response = settled_response(tree)
    path = tree / "data/runtime/provider_cost/events.jsonl"
    event = json.loads(path.read_text())
    if change == "wrong_cost":
        event["calculated_cost_usd"] = 0.002
    if change == "wrong_process":
        event["source_process"] = "another-process"
    if change == "is_test":
        event["is_test"] = True
    if change == "wrong_model":
        event["model"] = "synthetic-other-model"
    if change == "wrong_reservation":
        event["reservation_id"] = "another-reservation"
    if change == "attempt_only":
        event["outcome"] = "possibly_billable_attempt"
    if change == "missing_outcome":
        event.pop("outcome")
    path.write_text("" if change == "no_event" else (json.dumps(event) + "\n") * (2 if change == "duplicate_event" else 1))
    with pytest.raises(RuntimeError, match="CREDIT_AND_PROVIDER_COST_NOT_RECONCILED"):
        canary.prove_response(response, canary.preview(tree), "synthetic-canary", tree)


def test_real_governance_refusal_is_preserved(tree):
    with pytest.raises(RuntimeError, match="BRIDGE_REFUSED:PROCESS_CAP_EXCEEDED"):
        canary.prove_response({"error": {"code": "PROCESS_CAP_EXCEEDED"}}, canary.preview(tree), "x", tree)


def test_operator_enabled_journal_has_one_admitted_writer():
    registry = json.loads((canary.ROOT / "config/data_source_authority.json").read_text())
    row = next(r for r in registry["domains"] if r["domain"] == "anthropic_promotional_credit")
    assert row["writer"] == "scripts/lib/anthropic_credit.py"
    assert "what disable enable and test call" in row["approval"]["reference"]
    assert not any(r["domain"] == row["domain"] for r in registry["proposed_domains"])
    # An approval record is not an authentication or live-provider proof.
    assert "not a successful authentication/canary" in row["approval"]["reference"]


def test_deployed_apply_uses_manual_registered_route_and_writes_receipt(monkeypatch, tree):
    from scripts.lib import anthropic_monitoring, anthropic_routing, n8n_model_job

    home = tree.parent / "synthetic-home"
    current = home / "trade-ai-releases/portfolio-server/CURRENT"
    current.parent.mkdir(parents=True)
    current.symlink_to(tree, target_is_directory=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(canary, "ROOT", tree)
    monkeypatch.setenv("ANTHROPIC_CANARY_OPERATOR_RUN", "1")
    monkeypatch.setattr(anthropic_monitoring, "configuration_evidence", lambda: (True, "fixture_names"))
    monkeypatch.setattr(anthropic_routing, "state_root", lambda: tree)
    calls = []

    def bridge(messages, **kwargs):
        calls.append((deepcopy(messages), deepcopy(kwargs)))
        return settled_response(tree, kwargs["request_id"])

    monkeypatch.setattr(n8n_model_job, "bridge_governed_call", bridge)
    assert canary.main(["--apply"]) == 0
    assert len(calls) == 1
    assert calls[0][1]["manual_trigger"] is True
    assert calls[0][1]["process_id"] == canary.PROCESS
    assert calls[0][1]["caller"] == "advisory_desk"
    assert calls[0][1]["max_tokens"] == 64
    receipt = json.loads(next((tree / "data/runtime/provider_cost/canaries").glob("*.json")).read_text())
    assert receipt["status"] == "ANTHROPIC_CANARY_VERIFIED"
