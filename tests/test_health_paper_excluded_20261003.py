"""Paper data never feeds the health agent (operator rule 2026-10-03: "This is all live data").

Alpaca/TOS paper and the tradeai_automated sandbox are training. Before this change four
paper_trades checks and the APPROVED_FOR_PAPER_TEST "stuck" check raised CRITICAL findings
(two of the live agent's four criticals on 2026-10-03) and paper_execution.log fed the
log-error scan. These tests pin that no paper input can raise a critical or move
overall_score.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import health_agent as ha  # noqa: E402

POLICY = {"penalties": {"critical": 40, "warning": 15, "info": 5}, "weights": {}}


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    stub = types.ModuleType("db_adapter")
    stub.USE_DB = False
    stub._execute = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "db_adapter", stub)


def _run(monkeypatch, findings):
    monkeypatch.setattr(ha, "COLLECTORS", [lambda: [dict(f) for f in findings]])
    return ha.compute(POLICY)


def _live_warning():
    return ha._f("data_quality", "live_thing_stale", "warning", "a live check")


@pytest.mark.parametrize("paper", [
    ha._f("execution_health", "approved_paper_test_stuck", "critical", "4 stuck in paper lane", count=4),
    ha._f("execution_health", "log_errors", "critical", "paper_execution.log: 9 errors", log="paper_execution.log"),
    ha._f("risk_protection", "anything", "critical", "paper position", lane="paper"),
])
def test_paper_finding_never_raises_a_critical_or_moves_the_score(monkeypatch, paper):
    base_overall, _, base_cats, _ = _run(monkeypatch, [_live_warning()])
    overall, status, cats, cat_findings = _run(monkeypatch, [_live_warning(), paper])
    assert overall == base_overall and cats == base_cats
    every = [f for fs in cat_findings.values() for f in fs]
    assert not any(f.get("severity") == "critical" for f in every)
    assert all(f.get("type") != paper["type"] or f.get("lane") != "paper" for f in every)


def test_live_finding_with_a_paper_sounding_name_still_counts(monkeypatch):
    live = ha._f("execution_health", "log_errors", "critical", "atm.log: 9 errors", log="atm.log")
    base_overall, *_ = _run(monkeypatch, [])
    overall, _, _, cat_findings = _run(monkeypatch, [live])
    assert overall < base_overall
    assert any(f.get("log") == "atm.log" for fs in cat_findings.values() for f in fs)


def test_collectors_no_longer_read_paper_stores():
    src = (ROOT / "scripts" / "health_agent.py").read_text(encoding="utf-8")
    assert "FROM paper_trades" not in src
    assert "status = 'APPROVED_FOR_PAPER_TEST'" not in src
    assert "'APPROVED_FOR_PAPER_TEST'" not in src


def test_policy_has_no_paper_inputs():
    policy = json.loads((ROOT / "config" / "health_agent_policy.json").read_text(encoding="utf-8"))
    assert "paper_execution.log" not in policy["log_errors"]["watch"]
    assert not any(k.startswith("approved_paper_stuck") for k in policy["proposal_pipeline"])
