"""CW2/CW3 lanes (batch 5) write LaneRunReceipt@v2 produced_count and opt into the executor output verdict
(2026-10-15).

Lanes: record-decision-outcome, sync-social-to-intelligence, weekly-incubator-builder (CW2); opening-intelligence-render,
pattern-extractor, wire-advisory-lessons, build-symbol-profiles-at-0-19, hermes-discovery-scorecard,
incubator-rolloff-engine (CW3).

For each lane the REAL entry point runs inside a fake n8n attempt with its DB / provider / network work stubbed; the
test reads the immutable per-attempt receipt and applies the executor's output verdict with the committed contract
and allowlist entry: ``produced`` for a run that wrote, ``empty_allowed`` for an allowed empty run (where the rule
allows one), RUN_FAILED ``empty_output`` for a fatal skip. Hermetic (tests/support/lane_produced_count.py).
"""

from __future__ import annotations

import json
import sys
import types
from contextlib import nullcontext
from datetime import datetime, timezone

import pytest

from tests.support import lane_produced_count as H

LANES = (
    "record-decision-outcome",
    "sync-social-to-intelligence",
    "weekly-incubator-builder",
    "opening-intelligence-render",
    "pattern-extractor",
    "wire-advisory-lessons",
    "build-symbol-profiles-at-0-19",
    "hermes-discovery-scorecard",
    "incubator-rolloff-engine",
)


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_opted_in_with_code_that_writes_produced_count(lane):
    H.assert_opted_in(lane)


def _boom(*a, **k):
    raise RuntimeError("db down")


def _driver_stub(monkeypatch):
    """CI has no psycopg2; the lane modules import it at module level. Stub it only when it is absent (no test here
    opens a connection: every _db/_get_conn is replaced)."""
    try:
        import psycopg2  # noqa: F401
        import psycopg2.extras  # noqa: F401
    except ImportError:
        fake = types.ModuleType("psycopg2")
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = object
        fake.extras = extras
        fake.connect = _boom
        monkeypatch.setitem(sys.modules, "psycopg2", fake)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


# ── record-decision-outcome ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("n,expect", [(3, "produced"), (0, "empty_allowed")])
def test_record_decision_outcome(monkeypatch, tmp_path, n, expect):
    import record_decision_outcome as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "record-decision-outcome")
    monkeypatch.setattr(m, "record_current_decisions", lambda real_only=True: n)
    assert m.main([]) == 0
    H.check(tmp_path, "record-decision-outcome", run_id, produced=n, expect=expect)


def test_record_decision_outcome_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import record_decision_outcome as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "record-decision-outcome")
    monkeypatch.setattr(m, "record_current_decisions", _boom)
    with pytest.raises(RuntimeError):
        m.main([])
    H.check(tmp_path, "record-decision-outcome", run_id, produced=0, expect="empty_output")


