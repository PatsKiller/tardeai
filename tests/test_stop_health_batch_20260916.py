#!/usr/bin/env python3
"""B2 (2026-09-16): STOP HEALTH per-symbol repeats collapse into ONE batched Telegram.

Was: one Telegram per (symbol, condition) — a scan with N orphaned/oversized stops
sent N messages. Now: SIEM + Hermes stay per-symbol (durable evidence), the phone
gets a single batched card. Single-alert scans are unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import stop_health_check as shc  # noqa: E402


def _alert(symbol, account, flags, **kw):
    r = {"symbol": symbol, "account": account, "flags": flags, "order_id": "999",
         "qty": 100, "held_qty": 100, "stop_price": 10.0, "proximity_pct": 0.4,
         "broker": "schwab", "order_type": "stop", "current_price": 9.9,
         "coverage": 1.0, "lifecycle": "active", "health": "alert"}
    r.update(kw)
    return r


def _run(monkeypatch, alerts):
    sent: list[str] = []
    siem: list = []
    hermes: list = []

    class _SLM:
        @staticmethod
        def scan(persist=True):
            return {"summary": {"total": len(alerts), "by_health": "alert"}, "alerts": alerts}

    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor", _SLM)
    monkeypatch.setattr(shc, "_recently_alerted", lambda sym, cond, hours=2: False)
    monkeypatch.setattr(shc, "_siem", lambda *a, **k: siem.append(a))
    monkeypatch.setattr(shc, "_hermes_finding", lambda *a, **k: hermes.append(a))
    monkeypatch.setattr(shc, "_send_telegram", lambda m: sent.append(m) or True)
    monkeypatch.setattr(shc, "_portfolio_drawdown_guard", lambda: None)
    monkeypatch.setattr(shc, "_log_health_event", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_pl_if_fired", lambda *a, **k: None)
    return shc.run(quiet=True), sent, siem, hermes


def test_three_orphaned_stops_send_one_batched_message(monkeypatch):
    alerts = [
        _alert("ANET", "fidelity rollover ira", {"orphaned"}),
        _alert("CSCO", "fidelity rollover ira", {"orphaned"}),
        _alert("QCOM", "fidelity rollover ira", {"orphaned"}),
    ]
    result, sent, siem, hermes = _run(monkeypatch, alerts)
    # one phone message, three durable evidence rows each
    assert len(sent) == 1
    msg = sent[0]
    assert "STOP HEALTH — 3 alert(s)" in msg
    assert "(3 urgent)" not in msg  # all-urgent omits the redundant count
    for sym in ("ANET", "CSCO", "QCOM"):
        assert sym in msg
    assert len(siem) == 3 and len(hermes) == 3
    assert result["telegram_fired"] == ["ANET:ORPHANED", "CSCO:ORPHANED", "QCOM:ORPHANED"]


def test_single_alert_keeps_the_single_card_shape(monkeypatch):
    result, sent, siem, hermes = _run(monkeypatch, [_alert("HRL", "taxable", {"orphaned"})])
    assert len(sent) == 1
    assert sent[0].startswith("🚨 STOP HEALTH — ORPHANED: *HRL*")
    assert len(siem) == 1 and len(hermes) == 1


def test_already_alerted_symbols_are_skipped_and_nothing_sends(monkeypatch):
    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor",
                        type("SLM", (), {"scan": staticmethod(lambda persist=True: {"summary": {"total": 1, "by_health": "alert"}, "alerts": [_alert("A", "a", {"orphaned"})]})}))
    monkeypatch.setattr(shc, "_recently_alerted", lambda sym, cond, hours=2: True)
    sent = []
    monkeypatch.setattr(shc, "_send_telegram", lambda m: sent.append(m) or True)
    monkeypatch.setattr(shc, "_siem", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_hermes_finding", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_portfolio_drawdown_guard", lambda: None)
    monkeypatch.setattr(shc, "_log_health_event", lambda *a, **k: None)
    shc.run(quiet=True)
    assert sent == []


def test_mixed_severity_header_counts_urgent_only(monkeypatch):
    alerts = [_alert("A", "a", {"orphaned"}), _alert("B", "b", {"oversized"}),
              _alert("C", "c", {"neared"})]  # neared → NEAR_TRIGGER (warning)
    _, sent, _, _ = _run(monkeypatch, alerts)
    assert len(sent) == 1
    assert "STOP HEALTH — 3 alert(s)" in sent[0] and "(2 urgent)" in sent[0]
