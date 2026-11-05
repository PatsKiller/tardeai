"""SPEC_CRITICAL_TEXT_ACTION_ALERTS_20261104 — the critical-text channel, dry-run only.

Every address here is fake and every send is a recording stub: this file proves the channel's rules without
texting anyone. The one real send lives in the daily 09:00 test, not here.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import critical_texts as ct  # noqa: E402

FAKE_LINES = ["15550000001@example.invalid", "15550000002@example.invalid"]
NOW = datetime(2026, 11, 4, 17, 30, tzinfo=timezone.utc)


@pytest.fixture()
def paths(tmp_path):
    contact = tmp_path / "operator_contact.json"
    contact.write_text(json.dumps({"critical_sms_email_gateways": FAKE_LINES}), encoding="utf-8")
    config = tmp_path / "critical_text_classes.json"
    config.write_text(json.dumps({
        "schema": "CriticalTextClasses@v1", "max_per_hour": 2, "dedupe_hours": 12,
        "classes": {
            "A1_extended_hours_near_stop": {"enabled": True},
            "A2_stop_not_raised_after_move": {"enabled": True},
            "B7_margin_or_cash": {"enabled": False},
        },
    }), encoding="utf-8")
    return contact, config, tmp_path / "state.json"


def event(**over):
    base = {
        "alert_class": "A1_extended_hours_near_stop",
        "event_id": "SPCX:A1:2026-11-04T17:30",
        "symbol": "SPCX", "account": "Roth",
        "trigger": "ext-hrs 131.20, stop 130.00 inactive till 9:30",
        "action": "EXT limit sell 130.90",
    }
    base.update(over)
    return base


def recorder():
    calls = []

    def send(subject, body, to=None, attachments=None):
        calls.append({"subject": subject, "body": body, "to": to})
        return True

    return send, calls


def test_one_event_texts_every_fi_line(paths):
    contact, config, state = paths
    send, calls = recorder()
    result = ct.send_critical_text(event(), sender=send, contact_path=contact, config_path=config,
                                   state_path=state, now=NOW)
    assert result["sent"] is True
    assert [c["to"] for c in calls] == FAKE_LINES          # both lines, once each
    assert result["gateways"] == 2


def test_the_text_is_the_specified_sentence_and_fits_a_text(paths):
    contact, config, state = paths
    send, calls = recorder()
    ct.send_critical_text(event(), sender=send, contact_path=contact, config_path=config, state_path=state, now=NOW)
    text = calls[0]["body"]
    assert text.startswith("ACT NOW SPCX (Roth) ext-hrs 131.20")
    assert "Suggest EXT limit sell 130.90" in text and text.endswith("CC Risk")
    assert len(text) <= ct.MAX_TEXT_CHARS and "<" not in text and "http" not in text


def test_a_long_trigger_is_truncated_not_cut_mid_word(paths):
    contact, config, state = paths
    send, calls = recorder()
    ev = event(trigger="x " * 200, action="act")
    ct.send_critical_text(ev, sender=send, contact_path=contact, config_path=config, state_path=state, now=NOW)
    text = calls[0]["body"]
    assert len(text) <= ct.MAX_TEXT_CHARS
    assert text.endswith("act. CC Risk")          # the action survives the shortening
    assert "ACT NOW SPCX" in text


def test_a_trigger_with_no_spaces_keeps_the_action_and_the_number(paths):
    """A 300-character token used to collapse the text to 'ACT NOW SPCX… CC Risk' — no trigger, no action."""
    contact, config, state = paths
    send, calls = recorder()
    ev = event(trigger="x" * 300, action="EXT limit sell 130.90")
    ct.send_critical_text(ev, sender=send, contact_path=contact, config_path=config, state_path=state, now=NOW)
    text = calls[0]["body"]
    assert len(text) <= ct.MAX_TEXT_CHARS
    assert "Suggest EXT limit sell 130.90" in text
    assert "ACT NOW SPCX" in text
    assert text.endswith("CC Risk")


def test_the_same_event_never_texts_twice(paths):
    contact, config, state = paths
    send, calls = recorder()
    first = ct.send_critical_text(event(), sender=send, contact_path=contact, config_path=config, state_path=state, now=NOW)
    second = ct.send_critical_text(event(), sender=send, contact_path=contact, config_path=config, state_path=state,
                                   now=NOW + timedelta(minutes=5))
    assert first["sent"] is True and second["sent"] is False
    assert second["deduped"] == "SPCX:A1:2026-11-04T17:30"
    assert len(calls) == 2                                  # one fan-out, not two


def test_a_switched_off_class_does_not_text(paths):
    contact, config, state = paths
    send, calls = recorder()
    result = ct.send_critical_text(event(alert_class="B7_margin_or_cash"), sender=send, contact_path=contact,
                                   config_path=config, state_path=state, now=NOW)
    assert result["sent"] is False and "switched off" in result["reason"]
    assert calls == []


def test_an_unknown_class_fails_closed(paths):
    contact, config, state = paths
    send, calls = recorder()
    result = ct.send_critical_text(event(alert_class="Z9_invented"), sender=send, contact_path=contact,
                                   config_path=config, state_path=state, now=NOW)
    assert result["sent"] is False and "allowlist" in result["reason"] and calls == []


def test_no_gateway_configured_is_reported_not_invented(tmp_path):
    contact = tmp_path / "operator_contact.json"
    contact.write_text(json.dumps({"critical_sms_email_gateway": ""}), encoding="utf-8")
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"classes": {"A1_extended_hours_near_stop": {"enabled": True}}}), encoding="utf-8")
    send, calls = recorder()
    result = ct.send_critical_text(event(), sender=send, contact_path=contact, config_path=config,
                                   state_path=tmp_path / "s.json", now=NOW)
    assert result["sent"] is False and "no gateway" in result["reason"] and calls == []


def test_a_missing_allowlist_file_texts_nothing(tmp_path):
    contact = tmp_path / "operator_contact.json"
    contact.write_text(json.dumps({"critical_sms_email_gateways": FAKE_LINES}), encoding="utf-8")
    send, calls = recorder()
    result = ct.send_critical_text(event(), sender=send, contact_path=contact,
                                   config_path=tmp_path / "absent.json", state_path=tmp_path / "s.json", now=NOW)
    assert result["sent"] is False and calls == []


def test_the_hourly_cap_counts_texts_not_events(paths):
    """One event fans out to every verified Fi line, so a cap of 2 is one event on two lines, not two events."""
    contact, config, state = paths
    send, calls = recorder()
    first = ct.send_critical_text(event(event_id="e0"), sender=send, contact_path=contact, config_path=config,
                                  state_path=state, now=NOW)
    assert first["sent"] is True and len(calls) == 2          # two lines, two texts
    blocked = ct.send_critical_text(event(event_id="e1"), sender=send, contact_path=contact, config_path=config,
                                    state_path=state, now=NOW + timedelta(minutes=10))
    assert blocked["sent"] is False and "cap" in blocked["reason"]
    assert "2/2 texts" in blocked["reason"]
    assert len(calls) == 2                                    # nothing left the building after the cap


def test_one_failing_line_does_not_silence_the_other(paths):
    contact, config, state = paths
    seen = []

    def flaky(subject, body, to=None, attachments=None):
        seen.append(to)
        return to != FAKE_LINES[0]          # the first line fails

    result = ct.send_critical_text(event(), sender=flaky, contact_path=contact, config_path=config,
                                   state_path=state, now=NOW)
    assert seen == FAKE_LINES
    assert result["sent"] is True           # the second line carried it
    assert [r["ok"] for r in result["receipts"]] == [False, True]


def test_no_address_in_the_repo_allowlist():
    import re

    doc = json.loads((Path(__file__).resolve().parents[1] / ct.CONFIG_REL).read_text(encoding="utf-8"))
    blob = json.dumps(doc)
    # Class ids only; addresses live in operator_contact.json. `@v1` in the schema is not an address.
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", blob)


# ── D35 B4: the Schwab-login text carries the full one-tap reauth link ────────────────────────────────
# The hostname below is synthetic. The real tailnet base is runtime configuration (TRADEAI_CC_LINK_BASE),
# never a repository value: the repo is public and a tailnet host is an address.
FAKE_LINK_BASE = "https://cc-fixture.ts.net"


def _login_event(**over):
    base = dict(alert_class="B4_schwab_login_expiring", event_id="SCHWAB:B4:2026-11-04T17:30",
                trigger="Schwab login expires in 12h", action="Open Command Center and sign in again")
    base.update(over)
    return event(**base)


def test_the_login_text_carries_the_full_reauth_link():
    text = ct.format_text(_login_event(), link_base=FAKE_LINK_BASE)
    assert "https://cc-fixture.ts.net/v3/system/schwab-reauth" in text
    assert len(text) <= ct.MAX_TEXT_CHARS
    assert text.endswith("CC Risk")


def test_the_login_text_refuses_a_dev_port():
    for base in ("https://cc-fixture.ts.net:7777", "https://cc-fixture.ts.net:8443"):
        with pytest.raises(ct.CriticalTextError):
            ct.format_text(_login_event(), link_base=base)


def test_the_login_text_refuses_plain_http_and_a_non_tailnet_host():
    for base in ("http://cc-fixture.ts.net", "https://command-center.example.com"):
        with pytest.raises(ct.CriticalTextError):
            ct.format_text(_login_event(), link_base=base)


def test_the_login_text_fails_closed_without_a_link_base(monkeypatch):
    monkeypatch.delenv(ct.LINK_BASE_ENV, raising=False)
    with pytest.raises(ct.CriticalTextError):
        ct.format_text(_login_event())


def test_only_the_login_class_may_carry_a_link():
    with pytest.raises(ct.CriticalTextError):
        ct.format_text(event(link_base=FAKE_LINK_BASE))


def test_a_long_login_trigger_is_shortened_and_the_link_is_never_cut(monkeypatch):
    monkeypatch.delenv(ct.LINK_BASE_ENV, raising=False)
    long = _login_event(trigger="the Schwab refresh token expires in twelve hours " + "and the stop checks go blind " * 4)
    text = ct.format_text(long, link_base=FAKE_LINK_BASE)
    assert "https://cc-fixture.ts.net/v3/system/schwab-reauth" in text
    assert len(text) <= ct.MAX_TEXT_CHARS


ANCHOR = 'CRITICAL_TEXTS_20261104'  # config/ci_gates/critical_texts_20261104.json names this file


def test_a_producer_supplied_link_keeps_the_producers_own_sentence():
    """critical_producers._b4 hands in the finished URL inside its action; the assertion is that the sentence survives.

    Counting occurrences of the URL would pass for the wrong reason: a text that dropped the action and re-appended the link
    still contains one URL. The property is the producer's sentence, whole, inside one 160-character text.
    """
    url = "https://cc-fixture.ts.net/v3/system/schwab-reauth"
    action = f"Re-authorise at {url}"
    ev = _login_event(link=url, action=action)
    text = ct.format_text(ev)
    assert f"Suggest {action}." in text
    assert len(text) <= ct.MAX_TEXT_CHARS


def test_a_producer_supplied_link_gets_no_validation_exemption():
    with pytest.raises(ct.CriticalTextError):
        ct.format_text(_login_event(link="https://cc-fixture.ts.net:7777/v3/system/schwab-reauth",
                                    action="Re-authorise"))
    with pytest.raises(ct.CriticalTextError):
        ct.format_text(_login_event(link="http://cc-fixture.ts.net/v3/system/schwab-reauth", action="Re-authorise"))


# ── Findings from the whole-head review of c417f3776 (2026-11-05) ─────────────────────────────────────
URL = "https://cc-fixture.ts.net/v3/system/schwab-reauth"


def _b4_producer_event(renewal_wording: str) -> dict:
    """The exact shape critical_producers._b4 builds: `Schwab login expiring — {quote}: {url}`."""
    return _login_event(trigger="Schwab login expires in 12h",
                        action=f"Schwab login expiring — {renewal_wording}: {URL}", link=URL)


def test_an_over_long_producer_sentence_is_refused_not_truncated(monkeypatch):
    """F1: a 62-character renewal_wording (action 137 chars) used to be sliced to 160, cutting the URL and sending it."""
    monkeypatch.delenv(ct.LINK_BASE_ENV, raising=False)
    ev = _b4_producer_event("r" * 62)
    assert len(ev["action"]) == 137                     # the exact shape the reviewer drove
    with pytest.raises(ct.CriticalTextError):
        ct.format_text(ev)
    with pytest.raises(ct.CriticalTextError):
        # A plain over-long action with the link embedded is the same defect, not wording-specific.
        ct.format_text(_login_event(link=URL, action="Schwab login expiring: " + "y" * 130 + " " + URL))


def test_an_over_long_producer_sentence_sends_nothing_and_says_why(monkeypatch, tmp_path):
    """F1 through the public entry point: no broken link leaves the building, and the refusal names the reason."""
    monkeypatch.delenv(ct.LINK_BASE_ENV, raising=False)
    contact = tmp_path / "operator_contact.json"
    contact.write_text(json.dumps({"critical_sms_email_gateways": FAKE_LINES}), encoding="utf-8")
    config = tmp_path / "critical_text_classes.json"
    config.write_text(json.dumps({"classes": {"B4_schwab_login_expiring": {"enabled": True}},
                                  "max_per_hour": 10, "dedupe_hours": 12}), encoding="utf-8")
    send, calls = recorder()
    result = ct.send_critical_text(_b4_producer_event("r" * 62), sender=send, contact_path=contact,
                                   config_path=config, state_path=tmp_path / "s.json", now=NOW)
    assert result["sent"] is False and "does not fit" in result["reason"]
    assert calls == []


def test_a_link_in_the_rendered_text_is_refused_for_every_other_class(monkeypatch):
    """F3: only B4 may carry a link, checked on the sentence the operator reads, not just the link fields."""
    monkeypatch.delenv(ct.LINK_BASE_ENV, raising=False)
    for field in ("action", "trigger"):
        with pytest.raises(ct.CriticalTextError):
            ct.format_text(event(**{field: "open http://evil.example/?token=SECRET"}))
    with pytest.raises(ct.CriticalTextError):
        ct.format_text(event(action="see www.evil.example now"))
    with pytest.raises(ct.CriticalTextError):
        ct.format_text(event(action="visit ftp://evil.example/x"))
    # A plain number/decimal is not a URL and still formats.
    assert "Suggest EXT limit sell 130.90." in ct.format_text(event())


def test_a_malformed_link_base_is_a_named_refusal_not_a_bare_valueerror(monkeypatch, tmp_path):
    """F4: urlsplit/`.port` can raise ValueError; the channel's contract is an explicit policy refusal."""
    monkeypatch.delenv(ct.LINK_BASE_ENV, raising=False)
    for base in ("https://cc-fixture.ts.net:abc", "https://[::1", "https://cc-fixture.ts.net:99999"):
        with pytest.raises(ct.CriticalTextError):
            ct.critical_link(base)

    contact = tmp_path / "operator_contact.json"
    contact.write_text(json.dumps({"critical_sms_email_gateways": FAKE_LINES}), encoding="utf-8")
    config = tmp_path / "critical_text_classes.json"
    config.write_text(json.dumps({"classes": {"B4_schwab_login_expiring": {"enabled": True}},
                                  "max_per_hour": 10, "dedupe_hours": 12}), encoding="utf-8")
    send, calls = recorder()
    result = ct.send_critical_text(_login_event(link_base="https://cc-fixture.ts.net:abc"),
                                   sender=send, contact_path=contact, config_path=config,
                                   state_path=tmp_path / "s.json", now=NOW)
    assert result["sent"] is False and "not a valid URL" in result["reason"]
    assert calls == []


