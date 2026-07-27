"""Stage 1 contract tests — pure, no DB, no network, no broker.

Run: .venv/bin/python -m pytest tests/test_active_trader_stage1_contracts.py -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.contracts import (  # noqa: E402
    ALLOWED_BROKERS, AuthorizationStatus, BrokerCapability, CapabilityState,
    CheckpointState, ContractViolation, DriveManifestEntry, Environment,
    FeatureFlag, FlagMode, FLAG_REGISTRY, LitmusReport, NormalizedRejection,
    OrderIntent, RateBudget, RatePolicy, RunCheckpoint, SessionAccount,
    SessionAuthorization, SessionDraft, authorize_order, flag_default,
    reject_sentinel,
)

NOW = datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc)


def make_draft(version=1, env=Environment.LIVE, name="canary"):
    return SessionDraft(
        draft_id="d-1", draft_version=version, environment=env, session_name=name,
        broker_set=("alpaca",), account_policy={"alpaca/paper": {"role": "PRIMARY"}},
        symbol_policy={"symbols": ["GRAB"]},
        risk_limits={"max_trades": 3, "max_concurrent_positions": 1,
                     "max_gross_notional": 100, "max_risk_per_trade": 10, "max_daily_loss": 20},
        time_bounds={"start": "09:30"}, runner_policy={"enabled": False},
        feature_policy_versions={"candidate_rule": "v1"}, created_by="operator",
    )


def make_auth(draft=None, status=AuthorizationStatus.AUTHORIZED, expiry_h=4, revoked=False,
              accounts=None):
    draft = draft or make_draft()
    acct = accounts if accounts is not None else (
        SessionAccount("alpaca", "paper", Environment.parse(draft.environment), "PRIMARY",
                       max_shares=100, max_notional=1000),)
    auth = SessionAuthorization.__new__(SessionAuthorization)
    start, cutoff, exp = NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=expiry_h)
    object.__setattr__(auth, "session_authorization_id", "sa-1")
    object.__setattr__(auth, "draft", draft)
    object.__setattr__(auth, "operator_id", "operator")
    object.__setattr__(auth, "status", status)
    object.__setattr__(auth, "session_start", start)
    object.__setattr__(auth, "session_entry_cutoff", cutoff)
    object.__setattr__(auth, "session_expiry", exp)
    object.__setattr__(auth, "accounts", acct)
    object.__setattr__(auth, "revoked_at", NOW if revoked else None)
    object.__setattr__(auth, "authorization_hash", auth.expected_hash())
    auth.__post_init__()
    return auth


# ---------------- environment: explicit, no default, unambiguous
def test_environment_has_no_default():
    for bad in (None, "", "  "):
        with pytest.raises(ContractViolation):
            Environment.parse(bad)


def test_environment_unknown_rejected():
    with pytest.raises(ContractViolation):
        Environment.parse("PROD")


# ---------------- session authorization invariants
def test_authorized_draft_is_immutable():
    draft = make_draft()
    with pytest.raises(Exception):  # frozen dataclass
        draft.session_name = "changed"


def test_changed_draft_hash_cannot_reuse_authorization():
    auth = make_auth()
    tampered = make_draft(name="TAMPERED")
    with pytest.raises(ContractViolation, match="hash"):
        SessionAuthorization(
            session_authorization_id="sa-2", draft=tampered,
            authorization_hash=auth.authorization_hash, operator_id="operator",
            status=AuthorizationStatus.AUTHORIZED, session_start=auth.session_start,
            session_entry_cutoff=auth.session_entry_cutoff, session_expiry=auth.session_expiry,
            accounts=auth.accounts)


def test_new_draft_version_changes_hash():
    assert make_draft(version=1).hash != make_draft(version=2).hash


def make_intent(env, auth=None, broker="alpaca", account="paper", qty=10, key="k-1"):
    return OrderIntent(
        order_intent_id="oi-1", environment=env, broker=broker, account_label=account,
        symbol="GRAB", side="BUY", quantity=qty, order_type="LIMIT", time_in_force="DAY",
        trading_session="RTH", idempotency_key=key, session_authorization=auth, now=NOW)


def test_live_intent_without_authorization_rejected():
    with pytest.raises(ContractViolation, match="session authorization"):
        make_intent(Environment.LIVE)


def test_live_intent_unauthorized_account_rejected():
    auth = make_auth()
    with pytest.raises(ContractViolation, match="not authorized"):
        make_intent(Environment.LIVE, auth, account="other-account")


def test_out_of_envelope_quantity_rejected():
    auth = make_auth()
    with pytest.raises(ContractViolation, match="envelope"):
        auth.check_quantity("alpaca", "paper", shares=101, notional=10)


def test_expired_authorization_rejected():
    auth = make_auth()
    with pytest.raises(ContractViolation, match="expired"):
        auth.check_valid(NOW + timedelta(hours=5))


def test_revoked_authorization_rejected():
    auth = make_auth(status=AuthorizationStatus.REVOKED, revoked=True)
    with pytest.raises(ContractViolation, match="revoked"):
        auth.check_valid(NOW)


# ---------------- environment discipline on intents
def test_shadow_cannot_carry_broker_write_authorization():
    auth = make_auth(draft=make_draft(env=Environment.SHADOW),
                     accounts=(SessionAccount("alpaca", "paper", Environment.SHADOW, "PRIMARY"),))
    with pytest.raises(ContractViolation, match="SHADOW"):
        make_intent(Environment.SHADOW, auth)


def test_simulation_and_live_are_unambiguous():
    sim = make_intent(Environment.SIMULATION, key="k-sim")
    assert Environment.parse(sim.environment) is Environment.SIMULATION
    with pytest.raises(ContractViolation):
        make_intent("", key="k-none")


# ---------------- feature flags
def test_all_production_defaults_off():
    assert all(flag_default("production", n) is FlagMode.OFF for n in FLAG_REGISTRY)
    assert all(flag_default("test", n) is FlagMode.OFF for n in FLAG_REGISTRY)


def test_development_visible_flag_read_only_everything_else_off():
    assert flag_default("development", "active_trader_next_visible") is FlagMode.READ_ONLY
    others = [n for n in FLAG_REGISTRY if n != "active_trader_next_visible"]
    assert all(flag_default("development", n) is FlagMode.OFF for n in others)


def test_flags_alone_cannot_authorize_trading():
    flags = {name: FlagMode.LIVE_CANARY for name in FLAG_REGISTRY}
    with pytest.raises(ContractViolation, match="no flag can substitute"):
        authorize_order(_live_intent_no_auth(), flags, NOW)


def _live_intent_no_auth():
    """Bypass constructor validation to prove the gate itself also rejects."""
    intent = OrderIntent.__new__(OrderIntent)
    object.__setattr__(intent, "environment", Environment.LIVE)
    object.__setattr__(intent, "broker", "alpaca")
    object.__setattr__(intent, "account_label", "paper")
    object.__setattr__(intent, "session_authorization", None)
    object.__setattr__(intent, "quantity", 1)
    return intent


def test_flag_off_blocks_but_flag_on_does_not_grant():
    sim = make_intent(Environment.SIMULATION, key="k-block")
    with pytest.raises(ContractViolation, match="OFF"):
        authorize_order(sim, {"broker_alpaca": FlagMode.OFF}, NOW)
    authorize_order(sim, {"broker_alpaca": FlagMode.SIMULATION}, NOW)  # restricts only


def test_invalid_flag_modes_and_names_fail():
    with pytest.raises(ContractViolation):
        FeatureFlag("not_a_flag", FlagMode.OFF, 1, "r", "op")
    with pytest.raises(ContractViolation):
        FeatureFlag("quick_add", "ON", 1, "r", "op")  # type: ignore[arg-type]


def test_flag_expiry_returns_off():
    f = FeatureFlag("quick_add", FlagMode.SHADOW, 1, "test", "op", expires_at=NOW)
    assert f.effective_mode(NOW + timedelta(seconds=1)) is FlagMode.OFF
    assert f.effective_mode(NOW - timedelta(seconds=1)) is FlagMode.SHADOW


# ---------------- broker capability + rejection contracts
def test_unsupported_and_unknown_remain_explicit():
    cap_u = BrokerCapability("schwab", "acct", Environment.LIVE, "NATIVE_CLOSE_ALL",
                             CapabilityState.UNSUPPORTED, "RUNTIME_PROBE", verified_at=NOW)
    cap_k = BrokerCapability("schwab", "acct", Environment.LIVE, "BRACKET_ORDER",
                             CapabilityState.UNKNOWN, "DOCUMENTATION")
    assert cap_u.effective_state(NOW) is CapabilityState.UNSUPPORTED
    assert cap_k.effective_state(NOW) is CapabilityState.UNKNOWN


def test_stale_evidence_cannot_stay_supported():
    cap = BrokerCapability("alpaca", "paper", Environment.SIMULATION, "PLACE_LIMIT_RTH",
                           CapabilityState.SUPPORTED, "RUNTIME_PROBE",
                           verified_at=NOW, expires_at=NOW + timedelta(days=1))
    assert cap.effective_state(NOW) is CapabilityState.SUPPORTED
    assert cap.effective_state(NOW + timedelta(days=2)) is CapabilityState.UNKNOWN


def test_supported_without_evidence_rejected():
    with pytest.raises(ContractViolation, match="evidence"):
        BrokerCapability("alpaca", "paper", Environment.SIMULATION, "PLACE_LIMIT_RTH",
                         CapabilityState.SUPPORTED, "DOCUMENTATION")


def test_unknown_rejection_non_retryable_by_default():
    r = NormalizedRejection("schwab", "acct", Environment.LIVE, "X999", "weird broker text")
    assert r.normalized_code == "UNKNOWN_BROKER_REJECTION"
    assert r.retryable is False and r.requires_operator is True


def test_broker_assistance_rejection_requires_operator():
    r = NormalizedRejection("schwab", "acct", Environment.LIVE, "RJX", "call the trade desk",
                            normalized_code="SECURITY_REQUIRES_BROKER_ASSISTANCE")
    assert r.requires_broker_call is True and r.requires_operator is True and r.retryable is False


# ---------------- rate policy (owner-approved values)
def test_approved_moomoo_policy_values():
    p = RatePolicy.approved_moomoo("moomoo/acct1")
    assert (p.place.provider_ceiling, p.place.ordinary_budget, p.place.reserve_budget) == (15, 12, 3)
    assert (p.modify_cancel.provider_ceiling, p.modify_cancel.ordinary_budget,
            p.modify_cancel.reserve_budget) == (20, 16, 4)
    assert p.place.window_seconds == p.modify_cancel.window_seconds == 30


def test_place_and_modify_ceilings_independent():
    with pytest.raises(ContractViolation):
        RateBudget("SHARED", 20, 16, 4, 30, "a")           # shared budget class refused
    with pytest.raises(ContractViolation):
        RateBudget("PLACE", 15, 13, 3, 30, "a")            # 13+3 > 15
    with pytest.raises(ContractViolation):
        RateBudget("PLACE", 15, 12, 3, 0, "a")             # non-positive window
    with pytest.raises(ContractViolation):
        RateBudget("PLACE", 15, 12, 3, 30, "  ")           # missing account scope


def test_ordinary_traffic_cannot_consume_reserve():
    p = RatePolicy.approved_moomoo("moomoo/acct1")
    with pytest.raises(ContractViolation, match="reserve is protection-only"):
        p.consume("PLACE", used_ordinary=12, is_protection=False)
    p.consume("PLACE", used_ordinary=12, is_protection=True)   # reserve OK for protection
    with pytest.raises(ContractViolation, match="ceiling"):
        p.consume("PLACE", used_ordinary=15, is_protection=True)  # ceiling absolute


# ---------------- checkpoint
def make_cp(state=CheckpointState.RUNNING):
    return RunCheckpoint("20260722-01", "v3.3", "v1.1", "87c2fa09", "feat/active-trader-next",
                         1, state)


def test_checkpoint_optimistic_conflict():
    cp = make_cp()
    cp.update(expected_version=1, test_summary="a")
    with pytest.raises(ContractViolation, match="optimistic"):
        cp.update(expected_version=1, test_summary="b")


def test_checkpoint_idempotent_update():
    cp = make_cp()
    cp.update(expected_version=1, test_summary="same")
    cp.update(expected_version=2, test_summary="same")
    assert cp.test_summary == "same" and cp.version == 3


def test_failed_checkpoint_cannot_advance():
    cp = make_cp(CheckpointState.FAILED)
    with pytest.raises(ContractViolation, match="resume"):
        cp.update(expected_version=1, state=CheckpointState.GREEN_CLOSED)
    with pytest.raises(ContractViolation, match="resume=True"):
        cp.update(expected_version=1, state=CheckpointState.RUNNING)
    cp.update(expected_version=1, state=CheckpointState.RUNNING, resume=True)
    assert cp.state is CheckpointState.RUNNING


def test_green_closed_requires_verified_drive_artifacts():
    cp = make_cp()
    with pytest.raises(ContractViolation, match="verified"):
        cp.update(expected_version=1, state=CheckpointState.GREEN_CLOSED,
                  drive_artifacts=[{"name": "x", "verified": False}])
    cp2 = make_cp()
    cp2.update(expected_version=1, state=CheckpointState.GREEN_CLOSED,
               drive_artifacts=[{"name": "x", "verified": True}])
    assert cp2.state is CheckpointState.GREEN_CLOSED


# ---------------- drive manifest
def test_drive_manifest_verified_requires_upload_and_id():
    with pytest.raises(ContractViolation):
        DriveManifestEntry("a", "b", "c", "0" * 64, upload_state="PENDING", verified=True)
    ok = DriveManifestEntry("a", "b", "c", "0" * 64, upload_state="UPLOADED",
                            drive_file_id="f1", verified=True)
    assert ok.verified


# ---------------- litmus schema
def _litmus(**over):
    base = dict(review_id="r1", architecture_version="v3.3", implementation_sha="x",
                reviewer="arch", access_mode_verified="READ_ONLY", write_attempted=False,
                verdict="PASS", blocking_findings=(), nonblocking_findings=(), questions=(),
                evidence_refs=(), recommended_operator_checks=(), review_hash="h",
                completed_at="2026-07-22")
    base.update(over)
    return LitmusReport(**base)


def test_litmus_verdicts_and_boundaries():
    for v in ("PASS", "CONDITIONAL_PASS", "FAIL"):
        assert _litmus(verdict=v).verdict == v
    with pytest.raises(ContractViolation):
        _litmus(verdict="MAYBE")
    with pytest.raises(ContractViolation):
        _litmus(access_mode_verified="READ_WRITE")
    with pytest.raises(ContractViolation):
        _litmus(write_attempted=True)


# ---------------- secrets
def test_sentinel_values_rejected():
    for bad in ("UNSET__OPERATOR_REQUIRED", "", "  ", None):
        with pytest.raises(ContractViolation):
            reject_sentinel(bad, "ACTIVE_TRADER_TEST_DATABASE_DSN")
    assert reject_sentinel("postgresql://x", "dsn") == "postgresql://x"


def test_v1_broker_scope_is_closed():
    assert ALLOWED_BROKERS == ("alpaca", "moomoo", "schwab")
    with pytest.raises(ContractViolation):
        SessionAccount("tastytrade", "x", Environment.SIMULATION, "PRIMARY")
