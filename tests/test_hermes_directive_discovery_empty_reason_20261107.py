"""A run that staged nothing has to say why, in the receipt the grader reads.

WORK-QUEUE item 9, 2026-11-07: ``hermes-directive-discovery`` exited ok and staged nothing, and
``lib/run_quality.py`` could only report

    Ran live ... but produced nothing (summary.staged = 0; the receipt does not say why)

because the receipt carried ``{trend_directives, staged, skipped_stale}`` and nothing else. The
grader already knows how to read a stated reason — ``empty_reason`` / ``skip_reason`` /
``no_op_reason``, top level or summary — and grades a zero GOOD only when the reason is one of the
reviewed idle tokens in ``config/run_quality_idle_reasons.json``.

So the producer now counts *why* it staged nothing (hermes-disabled directives, stale directives,
matches that were already pending, matches beyond the per-directive cap) and states the reason. A
zero that is not idle (no directive, hermes disabled everywhere, no match at all) still says so in
words and stays EMPTY — the change explains a zero, it does not excuse one.

Hermetic: fake cursor and connection, ``_discover_for`` and ``_already_pending`` stubbed. No DB,
no network, no writes.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hermes_directive_discovery as hdd   # noqa: E402
from lib import run_quality as rq          # noqa: E402


class _Cur:
    def __init__(self, directives):
        self._directives = directives
        self.inserts = []

    def execute(self, sql, params=None):
        if "FROM watch_directives" in sql:
            self._rows = self._directives
        elif "INSERT INTO hermes_directive_hits_staging" in sql:
            self.inserts.append(params)
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, directives):
        self.cur = _Cur(directives)
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


@pytest.fixture
def fake_pipeline(monkeypatch):
    mod = types.ModuleType("research_critique_pipeline")
    mod.is_removal_flagged = lambda spec: False
    mod.load_critique_snapshot = lambda: {}
    monkeypatch.setitem(sys.modules, "research_critique_pipeline", mod)


def _run(monkeypatch, directives, cands_by_directive, pending=(), cap=15):
    """Run ``hdd.run(apply=True)`` against a fake connection; returns the report."""
    conn = _Conn(directives)
    monkeypatch.setattr(hdd, "_conn", lambda: conn)
    monkeypatch.setattr(hdd, "_discover_for", lambda cur, spec: dict(cands_by_directive))
    monkeypatch.setattr(hdd, "_already_pending", lambda cur, did, sym: sym in pending)
    report = hdd.run(apply=True, cap=cap)
    report["_conn"] = conn
    return report


DIRECTIVES = [(1, "AI datacenter", {"keywords": ["AI datacenter"]}, True),
              (2, "Hyperscale", {"keywords": ["hyperscale"]}, True)]
CANDS = {"AAA": ("research match", 0.7), "BBB": ("intel match", 0.5)}


def test_a_productive_run_states_no_empty_reason(monkeypatch, fake_pipeline):
    report = _run(monkeypatch, DIRECTIVES, CANDS)
    assert report["staged"] == 4 and "empty_reason" not in report
    summary = hdd._receipt_summary(report)
    assert "empty_reason" not in summary and summary["staged"] == 4


def test_everything_already_pending_is_the_reviewed_idle_token(monkeypatch, fake_pipeline):
    report = _run(monkeypatch, DIRECTIVES[:1], CANDS, pending=("AAA", "BBB"))
    assert report["staged"] == 0
    assert report["matched"] == 2 and report["already_pending"] == 2
    assert report["empty_reason"] == "no_new_input"

    receipt = {"summary": hdd._receipt_summary(report)}
    assert rq.stated_idle_reason(receipt) == "no_new_input"
    assert "no_new_input" in rq.idle_reasons()          # GOOD-if-idle, per config/run_quality_idle_reasons.json


def test_a_cap_only_zero_explains_the_cap(monkeypatch, fake_pipeline):
    report = _run(monkeypatch, DIRECTIVES[:1], CANDS, cap=0)
    assert report["staged"] == 0 and report["over_cap"] == 2
    assert report["empty_reason"] == "no_new_input"


def test_hermes_disabled_everywhere_is_not_idle(monkeypatch, fake_pipeline):
    disabled = [(1, "AI datacenter", {"keywords": ["AI datacenter"]}, False),
                (2, "Hyperscale", {"keywords": ["hyperscale"]}, False)]
    report = _run(monkeypatch, disabled, CANDS)
    assert report["hermes_disabled"] == 2 and report["staged"] == 0
    assert "hermes_enabled = false" in report["empty_reason"]
    assert report["empty_reason"] not in rq.idle_reasons()   # stays EMPTY, but now says why


def test_no_match_at_all_names_the_window_and_is_not_idle(monkeypatch, fake_pipeline):
    report = _run(monkeypatch, DIRECTIVES, {})
    assert report["matched"] == 0 and report["staged"] == 0
    assert "45 days" in report["empty_reason"] and "2 hermes-enabled" in report["empty_reason"]
    assert report["empty_reason"] not in rq.idle_reasons()


def test_no_directives_is_not_idle(monkeypatch, fake_pipeline):
    report = _run(monkeypatch, [], {})
    assert "no active trend directives" in report["empty_reason"]
    assert report["empty_reason"] not in rq.idle_reasons()


def test_the_receipt_summary_cannot_shadow_the_count(monkeypatch, fake_pipeline):
    """run_quality reads count keys in COUNT_KEYS order; ``candidates`` would outrank ``staged``."""
    report = _run(monkeypatch, DIRECTIVES, CANDS)
    summary = hdd._receipt_summary(report)
    assert "candidates" not in summary and "total" not in summary
    count, key = rq.item_count({"summary": summary})
    assert (count, key) == (4, "summary.staged")


def test_a_zero_stays_the_count_as_zero(monkeypatch, fake_pipeline):
    report = _run(monkeypatch, DIRECTIVES, CANDS, pending=("AAA", "BBB"))
    count, key = rq.item_count({"summary": hdd._receipt_summary(report)})
    assert (count, key) == (0, "summary.staged")
    assert rq.receipt_flags({"summary": hdd._receipt_summary(report)}) == []


def test_the_counters_are_in_the_report_and_the_receipt(monkeypatch, fake_pipeline):
    report = _run(monkeypatch, DIRECTIVES + [(3, "off", {}, False)], CANDS, pending=("BBB",))
    assert report["trend_directives"] == 3 and report["hermes_disabled"] == 1
    assert report["matched"] == 4 and report["already_pending"] == 2 and report["staged"] == 2
    summary = hdd._receipt_summary(report)
    for key in ("trend_directives", "hermes_disabled", "staged", "skipped_stale",
                "matched", "already_pending", "over_cap"):
        assert summary[key] == report[key]
    assert "detail" not in summary                    # the hit list stays out of the receipt
