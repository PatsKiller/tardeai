"""The integrity sweep's alarm must be OBSERVED firing, not assumed to.

AGENTS.md: an alarm that has never been observed firing is indistinguishable
from its absence. `tests/test_alarm_coverage.py` enforces that as a gate, and it
caught this omission on 2026-09-06 — I added a `send_telegram` call site in
run_integrity_checks.py with no firing test, in the same session that documented
the rule. The gate was right.

These tests call main() with a stubbed sender and assert on what it would send:
that P0/P1 findings reach the operator, that P2-only stays quiet, and that the
message says the sweep repaired nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = [
    "scripts/run_integrity_checks.py",
]


def _runner():
    spec = importlib.util.spec_from_file_location(
        "run_integrity_checks", ROOT / "scripts" / "run_integrity_checks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sent(monkeypatch):
    """Capture what would reach Telegram, without a network or a token."""
    out: list[str] = []
    import telegram_alert
    monkeypatch.setattr(telegram_alert, "send_telegram",
                        lambda msg, *a, **k: out.append(msg) or True)
    return out


def _report(findings):
    return {"findings": findings,
            "counts": {"P0": sum(1 for f in findings if f["severity"] == "P0"),
                       "P1": sum(1 for f in findings if f["severity"] == "P1"),
                       "P2": sum(1 for f in findings if f["severity"] == "P2")},
            "as_of": "2026-09-06T00:00:00+00:00", "ok": not findings}


def _run(mod, monkeypatch, findings, argv):
    monkeypatch.setattr(mod, "_conn", lambda: None)
    import lib.deterministic_integrity as DI
    monkeypatch.setattr(DI, "run_all", lambda **kw: _report(findings))
    monkeypatch.setattr(sys, "argv", ["run_integrity_checks.py", *argv])
    return mod.main()


def test_a_p0_finding_reaches_the_operator(sent, monkeypatch):
    """The one that matters: a consumer inner-joining an empty producer, which
    cost 30 days of CIO decisions before anything said so."""
    mod = _runner()
    rc = _run(mod, monkeypatch, [{
        "check": "join_input_empty", "severity": "P0",
        "subject": "strategy_rule_evaluations",
        "detail": "cio_decision_engine INNER JOINs it, 0 rows",
        "remediation": "schedule the producer"}], ["--alert"])
    assert rc == 0
    assert sent, "a P0 finding did not reach the operator"
    assert "join_input_empty" in sent[0]
    assert "strategy_rule_evaluations" in sent[0]


def test_a_p1_finding_reaches_the_operator(sent, monkeypatch):
    mod = _runner()
    _run(mod, monkeypatch, [{
        "check": "producer_unscheduled", "severity": "P1",
        "subject": "build_catalyst_graph.py",
        "detail": "no active cron and no timer",
        "remediation": "schedule it"}], ["--alert"])
    assert sent and "build_catalyst_graph.py" in sent[0]


def test_p2_only_does_not_page(sent, monkeypatch):
    """309 latent findings are a debt, not an outage. Paging on them is how an
    alarm becomes ignorable — the failure this whole sweep exists to avoid."""
    mod = _runner()
    _run(mod, monkeypatch, [{
        "check": "tree_relative_secret", "severity": "P2",
        "subject": "309 files", "detail": "latent", "remediation": "fix as a class"}],
        ["--alert"])
    assert sent == [], "a P2-only sweep must not page"


def test_a_clean_sweep_is_silent(sent, monkeypatch):
    mod = _runner()
    _run(mod, monkeypatch, [], ["--alert"])
    assert sent == []


def test_without_alert_nothing_is_sent(sent, monkeypatch):
    """The default run is a report. Sending must be opt-in, or a cron that only
    meant to collect starts paging."""
    mod = _runner()
    _run(mod, monkeypatch, [{
        "check": "join_input_empty", "severity": "P0", "subject": "x",
        "detail": "d", "remediation": "r"}], [])
    assert sent == []


def test_the_message_says_nothing_was_repaired(sent, monkeypatch):
    """The sweep reports and never fixes. An operator must not read a finding and
    assume it was handled — the taxonomy_tagger 'fix' would have destroyed a
    32,060-row corpus."""
    mod = _runner()
    _run(mod, monkeypatch, [{
        "check": "producer_unscheduled", "severity": "P1", "subject": "x",
        "detail": "d", "remediation": "r"}], ["--alert"])
    assert sent
    assert "repaired" in sent[0].lower() or "reports only" in sent[0].lower()


def test_a_send_failure_is_reported_not_swallowed(monkeypatch):
    """Exit 2 = the check ran, the notify did not. Returning 0 would make a dead
    Telegram lane look like a clean sweep."""
    mod = _runner()
    import telegram_alert

    def _boom(msg, *a, **k):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(telegram_alert, "send_telegram", _boom)
    rc = _run(mod, monkeypatch, [{
        "check": "join_input_empty", "severity": "P0", "subject": "x",
        "detail": "d", "remediation": "r"}], ["--alert"])
    assert rc == 2