def test_the_append_path_shortens_the_trigger_not_the_action(monkeypatch):
    """F5: with a long trigger and a link_base, the old path sliced the body and lost/cut the action."""
    monkeypatch.delenv(ct.LINK_BASE_ENV, raising=False)
    action = "Re-authorise and sign in again"
    long_trigger = "the Schwab refresh token expires in twelve hours " + "and the stop checks go blind " * 4
    text = ct.format_text(_login_event(trigger=long_trigger, action=action), link_base=FAKE_LINK_BASE)
    assert f"Suggest {action}." in text                 # the action survives whole
    assert URL in text                                  # the link survives whole
    assert text.endswith("CC Risk")
    assert len(text) <= ct.MAX_TEXT_CHARS


# ── Findings from the whole-head review of d7d9c5004 (2026-11-05, codex-cloud) ───────────────────────

def _live_paths(tmp_path, *, max_per_hour=2, classes=None):
    """A contact + allowlist pair with both fake Fi lines and the given cap."""
    contact = tmp_path / "operator_contact.json"
    contact.write_text(json.dumps({"critical_sms_email_gateways": FAKE_LINES}), encoding="utf-8")
    config = tmp_path / "critical_text_classes.json"
    config.write_text(json.dumps({
        "classes": classes or {"A1_extended_hours_near_stop": {"enabled": True}},
        "max_per_hour": max_per_hour, "dedupe_hours": 12,
    }), encoding="utf-8")
    return contact, config, tmp_path / "state.json"


