"""FQ-150 / D35: the ten B1–B10 producers, and the B4 link that has to work from a phone.

The B4 test is the one that matters: the operator must be able to re-authorise Schwab from the message itself, so the URL is
asserted to be https, on the tailnet host, on the real path, and free of the Development port — and the text is asserted NOT
to ask for a reply, because a reply-to-paste path puts a credential through a text message.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import critical_producers as P  # noqa: E402


def policy_yaml(tmp_path, url="https://cc-host.example.ts.net/v3/reports"):
    p = tmp_path / "operator_alert_policy.yaml"
    p.write_text(f'operator_alert_policy:\n  canonical_reports_url: "{url}"\n', encoding="utf-8")
    return p


def test_the_base_url_is_read_from_the_policy_and_is_https(tmp_path):
    base = P.command_center_base(path=policy_yaml(tmp_path))
    assert base == "https://cc-host.example.ts.net"


def test_the_dev_port_is_refused_rather_than_published(tmp_path):
    with pytest.raises(P.ProducerError) as exc:
        P.command_center_base(path=policy_yaml(tmp_path, "https://cc-host.example.ts.net:7777/v3/reports"))
    assert str(exc.value) == "command_center_on_dev_port"


def test_a_non_https_base_is_refused(tmp_path):
    with pytest.raises(P.ProducerError) as exc:
        P.command_center_base(path=policy_yaml(tmp_path, "http://cc-host.example.ts.net/v3/reports"))
    assert str(exc.value) == "command_center_not_https"


def test_the_reauth_link_is_full_https_path_and_no_dev_port(tmp_path):
    url = P.reauth_url(path=policy_yaml(tmp_path))
    assert url == "https://cc-host.example.ts.net/v3/system/schwab-reauth"
    assert url.startswith("https://") and url.endswith("/v3/system/schwab-reauth")
    assert ":7777" not in url


def test_b4_carries_the_link_in_its_text(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "reauth_url", lambda **k: "https://cc-host.example.ts.net/v3/system/schwab-reauth")
    event = P.produce("B4_schwab_login_expiring", {"symbol": "SCHW", "trigger": "Schwab refresh token expires in 2 days"})
    url = "https://cc-host.example.ts.net/v3/system/schwab-reauth"
    assert url in event["action"] and event["link"] == url
    assert event["alert_class"] == "B4_schwab_login_expiring"


def test_b4_never_asks_the_operator_to_reply_with_a_code(monkeypatch):
    """No text-reply paste path: re-authorisation happens behind the link, never in a text thread."""
    monkeypatch.setattr(P, "reauth_url", lambda **k: "https://cc-host.example.ts.net/v3/system/schwab-reauth")
    event = P.produce("B4_schwab_login_expiring", {"symbol": "SCHW", "trigger": "Schwab refresh token expires in 2 days"})
    body = f"{event['what']} {event['action']}".lower()
    for forbidden in ("reply", "text back", "paste", "send us", "code to", "respond with"):
        assert forbidden not in body, forbidden


def test_every_ten_class_has_a_producer():
    expected = {"A1_extended_hours_near_stop", "A2_stop_not_raised_after_move"} | {
        f"B{i}_{name}" for i, name in enumerate([
            "no_protective_stop_or_wrong_size", "stop_cancelled_expired_rejected", "stop_above_market_premarket",
            "schwab_login_expiring", "trading_halt", "options_expiry_or_assignment", "margin_or_cash",
            "order_rejected_or_partial", "monitoring_blind", "concentration_breach"], start=1)}
    assert set(P.PRODUCERS) == expected, set(P.PRODUCERS) ^ expected


def test_an_unknown_class_is_refused_rather_than_guessed():
    with pytest.raises(P.ProducerError) as exc:
        P.produce("Z9_not_a_class", {"trigger": "x"})
    assert str(exc.value) == "no_producer_for_class"


def test_a_producer_refuses_an_event_with_no_trigger_or_no_action():
    with pytest.raises(P.ProducerError) as exc:
        P.produce("B5_trading_halt", {"symbol": "ZZTEST"})
    assert str(exc.value) == "producer_needs_a_trigger"
    with pytest.raises(P.ProducerError) as exc:
        P.produce("B5_trading_halt", {"trigger": "halted", "suggested_action": ""})
    assert str(exc.value) == "producer_needs_an_action"


def test_dry_run_covers_every_enabled_class_with_fakes(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "reauth_url", lambda **k: "https://cc-host.example.ts.net/v3/system/schwab-reauth")
    monkeypatch.setenv("TRADEAI_CRITICAL_ALERT_CHAT_ID", "chat-fixture")
    classes = {k: {"enabled": True} for k in P.PRODUCERS}
    report = P.dry_run(policy={"classes": classes}, contact={
        "schema": "OperatorContact@v1", "critical_email_to": "operator@example.invalid",
        "critical_sms_email_gateways": [{"address": "gw@example.invalid", "verified": True}]})
    assert report["ok"] is True
    assert {r["alert_class"] for r in report["classes"]} == set(P.PRODUCERS)
    b4 = next(r for r in report["classes"] if r["alert_class"] == "B4_schwab_login_expiring")
    assert "/v3/system/schwab-reauth" in b4["action"]


def test_dry_run_reports_a_disabled_class_without_failing_the_run():
    """cc-deepseek F6: a class the operator turned OFF is a chosen configuration. A red light that always fires for it
    is how real failures get ignored, so the row says "disabled by configuration" and the run stays ok."""
    report = P.dry_run(policy={"classes": {"B5_trading_halt": {"enabled": False}}},
                       contact={"schema": "OperatorContact@v1"})
    assert report["ok"] is True
    assert report["classes"][0]["reason"] == "class_disabled_by_configuration"
    assert report["classes"][0]["disabled"] is True


ALLOWLIST = ROOT / "config" / "critical_text_classes.json"


@pytest.mark.skipif(not ALLOWLIST.is_file(), reason="the operator allowlist lands with the critical-text primitive; "
                                                   "until then there is nothing to check and nothing is enabled")
def test_the_repo_allowlist_enables_every_class_that_has_a_producer():
    """D35's acceptance line, held from this side: once the allowlist exists, a class with a producer must be ON.

    Skipping while the file is absent is honest — it is absent because the primitive is not merged yet, and a skip says so.
    The moment the file lands, a class accidentally left off fails here.
    """
    import json

    doc = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    classes = doc.get("classes") or {}
    missing = sorted(set(P.PRODUCERS) - set(classes))
    disabled = sorted(k for k in P.PRODUCERS if k in classes and (classes[k] or {}).get("enabled") is not True)
    assert not missing, f"producer with no allowlist entry: {missing}"
    assert not disabled, f"class present but not enabled: {disabled}"
