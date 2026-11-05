"""Incident/self-heal credit work: reserve attribution, per-process emergency cap, cheap-tier guard.

Operator 2026-11-02 (coordinator inbox 20261103T020403Z-OPERATOR-DECISION-emergency-fix-models.md):
reserve rows must name the process; the per-process cap may be raised for the incident/self-heal
process ONLY, on ``bulk`` (claude-haiku-5-5) or ``mid`` (claude-sonnet-5-5) ONLY, never Opus/Fable.
All state is a tmp_path fixture; no DB, network or credentials.
"""
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
import sys

import pytest

from scripts.lib.anthropic_credit import CreditBook, CreditDenied, caller_identity
from scripts.lib import anthropic_routing as routing


NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
HAIKU, SONNET, OPUS, FABLE = (
    "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1")
EMERGENCY = "incident_supervisor"
ORDINARY = "topic_ingestion"


def policy(**updates):
    base = {
        "enabled": True, "promotion_id": "fixture-promotion", "credit_usd": "200",
        "total_cap_usd": "190", "daily_cap_usd": "10",
        "starts_at": "2026-10-25T00:00:00Z", "expires_at": "2026-11-16T00:00:00Z",
        "per_call_caps_usd": {"bulk": "1.00", "mid": "1.00", "standard": "2.00", "high": "2.00",
                              "highest": "2.00", "long_form": "2.00", "premium": "4.00"},
        "models": {"bulk": HAIKU, "mid": SONNET, "standard": OPUS, "high": OPUS, "highest": OPUS,
                   "long_form": OPUS, "premium": FABLE},
        "emergency_process_caps": {"per_process": {EMERGENCY: {"bulk": "0.05", "mid": "0.05"}}},
    }
    return dict(base, **updates)


def reserve_row(book):
    return json.loads(book.path.read_text(encoding="utf-8").splitlines()[-1])


# ------------------------------------------------------------------ attribution

def test_reserve_row_names_the_caller_process_and_a_stable_process_name(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/opt/tradeai/scripts/incident_supervisor.py"])
    book = CreditBook(tmp_path, policy())
    book.reserve("r1", EMERGENCY, Decimal("0.01"), tier="bulk", now=NOW)
    row = reserve_row(book)
    assert row["event"] == "reserve"
    assert row["process"] == row["process_id"] == EMERGENCY
    assert row["process_name"] == "incident_supervisor.py"


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_process_id_is_a_loud_unknown_pid_sentinel_never_null(tmp_path, monkeypatch, missing):
    monkeypatch.setattr(os, "getpid", lambda: 4242)
    book = CreditBook(tmp_path, policy())
    book.reserve("missing", missing, Decimal("0.01"), tier="bulk", now=NOW)
    row = reserve_row(book)
    assert row["process"] == row["process_id"] == "unknown:4242"
    assert row["process"] is not None
    # The explicit sentinel keeps the verified journal readable and attributable.
    assert book.snapshot(now=NOW)["open_reservations"] == 1


def test_blank_or_non_string_process_id_uses_the_same_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 7)
    book = CreditBook(tmp_path, policy())
    for name in ("", 12345, object()):
        book.reserve(f"r-{name}", name, Decimal("0.01"), tier="bulk", now=NOW)
    assert [json.loads(line)["process"] for line in book.path.read_text().splitlines()] == [
        "unknown:7", "unknown:7", "unknown:7"]


