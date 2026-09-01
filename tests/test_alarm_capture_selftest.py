"""The harness must be proven to capture, and proven to notice a silent alarm.

Routed through send_telegram(bypass_router=True), never _raw_send_telegram: the
chokepoint ratchet counts a direct low-level call as a NEW bypass, and it is right
to. A test that bypasses the chokepoint to prove the chokepoint works is not a test.
"""
from __future__ import annotations

# `alarm_capture` is a fixture from tests/conftest.py — no import needed.


def test_harness_captures_a_real_send(alarm_capture):
    import telegram_alert as TA
    TA.send_telegram("probe: harness self-test", bypass_router=True)
    alarm_capture.assert_fired(contains="harness self-test")


def test_harness_reports_a_silent_alarm_rather_than_passing(alarm_capture):
    """If nothing is sent, assert_fired must fail. A harness that cannot fail is
    the same defect it exists to catch."""
    import pytest
    with pytest.raises(AssertionError):
        alarm_capture.assert_fired()


def test_harness_sends_nothing_over_the_network(alarm_capture, monkeypatch):
    import telegram_transport as TT
    def _boom(*a, **k):
        raise AssertionError("the real transport was called — the harness leaked")
    monkeypatch.setattr(TT, "send_message", _boom, raising=True)
    import telegram_alert as TA
    TA.send_telegram("probe: must not leak", bypass_router=True)
    alarm_capture.assert_fired()
