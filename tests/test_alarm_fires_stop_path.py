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
from datetime import datetime, timezone
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


# ── the trailing stop that stopped itself out ────────────────────────────────


class _FakeCursor:
    """Records SQL instead of executing it. fetchone() returns a zero count so the
    dedup probes in monitor_trade take their 'nothing recent' branch."""

    def __init__(self):
        self.statements: list[str] = []
        self.params: list = []

    def execute(self, sql, params=None):
        self.statements.append(" ".join(str(sql).split()))
        self.params.append(params)

    def fetchone(self):
        return (0,)

    def fetchall(self):
        return []

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass


def _trade(**kw):
    """SYF #2505 as stored, 2026-09-21."""
    base = dict(id=2505, symbol="SYF", strategy_id="pullback_macd_reversal",
                entry_price=74.86, entry_time=datetime(2026, 9, 21, 16, 40, tzinfo=timezone.utc),
                shares=66, stop_loss=74.99, target_1=87.38, dollar_risk=85.8,
                account="ALPACA_PAPER", current_price=75.15, unrealized_pnl=19.14,
                r_multiple=None, monitored_at=None, last_alert_at=None, stale_flag=False,
                planned_stop=73.56)
    base.update(kw)
    return base


def _run(monkeypatch, trade, price):
    """Drive monitor_trade with a recording cursor. dry_run keeps the broker out."""
    OTM = _otm()
    cur, conn = _FakeCursor(), None
    conn = _FakeConn(cur)
    monkeypatch.setattr(OTM, "get_current_price", lambda c, s: price)
    monkeypatch.setattr(OTM, "_log_risk_action", lambda *a, **k: None)
    monkeypatch.setattr(OTM, "insert_alert", lambda *a, **k: None)
    monkeypatch.setattr(OTM, "send_telegram", lambda *a, **k: True)
    OTM.monitor_trade(conn, trade, dry_run=True, no_telegram=True)
    return cur


def _recorded_r_multiple(cur):
    for sql, params in zip(cur.statements, cur.params):
        if "r_multiple=%s" in sql and params:
            return params[3]          # [price, pnl, pnl, r_mult, tid]
    return None


def _stop_writes(cur):
    return [p[0] for s, p in zip(cur.statements, cur.params)
            if "SET stop_loss=%s" in s and p]


def test_r_multiple_comes_from_the_original_risk_not_the_moving_stop(monkeypatch):
    """SYF #2505: the monitor reported R 2.2 on a trade that was at 0.22R.

    risk_per_share was abs(entry - stop) against the CURRENT stop, so every trail
    shrank the denominator and inflated R -- a feedback loop that ended only when the
    stop crossed the price. At entry 74.86 / planned_stop 73.56 / price 75.15 the true
    move is 0.22R, which does not meet the >= 1.0R gate, so no trailing may occur.

    The close path already divided by dollar_risk; this pins the monitor to agree.
    """
    cur = _run(monkeypatch, _trade(), price=75.15)
    r = _recorded_r_multiple(cur)
    assert r is not None, cur.statements
    assert abs(float(r) - 0.22) < 0.02, f"r_multiple={r}, expected ~0.22 (was 2.23)"
    assert _stop_writes(cur) == [], \
        f"0.22R must not trail at all, but the stop was moved to {_stop_writes(cur)}"


def test_a_trailed_stop_is_never_placed_at_or_above_the_price(monkeypatch):
    """A stop must never be written at or above the market.

    Constructed the way production actually looks: stop_loss has ALREADY been trailed
    away from planned_stop. That divergence is the bug's engine -- the old code read R
    off the moved stop (a shrinking denominator) while the tier arithmetic used the
    original risk, so the two disagreed and the arithmetic reached past the price.

    On SYF #2505 that produced stop 76.16 against price 75.15. Alpaca rejected it
    (code 42210000, "stop price must be less than current price") but the local row
    had already been written, so the next pass read its own phantom stop, saw
    price <= stop, and auto-closed the trade -- booked as a WIN.

    An earlier version of this test set stop_loss == planned_stop, which cannot
    reproduce the divergence and therefore passed with or without the fix.
    """
    for trailed, price in ((74.99, 75.15), (74.90, 75.40), (74.70, 75.80)):
        cur = _run(monkeypatch, _trade(stop_loss=trailed), price=price)
        for written in _stop_writes(cur):
            assert written < price, (
                f"stop {written} written at/above price {price} "
                f"(trailed stop was {trailed}, planned_stop 73.56)")
