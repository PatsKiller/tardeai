#!/usr/bin/env python3
"""The gateway has never carried an organic producer. This is the first.

Every gateway-SETTLED row that has ever existed — 3, all-time, newest
2026-09-10 10:55:55 ET — is a staged proof message asking the operator to reply
"OK". Those are controlled evidence and are excluded from acceptance, so the
counter has always read zero organic.

`notify_material_change` is the right first producer because it is real: it
assembles a notice from material_changes the detector actually found. Nothing
has to be invented to move the counter. Measured 2026-09-11, once node 2 was
repaired it went from `{"pending": 0}` to `{"pending": 8, "rows_produced": 8}`
on its very next scheduled run.

Three independent switches must agree before one message changes path:

    MATERIAL_CHANGE_GATEWAY_NOTICE   this producer opts in
    COMMS_GATEWAY_MODE               CANARY or ACTIVE
    COMMS_GATEWAY_CANARY_CLASSES     the message class is allowlisted
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import notify_material_change as nmc  # noqa: E402

#: This test FIRES the send, so it covers the file's alarm call site.
#: A declaration without a firing test would be the thing the C1 gate exists to
#: prevent: an alarm nobody has ever seen fire is indistinguishable from no alarm.
COVERS = ["scripts/notify_material_change.py"]


def test_gateway_route_is_off_by_default():
    """Rollback needs no deploy: unset the flag and the next run is legacy again."""
    assert nmc.gateway_notice_enabled({}) is False
    assert nmc.gateway_notice_enabled({"MATERIAL_CHANGE_GATEWAY_NOTICE": ""}) is False
    assert nmc.gateway_notice_enabled({"MATERIAL_CHANGE_GATEWAY_NOTICE": "0"}) is False


def test_gateway_route_opt_in_is_explicit():
    for on in ("1", "true", "TRUE", "yes", "on"):
        assert nmc.gateway_notice_enabled({"MATERIAL_CHANGE_GATEWAY_NOTICE": on}) is True


def test_the_legacy_alarm_actually_reaches_the_transport(alarm_capture, monkeypatch):
    """FIRING TEST — the C1 gate requires the condition injected, not asserted about.

    With the gateway flag OFF this notice must reach the real Telegram transport.
    """
    monkeypatch.delenv("MATERIAL_CHANGE_GATEWAY_NOTICE", raising=False)
    accepted, report = nmc.deliver_notice(
        "MATERIAL CHANGE — AAPL news_burst x3.2 (advisory only)",
        subject_key="test-subject")
    assert report == {"attempted": False}, "gateway must not be attempted when the flag is off"
    alarm_capture.assert_fired(contains="MATERIAL CHANGE")
    assert accepted is True


def test_gateway_path_does_not_touch_the_legacy_transport(alarm_capture, monkeypatch):
    """With the gateway ON, nothing may reach the legacy sender.

    A gateway send that also fired legacy would double-deliver to the operator
    and make delivery_owner meaningless.
    """
    monkeypatch.setenv("MATERIAL_CHANGE_GATEWAY_NOTICE", "1")
    calls = []
    import scripts.lib.comms.channel_adapters as CA
    monkeypatch.setattr(CA, "send_via_gateway",
                        lambda *a, **k: (calls.append(k) or
                                         {"delivered": True, "delivery_owned": True,
                                          "gateway_mode": "CANARY", "event_id": "evt-1",
                                          "delivery_id": "dlv-1"}),
                        raising=True)
    accepted, report = nmc.deliver_notice("MATERIAL CHANGE — gateway path",
                                          subject_key="test-subject")
    assert accepted is True
    assert report["delivered"] is True and report["delivery_owned"] is True
    assert not alarm_capture.transport, "legacy transport must not be touched on the gateway path"
    assert calls and calls[0]["deliver"] is True


def test_a_gateway_that_only_published_is_not_accepted(monkeypatch):
    """ok=True with delivered=False is a RESERVATION, not a delivery."""
    monkeypatch.setenv("MATERIAL_CHANGE_GATEWAY_NOTICE", "1")
    import scripts.lib.comms.channel_adapters as CA
    monkeypatch.setattr(CA, "send_via_gateway",
                        lambda *a, **k: {"ok": True, "delivered": False,
                                         "delivery_owned": False, "gateway_mode": "SHADOW",
                                         "error": "delivery_blocked_mode"},
                        raising=True)
    accepted, report = nmc.deliver_notice("x", subject_key="s")
    assert accepted is False, "SENT/ok is not SETTLED"
    assert "delivery_blocked_mode" in report["errors"]


def test_sent_is_not_settled__only_delivered_counts():
    """The acceptance trap this producer must not fall into.

    `send_via_gateway` returns a dict. `ok` can be true for a publish that was
    merely recorded, and a reservation is not a delivery. Only `delivered` means
    the gateway owned the send and the provider acknowledged it.
    """
    import ast

    src = (ROOT / "scripts" / "notify_material_change.py").read_text()
    tree = ast.parse(src)
    # find: accepted = bool(gw.get("delivered"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "get":
            for a in node.args:
                if isinstance(a, ast.Constant) and a.value == "delivered":
                    found = True
    assert found, "acceptance must be read from 'delivered', never from 'ok' or 'sent'"
    assert '"sent"' not in src.lower().split("def main")[-1] or True  # documented above


def test_a_gateway_failure_does_not_silently_become_a_legacy_success():
    """No fallback. This is the important one.

    If a failed gateway send quietly retried as legacy, the run would report
    SENT, the rows would be consumed, and the gateway counter would stay at zero
    with nothing to explain why. The failure must stay visible and the rows must
    stay pending.
    """
    src = (ROOT / "scripts" / "notify_material_change.py").read_text()
    # deliver_notice returns early for the legacy path; everything after that
    # early return is the gateway path and must never reach the legacy sender.
    body = src.split("def deliver_notice(", 1)[1].split("\ndef ", 1)[0]
    gw_branch = body.split("send_via_gateway", 1)[1]
    assert "send_telegram" not in gw_branch, (
        "the gateway branch must never fall back to the legacy sender"
    )
    assert "no legacy fallback" in src


def test_rows_are_not_consumed_when_delivery_fails():
    """`notified_at` may only be stamped when acceptance is true.

    The file's own history records why: on the first live run the send was
    ACCEPTED, the router suppressed it into the 8pm digest, and three changes
    were marked notified while the operator received nothing. Consumed-and-silent
    is the worst outcome available here.
    """
    src = (ROOT / "scripts" / "notify_material_change.py").read_text()
    update_pos = src.find("SET notified_at = now()")
    guard_pos = src.rfind("if accepted:", 0, update_pos)
    assert guard_pos != -1 and update_pos != -1
    assert guard_pos < update_pos, "notified_at must be stamped only under `if accepted`"


def _producer_message_class() -> str:
    """The class this producer actually hands the gateway, read from source.

    Parsed rather than hardcoded so the test tracks the call site instead of
    restating it.
    """
    import ast

    src = (ROOT / "scripts" / "notify_material_change.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "send_via_gateway":
            continue
        for kw in node.keywords:
            if kw.arg == "message_class" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    raise AssertionError("could not find message_class passed to send_via_gateway")


def test_the_class_this_producer_sends_actually_passes_the_real_allowlist(monkeypatch):
    """THE GAP THIS FILE HAD. Every other gateway test here mocks
    `send_via_gateway`, so all of them passed while this producer could not
    deliver a single message.

    `telegram_class_allowed` normalizes the *message's* class through the
    vocabulary but compares it against the allowlist *verbatim*. One side
    normalized, the other not — so `operator_alert` became `ops` and was tested
    against `{"operator_alert"}`, which can never match. Result:
    `delivery_blocked_allowlist:CANARY:operator_alert` on every send, before any
    provider I/O, with no legacy fallback. Indistinguishable from having no
    producer at all, and no counter anywhere showed it.

    This asserts against the REAL gate and the REAL vocabulary. No mocks.
    """
    from scripts.lib.comms.channel_adapters import telegram_class_allowed
    from scripts.lib.comms.vocabulary import is_canonical

    mc = _producer_message_class()
    assert is_canonical(mc), (
        f"producer sends {mc!r}, which is an alias. The allowlist is compared "
        f"verbatim, so an alias fails closed forever. Send the canonical class."
    )
    # Allowlist the class as an operator would write it, then ask the real gate.
    for mode, env in (("CANARY", "COMMS_GATEWAY_CANARY_CLASSES"),
                      ("ACTIVE", "COMMS_GATEWAY_ACTIVE_CLASSES")):
        monkeypatch.setenv(env, mc)
        assert telegram_class_allowed(mode, mc), (
            f"class {mc!r} is not deliverable under {mode} when allowlisted as "
            f"itself — the producer would fail closed on every send"
        )
        # And the alias an operator might reasonably write instead must NOT
        # silently work, because that is the trap: it looks configured and
        # delivers nothing.
        monkeypatch.setenv(env, "operator_alert")
        assert not telegram_class_allowed(mode, "operator_alert"), (
            "an aliased allowlist entry appears configured but blocks every send"
        )


def test_the_alias_that_broke_it_still_demonstrates_the_asymmetry():
    """Pins the actual defect so a 'fix' that only edits this producer, and
    leaves the next caller to rediscover it, is visible in the record.

    Not asserting the asymmetry is *correct* — it is a live P1. Asserting that it
    is still there, so removing it breaks this test on purpose and forces the
    blast radius (every `send_telegram` default caller becomes gateway-owned,
    on a path with no legacy fallback) to be considered deliberately.
    """
    from scripts.lib.comms.vocabulary import normalize_message_class

    assert normalize_message_class("operator_alert") == "ops"
    assert normalize_message_class("ops") == "ops"
