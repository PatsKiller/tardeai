"""C1 batch 2 — the stop path. Ten send_telegram sites in open_trade_monitor.

STOP_HIT_CLOSE, TIME_STOP_CLOSE, TRAILING_STOP and NEAR_TARGET were undeliverable
from 2026-05-25 to 2026-08-31: 581 identical failures, one cause, nobody paged. The
operator got 40 copies of the "monitoring" alert (a different, working sender) and
zero copies of "your stop was hit and I closed the position".

Nine of the ten sites call this module's own send_telegram(message, dry_run,
no_telegram) wrapper; the tenth is that wrapper's real transport call. Testing the
wrapper is therefore what covers the nine, which is why COVERS names the file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/open_trade_monitor.py"]

STOP_CLOSE = "🛑 STOP_HIT_CLOSE AAPL — stop hit at 182.40, position closed"


def _otm():
    import open_trade_monitor as OTM
    return OTM


def test_stop_close_reaches_the_transport(alarm_capture):
    """The alarm that was undeliverable for 98 days."""
    _otm().send_telegram(STOP_CLOSE)
    alarm_capture.assert_fired(contains="STOP_HIT_CLOSE")


def test_stop_close_delivers_even_when_the_router_would_suppress_it(alarm_capture, monkeypatch):
    """Pins the measured claim behind bypass_router=True.

    The wrapper's comment states the router's should_send_telegram() returns False
    for a stop-close body, so routing this normally "would replace a silent failure
    with a different silent failure that looks fixed". That is exactly what happened
    to the signal-flow CRITICAL in batch 1. This test makes the claim enforceable
    rather than a comment: with the router refusing everything, the stop close must
    STILL reach the transport.
    """
    try:
        import telegram_alert_router as TR
        monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: False, raising=True)
    except Exception:
        pytest.skip("router unavailable")
    _otm().send_telegram(STOP_CLOSE)
    alarm_capture.assert_fired(contains="STOP_HIT_CLOSE")


@pytest.mark.parametrize("kwargs", [{"no_telegram": True}, {"dry_run": True}])
def test_declared_suppression_does_not_reach_the_transport(alarm_capture, kwargs):
    """no_telegram and dry_run are DECLARED off-switches, not silent failures.

    They must suppress -- otherwise a dry run pages the operator. The distinction
    that matters is that these are arguments a caller passes deliberately, unlike an
    ImportError swallowed by a bare except.
    """
    _otm().send_telegram(STOP_CLOSE, **kwargs)
    assert not alarm_capture.fired, alarm_capture.text()[:160]


def test_a_broken_sender_is_reported_not_swallowed(alarm_capture, monkeypatch, caplog):
    """The 98-day defect: the import failed and nothing said so at ERROR.

    Reintroducing an unimportable sender must produce
    'STOP-PATH NOTIFICATION UNDELIVERABLE' at ERROR, not a quiet return.
    """
    import telegram_alert as TA
    monkeypatch.delattr(TA, "send_telegram", raising=True)
    with caplog.at_level("ERROR"):
        _otm().send_telegram(STOP_CLOSE)
    assert not alarm_capture.fired
    assert any("UNDELIVERABLE" in r.message or "NOT DELIVERED" in r.message
               for r in caplog.records), [r.message for r in caplog.records]


def test_a_refused_delivery_is_reported(alarm_capture, monkeypatch, caplog):
    """send_telegram returning False must be logged, not treated as success."""
    import telegram_alert as TA
    monkeypatch.setattr(TA, "send_telegram", lambda *a, **k: False, raising=True)
    with caplog.at_level("ERROR"):
        _otm().send_telegram(STOP_CLOSE)
    assert any("NOT DELIVERED" in r.message for r in caplog.records), \
        [r.message for r in caplog.records]
