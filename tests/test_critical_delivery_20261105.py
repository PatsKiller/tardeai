"""FQ-143 / D32 §6 + D33: the CRITICAL tier reaches three channels, and only CRITICAL reaches the text one.

HOUSE RULE E, in tests as in code: no address, no number appears here. Every fixture uses an obvious placeholder
(``gateway-one@example.invalid``), because the repository is public and the real addresses live only in the private
operator contact file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import critical_delivery as cd  # noqa: E402


def contact(**overrides):
    doc = {
        "schema": "OperatorContact@v1",
        "critical_email_to": "operator@example.invalid",
        "critical_sms_email_gateways": [
            {"address": "gateway-one@example.invalid", "label": "line one", "verified": True},
            {"address": "gateway-two@example.invalid", "label": "line two", "verified": True},
        ],
        "critical_sms_email_gateway": "gateway-one@example.invalid",
        "critical_sms_email_gateway_label": "line one",
    }
    doc.update(overrides)
    return doc


# ── the class guard, which is the whole point of HOUSE RULE E ────────────────────────────────────────────────

def policy(**classes):
    return {"schema": "CriticalTextClasses@v1", "classes": {k: {"enabled": v} for k, v in classes.items()}}


def test_only_enabled_classes_may_use_the_text_channel():
    p = policy(A1_extended_hours_near_stop=True, B2_stop_cancelled=False)
    cd.assert_text_allowed("A1_extended_hours_near_stop", p)  # must not raise
    with pytest.raises(cd.CriticalDeliveryRefused) as exc:
        cd.assert_text_allowed("B2_stop_cancelled", p)
    assert str(exc.value) == "text_channel_reserved_for_critical"
    for alert_class in ("digest", "status", "test", ""):
        with pytest.raises(cd.CriticalDeliveryRefused) as exc:
            cd.assert_text_allowed(alert_class, p)
        assert str(exc.value) == "not_a_critical_class", alert_class


def test_a_disabled_class_is_still_a_critical_class():
    """Turning a class off stops its texts and nothing else, so it stays in the taxonomy."""
    p = policy(B2_stop_cancelled=False)
    assert cd.is_critical_class("B2_stop_cancelled", p) is True
    assert cd.text_class_allowed("B2_stop_cancelled", p) is False


def test_an_absent_allowlist_refuses_rather_than_reading_open(tmp_path):
    with pytest.raises(cd.CriticalDeliveryRefused) as exc:
        cd.load_text_allowlist(tmp_path / "absent.json")
    assert str(exc.value) == "text_allowlist_missing"


def test_the_repo_allowlist_is_the_single_vocabulary(tmp_path):
    """No second class list in code: the module reads the operator's file, and keeps no copy that could drift from it.

    The operator's file (`config/critical_text_classes.json`) lands with the critical-text primitive. Until it is on main
    the loader must refuse, which is the safe direction: no allowlist means no text, never an open channel.
    """
    assert not hasattr(cd, "CRITICAL_CLASSES")
    fixture = tmp_path / "critical_text_classes.json"
    fixture.write_text(json.dumps({"schema": "CriticalTextClasses@v1", "classes": {"A1_x": {"enabled": True}}}))
    doc = cd.load_text_allowlist(fixture)
    assert list(doc["classes"]) == ["A1_x"]


def test_the_default_allowlist_path_is_the_repo_config_file():
    assert cd.ALLOWLIST_REL == ("config", "critical_text_classes.json")


def test_the_guard_has_no_override_argument():
    """A test contract, not a style note: an escape hatch here decides what interrupts the operator's phone."""
    import inspect

    params = inspect.signature(cd.assert_text_allowed).parameters
    assert list(params) == ["alert_class", "policy"], list(params)


# ── targets ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_gateway_address_is_a_target_and_a_test_target_is_carried_but_marked():
    targets = cd.text_targets(contact())
    assert [t.address for t in targets] == ["gateway-one@example.invalid", "gateway-two@example.invalid"]
    assert all(t.verified for t in targets)


def test_the_single_back_compat_key_still_counts():
    doc = contact()
    doc.pop("critical_sms_email_gateways")
    targets = cd.text_targets(doc)
    assert [t.address for t in targets] == ["gateway-one@example.invalid"]


def test_a_line_in_both_keys_is_not_sent_twice():
    doc = contact(critical_sms_email_gateways=[
        {"address": "only@example.invalid", "label": "line", "verified": True}], )
    doc["critical_sms_email_gateway"] = "only@example.invalid"
    assert len(cd.text_targets(doc)) == 1


def test_a_non_address_is_refused_rather_than_dialled():
    with pytest.raises(cd.CriticalDeliveryRefused) as exc:
        cd.text_targets(contact(critical_sms_email_gateways=[{"address": "555-0100"}]))
    assert str(exc.value) == "text_gateway_not_an_address"