def test_caller_identity_keeps_a_real_process_id_and_sanitizes_the_entrypoint(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/opt/tradeai/scripts/incident supervisor.py"])
    assert caller_identity(EMERGENCY) == (EMERGENCY, "incidentsupervisor.py")
    assert caller_identity(None)[0] == f"unknown:{os.getpid()}"


def test_cap_hit_fallback_row_names_the_process_that_was_refused(tmp_path):
    book = CreditBook(tmp_path, policy())
    with pytest.raises(CreditDenied, match="CREDIT_PROCESS_CAP"):
        book.reserve("a", ORDINARY, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.02"))
    book.record_fallback("CREDIT_PROCESS_CAP", now=NOW, process_id=ORDINARY)
    row = reserve_row(book)
    assert row["event"] == "fallback" and row["reason"] == "CREDIT_PROCESS_CAP"
    assert row["process"] == row["process_id"] == ORDINARY
    assert isinstance(row["process_name"], str) and row["process_name"]


def test_fallback_without_a_process_id_is_a_loud_sentinel_never_null(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 5150)
    book = CreditBook(tmp_path, policy())
    book.record_fallback("CREDIT_PROCESS_CAP", now=NOW)
    row = reserve_row(book)
    assert row["process"] == row["process_id"] == "unknown:5150"


def test_process_cap_counting_uses_the_same_normalized_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 99)
    book = CreditBook(tmp_path, policy())
    book.reserve("one", None, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.05"))
    with pytest.raises(CreditDenied, match="CREDIT_PROCESS_CAP"):
        book.reserve("two", None, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.05"))


# ------------------------------------------------------- per-process cap override

def test_emergency_process_uses_the_raised_cap_on_a_cheap_tier(tmp_path):
    book = CreditBook(tmp_path, policy())
    book.reserve("a", EMERGENCY, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.02"))
    assert book.snapshot(now=NOW)["reserved_usd"] == "0.03"
    with pytest.raises(CreditDenied, match="CREDIT_PROCESS_CAP"):
        book.reserve("b", EMERGENCY, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.02"))


def test_ordinary_process_still_hits_the_old_registry_cap(tmp_path):
    book = CreditBook(tmp_path, policy())
    with pytest.raises(CreditDenied, match="CREDIT_PROCESS_CAP"):
        book.reserve("a", ORDINARY, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.02"))


def test_config_without_an_override_behaves_as_today(tmp_path):
    p = policy()
    del p["emergency_process_caps"]
    book = CreditBook(tmp_path, p)
    with pytest.raises(CreditDenied, match="CREDIT_PROCESS_CAP"):
        book.reserve("a", EMERGENCY, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.02"))


def test_override_is_tier_scoped_and_never_raises_a_premium_tier(tmp_path):
    p = policy(emergency_process_caps={"per_process": {EMERGENCY: {"bulk": "0.05"}}})
    book = CreditBook(tmp_path, p)
    with pytest.raises(CreditDenied, match="CREDIT_PROCESS_CAP"):
        book.reserve("a", ORDINARY, Decimal("0.03"), tier="standard", now=NOW, process_cap=Decimal("0.02"))


def test_emergency_process_cannot_reserve_a_premium_tier_at_the_ledger(tmp_path):
    book = CreditBook(tmp_path, policy())
    for tier in ("standard", "high", "highest", "long_form", "premium"):
        with pytest.raises(CreditDenied, match="EMERGENCY_TIER_REFUSED"):
            book.reserve(f"tier-{tier}", EMERGENCY, Decimal("0.01"), tier=tier, now=NOW,
                         process_cap=Decimal("1.00"))
    # An ordinary process keeps its existing tier authority.
    book.reserve("ordinary-standard", ORDINARY, Decimal("0.01"), tier="standard", now=NOW,
                 process_cap=Decimal("1.00"))


def test_override_raises_and_never_lowers_a_higher_registry_cap(tmp_path):
    book = CreditBook(tmp_path, policy())
    book.reserve("a", EMERGENCY, Decimal("0.08"), tier="bulk", now=NOW, process_cap=Decimal("0.10"))
    with pytest.raises(CreditDenied, match="CREDIT_PROCESS_CAP"):
        book.reserve("b", EMERGENCY, Decimal("0.03"), tier="bulk", now=NOW, process_cap=Decimal("0.10"))


@pytest.mark.parametrize("block", [
    [],
    "not-a-dict",
    {"per_process": []},
    {"per_process": {EMERGENCY: []}},
    {"per_process": {EMERGENCY: {}}},
    {"per_process": {"": {"bulk": "1.00"}}},
    {"per_process": {EMERGENCY: {"standard": "5.00"}}},
    {"per_process": {EMERGENCY: {"high": "5.00"}}},
    {"per_process": {EMERGENCY: {"highest": "5.00"}}},
    {"per_process": {EMERGENCY: {"long_form": "5.00"}}},
    {"per_process": {EMERGENCY: {"premium": "5.00"}}},
    {"per_process": {EMERGENCY: {"bulk": "0"}}},
    {"per_process": {EMERGENCY: {"bulk": "NaN"}}},
])
def test_invalid_or_non_cheap_override_refuses_the_policy(tmp_path, block):
    with pytest.raises(CreditDenied, match="CREDIT_CONFIGURATION_INVALID"):
        CreditBook(tmp_path, policy(emergency_process_caps=block))


def test_a_cheap_tier_remapped_to_opus_or_fable_is_refused(tmp_path):
    models = dict(policy()["models"], bulk=OPUS)
    with pytest.raises(CreditDenied, match="CREDIT_CONFIGURATION_INVALID"):
        CreditBook(tmp_path, policy(models=models))


# ------------------------------------------------------------- cheap-tier guard

@pytest.mark.parametrize("value", ["bulk", HAIKU, "mid", SONNET])
def test_guard_allows_bulk_and_mid_by_alias_and_model_name(value):
    assert routing.emergency_tier_allowed(value, policy=policy())


@pytest.mark.parametrize("value", [
    "standard", "high", "highest", "long_form", "premium",
    OPUS, FABLE,
])
def test_guard_refuses_opus_and_fable_by_alias_and_by_name(value):
    assert not routing.emergency_tier_allowed(value, policy=policy())
    with pytest.raises(routing.EmergencyTierRefused) as error:
        routing.require_emergency_tier(value, policy=policy())
    assert error.value.reason == "EMERGENCY_TIER_REFUSED"


@pytest.mark.parametrize("value", ["unknown-tier", "", None, "claude-unknown-9"])
def test_guard_refuses_an_unrecognized_tier(value):
    assert not routing.emergency_tier_allowed(value, policy=policy())
    with pytest.raises(routing.EmergencyTierRefused):
        routing.require_emergency_tier(value, policy=policy())


def test_guard_returns_the_configured_cheap_model_id():
    p = policy()
    assert routing.require_emergency_tier("bulk", policy=p) == HAIKU
    assert routing.require_emergency_tier("mid", policy=p) == SONNET
    assert routing.require_emergency_tier(HAIKU, policy=p) == HAIKU


def test_guard_refuses_a_cheap_alias_remapped_to_a_premium_model():
    p = policy(models={"bulk": OPUS, "mid": SONNET, "standard": OPUS, "premium": FABLE})
    assert not routing.emergency_tier_allowed("bulk", policy=p)


def test_emergency_process_list_is_config_driven():
    assert routing.emergency_processes(policy=policy()) == frozenset({EMERGENCY})
    assert routing.is_emergency_process(EMERGENCY, policy=policy())
    assert not routing.is_emergency_process(ORDINARY, policy=policy())


def test_shipping_config_allows_bulk_and_mid_and_refuses_every_premium_alias():
    shipping = json.loads(
        (routing.ROOT / "config/anthropic_credit_policy.json").read_text(encoding="utf-8"))
    assert routing.emergency_tier_allowed("bulk", policy=shipping)
    assert routing.emergency_tier_allowed("mid", policy=shipping)
    for tier in ("standard", "high", "highest", "long_form", "premium"):
        assert not routing.emergency_tier_allowed(tier, policy=shipping)
    assert routing.emergency_processes(policy=shipping) == frozenset({EMERGENCY})
