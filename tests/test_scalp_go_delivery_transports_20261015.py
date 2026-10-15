"""DD01 closure evidence (third-party n8n audit, 2026-10-15): the scalp GO delivery path under every raw transport.

Finding: lane trade-ai-scalp-live is allowlisted with a sender exception; its runner calls
continuous_runner._deliver_live_alert, which lazily imported alerting.send_whatsapp / alerting.send_slack and called
both BEFORE the send_telegram chokepoint (scripts/continuous_runner.py lines 636-637 before the fix). Required evidence: a hermetic
GO integration that intercepts every raw transport and shows one bounded intent and one delivery-owner action per
attempt, across disabled / partial / failed / retried delivery, without duplication.

What runs: only continuous_runner.CycleState + _deliver_live_alert (the notify path; no scan, no DB, no broker,
no order, no LLM: the per-trigger line builder is replaced) and the REAL scripts/alerting.py, so its raw transports
are exercised and caught. Every raw transport is replaced before anything runs: requests.post /
requests.Session.request, urllib.request.urlopen, http.client.HTTPConnection.request, smtplib.SMTP / SMTP_SSL,
socket.create_connection / socket.socket.connect (raise), and a fake twilio.rest.Client. The Telegram chokepoint
(telegram_alert.send_telegram) is a stub that records the intent; no token store, env file or network is touched.
Credentials below are fake literals, never read from any environment file.

Results (after the operator-approved fix, 2026-10-15: the direct send_whatsapp / send_slack calls were removed):
  * transports not configured, switched off, or fully configured with switches at their "true" default: zero raw
    sends and exactly one chokepoint call per attempt, no duplicate after delivery, across delivered / disabled /
    partial / failed-then-retried / failed-capped. Before the fix, a configured GO retried twice reached Slack and
    WhatsApp three times each while the chokepoint delivered it once.
"""

from __future__ import annotations

import http.client
import json
import smtplib
import socket
import sys
import types
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import continuous_runner as cr  # noqa: E402

MARKET = {"indices": {"SPY": {"change_percent": 0.4}}, "vix": {"price": 15.0}, "breadth_label": "ok"}
POLICY = {"max_attempts_per_trigger_per_day": 3, "retry_backoff_base_s": 600.0, "retry_backoff_multiplier": 2.0}
T0 = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
TELEGRAM_MAX = 4096
TRANSPORT_ENV = (
    "ENABLE_SLACK",
    "ENABLE_WHATSAPP",
    "ENABLE_EMAIL",
    "SLACK_WEBHOOK_URL",
    "TWILIO_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "TWILIO_WHATSAPP_TO",
)
FAKE_CREDS = {
    "SLACK_WEBHOOK_URL": "https://hooks.slack.invalid/services/T000/B000/fake",
    "TWILIO_SID": "ACfake000",
    "TWILIO_AUTH_TOKEN": "fake-token-not-real",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+10000000000",
    "TWILIO_WHATSAPP_TO": "whatsapp:+10000000001",
}


