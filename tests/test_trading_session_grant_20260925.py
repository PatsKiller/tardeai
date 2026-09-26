"""TradingSessionGrant@v1 — negative authority tests for the broker-boundary verifier.

Every refusal the governance amendment (AGENTS.md 1.3.0, PROPOSED) promises is proved
here: expired, revoked, wrong account, wrong symbol, over limit, altered envelope,
duplicate, alternate entry point, LLM origin, missing 2FA reference, unset operator
limit — plus the positive rule that protective management and exits of the session's
own positions survive a stopped session.

Pure: no broker, no network, no DB, no credential. The limit values below are test
fixtures, not operator risk limits.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.active_trader import session_control as SC  # noqa: E402
from scripts.lib import trading_session_grant as T  # noqa: E402

NOW = 10_000.0


def _draft(**over):
    d = {
        "strategy": "momentum_scalp",
        "setup_ids": ["ms_pullback"],
        "setup_versions": ["v3"],
        "registry_hash": "reg-test",
        "brokers": ["SIM_BROKER"],
        "account_ids": ["ACC-1"],
        "symbol_list_or_universe_rule": "symbols:AAA,BBB",
        "session_start": NOW - 60,
        "entry_cutoff": NOW + 3_600,
        "expiry": NOW + 7_200,
        "allowed_sessions": ["regular"],
        "max_trades": 3,
        "max_concurrent_positions": 2,
        "max_gross_notional": 20_000,
        "max_notional_per_trade": 10_000,
        "max_risk_per_trade": 200,
        "max_daily_loss": 500,
        "max_chase_bps": 10,
        "max_order_ttl_sec": 30,
        "allowed_order_types": ["limit"],
        "required_protection": ["stop"],
        "candidate_policy_version": "cand-v1",
        "risk_policy_version": "risk-v1",
        "operator_identity": "operator-test",
    }
    d.update(over)
    return d


def _grant(state=SC.ACTIVE, **over):
    env = SC.build_envelope(_draft(**over))
    return T.SessionGrant(
        session_id="at-sess-1",
        envelope=env,
        authorized_hash=env.authorization_hash,
        state=state,
        operator_identity=env.operator_identity,
        twofa_verification_ref="2fa-ceremony-ref-001",
    )


POSITIONS = {"pos-1": {"session_id": "at-sess-1", "symbol": "AAA", "account_id": "ACC-1", "qty": 100}}


def _usage(**over):
    base = dict(positions=POSITIONS)
    base.update(over)
    return T.SessionUsage(**base)


def _req(grant, **over):
    r = dict(
        request_id="req-1",
        mutation_class=T.ENTRY,
        entry_point="deterministic_execution_path",
        origin="deterministic",
        session_id=grant.session_id,
        authorization_hash=grant.authorized_hash,
        broker="SIM_BROKER",
        account_id="ACC-1",
        symbol="AAA",
        strategy="momentum_scalp",
        candidate_policy_version="cand-v1",
        risk_policy_version="risk-v1",
        order_type="limit",
        notional=5_000,
        risk=100,
        chase_bps=5,
        order_ttl_sec=20,
    )
    r.update(over)
    return T.MutationRequest(**r)


def _exit(grant, **over):
    base = dict(mutation_class=T.EXIT, position_id="pos-1", qty=100, notional=0, risk=0, order_type="limit")
    base.update(over)
    return _req(grant, **base)


# --- the baseline is allowed, so every refusal below is caused by one change ---------
def test_valid_entry_inside_envelope_is_allowed():
    g = _grant()
    d = T.verify_mutation(g, _req(g), _usage(), now=NOW)
    assert d.allowed and d.reason == T.ALLOW


# --- required refusals ---------------------------------------------------------------
def test_expired_session_refuses_entry():
    g = _grant(entry_cutoff=NOW - 10, expiry=NOW - 1)
    assert T.verify_mutation(g, _req(g), _usage(), now=NOW).reason == T.DENY_EXPIRED


def test_after_entry_cutoff_refuses_entry():
    g = _grant(entry_cutoff=NOW - 1)
    assert T.verify_mutation(g, _req(g), _usage(), now=NOW).reason == T.DENY_ENTRY_CUTOFF


def test_revoked_session_refuses_entry():
    g = dataclasses.replace(_grant(), state=SC.REVOKED, revoked_at=NOW - 5)
    assert T.verify_mutation(g, _req(g), _usage(), now=NOW).reason == T.DENY_REVOKED


def test_exit_only_kill_switch_refuses_entry():
    g = dataclasses.replace(_grant(), kill_switch_exit_only=True)
    assert T.verify_mutation(g, _req(g), _usage(), now=NOW).reason == T.DENY_REVOKED


def test_wrong_account_refused():
    g = _grant()
    d = T.verify_mutation(g, _req(g, account_id="ACC-OTHER"), _usage(), now=NOW)
    assert d.reason == T.DENY_WRONG_ACCOUNT


def test_wrong_broker_refused():
    g = _grant()
    d = T.verify_mutation(g, _req(g, broker="OTHER_BROKER"), _usage(), now=NOW)
    assert d.reason == T.DENY_WRONG_BROKER


def test_wrong_symbol_refused():
    g = _grant()
    assert T.verify_mutation(g, _req(g, symbol="ZZZ"), _usage(), now=NOW).reason == T.DENY_WRONG_SYMBOL


def test_universe_rule_requires_membership_proof():
    g = _grant(symbol_list_or_universe_rule="universe:premarket_movers")
    assert T.verify_mutation(g, _req(g), _usage(), now=NOW).reason == T.DENY_WRONG_SYMBOL
    ok = T.verify_mutation(g, _req(g, universe_membership_ref="univ-snap-1"), _usage(), now=NOW)
    assert ok.allowed


def test_over_limit_per_trade_notional():
    g = _grant()
    d = T.verify_mutation(g, _req(g, notional=10_001), _usage(), now=NOW)
    assert d.reason == T.DENY_OVER_LIMIT and d.detail == "max_notional_per_trade"


def test_over_limit_trade_count_and_daily_loss():
    g = _grant()
    assert T.verify_mutation(g, _req(g), _usage(trades_used=3), now=NOW).detail == "max_trades"
    assert T.verify_mutation(g, _req(g), _usage(realized_loss_today=500), now=NOW).detail == "max_daily_loss"
    assert T.verify_mutation(g, _req(g), _usage(gross_notional_open=16_000), now=NOW).detail == "max_gross_notional"


def test_altered_envelope_refused():
    g = _grant()
    tampered = dataclasses.replace(g.envelope, max_notional_per_trade=1_000_000)
    g2 = dataclasses.replace(g, envelope=tampered)
    assert T.verify_mutation(g2, _req(g2), _usage(), now=NOW).reason == T.DENY_ALTERED_ENVELOPE


def test_request_hash_mismatch_refused():
    g = _grant()
    d = T.verify_mutation(g, _req(g, authorization_hash="0" * 64), _usage(), now=NOW)
    assert d.reason == T.DENY_HASH_MISMATCH


def test_duplicate_request_refused():
    g = _grant()
    d = T.verify_mutation(g, _req(g), _usage(seen_request_ids=frozenset({"req-1"})), now=NOW)
    assert d.reason == T.DENY_DUPLICATE


def test_alternate_entry_point_refused():
    g = _grant()
    for ep in ("manual_cli", "api_v2_route", "telegram_command", "llm_tool_call", ""):
        d = T.verify_mutation(g, _req(g, entry_point=ep), _usage(), now=NOW)
        assert d.reason == T.DENY_ALTERNATE_ENTRY_POINT, ep


def test_llm_origin_refused_even_on_the_deterministic_path():
    g = _grant()
    d = T.verify_mutation(g, _req(g, origin="llm"), _usage(), now=NOW)
    assert d.reason == T.DENY_LLM_ORIGIN


def test_missing_2fa_reference_refused():
    g = dataclasses.replace(_grant(), twofa_verification_ref="")
    assert T.verify_mutation(g, _req(g), _usage(), now=NOW).reason == T.DENY_NO_2FA


def test_no_session_refused():
    g = _grant()
    assert T.verify_mutation(None, _req(g), _usage(), now=NOW).reason == T.DENY_NO_SESSION
    d = T.verify_mutation(g, _req(g, session_id=None), _usage(), now=NOW)
    assert d.reason == T.DENY_NO_SESSION


def test_unset_operator_limit_is_an_operator_decision_not_a_default():
    g = _grant(max_daily_loss=None)
    d = T.verify_mutation(g, _req(g), _usage(), now=NOW)
    assert d.reason == T.OPERATOR_DECISION_REQUIRED and "max_daily_loss" in d.detail


def test_order_type_outside_envelope_refused():
    g = _grant()
    assert T.verify_mutation(g, _req(g, order_type="market"), _usage(), now=NOW).reason == T.DENY_ORDER_TYPE


def test_policy_version_mismatch_refused():
    g = _grant()
    d = T.verify_mutation(g, _req(g, risk_policy_version="risk-v2"), _usage(), now=NOW)
    assert d.reason == T.DENY_POLICY_VERSION


# --- protection and exits survive a stopped session ------------------------------------
def test_exit_and_protection_allowed_after_cutoff_expiry_revocation_and_kill():
    stopped = [
        _grant(state=SC.ENTRY_CUTOFF, entry_cutoff=NOW - 1),
        _grant(state=SC.DRAINING, entry_cutoff=NOW - 20, expiry=NOW - 10),
        dataclasses.replace(_grant(), state=SC.REVOKED, revoked_at=NOW - 5),
        dataclasses.replace(_grant(), state=SC.KILLED, kill_switch_exit_only=True),
    ]
    for g in stopped:
        assert not T.verify_mutation(g, _req(g), _usage(), now=NOW).allowed, g.state
        assert T.verify_mutation(g, _exit(g), _usage(), now=NOW).allowed, g.state
        prot = _exit(g, mutation_class=T.PROTECTION, qty=0)
        assert T.verify_mutation(g, prot, _usage(), now=NOW).allowed, g.state
        cancel = _exit(g, mutation_class=T.CANCEL, qty=0)
        assert T.verify_mutation(g, cancel, _usage(), now=NOW).allowed, g.state


def test_exit_cannot_exceed_the_position_or_add_exposure():
    g = _grant(state=SC.ENTRY_CUTOFF, entry_cutoff=NOW - 1)
    assert T.verify_mutation(g, _exit(g, qty=101), _usage(), now=NOW).reason == T.DENY_EXPOSURE_INCREASE
    assert T.verify_mutation(g, _exit(g, notional=1), _usage(), now=NOW).reason == T.DENY_EXPOSURE_INCREASE


def test_exit_of_a_position_the_session_did_not_open_is_refused():
    g = _grant()
    foreign = {"pos-9": {"session_id": "other-session", "symbol": "AAA", "account_id": "ACC-1", "qty": 10}}
    d = T.verify_mutation(g, _exit(g, position_id="pos-9"), _usage(positions=foreign), now=NOW)
    assert d.reason == T.DENY_NOT_SESSION_POSITION


def test_altered_envelope_blocks_exits_too():
    """A tampered envelope proves nothing; exits fall back to normal per-order authority."""
    g = _grant(state=SC.ENTRY_CUTOFF, entry_cutoff=NOW - 1)
    g2 = dataclasses.replace(g, envelope=dataclasses.replace(g.envelope, account_ids=("ACC-1", "ACC-X")))
    assert T.verify_mutation(g2, _exit(g2), _usage(), now=NOW).reason == T.DENY_ALTERED_ENVELOPE


# --- the verifier stays a verifier -----------------------------------------------------
def test_module_imports_no_broker_adapter_and_makes_no_io():
    src = (ROOT / "scripts" / "lib" / "trading_session_grant.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    import_lines = [line for line in code.splitlines() if line.lstrip().startswith(("import ", "from "))]
    joined = "\n".join(import_lines)
    for forbidden in (
        "schwab_transport",
        "moomoo",
        "snaptrade",
        "broker_adapter",
        "requests",
        "urllib",
        "psycopg2",
        "socket",
        "subprocess",
        "bitwarden",
    ):
        assert forbidden not in joined, forbidden
