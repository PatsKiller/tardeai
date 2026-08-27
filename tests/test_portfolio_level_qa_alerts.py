"""Tests for the portfolio-level QA critical-violation and crash alert path.

Audit finding C5 (docs/audits/CIO_PLATFORM_AUDIT_2026-08-27.md): a live
core_compounders hard-cap breach (86.1-86.2% against a 40-60% target),
tagged `severity: critical` in code, was logged to logs/portfolio_qa.log
and portfolio_intelligence_events across multiple consecutive daily runs
with nothing forwarding it to a human. A separate FileNotFoundError on a
missing .env also killed a run entirely, silently.

Pure: `alert_critical_violations`/`_alert_crash` take a result dict / an
exception and call the already-normalized `telegram_alert.send_telegram`
chokepoint, which is monkeypatched here rather than actually sent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_level_qa as qa  # noqa: E402


def _violation(group="core_compounders", actual=86.1, hard_cap=60.0, severity="critical"):
    return {"group": group, "actual": actual, "hard_cap": hard_cap, "severity": severity}


def test_no_critical_violations_sends_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr("telegram_alert.send_telegram", lambda msg: calls.append(msg) or True)
    sent = qa.alert_critical_violations({"group_cap_violations": [], "qa_summary": "ok"})
    assert sent is False
    assert calls == []


def test_warning_severity_alone_does_not_alert(monkeypatch):
    """Only `critical` (hard-cap) violations page a human; `warning` (soft
    target drift) stays log-only — that distinction is deliberate, not a gap."""
    calls = []
    monkeypatch.setattr("telegram_alert.send_telegram", lambda msg: calls.append(msg) or True)
    result = {"group_cap_violations": [_violation(severity="warning")], "qa_summary": "ok"}
    sent = qa.alert_critical_violations(result)
    assert sent is False
    assert calls == []


def test_reproduces_the_core_compounders_hard_cap_incident(monkeypatch):
    """The actual audit finding: core_compounders at 86.1% against a hard
    cap, tagged critical, must now reach send_telegram."""
    calls = []
    monkeypatch.setattr("telegram_alert.send_telegram", lambda msg: calls.append(msg) or True)
    result = {
        "group_cap_violations": [_violation(group="core_compounders", actual=86.1, hard_cap=60.0)],
        "qa_summary": "Portfolio $1,250,000. Income $52,000/yr (95% of target). 1 group violations.",
    }
    sent = qa.alert_critical_violations(result)
    assert sent is True
    assert len(calls) == 1
    assert "core_compounders" in calls[0]
    assert "86.1" in calls[0]
    assert "60" in calls[0]


def test_multiple_critical_violations_are_all_named(monkeypatch):
    calls = []
    monkeypatch.setattr("telegram_alert.send_telegram", lambda msg: calls.append(msg) or True)
    result = {"group_cap_violations": [
        _violation(group="core_compounders", actual=86.1, hard_cap=60.0),
        _violation(group="speculative_growth", actual=42.0, hard_cap=25.0),
    ]}
    sent = qa.alert_critical_violations(result)
    assert sent is True
    assert "core_compounders" in calls[0] and "speculative_growth" in calls[0]


def test_alert_delivery_failure_does_not_raise(monkeypatch):
    """A failed Telegram send must not fail the QA run — but it must not go
    fully silent either (printed, not swallowed without a trace)."""
    def _boom(msg):
        raise RuntimeError("telegram down")
    monkeypatch.setattr("telegram_alert.send_telegram", _boom)
    result = {"group_cap_violations": [_violation()], "qa_summary": "ok"}
    sent = qa.alert_critical_violations(result)  # must not raise
    assert sent is False


def test_missing_telegram_module_does_not_raise(monkeypatch):
    """If telegram_alert can't even be imported, alerting must fail closed,
    not crash the QA evaluation that called it."""
    import builtins
    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name == "telegram_alert":
            raise ImportError("no telegram_alert")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    result = {"group_cap_violations": [_violation()], "qa_summary": "ok"}
    sent = qa.alert_critical_violations(result)
    assert sent is False


def test_crash_alert_calls_send_telegram_with_exception_detail(monkeypatch):
    calls = []
    monkeypatch.setattr("telegram_alert.send_telegram", lambda msg: calls.append(msg) or True)
    qa._alert_crash(FileNotFoundError("[Errno 2] No such file: '.env'"))
    assert len(calls) == 1
    assert "portfolio_level_qa.py CRASHED" in calls[0]
    assert "FileNotFoundError" in calls[0]
    assert ".env" in calls[0]


def test_crash_alert_never_raises_even_if_telegram_itself_fails(monkeypatch):
    def _boom(msg):
        raise RuntimeError("telegram down")
    monkeypatch.setattr("telegram_alert.send_telegram", _boom)
    qa._alert_crash(FileNotFoundError("boom"))  # must not raise
