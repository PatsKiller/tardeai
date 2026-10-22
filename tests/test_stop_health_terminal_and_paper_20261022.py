"""Stop health false positives (operator 2026-10-22: "false positive, I have no stop on SpaceX and don't own HPE").

1. SPCX: stops already FILLED (stale) or REPLACED sat above a price that had since dropped, so their negative
   proximity marked them health=alert and stop_health_check paged "NEAR TRIGGER — about to fire". A stop that can no
   longer fire is never "about to fire".
2. HPE: a working stop on the Alpaca paper account (tradeai_automated) read as a real holding because the batched card
   drops the account. Every line now names the account, and Alpaca lines say PAPER.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import stop_health_check as shc  # noqa: E402
import stop_lifecycle_monitor as slm  # noqa: E402

HELD = {"shares": 600.0, "broker_shares": 600.0, "price": 151.4}


def _stop(status, stop_price, **kw):
    s = {"symbol": "SPCX", "account": "schwab_rollover_ira", "broker": "schwab", "order_id": "1",
         "order_type": "STOP", "status": status, "stop_price": stop_price, "qty": 600.0}
    s.update(kw)
    return s


def test_replaced_stop_above_price_is_not_an_alert():
    r = slm._classify(_stop("replaced", 151.5), HELD)
    assert r["lifecycle"] == "cancelled" and r["proximity_pct"] < 0
    assert r["health"] != "alert" and "near_trigger" not in r["flags"]


def test_stale_filled_stop_above_price_is_not_an_alert():
    r = slm._classify(_stop("filled", 151.5, closed_at="2026-10-01T15:00:00+00:00"), HELD)
    assert r["lifecycle"] == "filled" and "filled_stale" in r["flags"]
    assert r["health"] != "alert"


def test_fresh_fill_still_alerts():
    from datetime import datetime, timezone
    r = slm._classify(_stop("filled", 151.5, closed_at=datetime.now(timezone.utc).isoformat()), HELD)
    assert "filled" in r["flags"] and r["health"] == "alert"


def test_working_stop_inside_alert_band_still_alerts():
    r = slm._classify(_stop("working", 151.0), HELD)
    assert r["lifecycle"] == "near_trigger" and r["health"] == "alert"


def _run(monkeypatch, alerts):
    sent = []

    class _SLM:
        @staticmethod
        def scan(persist=True):
            return {"summary": {"total": len(alerts), "by_health": "alert"}, "alerts": alerts}

    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor", _SLM)
    monkeypatch.setattr(shc, "_recently_alerted", lambda sym, cond, hours=2: False)
    monkeypatch.setattr(shc, "_siem", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_hermes_finding", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_send_telegram", lambda m, **k: sent.append(m) or True)
    monkeypatch.setattr(shc, "_portfolio_drawdown_guard", lambda: None)
    monkeypatch.setattr(shc, "_log_health_event", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_pl_if_fired", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_recover_current_scan", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(shc, "_last_known_blind_alerts", lambda *a, **k: {})
    monkeypatch.setattr(shc, "_schwab_unavailable_alert", lambda *a, **k: None)
    shc.run(quiet=True)
    return sent


def test_paper_stop_line_says_paper_and_names_the_account(monkeypatch):
    a = {"symbol": "HPE", "account": "tradeai_automated", "broker": "alpaca", "order_id": "x", "flags": ["near_trigger"],
         "qty": 88, "held_qty": 88, "stop_price": 54.02, "proximity_pct": 0.16, "lifecycle": "near_trigger",
         "health": "alert", "order_type": "stop", "current_price": 54.1, "coverage": "full"}
    b = dict(a, symbol="XLB", account="schwab_rollover_ira", broker="schwab")
    sent = _run(monkeypatch, [a, b])
    assert len(sent) == 1
    assert "[tradeai_automated · PAPER]" in sent[0]
    assert "[schwab_rollover_ira]" in sent[0] and "schwab_rollover_ira · PAPER" not in sent[0]