def test_the_default_sender_is_a_communications_gateway_intent(monkeypatch, tmp_path):
    """CX1: without an injected sender each Fi line is a gateway intent, never a direct provider call.

    The mutation is the old body: import ``scripts.email_notifier.send_email`` directly instead of calling
    ``send_via_gateway``. Then ``seen`` is empty (no gateway call) and the patched provider explodes.
    """
    contact, config, state = _live_paths(tmp_path)
    import scripts.email_notifier as notifier
    import scripts.lib.comms.channel_adapters as channel_adapters

    def _direct_provider(*_a, **_k):
        raise AssertionError("critical texts must not call a provider directly")

    monkeypatch.setattr(notifier, "send_email", _direct_provider)
    seen = []

    def fake_gateway(channel, **kwargs):
        seen.append((channel, kwargs))
        return {"ok": True, "delivered": True, "event_id": f"ev{len(seen)}",
                "delivery_id": f"d{len(seen)}", "gateway_mode": "ACTIVE"}

    monkeypatch.setattr(channel_adapters, "send_via_gateway", fake_gateway)
    result = ct.send_critical_text(event(), contact_path=contact, config_path=config, state_path=state, now=NOW)

    assert result["sent"] is True and len(seen) == 2
    assert [channel for channel, _ in seen] == ["email", "email"]
    assert [kwargs["to"] for _, kwargs in seen] == FAKE_LINES
    assert all(kwargs["deliver"] is True for _, kwargs in seen)
    assert [kwargs["producer"] for _, kwargs in seen] == ["critical_texts", "critical_texts"]
    assert result["gateways"] == 2


