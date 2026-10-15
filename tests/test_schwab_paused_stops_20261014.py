"""Schwab paused (incident 2026-10-14) — B: Schwab stop data UNAVAILABLE is reported, never read as "0 stops".

Before: stop_lifecycle_monitor._schwab_stops() swallowed every error (bare except) into [], the snapshot held
0 Schwab stops, and stop_health_check logged ok=True while the Schwab stops were not being read.
Fakes only: no database, no broker, Telegram captured at the transport.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import stop_health_check as shc  # noqa: E402
import stop_lifecycle_monitor as slm  # noqa: E402
from lib import stop_monitoring_health as smh  # noqa: E402

# Alarm-firing coverage: the DEGRADED page is observed at the real transport (alarm_capture) below.
COVERS = ["scripts/stop_health_check.py"]

_STOP = {"orderId": 1, "status": "WORKING", "orderType": "STOP", "stopPrice": 90.0,
         "orderLegCollection": [{"instruction": "SELL", "quantity": 10, "instrument": {"symbol": "NVDA"}}]}


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return self._rows


def _fake_schwab(monkeypatch, answer):
    calls: list[str] = []

    def get_orders_raw(acct):
        calls.append(acct)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setitem(sys.modules, "schwab_transport", types.SimpleNamespace(get_orders_raw=get_orders_raw))
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(
        _get_conn=lambda: types.SimpleNamespace(cursor=lambda: _Cur([("schwab_taxable",), ("schwab_roth_ira",)]))))
    return calls


# ── stop_lifecycle_monitor._schwab_stops ────────────────────────────────────

def test_forbidden_returns_unavailable_without_calling_schwab(monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    calls = _fake_schwab(monkeypatch, [_STOP])
    out = slm._schwab_stops()
    assert isinstance(out, slm.SchwabStopsUnavailable) and out.paused and out.status == "UNAVAILABLE"
    assert calls == []


@pytest.mark.parametrize("answer", [
    {"status": "error", "error": "Schwab rejected the login token (HTTP 401)"},
    RuntimeError("401 Client Error: Unauthorized"),
])
def test_a_401_returns_unavailable_not_empty_list(monkeypatch, answer):
    _fake_schwab(monkeypatch, answer)
    out = slm._schwab_stops()
    assert out != [] and isinstance(out, slm.SchwabStopsUnavailable)
    assert out.failed_accounts == ["schwab_taxable", "schwab_roth_ira"] and not out.paused


def test_a_clean_read_still_returns_the_list(monkeypatch):
    _fake_schwab(monkeypatch, [_STOP])
    out = slm._schwab_stops()
    assert isinstance(out, list) and len(out) == 2 and out[0]["symbol"] == "NVDA"


def _scan_unavailable(monkeypatch):
    monkeypatch.setenv("TRADEAI_SCHWAB_ACCESS_MODE", "forbidden")
    for name in ("_alpaca_stops", "_manual_stops"):
        monkeypatch.setattr(slm, name, lambda: [])
    monkeypatch.setattr(slm, "_holdings_map", lambda: {})
    monkeypatch.setattr(slm, "_alpaca_positions_map", lambda: {})
    return slm.scan(persist=False)


def test_scan_carries_the_unavailable_marker(monkeypatch):
    res = _scan_unavailable(monkeypatch)
    assert res["schwab_stops_status"] == "UNAVAILABLE"
    assert res["summary"]["schwab_stops"]["status"] == "UNAVAILABLE" and res["summary"]["schwab_stops"]["paused"]


# ── stop_health_check: DEGRADED, P1, not ok ─────────────────────────────────

def _health(monkeypatch, res, sent=None):
    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor",
                        types.SimpleNamespace(scan=lambda persist=True: res))
    monkeypatch.setattr(shc, "_recently_alerted", lambda sym, cond, hours=2: False)
    monkeypatch.setattr(shc, "_alerted_since", lambda *a, **k: False)
    # ZETA 2026-10-15 last-known fallback: hermetic (no DB, no holdings.json) — covered in its own test file.
    monkeypatch.setattr(shc, "_last_known_blind_alerts", lambda res, **k: {"stops": [], "findings": [], "sent": []})
    from lib import last_known_stops as _lks
    monkeypatch.setattr(_lks, "holdings_quotes", lambda path=None: {})
    monkeypatch.setattr(shc, "_siem", lambda *a, **k: None)
    monkeypatch.setattr(shc, "_portfolio_drawdown_guard", lambda: None)
    monkeypatch.setattr(shc, "_log_health_event", lambda *a, **k: None)
    if sent is not None:
        monkeypatch.setattr(shc, "_send_telegram", lambda m, **k: sent.append((m, k)) or "1")


def _unavailable_res():
    return {"generated_at": "2026-10-14T19:10:00+00:00", "stops": [], "alerts": [],
            "schwab_stops_status": "UNAVAILABLE",
            "summary": {"total": 0, "by_health": {"ok": 0, "warn": 0, "alert": 0},
                        "schwab_stops": {"status": "UNAVAILABLE", "reason": "schwab_read_failed: HTTP 401",
                                         "failed_accounts": ["schwab_taxable"], "paused": False}}}


def test_unavailable_reports_degraded_p1_not_ok(monkeypatch):
    sent: list = []
    _health(monkeypatch, _unavailable_res(), sent)
    out = shc.run(quiet=True)
    assert out["ok"] is False and out["status"] == "DEGRADED"
    assert len(sent) == 1
    msg, kw = sent[0]
    assert "Schwab stop data unavailable — stops at Schwab are NOT being monitored" in msg
    assert kw.get("priority") == "P1"           # declared intent: never digested, never quiet-held
    assert "SCHWAB:SCHWAB_STOPS_UNAVAILABLE" in out["telegram_fired"]


def test_unavailable_reaches_the_transport_through_the_real_router(alarm_capture, monkeypatch):
    _health(monkeypatch, _unavailable_res())
    shc.run(quiet=True)
    alarm_capture.assert_fired(contains="Schwab stop data unavailable")


def test_heartbeat_says_degraded(monkeypatch, tmp_path):
    _health(monkeypatch, _unavailable_res(), [])
    hb = tmp_path / "hb.json"
    shc.main(["--quiet"], heartbeat_path=hb)
    import json
    doc = json.loads(hb.read_text())
    assert doc["status"] == "degraded" and doc["schwab_stops"]["status"] == "UNAVAILABLE"


def test_a_clean_scan_is_not_degraded(monkeypatch):
    res = _unavailable_res()
    res["schwab_stops_status"] = "ok"
    res["summary"]["schwab_stops"] = {"status": "ok"}
    sent: list = []
    _health(monkeypatch, res, sent)
    out = shc.run(quiet=True)
    assert out["ok"] is True and out["summary"]["degraded"] is None and sent == []


def test_recovery_refuses_a_scan_blind_to_schwab():
    from datetime import datetime, timezone
    res = _unavailable_res()
    res["stops"] = [{"account": "alpaca", "symbol": "X", "health": "ok"}]
    res["summary"]["total"] = 1
    out = shc._recover_current_scan(res, datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert out == {"ok": False, "resolved_ids": [], "reason": "incomplete_scan"}


# ── stop_monitoring_health: unknown, not "naked" ────────────────────────────

def test_monitoring_health_treats_schwab_holdings_as_unknown(monkeypatch):
    res = _unavailable_res()
    monkeypatch.setitem(sys.modules, "stop_lifecycle_monitor", types.SimpleNamespace(scan=lambda persist=True: res))
    monkeypatch.setattr(smh, "_EXEMPT_ACCOUNTS", frozenset())   # prove the guard, not the exemption list
    monkeypatch.setattr(smh, "_holdings_rows", lambda: [
        {"symbol": "NVDA", "account": "schwab_taxable", "shares": 10},
        {"symbol": "ANET", "account": "fidelity_rollover_ira", "shares": 5}])
    monkeypatch.setattr(smh, "_stale_advisory_symbols", lambda: [])
    monkeypatch.setattr(smh, "_snapshot_age_minutes", lambda: None)
    monkeypatch.setattr(smh, "_is_stop_eligible", lambda s, a: True)
    diag = smh.diagnose(persist_scan=False)
    kinds = {(i["kind"], i["detail"]) for i in diag["issues"]}
    assert ("naked_position", "NVDA@schwab_taxable") not in kinds
    assert ("naked_position", "ANET@fidelity_rollover_ira") in kinds     # Fidelity is still checked
    assert diag["stop_status_unknown"] == ["NVDA@schwab_taxable"]
    assert any(k == "schwab_stops_unavailable" for k, _ in kinds)