def test_an_absent_email_is_refused_and_never_defaulted():
    with pytest.raises(cd.CriticalDeliveryRefused) as exc:
        cd.email_target(contact(critical_email_to=""))
    assert str(exc.value) == "critical_email_not_configured"


# ── the contact file ────────────────────────────────────────────────────────────────────────────────────────

def test_a_missing_contact_file_refuses_with_a_fixed_reason(tmp_path):
    with pytest.raises(cd.CriticalDeliveryRefused) as exc:
        cd.load_operator_contact(tmp_path / "absent.json")
    assert str(exc.value) == "operator_contact_missing"


def test_a_file_of_the_wrong_schema_refuses(tmp_path):
    p = tmp_path / "contact.json"
    p.write_text(json.dumps({"schema": "SomethingElse@v1"}))
    with pytest.raises(cd.CriticalDeliveryRefused) as exc:
        cd.load_operator_contact(p)
    assert str(exc.value) == "operator_contact_schema_invalid"


def test_the_path_is_the_private_persistent_state_file_not_the_repo(monkeypatch):
    """The repository is public. The contact file must never be read from inside it."""
    monkeypatch.delenv(cd.CONTACT_ENV, raising=False)
    path = cd.contact_path()
    assert path.name == "operator_contact.json"
    assert "persistent-state" in path.parts
    assert ROOT not in path.parents


# ── the message ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_subject_starts_with_the_prefix():
    assert cd.subject("after_hours_get_out", "NVDA through its stop").startswith("CRITICAL —")
    assert cd.subject("after_hours_get_out", "").startswith("CRITICAL —")


def test_the_text_leads_with_the_action_and_fits_three_hundred_characters():
    body = cd.text_body(what="NVDA through stop", price="$412.10", at="15:58 ET",
                        dollars_at_risk="$1,240", action="Consider EXT limit sell $410")
    assert len(body) <= cd.TEXT_MAX_CHARS
    assert body.index("Consider EXT limit sell") < body.index("$412.10"), body


def test_a_long_message_is_cut_at_a_word_boundary_not_mid_word():
    body = cd.text_body(what="x " * 400, action="act now")
    assert len(body) <= cd.TEXT_MAX_CHARS
    assert body.endswith("…")
    assert "  " not in body


# ── the fan-out plan ───────────────────────────────────────────────────────────────────────────────────────

def test_a_full_configuration_names_all_three_channels(monkeypatch):
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    plan = cd.fan_out_plan("B2_stop_cancelled_expired_rejected", contact(), policy(B2_stop_cancelled_expired_rejected=True))
    assert plan["channels"] == ["telegram_critical", "email", "text_gateway"]
    assert plan["missing"] == []


def test_a_missing_channel_is_reported_and_the_others_still_go(monkeypatch):
    monkeypatch.delenv(cd.CRITICAL_CHAT_ENV, raising=False)
    doc = contact()
    doc.pop("critical_email_to")
    plan = cd.fan_out_plan("B2_stop_cancelled_expired_rejected", doc, policy(B2_stop_cancelled_expired_rejected=True))
    assert plan["channels"] == ["telegram_critical", "email", "text_gateway"]  # the plan names the tier's channels
    assert set(plan["missing"]) == {"critical_chat_not_configured", "critical_email_not_configured"}
    assert plan["email_configured"] is False


def test_the_plan_refuses_a_non_critical_class_before_it_names_a_channel(monkeypatch):
    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    with pytest.raises(cd.CriticalDeliveryRefused):
        cd.fan_out_plan("digest", contact(), policy(B2_stop_cancelled_expired_rejected=True))


def test_the_plan_says_which_channels_it_will_actually_attempt(monkeypatch):
    """cc-deepseek-8 F4: `channels` is the tier's intent; `attempted` is what a dry run can trust."""
    monkeypatch.delenv(cd.CRITICAL_CHAT_ENV, raising=False)
    doc = contact()
    doc.pop("critical_email_to")
    plan = cd.fan_out_plan("B2_stop_cancelled_expired_rejected", doc, policy(B2_stop_cancelled_expired_rejected=True))
    assert plan["attempted"] == ["text_gateway"], plan["attempted"]
    assert plan["channels"] == ["telegram_critical", "email", "text_gateway"], "the intent list is unchanged"

    monkeypatch.setenv(cd.CRITICAL_CHAT_ENV, "chat-fixture")
    full = cd.fan_out_plan("B2_stop_cancelled_expired_rejected", contact(), policy(B2_stop_cancelled_expired_rejected=True))
    assert full["attempted"] == ["telegram_critical", "email", "text_gateway"], full["attempted"]

    off = cd.fan_out_plan("B2_stop_cancelled_expired_rejected", contact(), policy(B2_stop_cancelled_expired_rejected=False))
    assert "text_gateway" not in off["attempted"], "a class the allowlist does not enable is not attempted"