# ── sync-social-to-intelligence ───────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def sst(monkeypatch):
    import sync_social_to_intelligence as m

    monkeypatch.setattr(m, "_load_env", lambda: None)
    m._UNIVERSE_ERROR.clear()
    db = types.ModuleType("db_adapter")
    db._get_conn = lambda: object()
    iem = types.ModuleType("intelligence_entity_manager")
    iem.upsert_entity = lambda conn, sym, kind, fields, source=None: True
    report = types.ModuleType("lib.data_source_report")
    report.report_source = lambda *a, **k: None
    for name, mod in (("db_adapter", db), ("intelligence_entity_manager", iem), ("lib.data_source_report", report)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(m, "_fields", lambda r: {})
    return m


@pytest.mark.parametrize("universe,rows,expect,fatal", [
    (["NOC", "LMT"], 2, "produced", None),
    (["NOC"], 0, "empty_output", "upstream_stale"),
    ([], 0, "empty_output", "universe_empty_unexpected"),
])
def test_sync_social_to_intelligence(sst, monkeypatch, tmp_path, universe, rows, expect, fatal):
    run_id = H.attempt_env(monkeypatch, tmp_path, "sync-social-to-intelligence")
    monkeypatch.setattr(sst, "resolve_universe", lambda: list(universe))
    monkeypatch.setattr(sst, "latest_sentiment", lambda conn, syms: [{"symbol": s} for s in syms[:rows]])
    assert sst.main(["--apply"]) == 0
    out = H.check(tmp_path, "sync-social-to-intelligence", run_id, produced=rows, expect=expect)
    if fatal:
        assert out["output_verdict"]["fatal"] == [fatal]


# ── weekly-incubator-builder ──────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def wib(monkeypatch):
    import weekly_incubator_builder as m

    def load_runtime():
        m.PipelineRun = lambda *_a, **_k: nullcontext()

    monkeypatch.setattr(m, "_load_runtime", load_runtime)
    monkeypatch.setattr(m, "PipelineRun", None, raising=False)
    return m


@pytest.mark.parametrize("symbols,matches,expect", [(5, 7, "produced"), (0, 0, "empty_output")])
def test_weekly_incubator_builder(wib, monkeypatch, tmp_path, symbols, matches, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "weekly-incubator-builder")
    monkeypatch.setattr(wib, "_execute", lambda args: {"symbols": symbols, "strategy_matches": matches,
                                                       "rolled_on": matches, "stayed": 0, "total_active": 9})
    assert wib.main(["--run-label", "1900", "--apply"]) == 0
    out = H.check(tmp_path, "weekly-incubator-builder", run_id, produced=matches, expect=expect)
    if not symbols:
        assert out["output_verdict"]["fatal"] == ["no_input_unexpected"]


def test_weekly_incubator_builder_crash_is_a_fatal_skip(wib, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "weekly-incubator-builder")
    monkeypatch.setattr(wib, "_execute", _boom)
    assert wib.main(["--run-label", "1900", "--apply"]) == 1
    H.check(tmp_path, "weekly-incubator-builder", run_id, produced=0, expect="empty_output")


# ── opening-intelligence-render ───────────────────────────────────────────────────────────────────────────────────
def _snapshot(m, bias):
    return {"market_date": "2026-10-15", "captured_at": datetime(2026, 10, 15, 13, 15, tzinfo=timezone.utc).isoformat(),
            "opening_bias": bias, "confidence_state": "LOW", "source_kind": "FUTURES", "evidence": ["ES +0.2%"],
            "conflicts": []}


@pytest.mark.parametrize("bias,produced,expect", [("RISK_ON", 1, "produced"), ("DATA_INSUFFICIENT", 0, "empty_allowed")])
def test_opening_intelligence_render(monkeypatch, tmp_path, bias, produced, expect):
    import opening_intelligence as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "opening-intelligence-render")
    monkeypatch.setattr(m, "SNAPSHOT_DIR", tmp_path / "opening_intelligence")
    monkeypatch.setattr(m, "build_snapshot", lambda: _snapshot(m, bias))
    assert m.main(["--persist", "--render"]) == 0
    assert (tmp_path / "opening_intelligence" / "2026-10-15.jsonl").is_file()  # the snapshot is still appended
    H.check(tmp_path, "opening-intelligence-render", run_id, produced=produced, expect=expect)


def test_opening_intelligence_render_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import opening_intelligence as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "opening-intelligence-render")
    monkeypatch.setattr(m, "build_snapshot", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--persist", "--render"])
    H.check(tmp_path, "opening-intelligence-render", run_id, produced=0, expect="empty_output")


# ── pattern-extractor ─────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("upserted,errors,expect", [(4, 0, "produced"), (0, 0, "empty_allowed"), (0, 1, "empty_output")])
def test_pattern_extractor(monkeypatch, tmp_path, upserted, errors, expect):
    _driver_stub(monkeypatch)
    import pattern_extractor as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "pattern-extractor")
    monkeypatch.setattr(m, "run", lambda min_trades=5, dry_run=False: {
        "patterns_found": upserted, "proven": 0, "killed": 0, "neutral": upserted, "upserted": upserted,
        "errors": errors})
    monkeypatch.setattr(sys, "argv", ["pattern_extractor.py"])
    m.main()
    H.check(tmp_path, "pattern-extractor", run_id, produced=upserted, expect=expect)


# ── wire-advisory-lessons ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def wal(monkeypatch):
    import wire_advisory_lessons as m

    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="ok"))
    return m


def _advisory(i):
    return {"adv_id": i, "lane": "hermes", "symbol": "NOC", "recommendation": "Lesson: cut faster. Grade: B",
            "trigger_reason": f"paper_postmortem:{i}", "trade_id": i, "strategy_id": "swing", "exit_reason": "stop",
            "close_date": "2026-10-14", "pnl": -10.0, "dollar_risk": 20.0, "prop_origin": None, "prop_disc": None}


@pytest.mark.parametrize("n,expect", [(2, "produced"), (0, "empty_allowed")])
def test_wire_advisory_lessons(wal, monkeypatch, tmp_path, n, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "wire-advisory-lessons")
    monkeypatch.setattr(wal, "_db", lambda sql, params=None, fetch="all": (
        [_advisory(i) for i in range(n)] if fetch == "all" else {"id": 1}))
    assert wal.main([]) == 0
    H.check(tmp_path, "wire-advisory-lessons", run_id, produced=n, expect=expect)