class Wire:
    """Every raw transport call, by kind. Anything that would leave the process lands here instead."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.intents: list[dict] = []

    def raw(self) -> list[tuple[str, str]]:
        return list(self.calls)

    def count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)


@pytest.fixture
def wire(monkeypatch):
    w = Wire()

    def rec(kind):
        def _f(*a, **k):
            target = str(a[1] if len(a) > 1 and kind == "requests.session" else (a[0] if a else k.get("url", "")))
            w.calls.append((kind, target[:80]))
            return types.SimpleNamespace(status_code=200, ok=True, text="", json=lambda: {})

        return _f

    import requests

    monkeypatch.setattr(requests, "post", rec("requests.post"))
    monkeypatch.setattr(requests, "get", rec("requests.get"))
    monkeypatch.setattr(requests.Session, "request", rec("requests.session"))
    monkeypatch.setattr(urllib.request, "urlopen", rec("urllib.urlopen"))
    monkeypatch.setattr(http.client.HTTPConnection, "request", rec("http.client"))

    class _SMTP:
        def __init__(self, *a, **k):
            w.calls.append(("smtp", str(a[:1])))

        def __getattr__(self, name):
            return lambda *a, **k: None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _SMTP)

    def _no_net(*a, **k):
        w.calls.append(("socket", str(a[:1])[:80]))
        raise OSError("network blocked by test")

    monkeypatch.setattr(socket, "create_connection", _no_net)
    monkeypatch.setattr(socket.socket, "connect", _no_net)

    twilio = types.ModuleType("twilio")
    twilio_rest = types.ModuleType("twilio.rest")

    class Client:
        def __init__(self, sid, token):
            self.messages = types.SimpleNamespace(create=lambda **k: w.calls.append(("twilio", k.get("to", ""))))

    twilio_rest.Client = Client
    twilio.rest = twilio_rest
    monkeypatch.setitem(sys.modules, "twilio", twilio)
    monkeypatch.setitem(sys.modules, "twilio.rest", twilio_rest)
    nub = types.ModuleType("notification_url_builder")
    nub.publicize_message = lambda text: text
    monkeypatch.setitem(sys.modules, "notification_url_builder", nub)
    # the REAL alerting module (its raw transports are what DD01 is about), freshly imported
    monkeypatch.delitem(sys.modules, "alerting", raising=False)
    monkeypatch.delitem(sys.modules, "scripts.alerting", raising=False)
    for k in TRANSPORT_ENV:
        monkeypatch.delenv(k, raising=False)
    return w


def _chokepoint(monkeypatch, wire: Wire, outcome="accepted", delivered_ids=()):
    """The delivery owner: telegram_alert.send_telegram, stubbed. Records one intent per call."""
    tg = types.ModuleType("telegram_alert")
    pkg = types.ModuleType("scripts.telegram_alert")
    for m in (tg, pkg):
        m._ids = []
        m.reset_last_message_ids = (lambda mod: lambda: mod._ids.clear())(m)
        m.last_message_ids = (lambda mod: lambda: list(mod._ids))(m)
        m._enabled = lambda: outcome != "disabled"

    def send_telegram(msg, *a, **k):
        wire.intents.append(
            {
                "len": len(msg),
                "priority": k.get("priority"),
                "producer": k.get("producer"),
                "head": msg.split("\n", 1)[0],
            }
        )
        if outcome == "disabled":
            return False
        if outcome == "partial":
            tg._ids.extend(delivered_ids or ("4711",))
            return False
        if outcome == "raise":
            raise RuntimeError("gateway down")
        return outcome == "accepted"

    tg.send_telegram = send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", tg)
    monkeypatch.setitem(sys.modules, "scripts.telegram_alert", pkg)


def _cheap_lines(monkeypatch):
    """The real per-trigger builder calls critics / LLMs; replace it (the alert text shape is not under test)."""
    monkeypatch.setattr(cr, "_append_trigger_lines", lambda lines, t: lines.append(f"{t['type']} {t['symbol']}"))


def _row(sym, score=60):
    return {"symbol": sym, "score": score, "decision": "GO", "relative_volume": 2.0, "top_catalyst": {}}


def _cycle(state, now, rows=None):
    """detect -> update -> unmark -> deliver: the run_live_cycle alert path for one 5-minute cycle."""
    cs: dict = {"errors": []}
    rows = rows or [_row("AAA")]
    trig = state.detect_triggers(rows, {})
    state.update(rows)
    cr._set_trigger_marks(state, trig, alerted=False)
    n = cr._deliver_live_alert(state, trig, "10:00", MARKET, cs, None, policy=POLICY, now=now) if trig else 0
    return trig, cs, n


def _roundtrip(st):
    return cr.CycleState.from_dict(json.loads(json.dumps(st.to_dict())))


def _session(monkeypatch, wire, outcomes):
    """Run 5-minute cycles from T0 for 6 h; ``outcomes`` is the chokepoint result per attempt (last one repeats)."""
    st, minute, seen = cr.CycleState(), 0, []
    attempts = 0
    while minute <= 360:
        before = len(wire.intents)
        _chokepoint(monkeypatch, wire, outcomes[min(attempts, len(outcomes) - 1)])
        _, cs, n = _cycle(st, T0 + timedelta(minutes=minute))
        if len(wire.intents) > before:
            attempts += 1
        seen.append((minute, cs.get("alert_outcome"), n))
        st = _roundtrip(st)
        minute += 5
    return st, seen


def _assert_bounded_intents(wire):
    for i in wire.intents:
        assert i["producer"] == "continuous_runner" and i["priority"] == "P1"
        assert 0 < i["len"] <= TELEGRAM_MAX


@pytest.mark.parametrize(
    "outcomes,expect_intents,final",
    [
        (["accepted"], 1, "delivered"),
        (["disabled"], 1, "disabled"),
        (["partial"], 1, "partial"),
        (["rejected", "raise", "accepted"], 3, "delivered"),  # failed, failed, then delivered on the 3rd attempt
        (["rejected"], 3, "failed_final"),  # capped: 3 attempts per trigger per day, then never
    ],
    ids=["delivered", "disabled", "partial", "failed-then-retried-ok", "failed-capped"],
)
def test_go_delivery_unconfigured_transports_one_owner_no_raw_sends(monkeypatch, wire, outcomes, expect_intents, final):
    _cheap_lines(monkeypatch)
    st, seen = _session(monkeypatch, wire, outcomes)
    assert wire.raw() == [], f"raw transport reached: {wire.raw()}"
    assert len(wire.intents) == expect_intents  # one delivery-owner action per attempt, never one per cycle
    _assert_bounded_intents(wire)
    outcomes_seen = [o for _, o, _ in seen if o not in (None, "deferred")]
    assert outcomes_seen[-1] == final
    assert sum(n for _, _, n in seen) == (1 if final in ("delivered", "partial") else 0)  # delivered at most once
    assert "AAA" in st.prev_go  # never re-alerted after the final outcome


def test_go_delivery_switches_off_with_credentials_present_no_raw_sends(monkeypatch, wire):
    """Interim mitigation: credentials present but ENABLE_SLACK / ENABLE_WHATSAPP false -> no raw transport."""
    for k, v in FAKE_CREDS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ENABLE_SLACK", "false")
    monkeypatch.setenv("ENABLE_WHATSAPP", "false")
    _cheap_lines(monkeypatch)
    _session(monkeypatch, wire, ["rejected", "accepted"])
    assert wire.raw() == []
    assert len(wire.intents) == 2
    _assert_bounded_intents(wire)


@pytest.mark.parametrize(
    "outcomes,expect_intents,final",
    [
        (["accepted"], 1, "delivered"),
        (["disabled"], 1, "disabled"),
        (["partial"], 1, "partial"),
        (["rejected", "raise", "accepted"], 3, "delivered"),
        (["rejected"], 3, "failed_final"),
    ],
    ids=["delivered", "disabled", "partial", "failed-then-retried-ok", "failed-capped"],
)
def test_dd01_closure_no_raw_sends_even_with_credentials_configured(monkeypatch, wire, outcomes, expect_intents, final):
    """DD01 CLOSED (operator-approved 2026-10-15): with every Slack / Twilio credential set and the switches left at
    their "true" default, no outcome reaches a raw transport; the chokepoint is the only delivery action."""
    for k, v in FAKE_CREDS.items():
        monkeypatch.setenv(k, v)
    _cheap_lines(monkeypatch)
    st, seen = _session(monkeypatch, wire, outcomes)
    assert wire.raw() == [], f"raw transports reached: {wire.raw()}"
    assert len(wire.intents) == expect_intents
    _assert_bounded_intents(wire)
    assert [o for _, o, _ in seen if o not in (None, "deferred")][-1] == final
    assert sum(n for _, _, n in seen) == (1 if final in ("delivered", "partial") else 0)


def test_deliver_live_alert_names_no_raw_transport():
    """Static pin: the delivery function imports nothing from alerting and calls no raw sender."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(cr._deliver_live_alert)))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert "alerting" not in mods and mods <= {"telegram_alert"}
    assert not names & {"send_whatsapp", "send_slack", "send_email", "send_all_alerts"}
