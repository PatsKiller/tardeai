"""C1 — every alarm must be observed firing.

An alarm that has never been observed firing is indistinguishable from no alarm.
Presence of the code is not evidence: `send_alert` was present for months and had
never existed; the stop-path alarm was present for 98 days and never fired.

Each test here INJECTS the condition that should trigger the alarm and asserts a
message reached the transport -- captured, never sent. The `alarm_capture` fixture
lives in tests/conftest.py and patches telegram_transport.send_message.

COVERS lists the exact call sites each test exercises. tests/test_alarm_coverage.py
reads it to compute covered-vs-total, so the uncovered set stays named as debt
rather than silently omitted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = [
    "scripts/session18_signal_flow_health.py",
    "scripts/telegram_alert.py",
]


class _FakeCursor:
    """Returns scripted scalars, then refuses writes the way a read-only conn would."""

    def __init__(self, scalars):
        self._scalars = list(scalars)
        self._last = None

    def execute(self, sql, params=None):
        self._last = sql
        if "INSERT" in sql.upper():
            raise RuntimeError("read-only test connection: no audit write")

    def fetchone(self):
        return [self._scalars.pop(0)] if self._scalars else [0]


class _FakeConn:
    def __init__(self, scalars):
        self._cur = _FakeCursor(scalars)

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass


# ── session18_signal_flow_health: the alarm that was silent for 24 days ──────
def test_signal_flow_CRITICAL_reaches_the_transport(alarm_capture):
    """6 GO/A+ scans, 0 strategy_signals — the exact 2026-08 condition.

    This alarm fired 171 times into a bare `except` on an import that never
    existed. It produced a CRITICAL and reached nobody. This test is the
    observation that was missing.
    """
    import session18_signal_flow_health as H

    H.check_health(_FakeConn([6, 0]))
    alarm_capture.assert_fired(contains="Strategy Desk")


def test_signal_flow_NO_GO_TODAY_does_not_alarm(alarm_capture):
    """Zero input is a finding, not a page. It must NOT reach the transport.

    Without this, the CRITICAL test above would still pass if the alarm fired on
    everything -- an alarm that always fires is also indistinguishable from no
    alarm, because nobody reads it.
    """
    import session18_signal_flow_health as H

    H.check_health(_FakeConn([0, 0]))
    assert not alarm_capture.fired, (
        f"alarm fired on zero input: {alarm_capture.text()[:160]!r}"
    )


def test_signal_flow_healthy_does_not_alarm(alarm_capture):
    import session18_signal_flow_health as H

    H.check_health(_FakeConn([6, 6]))
    assert not alarm_capture.fired, alarm_capture.text()[:160]


# ── the transport chain itself ───────────────────────────────────────────────
def test_send_telegram_reaches_the_transport(alarm_capture, monkeypatch):
    """The chain 141 call sites depend on. Router bypassed to isolate transport."""
    import telegram_alert as TA

    TA.send_telegram("C1 probe: transport chain", bypass_router=True)
    alarm_capture.assert_fired(contains="transport chain")


def test_router_suppression_is_recorded_as_not_fired(alarm_capture, monkeypatch):
    """A message the router drops has NOT fired, and must not read as success.

    Measured earlier this session: runtime_mode=OFF makes should_send_telegram
    return False for four working alert classes. Counting those as 'sent' is how
    "we alert on that" stays true while nothing arrives.
    """
    import telegram_alert as TA
    try:
        import telegram_alert_router as TR
    except Exception:
        pytest.skip("router unavailable")

    monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: False, raising=True)
    TA.send_telegram("C1 probe: should be suppressed", bypass_router=False)
    assert not alarm_capture.fired, "a suppressed message reached the transport"


def test_send_telegram_with_id_returns_the_provider_message_id(alarm_capture):
    """The id the alert plane needs, from the call that already had it.

    `_raw_send_telegram_result` has always built a `message_ids` list and
    `_legacy_send` threw it away one stack frame later. That is why all 7,830
    `alert_events` rows carry `telegram_message_id` NULL and why no alert could
    be tied to a delivery. This is the observation that the id now survives.
    """
    import telegram_alert as TA

    result = TA.send_telegram_with_id("C1 probe: id capture", bypass_router=True)
    alarm_capture.assert_fired(contains="id capture")
    assert result["accepted"] is True
    assert result["message_id"] is not None, "the transport minted an id and it was dropped again"
    assert TA.last_message_id() == result["message_id"]


def test_a_suppressed_send_reports_no_message_id(alarm_capture, monkeypatch):
    """No id is the honest answer for a message nobody received.

    Carrying the previous send's id forward would tie an alert_events row to an
    unrelated Telegram message — worse than the NULL it replaces.
    """
    import telegram_alert as TA

    try:
        import telegram_alert_router as TR
    except Exception:
        pytest.skip("router unavailable")

    TA.send_telegram_with_id("C1 probe: first send", bypass_router=True)
    monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: False, raising=True)
    result = TA.send_telegram_with_id("C1 probe: suppressed", bypass_router=False)
    assert result["message_id"] is None, "a suppressed alert must not inherit the previous id"


def test_the_bool_contract_of_send_telegram_is_unchanged(alarm_capture):
    """182 call sites depend on it. The new function is additive, not a rewrite."""
    import telegram_alert as TA

    out = TA.send_telegram("C1 probe: bool contract", bypass_router=True)
    assert out is True or out is False
