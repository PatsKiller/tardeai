"""Owned SOURCE CLI and receipt boundaries; every real dependency is a scratch fake.

COVERS: scripts/health_agent_llm_review.py, scripts/proposal_llm_review_worker.py,
scripts/directive_keyword_enhancer.py, scripts/hermes_cross_source_synthesizer.py,
scripts/multi_tier_trade_reviewer.py, scripts/portfolio_lookthrough_themes.py,
scripts/shadow_batch_generator.py, scripts/hermes_subject_enhance_dispatch.py,
scripts/run_memory_shadow_measure.py, scripts/cio_reactive_cycle.py,
scripts/advisory_outcome_scorer.py, scripts/hermes_maturity_gates.py,
scripts/source_litmus_vs_yahoo.py,
scripts/lib/cio_nightly_reflection.py, scripts/lib/cio_desk_synthesis.py.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Exact legacy arguments remain accepted; --dry-run is an added offline boundary.
CASES = [
    ("scripts/health_agent_llm_review.py", [], ["run_review", "_get_conn"]),
    ("scripts/proposal_llm_review_worker.py", ["--run", "--limit", "2"], ["get_db", "process_one", "_load_env"]),
    ("scripts/directive_keyword_enhancer.py", ["--backfill", "--apply"], ["backfill", "enhance"]),
    ("scripts/hermes_cross_source_synthesizer.py", ["--apply"], ["get_db", "synthesize", "persist_briefs"]),
    ("scripts/multi_tier_trade_reviewer.py", ["--tier", "overnight"], ["run_tier", "_load_env"]),
    ("scripts/multi_tier_trade_reviewer.py", ["--tier", "weekly"], ["run_tier", "_load_env"]),
    ("scripts/multi_tier_trade_reviewer.py", ["--tier", "monthly"], ["run_tier", "_load_env"]),
    ("scripts/portfolio_lookthrough_themes.py", ["--grok"], ["run", "_initialize_state_paths"]),
    ("scripts/shadow_batch_generator.py", ["--run", "--top", "6"], ["run", "status"]),
    ("scripts/hermes_subject_enhance_dispatch.py", ["--apply"], ["load_table", "run_subject", "acquire_dispatch_lock"]),
    ("scripts/run_memory_shadow_measure.py", ["--json"], []),
    ("scripts/cio_reactive_cycle.py", ["--once", "--dispatch"], ["run_once"]),
    ("scripts/advisory_outcome_scorer.py", ["--once", "--max", "7"], ["score_pending_outcomes", "run_outcome_cycle", "_run"]),
    ("scripts/hermes_maturity_gates.py", ["--snapshot"], ["run", "_conn"]),
    ("scripts/source_litmus_vs_yahoo.py", ["--json", "--seed", "6"], ["_db", "_yahoo_closes"]),
    # supervisor_breach_detector.py is not here: train 5 keeps main's data dry run (evaluate, write nothing), which
    # the R11 monitor-fold parity run depends on (tests/test_monitor_fold_coverage_20261011.py,
    # tests/test_refactor_w1_breach_detector_20261010.py pin it). An offline-only preview is an owner decision.
    ("scripts/lib/cio_nightly_reflection.py", [], ["reflect", "materialize_cases", "persist_reflection"]),
    ("scripts/lib/cio_desk_synthesis.py", [], ["generate_desk_synthesis_v1", "collect_desk_inputs"]),
    ("scripts/market_regime_collector.py", ["--apply", "--json"], ["_load_env", "_get_conn", "collect_vix"]),
    ("scripts/sec_fundamentals_ingest.py", ["--apply"], ["_load_env"]),
    ("scripts/opening_intelligence.py", ["--persist", "--render"], []),
]


def forbid(*args, **kwargs):
    raise AssertionError("offline CLI reached a real dependency")


def load(path):
    name = "completion119_" + path.replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("M2_SKIP_DOCKER", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    return tmp_path / "state"


def contents(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def receipt(scratch, lane):
    return json.loads((scratch / "data" / "runtime" / f"{lane}_last.json").read_text())


@pytest.mark.parametrize("path,argv,blocked", CASES)
def test_offline_cli_cannot_reach_real_dependency(path, argv, blocked, monkeypatch, scratch, capsys):
    mod = load(path)
    for name in blocked:
        monkeypatch.setattr(mod, name, forbid)
    before = contents(scratch)
    assert mod.main(argv + ["--dry-run"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert contents(scratch) == before


@pytest.mark.parametrize("path,argv,blocked", CASES)
@pytest.mark.parametrize("unknown", ["--unknown-completion-option", "--dry-ru"])
def test_unknown_and_abbreviated_flags_exit_2_before_work(path, argv, blocked, unknown, monkeypatch, scratch):
    mod = load(path)
    for name in blocked:
        monkeypatch.setattr(mod, name, forbid)
    with pytest.raises(SystemExit) as exc:
        mod.main(argv + [unknown])
    assert exc.value.code == 2
    assert contents(scratch) == {}


@pytest.mark.parametrize("path,first,second", [
    ("scripts/directive_keyword_enhancer.py", ["--label", "Energy"], ["--label", "Semiconductors"]),
    ("scripts/multi_tier_trade_reviewer.py", ["--tier", "weekly"], ["--tier", "monthly"]),
    ("scripts/shadow_batch_generator.py", ["--top", "2"], ["--top", "9"]),
    ("scripts/run_memory_shadow_measure.py", ["--out", "first.json"], ["--out", "second.json"]),
    ("scripts/advisory_outcome_scorer.py", ["--max", "2"], ["--max", "9"]),
])
def test_plan_reflects_requested_inputs(path, first, second, capsys):
    mod = load(path)
    assert mod.main(first + ["--dry-run"]) == 0
    one = capsys.readouterr().out
    assert mod.main(second + ["--dry-run"]) == 0
    assert capsys.readouterr().out != one


@pytest.mark.parametrize("tier", ["overnight", "weekly", "monthly"])
def test_review_legacy_argv_and_failure_preserve_success(tier, monkeypatch, scratch):
    mod = load("scripts/multi_tier_trade_reviewer.py")
    monkeypatch.setattr(mod, "_load_env", lambda: None)
    seen = []

    def fake(t, trade_id, dry_run):
        seen.append((t, trade_id, dry_run))
        return {"trades_reviewed": 1, "results": [{"success": True}]}

    monkeypatch.setattr(mod, "run_tier", fake)
    assert mod.main(["--tier", tier]) == 0
    assert seen == [(tier, None, False)]
    lane = f"multi-tier-trade-reviewer-{tier}"
    good = receipt(scratch, lane)
    assert good["status"] == "ok" and good["exit"] == 0 and good["ok_at"]
    monkeypatch.setattr(mod, "run_tier", lambda *args: {"results": [{"success": False, "error": "fixture failure"}]})
    assert mod.main(["--tier", tier]) == 1
    failed = receipt(scratch, lane)
    assert failed["status"] == "failed" and failed["exit"] == 1
    assert failed["ok_at"] == good["ok_at"]


@pytest.mark.parametrize("path,lane,method,good,bad,argv", [
    ("scripts/hermes_maturity_gates.py", "tradeai-maturity-feeds", "run",
     {"computed_at": "fixture", "overall": 50}, {"error": "DB_UNAVAILABLE"}, ["--snapshot"]),
    ("scripts/lib/cio_nightly_reflection.py", "cio-nightly-reflection", "reflect",
     {"cases_seen": 2, "proposals": []}, None, []),
    ("scripts/advisory_outcome_scorer.py", "advisory-outcome-scorer", "_run",
     (0, {"written": 2}), (1, {"written": 0}), ["--once"]),
])
def test_fake_real_receipt_failure_keeps_ok_at(path, lane, method, good, bad, argv, monkeypatch, scratch):
    mod = load(path)
    monkeypatch.setattr(mod, method, lambda *a, **kw: good)
    assert mod.main(argv) == 0
    previous = receipt(scratch, lane)
    assert previous["status"] == "ok" and previous["ok_at"]
    if bad is None:
        monkeypatch.setattr(mod, method, forbid)
        with pytest.raises(AssertionError):
            mod.main(argv)
    else:
        monkeypatch.setattr(mod, method, lambda *a, **kw: bad)
        assert mod.main(argv) == (0 if lane == "tradeai-maturity-feeds" else 1)
    failed = receipt(scratch, lane)
    assert failed["status"] == "failed" and failed["ok_at"] == previous["ok_at"]


def test_memory_report_write_error_is_failed_and_keeps_previous_receipt(monkeypatch, scratch):
    mod = load("scripts/run_memory_shadow_measure.py")
    fake = types.ModuleType("scripts.lib.agent_memory_shadow_measure")
    fake.run_measure = lambda **kw: {"written_to": "fixture-report", "metrics": {}, "promotion_gate": {}}
    monkeypatch.setitem(sys.modules, "scripts.lib.agent_memory_shadow_measure", fake)
    assert mod.main(["--json"]) == 0
    old = receipt(scratch, "cio-memory-shadow-measure")
    fake.run_measure = lambda **kw: {"write_error": "fixture", "metrics": {}, "promotion_gate": {}}
    assert mod.main(["--json"]) == 1
    result = receipt(scratch, "cio-memory-shadow-measure")
    assert result["status"] == "failed" and result["ok_at"] == old["ok_at"]


def test_synth_no_briefs_and_partial_writes_are_failed_receipts(monkeypatch, scratch):
    mod = load("scripts/hermes_cross_source_synthesizer.py")
    conn = types.SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(mod, "get_db", lambda: conn)
    monkeypatch.setattr(mod, "collect_signal_bundle", lambda c: {"sources": {"fixture": [1]}})
    monkeypatch.setattr(mod, "synthesize", lambda b: [{"topic": "Fixture", "summary": "fixture"}])
    monkeypatch.setattr(mod, "persist_briefs", lambda *a, **kw: {"applied": 1})
    assert mod.main(["--apply"]) == 0
    good = receipt(scratch, "hermes-cross-source-synthesizer")
    monkeypatch.setattr(mod, "persist_briefs", lambda *a, **kw: {"applied": 0})
    assert mod.main(["--apply"]) == 1
    assert receipt(scratch, "hermes-cross-source-synthesizer")["ok_at"] == good["ok_at"]
    monkeypatch.setattr(mod, "synthesize", lambda b: [])
    assert mod.main(["--apply"]) == 1
    assert receipt(scratch, "hermes-cross-source-synthesizer")["status"] == "failed"


def test_keyword_backfill_receipt_and_exact_argv(monkeypatch, scratch):
    mod = load("scripts/directive_keyword_enhancer.py")
    seen = []
    monkeypatch.setattr(mod, "backfill", lambda **kw: seen.append(kw) or [{"id": "fixture"}])
    assert mod.main(["--backfill", "--apply", "--force"]) == 0
    assert seen == [{"apply": True, "force": True}]
    good = receipt(scratch, "directive-keyword-enhancer")
    monkeypatch.setattr(mod, "backfill", forbid)
    with pytest.raises(AssertionError):
        mod.main(["--backfill", "--apply"])
    assert receipt(scratch, "directive-keyword-enhancer")["ok_at"] == good["ok_at"]


def test_litmus_soft_skip_does_not_report_fresh_success(monkeypatch, scratch):
    mod = load("scripts/source_litmus_vs_yahoo.py")
    monkeypatch.setattr(mod, "RECEIPT", scratch / "data/runtime/source_litmus_last_run.json")
    monkeypatch.setattr(mod, "_db", lambda: types.SimpleNamespace(cursor=lambda: None, close=lambda: None))
    monkeypatch.setattr(mod, "_last_session", lambda cur: date(2026, 10, 9))
    monkeypatch.setattr(mod, "_sample", lambda *a: [("AAA", "fixture", 10.0)])
    monkeypatch.setattr(mod, "_weekend_rows", lambda *a: [])
    monkeypatch.setattr(mod, "_yahoo_closes", lambda *a: {"AAA": 10.0})
    assert mod.main(["--json"]) == 0
    good = receipt(scratch, "source-litmus-vs-yahoo")
    monkeypatch.setattr(mod, "_yahoo_closes", lambda *a: {})
    assert mod.main(["--json"]) == 0  # existing anti-flap exit policy retained
    failed = receipt(scratch, "source-litmus-vs-yahoo")
    assert failed["status"] == "failed" and failed["error"] == "REFERENCE_UNAVAILABLE"
    assert failed["ok_at"] == good["ok_at"]


def test_advisory_closed_loop_failure_is_not_clean_success(monkeypatch, scratch):
    mod = load("scripts/advisory_outcome_scorer.py")
    monkeypatch.setattr(mod, "score_pending_outcomes", lambda **kw: {"ok": True, "written": 2})
    monkeypatch.setattr(mod, "run_outcome_cycle", lambda **kw: {"ok": True})
    fake = types.ModuleType("lib.intelligence_lineage")
    fake.observe_overdue_cases = forbid
    fake.rebuild_lineages = forbid
    monkeypatch.setitem(sys.modules, "lib.intelligence_lineage", fake)
    recon = types.ModuleType("lib.cio_reconciliation")
    recon.persist = forbid
    monkeypatch.setitem(sys.modules, "lib.cio_reconciliation", recon)
    assert mod.main(["--once", "--json"]) == 1
    assert receipt(scratch, "advisory-outcome-scorer")["summary"]["closed_loop_ok"] is False


def test_proposal_worker_errors_are_nonzero_and_keep_receipt(monkeypatch, scratch):
    mod = load("scripts/proposal_llm_review_worker.py")
    pipeline = types.ModuleType("pipeline_registry")

    class FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def rows(self, count):
            self.count = count

    pipeline.PipelineRun = FakePipeline
    monkeypatch.setitem(sys.modules, "pipeline_registry", pipeline)
    local = types.ModuleType("local_llm")
    local.warmup_ollama = lambda: True  # synthetic legacy child, never contacts retired runtime
    monkeypatch.setitem(sys.modules, "local_llm", local)
    monkeypatch.setattr(mod, "_load_env", lambda: None)
    monkeypatch.setattr(mod, "get_db", lambda: types.SimpleNamespace(close=lambda: None))
    seen = []

    def queued(conn, **kwargs):
        seen.append(kwargs)
        return [{"proposal_id": 43, "symbol": "AAA"}]

    monkeypatch.setattr(mod, "fetch_queue", queued)
    monkeypatch.setattr(mod, "process_one", lambda *a, **kw: {"proposal_id": 43, "symbol": "AAA", "status": "completed"})
    assert mod.main(["--run", "--limit", "2", "--proposal-id", "43"]) == 0
    assert seen == [{"limit": 2, "proposal_id": 43}]
    good = receipt(scratch, "proposal-llm-review-worker")
    monkeypatch.setattr(mod, "process_one", lambda *a, **kw: {"proposal_id": 43, "symbol": "AAA", "status": "error"})
    assert mod.main(["--run", "--limit", "2"]) == 1
    failed = receipt(scratch, "proposal-llm-review-worker")
    assert failed["exit"] == 1 and failed["ok_at"] == good["ok_at"]


def test_reactive_soft_errors_keep_exit_policy_and_failed_receipt(monkeypatch, scratch):
    mod = load("scripts/cio_reactive_cycle.py")
    import scripts.lib
    monkeypatch.setattr(scripts.lib, "assert_single_import_identity", lambda: None)
    good_result = {"ts": "fixture", "enabled": True, "event_enqueued": [], "event_skipped": [],
                   "goal_enqueue": {}, "dispatch": {}, "errors": []}
    monkeypatch.setattr(mod, "run_once", lambda **kw: good_result)
    assert mod.main(["--once", "--json"]) == 0
    previous = receipt(scratch, "cio-reactive-cycle")
    previous_timer = receipt(scratch, "cio-wake-turn-effects")
    monkeypatch.setattr(mod, "run_once", lambda **kw: {**good_result, "errors": ["enqueue:fixture"]})
    assert mod.main(["--once", "--json"]) == 0  # preserve the explicit existing anti-flap policy
    failed = receipt(scratch, "cio-reactive-cycle")
    assert failed["status"] == "failed" and failed["ok_at"] == previous["ok_at"]
    failed_timer = receipt(scratch, "cio-wake-turn-effects")
    assert failed_timer["status"] == "failed" and failed_timer["ok_at"] == previous_timer["ok_at"]
    monkeypatch.setattr(mod, "run_once", lambda **kw: {**good_result, "errors": ["identity:fixture"]})
    assert mod.main(["--once", "--json"]) == 1
    assert receipt(scratch, "cio-reactive-cycle")["exit"] == 1


def test_desk_fake_run_persists_receipt_and_failure_keeps_ok(monkeypatch, scratch):
    mod = load("scripts/lib/cio_desk_synthesis.py")
    (scratch / "data/cio").mkdir(parents=True)
    monkeypatch.setattr(mod, "_candidate_project_roots", lambda: [scratch])
    monkeypatch.setattr(mod, "generate_desk_synthesis_v1", lambda: {"note": "Fixture memo", "memo_spine_telegram": "Fixture spine"})
    assert mod.main([]) == 0
    previous = receipt(scratch, "cio-desk-memo-regen")
    assert (scratch / "data/cio/cio_desk_note_latest.md").read_text() == "Fixture memo\n"
    monkeypatch.setattr(mod, "generate_desk_synthesis_v1", forbid)
    with pytest.raises(AssertionError):
        mod.main([])
    failed = receipt(scratch, "cio-desk-memo-regen")
    assert failed["status"] == "failed" and failed["ok_at"] == previous["ok_at"]


def test_shadow_read_only_preview_never_writes_status(monkeypatch, scratch):
    mod = load("scripts/shadow_batch_generator.py")
    selection = {"members": [], "by_reason": {}, "est_cost_note": "fixture"}
    for key in ("total_qualifying", "selected", "deferred_by_cap", "starred", "held",
                "catalyst", "material_move", "legacy_buy_side", "legacy_ignore_avoid", "est_lane_calls"):
        selection[key] = 0
    monkeypatch.setattr(mod, "select_targets", lambda top: selection)
    monkeypatch.setattr(mod, "_effective_fresh_hours", lambda hours: 12.0)
    monkeypatch.setattr(mod, "classify_freshness", lambda *a: {"fresh": [], "regenerate": {}})
    monkeypatch.setattr(mod, "_write_status", forbid)
    monkeypatch.setattr(mod, "_generate_one", forbid)
    assert mod.run(top_n=6, dry_run=True)["state"] == "dry_run"
    assert contents(scratch) == {}


@pytest.mark.parametrize("json_flag", [[], ["--json"]])
def test_shadow_lock_and_partial_failure_exit_codes_and_receipts(json_flag, monkeypatch, scratch):
    mod = load("scripts/shadow_batch_generator.py")
    seen = []
    monkeypatch.setattr(mod, "run", lambda **kw: seen.append(kw) or {"state": "complete", "generated": 2, "failed": 0})
    assert mod.main(["--run", "--top", "6", "--force"] + json_flag) == 0
    assert seen == [{"top_n": 6, "force": True}]
    old = receipt(scratch, "shadow-batch-generator-at-15-10")
    monkeypatch.setattr(mod, "run", lambda **kw: {"state": "skipped_locked", "ok": True})
    assert mod.main(["--run"] + json_flag) == 75
    skipped = receipt(scratch, "shadow-batch-generator-at-15-10")
    assert skipped["exit"] == 75 and skipped["error"] == "RUN_SKIPPED_LOCK"
    assert skipped["ok_at"] == old["ok_at"] and skipped["summary"]["lock_skips"] == 1
    monkeypatch.setattr(mod, "run", lambda **kw: {"state": "complete", "generated": 1, "failed": 1})
    assert mod.main(["--run"] + json_flag) == 1
    failed = receipt(scratch, "shadow-batch-generator-at-15-10")
    assert failed["status"] == "failed" and failed["ok_at"] == old["ok_at"]


@pytest.mark.parametrize("outcome", ["LOCK_HELD", "DEFERRED_GUARD"])
def test_dispatch_skip_is_not_fresh_success(outcome, scratch):
    mod = load("scripts/hermes_subject_enhance_dispatch.py")
    real_result = {"as_of": "fixture", "ok": True, "outcome": "COMPLETE", "due": ["fixture"],
                   "runs": [{"subject": "fixture", "outcome": "RAN", "rc": 0}]}
    mod._write_lane_receipt(real_result, 0)
    old = receipt(scratch, "hermes-subject-enhance-dispatch")
    mod._write_lane_receipt({**real_result, "runs": [{"subject": "fixture", "outcome": outcome}]}, 0)
    skipped = receipt(scratch, "hermes-subject-enhance-dispatch")
    assert skipped["status"] == "failed" and skipped["ok_at"] == old["ok_at"]
    assert skipped["exit"] == 0  # legacy dispatcher soft policy, explicitly non-proven receipt
    assert skipped["summary"]["completed"] == 0
    assert skipped["summary"]["lock_skips" if outcome == "LOCK_HELD" else "deferred"] == 1


def test_health_preserves_legacy_and_canonical_receipt_without_fresh_error(monkeypatch, scratch):
    mod = load("scripts/health_agent_llm_review.py")
    monkeypatch.setattr(mod, "run_review", lambda **kw: {"status": "stored", "count": 2})
    assert mod.main([]) == 0
    old = receipt(scratch, "health-agent-llm-review")
    assert receipt(scratch, "health_agent_llm_review")["status"] == "ok"
    monkeypatch.setattr(mod, "run_review", lambda **kw: {"status": "llm_failed"})
    assert mod.main([]) == 1
    for lane in ("health-agent-llm-review", "health_agent_llm_review"):
        result = receipt(scratch, lane)
        assert result["status"] == "failed" and result["exit"] == 1
        assert result["ok_at"]
    assert receipt(scratch, "health-agent-llm-review")["ok_at"] == old["ok_at"]


def test_proposal_still_requires_an_explicit_mode(monkeypatch, scratch):
    mod = load("scripts/proposal_llm_review_worker.py")
    monkeypatch.setattr(mod, "get_db", forbid)
    monkeypatch.setattr(mod, "_load_env", forbid)
    with pytest.raises(SystemExit) as exc:
        mod.main([])
    assert exc.value.code == 2
    assert contents(scratch) == {}
