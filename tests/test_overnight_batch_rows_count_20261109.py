"""LQ-20261107-1539 — overnight_batch must report what it produced, or None if it did not measure.

The operator got a CRITICAL email at 08:30 ET on 2026-11-09:

    overnight_batch_tax -- 2 runs with rows_produced=0 in 24h

It was false. The 06:35 sweep had queued 4 tax_agent jobs (watchlist_agent_jobs,
submitted_from='tax_sweep'). The `__main__` block ran `run_tax_sweep()` and threw away its
return value, then wrote `_count = 0` anyway. Same shape in `--index-embeddings` and the
default `run()`. `--outcomes` was worse: it read `_result.get('scored', 0)`, a key
`evaluate_past_decisions()` never returns (it returns {"updated", "lessons"}), so that branch
reported 0 on every run too.

0 and None are different facts (pipeline_registry.run_complete docstring): `pipeline_zero_rows`
counts only `(summary->>'rows_produced')::bigint = 0`, and a JSON null becomes -1 there — so a
null can never be read as a dark pipeline, and a hardcoded 0 can never stop firing.

Everything here is stubbed: no DB, no holdings, no network, no Telegram.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "overnight_batch.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("overnight_batch_1539", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ob():
    return _load_module()


class _Registry:
    """Records the row count each run reports, without touching the DB."""

    def __init__(self):
        self.started = []
        self.completed = []
        self.failed = []

    def run_start(self, mode):
        self.started.append(mode)
        return 1

    def run_complete(self, run_id, rows_processed=None):
        self.completed.append((run_id, rows_processed))

    def run_fail(self, run_id, message=""):
        self.failed.append((run_id, message))

    @property
    def rows(self):
        assert self.completed, "run_complete was never called"
        return self.completed[-1][1]


@pytest.fixture()
def registry(monkeypatch):
    reg = _Registry()
    fake = types.ModuleType("pipeline_registry")
    fake.run_start = reg.run_start
    fake.run_complete = reg.run_complete
    fake.run_fail = reg.run_fail
    monkeypatch.setitem(sys.modules, "pipeline_registry", fake)
    return reg


def test_tax_sweep_reports_the_jobs_it_queued(ob, registry, monkeypatch):
    """The operator's false CRITICAL: 4 jobs queued, 0 reported."""
    monkeypatch.setattr(ob, "run_tax_sweep", lambda: 4)

    ob.main(["--tax-sweep"])

    assert registry.started == ["overnight_batch_tax"]
    assert registry.rows == 4, "a branch that queued 4 jobs must not report 0"


def test_a_tax_sweep_that_measured_nothing_reports_a_real_zero(ob, registry, monkeypatch):
    """A measured 0 is a fact and stays 0 — the alarm is allowed to see it."""
    monkeypatch.setattr(ob, "run_tax_sweep", lambda: 0)

    ob.main(["--tax-sweep"])

    assert registry.rows == 0


def test_a_branch_that_cannot_measure_reports_none_not_zero(ob, registry, monkeypatch):
    """None is "nobody told me"; it must survive to run_complete unchanged."""
    monkeypatch.setattr(ob, "run_tax_sweep", lambda: None)

    ob.main(["--tax-sweep"])

    assert registry.rows is None, "an unmeasured branch must not claim it produced nothing"


def test_outcomes_reports_its_own_key_not_a_missing_one(ob, registry, monkeypatch):
    """evaluate_past_decisions returns {"updated", "lessons"}; 'scored' was never there."""
    monkeypatch.setattr(
        ob, "evaluate_past_decisions",
        lambda: {"updated": 3, "lessons": ["a lesson"]},
    )

    ob.main(["--outcomes"])

    assert registry.rows == 3, "the branch read a key the producer never returns"


def test_index_embeddings_reports_the_indexed_count(ob, registry, monkeypatch):
    """batch_index_all returns {"indexed": N, "model": ..., "dim": ...}; the count was discarded."""
    fake = types.ModuleType("content_scoring")
    fake.batch_index_all = lambda batch_size=50: {"indexed": 7, "model": "x", "dim": 384}
    monkeypatch.setitem(sys.modules, "content_scoring", fake)

    ob.main(["--index-embeddings"])

    assert registry.rows == 7


def test_index_embeddings_without_a_count_is_not_measured(ob, registry, monkeypatch):
    fake = types.ModuleType("content_scoring")
    fake.batch_index_all = lambda batch_size=50: {"model": "x"}
    monkeypatch.setitem(sys.modules, "content_scoring", fake)

    ob.main(["--index-embeddings"])

    assert registry.rows is None


def test_the_default_batch_reports_the_jobs_it_queued(ob, registry, monkeypatch):
    monkeypatch.setattr(
        ob, "run",
        lambda send_telegram=False: {
            "metrics": {},
            "tier1": {"jobs_queued": 3},
            "tier2": {"jobs_queued": 2},
        },
    )

    ob.main([])

    assert registry.started == ["overnight_batch"]
    assert registry.rows == 5


def test_the_default_batch_without_tier_counts_is_not_measured(ob, registry, monkeypatch):
    monkeypatch.setattr(ob, "run", lambda send_telegram=False: {"metrics": {}})

    ob.main([])

    assert registry.rows is None


def test_research_and_proactive_keep_reporting_their_counts(ob, registry, monkeypatch):
    """These two already measured; the shared helper must not turn a real count into None."""
    monkeypatch.setattr(ob, "refresh_research_topics", lambda: {"refreshed": 11, "total": 30})
    ob.main(["--research"])
    assert registry.rows == 11

    monkeypatch.setattr(
        ob, "proactive_intel_scan",
        lambda: {"scanned": 5, "debated": 1, "queued": 2, "throttled": 0, "event_retries": 0},
    )
    ob.main(["--proactive"])
    assert registry.rows == 2


def test_a_failing_branch_is_closed_as_failed_and_the_count_is_never_written(ob, registry, monkeypatch):
    def boom():
        raise RuntimeError("no holdings")

    monkeypatch.setattr(ob, "run_tax_sweep", boom)

    with pytest.raises(RuntimeError):
        ob.main(["--tax-sweep"])

    assert registry.failed and registry.failed[-1][1] == "no holdings"
    assert registry.completed == [], "a failed run must not also record a success row count"
