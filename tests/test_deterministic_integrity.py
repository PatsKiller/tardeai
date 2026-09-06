"""The daily sweep that would have found what took a full session by hand.

Every check here exists because the defect it detects was real on 2026-09-06 and
had been silently true for weeks or months. Run cold against origin/main, the
engine independently rediscovered all of them plus one more (db_retention
unscheduled).

It reports and does not repair — deliberately. Re-enabling taxonomy_tagger, the
"obvious" fix for one of these findings, would have foreclosed a 32,060-row
corpus. An auto-fixer would have taken that action.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import deterministic_integrity as DI  # noqa: E402


# ── it must never repair ───────────────────────────────────────────────────

def test_the_engine_does_not_write_or_execute():
    """A check that acts is another thing nobody is watching."""
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text(encoding="utf-8")
    for banned in ("INSERT INTO", "UPDATE ", "DELETE FROM", "os.remove",
                   "shutil.rmtree", "crontab -", "write_text("):
        assert banned not in src, f"the engine must not repair: found {banned!r}"


def test_no_model_in_the_engine():
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text(encoding="utf-8")
    low = src.lower()
    for banned in ("openai", "anthropic", "deepseek", "grok", "completion", "prompt"):
        assert banned not in low, f"deterministic engine referenced {banned}"


# ── a commented cron is not scheduled ──────────────────────────────────────

def test_a_commented_cron_is_not_scheduled():
    """taxonomy_tagger sat commented for two months and every filename grep
    reported it as present."""
    cron = "# 20 * * * * python3 scripts/taxonomy_tagger.py --all\n"
    assert DI.is_scheduled("taxonomy_tagger.py", cron=cron, timers="") is False


def test_an_active_cron_is_scheduled():
    cron = "20 * * * * python3 scripts/taxonomy_tagger.py --all\n"
    assert DI.is_scheduled("taxonomy_tagger.py", cron=cron, timers="") is True


def test_a_systemd_timer_counts():
    assert DI.is_scheduled("mint_identity_registry.py", cron="",
                           timers="mint_identity_registry.timer") is True


def test_commented_only_is_reported_distinctly(monkeypatch):
    """'Present as a comment' is more deceptive than absent, and gets its own
    check so the remediation can say so."""
    monkeypatch.setattr(DI, "_crontab",
                        lambda: "# 20 * * * * python3 scripts/taxonomy_tagger.py\n")
    out = DI.check_commented_out_crons(["taxonomy_tagger.py"])
    assert out and out[0]["check"] == "cron_commented_out"


def test_an_active_line_suppresses_the_commented_finding(monkeypatch):
    monkeypatch.setattr(
        DI, "_crontab",
        lambda: "# old\n20 * * * * python3 scripts/taxonomy_tagger.py --all\n")
    assert DI.check_commented_out_crons(["taxonomy_tagger.py"]) == []


# ── populations are aggregated, not shouted ────────────────────────────────

def test_population_checks_collapse_to_one_finding():
    """309 tree-relative .env findings emitted individually is an alert nobody
    reads. AGENTS.md: a mechanical sweep is a candidate generator, not a count."""
    many = [DI._finding("tree_relative_secret", DI.P1, f"f{i}.py", "d", "fix")
            for i in range(50)]
    out = DI._aggregate(many)
    assert len(out) == 1
    assert "50" in out[0]["detail"]
    assert out[0]["severity"] == DI.P2, "a latent population is a debt, not an outage"


def test_incident_checks_are_not_aggregated():
    one = [DI._finding("producer_unscheduled", DI.P1, "x.py", "d", "fix")]
    assert DI._aggregate(one) == one


# ── the empty-join check, which is the 30-day CIO outage ───────────────────

class _FakeCur:
    def __init__(self, n): self.n = n
    def execute(self, *a, **k): pass
    def fetchone(self): return (self.n,)


class _FakeConn:
    def __init__(self, n): self._n = n
    def cursor(self): return _FakeCur(self._n)


def test_an_empty_join_input_is_p0():
    """cio_decision_engine INNER JOINed a 0-row table and reported success on
    3,010 runs a week for 30 days."""
    out = DI.check_empty_join_inputs(_FakeConn(0),
                                     [("cio_decision_engine", "strategy_rule_evaluations")])
    assert out and out[0]["severity"] == DI.P0


def test_a_populated_join_input_is_silent():
    assert DI.check_empty_join_inputs(_FakeConn(2716),
                                      [("cio_decision_engine", "strategy_rule_evaluations")]) == []


# ── docstrings must not satisfy a check ────────────────────────────────────

def test_checks_read_code_not_prose():
    """Three guards this session passed on a comment describing the defect."""
    src = (ROOT / "scripts" / "lib" / "deterministic_integrity.py").read_text(encoding="utf-8")
    assert "_code_only" in src
    stripped = DI._code_only('def f():\n    """rows_processed: int = 0 in a docstring"""\n    return 1\n')
    assert "rows_processed" not in stripped


def test_exit_status_is_not_the_alarm_channel():
    """Findings live in the report. Exit 0 = the check ran, so systemd cannot
    confuse a crashed sweep with a sweep that found something."""
    runner = (ROOT / "scripts" / "run_integrity_checks.py").read_text(encoding="utf-8")
    assert "the CHECK ran" in runner or "check ran" in runner.lower()
    assert "return 0" in runner
