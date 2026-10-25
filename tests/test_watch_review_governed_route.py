"""No provider, credentials, cap DB, live policy writes or queue draining."""
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

import run_watch_review_canary as canary
import run_watch_review_workers as workers
from lib import llm_consumption as consumption
from lib import watch_review_policy_ledger as ledger
from lib import watch_review_pipeline as pipeline
from lib.llm_model_registry import deepseek_model_id, resolve_logical_policy


def setup_route(monkeypatch):
    policy = {"authorization_policy_id": "fixture-policy", "operator_id": "fixture-operator"}
    monkeypatch.setattr(ledger, "load_policy", lambda policy_id=None: policy)
    create = Mock(return_value={"execution_authorization_id": "fixture-exec", "authorization_policy_id": "fixture-policy"})
    validate = Mock(return_value=(True, "OK", {}))
    consumed = Mock()
    send = Mock(return_value=("fixture response", {"returned_model": "deepseek-flash", "request_id": "fixture-request"}))
    monkeypatch.setattr(ledger, "create_execution_authorization", create)
    monkeypatch.setattr(ledger, "validate_execution_authorization", validate)
    monkeypatch.setattr(ledger, "mark_execution_consumed", consumed)
    monkeypatch.setattr(consumption, "gate_and_generate", send)
    monkeypatch.setattr(ledger, "persist_policy", Mock(side_effect=AssertionError("no implicit authorization")))
    monkeypatch.setattr(ledger, "_atomic_write", Mock(side_effect=AssertionError("no policy identity rewrite")))
    return policy, create, validate, consumed, send


def call(spec, **overrides):
    values = {"agent_id": spec["agent_id"], "symbol": "FIXTURE", "process_id": spec["registered_process_id"],
              "model": spec["model"], "policy": spec["policy"], "prompt": "fixture prompt", "max_cost": 0.01,
              "manual_trigger": False, "policy_id": "fixture-policy"}
    return canary.run_agent_call(**{**values, **overrides})


@pytest.mark.parametrize("spec", [ledger.MARIA_SPEC, ledger.CIO_SPEC])
def test_scheduled_role_uses_current_registered_binding_and_consumption_gate(monkeypatch, spec):
    policy, create, validate, consumed, send = setup_route(monkeypatch)
    result = call(spec)
    assert spec["model"] == deepseek_model_id(spec["policy"]) == "deepseek-flash"
    assert send.call_count == consumed.call_count == create.call_count == validate.call_count == 1
    kwargs = send.call_args.kwargs
    assert kwargs["process_id"] == spec["registered_process_id"]
    assert kwargs["model"] == "deepseek-flash" and kwargs["policy"] == spec["policy"]
    assert kwargs["metadata"]["thinking"] == resolve_logical_policy(spec["policy"])["thinking"]
    assert kwargs["metadata"]["fallback_used"] is False
    assert result["prov"]["thinking"] == resolve_logical_policy(spec["policy"])["thinking"]
    assert policy["operator_id"] == "fixture-operator"


@pytest.mark.parametrize("bad", [{"model": "deepseek-v4-pro"}, {"process_id": "unregistered"},
    {"policy": "FAST"}, {"agent_id": "unknown"}])
def test_route_mismatch_refuses_before_authorization_or_send(monkeypatch, bad):
    _, create, _, consumed, send = setup_route(monkeypatch)
    with pytest.raises(ValueError):
        call(ledger.CIO_SPEC, **bad)
    create.assert_not_called()
    consumed.assert_not_called()
    send.assert_not_called()


def test_missing_parent_policy_does_not_create_approval(monkeypatch):
    _, create, _, consumed, send = setup_route(monkeypatch)
    monkeypatch.setattr(ledger, "load_policy", lambda policy_id=None: None)
    with pytest.raises(PermissionError, match="policy_missing"):
        call(ledger.CIO_SPEC)
    create.assert_not_called()
    consumed.assert_not_called()
    send.assert_not_called()


def test_authorization_refusal_never_reaches_consumption_gate(monkeypatch):
    _, _, validate, consumed, send = setup_route(monkeypatch)
    validate.return_value = (False, "POLICY_MISMATCH", {})
    with pytest.raises(RuntimeError, match="auth_reject:POLICY_MISMATCH"):
        call(ledger.CIO_SPEC)
    send.assert_not_called()
    consumed.assert_not_called()


@pytest.mark.parametrize("provenance", [{"returned_model": "other", "request_id": "x"},
    {"returned_model": "deepseek-flash", "fallback_used": True, "request_id": "x"},
    {"returned_model": "deepseek-flash"}])
def test_invalid_response_never_consumes_authorization(monkeypatch, provenance):
    _, _, _, consumed, send = setup_route(monkeypatch)
    send.return_value = ("fixture", provenance)
    with pytest.raises(RuntimeError):
        call(ledger.CIO_SPEC)
    consumed.assert_not_called()


def test_legacy_parent_policy_does_not_silently_gain_new_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "_now", lambda: datetime(2026, 10, 24, tzinfo=timezone.utc))
    policy = ledger.build_intended_policy(operator_id="fixture")
    policy.update(allowed_models=["deepseek-v4-flash", "deepseek-v4-pro"], allowed_policies=["FAST", "PRO"])
    monkeypatch.setattr(ledger, "load_policy", lambda policy_id=None: policy)
    monkeypatch.setattr(ledger, "containment_required_ok", lambda: (True, "fixture"))
    write = Mock(side_effect=AssertionError("must refuse before write"))
    monkeypatch.setattr(ledger, "_atomic_write", write)
    with pytest.raises(PermissionError, match="MODEL_MISMATCH"):
        ledger.create_execution_authorization(policy_id="fixture", symbol="FIXTURE", agent_id="cio",
            input_snapshot_id="fixture", input_hash="hash", trigger_reason="fixture")
    write.assert_not_called()
    assert policy["allowed_policies"] == ["FAST", "PRO"]


def test_worker_dry_run_does_not_touch_cap_database_or_materialize_jobs(monkeypatch):
    monkeypatch.setattr(ledger, "load_policy", lambda: {"workers_enabled": True, "authorization_policy_id": "fixture"})
    monkeypatch.setattr(ledger, "validate_policy", lambda p: (True, "fixture"))
    monkeypatch.setattr(ledger, "containment_required_ok", lambda: (True, "fixture"))
    monkeypatch.setattr(pipeline, "schedule_times", lambda: {})
    plan = Mock(return_value={"jobs": []})
    monkeypatch.setattr(pipeline, "plan_jobs", plan)
    monkeypatch.setattr(workers, "_load_cards", lambda: [])
    cap = Mock(side_effect=AssertionError("dry-run cannot reach cap DB"))
    monkeypatch.setattr(canary, "ensure_cio_caps", cap)
    result = workers._execute_jobs(role="cio", dry_run=True)
    assert result["provider_calls"] == 0
    assert plan.call_count == 1 and plan.call_args.kwargs["dry_run"] is True
    cap.assert_not_called()
