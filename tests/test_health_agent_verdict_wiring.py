"""The verdict path inside the live agent, exercised end to end.

The classifier is tested separately. What is tested here is that
`run_auto_remediation` actually USES it — that a command exiting 0 against an
unchanged condition produces `ok: False`, and that "Auto-fixed" is not printed.

PR #543 shipped broken past a test that only read source text, so nothing here
asserts on source. The agent is driven with a stubbed subprocess and a stubbed
`compute()`, and the assertions are on what it returns and what it would say.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

STALE = {
    "category": "data_freshness",
    "type": "portfolio_repricer_stale",
    "severity": "critical",
    "message": "portfolio repricer output stale",
    "age_hours": 24.0,
}

POLICY = {
    "auto_remediate": {
        "enabled": True,
        "cooldown_minutes": 0,
        "max_ineffective_attempts_verified": 2,
    },
    "remediation_map": {"portfolio_repricer_stale": "python3 scripts/portfolio_repricer.py"},
}


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    """The real module, with its durable writes redirected to tmp."""
    mod = importlib.import_module("health_agent")
    monkeypatch.setattr(mod, "REMEDIATION_LOG", tmp_path / "remediation.jsonl", raising=False)
    monkeypatch.setattr(mod, "REMEDIATION_STATE", tmp_path / "state.json", raising=False)
    return mod


def _stub_subprocess(monkeypatch, agent, returncode: int):
    class _P:
        def __init__(self, rc): self.returncode = rc
        def communicate(self, timeout=None): return ("", "")
        def kill(self): pass
    monkeypatch.setattr(agent.subprocess, "Popen",
                        lambda *a, **k: _P(returncode), raising=False)


def test_exit_zero_with_the_condition_still_firing_is_not_success(agent, monkeypatch):
    """The 2026-08-26 repricer shape, driven through the real function."""
    _stub_subprocess(monkeypatch, agent, 0)
    # The re-check still sees the same finding.
    monkeypatch.setattr(agent, "compute",
                        lambda policy: (50, "degraded", {}, {"data_freshness": [dict(STALE)]}),
                        raising=False)

    results = agent.run_auto_remediation(POLICY, [dict(STALE)])

    assert results, "the remediation should have been attempted"
    entry = results[0]
    assert entry["exit_code"] == 0, "the command really did exit 0"
    assert entry["ok"] is False, "exit 0 must not be reported as a fix"
    assert entry["outcome"] == "INEFFECTIVE"
    assert entry["verified_by_recheck"] is True


def test_exit_zero_with_the_condition_gone_is_success(agent, monkeypatch):
    _stub_subprocess(monkeypatch, agent, 0)
    monkeypatch.setattr(agent, "compute",
                        lambda policy: (95, "healthy", {}, {"data_freshness": []}),
                        raising=False)

    entry = agent.run_auto_remediation(POLICY, [dict(STALE)])[0]
    assert entry["outcome"] == "CLEARED"
    assert entry["ok"] is True


def test_a_regressing_metric_is_worsened(agent, monkeypatch):
    _stub_subprocess(monkeypatch, agent, 0)
    worse = dict(STALE, age_hours=36.0)
    monkeypatch.setattr(agent, "compute",
                        lambda policy: (30, "critical", {}, {"data_freshness": [worse]}),
                        raising=False)

    entry = agent.run_auto_remediation(POLICY, [dict(STALE)])[0]
    assert entry["outcome"] == "WORSENED"
    assert entry["ok"] is False
    assert entry.get("escalate"), "WORSENED must escalate on the first observation"
    assert entry["escalate"]["command_that_did_not_help"]


def test_an_unavailable_recheck_claims_nothing(agent, monkeypatch):
    """If the condition cannot be re-observed, no success may be claimed.

    Falling back to the exit code here would reintroduce the original defect.
    """
    _stub_subprocess(monkeypatch, agent, 0)
    def _boom(policy): raise RuntimeError("collector down")
    monkeypatch.setattr(agent, "compute", _boom, raising=False)

    entry = agent.run_auto_remediation(POLICY, [dict(STALE)])[0]
    assert entry["ok"] is False
    assert entry["outcome"] == "UNVERIFIED"


def test_a_failing_command_is_not_credited_by_a_coincidental_clear(agent, monkeypatch):
    _stub_subprocess(monkeypatch, agent, 1)
    monkeypatch.setattr(agent, "compute",
                        lambda policy: (95, "healthy", {}, {"data_freshness": []}),
                        raising=False)

    entry = agent.run_auto_remediation(POLICY, [dict(STALE)])[0]
    assert entry["outcome"] == "FAILED"
    assert entry["ok"] is False


def test_the_alert_does_not_say_auto_fixed_for_an_ineffective_remediation(agent, monkeypatch):
    """The operator-facing string is the thing that misled for 24 hours."""
    _stub_subprocess(monkeypatch, agent, 0)
    monkeypatch.setattr(agent, "compute",
                        lambda policy: (50, "degraded", {}, {"data_freshness": [dict(STALE)]}),
                        raising=False)
    results = agent.run_auto_remediation(POLICY, [dict(STALE)])

    # alert() sends rather than returns, so intercept the transport. Nothing is
    # sent: a skipped assertion here would be the same defect in miniature.
    sent: list[str] = []
    import types
    stub = types.ModuleType("telegram_alert")
    stub.send_telegram = lambda msg, *a, **k: sent.append(msg)
    monkeypatch.setitem(sys.modules, "telegram_alert", stub)
    # Rate-limit suppression is orthogonal to what is being asserted here.
    monkeypatch.setattr(agent, "_alert_suppressed", lambda *a, **k: False, raising=False)

    snapshot = {
        "status": "degraded", "overall_score": 50, "category_scores": {"data_freshness": 50},
        "findings": [dict(STALE)], "trends": [], "remediated": results,
    }
    agent.alert({"alert": {"telegram_on_status": ["degraded"]}}, snapshot)

    assert sent, "alert() should have produced a message"
    text = sent[0]
    assert "Auto-fixed" not in text, "an ineffective remediation must not be announced as fixed"
    assert "ineffective" in text.lower()
    assert "portfolio_repricer.py" in text, "the operator needs the command that did not help"