def test_wire_advisory_lessons_crash_is_a_fatal_skip(wal, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "wire-advisory-lessons")
    monkeypatch.setattr(wal, "_db", _boom)
    with pytest.raises(RuntimeError):
        wal.main([])
    H.check(tmp_path, "wire-advisory-lessons", run_id, produced=0, expect="empty_output")


# ── build-symbol-profiles-at-0-19 ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("updated,checked,expect", [(3, 3, "produced"), (0, 0, "empty_allowed")])
def test_build_symbol_profiles(monkeypatch, tmp_path, updated, checked, expect):
    import build_symbol_profiles as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "build-symbol-profiles-at-0-19")
    monkeypatch.setattr(m, "run", lambda **k: {"updated": updated, "checked": checked, "no_profile": 0,
                                               "rejected": 0})
    assert m.main([]) == 0
    legacy = json.loads((tmp_path / "data/runtime/build_symbol_profiles_last.json").read_text())
    assert legacy["schema"] == "LaneRunReceipt@v1"  # the legacy CLI receipt is unchanged
    out = H.check(tmp_path, "build-symbol-profiles-at-0-19", run_id, produced=updated, expect=expect)
    if not checked:
        assert out["output_verdict"]["empty_reason"] == "nothing_due"


def test_build_symbol_profiles_work_but_nothing_landed_is_empty_output(monkeypatch, tmp_path):
    import build_symbol_profiles as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "build-symbol-profiles-at-0-19")
    monkeypatch.setattr(m, "run", lambda **k: {"updated": 0, "checked": 4, "no_profile": 4, "rejected": 0})
    assert m.main([]) == 1
    H.check(tmp_path, "build-symbol-profiles-at-0-19", run_id, produced=0, expect="empty_output")


def test_build_symbol_profiles_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import build_symbol_profiles as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "build-symbol-profiles-at-0-19")
    monkeypatch.setattr(m, "run", _boom)
    with pytest.raises(RuntimeError):
        m.main([])
    H.check(tmp_path, "build-symbol-profiles-at-0-19", run_id, produced=0, expect="empty_output")


# ── hermes-discovery-scorecard ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def hds(monkeypatch, tmp_path):
    import hermes_discovery_scorecard as m

    monkeypatch.setattr(m, "SCORECARD_PATH", tmp_path / "card" / "hermes_discovery_scorecard.json")
    monkeypatch.setattr(m, "build_scorecard", lambda: {"ok": True})
    monkeypatch.setattr(m, "write_outcome_feed", lambda card: tmp_path / "card" / "feed.json")
    monkeypatch.setattr(m, "_receipt_summary", lambda card: {"ok": True})
    return m


def test_hermes_discovery_scorecard(hds, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-discovery-scorecard")
    monkeypatch.setattr(hds, "_db_available", lambda: True)
    assert hds.main([]) == 0
    assert hds.SCORECARD_PATH.is_file()
    H.check(tmp_path, "hermes-discovery-scorecard", run_id, produced=2, expect="produced")


def test_hermes_discovery_scorecard_db_down_is_a_fatal_skip(hds, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "hermes-discovery-scorecard")
    monkeypatch.setattr(hds, "_db_available", lambda: False)
    assert hds.main([]) == 1
    H.check(tmp_path, "hermes-discovery-scorecard", run_id, produced=0, expect="empty_output")


# ── incubator-rolloff-engine ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rolled,expect", [(2, "produced"), (0, "empty_allowed")])
def test_incubator_rolloff_engine(monkeypatch, tmp_path, rolled, expect):
    import incubator_rolloff_engine as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "incubator-rolloff-engine")
    monkeypatch.setattr(m, "main", lambda: {"rolled_off": rolled, "still_active": 5, "checked": 5 + rolled,
                                            "mode": "apply"})
    assert m._apply_with_receipt() == 0
    H.check(tmp_path, "incubator-rolloff-engine", run_id, produced=rolled, expect=expect)


def test_incubator_rolloff_engine_failure_is_a_fatal_skip(monkeypatch, tmp_path):
    import incubator_rolloff_engine as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "incubator-rolloff-engine")

    def fail():
        raise SystemExit(1)  # main()'s own failure path (logs, rolls back, sys.exit(1))

    monkeypatch.setattr(m, "main", fail)
    with pytest.raises(SystemExit):
        m._apply_with_receipt()
    H.check(tmp_path, "incubator-rolloff-engine", run_id, produced=0, expect="empty_output")
