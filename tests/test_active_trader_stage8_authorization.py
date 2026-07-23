"""Stage 8 tests — session authorization + inactive action contracts (pure)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.contracts import ContractViolation, Environment  # noqa: E402
from active_trader.authorization import (  # noqa: E402
    ActionRequest, ActionResult, ActionType, AuthStatus, DESTRUCTIVE_ACTIONS,
    ProviderResult, SessionAuthorization, TestAuthorizationProvider,
    UnavailableProductionAuthorizationProvider, evaluate_action, issue_test_authorization,
    requires_reauthorization,
)

NOW = datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc)
ALL_ACTIONS = frozenset(ActionType)


def make_auth(**over):
    base = dict(
        draft_id="d1", draft_version=1, draft_hash="h1", operator_id="op",
        environment=Environment.SIMULATION,
        authorized_accounts=(("alpaca", "alpaca_paper", "PRIMARY"),),
        symbols=("TESTA",), quantity_envelope={"max_aggregate_shares": 100},
        risk_envelope={"max_risk": 100}, allowed_actions=ALL_ACTIONS, fallback_policy={},
        feature_policy_versions={}, now=NOW)
    base.update(over)
    return issue_test_authorization(**base)


# ---- providers
def test_test_provider_issues_bounded_session():
    auth = make_auth()
    assert auth.status is AuthStatus.AUTHORIZED and auth.environment is Environment.SIMULATION
    assert auth.expiry == NOW + timedelta(hours=4) and auth.provider == "test"


def test_production_provider_is_inactive():
    p = UnavailableProductionAuthorizationProvider()
    assert p.verify("h", "op") is ProviderResult.LIVE_INACTIVE
    with pytest.raises(ContractViolation, match="LIVE_INACTIVE"):
        make_auth(provider=p)


def test_rejected_test_verification_no_issue():
    with pytest.raises(ContractViolation):
        make_auth(provider=TestAuthorizationProvider(accept=False))


def test_live_environment_not_issued():
    with pytest.raises(ContractViolation, match="SHADOW/SIMULATION"):
        make_auth(environment=Environment.LIVE)


# ---- hash binding + envelope
def test_hash_binding():
    auth = make_auth()
    assert auth.binds("h1") and not auth.binds("h2")


def test_account_and_symbol_envelope():
    auth = make_auth()
    auth.check_account("alpaca", "alpaca_paper")
    with pytest.raises(ContractViolation):
        auth.check_account("schwab", "x")
    auth.check_symbol("TESTA")
    with pytest.raises(ContractViolation):
        auth.check_symbol("OTHER")
    uni = make_auth(symbols=("__UNIVERSE__", "rule-v1"))
    uni.check_symbol("ANYTHING")           # dynamic universe rule


def test_expiry_and_revocation():
    auth = make_auth()
    with pytest.raises(ContractViolation, match="expired"):
        auth.check_active(NOW + timedelta(hours=5))
    auth.status = AuthStatus.REVOKED
    auth.revoked_at = NOW
    with pytest.raises(ContractViolation, match="revoked"):
        auth.check_active(NOW)


def test_reauthorization_triggers():
    auth = make_auth()
    assert requires_reauthorization(auth, new_draft_hash="different")
    assert requires_reauthorization(auth, new_account=("schwab", "x", "FALLBACK"))
    assert requires_reauthorization(auth, larger_quantity=True)
    assert requires_reauthorization(auth, environment_change=True)
    assert not requires_reauthorization(auth, new_draft_hash="h1")


# ---- inactive actions
def req(action, **over):
    base = dict(action=action, authorization=make_auth(), broker="alpaca",
                account_label="alpaca_paper", symbol="TESTA", quantity=10, now=NOW)
    base.update(over)
    return ActionRequest(**base)


def test_every_action_validates_inactive_when_clean():
    for action in ActionType:
        r = req(action)
        # destructive actions need a confirmation token
        if action in DESTRUCTIVE_ACTIONS:
            r = req(action, confirmation_token=f"CONFIRM:{action.value}:{r.symbol or r.account_label}")
        out = evaluate_action(r)
        assert out.inactive is True
        assert out.result is ActionResult.VALIDATED_INACTIVE, f"{action}: {out.result} {out.reason}"
        assert out.intent_id and out.intent_id.startswith("lab-")
        assert out.journal_event == f"inactive_action:{action.value}"


def test_action_blocked_when_not_in_allowed_actions():
    auth = make_auth(allowed_actions=frozenset({ActionType.PRIME}))
    out = evaluate_action(req(ActionType.FIRE, authorization=auth))
    assert out.result is ActionResult.BLOCKED and out.inactive


def test_capability_and_data_and_risk_gates():
    assert evaluate_action(req(ActionType.SMART_ENTRY, capability_state="UNSUPPORTED")).result is ActionResult.UNSUPPORTED
    assert evaluate_action(req(ActionType.SMART_ENTRY, capability_state="UNKNOWN")).result is ActionResult.UNKNOWN_CAPABILITY
    assert evaluate_action(req(ActionType.SMART_ENTRY, data_state="STALE")).result is ActionResult.STALE_DATA
    assert evaluate_action(req(ActionType.SMART_ENTRY, data_state="GAP")).result is ActionResult.STALE_DATA
    assert evaluate_action(req(ActionType.SMART_ENTRY, risk_ok=False)).result is ActionResult.RISK_REJECTED


def test_unauthorized_account_symbol_requires_reauthorization():
    assert evaluate_action(req(ActionType.PRIME, account_label="other")).result is ActionResult.REAUTHORIZATION_REQUIRED
    assert evaluate_action(req(ActionType.PRIME, symbol="OTHER")).result is ActionResult.REAUTHORIZATION_REQUIRED


def test_destructive_requires_confirmation():
    for action in (ActionType.CANCEL_ALL_SYMBOL, ActionType.FLATTEN_ACCOUNT, ActionType.OVERNIGHT_CONVERT):
        no_token = evaluate_action(req(action))
        assert no_token.result is ActionResult.BLOCKED and "confirmation" in no_token.reason
        ref = req(action)
        token = f"CONFIRM:{action.value}:{ref.symbol or ref.account_label}"
        assert evaluate_action(req(action, confirmation_token=token)).result is ActionResult.VALIDATED_INACTIVE


def test_quantity_envelope_rejects_oversize():
    out = evaluate_action(req(ActionType.QUICK_ADD, quantity=500))  # cap 100
    assert out.result is ActionResult.RISK_REJECTED


def test_idempotent_intent_id():
    a = evaluate_action(req(ActionType.SMART_ENTRY, idempotency_key="k1"))
    b = evaluate_action(req(ActionType.SMART_ENTRY, idempotency_key="k1"))
    assert a.intent_id == b.intent_id


def test_nothing_executes():
    # every outcome is inactive; no field indicates execution
    for action in ActionType:
        r = req(action, confirmation_token=f"CONFIRM:{action.value}:TESTA"
                if action in DESTRUCTIVE_ACTIONS else None)
        out = evaluate_action(r)
        assert out.inactive is True
