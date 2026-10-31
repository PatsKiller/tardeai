"""A message the comms classifier rates CRITICAL is never digested by the legacy text router.

2026-10-31 audit: cron senders run with the comms gateway OFF, so the legacy router decides. In 48 h it suppressed 13
messages that the comms classifier itself labelled priority=critical, including the 10-30 11:07 ET position-sync
"[holdings-change] … protective-stop band recheck recommended" alerts. Fixtures only: synthetic symbols, transport
stubbed, no network, no DB.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import telegram_alert as ta  # noqa: E402
import telegram_alert_router as router  # noqa: E402

HOLDINGS_CHANGE = "[holdings-change] SYMA resized 900→1200 sh — protective-stop band recheck recommended"


@pytest.fixture
def transport(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(ta, "_token", lambda: "synthetic")
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["1"])
    monkeypatch.setattr(
        ta, "_raw_send_telegram_result", lambda message, targets, **kw: sent.append(message) or {"ok": True}
    )
    monkeypatch.setattr(router, "mark_sent", lambda message: None)
    return sent


def test_holdings_change_stop_recheck_is_delivered_when_router_would_digest(monkeypatch, transport):
    monkeypatch.setattr(router, "should_send_telegram", lambda m: False)
    monkeypatch.setattr(router, "classify_alert", lambda m: "P1_DIGEST")
    assert ta._legacy_send(HOLDINGS_CHANGE, False) is True
    assert transport == [HOLDINGS_CHANGE]


def test_non_critical_digest_message_stays_suppressed(monkeypatch, transport):
    monkeypatch.setattr(router, "should_send_telegram", lambda m: False)
    monkeypatch.setattr(router, "classify_alert", lambda m: "P1_DIGEST")
    import report_capture

    monkeypatch.setattr(report_capture, "archive_message", lambda *a, **k: None)
    assert ta._legacy_send("Research lane health: coverage stall 11/20", False) is False
    assert transport == []


def test_rate_limited_critical_stays_suppressed(monkeypatch, transport):
    # P0 messages suppressed by the rate limit or daily budget are not classification suppressions.
    monkeypatch.setattr(router, "should_send_telegram", lambda m: False)
    monkeypatch.setattr(router, "classify_alert", lambda m: "P0_INTERRUPT")
    import report_capture

    monkeypatch.setattr(report_capture, "archive_message", lambda *a, **k: None)
    assert ta._legacy_send(HOLDINGS_CHANGE, False) is False
    assert transport == []


def test_comms_classifier_really_rates_the_fixture_critical():
    from scripts.lib.comms.classify import classify

    assert classify(body=HOLDINGS_CHANGE)["priority"] == "critical"


def test_classify_failure_keeps_router_decision(monkeypatch, capsys):
    import scripts.lib.comms.classify as c

    def boom(**kw):
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(c, "classify", boom)
    assert ta._comms_critical_override(HOLDINGS_CHANGE, "P1_DIGEST") is False
    assert "comms classify unavailable (RuntimeError)" in capsys.readouterr().out
