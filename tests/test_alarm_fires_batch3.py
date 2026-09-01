"""C1 batch 3 — the Alpaca host-lock and the system health alerts.

Site-level coverage: these files have alarm sites in several functions, so only the
sites actually exercised are declared. Claiming the whole file would assert that
alarms had been observed firing when they had not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# system_health_agent.py:478 is deliberately NOT listed. Its alerts are confirmed
# NOT to reach the transport (see the finding test below), and "covered" means
# observed firing. Claiming it would be the exact overstatement this gate exists to
# prevent.
COVERS = [
    "scripts/alpaca_stop_manager.py:65",
    "scripts/alpaca_stop_manager.py:77",
]


# ── alpaca_stop_manager: the live-endpoint host lock ─────────────────────────
def test_non_paper_mode_alarms_and_refuses(alarm_capture):
    import alpaca_stop_manager as ASM
    with pytest.raises(RuntimeError):
        ASM.require_paper_trading_base({"ALPACA_MODE": "live"})
    alarm_capture.assert_fired(contains="host-lock")


def test_live_endpoint_alarms_and_refuses(alarm_capture):
    import alpaca_stop_manager as ASM
    with pytest.raises(RuntimeError):
        ASM.require_paper_trading_base(
            {"ALPACA_MODE": "paper", "ALPACA_BASE_URL": "https://api.alpaca.markets"})
    alarm_capture.assert_fired(contains="Live Alpaca endpoint")


def test_a_valid_paper_base_does_not_alarm(alarm_capture):
    """An alarm that fires on the healthy path is also indistinguishable from none."""
    import alpaca_stop_manager as ASM
    ASM.require_paper_trading_base(
        {"ALPACA_MODE": "paper", "ALPACA_BASE_URL": f"https://{ASM.PAPER_HOST}"})
    assert not alarm_capture.fired, alarm_capture.text()[:160]


def test_host_lock_bypasses_the_router(alarm_capture, monkeypatch):
    """A safety refusal must not be digestible away.

    The signal-flow CRITICAL was routed, classified P1_DIGEST and suppressed into an
    archive nothing delivers. This asserts the host lock does not share that fate.
    """
    try:
        import telegram_alert_router as TR
        monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: False, raising=True)
    except Exception:
        pytest.skip("router unavailable")
    import alpaca_stop_manager as ASM
    with pytest.raises(RuntimeError):
        ASM.require_paper_trading_base({"ALPACA_MODE": "live"})
    alarm_capture.assert_fired(contains="host-lock")


# ── system_health_agent._send_alert — FINDING, not coverage ──────────────────
@pytest.mark.parametrize("body", [
    "⚠️ AGENT STALENESS\nresearch-lane stale for 9h",
    "🔴 PIPELINE HEALTH\nscreener produced 0 rows",
])
def test_health_alerts_are_suppressed_and_never_page_FINDING(alarm_capture, body):
    """FINDING, pinned as current behaviour. These alerts do not reach Telegram.

    _send_alert says "Send alert through central router. NEVER bypass", so the
    router decides whether it is heard. For these exact bodies -- the ones
    run_health_check emits -- it returns P1_DIGEST and the message is archived to
    telegram_outbox instead of sent.

    That archive is readable in the v3 Reports portal, so this is not total silence.
    But nothing PUSHES it: the only active digest cron reads a different table. The
    alert reaches a pull surface, never a page.

    This test asserts the CURRENT behaviour rather than the desired one, because
    bypassing a function whose contract says NEVER bypass is a design decision for
    the operator, not a fix an agent should take unilaterally. When that decision is
    made, this test flips to assert delivery and the site can be declared covered.
    """
    import system_health_agent as SHA
    SHA._send_alert(body)
    assert not alarm_capture.fired, (
        "health alerts now reach the transport — good. Flip this test to "
        "assert_fired() and add system_health_agent.py:478 to COVERS."
    )
    assert alarm_capture.suppressed, "expected the router to record a suppression"