def test_a_blocked_gateway_delivery_is_a_failed_receipt_not_a_silent_send(monkeypatch, tmp_path):
    """CX1: when the gateway does not deliver, the channel says so; it never claims a send it did not make."""
    contact, config, state = _live_paths(tmp_path)
    import scripts.lib.comms.channel_adapters as channel_adapters

    monkeypatch.setattr(channel_adapters, "send_via_gateway",
                        lambda *a, **k: {"ok": False, "delivered": False, "error": "delivery_blocked_mode",
                                         "event_id": "ev", "gateway_mode": "OFF"})
    result = ct.send_critical_text(event(), contact_path=contact, config_path=config, state_path=state, now=NOW)
    assert result["sent"] is False
    assert [r["ok"] for r in result["receipts"]] == [False, False]
    assert not state.exists()                       # nothing recorded as sent, so no dedupe entry was written


def test_two_overlapping_producers_cannot_both_send_the_same_event(tmp_path):
    """CX2: the read/check/send/write transaction is serialized, so the same event fans out once.

    Both threads pass the start barrier together and the sender is slow enough that, without the state
    transaction lock, both load an empty state and both fan out (four texts). With it, the second sees the
    first's send and dedupes.
    """
    contact, config, state = _live_paths(tmp_path)
    calls = []
    calls_lock = threading.Lock()

    def slow_sender(subject, body, to=None, attachments=None):
        with calls_lock:
            calls.append(to)
        time.sleep(0.05)
        return True

    start = threading.Barrier(2)
    results = []

    def worker():
        start.wait()
        results.append(ct.send_critical_text(event(), sender=slow_sender, contact_path=contact,
                                             config_path=config, state_path=state, now=NOW))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(r["sent"] for r in results) == [False, True]
    assert any(r.get("deduped") for r in results)
    assert calls == FAKE_LINES                      # one fan-out, not two


