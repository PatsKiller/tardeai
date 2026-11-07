"""ANCHOR: ORCHESTRATOR_STAGE_ISOLATION_LQ225_20261107. LQ-20261107-225 — a stage that
cannot run must not take the whole pipeline with it.

Measured 2026-11-07: ``ticker_snapshot_daily`` last wrote **2026-11-03** and
``candidate_setup_advisory`` (whose ``snapshot_date`` is inherited from it) last carried
that same date.  The producer is ``portfolio_orchestrator.py`` (cron ``15 7 * * 1-5``).
Its log shows the run dying at ``[2/10] Analytics`` on 2026-11-04, 11-05 and 11-06 with
``AttributeError: 'NoneType' object has no attribute 'upper'`` — a holding whose
``asset_type`` is null.  The crash itself is fixed (LQ-20261107-72 / FU-007, 2026-11-07);
what is pinned here is why three dead runs left nothing behind:

* stages 2-5 (analytics, tax, rebalancing, risk) were the only BARE calls in the pipeline,
  so an exception there killed the process before ``_report_stage_failures`` could write
  ``orchestrator_stage_failures.json`` or send the alert — every later stage, including
  the snapshot persistence, was lost and the first signal was a staleness warning on
  /v3/health four days later;
* a run that dies outside the registry must still leave that durable record.

Hermetic: no database, no network, no pipeline run.  The live proof is Monday's 07:15 run
(see the DONE note) — the pipeline writes durable state and cannot be run from here.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_orchestrator as po  # noqa: E402

SOURCE = (ROOT / "scripts" / "portfolio_orchestrator.py").read_text()
TREE = ast.parse(SOURCE)


@pytest.fixture(autouse=True)
def _clean():
    po._STAGE_FAILURES.clear()
    po._DEGRADATIONS.clear()
    yield
    po._STAGE_FAILURES.clear()
    po._DEGRADATIONS.clear()


def _pipeline_fn():
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "run_portfolio_pipeline":
            return node
    raise AssertionError("run_portfolio_pipeline is gone — this file pins its stage wiring")


def _calls(node, name):
    return [c for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == name]


# ── the isolation property: a stage failure is recorded, not raised ─────────────────────────────────────────

def test_a_failing_stage_returns_the_default_instead_of_killing_the_run():
    """The 2026-11-04..06 shape: analyze_concentration raised, and nothing after it ran."""
    def boom():
        raise AttributeError("'NoneType' object has no attribute 'upper'")

    assert po._run_stage("analytics", boom, default={}) == {}
    f = po._STAGE_FAILURES[-1]
    assert f["stage"] == "analytics"
    assert f["error_type"] == "AttributeError", "the TYPE is what identifies the crash"
    assert "upper" in f["error"]


def test_a_healthy_stage_is_returned_unchanged_with_its_arguments():
    seen = {}

    def fn(first, second=None, **kw):
        seen.update(first=first, second=second, kw=kw)
        return {"flag_count": {"HIGH": 2}}

    out = po._run_stage("rebalancing", fn, "portfolio", "state_dir", extra=1)
    assert out == {"flag_count": {"HIGH": 2}}
    assert seen == {"first": "portfolio", "second": "state_dir", "kw": {"extra": 1}}
    assert po._STAGE_FAILURES == []


def test_the_default_is_the_exact_object_the_caller_passed():
    """Downstream stages call `.get(...)` on these; a wrapper that invented `None` would move the crash."""
    default = {}
    assert po._run_stage("risk", lambda: 1 / 0, default=default) is default


def test_a_failure_through_the_wrapper_reaches_the_durable_artifact_and_the_alert(tmp_path, monkeypatch):
    """The evidence a dead run never produced on 11-04..06."""
    sent = []
    monkeypatch.setitem(sys.modules, "telegram_alert", type(
        "M", (), {"send_telegram": staticmethod(lambda m, **kw: sent.append(m))}))

    po._run_stage("analytics", lambda: (_ for _ in ()).throw(AttributeError("boom")), default={})

    assert po._report_stage_failures(tmp_path) == 1
    art = json.loads((tmp_path / "orchestrator_stage_failures.json").read_text())
    assert art["failure_count"] == 1
    assert art["failures"][0]["stage"] == "analytics"
    assert sent and "analytics" in sent[0]


# ── the wiring: stages 2-5 use the registry, and the snapshot write stays in the run ─────────────────────────

def test_stages_two_to_five_go_through_the_stage_registry():
    """They were bare calls; that is how one AttributeError cost four days of output."""
    pipeline = _pipeline_fn()
    wrapped = {c.args[0].value for c in _calls(pipeline, "_run_stage")
               if c.args and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str)}
    assert {"analytics", "tax", "rebalancing", "risk"} <= wrapped, (
        f"stages not routed through _run_stage: {sorted({'analytics','tax','rebalancing','risk'} - wrapped)}")


@pytest.mark.parametrize("fn_name", ["analyze_portfolio", "analyze_taxes", "compute_rebalancing", "analyze_risk"])
def test_no_stage_function_is_called_outside_the_registry(fn_name):
    """A second, bare call would reintroduce the outage even with the wrapper in place."""
    pipeline = _pipeline_fn()
    bare = []
    for call in _calls(pipeline, fn_name):
        parents = [n for n in ast.walk(pipeline)
                   if isinstance(n, ast.Call) and any(a is call for a in n.args)]
        if not any(isinstance(p.func, ast.Name) and p.func.id == "_run_stage" for p in parents):
            bare.append(call.lineno)
    assert not bare, f"{fn_name} called outside _run_stage at line(s) {bare}"


def test_the_snapshot_that_went_stale_is_still_written_by_this_lane():
    """Guards the opposite mistake: 'fixing' the symptom by deleting the persistence."""
    _pipeline_fn()
    assert "save_ticker_snapshot_daily(" in SOURCE


def test_a_run_that_dies_still_records_a_fatal_stage():
    """__main__'s except block used to print a traceback and exit — nothing durable."""
    assert '_stage_failed("pipeline", e, fatal=True)' in SOURCE
    assert "_report_stage_failures(" in SOURCE.split('_stage_failed("pipeline", e, fatal=True)')[1]
