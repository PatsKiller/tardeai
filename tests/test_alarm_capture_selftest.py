"""The harness must be proven to capture, and proven to notice a silent alarm."""
from __future__ import annotations

# `alarm_capture` is a fixture from tests/conftest.py — no import needed.


def test_harness_captures_a_real_send(alarm_capture):
    import telegram_alert as TA
    TA._raw_send_telegram("probe: harness self-test")
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
    TA._raw_send_telegram("probe: must not leak")
    alarm_capture.assert_fired()