def test_two_overlapping_events_cannot_exceed_the_hourly_text_cap(tmp_path):
    """CX2: the cap is a reservation taken under the lock, so two events cannot each pass it.

    Cap 2 with two lines is one event. Without the lock both events load zero recent texts and both send
    two, so four texts leave against a cap of two.
    """
    contact, config, state = _live_paths(tmp_path, max_per_hour=2)
    calls = []
    calls_lock = threading.Lock()

    def slow_sender(subject, body, to=None, attachments=None):
        with calls_lock:
            calls.append(to)
        time.sleep(0.05)
        return True

    start = threading.Barrier(2)
    results = []
    events = [event(event_id="ev-A"), event(event_id="ev-B")]

    def worker(ev):
        start.wait()
        results.append(ct.send_critical_text(ev, sender=slow_sender, contact_path=contact,
                                             config_path=config, state_path=state, now=NOW))

    threads = [threading.Thread(target=worker, args=(ev,)) for ev in events]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 2                          # the cap, not four
    assert sum(1 for r in results if r["sent"]) == 1
    assert any("cap" in str(r.get("reason") or "") for r in results)


def test_a_stop_alert_for_one_account_does_not_suppress_anothers(tmp_path):
    """CX3: two accounts with the same symbol/date/price get different identities and both text."""
    from scripts.lib.critical_text_triggers import extended_hours_near_stop

    contact, config, state = _live_paths(tmp_path, max_per_hour=10)
    account_a = extended_hours_near_stop("SPCX", "Account A", 131.20, 130.00, date_key="2026-11-04")
    account_b = extended_hours_near_stop("SPCX", "Account B", 131.20, 130.00, date_key="2026-11-04")
    assert account_a["event_id"] != account_b["event_id"]

    send, calls = recorder()
    first = ct.send_critical_text(account_a, sender=send, contact_path=contact, config_path=config,
                                  state_path=state, now=NOW)
    second = ct.send_critical_text(account_b, sender=send, contact_path=contact, config_path=config,
                                   state_path=state, now=NOW)
    assert first["sent"] is True and second["sent"] is True
    assert len(calls) == 4                          # two accounts x two Fi lines

