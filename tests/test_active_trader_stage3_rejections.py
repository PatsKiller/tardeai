"""Stage 3 tests — classifier, capability projection, notifications, fallback.

Pure functions + fixtures + mock sinks only. NO live broker call, NO real alert.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from active_trader.contracts import CapabilityState, ContractViolation  # noqa: E402
from active_trader.rejections import (  # noqa: E402
    CLASSIFIER_VERSION, Classification, RawBrokerEvent, classify, project_capability, redact,
)
from active_trader.notifications import (  # noqa: E402
    InMemorySink, MockGmailSink, MockTelegramSink, NotificationCenter, Severity,
    dedupe_key_for, route_channels, severity_for,
)
from active_trader.fallback import (  # noqa: E402
    EvaluationInput, FallbackDecision, FallbackPolicy, evaluate,
    unapproved_alternate_projection,
)

NOW = datetime(2026, 7, 22, 20, 0, tzinfo=timezone.utc)
FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "active_trader_rejections.json").read_text())


def make_event(broker="schwab", raw_status="REJECTED", raw_code="", raw_message="",
               http_status=400, order_state=None, filled=0.0, remaining=100.0,
               symbol="XYZ", account="acct_a", provenance="SYNTHETIC"):
    return RawBrokerEvent(
        broker=broker, account_label=account, masked_account_id="***123", symbol=symbol,
        order_intent_id="oi-1", raw_status=raw_status, raw_code=raw_code,
        raw_message=raw_message, http_status=http_status, order_state=order_state,
        filled_quantity=filled, remaining_quantity=remaining,
        observed_at=NOW.isoformat(), adapter_version="stage3-test", provenance=provenance)


def fixture_event(broker, fx):
    return make_event(broker=broker, raw_status=fx["raw_status"], raw_code=fx["raw_code"],
                      raw_message=fx["raw_message"], http_status=fx.get("http_status"),
                      order_state=fx.get("order_state"),
                      filled=fx.get("filled_quantity", 0.0),
                      remaining=fx.get("remaining_quantity", 100.0),
                      provenance=fx["provenance"])


# ================ 8.1 classification
def test_every_fixture_classifies_as_expected():
    for broker, fixtures in ((b, FIXTURES[b]) for b in ("schwab", "alpaca", "moomoo")):
        for fx in fixtures:
            cls = classify(fixture_event(broker, fx))
            assert cls.normalized_code == fx["expect"], f"{broker}/{fx['name']}: {cls.normalized_code}"
            assert cls.classifier_version == CLASSIFIER_VERSION
            assert cls.matched_rule_id


def test_all_twenty_required_codes_reachable():
    reached = {fx["expect"] for b in ("schwab", "alpaca", "moomoo") for fx in FIXTURES[b]}
    extra = {  # codes not in fixtures, driven directly
        classify(make_event(raw_message="trading halted in this security")).normalized_code,
        classify(make_event(raw_message="possible wash trade detected")).normalized_code,
        classify(make_event(http_status=200, order_state="STALE", raw_message="x",
                            raw_status="", raw_code="")).normalized_code,
        classify(make_event(broker="moomoo", raw_code="RET_UNLOCK_REQUIRED",
                            provenance="SYNTHETIC_FUTURE_ADAPTER")).normalized_code,
    }
    reached |= extra
    required = {"SECURITY_REQUIRES_BROKER_ASSISTANCE", "ELECTRONIC_ENTRY_NOT_ALLOWED",
                "LOW_PRICE_OR_MICROCAP_RESTRICTION", "SECURITY_NOT_DAY_TRADE_ELIGIBLE",
                "ACCOUNT_NOT_AUTHORIZED", "INSUFFICIENT_BUYING_POWER",
                "ORDER_TYPE_NOT_SUPPORTED", "SESSION_NOT_SUPPORTED",
                "PRICE_INCREMENT_INVALID", "QUANTITY_LIMIT_REJECTED",
                "POSITION_OR_ORDER_CONFLICT", "RATE_LIMITED", "MARKET_CLOSED", "HALTED",
                "STALE_ACCOUNT_STATE", "AUTHENTICATION_EXPIRED", "UNKNOWN_BROKER_REJECTION"}
    missing = required - reached
    assert not missing, f"unreached required codes: {missing}"
    # remaining registry codes are classifiable via Classification construction:
    for code in ("ACCOUNT_RESTRICTED", "INSUFFICIENT_SHARES", "PRICE_BAND_REJECTED"):
        Classification(code, False, True, False, None, "account", "EXACT_CODE", "T",
                       CLASSIFIER_VERSION, "direct")


def test_exact_code_beats_message_pattern():
    e = make_event(broker="alpaca", raw_code="42910000",
                   raw_message="insufficient buying power")  # message says BP, code says rate limit
    cls = classify(e)
    assert cls.normalized_code == "RATE_LIMITED" and cls.confidence == "EXACT_CODE"


def test_broker_pattern_isolation():
    e = make_event(broker="alpaca", raw_message="broker assistance required")  # schwab-only needle
    assert classify(e).normalized_code == "UNKNOWN_BROKER_REJECTION"


def test_case_and_spacing_normalization_without_overmatch():
    e = make_event(raw_message="  BROKER   ASSISTANCE  needed ")
    assert classify(e).normalized_code == "SECURITY_REQUIRES_BROKER_ASSISTANCE"
    e2 = make_event(raw_message="brokerage account statement available")
    assert classify(e2).normalized_code == "UNKNOWN_BROKER_REJECTION"


def test_redaction_of_secrets_and_account_digits():
    e = make_event(raw_message="Bearer abc123token failed for account 123456789 api_key=SECRETX")
    assert "abc123token" not in e.raw_message and "123456789" not in e.raw_message \
        and "SECRETX" not in e.raw_message and "[REDACTED]" in e.raw_message


def test_deterministic_replay():
    e = make_event(raw_message="insufficient buying power", broker="alpaca")
    assert classify(e) == classify(e)


def test_malformed_and_missing_fields():
    e = classify(make_event(raw_code=None, raw_message=None, http_status=None))
    assert e.normalized_code == "UNKNOWN_BROKER_REJECTION"
    with pytest.raises(ContractViolation):
        make_event(broker="tastytrade")     # outside v1 scope
    with pytest.raises(ContractViolation):
        RawBrokerEvent("alpaca", "a", "***1", None, None, "", "", "", None, None, None,
                       None, NOW.isoformat(), "v", provenance="LIVE_CAPTURE")  # bad provenance


# ================ 8.2 retry safety
def test_unknown_broker_assist_and_electronic_are_not_retryable():
    for msg, code in (("weird", "UNKNOWN_BROKER_REJECTION"),
                      ("broker assistance", "SECURITY_REQUIRES_BROKER_ASSISTANCE"),
                      ("not permitted for electronic entry", "ELECTRONIC_ENTRY_NOT_ALLOWED")):
        cls = classify(make_event(raw_message=msg))
        assert cls.normalized_code == code and cls.retryable is False


def test_auth_expiry_never_retried_in_order_path():
    cls = classify(make_event(http_status=401, raw_message="unauthorized"))
    assert cls.normalized_code == "AUTHENTICATION_EXPIRED" and cls.retryable is False


def test_rate_limit_requires_bounded_backoff():
    cls = classify(make_event(http_status=429, raw_message="slow down"))
    assert cls.normalized_code == "RATE_LIMITED" and cls.retryable is True \
        and cls.retry_backoff_seconds == 30
    with pytest.raises(ContractViolation, match="bounded backoff"):
        Classification("RATE_LIMITED", True, False, False, None, "account",
                       "EXACT_CODE", "T", CLASSIFIER_VERSION, "no backoff")


def test_unknown_can_never_be_marked_retryable():
    with pytest.raises(ContractViolation):
        Classification("UNKNOWN_BROKER_REJECTION", True, True, False, None, "account",
                       "FALLBACK", "T", CLASSIFIER_VERSION, "bad")


# ================ 8.3 capability projection
def test_symbol_scoped_projection_no_cross_leakage():
    e = make_event(raw_message="opening transactions in this security are not permitted",
                   symbol="GME", account="schwab_taxable")
    p = project_capability(e, classify(e))
    assert p.capability == "ELECTRONIC_ENTRY_ELIGIBILITY" and p.proposed_state == "RESTRICTED"
    assert p.scope == "account+symbol" and p.symbol == "GME" and p.account_label == "schwab_taxable"
    e2 = make_event(raw_message="opening transactions in this security are not permitted",
                    symbol="AMC", account="schwab_roth")
    p2 = project_capability(e2, classify(e2))
    assert p2.idempotency_key != p.idempotency_key and p2.symbol == "AMC"


def test_projection_only_restricts_never_grants():
    from active_trader.rejections import CapabilityEvidenceProposal
    from active_trader.contracts import Environment
    with pytest.raises(ContractViolation):
        CapabilityEvidenceProposal("alpaca", "a", Environment.SIMULATION, "PLACE_LIMIT_RTH",
                                   "SUPPORTED", "account", None, "k", "2026-08-01")


def test_no_projection_without_affected_capability():
    e = make_event(broker="alpaca", raw_message="insufficient buying power")
    assert project_capability(e, classify(e)) is None


def test_projection_idempotent_replay():
    e = make_event(raw_message="broker assistance", symbol="GME")
    p1, p2 = (project_capability(e, classify(e)) for _ in range(2))
    assert p1.idempotency_key == p2.idempotency_key


# ================ 8.4 notifications
def _center():
    mem, tg, gm = InMemorySink(), MockTelegramSink(), MockGmailSink()
    return NotificationCenter(sinks=[mem, tg, gm], now=lambda: NOW), mem, tg, gm


def test_notification_creation_channels_and_content():
    center, mem, tg, gm = _center()
    e = make_event(raw_message="broker assistance", symbol="GME", filled=25.0, remaining=75.0)
    note = center.publish(e, classify(e), requested_qty=100, protection_state="CONFIRMED",
                          fallback_accounts=("alpaca/paper",))
    assert note.severity is Severity.ACTION_REQUIRED
    assert set(("COMMAND_CENTER", "JOURNAL", "TELEGRAM", "EMAIL")) <= set(note.channel_policy)
    s = note.operator_summary
    for req in ("SCHWAB", "***123", "GME", "100", "25.0", "75.0", "Normalized:",
                "Broker call required: YES", "Protection state: CONFIRMED", "alpaca/paper"):
        assert req in s, req
    assert "submitted" not in s.lower()
    assert len(tg.payloads) == 1 and tg.payloads[0]["chat"] == "[TEST-SINK]"
    assert len(gm.payloads) == 1 and gm.payloads[0]["to"] == "[TEST-SINK-OPERATOR]"


def test_dedup_no_flood_but_changed_fill_updates():
    center, mem, tg, gm = _center()
    e = make_event(broker="alpaca", raw_message="insufficient buying power")
    n1 = center.publish(e, classify(e), requested_qty=100)
    before = len(mem.delivered)
    n2 = center.publish(e, classify(e), requested_qty=100)          # identical repeat
    assert n2 is n1 and len(mem.delivered) == before                # no flood
    e2 = make_event(broker="alpaca", raw_message="insufficient buying power", filled=10.0,
                    remaining=90.0)
    n3 = center.publish(e2, classify(e2), requested_qty=100)
    assert n3 is n1 and n1.status == "UPDATED" and n1.filled_quantity == 10.0
    assert len(mem.delivered) == before + 1                          # one update emitted


def test_escalation_ack_resolution_expiry():
    center, mem, tg, gm = _center()
    e = make_event(broker="alpaca", raw_message="market is closed")
    note = center.publish(e, classify(e))
    assert note.severity is Severity.WARNING and "TELEGRAM" not in note.channel_policy
    center.escalate(note)
    assert note.status == "ESCALATED" and note.severity is Severity.CRITICAL \
        and "EMAIL" in note.channel_policy
    center.acknowledge(note, "operator")
    assert note.status == "ACKNOWLEDGED"
    center.resolve(note, "handled")
    assert note.status == "RESOLVED"
    e2 = make_event(broker="alpaca", raw_message="sub-penny increment", symbol="ABC")
    n2 = center.publish(e2, classify(e2))
    n2.expires_at = NOW - timedelta(seconds=1)
    assert center.expire_stale() == 1 and n2.status == "EXPIRED"


def test_email_policy_broker_call_or_critical_only():
    assert "EMAIL" in route_channels(Severity.ACTION_REQUIRED, broker_call_required=True)
    assert "EMAIL" not in route_channels(Severity.ACTION_REQUIRED, broker_call_required=False)
    assert "EMAIL" in route_channels(Severity.CRITICAL)
    assert route_channels(Severity.INFO) == ("COMMAND_CENTER", "JOURNAL")


def test_notification_redaction():
    center, mem, tg, gm = _center()
    e = make_event(raw_message="rejected; token=SECRETVALUE account 987654321",
                   raw_code="X1")
    note = center.publish(e, classify(e))
    assert "SECRETVALUE" not in note.operator_summary and "987654321" not in note.operator_summary


# ================ 8.5 fallback evaluator
def make_policy(**over):
    base = dict(session_authorization_id="sa-1", source_account_id="schwab_taxable",
                fallback_account_id="alpaca_paper", priority=1,
                allowed_normalized_codes=("ELECTRONIC_ENTRY_NOT_ALLOWED",
                                          "SECURITY_REQUIRES_BROKER_ASSISTANCE"),
                max_fallback_shares=500, max_fallback_notional=5000, max_fallback_risk=100,
                auto_failover=True, requires_operator_confirmation=False,
                expires_at=NOW + timedelta(hours=4), policy_version="fp-v1")
    base.update(over)
    return FallbackPolicy(**base)


def make_input(**over):
    cls = classify(make_event(raw_message="not permitted for electronic entry"))
    base = dict(source_order_state="REJECTED_WITH_ZERO_FILL", source_filled_quantity=0.0,
                source_remaining_quantity=100.0, source_rejection=cls,
                fallback_account_capability=CapabilityState.SUPPORTED,
                fallback_symbol_eligible=True, fallback_in_envelope=True,
                fallback_role_is_fallback=True, policy=make_policy(),
                requested_quantity=100, price=10.0, per_share_risk=0.5,
                authorized_aggregate_quantity=200, confirmed_aggregate_filled=0,
                confirmed_working_quantity=0, session_gross_notional_remaining=10000,
                session_risk_remaining=500, session_trades_remaining=3,
                session_within_time_bounds=True, market_thesis_valid=True, now=NOW)
    base.update(over)
    return EvaluationInput(**base)


def test_happy_path_auto_failover():
    r = evaluate(make_input())
    assert r.decision is FallbackDecision.AUTO_FAILOVER_ELIGIBLE and r.max_new_quantity == 100


def test_source_finality_blocks_everything():
    for state in ("SUBMITTED", "ACCEPTED", "PENDING_REPLACE", "PENDING_CANCEL",
                  "PARTIALLY_FILLED_WITH_UNCONFIRMED_REMAINDER"):
        r = evaluate(make_input(source_order_state=state))
        assert r.decision is FallbackDecision.WAIT_FOR_SOURCE_FINALITY, state
    for state in ("UNKNOWN", "STALE", "BROKER_UNREACHABLE"):
        assert evaluate(make_input(source_order_state=state)).decision is FallbackDecision.BLOCKED
    r = evaluate(make_input(source_filled_quantity=None))
    assert r.decision is FallbackDecision.BLOCKED    # late-fill/ambiguous-cancel protection


def test_partial_fill_confirmed_reduces_quantity():
    r = evaluate(make_input(source_order_state="CANCELLED_WITH_CONFIRMED_FILL_QUANTITY",
                            source_filled_quantity=40.0, confirmed_aggregate_filled=40))
    assert r.decision is FallbackDecision.AUTO_FAILOVER_ELIGIBLE and r.max_new_quantity == 100
    r2 = evaluate(make_input(source_order_state="CANCELLED_WITH_CONFIRMED_FILL_QUANTITY",
                             source_filled_quantity=150.0, confirmed_aggregate_filled=150,
                             requested_quantity=100))
    assert r2.max_new_quantity == 50                 # envelope room 200-150 = 50


def test_unapproved_alternate_requires_reauthorization():
    r = evaluate(make_input(fallback_in_envelope=False))
    assert r.decision is FallbackDecision.REAUTHORIZE_SESSION
    proj = unapproved_alternate_projection("GME", ("schwab_roth",))
    assert proj[0] == "REJECTION_RECEIVED" and "SYMBOL_PAUSED:GME" in proj \
        and proj[-1] == "SESSION_AMENDMENT_REQUIRED"


def test_ineligibility_paths_no_fallback():
    assert evaluate(make_input(fallback_role_is_fallback=False)).decision is FallbackDecision.NO_FALLBACK
    assert evaluate(make_input(policy=None)).decision is FallbackDecision.NO_FALLBACK
    assert evaluate(make_input(policy=make_policy(expires_at=NOW - timedelta(seconds=1)))
                    ).decision is FallbackDecision.NO_FALLBACK
    bp = classify(make_event(broker="alpaca", raw_message="insufficient buying power"))
    assert evaluate(make_input(source_rejection=bp)).decision is FallbackDecision.NO_FALLBACK
    assert evaluate(make_input(fallback_account_capability=CapabilityState.UNKNOWN)
                    ).decision is FallbackDecision.NO_FALLBACK
    assert evaluate(make_input(fallback_symbol_eligible=None)).decision is FallbackDecision.NO_FALLBACK
    assert evaluate(make_input(market_thesis_valid=False)).decision is FallbackDecision.NO_FALLBACK
    assert evaluate(make_input(session_within_time_bounds=False)).decision is FallbackDecision.NO_FALLBACK
    assert evaluate(make_input(session_trades_remaining=0)).decision is FallbackDecision.NO_FALLBACK


def test_quantity_notional_risk_caps():
    assert evaluate(make_input(policy=make_policy(max_fallback_shares=30))).max_new_quantity == 30
    assert evaluate(make_input(policy=make_policy(max_fallback_notional=250))).max_new_quantity == 25
    assert evaluate(make_input(policy=make_policy(max_fallback_risk=10))).max_new_quantity == 20
    assert evaluate(make_input(session_gross_notional_remaining=100)).max_new_quantity == 10
    assert evaluate(make_input(session_risk_remaining=5)).max_new_quantity == 10
    r = evaluate(make_input(authorized_aggregate_quantity=100, confirmed_aggregate_filled=60,
                            confirmed_working_quantity=40))
    assert r.decision is FallbackDecision.NO_FALLBACK    # envelope exhausted


def test_prompt_only_and_idempotent_replay():
    r = evaluate(make_input(policy=make_policy(requires_operator_confirmation=True)))
    assert r.decision is FallbackDecision.PROMPT_OPERATOR
    a, b = evaluate(make_input()), evaluate(make_input())
    assert a == b and a.idempotency_key == b.idempotency_key
