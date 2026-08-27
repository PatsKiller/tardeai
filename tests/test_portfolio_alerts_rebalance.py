"""Tests for the daily rebalance alert's verify-before-notify gate.

Audit finding H1 (docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): the daily
drift-based rebalance alert (portfolio_alerts.py, >$200k trigger) was never
checked for SSDI/IRMAA/tax compliance by anything — the weekly gemma3-tier
verifier covers a completely separate table. build_rebalance_alert() closes
that gap by calling rebalance_verifier.verify_daily_rebalance_orders inline
before building the alert.

No test here reaches a real Anthropic API call — verify_daily_rebalance_orders
itself is monkeypatched at the import site.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_alerts as pa  # noqa: E402


def _rebal(total=250000, orders=None):
    return {"total_to_rebalance": total, "rebalance_orders": orders or []}


def test_clean_verification_produces_warning_severity(monkeypatch):
    monkeypatch.setattr(
        "rebalance_verifier.verify_daily_rebalance_orders",
        lambda orders, **kw: {"verification_passed": True, "critical_flags": []},
    )
    alert = pa.build_rebalance_alert(_rebal(total=250000))
    assert alert["type"] == "REBALANCE"
    assert alert["severity"] == "WARNING"
    assert "$250,000" in alert["msg"]
    assert "COMPLIANCE FLAG" not in alert["msg"]


def test_critical_flag_upgrades_severity_and_prepends_to_message(monkeypatch):
    monkeypatch.setattr(
        "rebalance_verifier.verify_daily_rebalance_orders",
        lambda orders, **kw: {"verification_passed": False,
                              "critical_flags": ["MAGI would exceed IRMAA threshold by $8,200"]},
    )
    alert = pa.build_rebalance_alert(_rebal(total=312000))
    assert alert["severity"] == "CRITICAL"
    assert "COMPLIANCE FLAG" in alert["msg"]
    assert "MAGI would exceed IRMAA threshold" in alert["msg"]
    # the underlying drift info must still be present, not replaced
    assert "$312,000" in alert["msg"]


def test_multiple_critical_flags_are_all_included(monkeypatch):
    monkeypatch.setattr(
        "rebalance_verifier.verify_daily_rebalance_orders",
        lambda orders, **kw: {"critical_flags": ["IRMAA risk", "SSDI earned-income risk"]},
    )
    alert = pa.build_rebalance_alert(_rebal())
    assert "IRMAA risk" in alert["msg"] and "SSDI earned-income risk" in alert["msg"]


def test_verification_failure_does_not_suppress_the_alert(monkeypatch):
    """A failed compliance check (network error, missing key, whatever) must
    never mean the operator stops getting the underlying drift alert — that
    would be a worse regression than the gap this fix closes."""
    def _boom(orders, **kw):
        raise RuntimeError("anthropic API unavailable")
    monkeypatch.setattr("rebalance_verifier.verify_daily_rebalance_orders", _boom)
    alert = pa.build_rebalance_alert(_rebal(total=205000))  # must not raise
    assert alert["type"] == "REBALANCE"
    assert alert["severity"] == "WARNING"
    assert "$205,000" in alert["msg"]


def test_skipped_verification_no_api_key_does_not_suppress_the_alert(monkeypatch):
    monkeypatch.setattr(
        "rebalance_verifier.verify_daily_rebalance_orders",
        lambda orders, **kw: {"skipped": True, "reason": "no_api_key"},
    )
    alert = pa.build_rebalance_alert(_rebal(total=205000))
    assert alert["severity"] == "WARNING"
    assert "COMPLIANCE FLAG" not in alert["msg"]


def test_orders_are_passed_through_to_the_verifier(monkeypatch):
    captured = {}

    def _capture(orders, **kw):
        captured["orders"] = orders
        captured["total_to_rebalance"] = kw.get("total_to_rebalance")
        return {"critical_flags": []}

    monkeypatch.setattr("rebalance_verifier.verify_daily_rebalance_orders", _capture)
    orders = [{"account": "Rollover IRA", "action": "SELL", "amount_usd": 250000}]
    pa.build_rebalance_alert(_rebal(total=250000, orders=orders))
    assert captured["orders"] == orders
    assert captured["total_to_rebalance"] == 250000


def test_generate_strategic_alerts_only_fires_above_threshold(monkeypatch):
    """Confirm the existing $200k gate is untouched by this change — the
    verify-before-notify check only runs (and only costs anything) when the
    alert would have fired anyway."""
    calls = []
    monkeypatch.setattr(
        "rebalance_verifier.verify_daily_rebalance_orders",
        lambda orders, **kw: calls.append(1) or {"critical_flags": []},
    )
    monkeypatch.setattr("portfolio_rebalancer.compute_rebalancing",
                        lambda portfolio: _rebal(total=150000))
    alerts = pa.generate_strategic_alerts(
        {"portfolio_totals": {"day_change": 0, "total_value": 1000000}, "holdings": []},
        {"critical_flags": []},
    )
    assert not any(a["type"] == "REBALANCE" for a in alerts)
    assert calls == []
